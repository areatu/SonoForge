"""Unit tests for BSA and indexed measurements."""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.calculations.body_surface import (
    bsa_du_bois_m2,
    compute_indexed_measurements,
)
from echo_personal_tool.domain.models import (
    ChamberSimpsonResult,
    LinearMeasurement,
    LvefResult,
    LvViewMetrics,
    MeasurementSnapshot,
    TeichholzResult,
)


def test_bsa_du_bois_returns_none_for_invalid_input() -> None:
    assert bsa_du_bois_m2(0.0, 70.0) is None
    assert bsa_du_bois_m2(170.0, 0.0) is None


def test_bsa_du_bois_known_example() -> None:
    bsa = bsa_du_bois_m2(170.0, 70.0)
    assert bsa is not None
    assert bsa == pytest.approx(1.82, rel=0.02)


def test_compute_indexed_measurements_requires_height_and_weight() -> None:
    snapshot = MeasurementSnapshot(
        lvef=LvefResult(
            a4c=LvViewMetrics(edv_ml=120.0, esv_ml=45.0),
            lvef_percent=62.5,
        ),
    )
    assert compute_indexed_measurements(snapshot, height_cm=None, weight_kg=70.0) is None
    assert compute_indexed_measurements(snapshot, height_cm=170.0, weight_kg=None) is None


def test_compute_indexed_volumes_and_linear() -> None:
    snapshot = MeasurementSnapshot(
        lvef=LvefResult(
            a4c=LvViewMetrics(edv_ml=120.0, esv_ml=45.0),
            lvef_percent=62.5,
        ),
        teichholz=TeichholzResult(edv_ml=110.0, esv_ml=50.0, lvef_percent=54.5),
        la_simpson=ChamberSimpsonResult(
            chamber="LA",
            a4c=LvViewMetrics(esv_ml=40.0),
        ),
        linear_measurements=(LinearMeasurement(label="LVEDD", pixel_length=100.0, millimeter_length=50.0),),
    )

    indexed = compute_indexed_measurements(snapshot, height_cm=170.0, weight_kg=70.0)

    assert indexed is not None
    assert indexed.bsa_m2 == pytest.approx(1.82, rel=0.02)
    assert indexed.simpson_edvi_ml_m2 == pytest.approx(120.0 / indexed.bsa_m2, rel=0.01)
    assert indexed.simpson_esvi_ml_m2 == pytest.approx(45.0 / indexed.bsa_m2, rel=0.01)
    assert indexed.teichholz_edvi_ml_m2 == pytest.approx(110.0 / indexed.bsa_m2, rel=0.01)
    assert indexed.lav_4c_index_ml_m2 == pytest.approx(40.0 / indexed.bsa_m2, rel=0.01)
    assert indexed.lvmi_g_m2 is None
    assert len(indexed.linear_index_mm_m2) == 1
    assert indexed.linear_index_mm_m2[0][0] == "LVEDD"


def test_compute_indexed_lvmi() -> None:
    snapshot = MeasurementSnapshot(lvm_g=120.0)
    indexed = compute_indexed_measurements(snapshot, height_cm=170.0, weight_kg=70.0)
    assert indexed is not None
    assert indexed.lvmi_g_m2 == pytest.approx(120.0 / indexed.bsa_m2, rel=0.01)


def test_mean_of_two_monoplanes_is_not_indexed_as_biplane() -> None:
    snapshot = MeasurementSnapshot(
        la_simpson=ChamberSimpsonResult(
            chamber="LA",
            method="simpson_mean_monoplan",
            a4c=LvViewMetrics(esv_ml=40.0),
            a2c=LvViewMetrics(esv_ml=50.0),
        )
    )

    indexed = compute_indexed_measurements(snapshot, height_cm=170.0, weight_kg=70.0)

    assert indexed is not None
    assert indexed.lav_4c_index_ml_m2 == pytest.approx(40.0 / indexed.bsa_m2, rel=0.01)
    assert indexed.lav_bi_index_ml_m2 is None


def test_only_a_confirmed_true_biplane_volume_is_indexed() -> None:
    snapshot = MeasurementSnapshot(
        la_simpson=ChamberSimpsonResult(
            chamber="LA",
            method="simpson_biplan",
            a4c=LvViewMetrics(esv_ml=40.0),
            a2c=LvViewMetrics(esv_ml=50.0),
            biplane_es_ml=55.0,
            biplane_verified=True,
        )
    )

    indexed = compute_indexed_measurements(snapshot, height_cm=170.0, weight_kg=70.0)

    assert indexed is not None
    assert indexed.lav_bi_index_ml_m2 == pytest.approx(55.0 / indexed.bsa_m2, rel=0.01)


def test_true_la_biplane_calculation_populates_the_biplane_index() -> None:
    import math

    from echo_personal_tool.domain.calculations.chamber_simpson import calculate_chamber
    from echo_personal_tool.domain.models import Contour

    def arc(view: str, width: float) -> Contour:
        annulus = ((0.0, 0.0), (width, 0.0))
        points = [
            (width / 2.0 + width / 2.0 * math.cos(angle), 100.0 * math.sin(angle))
            for angle in (math.pi - index * math.pi / 180 for index in range(181))
        ]
        return Contour(phase="ES", view=view, chamber="LA", mitral_annulus=annulus, points=points)

    result = calculate_chamber((arc("A4C", 40.0), arc("A2C", 20.0)), "LA", (1.0, 1.0))
    assert result is not None and result.biplane_es_ml is not None

    indexed = compute_indexed_measurements(
        MeasurementSnapshot(la_simpson=result),
        height_cm=170.0,
        weight_kg=70.0,
    )

    assert indexed is not None
    assert indexed.lav_bi_index_ml_m2 == pytest.approx(result.biplane_es_ml / indexed.bsa_m2, rel=0.01)
