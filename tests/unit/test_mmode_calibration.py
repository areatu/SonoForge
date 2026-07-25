"""Tests for mmode_calibration.mmode_state_from_panel."""

from __future__ import annotations

from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi
from echo_personal_tool.domain.models.frame_panels import (
    MmodeCalibrationState,
    PanelKind,
    UltrasoundPanel,
)
from echo_personal_tool.domain.services.mmode_calibration import mmode_state_from_panel


def _m_mode_panel(vertical_mm=0.5, horizontal_ms=10.0):
    return UltrasoundPanel(
        kind=PanelKind.M_MODE,
        bounds=DopplerSpectrogramRoi(x0=0, y0=0, width=200, height=60),
        physical_delta_x=0.01,
        physical_delta_y=0.05,
        physical_units_x=3,
        physical_units_y=2,
    )


class TestMmodeStateFromPanel:
    def test_non_mmode_returns_none(self):
        panel = UltrasoundPanel(
            kind=PanelKind.B_MODE,
            bounds=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=100),
        )
        assert mmode_state_from_panel(panel) is None

    def test_doppler_returns_none(self):
        panel = UltrasoundPanel(
            kind=PanelKind.DOPPLER,
            bounds=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=100),
        )
        assert mmode_state_from_panel(panel) is None

    def test_valid_m_mode_panel(self):
        panel = _m_mode_panel()
        state = mmode_state_from_panel(panel)
        assert state is not None
        assert isinstance(state, MmodeCalibrationState)
        assert state.vertical_mm_per_pixel > 0.0

    def test_m_mode_no_vertical_calibration(self):
        """M-mode panel with no physical_delta_y → vertical_mm_per_pixel is None."""
        panel = UltrasoundPanel(
            kind=PanelKind.M_MODE,
            bounds=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50),
        )
        assert mmode_state_from_panel(panel) is None

    def test_m_mode_zero_vertical(self):
        panel = UltrasoundPanel(
            kind=PanelKind.M_MODE,
            bounds=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50),
            physical_delta_y=0.0,
            physical_units_y=2,
        )
        assert mmode_state_from_panel(panel) is None

    def test_state_roi_matches_panel(self):
        panel = _m_mode_panel()
        state = mmode_state_from_panel(panel)
        assert state.roi == panel.bounds
