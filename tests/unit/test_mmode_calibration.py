"""Unit tests for M-mode calibration from ultrasound panels."""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi
from echo_personal_tool.domain.models.frame_panels import (
    MmodeCalibrationState,
    PanelKind,
    UltrasoundPanel,
)
from echo_personal_tool.domain.services.mmode_calibration import (
    mmode_state_from_panel,
)
from echo_personal_tool.domain.services.ultrasound_region_physics import (
    PHYSICAL_UNIT_MM,
    PHYSICAL_UNIT_SEC,
)


def _make_mmode_panel(
    vertical_mm_per_pixel: float = 1.0,
    include_vertical: bool = True,
) -> UltrasoundPanel:
    bounds = DopplerSpectrogramRoi(x0=0.0, y0=0.0, width=100.0, height=50.0)
    return UltrasoundPanel(
        kind=PanelKind.M_MODE,
        bounds=bounds,
        physical_delta_y=vertical_mm_per_pixel if include_vertical else None,
        physical_units_y=PHYSICAL_UNIT_MM if include_vertical else None,
    )


class TestMmodeStateFromPanel:
    def test_returns_none_for_non_mmode_panel(self) -> None:
        bounds = DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50)
        panel = UltrasoundPanel(
            kind=PanelKind.DOPPLER,
            bounds=bounds,
            physical_delta_y=1.0,
            physical_units_y=PHYSICAL_UNIT_MM,
        )
        assert mmode_state_from_panel(panel) is None

    def test_returns_none_when_no_vertical_mm(self) -> None:
        panel = _make_mmode_panel(include_vertical=False)
        assert mmode_state_from_panel(panel) is None

    def test_returns_none_when_vertical_mm_zero(self) -> None:
        bounds = DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50)
        panel = UltrasoundPanel(
            kind=PanelKind.M_MODE,
            bounds=bounds,
            physical_delta_y=0.0,
            physical_units_y=PHYSICAL_UNIT_MM,
        )
        assert mmode_state_from_panel(panel) is None

    def test_returns_none_when_no_units(self) -> None:
        bounds = DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50)
        panel = UltrasoundPanel(
            kind=PanelKind.M_MODE,
            bounds=bounds,
            physical_delta_y=1.0,
            physical_units_y=None,
        )
        assert mmode_state_from_panel(panel) is None

    def test_returns_state_for_valid_mmode_panel(self) -> None:
        panel = _make_mmode_panel(vertical_mm_per_pixel=0.5)
        result = mmode_state_from_panel(panel)
        assert result is not None
        assert isinstance(result, MmodeCalibrationState)
        assert result.vertical_mm_per_pixel == 0.5
