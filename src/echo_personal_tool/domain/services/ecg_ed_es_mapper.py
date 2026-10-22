"""Map R-peaks to ED/ES frame indices in a CINE sequence."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import numpy as np

from echo_personal_tool.domain.models.ecg import EcEDFrameMapping, EcgWaveform, RPeakResult
from echo_personal_tool.domain.services.ecg_rpeak_detector import detect_r_peaks_from_waveform

_DEFAULT_CONFIDENCE_THRESHOLD = 0.4


def detect_ed_es_from_area_curve(
    samples: tuple[tuple[int, float], ...],
    n_frames: int,
) -> tuple[int, int] | None:
    """Select ED=max area and ES=min area from stored Simpson samples."""
    by_frame = {int(frame): float(area) for frame, area in samples if 0 <= int(frame) < n_frames and np.isfinite(area)}
    if len(by_frame) < 2:
        return None
    frames = np.array(sorted(by_frame), dtype=np.int64)
    areas = np.array([by_frame[int(frame)] for frame in frames], dtype=np.float64)
    if np.ptp(areas) <= 1e-8:
        return None
    return int(frames[np.argmax(areas)]), int(frames[np.argmin(areas)])


def map_rpeaks_to_frames(
    r_peak_result: RPeakResult | None,
    frame_time_ms: float,
    n_frames: int,
) -> EcEDFrameMapping:
    """Map R-peaks to ED/ES frame indices.

    Clinical convention:
    - ED (end-diastole) ≈ R-peak (ventricles just filled, about to contract)
    - ES (end-systole) ≈ mid-diastole, approximately 35% of cycle after R-peak

    Args:
        r_peak_result: Detected R-peaks, or None for fallback.
        frame_time_ms: Time per frame in milliseconds.
        n_frames: Total number of frames in the CINE sequence.

    Returns:
        EcEDFrameMapping with ED/ES frame indices.
    """
    if r_peak_result is None or len(r_peak_result.r_peak_indices) == 0 or r_peak_result.confidence < 0.3:
        return EcEDFrameMapping(
            ed_frame_index=0,
            es_frame_index=max(1, n_frames // 3),
            cycle_start_frame=0,
            cycle_end_frame=n_frames - 1,
            source="image_fallback",
        )

    # R-peak times → frame indices
    r_frame_indices = r_peak_result.r_peak_times_ms / frame_time_ms

    # ED = frame closest to first R-peak
    ed_frame = int(round(r_frame_indices[0]))
    ed_frame = max(0, min(ed_frame, n_frames - 1))

    # ES = frame closest to midpoint between first two R-peaks
    # (systole is ~35% of cardiac cycle)
    if len(r_frame_indices) >= 2:
        cycle_length_frames = r_frame_indices[1] - r_frame_indices[0]
        systole_offset = cycle_length_frames * 0.35
        es_frame = int(round(r_frame_indices[0] + systole_offset))
    else:
        es_frame = min(ed_frame + max(1, n_frames // 3), n_frames - 1)

    es_frame = max(0, min(es_frame, n_frames - 1))

    # Ensure ED != ES
    if ed_frame == es_frame:
        es_frame = min(ed_frame + max(1, n_frames // 3), n_frames - 1)

    # Cycle boundaries
    cycle_start = ed_frame
    cycle_end = min(int(round(r_frame_indices[-1])), n_frames - 1)
    if cycle_end <= cycle_start:
        cycle_end = n_frames - 1

    return EcEDFrameMapping(
        ed_frame_index=ed_frame,
        es_frame_index=es_frame,
        cycle_start_frame=cycle_start,
        cycle_end_frame=cycle_end,
        source="ecg",
    )


def detect_ed_es_for_cine(
    ecg: EcgWaveform | None,
    frame_time_ms: float,
    n_frames: int,
    *,
    r_peak_result: RPeakResult | None = None,
    simpson_fallback: Callable[[], tuple[int, int] | None] | None = None,
    image_fallback: Callable[[], tuple[int, int]] | None = None,
    confidence_threshold: float = _DEFAULT_CONFIDENCE_THRESHOLD,
) -> EcEDFrameMapping:
    """Detect ED/ES for a CINE sequence with an ECG-first policy.

    Prefers ECG R-peaks when a usable waveform with reliable confidence is
    available; otherwise falls back to a stored Simpson area curve, then the
    image-based detector. The returned mapping's ``source`` reflects the winner.
    """
    if n_frames <= 0:
        return EcEDFrameMapping(0, 0, 0, 0, source="image")

    if r_peak_result is None and ecg is not None:
        r_peak_result = detect_r_peaks_from_waveform(ecg)
    if (
        r_peak_result is not None
        and len(r_peak_result.r_peak_indices) > 0
        and r_peak_result.confidence >= confidence_threshold
    ):
        mapping = map_rpeaks_to_frames(r_peak_result, frame_time_ms, n_frames)
        return replace(mapping, r_peak_result=r_peak_result)

    if simpson_fallback is not None:
        try:
            simpson_phases = simpson_fallback()
        except Exception:  # noqa: BLE001
            simpson_phases = None
        if simpson_phases is not None:
            ed, es = simpson_phases
            ed = int(np.clip(ed, 0, n_frames - 1))
            es = int(np.clip(es, 0, n_frames - 1))
            if ed != es:
                return EcEDFrameMapping(
                    ed_frame_index=ed,
                    es_frame_index=es,
                    cycle_start_frame=min(ed, es),
                    cycle_end_frame=max(ed, es),
                    source="simpson",
                )

    if image_fallback is not None:
        try:
            ed, es = image_fallback()
        except Exception:  # noqa: BLE001
            ed, es = 0, max(1, n_frames // 3)
        ed = int(np.clip(ed, 0, n_frames - 1))
        es = int(np.clip(es, 0, n_frames - 1))
        return EcEDFrameMapping(
            ed_frame_index=ed,
            es_frame_index=es,
            cycle_start_frame=min(ed, es),
            cycle_end_frame=max(ed, es),
            source="image",
        )

    return EcEDFrameMapping(
        ed_frame_index=0,
        es_frame_index=max(1, n_frames // 3),
        cycle_start_frame=0,
        cycle_end_frame=n_frames - 1,
        source="image",
    )
