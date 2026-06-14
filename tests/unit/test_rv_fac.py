"""Tests for RV fractional area change."""

from __future__ import annotations

from echo_personal_tool.domain.calculations.rv_fac import fac_percent, from_rv_contours
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
