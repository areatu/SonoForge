"""Tests for composite frame panel models."""

from __future__ import annotations

from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi
from echo_personal_tool.domain.models.frame_panels import PanelKind, UltrasoundPanel
from echo_personal_tool.domain.services.ultrasound_region_physics import (
    PHYSICAL_UNIT_CM,
    PHYSICAL_UNIT_SEC,
)


def test_ultrasound_panel_horizontal_mm_per_pixel() -> None:
    panel = UltrasoundPanel(
        kind=PanelKind.B_MODE,
        bounds=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=100),
        physical_delta_x=0.02,
        physical_delta_y=0.03,
        physical_units_x=PHYSICAL_UNIT_CM,
        physical_units_y=PHYSICAL_UNIT_CM,
    )
    assert panel.horizontal_mm_per_pixel == 0.2
    assert panel.vertical_mm_per_pixel == 0.3


def test_ultrasound_panel_horizontal_mm_none_on_time_axis() -> None:
    panel = UltrasoundPanel(
        kind=PanelKind.M_MODE,
        bounds=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=100),
        physical_delta_x=0.024,
        physical_units_x=PHYSICAL_UNIT_SEC,
    )
    assert panel.horizontal_mm_per_pixel is None
    assert panel.horizontal_ms_per_pixel == 24.0
