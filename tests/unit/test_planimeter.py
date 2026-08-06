"""Unit tests for planimeter area/volume calculations."""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.calculations.planimeter import (
    closed_polygon_area_cm2,
    closed_polygon_volume_ml,
    format_area_result,
    format_volume_result,
    is_planimeter_polygon,
    next_area_label,
    next_volume_label,
)
from echo_personal_tool.domain.models.contour import Contour


def _rect_contour(
    chamber: str = "AREA",
    width: float = 100.0,
    height: float = 50.0,
    label: str | None = None,
    open_arc: bool = False,
) -> Contour:
    if open_arc:
        return Contour(
            phase="ED",
            chamber=chamber,
            points=[(0.0, 0.0), (width, 0.0), (width, height)],
            mitral_annulus=((0.0, 0.0), (width, 0.0)),
            measurement_label=label,
        )
    return Contour(
        phase="ED",
        chamber=chamber,
        points=[(0.0, 0.0), (width, 0.0), (width, height), (0.0, height)],
        measurement_label=label,
    )


class TestIsPlanimeterPolygon:
    def test_area_chamber(self) -> None:
        assert is_planimeter_polygon(Contour(phase="ED", chamber="AREA")) is True

    def test_volume_chamber(self) -> None:
        assert is_planimeter_polygon(Contour(phase="ED", chamber="VOL")) is True

    def test_lv_chamber(self) -> None:
        assert is_planimeter_polygon(Contour(phase="ED", chamber="LV")) is False

    def test_case_insensitive(self) -> None:
        assert is_planimeter_polygon(Contour(phase="ED", chamber="area")) is True
        assert is_planimeter_polygon(Contour(phase="ED", chamber="vol")) is True


class TestNextAreaLabel:
    def test_first_area(self) -> None:
        assert next_area_label(()) == "Площадь1"

    def test_second_area(self) -> None:
        contours = (
            Contour(phase="ED", chamber="AREA"),
            Contour(phase="ED", chamber="LV"),
        )
        assert next_area_label(contours) == "Площадь2"


class TestNextVolumeLabel:
    def test_first_volume(self) -> None:
        assert next_volume_label(()) == "Объем1"

    def test_second_volume(self) -> None:
        contours = (Contour(phase="ED", chamber="VOL"),)
        assert next_volume_label(contours) == "Объем2"


class TestClosedPolygonAreaCm2:
    def test_returns_area_in_cm2(self) -> None:
        c = _rect_contour(width=10.0, height=10.0)
        result = closed_polygon_area_cm2(c, (1.0, 1.0))
        assert result is not None
        assert result == pytest.approx(1.0)  # 10x10 px → 100 mm² → 1.0 cm²

    def test_returns_none_for_open_arc(self) -> None:
        c = _rect_contour(open_arc=True)
        assert closed_polygon_area_cm2(c, (1.0, 1.0)) is None

    def test_returns_none_for_fewer_than_3_points(self) -> None:
        c = Contour(phase="ED", chamber="AREA", points=[(0, 0), (10, 0)])
        assert closed_polygon_area_cm2(c, (1.0, 1.0)) is None

    def test_with_pixel_spacing(self) -> None:
        c = _rect_contour(width=10.0, height=10.0)
        result = closed_polygon_area_cm2(c, (0.5, 0.5))
        assert result == pytest.approx(0.25)  # 5x5 mm → 25 mm² → 0.25 cm²


class TestClosedPolygonVolumeMl:
    def test_returns_volume_for_closed_contour(self) -> None:
        c = _rect_contour(width=20.0, height=20.0)
        result = closed_polygon_volume_ml(c, (1.0, 1.0))
        assert result is not None
        assert result > 0.0

    def test_returns_none_for_open_arc(self) -> None:
        c = _rect_contour(open_arc=True)
        assert closed_polygon_volume_ml(c, (1.0, 1.0)) is None


class TestFormatAreaResult:
    def test_returns_dash_when_no_spacing(self) -> None:
        c = _rect_contour()
        result = format_area_result(c, None, spacing_calibrated=True)
        assert "—" in result

    def test_calibrated_format(self) -> None:
        c = _rect_contour(width=10.0, height=10.0)
        result = format_area_result(c, (1.0, 1.0), spacing_calibrated=True)
        assert "cm²" in result

    def test_uncalibrated_format(self) -> None:
        c = _rect_contour(width=10.0, height=10.0)
        result = format_area_result(c, (1.0, 1.0), spacing_calibrated=False)
        assert "px²" in result

    def test_custom_label(self) -> None:
        c = _rect_contour(width=10.0, height=10.0, label="Левое предсердие")
        result = format_area_result(c, (1.0, 1.0), spacing_calibrated=True)
        assert result.startswith("Левое предсердие")


class TestFormatVolumeResult:
    def test_returns_dash_when_no_spacing(self) -> None:
        c = _rect_contour()
        result = format_volume_result(c, None, spacing_calibrated=True)
        assert "—" in result

    def test_calibrated_format(self) -> None:
        c = _rect_contour(width=20.0, height=20.0)
        result = format_volume_result(c, (1.0, 1.0), spacing_calibrated=True)
        assert "mL" in result

    def test_uncalibrated_format(self) -> None:
        c = _rect_contour(width=20.0, height=20.0)
        result = format_volume_result(c, (1.0, 1.0), spacing_calibrated=False)
        assert "px³" in result
