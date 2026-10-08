from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QMessageBox

from echo_personal_tool.application.measurement_persistence import MeasurementPersistence
from echo_personal_tool.application.study_measurement_session import StudyMeasurementSessionStore
from echo_personal_tool.presentation.measurement_storage_dialog import MeasurementStorageDialog

pytestmark = pytest.mark.gui


def _make_dialog(tmp_path, monkeypatch):
    monkeypatch.setattr("echo_personal_tool.application.measurement_persistence.describe_study", lambda _: {})
    store = StudyMeasurementSessionStore()
    p = MeasurementPersistence(tmp_path, store, enabled=True)
    p.load([SimpleNamespace(study_uid="1.2.3")], lambda: None)
    assert p.flush()
    store.set_patient_metrics("1.2.3", 170.0, 70.0)
    assert p.flush()
    controller = SimpleNamespace(measurement_persistence=p, resolve_study_uid=lambda: "1.2.3")
    return p, MeasurementStorageDialog(controller)


def test_manager_delete_keeps_ram_but_disables_disk_writes(tmp_path, monkeypatch, qapp, isolated_qsettings):
    monkeypatch.setattr("echo_personal_tool.application.measurement_persistence.describe_study", lambda _: {})
    store = StudyMeasurementSessionStore()
    p = MeasurementPersistence(tmp_path, store, enabled=True)
    p.load([SimpleNamespace(study_uid="1.2.3")], lambda: None)
    assert p.flush()
    store.set_patient_metrics("1.2.3", 170.0, 70.0)
    assert p.flush()
    controller = SimpleNamespace(measurement_persistence=p, resolve_study_uid=lambda: "1.2.3")
    dialog = MeasurementStorageDialog(controller)
    assert p.flush()
    assert dialog.records.count() == 1
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Yes)
    dialog.delete_all()
    assert p.flush()
    assert dialog.records.count() == 0
    assert not p.enabled
    assert store.get("1.2.3").height_cm == 170.0
    from echo_personal_tool.infrastructure.user_preferences import load_user_preferences

    assert not load_user_preferences().measurement_persistence_enabled
    dialog.close()
    assert p.close()


def test_summary_uses_plural_forms(tmp_path, monkeypatch, qapp, isolated_qsettings):
    p, dialog = _make_dialog(tmp_path, monkeypatch)
    assert p.flush()
    assert dialog.records.count() == 1
    assert dialog.summary.text().startswith("1 запись ·")

    # Второй этюд становится записью только когда его замеры сохранены:
    # load() сам по себе лишь читает существующие файлы.
    p.load(
        [SimpleNamespace(study_uid="1.2.3"), SimpleNamespace(study_uid="1.2.4")],
        lambda: None,
    )
    assert p.flush()
    p.store.set_patient_metrics("1.2.4", 165.0, 60.0)
    assert p.flush()
    dialog.refresh()
    assert p.flush()
    assert dialog.records.count() == 2
    assert dialog.summary.text().startswith("2 записи ·")
    dialog.close()
    assert p.close()


def test_retry_disables_dialog_until_refresh_completes(tmp_path, monkeypatch, qapp, isolated_qsettings):
    p, dialog = _make_dialog(tmp_path, monkeypatch)
    try:
        dialog.retry()
        assert not dialog.isEnabled()
        assert p.flush()
        assert dialog.isEnabled()
    finally:
        dialog.close()
        assert p.close()


def test_export_disables_dialog_until_callback(tmp_path, monkeypatch, qapp, isolated_qsettings):
    p, dialog = _make_dialog(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "echo_personal_tool.presentation.measurement_storage_dialog.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: (str(tmp_path / "export.json"), "SonoForge (*.json)"),
    )
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
    try:
        dialog.export_current()
        assert not dialog.isEnabled()
        assert p.flush()
        assert dialog.isEnabled()
    finally:
        dialog.close()
        assert p.close()


def test_callback_after_close_never_touches_widgets(tmp_path, monkeypatch, qapp, isolated_qsettings):
    from shiboken6 import delete

    p, dialog = _make_dialog(tmp_path, monkeypatch)
    captured = []
    monkeypatch.setattr(p, "submit", lambda operation, callback: captured.append(callback))
    try:
        dialog.refresh()
        assert captured
        dialog.close()
        delete(dialog)
        # Without the _alive guard this raises RuntimeError on the dead C++ object.
        captured[0]([("record", 2048)], None)
        captured[0](None, "io")
    finally:
        assert p.close()


def test_delete_all_writes_prefs_only_on_success(tmp_path, monkeypatch, qapp, isolated_qsettings):
    from echo_personal_tool.infrastructure.user_preferences import load_user_preferences, save_user_preferences

    p, dialog = _make_dialog(tmp_path, monkeypatch)
    prefs = load_user_preferences()
    prefs.measurement_persistence_enabled = True
    save_user_preferences(prefs)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)

    def boom():
        raise OSError("disk gone")

    monkeypatch.setattr(p.repository, "delete_all", boom)
    try:
        dialog.delete_all()
        assert p.flush()
        assert load_user_preferences().measurement_persistence_enabled
    finally:
        dialog.close()
        assert p.close()
