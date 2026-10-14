"""Manual BSA and record BSA provenance (QH-1b.2, slice 2).

Slice 2 fixes the two gaps slice 1 documented but deliberately did not touch:

- the study has exactly **one** BSA. A value typed in the calculators is the
  deliberate clinical choice and overrides the Du Bois estimate for the
  indexed panel, the calculators, the report and the PDF — before this slice
  the tool panel showed one body surface area and the indexed values another;
- the BSA behind the stored results is **persisted** with the study (manual
  input + the basis the write froze), so opening a record can tell the user
  whether the numbers on screen were produced on the same body surface area as
  the record, instead of silently presenting recalculated values as the
  recorded ones (spec §5.2, A-03).
"""

from __future__ import annotations

import json

import pytest

from echo_personal_tool.application.measurement_persistence import record_bsa_basis
from echo_personal_tool.application.study_measurement_session import StudyMeasurementData
from echo_personal_tool.domain.calculations.body_surface import (
    bsa_du_bois_m2,
    compute_indexed_measurements,
    resolve_bsa_basis,
)
from echo_personal_tool.domain.models import LvefResult, LvViewMetrics, MeasurementSnapshot
from echo_personal_tool.domain.models.result_provenance import (
    BSA_SOURCE_DERIVED,
    BSA_SOURCE_MANUAL,
    BSA_SOURCE_MISSING,
    REASON_HEIGHT_WEIGHT_CHANGED,
    REASON_INPUT_CHANGED,
    REASON_LEGACY_NO_PROVENANCE,
    REASON_MANUAL_OVERRIDE,
    BsaBasis,
    Freshness,
)
from echo_personal_tool.domain.services.bsa_provenance import (
    bsa_record_note,
    bsa_source_label,
    evaluate_bsa_record_status,
)
from echo_personal_tool.infrastructure import measurement_codec
from echo_personal_tool.infrastructure.i18n import set_language, tr

pytestmark = pytest.mark.migration

MANUAL = 1.55  # deliberately far from the Du Bois value of 170 cm / 70 kg
SOP = "1.2.840.1.1"


@pytest.fixture(autouse=True)
def _english_ui():
    set_language("en")
    yield
    set_language("en")


def _snapshot_with_volumes() -> MeasurementSnapshot:
    return MeasurementSnapshot(
        lvef=LvefResult(a4c=LvViewMetrics(edv_ml=120.0, esv_ml=45.0), lvef_percent=62.5),
        linear_measurements=(),
    )


# ── one BSA for the study ────────────────────────────────────────────────


def test_manual_bsa_wins_over_du_bois() -> None:
    basis = resolve_bsa_basis(height_cm=170.0, weight_kg=70.0, manual_bsa_m2=MANUAL)
    assert basis.value == pytest.approx(MANUAL)
    assert basis.source == BSA_SOURCE_MANUAL
    # The metrics the value was taken from travel with it for later reporting.
    assert (basis.height_cm, basis.weight_kg) == (170.0, 70.0)


def test_without_manual_value_the_estimate_is_used() -> None:
    basis = resolve_bsa_basis(height_cm=170.0, weight_kg=70.0)
    assert basis.value == pytest.approx(bsa_du_bois_m2(170.0, 70.0))
    assert basis.source == BSA_SOURCE_DERIVED


@pytest.mark.parametrize("bad", [0.0, -1.0, float("inf"), float("nan")])
def test_unusable_manual_value_falls_back_to_the_estimate(bad: float) -> None:
    basis = resolve_bsa_basis(height_cm=170.0, weight_kg=70.0, manual_bsa_m2=bad)
    assert basis.source == BSA_SOURCE_DERIVED


def test_no_inputs_at_all_means_no_bsa() -> None:
    basis = resolve_bsa_basis()
    assert basis.value is None
    assert basis.source == BSA_SOURCE_MISSING


def test_indexed_values_use_the_manual_bsa() -> None:
    snapshot = _snapshot_with_volumes()
    indexed = compute_indexed_measurements(
        snapshot,
        height_cm=170.0,
        weight_kg=70.0,
        manual_bsa_m2=MANUAL,
    )
    assert indexed is not None
    assert indexed.bsa_m2 == pytest.approx(MANUAL)
    assert indexed.simpson_edvi_ml_m2 == pytest.approx(120.0 / MANUAL)
    assert indexed.bsa_basis is not None and indexed.bsa_basis.source == BSA_SOURCE_MANUAL


