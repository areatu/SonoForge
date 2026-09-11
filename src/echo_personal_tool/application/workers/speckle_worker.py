"""Background worker for speckle tracking and strain computation."""

from __future__ import annotations

import dataclasses
import json
import logging
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QRunnable, Signal

from echo_personal_tool.domain.models.speckle import (
    MyocardialZone,
    SpeckleConfig,
    StrainResult,
)
from echo_personal_tool.domain.services.aha_segments import (
    assign_aha_segments,
    compute_gls_from_segments,
)
from echo_personal_tool.domain.services.cardiac_cycle_detector import (
    auto_detect_ed_es,
    build_myocardial_roi_mask,
    detect_ed_es_from_frames,
    estimate_heart_rate_fft,
)
from echo_personal_tool.domain.services.myocardial_zone import sample_kernels_in_zone
from echo_personal_tool.domain.services.quality import assess_tracking_quality
from echo_personal_tool.domain.services.speckle_tracking import (
    build_zone_mask,
    clamp_trajectories_to_wall,
    estimate_global_translations,
    log_reference_max,
    preprocess_echo_frame,
    remove_global_translations,
    track_cine_bidirectional,
    track_cine_incremental,
    track_cine_sequential,
    verification_gate_px,
    verify_trajectory_closure,
)
from echo_personal_tool.domain.services.strain_computation import (
    aggregate_segment_curves,
    arc_contraction_mm,
    arc_length_inflation_mm,
    assess_strain_plausibility,
    compute_gls,
    compute_longitudinal_strain_gl,
    compute_node_longitudinal_curves,
    compute_strain_rate,
    compute_weighted_longitudinal_strain_gl,
    compute_weighted_radial_strain_gl,
    global_curve_from_node_curves,
    peak_in_window,
    smooth_curves_time,
)
from echo_personal_tool.domain.services.strain_metrics import (
    compute_strain_metrics,
    detect_avc_frame,
    estimate_cycle_length_frames,
    time_to_peak_map,
)
from echo_personal_tool.domain.services.tracking_smoothing import (
    apply_motion_model,
    extract_trajectories,
    interpolate_invalid_kernels,
    repair_outlier_columns,
    smooth_trajectories,
)
from echo_personal_tool.domain.services.wall_visibility import measure_wall_visibility

logger = logging.getLogger(__name__)


def _load_full_cine_frames(path: Path | str, media_format: str) -> np.ndarray:
    """Decode the full clip from disk on the worker thread.

    Used when the playback frame cache only holds a sliding window (large
    cines exceed the memory budget and get evicted), so speckle tracking no
    longer depends on the whole clip being pre-cached.

    Returns a stacked (N, H, W) or (N, H, W, C) uint8 array.
    """
    path = Path(path)
    if media_format == "dicom":
        from echo_personal_tool.infrastructure.dicom_session import (
            get_thread_dicom_session,
        )

        session = get_thread_dicom_session()
        session.open(path)
        try:
            all_frames = session.decode_all_frames()
        finally:
            session.release_heavy()
    elif media_format == "mp4":
        import cv2

        cap = cv2.VideoCapture(str(path))
        try:
            all_frames = []
            while True:
                ok, frame = cap.read()
                if not ok or frame is None:
                    break
                all_frames.append(frame)
        finally:
            cap.release()
    else:
        raise RuntimeError(f"Cannot decode full cine from media format {media_format!r}")

    frames_list = list(all_frames)
    if not frames_list:
        raise RuntimeError("No frames decoded from source")
    return np.stack(frames_list)


def _closure_gate_px(config: SpeckleConfig) -> float:
    """Round-trip rejection threshold of the verification pass, in pixels.

    Thin alias of the domain helper so the worker, the harnesses and the pass
    itself can never drift apart (the radius the round trip gets is a floor of
    ``VERIFICATION_SEARCH_RADIUS_PX``, not whatever the selected tracking mode
    happens to use).
    """
    return verification_gate_px(config)


def _embed_closure_matrix(closure: np.ndarray, n_frames: int, phase_start: int) -> np.ndarray:
    """Place the tracked-window closure matrix on the full frame timeline."""
    embedded = np.full((n_frames, closure.shape[1]), np.nan, dtype=np.float64)
    tracked_len = int(min(closure.shape[0], n_frames - phase_start))
    if tracked_len > 0:
        embedded[phase_start : phase_start + tracked_len] = closure[:tracked_len]
    return embedded


# Fewer visible endocardial nodes than this and the arc is no longer a usable
# material line: the visibility filter is then abandoned (and the QC report
# still carries the measured loss), instead of reporting the strain of a stub.
MIN_VISIBLE_NODES = 8


def _invisible_segments(
    kernels: list[TrackingKernel],
    arc_columns: list[int],
    visible_nodes: np.ndarray,
) -> tuple[int, ...]:
    """AHA segments of one view whose nodes are mostly invisible (clinical Q4).

    A segment is treated as not measured when fewer than half of its nodes are
    visible somewhere in the wall along the cycle — a single unlucky node must
    not retire a segment. EACVI/ASE allow one excluded segment per view.
    """
    per_segment: dict[int, list[bool]] = {}
    for node in arc_columns:
        segment = getattr(kernels[node], "aha_segment", None)
        if segment is None:
            continue
        per_segment.setdefault(int(segment), []).append(bool(visible_nodes[node]))
    return tuple(sorted(seg for seg, flags in per_segment.items() if sum(flags) * 2 < len(flags)))


def _arc_ordered_columns(
    indices: list[int],
    kernels: list[TrackingKernel],
    *,
    drop_ends: int = 0,
) -> list[int]:
    """Kernel indices of one layer, ordered along the wall, ends optionally dropped."""
    ordered = sorted(indices, key=lambda i: kernels[i].node_index)
    if drop_ends > 0 and len(ordered) > 2 * drop_ends + 2:
        ordered = ordered[drop_ends:-drop_ends]
    return ordered


def _segment_tracking_quality(
    kernels: list[TrackingKernel],
    ncc_matrix: np.ndarray,
    ed_index: int,
    es_index: int,
    *,
    min_quality: float = 0.3,
) -> dict[int, float]:
    """Mean NCC fidelity per AHA segment over the ED..ES window.

    One number per segment: the mean NCC of the kernels that belong to it
    (all layers), so the bull's-eye can grey out a segment whose speckle was
    not tracked, independently of the strain value it shows.
    """
    if ncc_matrix is None or len(kernels) == 0:
        return {}
    start = int(max(0, min(ed_index, es_index)))
    end = int(min(ncc_matrix.shape[0] - 1, max(ed_index, es_index)))
    if end < start:
        return {}
    window = np.asarray(ncc_matrix[start : end + 1], dtype=np.float64)
    per_kernel = np.nanmean(window, axis=0) if window.size else np.zeros(len(kernels))
    out: dict[int, list[float]] = {}
    for index, kernel in enumerate(kernels):
        segment = int(getattr(kernel, "aha_segment", 0) or 0)
        if segment <= 0:
            continue
        value = float(per_kernel[index]) if index < per_kernel.shape[0] else float("nan")
        if np.isfinite(value):
            out.setdefault(segment, []).append(value)
    return {seg: float(np.mean(values)) for seg, values in out.items() if values}


