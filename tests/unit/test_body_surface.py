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
        linear_measurements=(
            LinearMeasurement(label="LVEDD", pixel_length=100.0, millimeter_length=50.0),
        ),
    )

    indexed = compute_indexed_measurements(snapshot, height_cm=170.0, weight_kg=70.0)

    assert indexed is not None
    assert indexed.bsa_m2 == pytest.approx(1.82, rel=0.02)
    assert indexed.simpson_edvi_ml_m2 == pytest.approx(120.0 / indexed.bsa_m2, rel=0.01)
    assert indexed.simpson_esvi_ml_m2 == pytest.approx(45.0 / indexed.bsa_m2, rel=0.01)
    assert indexed.teichholz_edvi_ml_m2 == pytest.approx(110.0 / indexed.bsa_m2, rel=0.01)
    assert indexed.lav_4c_index_ml_m2 == pytest.approx(40.0 / indexed.bsa_m2, rel=0.01)
    assert len(indexed.linear_index_mm_m2) == 1
    assert indexed.linear_index_mm_m2[0][0] == "LVEDD"
    assert indexed.linear_index_mm_m2[0][1] == pytest.approx(50.0 / indexed.bsa_m2, rel=0.01)
