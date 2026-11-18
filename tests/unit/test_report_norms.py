"""Norms of the report rows (2026-11-18 list, items 6–8).

The reference handbook splits the chamber ranges by sex and the report must
follow it: «62–150» for a man's EDV is a different statement than «46–106» for
a woman's.  The indexed aorta rows (item 8) appear only when the absolute
measurement is pathological, and they carry their own mm/m² norms.
"""

from __future__ import annotations

from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
from echo_personal_tool.domain.models.measurements import (
    IndexedMeasurements,
    LvefResult,
    LvViewMetrics,
    MeasurementSnapshot,
)
from echo_personal_tool.domain.services.report_builder import build_report_document


def _row(document, parameter_id: str):
    for group in document.groups:
        for value in group.values:
            if value.parameter_id == parameter_id:
                return value
    raise AssertionError(f"no row {parameter_id!r} in {[v.parameter_id for g in document.groups for v in g.values]}")


def _lv_snapshot() -> MeasurementSnapshot:
    return MeasurementSnapshot(
        lvef=LvefResult(a4c=LvViewMetrics(edv_ml=90.0, esv_ml=40.0), sv_ml=50.0, lvef_percent=55.0),
        indexed=IndexedMeasurements(bsa_m2=2.0, simpson_edvi_ml_m2=45.0, simpson_esvi_ml_m2=20.0, rav_index_ml_m2=30.0),
        spacing_calibrated=True,
    )


def test_lv_volume_and_ef_norms_differ_by_sex() -> None:
    male = build_report_document(_lv_snapshot(), sex="M")
    female = build_report_document(_lv_snapshot(), sex="F")

    assert _row(male, "lv.edv_a4c").norm == "62–150"
    assert _row(female, "lv.edv_a4c").norm == "46–106"
    assert _row(male, "lv.esv_a4c").norm == "21–61"
    assert _row(female, "lv.esv_a4c").norm == "14–42"
    assert _row(male, "lv.edvi").norm == "34–74"  # mL/m², 2015 ASE/EACVI
    assert _row(female, "lv.edvi").norm == "29–61"
    assert _row(male, "lv.ef_bp").norm == "52–72"
    assert _row(female, "lv.ef_bp").norm == "54–74"


def test_atrial_volumes_follow_the_handbook_not_a_generic_upper_bound() -> None:
    male = build_report_document(_lv_snapshot(), sex="M")
    female = build_report_document(_lv_snapshot(), sex="F")

    # RAVi: ≤34 mL/m² for men, ≤27 for women (BJ Cardiology SOP / PH guidance).
    assert _row(male, "ra.ravi").norm == "≤34"
    assert _row(female, "ra.ravi").norm == "≤27"
    assert _row(male, "ra.ravi").pathological is False  # 30 mL/m² is a man's norm
    assert _row(female, "ra.ravi").pathological is True


def test_pathology_flips_with_the_patients_sex() -> None:
    snapshot = MeasurementSnapshot(
        lvef=LvefResult(a4c=LvViewMetrics(edv_ml=90.0, esv_ml=40.0), sv_ml=50.0, lvef_percent=53.0),
        spacing_calibrated=True,
    )
    # 53 % is inside the male range 52–72 and outside the female 54–74.
    assert _row(build_report_document(snapshot, sex="M"), "lv.ef_bp").pathological is False
    assert _row(build_report_document(snapshot, sex="F"), "lv.ef_bp").pathological is True


def test_no_false_alarms_for_in_norm_values() -> None:
    male = build_report_document(_lv_snapshot(), sex="M")
    for parameter_id in ("lv.edv_a4c", "lv.esv_a4c", "lv.edvi", "lv.esvi", "lv.ef_bp"):
        assert _row(male, parameter_id).pathological is False, parameter_id


def test_a_pathological_aorta_adds_indexed_values_with_norms() -> None:
    def snapshot(sinus_mm: float) -> MeasurementSnapshot:
        return MeasurementSnapshot(
            linear_measurements=(
                LinearMeasurement("Ao Sinus", 90.0, sinus_mm, 1, sop_instance_uid="1.2.3", measurement_id="aorta-1"),
            ),
            indexed=IndexedMeasurements(bsa_m2=2.0),
            spacing_calibrated=True,
        )

    document = build_report_document(snapshot(45.0), sex="M")  # 45 mm > ≤40 mm
    keys = [value.key for group in document.groups for value in group.values]
    assert "av:linear.ao.sinus.i:0" in keys
    indexed_row = _row(document, "linear.ao.sinus.i")
    assert indexed_row.norm == "≤20"  # mm/m², SoV < 2.0 cm/m²
    assert indexed_row.pathological is True  # 45 / 2.0 = 22.5 mm/m²

    # An in-norm aorta stays a single line: no speculative index rows.
    clean = build_report_document(snapshot(35.0), sex="M")
    assert "av:linear.ao.sinus.i:0" not in [
        value.key for group in clean.groups for value in group.values
    ]
