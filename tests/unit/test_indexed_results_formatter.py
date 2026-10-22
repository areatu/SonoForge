"""Tests for indexed overlay when ASE norms exceeded."""

from __future__ import annotations

from echo_personal_tool.domain.calculations.body_surface import compute_indexed_measurements
from echo_personal_tool.domain.models import (
    IndexedMeasurements,
    LinearMeasurement,
    LvefResult,
    LvViewMetrics,
    MeasurementSnapshot,
)
from echo_personal_tool.domain.models.measurements import ChamberSimpsonResult
from echo_personal_tool.domain.services.indexed_results_formatter import (
    append_indexed_when_abnormal,
)
from echo_personal_tool.domain.services.measurement_results_formatter import (
    format_results_overlay,
)


def test_shows_lvmi_when_out_of_norm() -> None:
    snapshot = MeasurementSnapshot(
        lvm_g=250.0,
        height_cm=170.0,
        weight_kg=70.0,
        indexed=IndexedMeasurements(bsa_m2=1.82, lvmi_g_m2=137.0),
    )
    lines: list[str] = []
    append_indexed_when_abnormal(lines, snapshot)
    assert any("ИММЛЖ" in line for line in lines)


def test_shows_edvi_when_lvedd_abnormal() -> None:
    base = MeasurementSnapshot(
        lvef=LvefResult(a4c=LvViewMetrics(edv_ml=180.0, esv_ml=70.0)),
        linear_measurements=(LinearMeasurement(label="LVEDD", pixel_length=100.0, millimeter_length=62.0),),
        height_cm=170.0,
        weight_kg=70.0,
    )
    indexed = compute_indexed_measurements(base, height_cm=170.0, weight_kg=70.0)
    snapshot = MeasurementSnapshot(
        lvef=base.lvef,
        linear_measurements=base.linear_measurements,
        height_cm=170.0,
        weight_kg=70.0,
        indexed=indexed,
    )
    text = format_results_overlay(snapshot)
    assert "иКДО 4C" in text


def test_shows_aorta_index_when_annulus_large() -> None:
    snapshot = MeasurementSnapshot(
        linear_measurements=(LinearMeasurement(label="Annulus", pixel_length=100.0, millimeter_length=40.0),),
        height_cm=170.0,
        weight_kg=70.0,
        indexed=IndexedMeasurements(
            bsa_m2=1.82,
            linear_index_mm_m2=(("Annulus", 21.98),),
        ),
    )
    lines: list[str] = []
    append_indexed_when_abnormal(lines, snapshot)
    assert any("Annulus инд." in line for line in lines)


def test_no_indexed_lines_without_height_weight() -> None:
    snapshot = MeasurementSnapshot(lvm_g=250.0, indexed=None)
    text = format_results_overlay(snapshot)
    assert "ИММЛЖ" not in text
    assert "ППТ" not in text


def test_overlay_shows_lavi_ravi_always_with_bsa() -> None:
    from echo_personal_tool.domain.services.indexed_results_formatter import (
        append_indexed_for_overlay,
    )

    snapshot = MeasurementSnapshot(
        la_simpson=ChamberSimpsonResult(
            chamber="LA",
            a4c=LvViewMetrics(esv_ml=40.0),
        ),
        ra_simpson=ChamberSimpsonResult(
            chamber="RA",
            a4c=LvViewMetrics(esv_ml=30.0),
        ),
        height_cm=180.0,
        weight_kg=80.0,
        indexed=IndexedMeasurements(
            bsa_m2=2.0,
            lav_4c_index_ml_m2=20.0,
            rav_index_ml_m2=15.0,
        ),
    )
    lines: list[str] = []
    append_indexed_for_overlay(lines, snapshot)
    assert any("иОЛП" in line for line in lines)
    assert any("иОПП" in line for line in lines)
    assert not any("ИММЛЖ" in line for line in lines)


def test_overlay_lvmi_still_abnormal_only() -> None:
    snapshot = MeasurementSnapshot(
        lvm_g=120.0,
        height_cm=180.0,
        weight_kg=80.0,
        indexed=IndexedMeasurements(bsa_m2=2.0, lvmi_g_m2=60.0),
    )
    text = format_results_overlay(snapshot)
    assert "ИММЛЖ" not in text
