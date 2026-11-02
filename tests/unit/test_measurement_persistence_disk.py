"""Coordinator tests with a real repository and Qt events, not viewer refresh mocks."""

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from echo_personal_tool.application.measurement_persistence import MeasurementPersistence, combine, scoped
from echo_personal_tool.application.study_measurement_session import StudyMeasurementData, StudyMeasurementSessionStore
from echo_personal_tool.domain.models import LinearMeasurement
from echo_personal_tool.domain.models.manual_calculator_input import ManualCalculatorInput
from echo_personal_tool.domain.models.result_provenance import BSA_SOURCE_DERIVED, BSA_SOURCE_MANUAL
from echo_personal_tool.infrastructure.measurement_codec import FORMAT
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


def test_failed_save_keeps_dirty_snapshot_and_retry(tmp_path, monkeypatch, qapp, caplog):
    p, store = setup_persistence(tmp_path, monkeypatch, qapp)
    original = p.repository.save
    monkeypatch.setattr(
        p.repository, "save", lambda *args: (_ for _ in ()).throw(OSError("PHI_QH4A_PRIVATE /private/patient.dcm"))
    )
    store.set_patient_metrics(UID, 173, 70)
    assert not p.flush()
    assert "operation=measurement.save code=io error_type=OSError" in caplog.text
    assert "PHI_QH4A_PRIVATE" not in caplog.text
    assert "/private/patient.dcm" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
    assert store.get(UID).height_cm == 173
    monkeypatch.setattr(p.repository, "save", original)
    assert p.flush()
    assert p.repository.load(UID)["data"].height_cm == 173
    assert p.close()


def test_discard_unsaved_unblocks_navigation_and_keeps_autosave(tmp_path, monkeypatch, qapp):
    """«Don't save» drops the queued writes so the study switch can proceed."""
    p, store = setup_persistence(tmp_path, monkeypatch, qapp)
    original = p.repository.save
    monkeypatch.setattr(p.repository, "save", lambda *args: (_ for _ in ()).throw(OSError("disk unplugged")))
    store.set_patient_metrics(UID, 173, 70)
    assert not p.flush()
    assert p.discard_unsaved()
    assert p.flush()  # nothing pending: navigation/close are unblocked
    assert p.enabled  # autosave stays on for the next study
    # Later edits of the next study still save normally.
    monkeypatch.setattr(p.repository, "save", original)
    store.set_patient_metrics(UID, 180, 74)
    assert p.flush()
    assert p.repository.load(UID)["data"].height_cm == 180
    assert p.close()


def test_discard_unsaved_fences_inflight_failure_from_requeue(tmp_path, monkeypatch, qapp):
    """A write already on the worker cannot requeue its snapshot after discard."""
    p, store = setup_persistence(tmp_path, monkeypatch, qapp)
    original = p.repository.save
    monkeypatch.setattr(p.repository, "save", lambda *args: (_ for _ in ()).throw(OSError("disk unplugged")))
    store.set_patient_metrics(UID, 173, 70)
    p.save_pending()  # hand the failing batch to the worker
    assert p.discard_unsaved()  # user answered «Don't save» mid-write
    assert p.flush()  # late failure must not resurrect the dirty snapshot
    assert p.enabled
    monkeypatch.setattr(p.repository, "save", original)
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


def test_save_writes_the_bsa_basis_of_the_record(tmp_path, monkeypatch, qapp):
    """QH-1b.2 slice 2: the write freezes the BSA behind the derived results."""
    p, store = setup_persistence(tmp_path, monkeypatch, qapp)
    store.set_manual_bsa(UID, 1.55)
    assert p.flush()
    record = p.repository.load(UID)
    assert record is not None
    assert record["data"].manual_bsa_m2 == pytest.approx(1.55)
    assert record["data"].bsa_basis is not None
    assert record["data"].bsa_basis.source == BSA_SOURCE_MANUAL
    assert record["data"].bsa_basis.value == pytest.approx(1.55)
    assert p.close()


