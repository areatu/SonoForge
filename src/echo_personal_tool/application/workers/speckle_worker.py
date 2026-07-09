"""Background worker for speckle tracking and strain computation."""

from __future__ import annotations

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
from echo_personal_tool.domain.services.cardiac_cycle_detector import (
    auto_detect_ed_es,
    build_myocardial_roi_mask,
    detect_ed_es_from_frames,
    estimate_heart_rate_fft,
    _shoelace_area,
)
from echo_personal_tool.domain.services.myocardial_zone import sample_kernels_in_zone
from echo_personal_tool.domain.services.aha_segments import assign_aha_segments, compute_aha_segment_strain, compute_gls_from_segments
from echo_personal_tool.domain.services.speckle_tracking import (
    build_zone_mask,
    preprocess_echo_frame,
    track_cine_bidirectional,
    track_cine_incremental,
)
from echo_personal_tool.domain.services.strain_computation import (
    apply_drift_compensation,
    compute_gls,
    compute_longitudinal_strain_gl,
    compute_radial_strain_gl,
    compute_strain_rate,
    compute_weighted_longitudinal_strain_gl,
    compute_weighted_radial_strain_gl,
)
from echo_personal_tool.domain.services.tracking_smoothing import (
    apply_motion_model,
    extract_trajectories,
    interpolate_invalid_kernels,
    smooth_trajectories,
)

logger = logging.getLogger(__name__)


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


class SpeckleTrackingSignals(QObject):
    finished = Signal(object)
    error = Signal(str)
    progress = Signal(int, int)


