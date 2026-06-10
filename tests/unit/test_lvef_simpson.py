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


def test_calculate_monoplan_rectangle_volume() -> None:
    contours = (
        rectangle_contour(phase="ed", view="a4c", width_px=100.0, height_px=50.0),
        rectangle_contour(phase="Es", view="A4C", width_px=80.0, height_px=40.0),
    )

    result = calculate(contours, (0.5, 0.5))

    assert result is not None
    assert result.method == "simpson_monoplan"
    assert result.edv_ml == pytest.approx(49.087385, rel=1e-6)
    assert result.esv_ml == pytest.approx(25.132741, rel=1e-6)
    assert result.lvef_percent == pytest.approx(48.8, rel=1e-6)


def test_calculate_ed_larger_than_es_yields_positive_lvef() -> None:
    contours = (
        rectangle_contour(phase="ED", view="A4C", width_px=100.0, height_px=50.0),
        rectangle_contour(phase="ES", view="A4C", width_px=70.0, height_px=35.0),
    )

    result = calculate(contours, (0.5, 0.5))

    assert result is not None
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
    assert result.edv_ml == pytest.approx(59.886609959055434, rel=1e-6)
    assert result.esv_ml == pytest.approx(32.201325, rel=1e-6)
    assert result.lvef_percent == pytest.approx(46.22950819672132, rel=1e-6)


def test_calculate_without_ed_es_pair_returns_none() -> None:
    contours = (
        rectangle_contour(phase="ED", view="A4C", width_px=100.0, height_px=50.0),
    )

    assert calculate(contours, (0.5, 0.5)) is None
