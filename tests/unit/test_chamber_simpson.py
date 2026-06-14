"""Unit tests for LA/RA/RV Simpson chamber volumes."""

from __future__ import annotations

from echo_personal_tool.domain.calculations.chamber_simpson import calculate_chamber
from echo_personal_tool.domain.models import Contour


def _open_arc(*, chamber: str, phase: str, view: str, width: float, height: float) -> Contour:
    import math

    annulus = ((0.0, 0.0), (width, 0.0))
    n = 9
    angles = [math.pi - i * math.pi / (n - 1) for i in range(n)]
    points = [
        (width / 2.0 + (width / 2.0) * math.cos(a), height * math.sin(a)) for a in angles
    ]
    return Contour(
        phase=phase,
        view=view,
        chamber=chamber,
        mitral_annulus=annulus,
        points=points,
    )


def test_la_simpson_monoplan_volume() -> None:
    contours = (
        _open_arc(chamber="LA", phase="ES", view="A4C", width=80.0, height=50.0),
        _open_arc(chamber="LA", phase="ED", view="A4C", width=90.0, height=55.0),
    )

    result = calculate_chamber(contours, "LA", (0.5, 0.5))

    assert result is not None
    assert result.chamber == "LA"
    assert result.a4c is not None
    assert result.a4c.esv_ml is not None
    assert result.max_volume_ml is not None
    assert result.max_volume_ml >= result.a4c.esv_ml


def test_la_simpson_includes_area_cm2() -> None:
    contours = (_open_arc(chamber="LA", phase="ES", view="A4C", width=80.0, height=50.0),)

    result = calculate_chamber(contours, "LA", (0.5, 0.5))

    assert result is not None
    assert result.area_cm2 is not None
    assert result.area_cm2 > 0.0


def test_rv_simpson_ef_when_ed_and_es_present() -> None:
    contours = (
        _open_arc(chamber="RV", phase="ED", view="A4C", width=100.0, height=60.0),
        _open_arc(chamber="RV", phase="ES", view="A4C", width=80.0, height=45.0),
    )

    result = calculate_chamber(contours, "RV", (0.5, 0.5))

    assert result is not None
    assert result.ef_percent is not None
    assert result.ef_percent > 0.0
    assert result.method == "simpson_monoplan"


def test_chamber_calculator_ignores_other_chambers() -> None:
    contours = (
        _open_arc(chamber="LA", phase="ES", view="A4C", width=80.0, height=50.0),
        _open_arc(chamber="LV", phase="ED", view="A4C", width=100.0, height=60.0),
    )

    result = calculate_chamber(contours, "LA", (0.5, 0.5))

    assert result is not None
    assert result.a4c is not None
    assert result.a4c.edv_ml is None


def test_ra_simpson_includes_area_cm2() -> None:
    contours = (_open_arc(chamber="RA", phase="ES", view="A4C", width=80.0, height=50.0),)

    result = calculate_chamber(contours, "RA", (0.5, 0.5))

    assert result is not None
    assert result.area_cm2 is not None
    assert result.area_cm2 > 0.0
