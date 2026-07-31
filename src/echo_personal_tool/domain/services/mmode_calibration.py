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
