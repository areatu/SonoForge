"""Synthetic-only disk/process tests for WP4; no real profile or medical data."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from echo_personal_tool.application.study_measurement_session import StudyMeasurementData, StudyMeasurementSessionStore
from echo_personal_tool.domain.models import Contour, LinearMeasurement
from echo_personal_tool.domain.models.doppler import DopplerMeasurementDTO, DopplerPeakMarker, DopplerTrace
from echo_personal_tool.domain.models.doppler_roi import DopplerCalibrationState, DopplerSpectrogramRoi
from echo_personal_tool.domain.models.frame_panels import MmodeCalibrationState
from echo_personal_tool.domain.models.measurements import StrainReport
from echo_personal_tool.domain.models.vessel_measurement import VesselMeasurement
from echo_personal_tool.infrastructure.measurement_codec import (
    FORMAT,
    SEMANTICS_VERSION,
    VERSION,
    MeasurementStorageError,
    dumps,
    loads,
    migrate,
    study_key,
)
from echo_personal_tool.infrastructure.measurement_repository import MeasurementRepository

_UTC = timezone.utc  # noqa: UP017 - retain Python 3.10 compatibility

UID = "1.2.3"
SOP = "1.2.3.4"
SOURCES = {SOP: {"fingerprint": "a" * 64, "frames": 5, "spacing": [0.5, 0.6]}}


def record(data=None):
    return dict(
        format=FORMAT,
        schema_version=VERSION,
        measurement_semantics_version=SEMANTICS_VERSION,
        study_uid=UID,
        revision=1,
        saved_at=datetime.now(_UTC).isoformat(),
        sources=SOURCES,
        data=data or StudyMeasurementData(),
    )


def complete_data():
    roi = DopplerSpectrogramRoi(1, 2, 100, 80)
    cal = DopplerCalibrationState(roi, baseline_y_px=40, time_span_ms=500)
    dto = DopplerMeasurementDTO(
        (DopplerPeakMarker("E", 0, -70.25),), (), (DopplerTrace("VTI", ((0.0, -20.0), (30.0, -50.0))),)
    )
    return StudyMeasurementData(
        contours=(
            Contour(
                "ED",
                points=[(1.0, 2.0), (4.0, 9.0), (6.0, 2.0)],
                frame_index=0,
                sop_instance_uid=SOP,
                mitral_annulus=((1.0, 2.0), (6.0, 2.0)),
                apex_landmark=(4.0, 9.0),
            ),
        ),
        linear_measurements=(LinearMeasurement("LVEDD", 10.123456789, 5.123456789, 0, (1.0, 2.0), (3.0, 4.0), SOP),),
        doppler_by_instance=((SOP, dto),),
        doppler_by_instance_frame=((SOP, 2, dto),),
        doppler_calibration_by_instance=((SOP, cal),),
        doppler_calibration_by_instance_frame=((SOP, 2, cal),),
        mmode_calibration_by_instance=((SOP, MmodeCalibrationState(roi, 0.2, 0.3)),),
        cine_segment_roi_by_instance=((SOP, (1.0, 2.0, 50.0, 60.0)),),
        manual_spacing_by_instance=((SOP, (0.5, 0.6)),),
        mmode_time_by_instance=((SOP, 2.0),),
        height_cm=170.0,
        weight_kg=70.0,
        height_source="manual",
        weight_source="dicom",
        vessel_measurements=(VesselMeasurement(100.0, 20.0, 0.8, 5.0, 46.0, SOP, 0),),
        simpson_area_by_frame=((SOP, "A4C", 0, 122.2),),
        strain=StrainReport(gls_by_view=(("A4C", -19.5),), qc_by_view=(("A4C", "valid"),), gls_average=-19.5),
    )


def test_round_trip_all_fields_precision_and_no_patient_paths():
    original = record(complete_data())
    payload = dumps(original)
    assert loads(payload) == original
    assert b"PatientName" not in payload and b"path" not in payload
    assert b"__class__" not in payload and b"manual_pixel_spacing" not in payload


@pytest.mark.parametrize("uid", ["", "__default__", "__legacy__", "../../patient", "1.02.3", "a.b", "1." * 40])
def test_invalid_identity(uid):
    with pytest.raises(MeasurementStorageError, match="identity"):
        study_key(uid)


def test_local_namespace_distinct():
    assert len(study_key("local:" + "a" * 16)) == 64


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.update(schema_version=999),
        lambda r: r.update(revision=True),
        lambda r: r.update(extra="not allowed"),
        lambda r: r["data"].update(height_cm=float("nan")),
        lambda r: r["data"].update(height_source="unknown"),
        lambda r: r["data"].update(weight_kg=701),
        lambda r: r["data"].update(height_cm=170),  # unset must not carry a value
        lambda r: r["sources"][SOP].update(frames=-1),
        lambda r: r["sources"][SOP].update(spacing=[0, 0]),
        lambda r: r["sources"][SOP].update(path="patient.dcm"),
    ],
)
def test_untrusted_input_rejected(mutate):
    wire = json.loads(dumps(record()))
    mutate(wire)
    with pytest.raises(MeasurementStorageError):
        loads(json.dumps(wire).encode())


def test_duplicate_json_keys_and_depth_rejected():
    with pytest.raises(MeasurementStorageError):
        loads(b'{"format":"sonoforge.study-measurements","format":"x"}')
    with pytest.raises(MeasurementStorageError):
        loads(b"[" * 10000 + b"0" + b"]" * 10000)


@pytest.mark.parametrize("frame", [-1, 5, None])
def test_frame_bounds(frame):
    data = replace(complete_data(), contours=(replace(complete_data().contours[0], frame_index=frame),))
    with pytest.raises(MeasurementStorageError, match="source"):
        dumps(record(data))


def test_unknown_sop_and_ai_preview_rejected():
    data = complete_data()
    for contour in (
        replace(data.contours[0], sop_instance_uid="other"),
        replace(data.contours[0], review_pending=True),
    ):
        with pytest.raises(MeasurementStorageError):
            dumps(record(replace(data, contours=(contour,))))


def test_write_revision_conflict_and_delete(tmp_path):
    repo = MeasurementRepository(tmp_path / "measurements")
    try:
        assert repo.load(UID) is None
        first = repo.save(UID, complete_data(), SOURCES, 0)
        assert repo.load(UID) == first
        with pytest.raises(MeasurementStorageError, match="conflict"):
            repo.save(UID, complete_data(), SOURCES, 0)
        assert repo.save(UID, StudyMeasurementData(), SOURCES, 1)["revision"] == 2
        repo.delete(UID)
        assert repo.load(UID) is None
    finally:
        repo.close()


def test_failed_replace_leaves_last_committed_record(tmp_path, monkeypatch):
    repo = MeasurementRepository(tmp_path)
    first = repo.save(UID, complete_data(), SOURCES, 0)
    monkeypatch.setattr(os, "replace", lambda *a: (_ for _ in ()).throw(OSError("synthetic failure")))
    try:
        with pytest.raises(OSError):
            repo.save(UID, StudyMeasurementData(), SOURCES, 1)
        assert repo.load(UID) == first
        assert not list(tmp_path.glob(".pending-*"))
    finally:
        repo.close()


def test_quota_does_not_evict(tmp_path):
    repo = MeasurementRepository(tmp_path)
    first = repo.save(UID, StudyMeasurementData(), SOURCES, 0)
    repo.max_bytes = repo.size_bytes()
    try:
        with pytest.raises(MeasurementStorageError, match="quota"):
            repo.save(UID, complete_data(), SOURCES, 1)
        assert repo.load(UID) == first
    finally:
        repo.close()


@pytest.mark.parametrize("payload", [b"broken", b'{"format":"sonoforge.study-measurements","schema_version":999}'])
def test_corrupt_or_future_record_never_overwritten(tmp_path, payload):
    path = tmp_path / (study_key(UID) + ".json")
    path.write_bytes(payload)
    repo = MeasurementRepository(tmp_path)
    try:
        with pytest.raises(MeasurementStorageError):
            repo.save(UID, StudyMeasurementData(), SOURCES, 0)
        assert path.read_bytes() == payload
    finally:
        repo.close()


def test_process_lock_and_recovery_after_process_death(tmp_path):
    code = """import sys,time
