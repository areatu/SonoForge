"""Tests for RV fractional area change."""

from __future__ import annotations

from echo_personal_tool.domain.calculations.rv_fac import (
    fac_percent,
    format_rv_area_overlay_line,
    from_rv_contours,
    rv_area_mm2,
)
from echo_personal_tool.domain.models import Contour


def test_fac_percent_basic() -> None:
    assert fac_percent(100.0, 60.0) == 40.0


def test_from_rv_contours_requires_ed_and_es() -> None:
    ed = Contour(
        phase="ED",
        view="A4C",
        chamber="RV",
        mitral_annulus=((0.0, 0.0), (100.0, 0.0)),
        points=[(0.0, 0.0), (50.0, 80.0), (100.0, 0.0)],
    )
    assert from_rv_contours((ed,), (1.0, 1.0)) is None

    es = Contour(
        phase="ES",
        view="A4C",
        chamber="RV",
        mitral_annulus=((0.0, 0.0), (100.0, 0.0)),
        points=[(0.0, 0.0), (50.0, 40.0), (100.0, 0.0)],
    )
    fac = from_rv_contours((ed, es), (1.0, 1.0))
    assert fac is not None
    assert 0.0 < fac < 100.0


def test_rv_area_overlay_line() -> None:
    contour = Contour(
        phase="ED",
        view="A4C",
        chamber="RV",
        mitral_annulus=((0.0, 0.0), (100.0, 0.0)),
        points=[(0.0, 0.0), (50.0, 80.0), (100.0, 0.0)],
    )
    line = format_rv_area_overlay_line(contour, (1.0, 1.0))
    assert "RV FAC ED" in line
    assert "mm²" in line
    assert rv_area_mm2(contour, (1.0, 1.0)) == 4000.0
