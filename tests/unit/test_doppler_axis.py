"""Unit tests for DopplerAxisMapping."""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.models.doppler_axis import DopplerAxisMapping
from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi


class TestDopplerAxisMappingDefaults:
    def test_poc_default(self) -> None:
        m = DopplerAxisMapping.poc_default()
        assert m.time_span_ms == 1000.0
        assert m.velocity_span_cm_s == 200.0

    def test_from_frame_size(self) -> None:
        m = DopplerAxisMapping.from_frame_size(800.0, 200.0, velocity_span_cm_s=150.0)
        assert m.plot_width == 800.0
        assert m.plot_height == 200.0
        assert m.velocity_min_cm_s == -75.0
        assert m.velocity_max_cm_s == 75.0


class TestHasRoiCalibration:
    def test_false_without_roi(self) -> None:
        m = DopplerAxisMapping()
        assert m.has_roi_calibration is False

    def test_true_with_roi_and_baseline(self) -> None:
        roi = DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50)
        m = DopplerAxisMapping(roi=roi, baseline_y_px=25.0)
        assert m.has_roi_calibration is True

    def test_false_without_baseline(self) -> None:
        roi = DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50)
        m = DopplerAxisMapping(roi=roi)
        assert m.has_roi_calibration is False


class TestTimeConversion:
    def test_time_ms_from_x(self) -> None:
        m = DopplerAxisMapping(time_origin_ms=100.0, time_span_ms=800.0, plot_width=100.0, plot_origin_x=0.0)
        # x = plot_width → time = origin + span = 900
        assert m.time_ms_from_x(100.0) == pytest.approx(900.0)

    def test_x_from_time_ms(self) -> None:
        m = DopplerAxisMapping(time_origin_ms=100.0, time_span_ms=800.0, plot_width=100.0, plot_origin_x=0.0)
        assert m.x_from_time_ms(900.0) == pytest.approx(100.0)

    def test_roundtrip(self) -> None:
        m = DopplerAxisMapping(time_origin_ms=0.0, time_span_ms=1000.0, plot_width=500.0)
        x = m.x_from_time_ms(250.0)
        assert m.time_ms_from_x(x) == pytest.approx(250.0)

    def test_zero_width(self) -> None:
        m = DopplerAxisMapping(plot_width=0.0)
        assert m.time_ms_from_x(50.0) == 0.0
        assert m.x_from_time_ms(500.0) == 0.0


class TestVelocityConversion:
    def test_velocity_with_baseline(self) -> None:
        m = DopplerAxisMapping(
            baseline_y_px=100.0, velocity_span_cm_s=200.0,
            plot_height=100.0, plot_origin_y=50.0,
        )
        # y = baseline → velocity = 0
        v = m.velocity_cm_s_from_y(100.0)
        assert v == pytest.approx(0.0)

    def test_velocity_above_baseline_is_positive(self) -> None:
        m = DopplerAxisMapping(
            baseline_y_px=100.0, velocity_span_cm_s=200.0,
            plot_height=100.0,
        )
        v = m.velocity_cm_s_from_y(50.0)  # above baseline → positive
        assert v > 0.0

    def test_y_from_velocity_with_baseline(self) -> None:
        m = DopplerAxisMapping(
            baseline_y_px=100.0, velocity_span_cm_s=200.0,
            plot_height=100.0,
        )
        y = m.y_from_velocity_cm_s(0.0)
        assert y == pytest.approx(100.0)

    def test_roundtrip_with_baseline(self) -> None:
        m = DopplerAxisMapping(
            baseline_y_px=100.0, velocity_span_cm_s=200.0,
            plot_height=100.0,
        )
        y = m.y_from_velocity_cm_s(50.0)
        v = m.velocity_cm_s_from_y(y)
        assert v == pytest.approx(50.0)

    def test_velocity_without_baseline(self) -> None:
        m = DopplerAxisMapping(
            plot_height=100.0, plot_origin_y=0.0,
            velocity_min_cm_s=-100.0, velocity_max_cm_s=100.0,
        )
        v = m.velocity_cm_s_from_y(0.0)
        assert v == pytest.approx(100.0)  # top of plot = max velocity

    def test_y_from_velocity_without_baseline(self) -> None:
        m = DopplerAxisMapping(
            plot_height=100.0, plot_origin_y=0.0,
            velocity_min_cm_s=-100.0, velocity_max_cm_s=100.0,
        )
        y = m.y_from_velocity_cm_s(100.0)
        assert y == pytest.approx(0.0)

    def test_zero_height(self) -> None:
        m = DopplerAxisMapping(plot_height=0.0)
        assert m.velocity_cm_s_from_y(50.0) == 0.0
        assert m.y_from_velocity_cm_s(50.0) == 0.0

    def test_baseline_plot_y(self) -> None:
        m = DopplerAxisMapping(baseline_y_px=75.0)
        assert m.baseline_plot_y() == 75.0

    def test_baseline_plot_y_none(self) -> None:
        m = DopplerAxisMapping()
        assert m.baseline_plot_y() is None