def test_restart_keeps_the_manual_bsa_and_its_basis(tmp_path, monkeypatch, qapp):
    p, store = setup_persistence(tmp_path, monkeypatch, qapp)
    store.set_manual_bsa(UID, 1.55)
    assert p.flush()
    assert p.close()

    second, restored = setup_persistence(tmp_path, monkeypatch, qapp)
    data = restored.get(UID)
    assert data.manual_bsa_m2 == pytest.approx(1.55)
    assert data.bsa_basis is not None and data.bsa_basis.source == BSA_SOURCE_MANUAL
    # The record and the study agree on the BSA, so nothing is flagged.
    assert second.close()


def test_saved_signal_carries_the_frozen_basis(tmp_path, monkeypatch, qapp):
    p, store = setup_persistence(tmp_path, monkeypatch, qapp)
    seen: list[tuple[str, object]] = []
    p.saved.connect(lambda uid, basis: seen.append((uid, basis)))
    store.set_patient_metrics(UID, 170.0, 70.0)
    assert p.flush()
    assert len(seen) == 1
    uid, basis = seen[0]
    assert uid == UID
    # QH-1b.2 slices 3a–c: saved now carries a 4-tuple (bsa, simpson, doppler, derived)
    if isinstance(basis, tuple):
        basis = basis[0]
    assert basis is not None and basis.source == BSA_SOURCE_DERIVED
    assert p.close()


def test_failed_save_does_not_report_a_stored_basis(tmp_path, monkeypatch, qapp):
    """A failed write must not tell the study its record was updated."""
    p, store = setup_persistence(tmp_path, monkeypatch, qapp)
    seen: list[tuple[str, object]] = []
    p.saved.connect(lambda uid, basis: seen.append((uid, basis)))
    monkeypatch.setattr(p.repository, "save", lambda *args: (_ for _ in ()).throw(OSError("disk")))
    store.set_patient_metrics(UID, 170.0, 70.0)
    assert not p.flush()
    assert seen == []
    # The failed write keeps the study dirty, and that blocks navigation.
    assert not p.close()


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
    # An application caller cannot bypass the read-only preview boundary.
    p.import_study(UID, export, results.append, preview=None)
    assert results == [None, "invalid"]
    assert store.get(UID).height_cm == 185
    previews = []
    p.preview_import(UID, export, previews.append)
    assert p.flush() and previews[0].compatible
    p.import_study(UID, export, results.append, preview=previews[0])
    assert p.flush()
    assert results == [None, "invalid", None]
    assert store.get(UID).height_cm == 175
    assert p.close()


def test_import_preview_precedes_full_replace_and_preserves_manual_input_provenance(tmp_path, monkeypatch, qapp):
    p, store = setup_persistence(tmp_path / "repo", monkeypatch, qapp)
    store.set_patient_metrics(UID, 175, 70)
    store.set_manual_calculator_input(UID, "rap", 8.0)
    assert p.flush()
    export = tmp_path / "export.json"
    results = []
    p.export_study(UID, export, results.append)
    assert p.flush() and results == [None]

    # Preview is read-only: RAM still contains the newer session value.
    store.set_patient_metrics(UID, 185, 80)
    store.set_manual_calculator_input(UID, "rap", 15.0)
    assert p.flush()
    previews = []
    p.preview_import(UID, export, previews.append)
    assert p.flush() and len(previews) == 1
    preview = previews[0]
    assert preview.compatible
    assert preview.categories == ("metrics", "calculator_inputs")
    assert preview.category_counts == (("metrics", 2), ("calculator_inputs", 1))
    assert preview.source_count == 1
    assert preview.unavailable_sources == 0
    assert store.get(UID).height_cm == 185

    p.import_study(UID, export, results.append, preview=preview)
    assert p.flush() and results == [None, None]
    restored = store.get(UID)
    assert restored.height_cm == 175
    assert restored.manual_calculator_inputs == (ManualCalculatorInput("rap", 8.0),)
    assert p.close()


def test_import_preview_blocks_source_mismatch_without_ram_or_disk_change(tmp_path, monkeypatch, qapp):
    p, store = setup_persistence(tmp_path / "repo", monkeypatch, qapp)
    store.set_patient_metrics(UID, 175, 70)
    assert p.flush()
    export = tmp_path / "export.json"
    p.export_study(UID, export, lambda error: None)
    assert p.flush()
    wire = json.loads(export.read_text())
    wire["sources"][SOP]["fingerprint"] = "b" * 64
    export.write_text(json.dumps(wire))

    previews = []
    p.preview_import(UID, export, previews.append)
    assert p.flush()
    preview = previews[0]
    assert not preview.compatible
    assert preview.error == "source"
    assert preview.unavailable_sources == 1
    assert store.get(UID).height_cm == 175
    before = p.repository.load(UID)
    results = []
    p.import_study(UID, export, results.append, preview=preview)
    assert results == ["source"]
    assert p.repository.load(UID) == before
    assert p.close()