def test_manual_bsa_alone_indexes_without_body_metrics() -> None:
    """A typed BSA is enough: the volumes exist, the patient metrics were absent."""
    indexed = compute_indexed_measurements(
        _snapshot_with_volumes(),
        height_cm=None,
        weight_kg=None,
        manual_bsa_m2=MANUAL,
    )
    assert indexed is not None
    assert indexed.bsa_m2 == pytest.approx(MANUAL)
    assert indexed.simpson_edvi_ml_m2 == pytest.approx(120.0 / MANUAL)


def test_indexed_values_without_any_bsa_stay_absent() -> None:
    assert compute_indexed_measurements(_snapshot_with_volumes(), height_cm=None, weight_kg=None) is None


# ── record status ────────────────────────────────────────────────────────


def _basis(value: float | None, source: str, height: float | None = 170.0, weight: float | None = 70.0) -> BsaBasis:
    return BsaBasis(value, source, height, weight)


def test_record_without_a_basis_is_unverified_not_fresh() -> None:
    status = evaluate_bsa_record_status(None, _basis(1.7, BSA_SOURCE_DERIVED))
    assert status is not None
    assert status.freshness == Freshness.UNVERIFIED.value
    assert status.reasons == (REASON_LEGACY_NO_PROVENANCE,)
    assert status.needs_attention


def test_record_normalised_but_no_bsa_now_is_unavailable() -> None:
    status = evaluate_bsa_record_status(_basis(1.7, BSA_SOURCE_DERIVED), _basis(None, BSA_SOURCE_MISSING, None, None))
    assert status is not None and status.freshness == Freshness.UNAVAILABLE.value
    assert status.needs_attention


def test_nothing_to_report_when_no_bsa_anywhere() -> None:
    """A study without body metrics is not a provenance problem."""
    assert evaluate_bsa_record_status(_basis(None, BSA_SOURCE_MISSING, None, None), None) is None
    assert evaluate_bsa_record_status(None, None) is None


def test_record_without_basis_but_with_current_bsa_is_stale() -> None:
    status = evaluate_bsa_record_status(_basis(None, BSA_SOURCE_MISSING, None, None), _basis(1.7, BSA_SOURCE_DERIVED))
    assert status is not None
    assert status.freshness == Freshness.STALE.value
    assert status.reasons == (REASON_INPUT_CHANGED,)


def test_same_bsa_is_fresh_and_silent() -> None:
    status = evaluate_bsa_record_status(_basis(MANUAL, BSA_SOURCE_MANUAL), _basis(MANUAL, BSA_SOURCE_MANUAL))
    assert status is not None
    assert not status.needs_attention
    assert bsa_record_note(status) is None


def test_height_change_makes_the_record_stale() -> None:
    recorded = _basis(bsa_du_bois_m2(170.0, 70.0), BSA_SOURCE_DERIVED, 170.0, 70.0)
    current = _basis(bsa_du_bois_m2(175.0, 70.0), BSA_SOURCE_DERIVED, 175.0, 70.0)
    status = evaluate_bsa_record_status(recorded, current)
    assert status is not None
    assert status.freshness == Freshness.STALE.value
    assert REASON_HEIGHT_WEIGHT_CHANGED in status.reasons


def test_manual_value_that_disappeared_from_the_record_is_reported() -> None:
    recorded = _basis(MANUAL, BSA_SOURCE_MANUAL)
    current = _basis(bsa_du_bois_m2(170.0, 70.0), BSA_SOURCE_DERIVED)
    status = evaluate_bsa_record_status(recorded, current)
    assert status is not None
    assert REASON_MANUAL_OVERRIDE in status.reasons
    note = bsa_record_note(status)
    assert note is not None
    assert "1.55" in note and "manual" in note


def test_source_labels_name_the_source() -> None:
    assert bsa_source_label(_basis(1.7, BSA_SOURCE_MANUAL)) == tr("provenance.bsa_source_manual")
    assert bsa_source_label(_basis(1.7, BSA_SOURCE_DERIVED)) == tr("provenance.bsa_source_derived")
    assert bsa_source_label(None) == tr("provenance.bsa_source_missing")


