"""Build M-mode calibration from ultrasound panels."""

from __future__ import annotations

from echo_personal_tool.domain.models.frame_panels import (
    MmodeCalibrationState,
    PanelKind,
    UltrasoundPanel,
)


def mmode_state_from_panel(panel: UltrasoundPanel) -> MmodeCalibrationState | None:
    if panel.kind is not PanelKind.M_MODE:
        return None
    return MmodeCalibrationState(
        roi=panel.bounds,
        vertical_mm_per_pixel=panel.vertical_mm_per_pixel,
        horizontal_ms_per_pixel=panel.horizontal_ms_per_pixel,
        from_dicom_tags=True,
    )


def horizontal_ms_from_frame_time(
    frame_time_ms: float | None, roi_width_px: float
) -> float | None:
    """Fallback time scale from dataset-level FrameTime tag.

    For single-frame M-mode strips: entire width = sweep duration.
    """
    if frame_time_ms is None or frame_time_ms <= 0.0:
        return None
    if roi_width_px <= 0.0:
        return None
    return float(frame_time_ms) / roi_width_px
