"""Unit tests for Simpson LVEF calculations."""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.calculations.lvef_simpson import calculate
from echo_personal_tool.domain.models import Contour


def rectangle_contour(
    *,
    phase: str,
    view: str,
    width_px: float,
    height_px: float,
) -> Contour:
    return Contour(
        phase=phase,
        view=view,
        points=[
            (0.0, 0.0),
            (width_px, 0.0),
            (width_px, height_px),
            (0.0, height_px),
        ],
    )


def open_arc_contour(*, phase: str, view: str, width_px: float, height_px: float) -> Contour:
    import math

    n = 9
    annulus = ((0.0, 0.0), (width_px, 0.0))
    angles = [math.pi - i * math.pi / (n - 1) for i in range(n)]
    points = [
        (width_px / 2.0 + (width_px / 2.0) * math.cos(a), height_px * math.sin(a))
        for a in angles
    ]
    return Contour(phase=phase, view=view, mitral_annulus=annulus, points=points)


def test_calculate_monoplan_rectangle_volume() -> None:
    contours = (
        rectangle_contour(phase="ed", view="a4c", width_px=100.0, height_px=50.0),
        rectangle_contour(phase="Es", view="A4C", width_px=80.0, height_px=40.0),
    )

    result = calculate(contours, (0.5, 0.5))

    assert result is not None
    assert result.a4c is not None
    assert result.a4c.edv_ml == pytest.approx(49.087385, rel=1e-6)
    assert result.a4c.esv_ml == pytest.approx(25.132741, rel=1e-6)
    assert result.lvef_percent == pytest.approx(48.8, rel=1e-6)
    assert result.method == "simpson_monoplan"


def test_calculate_ed_larger_than_es_yields_positive_lvef() -> None:
    contours = (
        rectangle_contour(phase="ED", view="A4C", width_px=100.0, height_px=50.0),
        rectangle_contour(phase="ES", view="A4C", width_px=70.0, height_px=35.0),
    )

    result = calculate(contours, (0.5, 0.5))

    assert result is not None
    assert result.lvef_percent is not None
    assert result.lvef_percent > 0.0


def test_calculate_missing_spacing_returns_none() -> None:
    contours = (
        rectangle_contour(phase="ED", view="A4C", width_px=100.0, height_px=50.0),
        rectangle_contour(phase="ES", view="A4C", width_px=80.0, height_px=40.0),
    )

    assert calculate(contours, None) is None  # type: ignore[arg-type]


def test_calculate_biplan_averages_views() -> None:
    contours = (
        rectangle_contour(phase="ED", view="A4C", width_px=100.0, height_px=50.0),
        rectangle_contour(phase="ES", view="A4C", width_px=80.0, height_px=40.0),
        rectangle_contour(phase="ED", view="A2C", width_px=120.0, height_px=50.0),
        rectangle_contour(phase="ES", view="A2C", width_px=100.0, height_px=40.0),
    )

    result = calculate(contours, (0.5, 0.5))

    assert result is not None
    assert result.method == "simpson_biplan"
    assert result.lvef_percent == pytest.approx(46.22950819672132, rel=1e-6)


def test_calculate_single_ed_returns_partial_a4c_metrics() -> None:
    contours = (
        open_arc_contour(phase="ED", view="A4C", width_px=100.0, height_px=50.0),
    )
    result = calculate(contours, (0.5, 0.5))

    assert result is not None
    assert result.a4c is not None
    assert result.a4c.edv_ml is not None
    assert result.a4c.edv_ml > 0.0
    assert result.a4c.length_ed_mm is not None
    assert result.a4c.length_ed_mm > 0.0
    assert result.a4c.esv_ml is None
    assert result.lvef_percent is None
    assert result.method is None


def test_calculate_biplan_populates_both_views() -> None:
    contours = (
        open_arc_contour(phase="ED", view="A4C", width_px=100.0, height_px=50.0),
        open_arc_contour(phase="ES", view="A4C", width_px=80.0, height_px=40.0),
        open_arc_contour(phase="ED", view="A2C", width_px=120.0, height_px=50.0),
        open_arc_contour(phase="ES", view="A2C", width_px=100.0, height_px=40.0),
    )
    result = calculate(contours, (0.5, 0.5))
    assert result is not None
    assert result.a4c is not None
    assert result.a2c is not None
    assert result.method == "simpson_biplan"


def test_calculate_open_arc_monoplan() -> None:
    contours = (
        open_arc_contour(phase="ed", view="A4C", width_px=100.0, height_px=50.0),
        open_arc_contour(phase="es", view="A4C", width_px=80.0, height_px=40.0),
    )
    result = calculate(contours, (0.5, 0.5))

    assert result is not None
    assert result.a4c is not None
    assert result.method == "simpson_monoplan"
    assert result.a4c.edv_ml == pytest.approx(31.498208, rel=1e-4)
    assert result.a4c.esv_ml == pytest.approx(16.127083, rel=1e-4)
