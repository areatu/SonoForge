"""Tests for planimeter_formatter module."""

from __future__ import annotations

from unittest.mock import patch

from echo_personal_tool.domain.calculations.planimeter import (
    GENERIC_AREA_CHAMBER,
    GENERIC_VOLUME_CHAMBER,
)
from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.services.planimeter_formatter import (
    format_planimeter_overlay_line,
    planimeter_results_from_contours,
)


def _area_contour():
    return Contour(
        phase="ED",
        chamber=GENERIC_AREA_CHAMBER,
        points=[(10, 10), (50, 10), (50, 50), (10, 50)],
        measurement_label="Area1",
    )


def _volume_contour():
    return Contour(
        phase="ED",
        chamber=GENERIC_VOLUME_CHAMBER,
        points=[(10, 10), (50, 10), (50, 50), (10, 50)],
        measurement_label="Vol1",
    )


def _lv_contour():
    return Contour(
        phase="ED",
        chamber="LV",
        points=[(10, 10), (50, 10), (50, 50), (10, 50)],
    )


class TestPlanimeterResultsFromContours:
    def test_no_pixel_spacing(self):
        result = planimeter_results_from_contours((_area_contour(),), None, spacing_calibrated=True)
        assert result == ()

    def test_area_contour(self):
        contours = (_area_contour(),)
        with patch(
            "echo_personal_tool.domain.services.planimeter_formatter.closed_polygon_area_cm2",
            return_value=12.5,
        ):
            result = planimeter_results_from_contours(contours, (1.0, 1.0), spacing_calibrated=True)
        assert len(result) == 1
        assert result[0].kind == "area"
        assert result[0].value == 12.5
        assert result[0].label == "Area1"

    def test_volume_contour(self):
        contours = (_volume_contour(),)
        with patch(
            "echo_personal_tool.domain.services.planimeter_formatter.closed_polygon_volume_ml",
            return_value=80.0,
        ):
            result = planimeter_results_from_contours(contours, (1.0, 1.0), spacing_calibrated=True)
        assert len(result) == 1
        assert result[0].kind == "volume"
        assert result[0].value == 80.0
        assert result[0].unit == "mL"

    def test_volume_uncalibrated(self):
        contours = (_volume_contour(),)
        with patch(
            "echo_personal_tool.domain.services.planimeter_formatter.closed_polygon_volume_ml",
            return_value=80.0,
        ):
            result = planimeter_results_from_contours(contours, (1.0, 1.0), spacing_calibrated=False)
        assert result[0].unit == "px³"

    def test_lv_contour_ignored(self):
        result = planimeter_results_from_contours(
            (_lv_contour(),), (1.0, 1.0), spacing_calibrated=True,
        )
        assert result == ()

    def test_multiple_contours(self):
        contours = (_area_contour(), _volume_contour())
        with patch(
            "echo_personal_tool.domain.services.planimeter_formatter.closed_polygon_area_cm2",
            return_value=10.0,
        ), patch(
            "echo_personal_tool.domain.services.planimeter_formatter.closed_polygon_volume_ml",
            return_value=50.0,
        ):
            result = planimeter_results_from_contours(contours, (1.0, 1.0), spacing_calibrated=True)
        assert len(result) == 2

    def test_area_none_skipped(self):
        contours = (_area_contour(),)
        with patch(
            "echo_personal_tool.domain.services.planimeter_formatter.closed_polygon_area_cm2",
            return_value=None,
        ):
            result = planimeter_results_from_contours(contours, (1.0, 1.0), spacing_calibrated=True)
        assert result == ()

    def test_fallback_label(self):
        c = Contour(phase="ED", chamber=GENERIC_AREA_CHAMBER, points=[(0, 0), (10, 0), (10, 10)])
        with patch(
            "echo_personal_tool.domain.services.planimeter_formatter.closed_polygon_area_cm2",
            return_value=5.0,
        ):
            result = planimeter_results_from_contours((c,), (1.0, 1.0), spacing_calibrated=True)
        assert result[0].label == GENERIC_AREA_CHAMBER


class TestFormatPlanimeterOverlayLine:
    def test_area_format(self):
        c = _area_contour()
        with patch(
            "echo_personal_tool.domain.services.planimeter_formatter.format_area_result",
            return_value="Area1: 12.34 cm²",
        ):
            line = format_planimeter_overlay_line(c, (1.0, 1.0), spacing_calibrated=True)
        assert "12.34" in line

    def test_volume_format(self):
        c = _volume_contour()
        with patch(
            "echo_personal_tool.domain.services.planimeter_formatter.format_volume_result",
            return_value="Vol1: 80.0 mL",
        ):
            line = format_planimeter_overlay_line(c, (1.0, 1.0), spacing_calibrated=True)
        assert "80.0" in line

    def test_unknown_chamber(self):
        c = _lv_contour()
        line = format_planimeter_overlay_line(c, (1.0, 1.0), spacing_calibrated=True)
        assert line == ""
