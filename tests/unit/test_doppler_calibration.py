"""Unit tests for Doppler calibration helpers."""

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


def _make_roi() -> DopplerSpectrogramRoi:
    return DopplerSpectrogramRoi(x0=10.0, y0=20.0, width=100.0, height=50.0)


def _make_state() -> DopplerCalibrationState:
    return DopplerCalibrationState(
        roi=_make_roi(),
        baseline_y_px=45.0,
        time_span_ms=800.0,
        velocity_span_cm_s=200.0,
    )


class TestIsCalibrationComplete:
    def test_none_is_not_complete(self) -> None:
        assert is_calibration_complete(None) is False

    def test_complete_state(self) -> None:
        assert is_calibration_complete(_make_state()) is True

    def test_incomplete_when_no_velocity(self) -> None:
        state = DopplerCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=0),
            baseline_y_px=0.0,
        )
        assert is_calibration_complete(state) is False


class TestBuildAxisMapping:
    def test_returns_doppler_axis_mapping(self) -> None:
        state = _make_state()
        result = build_axis_mapping(state)
        assert isinstance(result, DopplerAxisMapping)
        assert result.roi == state.roi
        assert result.baseline_y_px == 45.0

    def test_velocity_half_span(self) -> None:
        state = _make_state()
        result = build_axis_mapping(state)
        assert result.velocity_min_cm_s == -100.0
        assert result.velocity_max_cm_s == 100.0

    def test_plot_dimensions_match_roi(self) -> None:
        state = _make_state()
        result = build_axis_mapping(state)
        assert result.plot_width == 100.0
        assert result.plot_height == 50.0


class TestCalibrationFromRoiAndBaseline:
    def test_default_spectral_span(self) -> None:
        roi = _make_roi()
        result = calibration_from_roi_and_baseline(roi, 40.0)
        assert result.velocity_span_cm_s == 200.0
        assert result.kind == DopplerKind.SPECTRAL

    def test_tissue_span(self) -> None:
        roi = _make_roi()
        result = calibration_from_roi_and_baseline(
            roi, 40.0, kind=DopplerKind.TISSUE,
        )
        assert result.velocity_span_cm_s == 40.0

    def test_custom_velocity_span(self) -> None:
        roi = _make_roi()
        result = calibration_from_roi_and_baseline(
            roi, 40.0, velocity_span_cm_s=150.0,
        )
        assert result.velocity_span_cm_s == 150.0


class TestRoiFromCorners:
    def test_normalizes_corners(self) -> None:
        roi = roi_from_corners((50.0, 30.0), (10.0, 5.0))
        assert roi.x0 == 10.0
        assert roi.y0 == 5.0
        assert roi.width == 40.0
        assert roi.height == 25.0

    def test_same_point_gives_minimal_roi(self) -> None:
        roi = roi_from_corners((10.0, 10.0), (10.0, 10.0))
        assert roi.width == 1.0
        assert roi.height == 1.0
