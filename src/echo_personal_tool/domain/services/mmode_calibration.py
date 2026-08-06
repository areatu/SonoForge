"""Build M-mode calibration from ultrasound panels."""

from __future__ import annotations

from echo_personal_tool.domain.models.frame_panels import (
    MmodeCalibrationState,
    PanelKind,
    UltrasoundPanel,
)


def mmode_state_from_panel(
    panel: UltrasoundPanel,
    frame_time_ms: float | None = None,
) -> MmodeCalibrationState | None:
    if panel.kind is not PanelKind.M_MODE:
        return None

    horizontal_ms = panel.horizontal_ms_per_pixel
    time_from_dicom = horizontal_ms is not None

    if horizontal_ms is None and frame_time_ms is not None and frame_time_ms > 0.0 and panel.bounds.width > 0:
        horizontal_ms = frame_time_ms / panel.bounds.width
        time_from_dicom = False

    return MmodeCalibrationState(
        roi=panel.bounds,
        vertical_mm_per_pixel=panel.vertical_mm_per_pixel,
        horizontal_ms_per_pixel=horizontal_ms,
        from_dicom_tags=panel.horizontal_ms_per_pixel is not None and panel.vertical_mm_per_pixel is not None,
        depth_from_dicom_tags=panel.vertical_mm_per_pixel is not None,
        time_from_dicom_tags=time_from_dicom,
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
