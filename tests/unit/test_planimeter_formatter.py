"""Unit tests for planimeter formatter."""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.services.planimeter_formatter import (
    format_planimeter_overlay_line,
    planimeter_results_from_contours,
)


def _rect(chamber: str, w: float = 10.0, h: float = 10.0) -> Contour:
    return Contour(
        phase="ED",
        chamber=chamber,
        points=[(0.0, 0.0), (w, 0.0), (w, h), (0.0, h)],
    )


class TestPlanimeterResultsFromContours:
    def test_empty_contours(self) -> None:
        assert planimeter_results_from_contours((), (1.0, 1.0), spacing_calibrated=True) == ()

    def test_none_spacing(self) -> None:
        contours = (_rect("AREA"),)
        assert planimeter_results_from_contours(contours, None, spacing_calibrated=True) == ()

    def test_area_contour(self) -> None:
        contours = (_rect("AREA", 10.0, 10.0),)
        results = planimeter_results_from_contours(contours, (1.0, 1.0), spacing_calibrated=True)
        assert len(results) == 1
        assert results[0].kind == "area"
        assert results[0].unit == "cm²"

    def test_volume_contour(self) -> None:
        contours = (_rect("VOL", 20.0, 20.0),)
        results = planimeter_results_from_contours(contours, (1.0, 1.0), spacing_calibrated=True)
        assert len(results) == 1
        assert results[0].kind == "volume"
        assert results[0].unit == "mL"

    def test_volume_uncalibrated(self) -> None:
        contours = (_rect("VOL", 20.0, 20.0),)
        results = planimeter_results_from_contours(contours, (1.0, 1.0), spacing_calibrated=False)
        assert results[0].unit == "px³"

    def test_lv_chamber_ignored(self) -> None:
        contours = (_rect("LV"),)
        assert planimeter_results_from_contours(contours, (1.0, 1.0), spacing_calibrated=True) == ()

    def test_custom_label(self) -> None:
        c = _rect("AREA")
        c = Contour(phase="ED", chamber="AREA", points=c.points, measurement_label="My Area")
        results = planimeter_results_from_contours((c,), (1.0, 1.0), spacing_calibrated=True)
        assert results[0].label == "My Area"


class TestFormatPlanimeterOverlayLine:
    def test_area(self) -> None:
        c = _rect("AREA", 10.0, 10.0)
        result = format_planimeter_overlay_line(c, (1.0, 1.0), spacing_calibrated=True)
        assert "cm²" in result

    def test_volume(self) -> None:
        c = _rect("VOL", 20.0, 20.0)
        result = format_planimeter_overlay_line(c, (1.0, 1.0), spacing_calibrated=True)
        assert "mL" in result

    def test_unknown_chamber(self) -> None:
        c = _rect("LV")
        result = format_planimeter_overlay_line(c, (1.0, 1.0), spacing_calibrated=True)
        assert result == ""
