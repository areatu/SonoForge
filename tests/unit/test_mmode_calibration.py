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
        """M-mode panel with no physical_delta_y → partial state (not None)."""
        panel = UltrasoundPanel(
            kind=PanelKind.M_MODE,
            bounds=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50),
        )
        state = mmode_state_from_panel(panel)
        assert state is not None
        assert state.vertical_mm_per_pixel is None
        assert state.is_complete() is False

    def test_m_mode_zero_vertical(self):
        """M-mode panel with PhysicalDeltaY=0 → partial state."""
        panel = UltrasoundPanel(
            kind=PanelKind.M_MODE,
            bounds=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50),
            physical_delta_y=0.0,
            physical_units_y=2,
        )
        state = mmode_state_from_panel(panel)
        assert state is not None
        assert state.vertical_mm_per_pixel is None
        assert state.is_complete() is False

    def test_state_roi_matches_panel(self):
        panel = _m_mode_panel()
        state = mmode_state_from_panel(panel)
        assert state.roi == panel.bounds


class TestMmodeCalibrationStatePartial:
    def test_partial_state_no_depth(self):
        """State with ROI but no depth should exist but not be complete."""
        state = MmodeCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50),
            vertical_mm_per_pixel=None,
            horizontal_ms_per_pixel=10.0,
        )
        assert state.is_complete() is False
        assert state.vertical_mm_per_pixel is None
        assert state.horizontal_ms_per_pixel == 10.0

    def test_partial_state_no_time(self):
        """State with ROI + depth but no time should be complete (time is optional)."""
        state = MmodeCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50),
            vertical_mm_per_pixel=0.5,
            horizontal_ms_per_pixel=None,
        )
        assert state.is_complete() is True

    def test_complete_state(self):
        """State with all fields should be complete."""
        state = MmodeCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50),
            vertical_mm_per_pixel=0.5,
            horizontal_ms_per_pixel=10.0,
        )
        assert state.is_complete() is True
        assert state.has_depth_from_dicom() is False
        assert state.has_time_from_dicom() is False

    def test_from_dicom_flags(self):
        """from_dicom_tags flag propagates to helper methods."""
        state = MmodeCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50),
            vertical_mm_per_pixel=0.5,
            horizontal_ms_per_pixel=10.0,
            from_dicom_tags=True,
        )
        assert state.has_depth_from_dicom() is True
        assert state.has_time_from_dicom() is True


class TestMmodeStateFromPanelPartial:
    def test_m_mode_no_vertical_returns_partial(self):
        """M-mode panel without PhysicalDeltaY → partial state with ROI only."""
        panel = UltrasoundPanel(
            kind=PanelKind.M_MODE,
            bounds=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50),
        )
        state = mmode_state_from_panel(panel)
        assert state is not None
        assert state.vertical_mm_per_pixel is None
        assert state.horizontal_ms_per_pixel is None
        assert state.is_complete() is False
        assert state.roi.width == 100

    def test_m_mode_with_time_only(self):
        """M-mode panel with PhysicalDeltaX but no PhysicalDeltaY → partial state with time."""
        panel = UltrasoundPanel(
            kind=PanelKind.M_MODE,
            bounds=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50),
            physical_delta_x=0.01,
            physical_units_x=3,
        )
        state = mmode_state_from_panel(panel)
        assert state is not None
        assert state.vertical_mm_per_pixel is None
        assert state.horizontal_ms_per_pixel is not None
        assert state.is_complete() is False

    def test_m_mode_zero_vertical_still_returns_partial(self):
        """M-mode panel with PhysicalDeltaY=0 → partial state (not rejected)."""
        panel = UltrasoundPanel(
            kind=PanelKind.M_MODE,
            bounds=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50),
            physical_delta_y=0.0,
            physical_units_y=2,
        )
        state = mmode_state_from_panel(panel)
        assert state is not None
        assert state.vertical_mm_per_pixel is None
        assert state.is_complete() is False


class TestHorizontalMsFromFrameTime:
    def test_from_frame_time_ms(self):
        """FrameTime in ms → ms per pixel for single-frame M-mode strip."""
        from echo_personal_tool.domain.services.mmode_calibration import horizontal_ms_from_frame_time
        result = horizontal_ms_from_frame_time(500.0, 200.0)
        assert result == 2.5  # 500ms / 200px = 2.5 ms/px

    def test_none_frame_time(self):
        """None frame_time → None."""
        from echo_personal_tool.domain.services.mmode_calibration import horizontal_ms_from_frame_time
        assert horizontal_ms_from_frame_time(None, 200.0) is None

    def test_zero_frame_time(self):
        """Zero frame_time → None."""
        from echo_personal_tool.domain.services.mmode_calibration import horizontal_ms_from_frame_time
        assert horizontal_ms_from_frame_time(0.0, 200.0) is None

    def test_zero_roi_width(self):
        """Zero roi_width → None."""
        from echo_personal_tool.domain.services.mmode_calibration import horizontal_ms_from_frame_time
        assert horizontal_ms_from_frame_time(500.0, 0.0) is None