def test_import_refuses_bytes_changed_after_preview(tmp_path, monkeypatch, qapp):
    p, store = setup_persistence(tmp_path / "repo", monkeypatch, qapp)
    store.set_patient_metrics(UID, 175, 70)
    assert p.flush()
    export = tmp_path / "export.json"
    p.export_study(UID, export, lambda error: None)
    assert p.flush()
    previews = []
    p.preview_import(UID, export, previews.append)
    assert p.flush()
    export.write_bytes(export.read_bytes() + b" ")

    results = []
    p.import_study(UID, export, results.append, preview=previews[0])
    assert p.flush()
    assert results == ["conflict"]
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


def test_reset_barrier_discards_late_pre_reset_save_callback(tmp_path, monkeypatch, qapp):
    from threading import Event

    p, store = setup_persistence(tmp_path, monkeypatch, qapp)
    original = p.repository.save
    entered, release = Event(), Event()

    def delayed_save(*args):
        entered.set()
        assert release.wait(2)
        return original(*args)

    monkeypatch.setattr(p.repository, "save", delayed_save)
    store.set_manual_calculator_input(UID, "rap", 8.0)
    p.save_pending()
    assert entered.wait(2)
    # The controller calls this barrier before its authoritative reset.
    p.barrier(UID)
    store.reset_measurements(UID)
    release.set()
    assert p.flush()
    assert p.repository.load(UID)["data"].manual_calculator_inputs == ()
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


def test_runtime_enable_saves_pre_enable_edits_with_no_edits_after(tmp_path, monkeypatch, qapp):
    """#323: work done while autosave was off must reach disk when the user
    enables autosave and closes without further edits. Regression test: the
    adoption read used to leave the live session un-dirtied, so flush()/close()
    reported success while the repository stayed empty (silent data loss)."""
    monkeypatch.setattr("echo_personal_tool.application.measurement_persistence.describe_study", lambda s: SOURCES)
    store = StudyMeasurementSessionStore()
    p = MeasurementPersistence(tmp_path, store, enabled=False)
    p.load([SimpleNamespace(study_uid=UID)], lambda: None)  # open while disabled: no contexts
    store.set_patient_metrics(UID, 175, 72)  # session-only while disabled
    store.set_linear_measurements_for_instance(UID, SOP, (LinearMeasurement("LVEDD", 20, 10, 0, sop_instance_uid=SOP),))
    p.enable()
    p.load([SimpleNamespace(study_uid=UID)], lambda: None, restore=set())  # controller adoption
    assert p.flush()
    record = p.repository.load(UID)
    assert record is not None
    assert record["data"].height_cm == 175
    assert len(record["data"].linear_measurements) == 1
    assert p.close()
    # And it survives a restart.
    second, restored = setup_persistence(tmp_path, monkeypatch, qapp)
    assert restored.get(UID).height_cm == 175
    assert len(restored.get(UID).linear_measurements) == 1
    assert second.close()


def test_runtime_enable_with_empty_session_writes_no_record(tmp_path, monkeypatch, qapp):
    """#323 guard: adopting an untouched live session must not create records."""
    monkeypatch.setattr("echo_personal_tool.application.measurement_persistence.describe_study", lambda s: SOURCES)
    store = StudyMeasurementSessionStore()
    p = MeasurementPersistence(tmp_path, store, enabled=False)
    p.load([SimpleNamespace(study_uid=UID)], lambda: None)
    p.enable()
    p.load([SimpleNamespace(study_uid=UID)], lambda: None, restore=set())
    assert p.flush()
    assert p.repository.load(UID) is None
    assert p.close()


