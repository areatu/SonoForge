"""Opt-in controller reopen path and WP4.2 precedence with real source files."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.domain.models import LinearMeasurement
from echo_personal_tool.infrastructure.local_scanner import LocalMediaDirectoryScanner
from echo_personal_tool.infrastructure.user_preferences import UserPreferences
from tests.fixtures.generate_synthetic_dicom import write_synthetic_dicom

pytestmark = pytest.mark.gui


def test_controller_reopen_restores_metrics_and_calipers(tmp_path, monkeypatch, qapp):
    monkeypatch.setattr(
        "echo_personal_tool.application.app_controller.load_user_preferences",
        lambda: UserPreferences(measurement_persistence_enabled=True),
    )
    root = tmp_path / "sources"
    root.mkdir()
    write_synthetic_dicom(root / "clip.dcm", study_uid="1.2.3", series_uid="1.2.99")
    studies = LocalMediaDirectoryScanner().scan(root)
    instance = studies[0].series[0].instances[0]
    pool = SimpleNamespace(start=lambda *args: None)
    first = AppController(thread_pool=pool)
    first.load_pre_scanned_studies(studies)
    assert first.measurement_persistence.flush()
    first.load_instance(instance)
    first.on_patient_metrics_changed(181, 82)
    first.on_linear_measurements_changed([LinearMeasurement("LVEDD", 20.0, 10.0)])
    assert first.measurement_persistence.close()
    second = AppController(thread_pool=pool)
    second.load_pre_scanned_studies(studies)
    assert second.measurement_persistence.flush()
    second.load_instance(replace(instance, patient_height_m=1.50, patient_weight_kg=50.0))
    snapshot = second.compute_study_snapshot()
    assert snapshot.height_cm == 181
    assert snapshot.weight_kg == 82
    assert len(snapshot.linear_measurements) == 1
    assert snapshot.linear_measurements[0].sop_instance_uid == instance.sop_instance_uid
    assert snapshot.linear_measurements[0].frame_index == 0
    second.reset_measurements_and_calibration()
    assert second.compute_study_snapshot().height_cm == 181
    assert second.measurement_persistence.close()


def test_manual_clear_does_not_autofill_on_next_clip(tmp_path, qapp):
    controller = AppController(thread_pool=SimpleNamespace(start=lambda *args: None))
    root = tmp_path / "sources"
    root.mkdir()
    write_synthetic_dicom(root / "clip.dcm", study_uid="1.2.3", series_uid="1.2.99")
    studies = LocalMediaDirectoryScanner().scan(root)
    instance = studies[0].series[0].instances[0]
    controller.load_pre_scanned_studies(studies)
    controller.load_instance(replace(instance, patient_height_m=1.70, patient_weight_kg=None))
    assert controller.compute_study_snapshot().height_cm == 170
    controller.on_patient_metrics_changed(None, None)
    controller.load_instance(replace(instance, patient_height_m=1.80, patient_weight_kg=80.0))
    assert controller.compute_study_snapshot().height_cm is None
    assert controller.compute_study_snapshot().weight_kg is None
    controller.use_dicom_patient_metrics()
    assert controller.compute_study_snapshot().height_cm == 180
    assert controller.compute_study_snapshot().weight_kg == 80
    assert controller.measurement_persistence.close()


def test_report_contours_use_their_own_source_spacing(qapp):
    from datetime import datetime
    from pathlib import Path

    from echo_personal_tool.domain.models import Contour, InstanceMetadata, SeriesMetadata, StudyMetadata

    controller = AppController(thread_pool=SimpleNamespace(start=lambda *args: None))
    first = InstanceMetadata("1.2.3.1", "1.2.3.9", "US", 1, (0.5, 0.5), None, "", Path("a.dcm"))
    second = replace(first, sop_instance_uid="1.2.3.2", pixel_spacing=(1.0, 1.0), path=Path("b.dcm"))
    controller._studies = [
        StudyMetadata("1.2.3", datetime.now(), (SeriesMetadata("1.2.3.9", "1.2.3", "US", "", (first, second)),))
    ]
    controller.measurement_persistence.sources = {
        "1.2.3": {first.sop_instance_uid: {"spacing": [0.5, 0.5]}, second.sop_instance_uid: {"spacing": [1.0, 1.0]}}
    }
    contours = tuple(
        Contour(
            "GEN",
            chamber="AREA",
            points=[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)],
            measurement_label=label,
            sop_instance_uid=i.sop_instance_uid,
            frame_index=0,
        )
        for label, i in [("A", first), ("B", second)]
    )
    controller._measurement_session.merge_contours("1.2.3", contours)
    for current in (first, second):
        controller._current_instance = current
        controller.state_manager.set_instance(current, 1, None, emit=False)
        result = {p.label: p.value for p in controller.compute_study_snapshot().planimeter}
        assert result == pytest.approx({"A": 0.25, "B": 1.0})
    assert controller.measurement_persistence.close()


def test_runtime_enable_adopts_open_study_and_resolves_conflict(tmp_path, monkeypatch, qapp):
    """The Settings toggle applies without a restart: enabling while a study is
    open adopts its saved record; a record the session never loaded raises a
    RAM-vs-disk resolution instead of a silent overwrite."""
    monkeypatch.setattr(
        "echo_personal_tool.application.app_controller.load_user_preferences",
        lambda: UserPreferences(measurement_persistence_enabled=True),
    )
    root = tmp_path / "sources"
    root.mkdir()
    write_synthetic_dicom(root / "clip.dcm", study_uid="1.2.3", series_uid="1.2.99")
    studies = LocalMediaDirectoryScanner().scan(root)
    instance = studies[0].series[0].instances[0]
    pool = SimpleNamespace(start=lambda *args: None)
    first = AppController(thread_pool=pool)
    first.load_pre_scanned_studies(studies)
    assert first.measurement_persistence.flush()
    first.load_instance(instance)
    first.on_patient_metrics_changed(181, 82)
    assert first.measurement_persistence.flush()
    assert first.measurement_persistence.close()

    # New session with autosave off: open the same study, measure, enable at runtime.
    monkeypatch.setattr(
        "echo_personal_tool.application.app_controller.load_user_preferences",
        lambda: UserPreferences(measurement_persistence_enabled=False),
    )
    second = AppController(thread_pool=pool)
    conflicts: list = []
    second.persistence_conflict.connect(lambda uids: conflicts.append(list(uids)))
    second.load_pre_scanned_studies(studies)
    assert second.measurement_persistence.flush()
    second.load_instance(instance)
    second.on_patient_metrics_changed(190, 90)
    assert not second.measurement_persistence.enabled
    second.set_measurement_persistence_enabled(True)
    assert second.measurement_persistence.enabled
    assert second.measurement_persistence.flush()
    assert conflicts == [["1.2.3"]]
    assert second.compute_study_snapshot().height_cm == 190  # live session kept
    second.resolve_persistence_conflict(load_saved=False)  # «keep current»
    second.on_patient_metrics_changed(191, 91)
    assert second.measurement_persistence.flush()
    record = second.measurement_persistence.repository.load("1.2.3")
    assert record["data"].height_cm == 191
    assert second.measurement_persistence.close()


def test_runtime_enable_load_saved_restores_record(tmp_path, monkeypatch, qapp):
    monkeypatch.setattr(
        "echo_personal_tool.application.app_controller.load_user_preferences",
        lambda: UserPreferences(measurement_persistence_enabled=True),
    )
    root = tmp_path / "sources"
    root.mkdir()
    write_synthetic_dicom(root / "clip.dcm", study_uid="1.2.3", series_uid="1.2.99")
    studies = LocalMediaDirectoryScanner().scan(root)
    instance = studies[0].series[0].instances[0]
    pool = SimpleNamespace(start=lambda *args: None)
    first = AppController(thread_pool=pool)
    first.load_pre_scanned_studies(studies)
    assert first.measurement_persistence.flush()
    first.load_instance(instance)
    first.on_patient_metrics_changed(181, 82)
    assert first.measurement_persistence.flush()
    assert first.measurement_persistence.close()

    monkeypatch.setattr(
        "echo_personal_tool.application.app_controller.load_user_preferences",
        lambda: UserPreferences(measurement_persistence_enabled=False),
    )
    second = AppController(thread_pool=pool)
    second.load_pre_scanned_studies(studies)
    assert second.measurement_persistence.flush()
    second.set_measurement_persistence_enabled(True)
    assert second.measurement_persistence.flush()
    second.resolve_persistence_conflict(load_saved=True)  # «load saved»
    assert second.measurement_persistence.flush()
    # studies_loaded rebuilds the gallery in the UI; the test reloads the instance likewise
    second.load_instance(instance)
    assert second.compute_study_snapshot().height_cm == 181  # record replaced the RAM session
    assert second.measurement_persistence.close()


def test_runtime_disable_settles_pending_edits(tmp_path, monkeypatch, qapp):
    monkeypatch.setattr(
        "echo_personal_tool.application.app_controller.load_user_preferences",
        lambda: UserPreferences(measurement_persistence_enabled=True),
    )
    root = tmp_path / "sources"
    root.mkdir()
    write_synthetic_dicom(root / "clip.dcm", study_uid="1.2.3", series_uid="1.2.99")
    studies = LocalMediaDirectoryScanner().scan(root)
    instance = studies[0].series[0].instances[0]
    controller = AppController(thread_pool=SimpleNamespace(start=lambda *args: None))
    controller.load_pre_scanned_studies(studies)
    assert controller.measurement_persistence.flush()
    controller.load_instance(instance)
    controller.on_patient_metrics_changed(181, 82)
    assert controller.measurement_persistence.has_pending_edits
    assert controller.measurement_persistence.flush()  # «save and turn off»
    controller.set_measurement_persistence_enabled(False)
    assert not controller.measurement_persistence.enabled
    controller.on_patient_metrics_changed(200, 100)  # session-only from here on
    assert controller.measurement_persistence.flush()
    record = controller.measurement_persistence.repository.load("1.2.3")
    assert record["data"].height_cm == 181
    assert controller.measurement_persistence.close()
