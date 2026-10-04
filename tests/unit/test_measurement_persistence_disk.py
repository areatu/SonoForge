"""Coordinator tests with a real repository and Qt events, not viewer refresh mocks."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from echo_personal_tool.application.measurement_persistence import MeasurementPersistence, combine, scoped
from echo_personal_tool.application.study_measurement_session import StudyMeasurementData, StudyMeasurementSessionStore
from echo_personal_tool.domain.models import LinearMeasurement
from echo_personal_tool.infrastructure.measurement_repository import MeasurementRepository

UID = "1.2.3"
SOP = "1.2.3.4"
SOURCES = {SOP: {"fingerprint": "a" * 64, "frames": 1, "spacing": [0.5, 0.5]}}
pytestmark = pytest.mark.gui


def setup_persistence(tmp_path, monkeypatch, qapp):
    monkeypatch.setattr("echo_personal_tool.application.measurement_persistence.describe_study", lambda s: SOURCES)
    store = StudyMeasurementSessionStore()
    p = MeasurementPersistence(tmp_path, store, enabled=True)
    p.load([SimpleNamespace(study_uid=UID)], lambda: None)
    assert p.flush()
    return p, store


def test_restart_metrics_and_authoritative_empty_snapshot(tmp_path, monkeypatch, qapp):
    p, store = setup_persistence(tmp_path, monkeypatch, qapp)
    store.set_patient_metrics(UID, 175, 72)
    store.set_linear_measurements_for_instance(UID, SOP, (LinearMeasurement("LVEDD", 20, 10, 0, sop_instance_uid=SOP),))
    assert p.flush()
    assert p.close()
    second, restored = setup_persistence(tmp_path, monkeypatch, qapp)
    assert restored.get(UID).height_cm == 175
    assert restored.get(UID).weight_kg == 72
    assert len(restored.get(UID).linear_measurements) == 1
    restored.set_linear_measurements_for_instance(UID, SOP, ())
    assert second.flush()
    assert second.close()
    third, restored = setup_persistence(tmp_path, monkeypatch, qapp)
    assert restored.get(UID).linear_measurements == ()
    assert restored.get(UID).height_cm == 175
    assert third.close()


def test_failed_save_keeps_dirty_snapshot_and_retry(tmp_path, monkeypatch, qapp):
    p, store = setup_persistence(tmp_path, monkeypatch, qapp)
    original = p.repository.save
    monkeypatch.setattr(p.repository, "save", lambda *args: (_ for _ in ()).throw(OSError()))
    store.set_patient_metrics(UID, 173, 70)
    assert not p.flush()
    assert store.get(UID).height_cm == 173
    monkeypatch.setattr(p.repository, "save", original)
    assert p.flush()
    assert p.repository.load(UID)["data"].height_cm == 173
    assert p.close()


def test_delete_all_queued_save_cannot_resurrect(tmp_path, monkeypatch, qapp):
    p, store = setup_persistence(tmp_path, monkeypatch, qapp)
    store.set_patient_metrics(UID, 173, 70)
    p.save_pending()
    results = []
    p.delete_all(results.append)
    assert p.flush()
    assert results == [None]
    assert p.repository.load(UID) is None
    store.set_patient_metrics(UID, 174, 70)
    assert p.flush()
    assert p.repository.load(UID) is None
    assert p.close()


def test_disabled_no_root_created(tmp_path, qapp):
    root = tmp_path / "not-created"
    store = StudyMeasurementSessionStore()
    p = MeasurementPersistence(root, store, enabled=False)
    p.load([], lambda: None)
    store.set_patient_metrics(UID, 180, 80)
    assert p.close()
    assert not root.exists()


def test_partial_projection_preserves_unavailable_measurements():
    a = LinearMeasurement("A", 20, 10, 0, sop_instance_uid="a")
    b = LinearMeasurement("B", 20, 10, 0, sop_instance_uid="b")
    full = StudyMeasurementData(linear_measurements=(a, b))
    visible = scoped(full, {"a"})
    assert visible.linear_measurements == (a,)
    updated = replace(visible, linear_measurements=())
    assert combine(full, updated, {"a"}).linear_measurements == (b,)


def test_source_mismatch_blocks_restore_and_overwrite(tmp_path, monkeypatch, qapp):
    p, store = setup_persistence(tmp_path, monkeypatch, qapp)
    store.set_patient_metrics(UID, 173, 70)
    assert p.close()
    repo = MeasurementRepository(tmp_path)
    before = repo.load(UID)
    changed = {SOP: {**SOURCES[SOP], "fingerprint": "b" * 64}}
    monkeypatch.setattr("echo_personal_tool.application.measurement_persistence.describe_study", lambda s: changed)
    next_store = StudyMeasurementSessionStore()
    next_p = MeasurementPersistence(tmp_path, next_store, enabled=True)
    next_p.load([SimpleNamespace(study_uid=UID)], lambda: None)
    assert next_p.flush()
    assert next_store.get(UID).height_cm is None
    next_store.set_patient_metrics(UID, 180, 80)
    assert not next_p.flush()
    assert repo.load(UID) == before
    next_p._dirty.clear()  # explicit test cleanup, not product behavior
    assert next_p.close()


def test_export_import_checked_roundtrip(tmp_path, monkeypatch, qapp):
    p, store = setup_persistence(tmp_path / "repo", monkeypatch, qapp)
    store.set_patient_metrics(UID, 175, 70)
    assert p.flush()
    export = tmp_path / "export.json"
    results = []
    p.export_study(UID, export, results.append)
    assert p.flush() and results == [None]
    store.set_patient_metrics(UID, 185, 80)
    assert p.flush()
    p.import_study(UID, export, results.append)
    assert p.flush()
    assert results == [None, None]
    assert store.get(UID).height_cm == 175
    assert p.close()


def test_ai_preview_does_not_erase_last_accepted_contour(tmp_path, monkeypatch, qapp):
    from echo_personal_tool.domain.models import Contour

    p, store = setup_persistence(tmp_path, monkeypatch, qapp)
    accepted = Contour("ED", points=[(1.0, 1.0), (2.0, 3.0), (3.0, 1.0)], sop_instance_uid=SOP, frame_index=0)
    store.merge_contours(UID, (accepted,))
    assert p.flush()
    store.merge_contours(UID, (replace(accepted, review_pending=True, points=[(0.0, 0.0)]),))
    assert p.flush()
    assert p.repository.load(UID)["data"].contours == (accepted,)
    assert p.close()


def test_explicit_delete_one_suppresses_autosave_until_reopen(tmp_path, monkeypatch, qapp):
    from echo_personal_tool.infrastructure.measurement_codec import study_key

    p, store = setup_persistence(tmp_path, monkeypatch, qapp)
    store.set_patient_metrics(UID, 173, 70)
    assert p.flush()
    results = []
    p.delete_record(study_key(UID), results.append)
    assert p.flush() and results == [None]
    store.set_patient_metrics(UID, 178, 70)
    assert p.flush()
    assert p.repository.load(UID) is None
    assert p.close()
    assert p.close()  # duplicate close event is harmless


def test_export_when_autosave_disabled_does_not_create_repository(tmp_path, monkeypatch, qapp):
    monkeypatch.setattr("echo_personal_tool.application.measurement_persistence.describe_study", lambda s: SOURCES)
    root = tmp_path / "not-created"
    store = StudyMeasurementSessionStore()
    p = MeasurementPersistence(root, store, enabled=False)
    p.load([SimpleNamespace(study_uid=UID)], lambda: None)
    store.set_patient_metrics(UID, 178, 70)
    results = []
    export = tmp_path / "export.json"
    p.export_study(UID, export, results.append)
    assert p.flush() and results == [None]
    assert export.exists() and not root.exists()
    assert p.close()


def test_doppler_authoritative_deletion_roundtrips(tmp_path, monkeypatch, qapp):
    from echo_personal_tool.domain.models.doppler import DopplerMeasurementDTO, DopplerPeakMarker

    p, store = setup_persistence(tmp_path, monkeypatch, qapp)
    dto = DopplerMeasurementDTO((DopplerPeakMarker("E", 10, 80),), (), ())
    store.set_doppler_for_instance_frame(UID, SOP, 0, dto)
    assert p.flush()
    empty = DopplerMeasurementDTO((), (), ())
    store.set_doppler_for_instance_frame(UID, SOP, 0, empty)
    assert p.close()
    next_p, next_store = setup_persistence(tmp_path, monkeypatch, qapp)
    assert next_store.get(UID).all_doppler_dto == empty
    assert next_p.close()


def test_new_edit_during_failed_write_never_requeues_old_snapshot(tmp_path, monkeypatch, qapp):
    from threading import Event

    p, store = setup_persistence(tmp_path, monkeypatch, qapp)
    original = p.repository.save
    entered, release = Event(), Event()
    calls = []

    def save(*args):
        calls.append(args[1].height_cm)
        if len(calls) == 1:
            entered.set()
            assert release.wait(2)
            raise OSError("synthetic first failure")
        return original(*args)

    monkeypatch.setattr(p.repository, "save", save)
    store.set_patient_metrics(UID, 173, 70)
    p.save_pending()
    assert entered.wait(2)
    store.set_patient_metrics(UID, 180, 80)
    p.save_pending()  # coalesced, not a second queued stale write
    release.set()
    assert p.flush()
    assert calls == [173, 180]
    assert p.repository.load(UID)["data"].height_cm == 180
    assert not p._dirty
    assert p.close()


def test_export_cannot_bypass_managed_repository_lock_and_revision(tmp_path, monkeypatch, qapp):
    from echo_personal_tool.infrastructure.measurement_codec import study_key

    p, store = setup_persistence(tmp_path, monkeypatch, qapp)
    store.set_patient_metrics(UID, 175, 70)
    assert p.flush()
    before = p.repository.load(UID)
    results = []
    p.export_study(UID, tmp_path / (study_key(UID) + ".json"), results.append)
    assert p.flush()
    assert results == ["unsafe_path"]
    assert p.repository.load(UID) == before
    assert p.close()