def test_runtime_enable_conflict_waits_for_resolution_then_saves_ram(tmp_path, monkeypatch, qapp):
    """#323: an adoption conflict must not overwrite the saved record before the
    user decides; resolving it as «keep RAM» must persist RAM even without
    further edits (adopt_conflicts had the same missing dirty-mark)."""
    seeded, seeded_store = setup_persistence(tmp_path, monkeypatch, qapp)
    seeded_store.set_patient_metrics(UID, 160, 60)
    assert seeded.flush()
    assert seeded.close()

    store = StudyMeasurementSessionStore()
    p = MeasurementPersistence(tmp_path, store, enabled=False)
    p.load([SimpleNamespace(study_uid=UID)], lambda: None)  # open while disabled
    store.set_patient_metrics(UID, 175, 72)  # RAM-only work
    p.enable()
    p.load([SimpleNamespace(study_uid=UID)], lambda: None, restore=set())
    assert p.flush()
    assert UID in p.restore_conflicts
    assert p.repository.load(UID)["data"].height_cm == 160  # disk untouched pre-resolution
    p.adopt_conflicts()  # user keeps the live session; no further edits
    assert p.flush()
    assert p.repository.load(UID)["data"].height_cm == 175
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


# ── QH-0 reproduction + QH-1a.1: saved-record listing via the file repository ──


def test_list_record_summaries_includes_saved_after_restart(tmp_path, monkeypatch, qapp):
    """A-01: a real save then restart must surface the saved study on the StartPage."""
    p, store = setup_persistence(tmp_path, monkeypatch, qapp)
    store.set_patient_metrics(UID, 175, 70)
    assert p.flush()
    assert p.close()
    # restart: a fresh persistence over the same repository
    second = setup_persistence(tmp_path, monkeypatch, qapp)[0]
    listing = second.list_record_summaries()
    assert listing.list_error is None
    assert len(listing.summaries) == 1
    summary = listing.summaries[0]
    assert summary.status == "readable"
    assert summary.study_uid == UID
    assert summary.measurement_count == 1
    assert summary.measurement_types == (SOP,)
    assert summary.revision >= 1
    assert summary.saved_at
    second.close()


def test_list_record_summaries_classifies_corrupt_and_unsupported_neighbours(tmp_path, monkeypatch, qapp):
    """One bad neighbour must not hide the rest; each entry is classified (§5.1)."""
    p, store = setup_persistence(tmp_path, monkeypatch, qapp)
    store.set_patient_metrics(UID, 175, 70)
    assert p.flush()
    # corrupt neighbour (not valid JSON)
    (tmp_path / ("c" * 64 + ".json")).write_bytes(b"not json at all")
    # unsupported: schema_version outside the supported range
    (tmp_path / ("f" * 64 + ".json")).write_bytes(json.dumps({"format": FORMAT, "schema_version": 999}).encode())
    listing = p.list_record_summaries()
    statuses = {s.status for s in listing.summaries}
    assert statuses == {"readable", "corrupt", "unsupported"}
    assert listing.list_error is None
    assert any(s.study_uid == UID for s in listing.summaries if s.status == "readable")
    p.close()


def test_list_record_summaries_list_error_distinct_from_empty(tmp_path, monkeypatch, qapp):
    """A whole-list failure is reported, not silently collapsed into an empty store."""
    p, store = setup_persistence(tmp_path, monkeypatch, qapp)
    empty = p.list_record_summaries()
    assert empty.summaries == []
    assert empty.list_error is None  # clean empty store

    def boom():
        raise OSError("disk gone")

    monkeypatch.setattr(p.repository, "entries", boom)
    failed = p.list_record_summaries()
    assert failed.summaries == []
    assert failed.list_error is not None  # distinguishable from a clean empty store
    p.close()


def test_list_record_summaries_disabled_returns_empty(tmp_path, qapp):
    """Off-policy: a disabled persistence enumerates nothing and reports no error (§5.1)."""
    store = StudyMeasurementSessionStore()
    p = MeasurementPersistence(tmp_path, store, enabled=False)
    p.load([], lambda: None)
    listing = p.list_record_summaries()
    assert listing.summaries == []
    assert listing.list_error is None
    assert p.close()


