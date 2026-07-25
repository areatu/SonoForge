"""Regression tests for Doppler calibration and velocity calculations."""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.models.doppler_axis import DopplerAxisMapping
from echo_personal_tool.domain.models.doppler_roi import (
    DopplerCalibrationState,
    DopplerKind,
    DopplerSpectrogramRoi,
)
from echo_personal_tool.domain.services.doppler_calibration import (
    build_axis_mapping,
    calibration_from_roi_and_baseline,
    is_calibration_complete,
    roi_from_corners,
)


def _make_roi(x0: float = 100.0, y0: float = 50.0, w: float = 400.0, h: float = 200.0) -> DopplerSpectrogramRoi:
    return DopplerSpectrogramRoi(x0=x0, y0=y0, width=w, height=h)


class TestDopplerAxisMappingRegression:
    """DopplerAxisMapping conversions must produce exact known outputs."""

    def test_time_ms_from_x_origin(self) -> None:
        mapping = DopplerAxisMapping(
            time_origin_ms=0.0,
            time_span_ms=1000.0,
            plot_width=400.0,
            plot_origin_x=100.0,
        )
        assert mapping.time_ms_from_x(100.0) == pytest.approx(0.0)

    def test_time_ms_from_x_end(self) -> None:
        mapping = DopplerAxisMapping(
            time_origin_ms=0.0,
            time_span_ms=1000.0,
            plot_width=400.0,
            plot_origin_x=100.0,
        )
        assert mapping.time_ms_from_x(500.0) == pytest.approx(1000.0)

    def test_time_ms_from_x_midpoint(self) -> None:
        mapping = DopplerAxisMapping(
            time_origin_ms=0.0,
            time_span_ms=1000.0,
            plot_width=400.0,
            plot_origin_x=100.0,
        )
        assert mapping.time_ms_from_x(300.0) == pytest.approx(500.0)

    def test_x_from_time_ms_roundtrip(self) -> None:
        mapping = DopplerAxisMapping(
            time_origin_ms=0.0,
            time_span_ms=1000.0,
            plot_width=400.0,
            plot_origin_x=100.0,
        )
        x = mapping.x_from_time_ms(750.0)
        assert mapping.time_ms_from_x(x) == pytest.approx(750.0)

    def test_velocity_from_y_baseline_center(self) -> None:
        roi = _make_roi()
        mapping = DopplerAxisMapping(
            roi=roi,
            baseline_y_px=150.0,
            velocity_span_cm_s=200.0,
            plot_height=200.0,
            plot_origin_y=50.0,
        )
        assert mapping.velocity_cm_s_from_y(150.0) == pytest.approx(0.0)

    def test_velocity_from_y_above_baseline(self) -> None:
        mapping = DopplerAxisMapping(
            time_span_ms=1000.0,
            velocity_span_cm_s=200.0,
            plot_width=400.0,
            plot_height=200.0,
            plot_origin_x=100.0,
            plot_origin_y=50.0,
            baseline_y_px=150.0,
        )
        vel = mapping.velocity_cm_s_from_y(100.0)
        assert vel > 0.0

    def test_velocity_from_y_below_baseline(self) -> None:
        mapping = DopplerAxisMapping(
            time_span_ms=1000.0,
            velocity_span_cm_s=200.0,
            plot_width=400.0,
            plot_height=200.0,
            plot_origin_x=100.0,
            plot_origin_y=50.0,
            baseline_y_px=150.0,
        )
        vel = mapping.velocity_cm_s_from_y(200.0)
        assert vel < 0.0

    def test_velocity_y_roundtrip(self) -> None:
        mapping = DopplerAxisMapping(
            time_span_ms=1000.0,
            velocity_span_cm_s=200.0,
            plot_width=400.0,
            plot_height=200.0,
            plot_origin_x=100.0,
            plot_origin_y=50.0,
            baseline_y_px=150.0,
        )
        for vel in (-100.0, -50.0, 0.0, 50.0, 100.0):
            y = mapping.y_from_velocity_cm_s(vel)
            assert mapping.velocity_cm_s_from_y(y) == pytest.approx(vel)

    def test_velocity_fallback_no_baseline(self) -> None:
        mapping = DopplerAxisMapping(
            velocity_min_cm_s=-100.0,
            velocity_max_cm_s=100.0,
            plot_height=200.0,
            plot_origin_y=50.0,
        )
        assert mapping.velocity_cm_s_from_y(50.0) == pytest.approx(100.0)
        assert mapping.velocity_cm_s_from_y(250.0) == pytest.approx(-100.0)

    def test_has_roi_calibration_true(self) -> None:
        roi = _make_roi()
        mapping = DopplerAxisMapping(
            roi=roi,
            baseline_y_px=100.0,
            plot_width=400.0,
            plot_height=200.0,
        )
        assert mapping.has_roi_calibration is True

    def test_has_roi_calibration_no_baseline(self) -> None:
        roi = _make_roi()
        mapping = DopplerAxisMapping(roi=roi, plot_width=400.0, plot_height=200.0)
        assert mapping.has_roi_calibration is False


