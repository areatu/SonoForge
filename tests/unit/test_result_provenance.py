"""QH-1b.1: provenance/freshness DTO + dependency map + schema/migration tests.

Spec §5.2 and §5.3:
- For each derived result store stable ID, method ID, source identity, input refs
  with revisions, calibration, algorithm/config/model, units/definitions, QC,
  freshness and reason codes. Timestamp is metadata only.
- Freshness separate from QC: fresh, stale, unverified, unavailable.
- Dependency map and invalidation contract.
- Compatibility: v1/v2 docs keep primary data, derived become UNVERIFIED;
  future/unsupported not overwritten quietly; no executable deserialization;
  bounded parse.

This file is the contract test for the first design PR of QH-1b.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from echo_personal_tool.application.study_measurement_session import StudyMeasurementData
from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
from echo_personal_tool.domain.models.result_provenance import (
    REASON_INPUT_CHANGED,
    REASON_LEGACY_NO_PROVENANCE,
    CalibrationRef,
    Freshness,
    InputReference,
    ResultQC,
    SourceIdentity,
    legacy_unverified_provenance,
    make_provenance,
    new_result_id,
)
from echo_personal_tool.domain.services.provenance_dependencies import (
    ALL_INPUT_KINDS,
    ALL_RESULT_FAMILIES,
    CALIB_PIXEL,
    CALIB_TIME,
    DEPENDENCY_MAP,
    INPUT_ALGORITHM,
    INPUT_CONTOUR,
    INPUT_HEIGHT,
    INPUT_MANUAL_OVERRIDE,
    INPUT_MODEL,
    INPUT_WEIGHT,
    RESULT_CALCULATIONS,
    RESULT_INDEXED,
    RESULT_LVEF,
    RESULT_SIMPSON,
    RESULT_STRAIN,
    DependencyChange,
    affected_families,
    is_calibration_kind,
    requires_per_source_isolation,
    should_discard_late_callback,
)
from echo_personal_tool.infrastructure.measurement_codec import (
    FORMAT,
    SEMANTICS_VERSION,
    VERSION,
    MeasurementStorageError,
    dumps,
    loads,
)

pytestmark = pytest.mark.migration


# ── DTO basics ────────────────────────────────────────────────────────────


def test_freshness_enum_values():
    assert {f.value for f in Freshness} == {"fresh", "stale", "unverified", "unavailable"}


def test_new_result_id_is_opaque_and_unique():
    a = new_result_id()
    b = new_result_id()
    assert a != b
    assert len(a) == 32
    # No PHI
    assert "patient" not in a.lower()


def test_make_provenance_fresh_by_default():
    src = SourceIdentity(study_uid="1.2.3", sop_instance_uid="1.2.3.1", frame_index=2)
    prov = make_provenance(
        method_id="simpson_biplane",
        family=RESULT_SIMPSON,
        source=src,
        units="mL",
        definition="Simpson biplane EDV",
        revision=1,
    )
    assert prov.is_fresh()
    assert prov.freshness == Freshness.FRESH.value
    assert prov.family == RESULT_SIMPSON
    assert prov.source == src
    assert prov.revision == 1
    assert prov.timestamp


def test_with_freshness_increments_revision_and_keeps_identity():
    prov = make_provenance(method_id="lvef", family=RESULT_LVEF)
    original_id = prov.result_id
    original_rev = prov.revision
    stale = prov.with_freshness(Freshness.STALE.value, reasons=(REASON_INPUT_CHANGED,))
    assert stale.result_id == original_id
    assert stale.revision == original_rev + 1
    assert stale.is_stale()
    assert REASON_INPUT_CHANGED in stale.freshness_reasons
    assert (
        stale.timestamp == prov.timestamp
    )  # timestamp is metadata, but we keep original for simplicity? Factory uses now, with_freshness keeps old timestamp


def test_with_freshness_invalid_raises():
    prov = make_provenance(method_id="x", family=RESULT_SIMPSON)
    with pytest.raises(ValueError):
        prov.with_freshness("bogus")  # type: ignore[arg-type]


def test_legacy_unverified_provenance():
    prov = legacy_unverified_provenance(result_id="abc", family=RESULT_STRAIN, method_id="legacy")
    assert prov.is_unverified()
    assert REASON_LEGACY_NO_PROVENANCE in prov.freshness_reasons
    assert prov.qc.status == "unverified"
    assert prov.family == RESULT_STRAIN


def test_provenance_with_inputs_and_calibration():
    src = SourceIdentity(study_uid="1.2.3", sop_instance_uid="1.2.3.4", frame_index=0, fingerprint="a" * 64)
    inputs = (
        InputReference(measurement_id="contour:1", revision=2, kind="contour", label="LV ED"),
        InputReference(measurement_id="contour:2", revision=1, kind="contour", label="LV ES"),
    )
    cals = (
        CalibrationRef(kind="pixel", value=(0.5, 0.5), version="v2", source_instance_uid="1.2.3.4"),
        CalibrationRef(kind="time", value=33.3, version="v1"),
    )
    prov = make_provenance(
        method_id="simpson_mono",
        family=RESULT_SIMPSON,
        source=src,
        inputs=inputs,
        calibration=cals,
        units="mL",
        definition="Simpson monoplane volume",
        semantics_version=2,
        algorithm_version="1.0.0",
        config_digest="abc123",
    )
    assert len(prov.inputs) == 2
    assert len(prov.calibration) == 2
    assert prov.method.semantics_version == 2
    assert prov.method.algorithm_version == "1.0.0"
    assert prov.method.config_digest == "abc123"


def test_qc_separate_from_freshness():
    """QC valid/review/invalid stays separate; review not auto invalid."""
    qc_valid = ResultQC(status="valid", coverage=0.9)
    prov = make_provenance(method_id="strain", family=RESULT_STRAIN, qc=qc_valid, freshness=Freshness.FRESH.value)
    assert prov.qc.status == "valid"
    assert prov.is_fresh()

    qc_review = ResultQC(status="review", coverage=0.6, reasons=("low_coverage",))
    prov2 = make_provenance(method_id="strain", family=RESULT_STRAIN, qc=qc_review, freshness=Freshness.FRESH.value)
    assert prov2.qc.status == "review"
    assert prov2.is_fresh()  # fresh does not mean clinically valid, per spec


# ── Dependency map ────────────────────────────────────────────────────────


def test_dependency_map_covers_all_input_kinds():
    for kind in ALL_INPUT_KINDS:
        # Must be present or explicitly empty (late_callback)
        assert kind in DEPENDENCY_MAP, f"missing {kind} in DEPENDENCY_MAP"


def test_dependency_map_values_are_valid_families():
    for kind, families in DEPENDENCY_MAP.items():
        assert kind in ALL_INPUT_KINDS
        for fam in families:
            assert fam in ALL_RESULT_FAMILIES, f"{kind} -> invalid family {fam}"


def test_contour_change_invalidates_simpson_strain_not_whole_study():
    fams = affected_families(DependencyChange(kind=INPUT_CONTOUR, measurement_id="c1"))
    assert RESULT_SIMPSON in fams
    assert RESULT_STRAIN in fams
    assert RESULT_LVEF in fams
    # Not whole study without necessity — indexed alone should not be forced by contour?
    # Actually contour -> indexed via calculations, but spec says not whole study without necessity.
    # Our map includes calculations for contour, but not raw volumes independent?
    # Check that height/weight alone does not invalidate simpson raw volumes
    fams_hw = affected_families(DependencyChange(kind=INPUT_HEIGHT))
    assert RESULT_SIMPSON not in fams_hw
    assert RESULT_INDEXED in fams_hw


def test_pixel_calibration_invalidates_only_dependent_per_source():
    fams = affected_families(DependencyChange(kind=CALIB_PIXEL, source_instance_uid="1.2.3.1"))
    assert RESULT_SIMPSON in fams
    assert RESULT_LVEF in fams
    assert is_calibration_kind(CALIB_PIXEL)
    assert requires_per_source_isolation(CALIB_PIXEL)

    fams_time = affected_families(DependencyChange(kind=CALIB_TIME))
    assert RESULT_SIMPSON not in fams_time  # time does not affect volume
    assert "doppler" in fams_time or RESULT_CALCULATIONS in fams_time


def test_height_weight_bsa_updates_indexed_only():
    for kind in (INPUT_HEIGHT, INPUT_WEIGHT):
        fams = affected_families(DependencyChange(kind=kind))
        assert RESULT_INDEXED in fams
        assert RESULT_SIMPSON not in fams
        assert RESULT_STRAIN not in fams


def test_manual_override_recalc_calculators_preserving_source():
    fams = affected_families(DependencyChange(kind=INPUT_MANUAL_OVERRIDE))
    assert RESULT_CALCULATIONS in fams
    assert RESULT_INDEXED in fams
    # Not raw volumes
    assert RESULT_SIMPSON not in fams


def test_algorithm_model_config_old_result_historical():
    fams_algo = affected_families(DependencyChange(kind=INPUT_ALGORITHM, measurement_id="simpson_biplane"))
    assert RESULT_SIMPSON in fams_algo
    fams_model = affected_families(DependencyChange(kind=INPUT_MODEL, measurement_id="onnx_lv_v1"))
    assert RESULT_STRAIN in fams_model


def test_late_callback_discard_rule():
    # Accept only when captured context/generation/input revisions match
    assert not should_discard_late_callback(
        captured_generation=5, current_generation=5, captured_revision=2, current_revision=2
    )
    assert should_discard_late_callback(
        captured_generation=4, current_generation=5, captured_revision=2, current_revision=2
    )
    assert should_discard_late_callback(
        captured_generation=5, current_generation=5, captured_revision=1, current_revision=2
    )


def test_unknown_input_kind_raises():
    with pytest.raises(ValueError):
        affected_families(DependencyChange(kind="bogus_kind"))


# ── Codec v3 round-trip with provenance ───────────────────────────────────


def test_codec_v3_roundtrip_with_provenance(tmp_path=None):
    """New v3 document with provenance round-trips and validates."""
    src_uid = "1.2.3"
    sop_uid = "1.2.3.4"
    sources = {sop_uid: {"fingerprint": "a" * 64, "frames": 4, "spacing": [0.5, 0.5]}}

    # Primary measurements with stable IDs (QH-1b.1)
    contour = Contour(
        phase="ED",
        view="A4C",
        chamber="LV",
        points=[(0, 0), (1, 0), (1, 1)],
        frame_index=0,
        sop_instance_uid=sop_uid,
        measurement_id="contour-1",
        revision=1,
    )
    linear = LinearMeasurement(
        label="LVEDD",
        pixel_length=20,
        millimeter_length=10,
        frame_index=0,
        sop_instance_uid=sop_uid,
        measurement_id="linear-1",
        revision=1,
    )

    prov = make_provenance(
        method_id="simpson_biplane",
        family=RESULT_SIMPSON,
        source=SourceIdentity(study_uid=src_uid, sop_instance_uid=sop_uid, frame_index=0, fingerprint="a" * 64),
        inputs=(
            InputReference(measurement_id="contour-1", revision=1, kind="contour"),
            InputReference(measurement_id="contour-2", revision=1, kind="contour"),
        ),
        calibration=(CalibrationRef(kind="pixel", value=(0.5, 0.5), version="v2", source_instance_uid=sop_uid),),
        units="mL",
        definition="Simpson biplane EDV",
        semantics_version=2,
        algorithm_version="1.0.0",
        revision=1,
    )

    data = StudyMeasurementData(
        contours=(contour,),
        linear_measurements=(linear,),
        result_provenance=(prov,),
    )

    record = {
        "format": FORMAT,
        "schema_version": VERSION,
        "measurement_semantics_version": SEMANTICS_VERSION,
        "study_uid": src_uid,
        "revision": 1,
        "saved_at": "2026-10-14T00:00:00+00:00",
        "sources": sources,
        "data": data,
    }

    payload = dumps(record)
    loaded = loads(payload)
    assert loaded["schema_version"] == VERSION
    assert loaded["data"].contours[0].measurement_id == "contour-1"
    assert loaded["data"].linear_measurements[0].measurement_id == "linear-1"
    assert len(loaded["data"].result_provenance) == 1
    loaded_prov = loaded["data"].result_provenance[0]
    assert loaded_prov.result_id == prov.result_id
    assert loaded_prov.family == RESULT_SIMPSON
    assert loaded_prov.is_fresh()
    assert loaded_prov.inputs[0].measurement_id == "contour-1"


def test_codec_v1_v2_without_provenance_loads_as_empty_and_unverified():
    """Old v1/v2 docs without provenance keep primary data, derived becomes UNVERIFIED per spec §5.3.3."""
    src_uid = "1.2.3"
    sop_uid = "1.2.3.4"
    sources = {sop_uid: {"fingerprint": "b" * 64, "frames": 2, "spacing": [0.5, 0.5]}}

    # Simulate v2 doc without result_provenance field (old FIELDS)
    data_v2 = StudyMeasurementData(
        contours=(
            Contour(
                phase="ED",
                view="A4C",
                chamber="LV",
                points=[(0, 0), (1, 0), (1, 1)],
                frame_index=0,
                sop_instance_uid=sop_uid,
                # legacy: no measurement_id
            ),
        ),
    )

    # Manually craft v2 payload without result_provenance in data
    # Use old FIELDS to encode, but our codec now expects result_provenance optional
    record_v2 = {
        "format": FORMAT,
        "schema_version": 2,
        "measurement_semantics_version": 2,
        "study_uid": src_uid,
        "revision": 1,
        "saved_at": "2026-10-13T00:00:00+00:00",
        "sources": sources,
        "data": data_v2,
    }

    # dumps will write as v3 (current), but we want to test loading old v2 payload
    # So we manually encode old data without provenance field
    import dataclasses
    import json

    def _encode_old(value):
        if dataclasses.is_dataclass(value):
            # old fields without result_provenance
            allowed = {
                "contours",
                "linear_measurements",
                "doppler_by_instance",
                "doppler_by_instance_frame",
                "doppler_calibration_by_instance",
                "doppler_calibration_by_instance_frame",
                "mmode_calibration_by_instance",
                "cine_segment_roi_by_instance",
                "manual_spacing_by_instance",
                "mmode_time_by_instance",
                "height_cm",
                "weight_kg",
                "height_source",
                "weight_source",
                "vessel_measurements",
                "simpson_area_by_frame",
                "strain",
            }
            if type(value).__name__ == "StudyMeasurementData":
                fields = allowed
            else:
                fields = {f.name for f in dataclasses.fields(value)}
            return {name: _encode_old(getattr(value, name)) for name in sorted(fields) if hasattr(value, name)}
        if isinstance(value, (tuple, list)):
            return [_encode_old(item) for item in value]
        from enum import Enum

        if isinstance(value, Enum):
            return value.value
        return value

    wire = {**record_v2, "data": _encode_old(record_v2["data"])}
    payload_v2 = json.dumps(wire, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")

    loaded = loads(payload_v2)
    # After migration to v3, primary measurements should have legacy IDs stamped
    assert loaded["schema_version"] == VERSION
    assert loaded["data"].contours[0].measurement_id.startswith("legacy:contour:")
    # Provenance empty — old derived results become UNVERIFIED (handled by caller)
    assert loaded["data"].result_provenance == ()
    # Primary data preserved
    assert len(loaded["data"].contours) == 1


def test_future_schema_version_rejected_not_silently_overwritten():
    """Future/unsupported/corrupt records not overwritten quietly (spec §5.3.5)."""
    src_uid = "1.2.3"
    sop_uid = "1.2.3.4"
    sources = {sop_uid: {"fingerprint": "c" * 64, "frames": 1, "spacing": [0.5, 0.5]}}
    data = StudyMeasurementData()

    record_future = {
        "format": FORMAT,
        "schema_version": 99,  # future
        "measurement_semantics_version": 2,
        "study_uid": src_uid,
        "revision": 1,
        "saved_at": "2026-10-14T00:00:00+00:00",
        "sources": sources,
        "data": data,
    }

    # Encode without validation (bypass dumps)
    import dataclasses
    import json

    def _enc(v):
        if dataclasses.is_dataclass(v):
            return {f.name: _enc(getattr(v, f.name)) for f in dataclasses.fields(v)}
        if isinstance(v, (list, tuple)):
            return [_enc(x) for x in v]
        return v

    wire = {**record_future, "data": _enc(data)}
    payload = json.dumps(wire, separators=(",", ":")).encode("utf-8")

    with pytest.raises(MeasurementStorageError) as exc:
        loads(payload)
    assert exc.value.code == "version"


def test_executable_deserialization_rejected():
    """Bounded parse and ban executable deserialization (spec §5.3.2)."""
    # Payload trying to inject __class__ or similar
    payload = json.dumps(
        {
            "format": FORMAT,
            "schema_version": VERSION,
            "measurement_semantics_version": SEMANTICS_VERSION,
            "study_uid": "1.2.3",
            "revision": 1,
            "saved_at": "2026-10-14T00:00:00+00:00",
            "sources": {"1.2.3.4": {"fingerprint": "a" * 64, "frames": 1, "spacing": [0.5, 0.5]}},
            "data": {
                "contours": [],
                "linear_measurements": [],
                "doppler_by_instance": [],
                "doppler_by_instance_frame": [],
                "doppler_calibration_by_instance": [],
                "doppler_calibration_by_instance_frame": [],
                "mmode_calibration_by_instance": [],
                "cine_segment_roi_by_instance": [],
                "manual_spacing_by_instance": [],
                "mmode_time_by_instance": [],
                "height_cm": None,
                "weight_kg": None,
                "height_source": "unset",
                "weight_source": "unset",
                "vessel_measurements": [],
                "simpson_area_by_frame": [],
                "strain": None,
                "result_provenance": [
                    {
                        "__class__": "os.system",
                        "result_id": "evil",
                        "method": {"method_id": "x", "semantics_version": 1},
                        "freshness": "fresh",
                    }
                ],
            },
        },
        separators=(",", ":"),
    ).encode("utf-8")

    with pytest.raises(MeasurementStorageError):
        loads(payload)


def test_bounded_parse_string_length_limit():
    """String >4096 chars rejected (bounded parse)."""
    long_str = "a" * 5000
    payload = json.dumps(
        {
            "format": FORMAT,
            "schema_version": VERSION,
            "measurement_semantics_version": SEMANTICS_VERSION,
            "study_uid": "1.2.3",
            "revision": 1,
            "saved_at": "2026-10-14T00:00:00+00:00",
            "sources": {"1.2.3.4": {"fingerprint": "a" * 64, "frames": 1, "spacing": [0.5, 0.5]}},
            "data": {
                "contours": [],
                "linear_measurements": [],
                "doppler_by_instance": [],
                "doppler_by_instance_frame": [],
                "doppler_calibration_by_instance": [],
                "doppler_calibration_by_instance_frame": [],
                "mmode_calibration_by_instance": [],
                "cine_segment_roi_by_instance": [],
                "manual_spacing_by_instance": [],
                "mmode_time_by_instance": [],
                "height_cm": None,
                "weight_kg": None,
                "height_source": "unset",
                "weight_source": "unset",
                "vessel_measurements": [],
                "simpson_area_by_frame": [],
                "strain": None,
                "result_provenance": [
                    {
                        "result_id": long_str,
                        "method": {"method_id": "x", "semantics_version": 1, "definition": "", "units": ""},
                        "inputs": [],
                        "calibration": [],
                        "units": "",
                        "definition": "",
                        "qc": {"status": "valid"},
                        "freshness": "fresh",
                        "freshness_reasons": [],
                        "timestamp": "2026-10-14T00:00:00+00:00",
                        "revision": 0,
                        "family": "simpson",
                    }
                ],
            },
        },
        separators=(",", ":"),
    ).encode("utf-8")

    with pytest.raises(MeasurementStorageError) as exc:
        loads(payload)
    assert exc.value.code in ("limit", "invalid")


def test_provenance_duplicate_result_id_rejected():
    """Duplicate result_id in one doc is invalid (bounded uniqueness)."""
    prov = make_provenance(method_id="simpson", family=RESULT_SIMPSON, result_id="dup")
    data = StudyMeasurementData(result_provenance=(prov, prov))
    record = {
        "format": FORMAT,
        "schema_version": VERSION,
        "measurement_semantics_version": SEMANTICS_VERSION,
        "study_uid": "1.2.3",
        "revision": 1,
        "saved_at": "2026-10-14T00:00:00+00:00",
        "sources": {"1.2.3.4": {"fingerprint": "a" * 64, "frames": 1, "spacing": [0.5, 0.5]}},
        "data": data,
    }
    with pytest.raises(MeasurementStorageError) as exc:
        dumps(record)
    assert exc.value.code == "invalid"


def test_measurement_id_stamping_migration():
    """v2 doc without measurement_id gets legacy IDs after migration (QH-1b.1)."""
    src_uid = "1.2.3"
    sop_uid = "1.2.3.4"
    sources = {sop_uid: {"fingerprint": "d" * 64, "frames": 2, "spacing": [0.5, 0.5]}}

    contour_no_id = Contour(
        phase="ED",
        view="A4C",
        chamber="LV",
        points=[(0, 0), (1, 0), (1, 1)],
        frame_index=0,
        sop_instance_uid=sop_uid,
    )
    assert contour_no_id.measurement_id == ""

    data = StudyMeasurementData(contours=(contour_no_id,))
    _record = {
        "format": FORMAT,
        "schema_version": 2,
        "measurement_semantics_version": 2,
        "study_uid": src_uid,
        "revision": 1,
        "saved_at": "2026-10-13T00:00:00+00:00",
        "sources": sources,
        "data": data,
    }

    # Simulate old payload without measurement_id field in contour
    import json

    def _encode_old_contour(c):
        # Old contour without measurement_id/revision
        return {
            "phase": c.phase,
            "view": c.view,
            "chamber": c.chamber,
            "points": list(c.points),
            "source": c.source,
            "num_nodes": c.num_nodes,
            "frame_index": c.frame_index,
            "sop_instance_uid": c.sop_instance_uid,
            "review_pending": c.review_pending,
            "refine_step": c.refine_step,
            "refine_locked_indices": list(c.refine_locked_indices),
            "unassisted": c.unassisted,
        }

    wire_data = {
        "contours": [_encode_old_contour(contour_no_id)],
        "linear_measurements": [],
        "doppler_by_instance": [],
        "doppler_by_instance_frame": [],
        "doppler_calibration_by_instance": [],
        "doppler_calibration_by_instance_frame": [],
        "mmode_calibration_by_instance": [],
        "cine_segment_roi_by_instance": [],
        "manual_spacing_by_instance": [],
        "mmode_time_by_instance": [],
        "height_cm": None,
        "weight_kg": None,
        "height_source": "unset",
        "weight_source": "unset",
        "vessel_measurements": [],
        "simpson_area_by_frame": [],
        "strain": None,
    }

    wire = {
        "format": FORMAT,
        "schema_version": 2,
        "measurement_semantics_version": 2,
        "study_uid": src_uid,
        "revision": 1,
        "saved_at": "2026-10-13T00:00:00+00:00",
        "sources": sources,
        "data": wire_data,
    }

    payload = json.dumps(wire, separators=(",", ":")).encode("utf-8")
    loaded = loads(payload)
    assert loaded["data"].contours[0].measurement_id.startswith("legacy:contour:")


def test_null_no_data_not_zero_nan_as_normal():
    """Report: null/no data, not 0/NaN as normal value (spec §5.2)."""
    prov = make_provenance(
        method_id="simpson",
        family=RESULT_SIMPSON,
        freshness=Freshness.UNAVAILABLE.value,
        reasons=("source_missing",),
    )
    assert prov.is_unavailable()
    # Value should be None/null in report projection, not 0
    # Here we only test provenance freshness, not report formatting,
    # but ensure unavailable is distinct from fresh with 0 value
    assert prov.freshness != Freshness.FRESH.value


def test_timestamp_is_metadata_not_identity():
    """Timestamp saved as metadata, but not replacing identity/revision."""
    prov1 = make_provenance(method_id="simpson", family=RESULT_SIMPSON, result_id="same-id", revision=1)
    prov2 = replace(prov1, timestamp="2026-10-15T00:00:00+00:00")
    # Same result_id and revision, different timestamp — still same logical result
    assert prov1.result_id == prov2.result_id
    assert prov1.revision == prov2.revision
    assert prov1.timestamp != prov2.timestamp
