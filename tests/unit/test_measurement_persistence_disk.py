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


def test_runtime_enable_saves_without_restart(tmp_path, monkeypatch, qapp):
    """Settings toggle applies in-session: enable() hooks the store, the controller
    adopts open studies (contexts), and the next committed edit lands on disk."""
    monkeypatch.setattr("echo_personal_tool.application.measurement_persistence.describe_study", lambda s: SOURCES)
    store = StudyMeasurementSessionStore()
    p = MeasurementPersistence(tmp_path, store, enabled=False)
    p.load([SimpleNamespace(study_uid=UID)], lambda: None)  # open while disabled: no contexts
    store.set_patient_metrics(UID, 175, 72)  # session-only while disabled
    p.enable()
    # The controller adopts open studies right after a runtime enable; without
    # the adoption read a save is refused with `identity` (no checked context).
    p.load([SimpleNamespace(study_uid=UID)], lambda: None, restore=set())
    assert p.flush()
    store.set_linear_measurements_for_instance(UID, SOP, (LinearMeasurement("LVEDD", 20, 10, 0, sop_instance_uid=SOP),))
    assert p.flush()
    record = p.repository.load(UID)
    # The full-study snapshot includes the edit made before enabling.
    assert record["data"].height_cm == 175
    assert len(record["data"].linear_measurements) == 1
    assert p.close()


def test_runtime_disable_stops_tracking_after_settled_edits(tmp_path, monkeypatch, qapp):
    p, store = setup_persistence(tmp_path, monkeypatch, qapp)
    store.set_patient_metrics(UID, 175, 72)
    assert p.has_pending_edits
    assert p.flush()  # «save and turn off» settles unsaved edits first
    assert not p.has_pending_edits
    p.disable()
    store.set_patient_metrics(UID, 180, 74)  # session-only again
    assert p.flush()
    assert p.repository.load(UID)["data"].height_cm == 175
    assert p.close()


def test_runtime_enable_with_open_study_reports_record_conflict(tmp_path, monkeypatch, qapp):
    p, store = setup_persistence(tmp_path, monkeypatch, qapp)
    store.set_patient_metrics(UID, 175, 72)
    assert p.flush()
    assert p.close()

    monkeypatch.setattr("echo_personal_tool.application.measurement_persistence.describe_study", lambda s: SOURCES)
    store2 = StudyMeasurementSessionStore()
    p2 = MeasurementPersistence(tmp_path, store2, enabled=False)
    p2.load([SimpleNamespace(study_uid=UID)], lambda: None)
    store2.set_patient_metrics(UID, 180, 74)  # live session edits the record has never seen
    p2.enable()
    conflicts = []
    p2.load(
        [SimpleNamespace(study_uid=UID)],
        lambda: conflicts.extend(sorted(p2.restore_conflicts)),
        restore=set(),
    )
    assert p2.flush()
    assert conflicts == [UID]
    assert store2.get(UID).height_cm == 180  # RAM untouched by the adopt read
    assert UID not in p2.loaded
    # «Keep current»: RAM is authoritative; the next save rewrites the record.
    p2.adopt_conflicts()
    assert UID in p2.loaded
    assert not p2.restore_conflicts
    store2.set_patient_metrics(UID, 181, 75)
    assert p2.flush()
    assert p2.repository.load(UID)["data"].height_cm == 181
    assert p2.close()


def test_runtime_enable_restore_set_adopts_record_into_ram(tmp_path, monkeypatch, qapp):
    p, store = setup_persistence(tmp_path, monkeypatch, qapp)
    store.set_patient_metrics(UID, 175, 72)
    assert p.flush()
    assert p.close()

    monkeypatch.setattr("echo_personal_tool.application.measurement_persistence.describe_study", lambda s: SOURCES)
    store2 = StudyMeasurementSessionStore()
    p2 = MeasurementPersistence(tmp_path, store2, enabled=False)
    p2.enable()
    p2.load([SimpleNamespace(study_uid=UID)], lambda: None, restore={UID})
    assert p2.flush()
    assert store2.get(UID).height_cm == 175  # record applied to the live store
    assert UID in p2.loaded
    assert not p2.restore_conflicts
    assert p2.close()


def test_enable_without_adoption_refuses_save_with_identity(tmp_path, monkeypatch, qapp):
    """Why the controller adopts open studies: saving needs a checked context,
    and a refused save keeps the shutdown barrier (fail-fast, no silent loss)."""
    monkeypatch.setattr("echo_personal_tool.application.measurement_persistence.describe_study", lambda s: SOURCES)
    store = StudyMeasurementSessionStore()
    p = MeasurementPersistence(tmp_path, store, enabled=False)
    p.load([SimpleNamespace(study_uid=UID)], lambda: None)
    p.enable()
    store.set_patient_metrics(UID, 175, 72)
    assert not p.flush()  # refused: `identity`, nothing written
    assert p.repository.load(UID) is None
    # The adoption read (what the controller does right after a runtime enable) unblocks it.
    p.load([SimpleNamespace(study_uid=UID)], lambda: None, restore=set())
    assert p.flush()
    assert p.repository.load(UID)["data"].height_cm == 175
    assert p.close()