def _embed_window_curve(
    window_curve: np.ndarray,
    n_frames: int,
    phase_start: int,
    phase_end: int,
) -> np.ndarray:
    full = np.full(n_frames, np.nan, dtype=np.float64)
    n_window = phase_end - phase_start + 1
    if len(window_curve) == n_window:
        full[phase_start : phase_end + 1] = window_curve
    elif len(window_curve) > 0:
        copy_len = min(len(window_curve), n_window)
        full[phase_start : phase_start + copy_len] = window_curve[:copy_len]
    return full


def _resolve_partial_manual_anchors(
    *,
    manual_ed: int | None,
    manual_es: int | None,
    auto_ed: int,
    auto_es: int,
    n_frames: int,
) -> tuple[int, int, str | None]:
    """Combine one-sided manual ED/ES anchors with automatic detection.

    When the user pinned only ED (e.g. an EDV contour) or only ES (an ESV
    contour), that anchor wins over ECG/Simpson/image and the other side keeps
    the automatic candidate. If the auto candidate lands on the wrong side of
    the pinned anchor (or on it), the free side is moved to a default systolic
    span so the returned pair always satisfies ``ed < es`` and ``ed != es``.

    Returns ``(ed, es, source)`` where ``source`` is None for a fully automatic
    pair (caller keeps the mapping source) and "manual_ed+auto"/"manual_es+auto"
    for a partial-manual pair.
    """
    if n_frames <= 1:
        return 0, 0, None
    last = n_frames - 1

    ed = int(np.clip(manual_ed if manual_ed is not None else auto_ed, 0, last))
    es = int(np.clip(manual_es if manual_es is not None else auto_es, 0, last))

    source: str | None = None
    if manual_ed is not None and manual_es is None:
        source = "manual_ed+auto"
    elif manual_es is not None and manual_ed is None:
        source = "manual_es+auto"

    if ed == es:
        if source == "manual_ed+auto" and ed < last:
            es = min(last, ed + max(1, (last - ed) // 3))
        elif source == "manual_es+auto" and ed > 0:
            ed = max(0, es - max(1, es // 3))
        else:
            es = min(last, ed + max(1, (last - ed) // 3))
    elif ed > es:
        # Trust the pinned anchor and re-position the auto side.
        if source == "manual_ed+auto":
            es = min(last, ed + max(1, (last - ed) // 3))
        elif source == "manual_es+auto":
            ed = max(0, es - max(1, es // 3))

    return ed, es, source


def _ecg_avc_frame_local(
    r_peak_result,
    local_ed: int,
    frame_time_ms: float,
    phase_start: int,
    local_window_end: int,
) -> int | None:
    """AVC from the ECG: the end of the T-wave / second heart sound surrogate.

    Without a phonocardiogram the ECG cannot give AVC directly; the interval
    from the R-peak that started this beat to the end of systole is taken as an
    adaptive fraction of the RR interval (~35 % of the cycle, the standard
    approximation used for ES), and only returned when a plausible RR interval
    was actually measured. The caller keeps the source string, so the UI can
    state where the anchor came from instead of implying an ECG measurement.
    """
    if r_peak_result is None:
        return None
    times = np.asarray(getattr(r_peak_result, "r_peak_times_ms", ()), dtype=np.float64)
    if times.size < 2 or frame_time_ms <= 0:
        return None
    rr_ms = float(np.median(np.diff(times)))
    if not np.isfinite(rr_ms) or rr_ms <= 0:
        return None
    # R-peak of the analysed beat → frame index inside the local window
    r_local = [int(round(t / frame_time_ms)) - phase_start for t in times]
    beat_start = min((value for value in r_local if value >= -2), default=None)
    if beat_start is None:
        return None
    avc = int(round(beat_start + 0.35 * rr_ms / frame_time_ms))
    if avc < local_ed or avc > local_window_end:
        return None
    return avc


def _check_ste_geometry(
    zone: MyocardialZone,
    pixel_spacing: tuple[float, float],
) -> tuple[bool, tuple[str, ...]]:
    """Anatomical sanity check of the drawn myocardial zone.

    Catches the cases that make every downstream number meaningless no matter
    how well the blocks matched: a degenerate LV outline (a dot, a straight
    line, a closed ring instead of an apical arc), a wrong scale, or an
    epicardial contour that does not sit outside the endocardium.

    The zone is an *open* apical arc running from one mitral annulus point
    through the apex to the other (see :func:`create_myocardial_zone`), so the
    checks are arc-based: total arc length, annulus chord, apical depth
    (distance from the chord) and the mean endo→epi distance in mm.
    """
    notes: list[str] = []
    try:
        endo = np.asarray(zone.endo_points, dtype=np.float64)
        epi = np.asarray(zone.epi_points, dtype=np.float64)
        row_spacing, col_spacing = (float(pixel_spacing[0]), float(pixel_spacing[1]))
        if not np.isfinite([row_spacing, col_spacing]).all() or row_spacing <= 0 or col_spacing <= 0:
            return False, ("pixel spacing is not calibrated",)

        if endo.ndim != 2 or endo.shape[0] < 8 or not np.all(np.isfinite(endo)):
            return False, ("LV endocardial contour is unusable",)
        if epi.shape != endo.shape or not np.all(np.isfinite(epi)):
            return False, ("LV epicardial contour does not match the endocardium",)

        # Row/col spacing may be anisotropic; scale each axis before measuring.
        endo_mm = endo * np.array([col_spacing, row_spacing])
        epi_mm = epi * np.array([col_spacing, row_spacing])

        segments = np.linalg.norm(np.diff(endo_mm, axis=0), axis=1)
        arc_length = float(np.sum(segments))
        chord = float(np.linalg.norm(endo_mm[-1] - endo_mm[0]))
        chord_dir = endo_mm[-1] - endo_mm[0]
        chord_norm = float(np.linalg.norm(chord_dir))
        if chord_norm > 1e-6:
            normal = np.array([-chord_dir[1], chord_dir[0]]) / chord_norm
            depth = float(np.max(np.abs((endo_mm - endo_mm[0]) @ normal)))
        else:
            depth = arc_length

        # Distance from each epicardial point to the endocardial arc — robust to
        # a hand-drawn epicardium whose node order does not match the endocardium.
        pairwise = np.linalg.norm(epi_mm[:, None, :] - endo_mm[None, :, :], axis=2)
        thickness = float(np.mean(np.min(pairwise, axis=1)))

        if arc_length < 30.0:
            notes.append("LV contour is too short to measure strain")
        elif chord < 10.0:
            notes.append("LV annulus is not defined (contour looks closed)")
        elif depth < 8.0:
            notes.append("LV contour is a straight line without an apex")
        if not notes and not 1.0 <= thickness <= 25.0:
            notes.append("myocardial wall thickness is implausible")
    except Exception:  # noqa: BLE001 — geometry check must never break tracking
        notes.append("LV geometry could not be validated")
    return (not notes), tuple(notes)


class SpeckleTrackingSignals(QObject):
    finished = Signal(object)
    error = Signal(str)
    progress = Signal(int, int)


class SpeckleTrackingWorker(QRunnable):
    def __init__(
        self,
        frames: np.ndarray | None,
        zone: MyocardialZone,
        pixel_spacing: tuple[float, float],
        frame_time_ms: float = 33.3,
        config: SpeckleConfig | None = None,
        config_preset: str = "standard",
        manual_ed: int | None = None,
        manual_es: int | None = None,
        view: str = "A4C",
        ecg_waveform=None,
        simpson_area_curve: tuple[tuple[int, float], ...] = (),
        source_path: Path | str | None = None,
        media_format: str = "dicom",
        # Optional separate path from which a real DICOM ECG waveform is read
        # on this worker thread when ``ecg_waveform`` was not supplied (so a
        # real ECG is available even when the cine came from the frame cache).
        ecg_source_path: Path | str | None = None,
    ) -> None:
        super().__init__()
        self._frames = frames
        self._zone = zone
        self._pixel_spacing = pixel_spacing
        self._frame_time_ms = frame_time_ms
        self._config = config
        self._config_preset = config_preset
        self._manual_ed = manual_ed
        self._manual_es = manual_es
        # Analysed apical view — decides which wall pair the AHA segment ids
        # name (issue #C2). Default A4C keeps old callers working.
        self._view = str(view or "A4C").upper()
        self._ecg_waveform = ecg_waveform
        self._simpson_area_curve = simpson_area_curve
        self._source_path = source_path
        self._media_format = media_format
        self._ecg_source_path = ecg_source_path
        self.signals = SpeckleTrackingSignals()
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            config = self._config or SpeckleConfig.preset_standard()
            if self._frames is None:
                # Full cine is not fully cached (evicted by the memory budget).
                # Decode it from source here on the worker thread instead of
                # forcing the user to reload the whole clip.
                if self._source_path is None:
                    raise RuntimeError("No source available to load the full cine")
                self._frames = _load_full_cine_frames(self._source_path, self._media_format)
            n_frames = int(self._frames.shape[0])

            # Real ECG: prefer an explicitly supplied waveform; otherwise read
            # it from the DICOM source on this worker thread. Kept None when the
            # clip carries no ECG, so the STE window hides the strip (no
            # synthetic placeholder is ever drawn).
            if self._ecg_waveform is None:
                ecg_path = self._ecg_source_path or self._source_path
                if ecg_path is not None and self._media_format == "dicom":
                    try:
                        from echo_personal_tool.infrastructure.dicom_session import (
                            read_ecg_waveform,
                        )

                        self._ecg_waveform = read_ecg_waveform(ecg_path)
                    except Exception:  # noqa: BLE001 — no ECG is not fatal
                        self._ecg_waveform = None

            lv_center = tuple(np.mean(self._zone.endo_points, axis=0).tolist())
            avg_spacing = np.mean(self._pixel_spacing)
            kernel_radius = max(config.kernel_size // 2, 4)
            kernels = sample_kernels_in_zone(
                self._zone,
                kernel_radius=kernel_radius,
            )
            kernels = assign_aha_segments(kernels, lv_center=lv_center, view=self._view)

            manual_ed_given = self._manual_ed is not None
            manual_es_given = self._manual_es is not None
            fully_manual = manual_ed_given and manual_es_given
            logger.info(
                "STE: manual_ed=%s manual_es=%s n_frames=%d ecg=%s",
                self._manual_ed,
                self._manual_es,
                n_frames,
                self._ecg_waveform is not None,
            )
            ed_es_confidence = 0.5
            r_peak_result = None

            if fully_manual:
                global_ed = int(np.clip(self._manual_ed, 0, n_frames - 1))
                global_es = int(np.clip(self._manual_es, 0, n_frames - 1))
                ed_es_source = "manual"
                ed_es_confidence = 1.0
            else:
                # ECG-first policy: use R-peaks when reliable, else Simpson area
                # curve, else image fallback.
                from echo_personal_tool.domain.services.ecg_ed_es_mapper import (
                    detect_ed_es_for_cine,
                    detect_ed_es_from_area_curve,
                )

                def image_fallback() -> tuple[int, int]:
                    return detect_ed_es_from_frames(self._frames, self._zone, config)

                mapping = detect_ed_es_for_cine(
                    self._ecg_waveform,
                    self._frame_time_ms,
                    n_frames,
                    simpson_fallback=lambda: detect_ed_es_from_area_curve(self._simpson_area_curve, n_frames),
                    image_fallback=image_fallback,
                )
                auto_ed = mapping.ed_frame_index
                auto_es = mapping.es_frame_index
                ed_es_source = mapping.source
                r_peak_result = mapping.r_peak_result
                if mapping.r_peak_result is not None:
                    ed_es_confidence = float(mapping.r_peak_result.confidence)
                elif mapping.source == "simpson":
                    ed_es_confidence = 0.8
                else:
                    ed_es_confidence = 0.5

                # One-sided manual anchors: the user pinned one frame (usually
                # the EDV or ESV contour), the other side keeps the automatic
                # detection. A pinned anchor always wins over ECG/Simpson/image
                # so drawn EDV/ESV contours are honoured.
                global_ed, global_es, partial_source = _resolve_partial_manual_anchors(
                    manual_ed=self._manual_ed,
                    manual_es=self._manual_es,
                    auto_ed=auto_ed,
                    auto_es=auto_es,
                    n_frames=n_frames,
                )
                if partial_source is not None:
                    ed_es_source = partial_source
                    ed_es_confidence = 0.8  # manual side is exact, auto side needs review

            # ── Analysis window: a full cardiac cycle, not just ED…ES.
            # Strain after aortic valve closure (post-systolic shortening) and
            # the time-to-peak of every segment are only visible if the tracked
            # window runs to the next end-diastole; the old ED…ES window made
            # both structurally unmeasurable (issue #C10).
            phase_start = min(global_ed, global_es)
            rr_frames = None
            if r_peak_result is not None and len(r_peak_result.r_peak_times_ms) >= 2:
                rr_ms = float(np.median(np.diff(r_peak_result.r_peak_times_ms)))
                if rr_ms > 0:
                    rr_frames = rr_ms / max(self._frame_time_ms, 1e-6)
            heart_rate_for_cycle = 0.0
            try:
                roi = build_myocardial_roi_mask(self._frames.shape[1:], self._zone)
                heart_rate_for_cycle = float(
                    estimate_heart_rate_fft(
                        self._frames,
                        roi_mask=roi,
                        fps=1000.0 / self._frame_time_ms if self._frame_time_ms > 0 else 30.0,
                    )
                )
            except Exception:  # noqa: BLE001 — HR is only a hint for the window length
                heart_rate_for_cycle = 0.0
            cycle_frames = estimate_cycle_length_frames(
                global_ed,
                global_es,
                n_frames,
                heart_rate_bpm=heart_rate_for_cycle,
                frame_time_ms=self._frame_time_ms,
                rr_frames=rr_frames,
            )
            cycle_estimated = rr_frames is None and heart_rate_for_cycle <= 20.0
            phase_end = int(min(global_ed + cycle_frames, n_frames - 1))
            if phase_end <= max(global_ed, global_es):
                # The clip ends at ES — analyse what exists and say so.
                phase_end = max(global_ed, global_es)
            local_ed = global_ed - phase_start
            local_es = global_es - phase_start
            local_window_end = phase_end - phase_start
            logger.info(
                "STE analysis window: ED=%d ES=%d end=%d (%d frames, HR=%.0f bpm, RR=%s, cycle_estimated=%s)",
                global_ed,
                global_es,
                phase_end,
                phase_end - phase_start + 1,
                heart_rate_for_cycle,
                "n/a" if rr_frames is None else f"{rr_frames:.1f}",
                cycle_estimated,
            )
            logger.info(
                "STE: global_ed=%d global_es=%d phase=[%d..%d] tracking_mode=%s",
                global_ed,
                global_es,
                phase_start,
                phase_end,
                config.tracking_mode,
            )

            tracking_frames_raw = self._frames[phase_start : phase_end + 1]

            logger.info("STE: preprocessing frames (CLAHE + log)")
            log_ref = log_reference_max(tracking_frames_raw)
            preprocessed = np.stack(
                [
                    preprocess_echo_frame(tracking_frames_raw[i], log_ref_max=log_ref)
                    for i in range(tracking_frames_raw.shape[0])
                ]
            )

            zone_mask = build_zone_mask(self._zone, preprocessed.shape[1:3])
            track_ed_index = local_ed

            self.signals.progress.emit(0, 100)
            wall_thickness_px = int(config.wall_thickness_mm / avg_spacing)
            # Vendor-style border propagation: only well-posed when the window
            # starts at ED and runs to ES (the last frame of the window).
            is_border_mode = bool(
                config.tracking_mode == "border" and local_ed == 0 and local_es == int(preprocessed.shape[0]) - 1
            )
            if is_border_mode:
                tracking_path = "border"
            elif config.tracking_mode == "incremental":
                tracking_path = "incremental"
            elif config.tracking_mode == "sequential":
                tracking_path = "sequential"
            else:
                # Includes the fallback from "border" when the window is not a
                # full ED..ES cycle (manual ES, sub-window, offset ED).
                tracking_path = "bidirectional"
            if tracking_path in ("incremental", "bidirectional"):
                # ED-anchored modes jump from ED to every frame, so the search
                # window must span the full systolic excursion: the annulus
                # descends tens of pixels between ED and ES, and a radius that
                # only covers frame-to-frame motion clips the match near
                # end-systole (silently reporting a *smaller* strain while NCC
                # stays high). The old code only did this for the explicitly
                # selected modes, so the "border" preset silently degraded to
                # bidirectional tracking *with the small radius* whenever the
                # window was not a full cycle (plan §7.5, F9).
                config = dataclasses.replace(
                    config,
                    search_radius=max(config.search_radius, 24),
                )
            border_propagation = None
            if is_border_mode:
                from echo_personal_tool.domain.services.border_tracking import (
                    propagate_wall_borders,
                )

                border_propagation = propagate_wall_borders(
                    preprocessed,
                    self._zone.endo_points,
                    self._zone.epi_points,
                    config,
                )
                tracking_results = None
            elif config.tracking_mode == "incremental":
                tracking_results = track_cine_incremental(
                    preprocessed,
                    kernels,
                    ed_index=track_ed_index,
                    config=config,
                    progress_callback=lambda cur, tot: self.signals.progress.emit(int((cur / max(tot, 1)) * 70), 100),
                    zone_mask=zone_mask,
                    wall_thickness_px=wall_thickness_px,
                )
            elif config.tracking_mode == "sequential":
                # NOTE: no static ED zone_mask here — gating every target match
                # against the ED-frame wall band invalidates endo kernels that
                # correctly follow the contracting wall inward past the ED
                # endo, freezing them at ED positions. Validity is decided by
                # NCC + bidirectional closure; the (relaxed) wall clamp below
                # keeps layer order and stops wild jumps.
                tracking_results = track_cine_sequential(
                    preprocessed,
                    kernels,
                    ed_index=track_ed_index,
                    config=config,
                    progress_callback=lambda cur, tot: self.signals.progress.emit(int((cur / max(tot, 1)) * 70), 100),
                    wall_inward_slack=1.4,
                    wall_outward_slack=0.0,
                )
            else:
                tracking_results = track_cine_bidirectional(
                    preprocessed,
                    kernels,
                    ed_index=track_ed_index,
                    config=config,
                    progress_callback=lambda cur, tot: self.signals.progress.emit(int((cur / max(tot, 1)) * 70), 100),
                )

            if not fully_manual and global_ed == global_es and tracking_results is not None:
                new_local_ed, new_local_es = auto_detect_ed_es(tracking_results, kernels, self._pixel_spacing)
                new_local_ed = int(np.clip(new_local_ed, 0, int(preprocessed.shape[0]) - 1))
                new_local_es = int(np.clip(new_local_es, 0, int(preprocessed.shape[0]) - 1))
                global_ed = phase_start + new_local_ed
                global_es = phase_start + new_local_es
                local_ed = new_local_ed
                local_es = new_local_es

            self.signals.progress.emit(70, 100)
            if border_propagation is not None:
                # Border-propagation result: kernels are reconstructed between
                # the propagated endo/epi borders, which are already spatially
                # regularized each frame. Skip independent-kernel interpolation,
                # smoothing, motion-model and the static-band clamp entirely.
                kernels = assign_aha_segments(
                    border_propagation["kernels"],
                    lv_center=tuple(np.mean(self._zone.endo_points, axis=0).tolist()),
                    view=self._view,
                )
                positions = border_propagation["positions"]
                ncc_matrix = border_propagation["ncc"]
                raw_positions = positions.copy()
                smoothed = positions
            else:
                positions, ncc_matrix = extract_trajectories(tracking_results, kernels, ed_index=track_ed_index)
                positions = interpolate_invalid_kernels(
                    positions,
                    ncc_matrix,
                    kernels,
                    config.ncc_threshold,
                )
                # A match can be well correlated and still land on the wrong
                # speckle patch. Such a column is replaced by the median of its
                # immediate neighbours (plan §7.5, F8): a *median* follows any
                # locally smooth field, including the curved displacement of a
                # rotating ventricle, and the repair is gated on a robust
                # residual scale, so a healthy column is never touched.
                positions, outlier_columns = repair_outlier_columns(
                    positions,
                    kernels,
                    track_ed_index,
                    self._pixel_spacing,
                )
                if outlier_columns.any():
                    logger.info(
                        "STE wall-motion outliers: %d kernel-frames replaced by their neighbour median",
                        int(outlier_columns.sum()),
                    )
                raw_positions = positions.copy()
                if config.global_motion_compensation:
                    translations = estimate_global_translations(tracking_frames_raw, local_ed)
                    positions = remove_global_translations(positions, translations)
                smoothed = smooth_trajectories(positions, ncc_matrix, kernels, config)
                if config.physiology_prior:
                    # Optional physiological push (default OFF): without it,
                    # motion comes only from the NCC matches. A synthetic
                    # inward/outward nudge makes poor matches look plausible but
                    # also fabricates deformation that is not in the image.
                    smoothed = apply_motion_model(
                        smoothed,
                        ncc_matrix,
                        kernels,
                        track_ed_index,
                        config.ncc_threshold,
                    )
                # Wall-band containment (off by default, plan §7.5 F2): the
                # band is the *ED* wall, so a wall that travels further inward
                # than the ED geometry allows (or rotates as a whole) is pulled
                # back — measured as 4-5 pp of lost strain and as probe motion
                # turning into deformation. The phantom is the reference for
                # this decision; the clamp stays available for A/B comparison.
                if config.wall_clamp:
                    smoothed, n_clamped = clamp_trajectories_to_wall(
                        smoothed,
                        kernels,
                        track_ed_index,
                        inward_slack=1.4,
                        outward_slack=0.0,
                    )
                    logger.info("STE containment clamp: %d kernel-frame moves corrected", n_clamped)

            endo_indices = [i for i, k in enumerate(kernels) if k.layer == "endo"]
            epi_indices = [i for i, k in enumerate(kernels) if k.layer == "epi"]
            # The arc integral must walk the wall in order (the strain helper
            # uses the order it is given) and it uses every column: dropping the
            # two annulus-plane columns was only needed while the phantom's
            # annulus band was static (plan §7.5 F2/F8), and with the corrected
            # phantom the two ends are as accurate as the rest of the wall.
            # Round-trip verification of the tracking (clinical review Q6): the
            # finished trajectory — the one the overlay draws and the strain
            # integrates — is matched back to end diastole, node by node and
            # frame by frame, and the miss distance is reported. It runs here
            # rather than inside the tracker so that every tracking mode gets the
            # same verdict and the verdict describes the *smoothed* curve.
            # No zone mask: the mask constrains *tracking* to the myocardial
            # band, while the round trip is a verification of the trajectory and
            # must be able to match back wherever the tissue went (measured:
            # with the static ED mask only 24 % of the endocardial nodes could be
            # verified, without it 100 %).
            closure_matrix = verify_trajectory_closure(
                preprocessed,
                smoothed,
                kernels,
                ed_index=local_ed,
                config=config,
            )
            logger.info(
                "STE verification pass: closure over %d frames x %d kernels",
                closure_matrix.shape[0],
                closure_matrix.shape[1],
            )

            strain_endo_all = _arc_ordered_columns(endo_indices, kernels)
            strain_epi_all = _arc_ordered_columns(epi_indices, kernels)

            # Which tissue is actually in the image? (clinical review Q4) A node
            # that runs out of the sector keeps producing a position (the match
            # locks onto the boundary, where a blank patch even scores NCC 1.0),
            # so the strain must be computed on the visible part of the wall
            # only, and the report has to say how much was dropped.
            n_tracked_frames = int(min(preprocessed.shape[0], smoothed.shape[0]))
            visibility = measure_wall_visibility(
                preprocessed[:n_tracked_frames],
                smoothed[:n_tracked_frames],
                reference_index=int(min(max(local_ed, 0), n_tracked_frames - 1)) if n_tracked_frames else 0,
                kernel_radius=max(1, config.kernel_size // 2),
            )
            visible_nodes = visibility.visible_nodes()
            strain_endo = [i for i in strain_endo_all if visible_nodes[i]]
            strain_epi = [
                column
                for position, column in enumerate(strain_epi_all)
                if position < len(strain_endo_all) and visible_nodes[strain_endo_all[position]]
            ]
            excluded_endo_nodes = [i for i in strain_endo_all if not visible_nodes[i]]
            if len(strain_endo) < MIN_VISIBLE_NODES or len(strain_epi) != len(strain_endo):
                logger.warning(
                    "STE visibility: only %d/%d endocardial nodes visible (epi %d) — keeping the full arc",
                    len(strain_endo),
                    len(strain_endo_all),
                    len(strain_epi),
                )
                strain_endo = strain_endo_all
                strain_epi = strain_epi_all
                excluded_endo_nodes = []
            excluded_segments = _invisible_segments(kernels, strain_endo_all, visible_nodes)
            if excluded_endo_nodes:
                logger.info(
                    "STE visibility: %.1f%% of node-frames invisible; excluded nodes %s (segments %s)",
                    visibility.loss_fraction * 100.0,
                    excluded_endo_nodes,
                    list(excluded_segments),
                )

            # Use NCC weights from ED frame for quality-weighted strain
            ed_ncc = ncc_matrix[local_ed].copy()

            window_long = compute_weighted_longitudinal_strain_gl(
                smoothed, local_ed, self._pixel_spacing, strain_endo, ed_ncc
            )
            # Drift compensation is only meaningful when the tracked window
            # actually closes back to a diastolic baseline (i.e. the window
            # extends past end-systole into the next cycle). For the typical
            # systolic window ED..ES the strain at ES is the systolic peak and
            # must NOT be forced back to zero — doing so erases the measured
            # deformation (issue #3). Skip it and report drift honestly.
            # Drift policy (issue #C10): the residual baseline offset is
            # *measured* on the whole-cycle curve and reported as a number. The
            # curve itself is no longer detached from ED/ES by a linear ramp —
            # that correction moved every value of the curve (including the
            # systolic peak the report depends on) by an amount the user never
            # saw. ``apply_drift_compensation`` stays available for callers who
            # explicitly ask for a detrended curve.
            drift_applied = False

            longitudinal = _embed_window_curve(window_long, n_frames, phase_start, phase_end)

            n_pairs = min(len(strain_endo), len(strain_epi))
            if n_pairs > 0:
                window_radial = compute_weighted_radial_strain_gl(
                    smoothed,
                    local_ed,
                    self._pixel_spacing,
                    strain_endo[:n_pairs],
                    strain_epi[:n_pairs],
                    ed_ncc,
                )
                radial = _embed_window_curve(window_radial, n_frames, phase_start, phase_end)
            else:
                radial = np.full(n_frames, np.nan)

            self.signals.progress.emit(80, 100)
            fps = 1000.0 / self._frame_time_ms if self._frame_time_ms > 0 else 30.0
            roi_mask = build_myocardial_roi_mask(self._frames.shape[1:], self._zone)
            heart_rate = estimate_heart_rate_fft(self._frames, roi_mask=roi_mask, fps=fps)

            frame_times = [self._frame_time_ms] * n_frames
            strain_rate = compute_strain_rate(np.nan_to_num(longitudinal, nan=0.0), frame_times)

            per_kernel = np.zeros(len(kernels), dtype=np.float64)
            ed_contour = None
            es_contour = None
            tracked_ed_positions = None
            tracked_es_positions = None
            es_ncc = None
            es_valid = None
            node_curves_full: np.ndarray | None = None
            window_node_curves: np.ndarray | None = None
            node_indices: tuple[int, ...] = ()
            segment_curves: dict[int, np.ndarray] = {}
            window_segment_curves: dict[int, np.ndarray] = {}
            consistency_delta = 0.0

            if len(endo_indices) >= 2:
                endo_sorted_all = sorted(endo_indices, key=lambda i: kernels[i].node_index)
                ed_pos = smoothed[local_ed, endo_sorted_all, :]
                es_pos = smoothed[local_es, endo_sorted_all, :]
                ed_contour = ed_pos.copy()
                es_contour = es_pos.copy()
                # Node and segment curves live on the same visible node set as
                # the global curve, so the cross-check between them stays a
                # comparison of the same measurement.
                endo_sorted = [i for i in endo_sorted_all if visible_nodes[i]]
                if len(endo_sorted) < MIN_VISIBLE_NODES:
                    endo_sorted = endo_sorted_all

                # Single strain definition (issue #C3): every node owns the
                # Green–Lagrange strain of the sub-arc through it and its two
                # neighbours, instead of two neighbouring nodes sharing the
                # strain of one pair. Segment curves are then the weighted mean
                # of their node curves *in the same frame*, which is the
                # EACVI/ASE-compatible way to aggregate; peaks are read from
                # those curves, never averaged across different instants.
                window_node_curves = compute_node_longitudinal_curves(
                    smoothed[:, endo_sorted, :],
                    local_ed,
                    self._pixel_spacing,
                )
                # Metrics are read from a temporally filtered curve: peaks of a
                # raw per-frame signal are noise-biased (see smooth_curves_time).
                window_node_curves = smooth_curves_time(
                    window_node_curves,
                    window=int(config.curve_smoothing_frames),
                    polyorder=2,
                )
                node_curves_full = np.full((n_frames, len(endo_sorted)), np.nan, dtype=np.float64)
                window_len = phase_end - phase_start + 1
                tracked_len = int(min(window_node_curves.shape[0], window_len))
                if tracked_len != window_len:
                    logger.warning(
                        "STE: tracker returned %d frames for a %d-frame analysis window — using the frames that exist",
                        window_node_curves.shape[0],
                        window_len,
                    )
                node_curves_full[phase_start : phase_start + tracked_len] = window_node_curves[:tracked_len]
                node_indices = tuple(int(i) for i in endo_sorted)

                window_segment_curves = aggregate_segment_curves(
                    window_node_curves,
                    [kernels[i].aha_segment for i in endo_sorted],
                )
                segment_curves = {
                    int(seg): _embed_window_curve(curve, n_frames, phase_start, phase_end)
                    for seg, curve in window_segment_curves.items()
                }

                ess_by_node = window_node_curves[local_es]
                for position, kernel_index in enumerate(endo_sorted):
                    value = float(ess_by_node[position])
                    per_kernel[kernel_index] = value if np.isfinite(value) else 0.0

                # Definition (A) == definition (B) check: the whole-line curve
                # from the total arc length must agree with the mean of the node
                # curves when the nodes are equi-spaced. The gap is reported as
                # a self-consistency metric instead of being hidden.
                window_node_mean = global_curve_from_node_curves(window_node_curves)
                window_arclength = compute_longitudinal_strain_gl(
                    smoothed[:, endo_sorted, :],
                    local_ed,
                    self._pixel_spacing,
                    list(range(len(endo_sorted))),
                )
                consistency_delta = abs(
                    peak_in_window(window_node_mean, local_ed, local_es)
                    - peak_in_window(window_arclength, local_ed, local_es)
                )

            # ── AVC (aortic valve closure) and the clinical metrics derived
            # from the *global* curve over the whole cycle: GLS (peak of the
            # global curve, AVC-independent), ESS (value at AVC), time to peak,
            # post-systolic index and the measured baseline drift.
            avc_frame, avc_source, avc_confidence = detect_avc_frame(
                ed_frame=local_ed,
                es_frame=local_es,
                strain_curve=window_long,
                ecg_avc_frame=_ecg_avc_frame_local(
                    r_peak_result,
                    local_ed,
                    self._frame_time_ms,
                    phase_start,
                    local_window_end,
                ),
                area_curve=tuple(
                    (int(frame) - phase_start, float(area))
                    for frame, area in (self._simpson_area_curve or ())
                    if frame is not None
                ),
                search_end=local_window_end,
            )
            global_metrics = compute_strain_metrics(
                window_long,
                ed_index=local_ed,
                avc_index=avc_frame,
                window_end=local_window_end,
                frame_time_ms=self._frame_time_ms,
            )
            segment_metrics = {
                seg: compute_strain_metrics(
                    curve,
                    ed_index=local_ed,
                    avc_index=avc_frame,
                    window_end=local_window_end,
                    frame_time_ms=self._frame_time_ms,
                )
                for seg, curve in window_segment_curves.items()
            }
            segment_ttp = time_to_peak_map(
                window_segment_curves,
                ed_index=local_ed,
                avc_index=avc_frame,
                window_end=local_window_end,
                frame_time_ms=self._frame_time_ms,
            )
            logger.info(
                "STE: baseline drift measured as %.2f%% (not forced to zero; config.drift_compensation=%s)",
                float(global_metrics.drift) if np.isfinite(global_metrics.drift) else float("nan"),
                bool(config.drift_compensation),
            )
            logger.info(
                "STE metrics: AVC=%d (source=%s) peak=%.2f%% ESS=%.2f%% TTP=%.0f ms PSI=%.1f%% drift=%.2f%% notes=%s",
                avc_frame + phase_start,
                avc_source,
                global_metrics.peak,
                global_metrics.ess,
                global_metrics.time_to_peak_ms,
                global_metrics.post_systolic_index,
                global_metrics.drift,
                list(global_metrics.notes),
            )

            tracked_ed_positions = smoothed[local_ed].copy()
            tracked_es_positions = smoothed[local_es].copy()
            es_ncc = ncc_matrix[local_es].copy()
            es_valid = es_ncc >= config.ncc_threshold
            gls = compute_gls(window_long, local_ed, local_es)
            quality_slice = ncc_matrix[local_ed : local_es + 1]
            tracking_quality_mean = float(np.mean(quality_slice)) if quality_slice.size else 0.0

            # Segment values come from the *segment curves* of the arc model
            # (phase 1/2): each segment curve is the same-frame weighted mean of
            # its node curves, so the reported peak is the clinical segmental
            # strain. The previous angular path (``compute_aha_segment_strain``
            # over per-kernel end-systolic values) assigned kernels to segments
            # by the angle around the centroid and read a single frame — on the
            # kinematic phantom that produced values like +170 % for a segment
            # whose true strain is −20 % (plan §7.5, F7).
            segment_strain = {
                int(seg): float(metrics.peak) for seg, metrics in segment_metrics.items() if np.isfinite(metrics.peak)
            }
            segment_quality = _segment_tracking_quality(
                kernels,
                ncc_matrix,
                local_ed,
                local_es,
                min_quality=config.min_kernel_quality,
            )

            logger.info(
                "STE segment_strain: %s, segment_quality: %s",
                segment_strain,
                segment_quality,
            )
            logger.info(
                "STE per_kernel (endo only): %s",
                [f"{per_kernel[i]:.1f}" for i in endo_indices],
            )

            n_kernels = len(kernels)

            # Quality gate: filter kernels by NCC quality
            min_quality = config.min_kernel_quality
            es_ncc_for_gate = es_ncc if es_ncc is not None else np.ones(n_kernels)
            quality_mask = es_ncc_for_gate >= min_quality
            n_accepted = int(np.sum(quality_mask))
            n_rejected = n_kernels - n_accepted

            logger.info(
                "STE quality gate: %d/%d kernels accepted (min_quality=%.2f), %d rejected",
                n_accepted,
                n_kernels,
                min_quality,
                n_rejected,
            )

            # Log rejected kernels details
            if n_rejected > 0:
                rejected_indices = np.where(~quality_mask)[0]
                for idx in rejected_indices:
                    k = kernels[idx]
                    logger.info(
                        "  Rejected kernel %d: center=(%.1f,%.1f) layer=%s segment=%d ncc=%.3f",
                        idx,
                        k.center[0],
                        k.center[1],
                        k.layer,
                        k.aha_segment,
                        float(es_ncc_for_gate[idx]),
                    )

            # Clinical GLS: prefer the mean of well-tracked segment strains over
            # the raw curve peak, but only when segment coverage is adequate.
            # GLS = peak of the global strain curve over the analysed cycle
            # (EACVI/ASE: a *global* value, independent of the AVC estimate).
            # The mean of segment peaks remains a cross-check only: per-segment
            # peaks occur at different instants, so their mean is not a global
            # strain and must never become the reported number (issue #C6).
            gls_curve = float(global_metrics.peak) if np.isfinite(global_metrics.peak) else gls
            gls_segments = compute_gls_from_segments(
                segment_strain,
                segment_quality,
                min_quality=config.min_segment_quality,
            )
            # The reported GLS is *always* the peak of the global curve. The
            # previous revision used ``choose_clinical_gls`` here, which
            # replaced the value with the mean of the segment peaks whenever
            # three segments passed quality — contradicting the EACVI/ASE
            # definition (segments peak at different instants) and, with the old
            # angular segments, reporting numbers like +25 % for a −19 % phantom.
            # The segment mean stays available as a cross-check.
            gls, gls_source = gls_curve, "curve"
            logger.info(
                "STE GLS: global curve peak=%.2f%% (source=%s), segment-mean cross-check=%.2f%% (delta %.2f pp)",
                gls,
                gls_source,
                gls_segments,
                abs(gls - gls_segments),
            )
            # Honest QC: NCC fidelity alone can read >90% while the deformation
            # curve is physiologically impossible (issue #3). The status now
            # separates fidelity (did the blocks match?) from validity (is this a
            # defined measurement?) — geometry, coverage of the material line,
            # the fraction of interpolated node-frames and the agreement between
            # the two equivalent global-strain definitions.
            phys_ok, phys_reasons = assess_strain_plausibility(
                longitudinal,
                radial,
                global_ed,
                global_es,
            )
            coverage = n_accepted / n_kernels if n_kernels else 0.0
            window_ncc = ncc_matrix[local_ed : local_es + 1]
            interpolated_fraction = float(np.mean(window_ncc < config.ncc_threshold)) if window_ncc.size else 1.0
            # Round-trip verification summary over the analysed window: how much
            # of the wall the tracker could confirm by matching there and back.
            avg_spacing_mm = float((self._pixel_spacing[0] + self._pixel_spacing[1]) / 2.0)
            window_closure = closure_matrix[local_ed : local_es + 1]
            finite_closure = np.isfinite(window_closure)
            verified_fraction = float(np.mean(finite_closure)) if window_closure.size else 0.0
            unverified_fraction = 1.0 - verified_fraction
            rejected_fraction = (
                float(np.mean(window_closure[finite_closure] > _closure_gate_px(config)))
                if finite_closure.any()
                else 0.0
            )
            closure_median_mm = float(np.nanmedian(window_closure)) * avg_spacing_mm if finite_closure.any() else 0.0
            closure_p95_mm = (
                float(np.nanpercentile(window_closure, 95)) * avg_spacing_mm if finite_closure.any() else 0.0
            )
            logger.info(
                "STE verification: verified %.2f of node-frames, rejected %.2f, closure median %.2f mm, p95 %.2f mm",
                verified_fraction,
                rejected_fraction,
                closure_median_mm,
                closure_p95_mm,
            )
            geometry_ok, geometry_notes = _check_ste_geometry(self._zone, self._pixel_spacing)
            # Metric cross-checks (plan §7.5, F4): the reported GLS must agree
            # with the independent estimates built from the *same* tracking but
            # a different aggregation, and the endocardial line must shorten as
            # a line. These need no ground truth, so they work on a real patient.
            node_ess = (
                window_node_curves[local_es] if window_node_curves is not None else np.array([], dtype=np.float64)
            )
            finite_ess = node_ess[np.isfinite(node_ess)]
            sign_flip_fraction = 0.0
            if finite_ess.size >= 8 and abs(gls) >= 5.0:
                sign_flip_fraction = float(np.mean(finite_ess > 0.5 * abs(gls)))
            estimate_spread_pp = 0.0
            if np.isfinite(gls_segments) and str(gls_source) == "curve":
                estimate_spread_pp = float(abs(gls - gls_segments))
            # Position noise vs the contraction (plan §7.5, F6). A polyline
            # through noisy points is longer than the material line it samples,
            # so the noise bias *shortens* the reported strain while leaving the
            # NCC untouched — the one cross-check that catches "quality 95 %,
            # GLS wrong". It is measured on the pre-smoothing positions.
            noise_mm = 0.0
            noise_to_signal = 0.0
            # The noise estimate describes the *tracking* of the whole material
            # line, so it deliberately uses every endocardial column: tying it
            # to the visibility subset would let a clip whose tracker wandered
            # off the tissue look less noisy than it is (measured at 10 dB).
            if len(strain_endo_all) >= 2:
                noise_mm = arc_length_inflation_mm(raw_positions, smoothed, strain_endo_all, self._pixel_spacing)
                contraction = arc_contraction_mm(
                    smoothed,
                    strain_endo_all,
                    local_ed,
                    self._pixel_spacing,
                    window_end=smoothed.shape[0] - 1,
                )
                # Only meaningful when there is a contraction to measure: a truly
                # akinetic clip has no signal and is judged by the physiology
                # checks, not by this ratio.
                noise_to_signal = float(noise_mm / contraction) if contraction > 0.5 else 0.0
                logger.info(
                    "STE noise check: arc inflation=%.2f mm, contraction=%.2f mm, ratio=%.2f",
                    noise_mm,
                    contraction,
                    noise_to_signal,
                )
            quality = assess_tracking_quality(
                has_curve=bool(np.any(np.isfinite(window_long))),
                fidelity=tracking_quality_mean,
                coverage=coverage,
                interpolated_fraction=interpolated_fraction,
                consistency_delta=consistency_delta,
                physiology_ok=phys_ok,
                physiology_notes=tuple(phys_reasons),
                geometry_ok=geometry_ok,
                geometry_notes=geometry_notes,
                n_segments_measured=len(segment_strain),
                estimate_spread_pp=estimate_spread_pp,
                sign_flip_fraction=sign_flip_fraction,
                noise_to_signal=noise_to_signal,
                visibility_loss=visibility.loss_fraction,
                excluded_nodes=len(excluded_endo_nodes),
                excluded_segments=len(excluded_segments),
                closure_median_mm=closure_median_mm,
                closure_p95_mm=closure_p95_mm,
                rejected_fraction=rejected_fraction,
                unverified_fraction=unverified_fraction,
                gls_pp=gls,
            )
            qc_overall = quality.confidence
            logger.info(
                "STE QC: status=%s confidence=%.2f ncc=%.3f coverage=%.2f interp=%.2f "
                "consistency=%.2f spread=%.2f sign_flip=%.2f noise_ratio=%.2f "
                "visibility=%.2f excluded_segments=%s physiology_ok=%s geometry_ok=%s reasons=%s",
                quality.status,
                quality.confidence,
                tracking_quality_mean,
                coverage,
                interpolated_fraction,
                consistency_delta,
                estimate_spread_pp,
                sign_flip_fraction,
                noise_to_signal,
                visibility.loss_fraction,
                list(excluded_segments),
                phys_ok,
                geometry_ok,
                quality.reasons,
            )
            raw_phase_positions = np.full((n_frames, n_kernels, 2), np.nan)
            tracked_positions_all = np.full((n_frames, n_kernels, 2), np.nan)
            ncc_all_frames = np.full((n_frames, n_kernels), np.nan)
            tracked_len = int(min(smoothed.shape[0], phase_end - phase_start + 1))
            raw_phase_positions[phase_start : phase_start + tracked_len] = raw_positions[:tracked_len]
            tracked_positions_all[phase_start : phase_start + tracked_len] = smoothed[:tracked_len]
            ncc_all_frames[phase_start : phase_start + tracked_len] = ncc_matrix[:tracked_len]

            cumulative = (
                tracked_es_positions - tracked_ed_positions
                if tracked_es_positions is not None and tracked_ed_positions is not None
                else None
            )

            self.signals.progress.emit(100, 100)

            self._dump_ste_debug(
                smoothed=smoothed,
                ncc_matrix=ncc_matrix,
                kernels=kernels,
                ed_contour=ed_contour,
                es_contour=es_contour,
                endo_indices=endo_indices,
                epi_indices=epi_indices,
                longitudinal=longitudinal,
                radial=radial,
                gls=gls,
                global_ed=global_ed,
                global_es=global_es,
                phase_start=phase_start,
                phase_end=phase_end,
                pixel_spacing=self._pixel_spacing,
                config=config,
            )

            last = tracking_results[-1] if tracking_results else None

            # Prepare ECG trace for display (primary lead, matching the main
            # viewer's ECG strip so the strip and the STE window agree).
            ecg_trace_display = None
            if self._ecg_waveform is not None:
                lead = self._ecg_waveform.primary_lead
                lead_index = 0
                if lead is not None and lead in self._ecg_waveform.leads:
                    lead_index = self._ecg_waveform.leads.index(lead)
                ecg_trace_display = self._ecg_waveform.as_voltage_mv(lead_index)

            result = StrainResult(
                longitudinal=longitudinal,
                radial=radial,
                gls=gls,
                strain_rate=strain_rate,
                ed_index=global_ed,
                es_index=global_es,
                heart_rate_bpm=heart_rate,
                phases={"ED": global_ed, "ES": global_es},
                zone=self._zone,
                kernels=kernels,
                last_displacements=last.displacements if last is not None else None,
                last_ncc_scores=es_ncc,
                last_valid_mask=es_valid,
                cumulative_displacements=cumulative,
                per_kernel_longitudinal=per_kernel,
                ed_contour=ed_contour,
                es_contour=es_contour,
                tracked_es_positions=tracked_es_positions,
                tracked_ed_positions=tracked_ed_positions,
                tracked_positions_all=tracked_positions_all,
                view=self._view,
                avc_index=int(avc_frame + phase_start),
                avc_source=avc_source,
                avc_confidence=float(avc_confidence),
                ess=float(global_metrics.ess),
                peak_strain=float(global_metrics.peak),
                gls_peak_frame=(
                    None if global_metrics.peak_frame is None else int(global_metrics.peak_frame + phase_start)
                ),
                time_to_peak_ms=float(global_metrics.time_to_peak_ms),
                post_systolic_index=float(global_metrics.post_systolic_index),
                drift_measured=float(global_metrics.drift),
                is_post_systolic=bool(global_metrics.is_post_systolic),
                segment_metrics=dict(segment_metrics),
                segment_ttp_ms=dict(segment_ttp),
                gls_segment_mean=float(gls_segments),
                qc_estimate_spread_pp=float(estimate_spread_pp),
                qc_sign_flip_fraction=float(sign_flip_fraction),
                qc_noise_to_signal=float(noise_to_signal),
                qc_noise_mm=float(noise_mm),
                qc_visibility_loss=quality.visibility_loss,
                qc_excluded_nodes=quality.excluded_nodes,
                qc_excluded_segments=excluded_segments,
                closure_all_frames=_embed_closure_matrix(closure_matrix, n_frames, phase_start),
                qc_closure_median_mm=quality.closure_median_mm,
                qc_closure_p95_mm=quality.closure_p95_mm,
                qc_rejected_fraction=quality.rejected_fraction,
                qc_unverified_fraction=quality.unverified_fraction,
                analysis_window_end=int(phase_end),
                cycle_estimated=bool(cycle_estimated),
                raw_tracked_positions=raw_phase_positions,
                ncc_all_frames=ncc_all_frames,
                es_ncc_scores=es_ncc,
                es_valid_mask=es_valid,
                segment_strain=segment_strain,
                segment_quality=segment_quality,
                segment_curves=segment_curves,
                node_curves=node_curves_full,
                node_indices=node_indices,
                drift_compensation_applied=drift_applied,
                tracking_quality_mean=tracking_quality_mean,
                qc_score=qc_overall,
                qc_status=quality.status,
                qc_reasons=quality.reasons,
                qc_notes=quality.notes,
                qc_coverage=quality.coverage,
                qc_interpolated_fraction=quality.interpolated_fraction,
                qc_consistency_delta=quality.consistency_delta,
                qc_physiology_ok=phys_ok,
                qc_physiology_reasons=tuple(phys_reasons),
                gls_source=gls_source,
                tracking_window_start=phase_start,
                tracking_window_end=phase_end,
                ncc_threshold=config.ncc_threshold,
                kernels_accepted_count=n_accepted,
                kernels_rejected_count=n_rejected,
                kernels_total_count=n_kernels,
                ecg_waveform=self._ecg_waveform,
                r_peak_result=r_peak_result,
                frame_time_ms=self._frame_time_ms,
                cine_frames=self._frames,
                ed_es_source=ed_es_source,
                ed_es_confidence=ed_es_confidence,
                ed_es_quality="high" if ed_es_confidence >= 0.8 else "review",
                ecg_trace_for_display=ecg_trace_display,
            )
            self.signals.finished.emit(result)

        except Exception as e:
            logger.exception("Speckle tracking failed")
            self.signals.error.emit(str(e))

    def _dump_ste_debug(self, **kwargs) -> None:
        ts = int(time.time())
        out_dir = Path.home() / "ECHO2026_ste_debug"
        out_dir.mkdir(exist_ok=True)
        path = out_dir / f"ste_{ts}.json"

        smoothed = kwargs["smoothed"]
        ncc_matrix = kwargs["ncc_matrix"]
        kernels = kwargs["kernels"]
        ed_contour = kwargs["ed_contour"]
        es_contour = kwargs["es_contour"]
        endo_indices = kwargs["endo_indices"]
        longitudinal = kwargs["longitudinal"]
        gls = kwargs["gls"]
        phase_start = kwargs["phase_start"]
        phase_end = kwargs["phase_end"]
        pixel_spacing = kwargs["pixel_spacing"]
        config = kwargs["config"]

        n_frames, n_kernels, _ = smoothed.shape
        endo_sorted = sorted(endo_indices, key=lambda i: kernels[i].node_index)

        def _arr(a):
            return a.tolist() if a is not None else None

        data = {
            "timestamp": ts,
            "config": {
                "kernel_size": config.kernel_size,
                "search_radius": config.search_radius,
                "ncc_threshold": config.ncc_threshold,
                "min_kernel_quality": config.min_kernel_quality,
                "tracking_mode": config.tracking_mode,
                "bidirectional": config.bidirectional,
            },
            "pixel_spacing_mm": list(pixel_spacing),
            "ed_frame": kwargs["global_ed"],
            "es_frame": kwargs["global_es"],
            "phase_window": [phase_start, phase_end],
            "n_frames_total": n_frames,
            "gls_pct": round(gls, 2),
            "kernel_count": n_kernels,
            "kernels": [
                {"index": i, "center": list(k.center), "layer": k.layer, "node_index": k.node_index}
                for i, k in enumerate(kernels)
            ],
            "ed_contour": _arr(ed_contour),
            "es_contour": _arr(es_contour),
            "positions_per_frame": [smoothed[t].tolist() for t in range(n_frames)],
            "ncc_per_frame": [ncc_matrix[t].tolist() for t in range(n_frames)],
            "longitudinal_strain": _arr(longitudinal),
            "radial_strain": _arr(kwargs["radial"]),
        }

        with open(path, "w") as f:
            json.dump(data, f, indent=1)
        logger.info("STE debug dump: %s", path)