class TestBuildAxisMappingRegression:
    """Build axis mapping from calibration state produces expected output."""

    def test_build_mapping_symmetric_velocity(self) -> None:
        roi = _make_roi()
        state = DopplerCalibrationState(
            roi=roi,
            baseline_y_px=150.0,
            time_span_ms=1000.0,
            velocity_span_cm_s=200.0,
            kind=DopplerKind.SPECTRAL,
        )
        mapping = build_axis_mapping(state)
        assert mapping.velocity_min_cm_s == pytest.approx(-100.0)
        assert mapping.velocity_max_cm_s == pytest.approx(100.0)
        assert mapping.time_span_ms == pytest.approx(1000.0)

    def test_build_mapping_tissue_velocity(self) -> None:
        roi = _make_roi()
        state = DopplerCalibrationState(
            roi=roi,
            baseline_y_px=150.0,
            time_span_ms=500.0,
            velocity_span_cm_s=40.0,
            kind=DopplerKind.TISSUE,
        )
        mapping = build_axis_mapping(state)
        assert mapping.velocity_min_cm_s == pytest.approx(-20.0)
        assert mapping.velocity_max_cm_s == pytest.approx(20.0)

    def test_build_mapping_custom_time_span(self) -> None:
        roi = _make_roi()
        state = DopplerCalibrationState(
            roi=roi,
            baseline_y_px=100.0,
            time_span_ms=2000.0,
            velocity_span_cm_s=150.0,
        )
        mapping = build_axis_mapping(state)
        assert mapping.time_span_ms == pytest.approx(2000.0)


class TestCalibrationFromRoiRegression:
    """calibration_from_roi_and_baseline produces known states."""

    def test_spectral_default_span(self) -> None:
        roi = _make_roi()
        state = calibration_from_roi_and_baseline(roi, baseline_y_px=100.0)
        assert state.velocity_span_cm_s == pytest.approx(200.0)
        assert state.time_span_ms == pytest.approx(1000.0)

    def test_tissue_default_span(self) -> None:
        roi = _make_roi()
        state = calibration_from_roi_and_baseline(
            roi, baseline_y_px=100.0, kind=DopplerKind.TISSUE
        )
        assert state.velocity_span_cm_s == pytest.approx(40.0)

    def test_custom_velocity_span(self) -> None:
        roi = _make_roi()
        state = calibration_from_roi_and_baseline(
            roi, baseline_y_px=100.0, velocity_span_cm_s=300.0
        )
        assert state.velocity_span_cm_s == pytest.approx(300.0)

    def test_custom_time_span(self) -> None:
        roi = _make_roi()
        state = calibration_from_roi_and_baseline(
            roi, baseline_y_px=100.0, time_span_ms=800.0
        )
        assert state.time_span_ms == pytest.approx(800.0)


class TestIsCalibrationCompleteRegression:
    def test_complete_spectral(self) -> None:
        roi = _make_roi()
        state = DopplerCalibrationState(
            roi=roi,
            baseline_y_px=100.0,
            time_span_ms=1000.0,
            velocity_span_cm_s=200.0,
        )
        assert is_calibration_complete(state) is True

    def test_incomplete_no_roi(self) -> None:
        assert is_calibration_complete(None) is False

    def test_incomplete_zero_velocity_span(self) -> None:
        roi = _make_roi()
        state = DopplerCalibrationState(
            roi=roi,
            baseline_y_px=100.0,
            time_span_ms=1000.0,
            velocity_span_cm_s=0.0,
        )
        assert is_calibration_complete(state) is False


class TestRoiFromCornersRegression:
    def test_normal_order(self) -> None:
        roi = roi_from_corners((10.0, 20.0), (50.0, 80.0))
        assert roi.x0 == pytest.approx(10.0)
        assert roi.y0 == pytest.approx(20.0)
        assert roi.width == pytest.approx(40.0)
        assert roi.height == pytest.approx(60.0)

    def test_reversed_order(self) -> None:
        roi = roi_from_corners((50.0, 80.0), (10.0, 20.0))
        assert roi.x0 == pytest.approx(10.0)
        assert roi.y0 == pytest.approx(20.0)
        assert roi.width == pytest.approx(40.0)
        assert roi.height == pytest.approx(60.0)

    def test_same_point(self) -> None:
        roi = roi_from_corners((5.0, 5.0), (5.0, 5.0))
        assert roi.width == pytest.approx(1.0)
        assert roi.height == pytest.approx(1.0)


class TestDopplerVelocityCalculationRegression:
    """Doppler velocity calculations produce exact expected results."""

    def test_velocity_from_y_known_calibration(self) -> None:
        mapping = DopplerAxisMapping(
            time_span_ms=1000.0,
            velocity_span_cm_s=200.0,
            plot_width=500.0,
            plot_height=250.0,
            plot_origin_x=0.0,
            plot_origin_y=0.0,
            baseline_y_px=125.0,
        )
        # At baseline, velocity = 0
        assert mapping.velocity_cm_s_from_y(125.0) == pytest.approx(0.0)
        # 1 pixel above baseline = positive velocity
        vel_1px_above = mapping.velocity_cm_s_from_y(124.0)
        assert vel_1px_above > 0.0

    def test_velocity_scale_factor(self) -> None:
        mapping = DopplerAxisMapping(
            time_span_ms=1000.0,
            velocity_span_cm_s=100.0,
            plot_width=500.0,
            plot_height=100.0,
            plot_origin_x=0.0,
            plot_origin_y=0.0,
            baseline_y_px=50.0,
        )
        pixels_per_cm_s = 100.0 / 100.0  # plot_height / velocity_span
        # Moving 10 pixels above baseline
        vel = mapping.velocity_cm_s_from_y(40.0)
        assert vel == pytest.approx(10.0 * (1.0 / pixels_per_cm_s))

    def test_zero_height_returns_zero(self) -> None:
        mapping = DopplerAxisMapping(plot_height=0.0)
        assert mapping.velocity_cm_s_from_y(100.0) == 0.0

    def test_zero_width_returns_origin(self) -> None:
        mapping = DopplerAxisMapping(plot_width=0.0, time_origin_ms=500.0)
        assert mapping.time_ms_from_x(100.0) == pytest.approx(500.0)
