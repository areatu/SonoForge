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
    segments: int = 9,
) -> Contour:
    import math

    annulus = ((0.0, 0.0), (width, 0.0))
    n = segments
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
    assert result.method == "simpson_monoplan"
    assert result.biplane_es_ml is None
    assert result.biplane_verified is False


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


def test_la_two_views_use_the_true_coupled_biplane_volume() -> None:
    contours = (
        _open_arc(chamber="LA", phase="ED", view="A4C", width=80.0, height=50.0),
        _open_arc(chamber="LA", phase="ES", view="A4C", width=60.0, height=40.0),
        _open_arc(chamber="LA", phase="ED", view="A2C", width=90.0, height=60.0),
        _open_arc(chamber="LA", phase="ES", view="A2C", width=70.0, height=45.0),
    )

    result = calculate_chamber(contours, "LA", (0.5, 0.5))

    assert result is not None
    assert result.method == "simpson_biplan"
    assert result.biplane_verified is True
    assert result.biplane_es_ml is not None
    assert confirmed_biplane_es_volume_ml(result) == pytest.approx(result.biplane_es_ml)
    # The coupled volume is not the mean of the two monoplane volumes.
    mean = mean_es_volume_ml(result.a4c, result.a2c)
    assert mean is not None
    assert result.biplane_es_ml != pytest.approx(mean, rel=0.001)


def test_la_biplane_matches_the_analytic_coupled_disk_formula() -> None:
    import math

    contours = (
        _open_arc(chamber="LA", phase="ES", view="A4C", width=40.0, height=100.0, segments=720),
        _open_arc(chamber="LA", phase="ES", view="A2C", width=20.0, height=100.0, segments=720),
    )

    result = calculate_chamber(contours, "LA", (1.0, 1.0))

    assert result is not None
    assert result.biplane_es_ml is not None
    disk_sum = sum(1.0 - ((index + 0.5) / 20.0) ** 2 for index in range(20))
    expected = math.pi / 4.0 * 40.0 * 20.0 * (100.0 / 20.0) * disk_sum / 1000.0
    expected_a4c = math.pi / 4.0 * 40.0**2 * (100.0 / 20.0) * disk_sum / 1000.0
    expected_a2c = math.pi / 4.0 * 20.0**2 * (100.0 / 20.0) * disk_sum / 1000.0
    assert result.biplane_es_ml == pytest.approx(expected, rel=0.002)
    assert mean_es_volume_ml(result.a4c, result.a2c) == pytest.approx((expected_a4c + expected_a2c) / 2.0, rel=0.002)
    # Different diameters make the mean materially larger than the true biplane.
    assert result.biplane_es_ml < mean_es_volume_ml(result.a4c, result.a2c) * 0.9


def test_biplane_requires_the_same_phase_in_both_views() -> None:
    contours = (
        _open_arc(chamber="LA", phase="ED", view="A4C", width=40.0, height=100.0),
        _open_arc(chamber="LA", phase="ES", view="A4C", width=30.0, height=90.0),
        _open_arc(chamber="LA", phase="ED", view="A2C", width=20.0, height=100.0),
    )

    result = calculate_chamber(contours, "LA", (1.0, 1.0))

    assert result is not None
    assert result.biplane_es_ml is None
    assert result.biplane_verified is False
    assert result.method != "simpson_biplan"


@pytest.mark.parametrize("chamber", ["RA", "RV"])
def test_ra_and_rv_two_views_stay_descriptive_not_biplane(chamber: str) -> None:
    contours = (
        _open_arc(chamber=chamber, phase="ED", view="A4C", width=80.0, height=50.0),
        _open_arc(chamber=chamber, phase="ES", view="A4C", width=60.0, height=40.0),
        _open_arc(chamber=chamber, phase="ED", view="A2C", width=90.0, height=60.0),
        _open_arc(chamber=chamber, phase="ES", view="A2C", width=70.0, height=45.0),
    )

    result = calculate_chamber(contours, chamber, (0.5, 0.5))

    assert result is not None
    assert result.method == "simpson_mean_monoplan"
    assert result.biplane_es_ml is None
    assert result.biplane_verified is False


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


def test_la_biplane_ef_uses_the_same_coupled_volumes() -> None:
    import math

    contours = (
        _open_arc(chamber="LA", phase="ED", view="A4C", width=40.0, height=100.0, segments=720),
        _open_arc(chamber="LA", phase="ED", view="A2C", width=20.0, height=100.0, segments=720),
        _open_arc(chamber="LA", phase="ES", view="A4C", width=30.0, height=80.0, segments=720),
        _open_arc(chamber="LA", phase="ES", view="A2C", width=15.0, height=80.0, segments=720),
    )

    result = calculate_chamber(contours, "LA", (1.0, 1.0))

    assert result is not None
    assert result.ef_percent is not None
    disk_sum = sum(1.0 - ((index + 0.5) / 20.0) ** 2 for index in range(20))
    edv = math.pi / 4.0 * 40.0 * 20.0 * (100.0 / 20.0) * disk_sum / 1000.0
    esv = math.pi / 4.0 * 30.0 * 15.0 * (80.0 / 20.0) * disk_sum / 1000.0
    assert result.ef_percent == pytest.approx((edv - esv) / edv * 100.0, rel=0.002)


def test_contradictory_biplane_ed_es_is_not_confirmed() -> None:
    contours = (
        _open_arc(chamber="LA", phase="ED", view="A4C", width=20.0, height=100.0, segments=180),
        _open_arc(chamber="LA", phase="ED", view="A2C", width=20.0, height=100.0, segments=180),
        _open_arc(chamber="LA", phase="ES", view="A4C", width=40.0, height=100.0, segments=180),
        _open_arc(chamber="LA", phase="ES", view="A2C", width=40.0, height=100.0, segments=180),
    )

    result = calculate_chamber(contours, "LA", (1.0, 1.0))

    assert result is not None
    assert result.biplane_es_ml is None
    assert result.biplane_verified is False
    assert confirmed_biplane_es_volume_ml(result) is None