def _relocated_import(tmp_path):
    """Real source hashing and scanner identities, no descriptor mocks."""
    import shutil

    from echo_personal_tool.infrastructure.local_scanner import LocalMediaDirectoryScanner
    from tests.fixtures.generate_synthetic_media import write_synthetic_png

    old_dir, new_dir = tmp_path / "old", tmp_path / "new"
    old_dir.mkdir()
    write_synthetic_png(old_dir / "clip.png")
    original = LocalMediaDirectoryScanner().scan(old_dir)[0]
    store = StudyMeasurementSessionStore()
    p = MeasurementPersistence(tmp_path / "repo", store, enabled=True)
    p.load([original], lambda: None)
    assert p.flush()
    uid = original.study_uid
    sop = original.series[0].instances[0].sop_instance_uid
    store.set_linear_measurements_for_instance(uid, sop, (LinearMeasurement("LVEDD", 20, 10, 0, sop_instance_uid=sop),))
    store.set_patient_metrics(uid, 175, 70)
    assert p.flush()
    export = tmp_path / "export.json"
    errors = []
    p.export_study(uid, export, errors.append)
    assert p.flush() and errors == [None]
    original_record = p.repository.load(uid)
    shutil.move(str(old_dir), new_dir)
    (new_dir / "clip.png").rename(new_dir / "renamed.png")
    moved = LocalMediaDirectoryScanner().scan(new_dir)[0]
    p.load([moved], lambda: None)
    assert p.flush()
    assert not store.get(moved.study_uid).linear_measurements  # no automatic remap
    return p, store, original, moved, export, original_record


def test_explicit_hash_remap_preview_import_and_restart(tmp_path, qapp):
    p, store, original, moved, export, old_record = _relocated_import(tmp_path)
    uid = moved.study_uid
    previews = []
    p.preview_import(uid, export, previews.append)
    assert p.flush()
    preview = previews[0]
    assert preview.compatible and preview.remapped_sources == 1
    assert preview.unavailable_sources == preview.additional_live_sources == 0
    assert not store.get(uid).linear_measurements and p.repository.load(uid) is None
    assert str(tmp_path) not in repr(preview) and uid not in repr(preview)
    errors = []
    p.import_study(uid, export, errors.append, preview=preview)
    assert p.flush() and errors == [None]
    new_sop = moved.series[0].instances[0].sop_instance_uid
    assert store.get(uid).linear_measurements[0].sop_instance_uid == new_sop
    assert p.repository.load(original.study_uid) == old_record
    assert set(p.sources[uid]) == {new_sop}
    assert p.close()
    restored = StudyMeasurementSessionStore()
    second = MeasurementPersistence(tmp_path / "repo", restored, enabled=True)
    try:
        second.load([moved], lambda: None)
        assert second.flush()
        assert restored.get(uid).linear_measurements == store.get(uid).linear_measurements
        assert restored.get(uid).height_cm == 175
        # Continued edits use the new identity, not the source export's revision.
        restored.set_patient_metrics(uid, 176, 70)
        assert second.flush() and second.repository.load(uid)["revision"] == 2
    finally:
        assert second.close()


@pytest.mark.parametrize("fault", ["changed-before-preview", "changed-after-preview", "duplicate", "cancel"])
def test_remap_refusal_or_cancel_leaves_ram_and_disk_unchanged(tmp_path, qapp, fault):
    import shutil

    from echo_personal_tool.infrastructure.local_scanner import LocalMediaDirectoryScanner

    p, store, original, moved, export, old_record = _relocated_import(tmp_path)
    uid = moved.study_uid
    source = moved.series[0].instances[0].path
    if fault == "changed-before-preview":
        source.write_bytes(source.read_bytes() + b"changed")
    if fault == "duplicate":
        shutil.copyfile(source, source.with_name("duplicate.png"))
        moved = LocalMediaDirectoryScanner().scan(source.parent)[0]
        p.load([moved], lambda: None)
        assert p.flush()
    before = store.snapshot(uid)
    previews = []
    p.preview_import(uid, export, previews.append)
    assert p.flush()
    if fault in ("changed-before-preview", "duplicate"):
        assert not previews[0].compatible
    else:
        assert previews[0].compatible
    if fault == "changed-after-preview":
        source.write_bytes(source.read_bytes() + b"changed")
        errors = []
        p.import_study(uid, export, errors.append, preview=previews[0])
        assert p.flush() and errors == ["source"]
    assert store.snapshot(uid) == before
    assert p.repository.load(uid) is None
    assert p.repository.load(original.study_uid) == old_record
    assert p.close()


