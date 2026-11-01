"""Background worker for speckle tracking and strain computation."""

from __future__ import annotations

import dataclasses
import json
import logging
import time
import types
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QObject, QRunnable, Signal

from echo_personal_tool.domain.models.speckle import (
    MyocardialZone,
    SpeckleConfig,
    StrainResult,
    TrackingKernel,
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
from echo_personal_tool.domain.services.segment_map import describe_segment_sides
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
    effective_curve_smoothing_window,
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
from echo_personal_tool.infrastructure.safe_diagnostics import log_boundary_failure

logger = logging.getLogger(__name__)

#: Static UI-safe failure code (QH-4a ER-09): the tracking worker never emits
#: raw exception text (paths, frame identifiers, NumPy/SciPy messages).
SPECKLE_FAILURE_CODE = "tracking_failed"


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
            all_frames = []  # type: ignore
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


def _regularization_text(config: SpeckleConfig, window_frames: int) -> str:
    """Declare the regularization that was applied to *this* analysis window.

    The Savitzky-Golay length is forced odd and clamped to the analysis window
    (``effective_curve_smoothing_window``), so a long requested window on a short
    clip is not what the curves actually got — the report has to say so.
    """
    applied = effective_curve_smoothing_window(
        int(config.curve_smoothing_frames),
        int(window_frames),
    )
    curve_part = (
        f"Savitzky-Golay {applied}-frame filter on the strain curves"
        if applied
        else (
            f"no temporal curve filter (requested {int(config.curve_smoothing_frames)} frames, "
            f"analysis window {int(window_frames)} frames)"
        )
    )
    return (
        f"quality-weighted spatial + temporal spline smoothing of trajectories "
        f"(spatial={config.spatial_smoothing:g}, temporal={config.temporal_smoothing:g}), {curve_part}"
    )


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
        state = types.SimpleNamespace()
        try:
            self._run_setup(state)
            self._run_analysis_window(state)
            self._run_preprocess_and_track(state)
            self._run_trajectories(state)
            self._run_strain_curves(state)
            self._run_clinical_metrics(state)
            self._run_quality_gate(state)
            self._run_quality_assessment(state)
            self._emit_tracking_result(state)
        except Exception as exc:  # noqa: BLE001 - safe event only, never to the UI
            log_boundary_failure(logger, "speckle.track", exc, code="unexpected")
            self.signals.error.emit(SPECKLE_FAILURE_CODE)

    def _run_setup(self, state: Any) -> None:
        """Load the cine, sample kernels, and resolve manual or automatic ED/ES anchors."""
        state.config = self._config or SpeckleConfig.preset_standard()
        if self._frames is None:
            # Full cine is not fully cached (evicted by the memory budget).
            # Decode it from source here on the worker thread instead of
            # forcing the user to reload the whole clip.
            if self._source_path is None:
                raise RuntimeError("No source available to load the full cine")
            self._frames = _load_full_cine_frames(self._source_path, self._media_format)
        state.frames = self._frames
        state.n_frames = int(state.frames.shape[0])

        # Real ECG: prefer an explicitly supplied waveform; otherwise read
        # it from the DICOM source on this worker thread. Kept None when the
        # clip carries no ECG, so the STE window hides the strip (no
        # synthetic placeholder is ever drawn).
        if self._ecg_waveform is None:
            state.ecg_path = self._ecg_source_path or self._source_path
            if state.ecg_path is not None and self._media_format == "dicom":
                try:
                    from echo_personal_tool.infrastructure.dicom_session import (
                        read_ecg_waveform,
                    )

                    self._ecg_waveform = read_ecg_waveform(state.ecg_path)
                except Exception:  # noqa: BLE001 — no ECG is not fatal
                    self._ecg_waveform = None

        state.lv_center = tuple(np.mean(self._zone.endo_points, axis=0).tolist())
        state.avg_spacing = np.mean(self._pixel_spacing)
        state.kernel_radius = max(state.config.kernel_size // 2, 4)
        state.kernels = sample_kernels_in_zone(
            self._zone,
            kernel_radius=state.kernel_radius,
        )
        state.kernels = assign_aha_segments(
            state.kernels,
            lv_center=state.lv_center,
            view=self._view,
            flip=state.config.segment_flip,
        )

        state.manual_ed_given = self._manual_ed is not None
        state.manual_es_given = self._manual_es is not None
        state.fully_manual = state.manual_ed_given and state.manual_es_given
        logger.info(
            "STE: manual_ed=%s manual_es=%s n_frames=%d ecg=%s",
            self._manual_ed,
            self._manual_es,
            state.n_frames,
            self._ecg_waveform is not None,
        )
        state.ed_es_confidence = 0.5
        state.r_peak_result = None

        if state.fully_manual:
            state.global_ed = int(np.clip(self._manual_ed, 0, state.n_frames - 1))  # type: ignore
            state.global_es = int(np.clip(self._manual_es, 0, state.n_frames - 1))  # type: ignore
            state.ed_es_source = "manual"
            state.ed_es_confidence = 1.0
        else:
            # ECG-first policy: use R-peaks when reliable, else Simpson area
            # curve, else image fallback.
            from echo_personal_tool.domain.services.ecg_ed_es_mapper import (
                detect_ed_es_for_cine,
                detect_ed_es_from_area_curve,
            )

            def image_fallback() -> tuple[int, int]:
                return detect_ed_es_from_frames(state.frames, self._zone, state.config)

            state.mapping = detect_ed_es_for_cine(
                self._ecg_waveform,
                self._frame_time_ms,
                state.n_frames,
                simpson_fallback=lambda: detect_ed_es_from_area_curve(self._simpson_area_curve, state.n_frames),
                image_fallback=image_fallback,
            )
            state.auto_ed = state.mapping.ed_frame_index
            state.auto_es = state.mapping.es_frame_index
            state.ed_es_source = state.mapping.source
            state.r_peak_result = state.mapping.r_peak_result
            if state.mapping.r_peak_result is not None:
                state.ed_es_confidence = float(state.mapping.r_peak_result.confidence)
            elif state.mapping.source == "simpson":
                state.ed_es_confidence = 0.8
            else:
                state.ed_es_confidence = 0.5

            # One-sided manual anchors: the user pinned one frame (usually
            # the EDV or ESV contour), the other side keeps the automatic
            # detection. A pinned anchor always wins over ECG/Simpson/image
            # so drawn EDV/ESV contours are honoured.
            state.global_ed, state.global_es, state.partial_source = _resolve_partial_manual_anchors(
                manual_ed=self._manual_ed,
                manual_es=self._manual_es,
                auto_ed=state.auto_ed,
                auto_es=state.auto_es,
                n_frames=state.n_frames,
            )
            if state.partial_source is not None:
                state.ed_es_source = state.partial_source
                state.ed_es_confidence = 0.8  # manual side is exact, auto side needs review

    def _run_analysis_window(self, state: Any) -> None:
        """Choose a full-cycle window, including post-systolic motion where available."""
        # Strain after aortic valve closure (post-systolic shortening) and
        # the time-to-peak of every segment are only visible if the tracked
        # window runs to the next end-diastole; the old ED…ES window made
        # both structurally unmeasurable (issue #C10).
        state.phase_start = min(state.global_ed, state.global_es)
        state.rr_frames = None
        if state.r_peak_result is not None and len(state.r_peak_result.r_peak_times_ms) >= 2:
            state.rr_ms = float(np.median(np.diff(state.r_peak_result.r_peak_times_ms)))
            if state.rr_ms > 0:
                state.rr_frames = state.rr_ms / max(self._frame_time_ms, 1e-6)
        state.heart_rate_for_cycle = 0.0
        try:
            state.roi = build_myocardial_roi_mask(state.frames.shape[1:], self._zone)
            state.heart_rate_for_cycle = float(
                estimate_heart_rate_fft(
                    state.frames,
                    roi_mask=state.roi,
                    fps=1000.0 / self._frame_time_ms if self._frame_time_ms > 0 else 30.0,
                )
            )
        except Exception:  # noqa: BLE001 — HR is only a hint for the window length
            state.heart_rate_for_cycle = 0.0
        state.cycle_frames = estimate_cycle_length_frames(
            state.global_ed,
            state.global_es,
            state.n_frames,
            heart_rate_bpm=state.heart_rate_for_cycle,
            frame_time_ms=self._frame_time_ms,
            rr_frames=state.rr_frames,
        )
        state.cycle_estimated = state.rr_frames is None and state.heart_rate_for_cycle <= 20.0
        state.phase_end = int(min(state.global_ed + state.cycle_frames, state.n_frames - 1))
        if state.phase_end <= max(state.global_ed, state.global_es):
            # The clip ends at ES — analyse what exists and say so.
            state.phase_end = max(state.global_ed, state.global_es)
        state.local_ed = state.global_ed - state.phase_start
        state.local_es = state.global_es - state.phase_start
        state.local_window_end = state.phase_end - state.phase_start
        # HR/RR are not logged: they are patient-derived values and already
        # travel with the analysis record (``heart_rate_bpm``); CodeQL reads
        # them as sensitive data in logs, and the log does not need them.
        logger.info(
            "STE analysis window: ED=%d ES=%d end=%d (%d frames, cycle_estimated=%s, rr_available=%s)",
            state.global_ed,
            state.global_es,
            state.phase_end,
            state.phase_end - state.phase_start + 1,
            state.cycle_estimated,
            "ecg" if state.rr_frames is not None else "no",
        )
        logger.info(
            "STE: global_ed=%d global_es=%d phase=[%d..%d] tracking_mode=%s",
            state.global_ed,
            state.global_es,
            state.phase_start,
            state.phase_end,
            state.config.tracking_mode,
        )

    def _run_preprocess_and_track(self, state: Any) -> None:
        """Preprocess analysis frames and dispatch the configured tracking algorithm."""
        state.tracking_frames_raw = state.frames[state.phase_start : state.phase_end + 1]

        logger.info("STE: preprocessing frames (CLAHE + log)")
        state.log_ref = log_reference_max(state.tracking_frames_raw)
        state.preprocessed = np.stack(
            [
                preprocess_echo_frame(state.tracking_frames_raw[state.i], log_ref_max=state.log_ref)
                for state.i in range(state.tracking_frames_raw.shape[0])
            ]
        )

        state.zone_mask = build_zone_mask(self._zone, state.preprocessed.shape[1:3])
        state.track_ed_index = state.local_ed

        self.signals.progress.emit(0, 100)
        state.wall_thickness_px = int(state.config.wall_thickness_mm / state.avg_spacing)
        # Vendor-style border propagation: only well-posed when the window
        # starts at ED and runs to ES (the last frame of the window).
        state.is_border_mode = bool(
            state.config.tracking_mode == "border"
            and state.local_ed == 0
            and state.local_es == int(state.preprocessed.shape[0]) - 1
        )
        if state.is_border_mode:
            state.tracking_path = "border"
        elif state.config.tracking_mode == "incremental":
            state.tracking_path = "incremental"
        elif state.config.tracking_mode == "sequential":
            state.tracking_path = "sequential"
        else:
            # Includes the fallback from "border" when the window is not a
            # full ED..ES cycle (manual ES, sub-window, offset ED).
            state.tracking_path = "bidirectional"
        if state.tracking_path in ("incremental", "bidirectional"):
            # ED-anchored modes jump from ED to every frame, so the search
            # window must span the full systolic excursion: the annulus
            # descends tens of pixels between ED and ES, and a radius that
            # only covers frame-to-frame motion clips the match near
            # end-systole (silently reporting a *smaller* strain while NCC
            # stays high). The old code only did this for the explicitly
            # selected modes, so the "border" preset silently degraded to
            # bidirectional tracking *with the small radius* whenever the
            # window was not a full cycle (plan §7.5, F9).
            state.config = dataclasses.replace(
                state.config,
                search_radius=max(state.config.search_radius, 24),
            )
        state.border_propagation = None
        if state.is_border_mode:
            from echo_personal_tool.domain.services.border_tracking import (
                propagate_wall_borders,
            )

            state.border_propagation = propagate_wall_borders(
                state.preprocessed,
                self._zone.endo_points,
                self._zone.epi_points,
                state.config,
            )
            state.tracking_results = None
        elif state.config.tracking_mode == "incremental":
            state.tracking_results = track_cine_incremental(
                state.preprocessed,
                state.kernels,
                ed_index=state.track_ed_index,
                config=state.config,
                progress_callback=lambda cur, tot: self.signals.progress.emit(int((cur / max(tot, 1)) * 70), 100),
                zone_mask=state.zone_mask,
                wall_thickness_px=state.wall_thickness_px,
            )
        elif state.config.tracking_mode == "sequential":
            # NOTE: no static ED zone_mask here — gating every target match
            # against the ED-frame wall band invalidates endo kernels that
            # correctly follow the contracting wall inward past the ED
            # endo, freezing them at ED positions. Validity is decided by
            # NCC + bidirectional closure; the (relaxed) wall clamp below
            # keeps layer order and stops wild jumps.
            state.tracking_results = track_cine_sequential(
                state.preprocessed,
                state.kernels,
                ed_index=state.track_ed_index,
                config=state.config,
                progress_callback=lambda cur, tot: self.signals.progress.emit(int((cur / max(tot, 1)) * 70), 100),
                wall_inward_slack=1.4,
                wall_outward_slack=0.0,
            )
        else:
            state.tracking_results = track_cine_bidirectional(
                state.preprocessed,
                state.kernels,
                ed_index=state.track_ed_index,
                config=state.config,
                progress_callback=lambda cur, tot: self.signals.progress.emit(int((cur / max(tot, 1)) * 70), 100),
            )

    def _run_trajectories(self, state: Any) -> None:
        """Assemble, smooth, and verify kernel trajectories and wall visibility."""
        if not state.fully_manual and state.global_ed == state.global_es and state.tracking_results is not None:
            state.new_local_ed, state.new_local_es = auto_detect_ed_es(
                state.tracking_results, state.kernels, self._pixel_spacing
            )
            state.new_local_ed = int(np.clip(state.new_local_ed, 0, int(state.preprocessed.shape[0]) - 1))
            state.new_local_es = int(np.clip(state.new_local_es, 0, int(state.preprocessed.shape[0]) - 1))
            state.global_ed = state.phase_start + state.new_local_ed
            state.global_es = state.phase_start + state.new_local_es
            state.local_ed = state.new_local_ed
            state.local_es = state.new_local_es

        self.signals.progress.emit(70, 100)
        if state.border_propagation is not None:
            # Border-propagation result: kernels are reconstructed between
            # the propagated endo/epi borders, which are already spatially
            # regularized each frame. Skip independent-kernel interpolation,
            # smoothing, motion-model and the static-band clamp entirely.
            state.kernels = assign_aha_segments(
                state.border_propagation["kernels"],
                lv_center=tuple(np.mean(self._zone.endo_points, axis=0).tolist()),
                view=self._view,
                flip=state.config.segment_flip,
            )
            state.positions = state.border_propagation["positions"]
            state.ncc_matrix = state.border_propagation["ncc"]
            state.raw_positions = state.positions.copy()
            state.smoothed = state.positions
        else:
            state.positions, state.ncc_matrix = extract_trajectories(
                state.tracking_results, state.kernels, ed_index=state.track_ed_index
            )
            state.positions = interpolate_invalid_kernels(
                state.positions,
                state.ncc_matrix,
                state.kernels,
                state.config.ncc_threshold,
            )
            # A match can be well correlated and still land on the wrong
            # speckle patch. Such a column is replaced by the median of its
            # immediate neighbours (plan §7.5, F8): a *median* follows any
            # locally smooth field, including the curved displacement of a
            # rotating ventricle, and the repair is gated on a robust
            # residual scale, so a healthy column is never touched.
            state.positions, state.outlier_columns = repair_outlier_columns(
                state.positions,
                state.kernels,
                state.track_ed_index,
                self._pixel_spacing,
            )
            if state.outlier_columns.any():
                logger.info(
                    "STE wall-motion outliers: %d kernel-frames replaced by their neighbour median",
                    int(state.outlier_columns.sum()),
                )
            state.raw_positions = state.positions.copy()
            if state.config.global_motion_compensation:
                state.translations = estimate_global_translations(state.tracking_frames_raw, state.local_ed)
                state.positions = remove_global_translations(state.positions, state.translations)
            state.smoothed = smooth_trajectories(state.positions, state.ncc_matrix, state.kernels, state.config)
            if state.config.physiology_prior:
                # Optional physiological push (default OFF): without it,
                # motion comes only from the NCC matches. A synthetic
                # inward/outward nudge makes poor matches look plausible but
                # also fabricates deformation that is not in the image.
                state.smoothed = apply_motion_model(
                    state.smoothed,
                    state.ncc_matrix,
                    state.kernels,
                    state.track_ed_index,
                    state.config.ncc_threshold,
                )
            # Wall-band containment (off by default, plan §7.5 F2): the
            # band is the *ED* wall, so a wall that travels further inward
            # than the ED geometry allows (or rotates as a whole) is pulled
            # back — measured as 4-5 pp of lost strain and as probe motion
            # turning into deformation. The phantom is the reference for
            # this decision; the clamp stays available for A/B comparison.
            if state.config.wall_clamp:
                state.smoothed, state.n_clamped = clamp_trajectories_to_wall(
                    state.smoothed,
                    state.kernels,
                    state.track_ed_index,
                    inward_slack=1.4,
                    outward_slack=0.0,
                )
                logger.info("STE containment clamp: %d kernel-frame moves corrected", state.n_clamped)

        state.endo_indices = [state.i for state.i, state.k in enumerate(state.kernels) if state.k.layer == "endo"]
        state.epi_indices = [state.i for state.i, state.k in enumerate(state.kernels) if state.k.layer == "epi"]
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
        state.closure_matrix = verify_trajectory_closure(
            state.preprocessed,
            state.smoothed,
            state.kernels,
            ed_index=state.local_ed,
            config=state.config,
        )
        logger.info(
            "STE verification pass: closure over %d frames x %d kernels",
            state.closure_matrix.shape[0],
            state.closure_matrix.shape[1],
        )

        state.strain_endo_all = _arc_ordered_columns(state.endo_indices, state.kernels)
        state.strain_epi_all = _arc_ordered_columns(state.epi_indices, state.kernels)

        # Which tissue is actually in the image? (clinical review Q4) A node
        # that runs out of the sector keeps producing a position (the match
        # locks onto the boundary, where a blank patch even scores NCC 1.0),
        # so the strain must be computed on the visible part of the wall
        # only, and the report has to say how much was dropped.
        state.n_tracked_frames = int(min(state.preprocessed.shape[0], state.smoothed.shape[0]))
        state.visibility = measure_wall_visibility(
            state.preprocessed[: state.n_tracked_frames],
            state.smoothed[: state.n_tracked_frames],
            reference_index=int(min(max(state.local_ed, 0), state.n_tracked_frames - 1))
            if state.n_tracked_frames
            else 0,
            kernel_radius=max(1, state.config.kernel_size // 2),
        )
        state.visible_nodes = state.visibility.visible_nodes()
        state.strain_endo = [state.i for state.i in state.strain_endo_all if state.visible_nodes[state.i]]
        state.strain_epi = [
            state.column
            for state.position, state.column in enumerate(state.strain_epi_all)
            if state.position < len(state.strain_endo_all)
            and state.visible_nodes[state.strain_endo_all[state.position]]
        ]
        state.excluded_endo_nodes = [state.i for state.i in state.strain_endo_all if not state.visible_nodes[state.i]]
        if len(state.strain_endo) < MIN_VISIBLE_NODES or len(state.strain_epi) != len(state.strain_endo):
            logger.warning(
                "STE visibility: only %d/%d endocardial nodes visible (epi %d) — keeping the full arc",
                len(state.strain_endo),
                len(state.strain_endo_all),
                len(state.strain_epi),
            )
            state.strain_endo = state.strain_endo_all
            state.strain_epi = state.strain_epi_all
            state.excluded_endo_nodes = []
        state.excluded_segments = _invisible_segments(state.kernels, state.strain_endo_all, state.visible_nodes)
        if state.excluded_endo_nodes:
            logger.info(
                "STE visibility: %.1f%% of node-frames invisible; excluded nodes %s (segments %s)",
                state.visibility.loss_fraction * 100.0,
                state.excluded_endo_nodes,
                list(state.excluded_segments),
            )

        # Use NCC weights from ED frame for quality-weighted strain

    def _run_strain_curves(self, state: Any) -> None:
        """Compute global and segmental longitudinal and radial strain curves."""
        state.ed_ncc = state.ncc_matrix[state.local_ed].copy()

        state.window_long = compute_weighted_longitudinal_strain_gl(
            state.smoothed, state.local_ed, self._pixel_spacing, state.strain_endo, state.ed_ncc
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
        state.drift_applied = False

        state.longitudinal = _embed_window_curve(state.window_long, state.n_frames, state.phase_start, state.phase_end)

        state.n_pairs = min(len(state.strain_endo), len(state.strain_epi))
        if state.n_pairs > 0:
            state.window_radial = compute_weighted_radial_strain_gl(
                state.smoothed,
                state.local_ed,
                self._pixel_spacing,
                state.strain_endo[: state.n_pairs],
                state.strain_epi[: state.n_pairs],
                state.ed_ncc,
            )
            state.radial = _embed_window_curve(state.window_radial, state.n_frames, state.phase_start, state.phase_end)
        else:
            state.radial = np.full(state.n_frames, np.nan)

        self.signals.progress.emit(80, 100)
        state.fps = 1000.0 / self._frame_time_ms if self._frame_time_ms > 0 else 30.0
        state.roi_mask = build_myocardial_roi_mask(state.frames.shape[1:], self._zone)
        state.heart_rate = estimate_heart_rate_fft(state.frames, roi_mask=state.roi_mask, fps=state.fps)

        state.frame_times = [self._frame_time_ms] * state.n_frames
        state.strain_rate = compute_strain_rate(np.nan_to_num(state.longitudinal, nan=0.0), state.frame_times)

        state.per_kernel = np.zeros(len(state.kernels), dtype=np.float64)
        state.ed_contour = None
        state.es_contour = None
        state.tracked_ed_positions = None
        state.tracked_es_positions = None
        state.es_ncc = None
        state.es_valid = None
        state.node_curves_full: np.ndarray | None = None
        state.window_node_curves: np.ndarray | None = None
        state.node_indices: tuple[int, ...] = ()
        state.segment_curves: dict[int, np.ndarray] = {}
        state.window_segment_curves: dict[int, np.ndarray] = {}
        state.consistency_delta = 0.0

        if len(state.endo_indices) >= 2:
            state.endo_sorted_all = sorted(state.endo_indices, key=lambda i: state.kernels[state.i].node_index)
            state.ed_pos = state.smoothed[state.local_ed, state.endo_sorted_all, :]
            state.es_pos = state.smoothed[state.local_es, state.endo_sorted_all, :]
            state.ed_contour = state.ed_pos.copy()
            state.es_contour = state.es_pos.copy()
            # Node and segment curves live on the same visible node set as
            # the global curve, so the cross-check between them stays a
            # comparison of the same measurement.
            state.endo_sorted = [state.i for state.i in state.endo_sorted_all if state.visible_nodes[state.i]]
            if len(state.endo_sorted) < MIN_VISIBLE_NODES:
                state.endo_sorted = state.endo_sorted_all

            # Single strain definition (issue #C3): every node owns the
            # Green–Lagrange strain of the sub-arc through it and its two
            # neighbours, instead of two neighbouring nodes sharing the
            # strain of one pair. Segment curves are then the weighted mean
            # of their node curves *in the same frame*, which is the
            # EACVI/ASE-compatible way to aggregate; peaks are read from
            # those curves, never averaged across different instants.
            state.window_node_curves = compute_node_longitudinal_curves(
                state.smoothed[:, state.endo_sorted, :],
                state.local_ed,
                self._pixel_spacing,
            )
            # Metrics are read from a temporally filtered curve: peaks of a
            # raw per-frame signal are noise-biased (see smooth_curves_time).
            state.window_node_curves = smooth_curves_time(
                state.window_node_curves,
                window=int(state.config.curve_smoothing_frames),
                polyorder=2,
            )
            state.node_curves_full = np.full((state.n_frames, len(state.endo_sorted)), np.nan, dtype=np.float64)
            state.window_len = state.phase_end - state.phase_start + 1
            state.tracked_len = int(min(state.window_node_curves.shape[0], state.window_len))
            if state.tracked_len != state.window_len:
                logger.warning(
                    "STE: tracker returned %d frames for a %d-frame analysis window — using the frames that exist",
                    state.window_node_curves.shape[0],
                    state.window_len,
                )
            state.node_curves_full[state.phase_start : state.phase_start + state.tracked_len] = (
                state.window_node_curves[: state.tracked_len]
            )
            state.node_indices = tuple(int(state.i) for state.i in state.endo_sorted)

            state.window_segment_curves = aggregate_segment_curves(
                state.window_node_curves,
                [state.kernels[state.i].aha_segment for state.i in state.endo_sorted],
            )
            state.segment_curves = {
                int(state.seg): _embed_window_curve(state.curve, state.n_frames, state.phase_start, state.phase_end)
                for state.seg, state.curve in state.window_segment_curves.items()
            }

            state.ess_by_node = state.window_node_curves[state.local_es]
            for state.position, state.kernel_index in enumerate(state.endo_sorted):
                state.value = float(state.ess_by_node[state.position])
                state.per_kernel[state.kernel_index] = state.value if np.isfinite(state.value) else 0.0

            # Definition (A) == definition (B) check: the whole-line curve
            # from the total arc length must agree with the mean of the node
            # curves when the nodes are equi-spaced. The gap is reported as
            # a self-consistency metric instead of being hidden.
            state.window_node_mean = global_curve_from_node_curves(state.window_node_curves)
            state.window_arclength = compute_longitudinal_strain_gl(
                state.smoothed[:, state.endo_sorted, :],
                state.local_ed,
                self._pixel_spacing,
                list(range(len(state.endo_sorted))),
            )
            state.consistency_delta = abs(
                peak_in_window(state.window_node_mean, state.local_ed, state.local_es)
                - peak_in_window(state.window_arclength, state.local_ed, state.local_es)
            )

        # ── AVC (aortic valve closure) and the clinical metrics derived
        # from the *global* curve over the whole cycle: GLS (peak of the
        # global curve, AVC-independent), ESS (value at AVC), time to peak,
        # post-systolic index and the measured baseline drift.

    def _run_clinical_metrics(self, state: Any) -> None:
        """Derive AVC, strain metrics, and per-segment tracking quality."""
        state.avc_frame, state.avc_source, state.avc_confidence = detect_avc_frame(
            ed_frame=state.local_ed,
            es_frame=state.local_es,
            strain_curve=state.window_long,
            ecg_avc_frame=_ecg_avc_frame_local(
                state.r_peak_result,
                state.local_ed,
                self._frame_time_ms,
                state.phase_start,
                state.local_window_end,
            ),
            area_curve=tuple(
                (int(state.frame) - state.phase_start, float(state.area))
                for state.frame, state.area in (self._simpson_area_curve or ())
                if state.frame is not None
            ),
            search_end=state.local_window_end,
        )
        state.global_metrics = compute_strain_metrics(
            state.window_long,
            ed_index=state.local_ed,
            avc_index=state.avc_frame,
            window_end=state.local_window_end,
            frame_time_ms=self._frame_time_ms,
        )
        state.segment_metrics = {
            state.seg: compute_strain_metrics(
                state.curve,
                ed_index=state.local_ed,
                avc_index=state.avc_frame,
                window_end=state.local_window_end,
                frame_time_ms=self._frame_time_ms,
            )
            for state.seg, state.curve in state.window_segment_curves.items()
        }
        state.segment_ttp = time_to_peak_map(
            state.window_segment_curves,
            ed_index=state.local_ed,
            avc_index=state.avc_frame,
            window_end=state.local_window_end,
            frame_time_ms=self._frame_time_ms,
        )
        logger.info(
            "STE: baseline drift measured as %.2f%% (not forced to zero; config.drift_compensation=%s)",
            float(state.global_metrics.drift) if np.isfinite(state.global_metrics.drift) else float("nan"),
            bool(state.config.drift_compensation),
        )
        logger.info(
            "STE metrics: AVC=%d (source=%s) peak=%.2f%% ESS=%.2f%% TTP=%.0f ms PSI=%.1f%% drift=%.2f%% notes=%s",
            state.avc_frame + state.phase_start,
            state.avc_source,
            state.global_metrics.peak,
            state.global_metrics.ess,
            state.global_metrics.time_to_peak_ms,
            state.global_metrics.post_systolic_index,
            state.global_metrics.drift,
            list(state.global_metrics.notes),
        )

        state.tracked_ed_positions = state.smoothed[state.local_ed].copy()
        state.tracked_es_positions = state.smoothed[state.local_es].copy()
        state.es_ncc = state.ncc_matrix[state.local_es].copy()
        state.es_valid = state.es_ncc >= state.config.ncc_threshold
        state.gls = compute_gls(state.window_long, state.local_ed, state.local_es)
        state.quality_slice = state.ncc_matrix[state.local_ed : state.local_es + 1]
        state.tracking_quality_mean = float(np.mean(state.quality_slice)) if state.quality_slice.size else 0.0

        # Segment values come from the *segment curves* of the arc model
        # (phase 1/2): each segment curve is the same-frame weighted mean of
        # its node curves, so the reported peak is the clinical segmental
        # strain. The previous angular path (``compute_aha_segment_strain``
        # over per-kernel end-systolic values) assigned kernels to segments
        # by the angle around the centroid and read a single frame — on the
        # kinematic phantom that produced values like +170 % for a segment
        # whose true strain is −20 % (plan §7.5, F7).
        state.segment_strain = {
            int(state.seg): float(state.metrics.peak)
            for state.seg, state.metrics in state.segment_metrics.items()
            if np.isfinite(state.metrics.peak)
        }
        state.segment_quality = _segment_tracking_quality(
            state.kernels,
            state.ncc_matrix,
            state.local_ed,
            state.local_es,
            min_quality=state.config.min_kernel_quality,
        )

        logger.info(
            "STE segment_strain: %s, segment_quality: %s",
            state.segment_strain,
            state.segment_quality,
        )
        logger.info(
            "STE per_kernel (endo only): %s",
            [f"{state.per_kernel[state.i]:.1f}" for state.i in state.endo_indices],
        )

    def _run_quality_gate(self, state: Any) -> None:
        """Apply the tracking-quality gate and select the clinical GLS value."""
        state.n_kernels = len(state.kernels)

        # Quality gate: filter kernels by NCC quality
        state.min_quality = state.config.min_kernel_quality
        state.es_ncc_for_gate = state.es_ncc if state.es_ncc is not None else np.ones(state.n_kernels)
        state.quality_mask = state.es_ncc_for_gate >= state.min_quality
        state.n_accepted = int(np.sum(state.quality_mask))
        state.n_rejected = state.n_kernels - state.n_accepted

        logger.info(
            "STE quality gate: %d/%d kernels accepted (min_quality=%.2f), %d rejected",
            state.n_accepted,
            state.n_kernels,
            state.min_quality,
            state.n_rejected,
        )

        # Log rejected kernels details
        if state.n_rejected > 0:
            state.rejected_indices = np.where(~state.quality_mask)[0]
            for state.idx in state.rejected_indices:
                state.k = state.kernels[state.idx]
                logger.info(
                    "  Rejected kernel %d: center=(%.1f,%.1f) layer=%s segment=%d ncc=%.3f",
                    state.idx,
                    state.k.center[0],
                    state.k.center[1],
                    state.k.layer,
                    state.k.aha_segment,
                    float(state.es_ncc_for_gate[state.idx]),
                )

        # Clinical GLS: prefer the mean of well-tracked segment strains over
        # the raw curve peak, but only when segment coverage is adequate.
        # GLS = peak of the global strain curve over the analysed cycle
        # (EACVI/ASE: a *global* value, independent of the AVC estimate).
        # The mean of segment peaks remains a cross-check only: per-segment
        # peaks occur at different instants, so their mean is not a global
        # strain and must never become the reported number (issue #C6).
        state.gls_curve = float(state.global_metrics.peak) if np.isfinite(state.global_metrics.peak) else state.gls
        state.gls_segments = compute_gls_from_segments(
            state.segment_strain,
            state.segment_quality,
            min_quality=state.config.min_segment_quality,
        )
        # The reported GLS is *always* the peak of the global curve. The
        # previous revision used ``choose_clinical_gls`` here, which
        # replaced the value with the mean of the segment peaks whenever
        # three segments passed quality — contradicting the EACVI/ASE
        # definition (segments peak at different instants) and, with the old
        # angular segments, reporting numbers like +25 % for a −19 % phantom.
        # The segment mean stays available as a cross-check.
        state.gls, state.gls_source = state.gls_curve, "curve"
        logger.info(
            "STE GLS: global curve peak=%.2f%% (source=%s), segment-mean cross-check=%.2f%% (delta %.2f pp)",
            state.gls,
            state.gls_source,
            state.gls_segments,
            abs(state.gls - state.gls_segments),
        )
        # Honest QC: NCC fidelity alone can read >90% while the deformation
        # curve is physiologically impossible (issue #3). The status now
        # separates fidelity (did the blocks match?) from validity (is this a
        # defined measurement?) — geometry, coverage of the material line,
        # the fraction of interpolated node-frames and the agreement between
        # the two equivalent global-strain definitions.

    def _run_quality_assessment(self, state: Any) -> None:
        """Assess geometry, closure, sampling, and overall tracking quality."""
        state.phys_ok, state.phys_reasons = assess_strain_plausibility(
            state.longitudinal,
            state.radial,
            state.global_ed,
            state.global_es,
        )
        state.coverage = state.n_accepted / state.n_kernels if state.n_kernels else 0.0
        state.window_ncc = state.ncc_matrix[state.local_ed : state.local_es + 1]
        state.interpolated_fraction = (
            float(np.mean(state.window_ncc < state.config.ncc_threshold)) if state.window_ncc.size else 1.0
        )
        # Round-trip verification summary over the analysed window: how much
        # of the wall the tracker could confirm by matching there and back.
        state.avg_spacing_mm = float((self._pixel_spacing[0] + self._pixel_spacing[1]) / 2.0)
        # Sampling extent actually used (Voigt 2015: "explicitly states what
        # is being measured and the spatial extent over which the data is
        # sampled"): the kernel footprint in millimetres and the spacing
        # between neighbouring nodes of the endocardial material line at ED.
        state.sampling_kernel_mm = float(state.config.kernel_size) * state.avg_spacing_mm
        state.sampling_node_spacing_mm = 0.0
        if len(state.strain_endo_all) >= 2:
            state.ed_arc = np.asarray(state.smoothed[state.local_ed][state.strain_endo_all], dtype=np.float64)
            state.steps = np.linalg.norm(np.diff(state.ed_arc, axis=0), axis=1)
            state.finite_steps = state.steps[np.isfinite(state.steps)]
            if state.finite_steps.size:
                state.sampling_node_spacing_mm = float(np.median(state.finite_steps)) * state.avg_spacing_mm
        state.frame_rate_hz = 1000.0 / float(self._frame_time_ms) if float(self._frame_time_ms) > 0 else 0.0
        state.window_closure = state.closure_matrix[state.local_ed : state.local_es + 1]
        state.finite_closure = np.isfinite(state.window_closure)
        state.verified_fraction = float(np.mean(state.finite_closure)) if state.window_closure.size else 0.0
        state.unverified_fraction = 1.0 - state.verified_fraction
        state.rejected_fraction = (
            float(np.mean(state.window_closure[state.finite_closure] > _closure_gate_px(state.config)))
            if state.finite_closure.any()
            else 0.0
        )
        state.closure_median_mm = (
            float(np.nanmedian(state.window_closure)) * state.avg_spacing_mm if state.finite_closure.any() else 0.0
        )
        state.closure_p95_mm = (
            float(np.nanpercentile(state.window_closure, 95)) * state.avg_spacing_mm
            if state.finite_closure.any()
            else 0.0
        )
        logger.info(
            "STE verification: verified %.2f of node-frames, rejected %.2f, closure median %.2f mm, p95 %.2f mm",
            state.verified_fraction,
            state.rejected_fraction,
            state.closure_median_mm,
            state.closure_p95_mm,
        )
        state.geometry_ok, state.geometry_notes = _check_ste_geometry(self._zone, self._pixel_spacing)
        # Metric cross-checks (plan §7.5, F4): the reported GLS must agree
        # with the independent estimates built from the *same* tracking but
        # a different aggregation, and the endocardial line must shorten as
        # a line. These need no ground truth, so they work on a real patient.
        state.node_ess = (
            state.window_node_curves[state.local_es]
            if state.window_node_curves is not None
            else np.array([], dtype=np.float64)
        )
        state.finite_ess = state.node_ess[np.isfinite(state.node_ess)]
        state.sign_flip_fraction = 0.0
        if state.finite_ess.size >= 8 and abs(state.gls) >= 5.0:
            state.sign_flip_fraction = float(np.mean(state.finite_ess > 0.5 * abs(state.gls)))
        state.estimate_spread_pp = 0.0
        if np.isfinite(state.gls_segments) and str(state.gls_source) == "curve":
            state.estimate_spread_pp = float(abs(state.gls - state.gls_segments))
        # Position noise vs the contraction (plan §7.5, F6). A polyline
        # through noisy points is longer than the material line it samples,
        # so the noise bias *shortens* the reported strain while leaving the
        # NCC untouched — the one cross-check that catches "quality 95 %,
        # GLS wrong". It is measured on the pre-smoothing positions.
        state.noise_mm = 0.0
        state.noise_to_signal = 0.0
        # The noise estimate describes the *tracking* of the whole material
        # line, so it deliberately uses every endocardial column: tying it
        # to the visibility subset would let a clip whose tracker wandered
        # off the tissue look less noisy than it is (measured at 10 dB).
        if len(state.strain_endo_all) >= 2:
            state.noise_mm = arc_length_inflation_mm(
                state.raw_positions, state.smoothed, state.strain_endo_all, self._pixel_spacing
            )
            state.contraction = arc_contraction_mm(
                state.smoothed,
                state.strain_endo_all,
                state.local_ed,
                self._pixel_spacing,
                window_end=state.smoothed.shape[0] - 1,
            )
            # Only meaningful when there is a contraction to measure: a truly
            # akinetic clip has no signal and is judged by the physiology
            # checks, not by this ratio.
            state.noise_to_signal = float(state.noise_mm / state.contraction) if state.contraction > 0.5 else 0.0
            logger.info(
                "STE noise check: arc inflation=%.2f mm, contraction=%.2f mm, ratio=%.2f",
                state.noise_mm,
                state.contraction,
                state.noise_to_signal,
            )
        # Frame rate is the one acquisition property the analysis can still
        # comment on (Voigt 2015: 40-80 Hz for motion/deformation at rest,
        # >100 Hz for strain rate). A note, not a gate: the clip is what it
        # is, but the reader has to know.
        state.frame_rate_note: tuple[str, ...] = ()
        if state.frame_rate_hz > 0 and (state.frame_rate_hz < 40.0 or state.frame_rate_hz > 100.0):
            state.frame_rate_note = (
                f"frame rate {state.frame_rate_hz:.0f} Hz is outside the recommended 40-100 Hz for deformation imaging",
            )
        state.quality = assess_tracking_quality(
            has_curve=bool(np.any(np.isfinite(state.window_long))),
            fidelity=state.tracking_quality_mean,
            coverage=state.coverage,
            interpolated_fraction=state.interpolated_fraction,
            consistency_delta=state.consistency_delta,
            physiology_ok=state.phys_ok,
            physiology_notes=tuple(state.phys_reasons),
            geometry_ok=state.geometry_ok,
            geometry_notes=state.geometry_notes,
            n_segments_measured=len(state.segment_strain),
            estimate_spread_pp=state.estimate_spread_pp,
            sign_flip_fraction=state.sign_flip_fraction,
            noise_to_signal=state.noise_to_signal,
            visibility_loss=state.visibility.loss_fraction,
            excluded_nodes=len(state.excluded_endo_nodes),
            excluded_segments=len(state.excluded_segments),
            closure_median_mm=state.closure_median_mm,
            closure_p95_mm=state.closure_p95_mm,
            rejected_fraction=state.rejected_fraction,
            unverified_fraction=state.unverified_fraction,
            gls_pp=state.gls,
        )
        state.qc_overall = state.quality.confidence
        logger.info(
            "STE QC: status=%s confidence=%.2f ncc=%.3f coverage=%.2f interp=%.2f "
            "consistency=%.2f spread=%.2f sign_flip=%.2f noise_ratio=%.2f "
            "visibility=%.2f excluded_segments=%s physiology_ok=%s geometry_ok=%s reasons=%s",
            state.quality.status,
            state.quality.confidence,
            state.tracking_quality_mean,
            state.coverage,
            state.interpolated_fraction,
            state.consistency_delta,
            state.estimate_spread_pp,
            state.sign_flip_fraction,
            state.noise_to_signal,
            state.visibility.loss_fraction,
            list(state.excluded_segments),
            state.phys_ok,
            state.geometry_ok,
            state.quality.reasons,
        )

    def _emit_tracking_result(self, state: Any) -> None:
        """Build the final StrainResult and emit it to the worker signal."""
        state.raw_phase_positions = np.full((state.n_frames, state.n_kernels, 2), np.nan)
        state.tracked_positions_all = np.full((state.n_frames, state.n_kernels, 2), np.nan)
        state.ncc_all_frames = np.full((state.n_frames, state.n_kernels), np.nan)
        state.tracked_len = int(min(state.smoothed.shape[0], state.phase_end - state.phase_start + 1))
        state.raw_phase_positions[state.phase_start : state.phase_start + state.tracked_len] = state.raw_positions[
            : state.tracked_len
        ]
        state.tracked_positions_all[state.phase_start : state.phase_start + state.tracked_len] = state.smoothed[
            : state.tracked_len
        ]
        state.ncc_all_frames[state.phase_start : state.phase_start + state.tracked_len] = state.ncc_matrix[
            : state.tracked_len
        ]

        state.cumulative = (
            state.tracked_es_positions - state.tracked_ed_positions
            if state.tracked_es_positions is not None and state.tracked_ed_positions is not None
            else None
        )

        self.signals.progress.emit(100, 100)

        self._dump_ste_debug(
            smoothed=state.smoothed,
            ncc_matrix=state.ncc_matrix,
            kernels=state.kernels,
            ed_contour=state.ed_contour,
            es_contour=state.es_contour,
            endo_indices=state.endo_indices,
            epi_indices=state.epi_indices,
            longitudinal=state.longitudinal,
            radial=state.radial,
            gls=state.gls,
            global_ed=state.global_ed,
            global_es=state.global_es,
            phase_start=state.phase_start,
            phase_end=state.phase_end,
            pixel_spacing=self._pixel_spacing,
            config=state.config,
        )

        state.last = state.tracking_results[-1] if state.tracking_results else None

        # Prepare ECG trace for display (primary lead, matching the main
        # viewer's ECG strip so the strip and the STE window agree).
        state.ecg_trace_display = None
        if self._ecg_waveform is not None:
            state.lead = self._ecg_waveform.primary_lead
            state.lead_index = 0
            if state.lead is not None and state.lead in self._ecg_waveform.leads:
                state.lead_index = self._ecg_waveform.leads.index(state.lead)
            state.ecg_trace_display = self._ecg_waveform.as_voltage_mv(state.lead_index)

        state.result = StrainResult(
            longitudinal=state.longitudinal,
            radial=state.radial,
            gls=state.gls,
            strain_rate=state.strain_rate,
            ed_index=state.global_ed,
            es_index=state.global_es,
            heart_rate_bpm=state.heart_rate,
            phases={"ED": state.global_ed, "ES": state.global_es},
            zone=self._zone,
            kernels=state.kernels,
            last_displacements=state.last.displacements if state.last is not None else None,
            last_ncc_scores=state.es_ncc,
            last_valid_mask=state.es_valid,
            cumulative_displacements=state.cumulative,
            per_kernel_longitudinal=state.per_kernel,
            ed_contour=state.ed_contour,
            es_contour=state.es_contour,
            tracked_es_positions=state.tracked_es_positions,
            tracked_ed_positions=state.tracked_ed_positions,
            tracked_positions_all=state.tracked_positions_all,
            view=self._view,
            avc_index=int(state.avc_frame + state.phase_start),
            avc_source=state.avc_source,
            avc_confidence=float(state.avc_confidence),
            ess=float(state.global_metrics.ess),
            peak_strain=float(state.global_metrics.peak),
            gls_peak_frame=(
                None
                if state.global_metrics.peak_frame is None
                else int(state.global_metrics.peak_frame + state.phase_start)
            ),
            time_to_peak_ms=float(state.global_metrics.time_to_peak_ms),
            post_systolic_index=float(state.global_metrics.post_systolic_index),
            drift_measured=float(state.global_metrics.drift),
            is_post_systolic=bool(state.global_metrics.is_post_systolic),
            segment_metrics=dict(state.segment_metrics),
            segment_ttp_ms=dict(state.segment_ttp),
            gls_segment_mean=float(state.gls_segments),
            qc_estimate_spread_pp=float(state.estimate_spread_pp),
            qc_sign_flip_fraction=float(state.sign_flip_fraction),
            qc_noise_to_signal=float(state.noise_to_signal),
            qc_noise_mm=float(state.noise_mm),
            qc_visibility_loss=state.quality.visibility_loss,
            qc_excluded_nodes=state.quality.excluded_nodes,
            qc_excluded_segments=state.excluded_segments,
            closure_all_frames=_embed_closure_matrix(state.closure_matrix, state.n_frames, state.phase_start),
            closure_gate_px=_closure_gate_px(state.config),
            sampling_kernel_mm=state.sampling_kernel_mm,
            sampling_node_spacing_mm=state.sampling_node_spacing_mm,
            regularization=_regularization_text(
                state.config,
                state.phase_end - state.phase_start + 1,
            ),
            segment_sides=describe_segment_sides(self._view, flip=state.config.segment_flip),
            segment_flip_applied=bool(state.config.segment_flip),
            translation_compensation_applied=bool(state.config.global_motion_compensation),
            frame_rate_hz=state.frame_rate_hz,
            qc_closure_median_mm=state.quality.closure_median_mm,
            qc_closure_p95_mm=state.quality.closure_p95_mm,
            qc_rejected_fraction=state.quality.rejected_fraction,
            qc_unverified_fraction=state.quality.unverified_fraction,
            analysis_window_end=int(state.phase_end),
            cycle_estimated=bool(state.cycle_estimated),
            raw_tracked_positions=state.raw_phase_positions,
            ncc_all_frames=state.ncc_all_frames,
            es_ncc_scores=state.es_ncc,
            es_valid_mask=state.es_valid,
            segment_strain=state.segment_strain,
            segment_quality=state.segment_quality,
            segment_curves=state.segment_curves,
            node_curves=state.node_curves_full,
            node_indices=state.node_indices,
            drift_compensation_applied=state.drift_applied,
            tracking_quality_mean=state.tracking_quality_mean,
            qc_score=state.qc_overall,
            qc_status=state.quality.status,
            qc_reasons=state.quality.reasons,
            qc_notes=tuple(state.quality.notes) + state.frame_rate_note,
            qc_coverage=state.quality.coverage,
            qc_interpolated_fraction=state.quality.interpolated_fraction,
            qc_consistency_delta=state.quality.consistency_delta,
            qc_physiology_ok=state.phys_ok,
            qc_physiology_reasons=tuple(state.phys_reasons),
            gls_source=state.gls_source,
            tracking_window_start=state.phase_start,
            tracking_window_end=state.phase_end,
            ncc_threshold=state.config.ncc_threshold,
            kernels_accepted_count=state.n_accepted,
            kernels_rejected_count=state.n_rejected,
            kernels_total_count=state.n_kernels,
            ecg_waveform=self._ecg_waveform,
            r_peak_result=state.r_peak_result,
            frame_time_ms=self._frame_time_ms,
            cine_frames=state.frames,
            ed_es_source=state.ed_es_source,
            ed_es_confidence=state.ed_es_confidence,
            ed_es_quality="high" if state.ed_es_confidence >= 0.8 else "review",
            ecg_trace_for_display=state.ecg_trace_display,
        )
        self.signals.finished.emit(state.result)

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
        longitudinal = kwargs["longitudinal"]
        gls = kwargs["gls"]
        phase_start = kwargs["phase_start"]
        phase_end = kwargs["phase_end"]
        pixel_spacing = kwargs["pixel_spacing"]
        config = kwargs["config"]

        n_frames, n_kernels, _ = smoothed.shape

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
        logger.info("STE debug dump written")
