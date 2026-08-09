"""Regression tests for maximum calibration: Doppler + M-mode fallback chain."""

from __future__ import annotations

from echo_personal_tool.domain.models.doppler_roi import (
    DopplerCalibrationState,
    DopplerSpectrogramRoi,
)
from echo_personal_tool.domain.models.frame_panels import (
    MmodeCalibrationState,
    PanelKind,
    UltrasoundPanel,
)
from echo_personal_tool.domain.services.mmode_calibration import mmode_state_from_panel
from echo_personal_tool.domain.services.ultrasound_region_physics import (
    PHYSICAL_UNIT_SEC,
    horizontal_ms_per_pixel,
)


class TestDopplerRegression:
    def test_samsung_partial_no_deltas(self):
        """Samsung without PhysicalDeltaX/Y → time_span_ms=0, is_partial=True."""
        state = DopplerCalibrationState(
            roi=DopplerSpectrogramRoi(x0=10, y0=20, width=200, height=100),
            baseline_y_px=70.0,
            time_span_ms=0.0,
            velocity_span_cm_s=200.0,
            from_dicom_tags=True,
            time_from_dicom_tags=False,
            velocity_from_dicom_tags=False,
        )
        assert state.has_time_scale() is False
        assert state.is_partial() is True
        assert state.is_complete() is False

    def test_doppler_full_dicom(self):
        """Both axes from tags → is_complete=True, is_dicom_trusted=True."""
        state = DopplerCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0, y0=0, width=200, height=100),
            baseline_y_px=50.0,
            time_span_ms=500.0,
            velocity_span_cm_s=200.0,
            from_dicom_tags=True,
            time_from_dicom_tags=True,
            velocity_from_dicom_tags=True,
        )
        assert state.is_complete() is True
        assert state.is_dicom_trusted() is True
        assert state.is_partial() is False

    def test_doppler_partial_time_missing(self):
        """One axis missing → is_partial=True."""
        state = DopplerCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0, y0=0, width=200, height=100),
            baseline_y_px=50.0,
            time_span_ms=0.0,
            velocity_span_cm_s=200.0,
            from_dicom_tags=True,
            time_from_dicom_tags=False,
            velocity_from_dicom_tags=True,
        )
        assert state.is_partial() is True
        assert state.has_time_scale() is False
        assert state.has_velocity_scale() is True

    def test_doppler_time_guard(self):
        """time_span_ms=0 → time_ms_from_x returns time_origin_ms."""
        from echo_personal_tool.domain.models.doppler_axis import DopplerAxisMapping

        axis = DopplerAxisMapping(
            time_origin_ms=100.0,
            time_span_ms=0.0,
            velocity_span_cm_s=200.0,
        )
        # time_ms_from_x should return time_origin_ms when time_span_ms=0
        result = axis.time_ms_from_x(100.0)
        assert result == 100.0


class TestMmodeRegression:
    def test_mmode_full_dicom(self):
        """Both axes from tags → is_complete=True."""
        state = MmodeCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0, y0=0, width=200, height=60),
            vertical_mm_per_pixel=0.15,
            horizontal_ms_per_pixel=2.5,
            from_dicom_tags=True,
            depth_from_dicom_tags=True,
            time_from_dicom_tags=True,
        )
        assert state.is_complete() is True
        assert state.is_partial() is False
        assert state.is_dicom_trusted() is True

    def test_mmode_no_time(self):
        """No time axis → is_partial=True."""
        state = MmodeCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0, y0=0, width=200, height=60),
            vertical_mm_per_pixel=0.15,
            horizontal_ms_per_pixel=None,
            from_dicom_tags=True,
            depth_from_dicom_tags=True,
            time_from_dicom_tags=False,
        )
        assert state.is_partial() is True
        assert state.has_depth_scale() is True
        assert state.has_time_scale() is False

    def test_mmode_no_depth(self):
        """No depth axis → is_partial=True."""
        state = MmodeCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0, y0=0, width=200, height=60),
            vertical_mm_per_pixel=None,
            horizontal_ms_per_pixel=2.5,
            from_dicom_tags=True,
            depth_from_dicom_tags=False,
            time_from_dicom_tags=True,
        )
        assert state.is_partial() is True
        assert state.has_depth_scale() is False
        assert state.has_time_scale() is True

    def test_mmode_frame_time_fallback(self):
        """No PhysicalDeltaX + FrameTime → time from FrameTime."""
        panel = UltrasoundPanel(
            kind=PanelKind.M_MODE,
            bounds=DopplerSpectrogramRoi(x0=0, y0=0, width=200, height=60),
            physical_delta_y=0.05,
            physical_units_y=2,
        )
        state = mmode_state_from_panel(panel, frame_time_ms=500.0)
        assert state is not None
        assert state.horizontal_ms_per_pixel == 2.5
        assert state.time_from_dicom_tags is False

    def test_mmode_banner_values(self):
        """M-mode banner shows actual values."""
        state = MmodeCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0, y0=0, width=200, height=60),
            vertical_mm_per_pixel=0.15,
            horizontal_ms_per_pixel=2.5,
            from_dicom_tags=True,
            depth_from_dicom_tags=True,
            time_from_dicom_tags=True,
        )
        # Test the model methods that banner uses
        assert state.has_depth_from_dicom() is True
        assert state.has_time_from_dicom() is True
        assert state.vertical_mm_per_pixel == 0.15
        assert state.horizontal_ms_per_pixel == 2.5

    def test_mmode_not_trusted_manual(self):
        """Manual calibration → is_dicom_trusted=False."""
        state = MmodeCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0, y0=0, width=200, height=60),
            vertical_mm_per_pixel=0.15,
            horizontal_ms_per_pixel=2.5,
            from_dicom_tags=False,
            depth_from_dicom_tags=False,
            time_from_dicom_tags=False,
        )
        assert state.is_dicom_trusted() is False


class TestPhysicsGuardRegression:
    def test_sf1_rejects_bmode(self):
        """B-mode (SF=1) with SEC units → None."""
        assert horizontal_ms_per_pixel(0.024, PHYSICAL_UNIT_SEC, spatial_format=1) is None

    def test_sf2_accepts_mmode(self):
        """M-mode (SF=2) with SEC units → valid value."""
        assert horizontal_ms_per_pixel(0.024, PHYSICAL_UNIT_SEC, spatial_format=2) == 24.0

    def test_sf3_accepts_spectral(self):
        """Spectral (SF=3) with SEC units → valid value."""
        assert horizontal_ms_per_pixel(0.024, PHYSICAL_UNIT_SEC, spatial_format=3) == 24.0