def _fail_directory_sync(monkeypatch):
    import errno
    import os
    import stat

    if os.name == "nt":
        pytest.skip("POSIX directory fsync")
    real_fsync = os.fsync

    def fail(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError(errno.EIO, "PHI_PRIVATE_DIRECTORY_SYNC")
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail)


def test_directory_sync_failed_save_keeps_dirty_and_reconciles_retry(tmp_path, monkeypatch, qapp, caplog):
    p, store = setup_persistence(tmp_path, monkeypatch, qapp)
    store.set_patient_metrics(UID, 170, 70)
    assert p.flush()
    saved = []
    p.saved.connect(lambda *args: saved.append(args))
    with monkeypatch.context() as patch:
        _fail_directory_sync(patch)
        store.set_patient_metrics(UID, 175, 70)
        assert not p.flush()
        assert p.has_pending_edits and not saved
        assert store.get(UID).height_cm == 175
        observed = p.repository.load(UID)
        assert observed["data"].height_cm == 175
        assert p._contexts[UID][0]["revision"] == observed["revision"]
        assert "PHI_PRIVATE_DIRECTORY_SYNC" not in caplog.text
    assert p.flush()
    assert not p.has_pending_edits and len(saved) == 1
    assert p.repository.load(UID)["revision"] == observed["revision"] + 1
    assert p.close()


def test_directory_sync_failed_import_does_not_restore_ram_and_can_retry(tmp_path, monkeypatch, qapp):
    p, store = setup_persistence(tmp_path / "repo", monkeypatch, qapp)
    store.set_patient_metrics(UID, 170, 70)
    assert p.flush()
    export = tmp_path / "export.json"
    p.export_study(UID, export, lambda error: None)
    assert p.flush()
    store.set_patient_metrics(UID, 180, 70)
    assert p.flush()
    previews = []
    p.preview_import(UID, export, previews.append)
    assert p.flush()
    errors, restored = [], []
    p.restored.connect(restored.append)
    with monkeypatch.context() as patch:
        _fail_directory_sync(patch)
        p.import_study(UID, export, errors.append, preview=previews[0])
        assert p.flush()  # operation drained; its callback reports failure
        assert errors == ["io"] and not restored
        assert store.get(UID).height_cm == 180
        assert p.repository.load(UID)["data"].height_cm == 170
    p.import_study(UID, export, errors.append, preview=previews[0])
    assert p.flush() and errors == ["io", None]
    assert restored == [UID] and store.get(UID).height_cm == 170
    assert p.close()


@pytest.mark.parametrize("operation", ["delete_record", "delete_all"])
def test_directory_sync_failed_delete_recovers_current_ram_for_retry(tmp_path, monkeypatch, qapp, operation):
    from echo_personal_tool.infrastructure.measurement_codec import study_key

    p, store = setup_persistence(tmp_path, monkeypatch, qapp)
    store.set_patient_metrics(UID, 170, 70)
    assert p.flush()
    errors = []
    with monkeypatch.context() as patch:
        _fail_directory_sync(patch)
        if operation == "delete_record":
            p.delete_record(study_key(UID), errors.append)
        else:
            p.delete_all(errors.append)
        assert not p.flush()  # retry also cannot get durable acknowledgement
        assert errors == ["io"]
        assert store.get(UID).height_cm == 170
        assert p.has_pending_edits
    assert p.flush()
    assert p.repository.load(UID)["data"].height_cm == 170
    assert p.close()


def test_unavailable_record_logs_safe_boundary_failure(tmp_path, monkeypatch, qapp, caplog):
    p, _store = setup_persistence(tmp_path, monkeypatch, qapp)
    path = tmp_path / "patient-1.2.3.json"
    monkeypatch.setattr(
        type(path), "open", lambda *a, **kw: (_ for _ in ()).throw(OSError("Patient Name /private/1.2.3"))
    )
    summary = p._summarize_entry(path)
    assert summary.status == "unavailable"
    assert "operation=measurement.list code=io error_type=OSError" in caplog.text
    assert "Patient Name" not in caplog.text
    assert "/private" not in caplog.text
    assert "1.2.3" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
    assert p.close()