class SpeckleTrackingWorker(QRunnable):

    def __init__(
        self,
        frames: np.ndarray,
        zone: MyocardialZone,
        pixel_spacing: tuple[float, float],
        frame_time_ms: float = 33.3,
        config: SpeckleConfig | None = None,
        config_preset: str = "echo_pac",
        manual_ed: int | None = None,
        manual_es: int | None = None,
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
        self.signals = SpeckleTrackingSignals()
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            config = self._config or SpeckleConfig.preset_echo_pac()
            n_frames = int(self._frames.shape[0])

            lv_center = tuple(np.mean(self._zone.endo_points, axis=0).tolist())
            avg_spacing = np.mean(self._pixel_spacing)
            kernel_radius = max(config.kernel_size // 2, 4)
            kernels = sample_kernels_in_zone(
                self._zone, kernel_radius=kernel_radius,
            )
            kernels = assign_aha_segments(kernels, lv_center=lv_center, view="A4C")

            manual_phases = self._manual_ed is not None and self._manual_es is not None
            logger.info(
                "STE: manual_ed=%s manual_es=%s n_frames=%d",
                self._manual_ed, self._manual_es, n_frames,
            )
            if manual_phases:
                global_ed = int(np.clip(self._manual_ed, 0, n_frames - 1))
                global_es = int(np.clip(self._manual_es, 0, n_frames - 1))
            else:
                global_ed, global_es = detect_ed_es_from_frames(
                    self._frames, self._zone, config
                )
                global_ed = int(np.clip(global_ed, 0, n_frames - 1))
                global_es = int(np.clip(global_es, 0, n_frames - 1))

            phase_start = min(global_ed, global_es)
            phase_end = max(global_ed, global_es)
            local_ed = global_ed - phase_start
            local_es = global_es - phase_start
            logger.info(
                "STE: global_ed=%d global_es=%d phase=[%d..%d] tracking_mode=%s",
                global_ed, global_es, phase_start, phase_end, config.tracking_mode,
            )

            tracking_frames_raw = self._frames[phase_start : phase_end + 1]

            logger.info("STE: preprocessing frames (CLAHE + log)")
            preprocessed = np.stack([
                preprocess_echo_frame(tracking_frames_raw[i])
                for i in range(tracking_frames_raw.shape[0])
            ])

            zone_mask = build_zone_mask(self._zone, preprocessed.shape[1:3])
            track_ed_index = local_ed

            self.signals.progress.emit(0, 100)
            wall_thickness_px = int(config.wall_thickness_mm / avg_spacing)
            if config.tracking_mode == "incremental":
                tracking_results = track_cine_incremental(
                    preprocessed,
                    kernels,
                    ed_index=track_ed_index,
                    config=config,
                    progress_callback=lambda cur, tot: self.signals.progress.emit(
                        int((cur / max(tot, 1)) * 70), 100
                    ),
                    zone_mask=zone_mask,
                    wall_thickness_px=wall_thickness_px,
                )
            else:
                tracking_results = track_cine_bidirectional(
                    preprocessed,
                    kernels,
                    ed_index=track_ed_index,
                    config=config,
                    progress_callback=lambda cur, tot: self.signals.progress.emit(
                        int((cur / max(tot, 1)) * 70), 100
                    ),
                )

            if not manual_phases and global_ed == global_es:
                new_local_ed, new_local_es = auto_detect_ed_es(
                    tracking_results, kernels, self._pixel_spacing
                )
                new_local_ed = int(
                    np.clip(new_local_ed, 0, int(preprocessed.shape[0]) - 1)
                )
                new_local_es = int(
                    np.clip(new_local_es, 0, int(preprocessed.shape[0]) - 1)
                )
                global_ed = phase_start + new_local_ed
                global_es = phase_start + new_local_es
                local_ed = new_local_ed
                local_es = new_local_es

            self.signals.progress.emit(70, 100)
            positions, ncc_matrix = extract_trajectories(
                tracking_results, kernels, ed_index=track_ed_index
            )
            positions = interpolate_invalid_kernels(
                positions, ncc_matrix, kernels, config.ncc_threshold,
            )
            smoothed = smooth_trajectories(positions, ncc_matrix, kernels, config)
            smoothed = apply_motion_model(
                smoothed, ncc_matrix, kernels, track_ed_index, config.ncc_threshold,
            )

            endo_indices = [i for i, k in enumerate(kernels) if k.layer == "endo"]
            epi_indices = [i for i, k in enumerate(kernels) if k.layer == "epi"]

            # Use NCC weights from ED frame for quality-weighted strain
            ed_ncc = ncc_matrix[local_ed].copy()

            window_long = compute_weighted_longitudinal_strain_gl(
                smoothed, local_ed, self._pixel_spacing, endo_indices, ed_ncc
            )
            if config.drift_compensation:
                window_long = apply_drift_compensation(
                    window_long, local_ed, local_es
                )

            longitudinal = _embed_window_curve(
                window_long, n_frames, phase_start, phase_end
            )

            n_pairs = min(len(endo_indices), len(epi_indices))
            if n_pairs > 0:
                window_radial = compute_weighted_radial_strain_gl(
                    smoothed,
                    local_ed,
                    self._pixel_spacing,
                    endo_indices[:n_pairs],
                    epi_indices[:n_pairs],
                    ed_ncc,
                )
                radial = _embed_window_curve(
                    window_radial, n_frames, phase_start, phase_end
                )
            else:
                radial = np.full(n_frames, np.nan)

            self.signals.progress.emit(80, 100)
            fps = 1000.0 / self._frame_time_ms if self._frame_time_ms > 0 else 30.0
            roi_mask = build_myocardial_roi_mask(self._frames.shape[1:], self._zone)
            heart_rate = estimate_heart_rate_fft(self._frames, roi_mask=roi_mask, fps=fps)

            frame_times = [self._frame_time_ms] * n_frames
            strain_rate = compute_strain_rate(
                np.nan_to_num(longitudinal, nan=0.0), frame_times
            )

            per_kernel = np.zeros(len(kernels), dtype=np.float64)
            ed_contour = None
            es_contour = None
            tracked_ed_positions = None
            tracked_es_positions = None
            es_ncc = None
            es_valid = None

            if len(endo_indices) >= 2:
                endo_sorted = sorted(endo_indices, key=lambda i: kernels[i].node_index)
                ed_pos = smoothed[local_ed, endo_sorted, :]
                es_pos = smoothed[local_es, endo_sorted, :]
                ed_contour = ed_pos.copy()
                es_contour = es_pos.copy()

                for j in range(len(endo_sorted) - 1):
                    d_init = np.linalg.norm(ed_pos[j + 1] - ed_pos[j]) * avg_spacing
                    d_es = np.linalg.norm(es_pos[j + 1] - es_pos[j]) * avg_spacing
                    if d_init > 1e-6:
                        ratio = d_es / d_init
                        seg_gl = 0.5 * (ratio**2 - 1.0) * 100.0
                        per_kernel[endo_sorted[j]] = seg_gl
                        per_kernel[endo_sorted[j + 1]] = seg_gl

            tracked_ed_positions = smoothed[local_ed].copy()
            tracked_es_positions = smoothed[local_es].copy()
            es_ncc = ncc_matrix[local_es].copy()
            es_valid = es_ncc >= config.ncc_threshold
            gls = compute_gls(window_long, local_ed, local_es)
            quality_slice = ncc_matrix[local_ed : local_es + 1]
            tracking_quality_mean = (
                float(np.mean(quality_slice)) if quality_slice.size else 0.0
            )

            segment_strain, segment_quality = compute_aha_segment_strain(
                per_kernel, kernels, es_ncc if es_ncc is not None else np.ones(len(kernels))
            )

            logger.info(
                "STE segment_strain: %s, segment_quality: %s",
                segment_strain, segment_quality,
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
                n_accepted, n_kernels, min_quality, n_rejected,
            )

            # Log rejected kernels details
            if n_rejected > 0:
                rejected_indices = np.where(~quality_mask)[0]
                for idx in rejected_indices:
                    k = kernels[idx]
                    logger.info(
                        "  Rejected kernel %d: center=(%.1f,%.1f) layer=%s segment=%d ncc=%.3f",
                        idx, k.center[0], k.center[1], k.layer,
                        k.aha_segment, float(es_ncc_for_gate[idx]),
                    )

            # Compute quality-gated GLS using segment strains
            if segment_strain:
                gls_quality_gated = compute_gls_from_segments(
                    segment_strain, segment_quality, min_quality=min_quality
                )
                # Use quality-gated GLS if available, otherwise fallback to curve-based GLS
                if gls_quality_gated != 0.0:
                    logger.info(
                        "STE GLS: curve-based=%.2f%%, quality-gated=%.2f%%",
                        gls, gls_quality_gated,
                    )
                    gls = gls_quality_gated
            tracked_positions_all = np.full((n_frames, n_kernels, 2), np.nan)
            ncc_all_frames = np.full((n_frames, n_kernels), np.nan)
            tracked_positions_all[phase_start : phase_end + 1] = smoothed
            ncc_all_frames[phase_start : phase_end + 1] = ncc_matrix

            cumulative = (
                tracked_es_positions - tracked_ed_positions
                if tracked_es_positions is not None and tracked_ed_positions is not None
                else None
            )

            self.signals.progress.emit(100, 100)

            self._dump_ste_debug(
                smoothed=smoothed, ncc_matrix=ncc_matrix, kernels=kernels,
                ed_contour=ed_contour, es_contour=es_contour,
                endo_indices=endo_indices, epi_indices=epi_indices,
                longitudinal=longitudinal, radial=radial, gls=gls,
                global_ed=global_ed, global_es=global_es,
                phase_start=phase_start, phase_end=phase_end,
                pixel_spacing=self._pixel_spacing, config=config,
            )

            last = tracking_results[-1] if tracking_results else None
            result = StrainResult(
                longitudinal=longitudinal, radial=radial, gls=gls,
                strain_rate=strain_rate, ed_index=global_ed, es_index=global_es,
                heart_rate_bpm=heart_rate, phases={"ED": global_ed, "ES": global_es},
                zone=self._zone, kernels=kernels,
                last_displacements=last.displacements if last is not None else None,
                last_ncc_scores=es_ncc, last_valid_mask=es_valid,
                cumulative_displacements=cumulative,
                per_kernel_longitudinal=per_kernel,
                ed_contour=ed_contour, es_contour=es_contour,
                tracked_es_positions=tracked_es_positions,
                tracked_ed_positions=tracked_ed_positions,
                tracked_positions_all=tracked_positions_all,
                ncc_all_frames=ncc_all_frames,
                es_ncc_scores=es_ncc, es_valid_mask=es_valid,
                segment_strain=segment_strain,
                segment_quality=segment_quality,
                drift_compensation_applied=bool(config.drift_compensation),
                tracking_quality_mean=tracking_quality_mean,
                tracking_window_start=phase_start,
                tracking_window_end=phase_end,
                ncc_threshold=config.ncc_threshold,
                kernels_accepted_count=n_accepted,
                kernels_rejected_count=n_rejected,
                kernels_total_count=n_kernels,
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
