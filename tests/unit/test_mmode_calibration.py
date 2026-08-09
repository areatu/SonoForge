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
        """State with ROI + depth but no time → is_complete=False (both axes required)."""
        state = MmodeCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50),
            vertical_mm_per_pixel=0.5,
            horizontal_ms_per_pixel=None,
        )
        assert state.is_complete() is False

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
        """depth_from_dicom_tags and time_from_dicom_tags propagate to helper methods."""
        state = MmodeCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50),
            vertical_mm_per_pixel=0.5,
            horizontal_ms_per_pixel=10.0,
            from_dicom_tags=True,
            depth_from_dicom_tags=True,
            time_from_dicom_tags=True,
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


class TestMmodeCalibrationStateEnhanced:
    def test_is_partial_depth_only(self):
        """State with depth but no time → is_partial=True."""
        state = MmodeCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50),
            vertical_mm_per_pixel=0.5,
            horizontal_ms_per_pixel=None,
        )
        assert state.is_partial() is True
        assert state.has_depth_scale() is True
        assert state.has_time_scale() is False

    def test_is_partial_time_only(self):
        """State with time but no depth → is_partial=True."""
        state = MmodeCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50),
            vertical_mm_per_pixel=None,
            horizontal_ms_per_pixel=10.0,
        )
        assert state.is_partial() is True
        assert state.has_depth_scale() is False
        assert state.has_time_scale() is True

    def test_is_complete_both_axes(self):
        """State with both axes → is_complete=True, is_partial=False."""
        state = MmodeCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50),
            vertical_mm_per_pixel=0.5,
            horizontal_ms_per_pixel=10.0,
        )
        assert state.is_complete() is True
        assert state.is_partial() is False

    def test_has_depth_from_dicom_with_flag(self):
        """depth_from_dicom_tags=True + valid depth → has_depth_from_dicom=True."""
        state = MmodeCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50),
            vertical_mm_per_pixel=0.5,
            depth_from_dicom_tags=True,
        )
        assert state.has_depth_from_dicom() is True

    def test_has_depth_from_dicom_without_depth(self):
        """depth_from_dicom_tags=True but no depth → has_depth_from_dicom=False."""
        state = MmodeCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50),
            vertical_mm_per_pixel=None,
            depth_from_dicom_tags=True,
        )
        assert state.has_depth_from_dicom() is False

    def test_has_time_from_dicom_with_flag(self):
        """time_from_dicom_tags=True + valid time → has_time_from_dicom=True."""
        state = MmodeCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50),
            horizontal_ms_per_pixel=10.0,
            time_from_dicom_tags=True,
        )
        assert state.has_time_from_dicom() is True

    def test_has_time_from_dicom_without_time(self):
        """time_from_dicom_tags=True but no time → has_time_from_dicom=False."""
        state = MmodeCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50),
            horizontal_ms_per_pixel=None,
            time_from_dicom_tags=True,
        )
        assert state.has_time_from_dicom() is False

    def test_is_dicom_trusted_full(self):
        """from_dicom_tags=True + both axes → is_dicom_trusted=True."""
        state = MmodeCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50),
            vertical_mm_per_pixel=0.5,
            horizontal_ms_per_pixel=10.0,
            from_dicom_tags=True,
        )
        assert state.is_dicom_trusted() is True

    def test_is_dicom_trusted_partial(self):
        """from_dicom_tags=True but missing one axis → is_dicom_trusted=False."""
        state = MmodeCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50),
            vertical_mm_per_pixel=0.5,
            horizontal_ms_per_pixel=None,
            from_dicom_tags=True,
        )
        assert state.is_dicom_trusted() is False

    def test_is_dicom_trusted_manual(self):
        """from_dicom_tags=False → is_dicom_trusted=False."""
        state = MmodeCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50),
            vertical_mm_per_pixel=0.5,
            horizontal_ms_per_pixel=10.0,
            from_dicom_tags=False,
        )
        assert state.is_dicom_trusted() is False


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


class TestMmodeStateFromPanelFrameTime:
    def test_frame_time_fallback_when_no_dicom_time(self):
        """Panel without PhysicalDeltaX + FrameTime → time from FrameTime."""
        panel = UltrasoundPanel(
            kind=PanelKind.M_MODE,
            bounds=DopplerSpectrogramRoi(x0=0, y0=0, width=200, height=60),
            physical_delta_y=0.05,
            physical_units_y=2,
        )
        state = mmode_state_from_panel(panel, frame_time_ms=500.0)
        assert state is not None
        assert state.horizontal_ms_per_pixel == 2.5  # 500ms / 200px
        assert state.time_from_dicom_tags is False
        assert state.depth_from_dicom_tags is True

    def test_dicom_time_takes_priority_over_frame_time(self):
        """Panel with PhysicalDeltaX + FrameTime → time from DICOM (not FrameTime)."""
        panel = UltrasoundPanel(
            kind=PanelKind.M_MODE,
            bounds=DopplerSpectrogramRoi(x0=0, y0=0, width=200, height=60),
            physical_delta_x=0.01,
            physical_delta_y=0.05,
            physical_units_x=3,
            physical_units_y=2,
        )
        state = mmode_state_from_panel(panel, frame_time_ms=500.0)
        assert state is not None
        assert state.horizontal_ms_per_pixel is not None
        assert state.time_from_dicom_tags is True

    def test_no_frame_time_no_dicom_time(self):
        """Panel without PhysicalDeltaX and no FrameTime → no time."""
        panel = UltrasoundPanel(
            kind=PanelKind.M_MODE,
            bounds=DopplerSpectrogramRoi(x0=0, y0=0, width=200, height=60),
            physical_delta_y=0.05,
            physical_units_y=2,
        )
        state = mmode_state_from_panel(panel, frame_time_ms=None)
        assert state is not None
        assert state.horizontal_ms_per_pixel is None
        assert state.time_from_dicom_tags is False

    def test_frame_time_zero_ignored(self):
        """FrameTime=0 → ignored, no time."""
        panel = UltrasoundPanel(
            kind=PanelKind.M_MODE,
            bounds=DopplerSpectrogramRoi(x0=0, y0=0, width=200, height=60),
            physical_delta_y=0.05,
            physical_units_y=2,
        )
        state = mmode_state_from_panel(panel, frame_time_ms=0.0)
        assert state is not None
        assert state.horizontal_ms_per_pixel is None

    def test_frame_time_negative_ignored(self):
        """FrameTime<0 → ignored, no time."""
        panel = UltrasoundPanel(
            kind=PanelKind.M_MODE,
            bounds=DopplerSpectrogramRoi(x0=0, y0=0, width=200, height=60),
            physical_delta_y=0.05,
            physical_units_y=2,
        )
        state = mmode_state_from_panel(panel, frame_time_ms=-100.0)
        assert state is not None
        assert state.horizontal_ms_per_pixel is None

    def test_frame_time_zero_width_ignored(self):
        """FrameTime with width=0 → ignored, no time."""
        panel = UltrasoundPanel(
            kind=PanelKind.M_MODE,
            bounds=DopplerSpectrogramRoi(x0=0, y0=0, width=0, height=60),
            physical_delta_y=0.05,
            physical_units_y=2,
        )
        state = mmode_state_from_panel(panel, frame_time_ms=500.0)
        assert state is not None
        assert state.horizontal_ms_per_pixel is None
