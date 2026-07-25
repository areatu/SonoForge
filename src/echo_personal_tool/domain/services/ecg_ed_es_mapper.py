"""Map R-peaks to ED/ES frame indices in a CINE sequence."""

from __future__ import annotations

from echo_personal_tool.domain.models.ecg import EcEDFrameMapping, RPeakResult


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
