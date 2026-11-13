"""Unit tests for LA/RA/RV Simpson chamber volumes."""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.calculations.chamber_simpson import (
    calculate_chamber,
    confirmed_biplane_es_volume_ml,
    confirmed_biplane_index_ml_m2,
    mean_es_volume_ml,
)
from echo_personal_tool.domain.models import Contour


def _open_arc(
    *,
    chamber: str,
    phase: str,
    view: str,
    width: float,
    height: float,
    review_pending: bool = False,
) -> Contour:
    import math

    annulus = ((0.0, 0.0), (width, 0.0))
    n = 9
    angles = [math.pi - i * math.pi / (n - 1) for i in range(n)]
    points = [(width / 2.0 + (width / 2.0) * math.cos(a), height * math.sin(a)) for a in angles]
    return Contour(
        phase=phase,
        view=view,
        chamber=chamber,
        mitral_annulus=annulus,
        points=points,
        review_pending=review_pending,
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


@pytest.mark.parametrize("chamber", ["LA", "RA", "RV"])
def test_pending_contour_alone_produces_no_numbers(chamber: str) -> None:
    pending = _open_arc(
        chamber=chamber,
        phase="ES",
        view="A4C",
        width=200.0,
        height=200.0,
        review_pending=True,
    )

    assert calculate_chamber((pending,), chamber, (0.5, 0.5)) is None


@pytest.mark.parametrize("chamber", ["LA", "RA", "RV"])
def test_pending_contour_does_not_change_accepted_chamber_result(chamber: str) -> None:
    accepted = _open_arc(chamber=chamber, phase="ES", view="A4C", width=80.0, height=50.0)
    pending = _open_arc(
        chamber=chamber,
        phase="ED",
        view="A4C",
        width=200.0,
        height=200.0,
        review_pending=True,
    )

    baseline = calculate_chamber((accepted,), chamber, (0.5, 0.5))
    with_pending = calculate_chamber((accepted, pending), chamber, (0.5, 0.5))

    assert baseline is not None
    assert with_pending == baseline


def test_two_views_are_reported_as_mean_of_monoplanes_not_biplane() -> None:
    contours = (
        _open_arc(chamber="LA", phase="ED", view="A4C", width=80.0, height=50.0),
        _open_arc(chamber="LA", phase="ES", view="A4C", width=60.0, height=40.0),
        _open_arc(chamber="LA", phase="ED", view="A2C", width=90.0, height=60.0),
        _open_arc(chamber="LA", phase="ES", view="A2C", width=70.0, height=45.0),
    )

    result = calculate_chamber(contours, "LA", (0.5, 0.5))

    assert result is not None
    assert result.method == "simpson_mean_monoplan"
    assert result.method != "simpson_biplan"
    assert result.biplane_es_ml is None
    assert result.biplane_verified is False
    assert confirmed_biplane_es_volume_ml(result) is None
    assert mean_es_volume_ml(result.a4c, result.a2c) is not None


def test_legacy_biplane_flag_without_confirmation_is_not_trusted() -> None:
    from dataclasses import replace

    contours = (
        _open_arc(chamber="LA", phase="ED", view="A4C", width=80.0, height=50.0),
        _open_arc(chamber="LA", phase="ES", view="A4C", width=60.0, height=40.0),
        _open_arc(chamber="LA", phase="ED", view="A2C", width=90.0, height=60.0),
        _open_arc(chamber="LA", phase="ES", view="A2C", width=70.0, height=45.0),
    )
    result = calculate_chamber(contours, "LA", (0.5, 0.5))
    assert result is not None

    legacy = replace(result, method="simpson_biplan", biplane_es_ml=55.0, biplane_verified=False)
    assert confirmed_biplane_es_volume_ml(legacy) is None
    assert confirmed_biplane_index_ml_m2(30.0, legacy) is None
    confirmed = replace(legacy, biplane_verified=True)
    assert confirmed_biplane_es_volume_ml(confirmed) == pytest.approx(55.0)
    assert confirmed_biplane_index_ml_m2(30.0, confirmed) == pytest.approx(30.0)
    assert confirmed_biplane_index_ml_m2(float("nan"), confirmed) is None


def test_flagged_volume_with_unknown_method_is_not_biplane() -> None:
    from dataclasses import replace

    from echo_personal_tool.domain.models.measurements import ChamberSimpsonResult

    mean = ChamberSimpsonResult(
        chamber="LA",
        method="simpson_mean_monoplan",
        biplane_es_ml=55.0,
        biplane_verified=True,
    )
    assert confirmed_biplane_es_volume_ml(mean) is None
    assert confirmed_biplane_es_volume_ml(replace(mean, method=None)) is None


def test_mean_of_es_does_not_mix_an_ed_volume_from_the_other_view() -> None:
    from echo_personal_tool.domain.models import LvViewMetrics

    assert mean_es_volume_ml(LvViewMetrics(esv_ml=40.0), LvViewMetrics(edv_ml=50.0)) is None
    assert mean_es_volume_ml(LvViewMetrics(esv_ml=40.0), LvViewMetrics(esv_ml=50.0)) == pytest.approx(45.0)