from pathlib import Path
from echo_personal_tool.infrastructure.measurement_repository import MeasurementRepository
r=MeasurementRepository(Path(sys.argv[1])); r.acquire(); print("locked",flush=True); time.sleep(30)
"""
    child = subprocess.Popen([sys.executable, "-c", code, str(tmp_path)], stdout=subprocess.PIPE)
    repo = MeasurementRepository(tmp_path)
    try:
        assert child.stdout.readline().strip() == b"locked"
        with pytest.raises(MeasurementStorageError, match="busy"):
            repo.acquire()
        child.kill()
        child.wait(timeout=5)
        repo.acquire()  # file is still present, but OS lock has gone
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        child.stdout.close()
        repo.close()


def test_temp_not_recovered_and_symlink_not_followed(tmp_path):
    repo = MeasurementRepository(tmp_path)
    (tmp_path / ".pending-crash.tmp").write_text("partial data")
    repo.acquire()
    assert not (tmp_path / ".pending-crash.tmp").exists()
    repo.close()
    target = tmp_path / "outside"
    target.write_text("untouched")
    try:
        (tmp_path / (study_key(UID) + ".json")).symlink_to(target)
    except OSError:
        pytest.skip("symlinks not permitted")
    with pytest.raises(MeasurementStorageError, match="unsafe_path"):
        repo.load(UID)
    assert target.read_text() == "untouched"


def test_posix_permissions(tmp_path):
    if os.name == "nt":
        pytest.skip("Windows uses profile ACL")
    repo = MeasurementRepository(tmp_path / "records")
    try:
        repo.save(UID, StudyMeasurementData(), SOURCES, 0)
        assert (repo.root.stat().st_mode & 0o777) == 0o700
        assert (repo.root / (study_key(UID) + ".json")).stat().st_mode & 0o777 == 0o600
    finally:
        repo.close()


def test_metrics_manual_clear_and_reset_precedence():
    store = StudyMeasurementSessionStore()
    store.fill_dicom_metrics(UID, 170, None)
    assert store.get(UID).height_source == "dicom"
    store.set_patient_metrics(UID, 180, None)
    store.fill_dicom_metrics(UID, 160, 80)
    assert store.get(UID).height_cm == 180
    assert store.get(UID).weight_kg is None
    assert store.get(UID).weight_source == "cleared"
    store.reset_measurements(UID)
    assert store.get(UID).height_cm == 180
    assert store.get(UID).weight_source == "cleared"
    assert store.get("1.2.99").height_cm is None


def test_snapshot_is_deep_and_restore_does_not_notify():
    events = []
    store = StudyMeasurementSessionStore(lambda *args: events.append(args))
    store.restore(UID, complete_data())
    assert events == []
    detached = store.snapshot(UID)
    detached.contours[0].points.append((99, 99))
    assert len(store.get(UID).contours[0].points) == 3
    store.set_patient_metrics(UID, 181, 78)
    assert len(events) == 1
    store.set_patient_metrics(UID, 181, 78)
    assert len(events) == 1


def test_frame_update_keeps_other_instance_legacy_doppler_contribution():
    """Instance A becomes frame-authoritative; instance B must stay in the aggregate."""
    peak_a = DopplerMeasurementDTO((DopplerPeakMarker("peak-a", 0, -70.0),), (), ())
    peak_b = DopplerMeasurementDTO((DopplerPeakMarker("peak-b", 1, -60.0),), (), ())
    store = StudyMeasurementSessionStore()
    store.restore(
        UID,
        replace(StudyMeasurementData(), doppler_by_instance=(("inst-a", peak_a), ("inst-b", peak_b))),
    )
    assert [m.label for m in store.get(UID).all_doppler_dto.peaks] == ["peak-a", "peak-b"]
    store.set_doppler_for_instance_frame(UID, "inst-a", 0, DopplerMeasurementDTO((), (), ()))
    aggregate = store.get(UID).all_doppler_dto
    assert [m.label for m in aggregate.peaks] == ["peak-b"]
    assert store.get(UID).doppler_by_instance == (("inst-b", peak_b),)


def _schema(name):
    from importlib.resources import files

    return json.loads(files("echo_personal_tool.resources").joinpath(name).read_text())


def test_v2_schema_matches_codec():
    import jsonschema

    schema = _schema("measurement-storage-v2.schema.json")
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(json.loads(dumps(record(complete_data()))), schema)


def _v1_document(data_wire: dict, *, schema_version: int = 1) -> bytes:
    """Build a version-1 document by hand: no semantics key, no identities."""
    return json.dumps(
        {
            "format": FORMAT,
            "schema_version": schema_version,
            "study_uid": UID,
            "revision": 1,
            "saved_at": datetime.now(_UTC).isoformat(),
            "sources": SOURCES,
            "data": data_wire,
        }
    ).encode()


V1_DOPPLER = {
    "peaks": [
        {"label": "TR Vmax", "time_ms": 10.0, "velocity_cm_s": 280.0},
        {"label": "TR Vmax", "time_ms": 20.0, "velocity_cm_s": 330.0},  # stale v1 append
    ],
    "intervals": [],
    "traces": [
        {"label": "AV VTI", "points": [[0.0, 0.0], [100.0, 100.0], [200.0, 0.0]]},
        {"label": "AV VTI", "points": [[300.0, 0.0], [400.0, 100.0], [500.0, 0.0]]},
    ],
}


def test_v1_dump_matches_v1_schema():
    """The v1 schema still describes exactly what a version-1 build wrote."""
    import jsonschema

    wire = json.loads(dumps(record(complete_data())))
    wire.pop("measurement_semantics_version")
    wire["schema_version"] = 1

    def strip(node) -> None:
        if isinstance(node, dict):
            node.pop("measurement_id", None)
            for value in node.values():
                strip(value)
        elif isinstance(node, list):
            for value in node:
                strip(value)

    strip(wire)
    jsonschema.validate(wire, _schema("measurement-storage-v1.schema.json"))
    # ... and such a document loads and migrates to the current version.
    loaded = loads(json.dumps(wire).encode())
    assert loaded["schema_version"] == VERSION
    assert loaded["measurement_semantics_version"] == SEMANTICS_VERSION


def test_v1_document_with_stale_duplicates_migrates():
    """Defensive path: collapse the duplicates a version-1 reader kept hiding."""
    payload = _v1_document({"doppler_by_instance": [[SOP, V1_DOPPLER]]})

    loaded = loads(payload)

    assert loaded["schema_version"] == VERSION
    assert loaded["measurement_semantics_version"] == SEMANTICS_VERSION
    migrated_dto = loaded["data"].doppler_by_instance[0][1]
    # Version 1 displayed and merged only the newest marker of a label.
    assert [(marker.label, marker.velocity_cm_s) for marker in migrated_dto.peaks] == [("TR Vmax", 330.0)]
    # Multi-beat traces stay repeats and become explicit version-2 measurements.
    assert [trace.label for trace in migrated_dto.traces] == ["AV VTI", "AV VTI"]
    assert len({trace.measurement_id for trace in migrated_dto.traces}) == 2
    assert all(trace.measurement_id for trace in migrated_dto.traces)


def test_repeated_measurements_round_trip_and_ambiguous_duplicates_rejected():
    peak = DopplerPeakMarker("TR Vmax", 10.0, 280.0, measurement_id="a")
    second = DopplerPeakMarker("TR Vmax", 20.0, 330.0, measurement_id="b")
    data = replace(
        complete_data(),
        doppler_by_instance=((SOP, DopplerMeasurementDTO(peaks=(peak, second), intervals=(), traces=())),),
        doppler_by_instance_frame=(),
    )

    loaded = loads(dumps(record(data)))

    assert loaded["data"].doppler_by_instance[0][1].peaks == (peak, second)
    # A legacy marker without an identity may coexist with one new measurement
    # of the same parameter: they are two measurements, not an ambiguity.
    with_legacy = replace(
        data,
        doppler_by_instance=(
            (SOP, DopplerMeasurementDTO(peaks=(replace(peak, measurement_id=""), second), intervals=(), traces=())),
        ),
    )
    assert loads(dumps(record(with_legacy)))["data"].doppler_by_instance[0][1].peaks == (
        replace(peak, measurement_id=""),
        second,
    )
    # Two identity-less markers of one label are an ambiguity the merge cannot
    # resolve, so the codec refuses them instead of guessing.
    without_ids = replace(
        data,
        doppler_by_instance=(
            (
                SOP,
                DopplerMeasurementDTO(
                    peaks=(replace(peak, measurement_id=""), replace(second, measurement_id="")),
                    intervals=(),
                    traces=(),
                ),
            ),
        ),
    )
    with pytest.raises(MeasurementStorageError, match="invalid"):
        dumps(record(without_ids))
    # A duplicated identity is the same measurement arriving twice: also refused.
    with pytest.raises(MeasurementStorageError, match="invalid"):
        dumps(
            record(
                replace(
                    data,
                    doppler_by_instance=((SOP, DopplerMeasurementDTO(peaks=(peak, peak), intervals=(), traces=())),),
                )
            )
        )


def test_future_semantics_version_is_read_blocked():
    wire = json.loads(dumps(record()))
    wire["measurement_semantics_version"] = SEMANTICS_VERSION + 1
    with pytest.raises(MeasurementStorageError, match="version"):
        loads(json.dumps(wire).encode())


def test_migrate_is_idempotent_for_current_documents():
    current = loads(dumps(record(complete_data())))
    assert migrate(current) is current