def test_notes_are_localised_and_mention_the_numbers() -> None:
    status = evaluate_bsa_record_status(_basis(MANUAL, BSA_SOURCE_MANUAL), _basis(1.9, BSA_SOURCE_DERIVED))
    english = bsa_record_note(status)
    set_language("ru")
    russian = bsa_record_note(status)
    assert english != russian
    assert "1.55" in russian and "1.90" in russian

    legacy = evaluate_bsa_record_status(None, _basis(1.7, BSA_SOURCE_DERIVED))
    assert bsa_record_note(legacy) == tr("provenance.bsa_record_unverified")


# ── persistence ──────────────────────────────────────────────────────────


def test_record_basis_freezes_the_manual_choice() -> None:
    stamped = record_bsa_basis(StudyMeasurementData(height_cm=170.0, weight_kg=70.0, manual_bsa_m2=MANUAL))
    assert stamped.bsa_basis is not None
    assert stamped.bsa_basis.value == pytest.approx(MANUAL)
    assert stamped.bsa_basis.source == BSA_SOURCE_MANUAL


def test_record_basis_is_absent_without_body_metrics() -> None:
    """'No BSA' is recorded as nothing, not as a claim about a missing value."""
    assert record_bsa_basis(StudyMeasurementData()).bsa_basis is None


def test_manual_bsa_round_trips_through_the_document() -> None:
    data = StudyMeasurementData(manual_bsa_m2=MANUAL, bsa_basis=_basis(MANUAL, BSA_SOURCE_MANUAL))
    wire = measurement_codec.dumps(_record(data))
    loaded = measurement_codec.loads(wire)
    assert loaded["schema_version"] == 4
    assert loaded["data"].manual_bsa_m2 == pytest.approx(MANUAL)
    assert loaded["data"].bsa_basis == _basis(MANUAL, BSA_SOURCE_MANUAL)


def test_v3_document_migrates_without_inventing_a_basis() -> None:
    data = StudyMeasurementData(height_cm=170.0, weight_kg=70.0, height_source="manual", weight_source="manual")
    wire = json.loads(measurement_codec.dumps(_record(data)))
    wire["schema_version"] = 3
    wire["data"].pop("manual_bsa_m2", None)
    wire["data"].pop("bsa_basis", None)

    loaded = measurement_codec.loads(json.dumps(wire).encode())

    assert loaded["schema_version"] == 4
    assert loaded["data"].manual_bsa_m2 is None
    assert loaded["data"].bsa_basis is None
    # ... and such a record is unverified, never silently fresh.
    status = evaluate_bsa_record_status(loaded["data"].bsa_basis, _basis(1.7, BSA_SOURCE_DERIVED))
    assert status is not None and status.freshness == Freshness.UNVERIFIED.value


@pytest.mark.parametrize(
    "field,value",
    [
        ("manual_bsa_m2", 0.0),
        ("manual_bsa_m2", 4.5),
        ("manual_bsa_m2", -1.0),
    ],
)
def test_document_rejects_a_manual_bsa_outside_editor_bounds(field: str, value: float) -> None:
    with pytest.raises(measurement_codec.MeasurementStorageError):
        measurement_codec.dumps(_record(StudyMeasurementData(**{field: value})))


@pytest.mark.parametrize(
    "basis",
    [
        BsaBasis(None, BSA_SOURCE_DERIVED),  # derived without a value
        BsaBasis(1.5, BSA_SOURCE_MISSING),  # missing with a value
        BsaBasis(1.5, "guess"),  # unknown source
        BsaBasis(1.5, BSA_SOURCE_MANUAL, height_cm=0.0),  # impossible height
        BsaBasis(9.0, BSA_SOURCE_MANUAL),  # beyond the editor range
    ],
)
def test_document_rejects_an_inconsistent_basis(basis: BsaBasis) -> None:
    with pytest.raises(measurement_codec.MeasurementStorageError):
        measurement_codec.dumps(_record(StudyMeasurementData(bsa_basis=basis)))


def _record(data: StudyMeasurementData) -> dict:
    from datetime import datetime, timezone

    return {
        "format": measurement_codec.FORMAT,
        "schema_version": measurement_codec.VERSION,
        "measurement_semantics_version": measurement_codec.SEMANTICS_VERSION,
        "study_uid": SOP,
        "revision": 1,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "sources": {},
        "data": data,
    }


def _store():
    from echo_personal_tool.application.study_measurement_session import StudyMeasurementSessionStore

    return StudyMeasurementSessionStore()
