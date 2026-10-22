from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
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


@pytest.mark.parametrize("remapped", [0, 1])
def test_import_preview_must_approve_full_replace_before_import(
    tmp_path, monkeypatch, qapp, isolated_qsettings, remapped
):
    p, dialog = _make_dialog(tmp_path, monkeypatch)
    preview = SimpleNamespace(
        compatible=True,
        categories=("metrics", "calculator_inputs"),
        source_count=1,
        unavailable_sources=0,
        additional_live_sources=0,
        digest="checked",
        remapped_sources=remapped,
    )
    imported = []
    monkeypatch.setattr(
        "echo_personal_tool.presentation.measurement_storage_dialog.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(tmp_path / "export.json"), "SonoForge (*.json)"),
    )
    monkeypatch.setattr(p, "preview_import", lambda uid, path, callback: callback(preview))
    monkeypatch.setattr(
        p,
        "import_study",
        lambda uid, path, callback, *, preview: (imported.append((uid, path, preview)), callback("conflict")),
    )
    questions = []

    def confirm(*args):
        questions.append(args)
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", confirm)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: None)
    try:
        dialog.import_current()
        assert questions[0][-1] == QMessageBox.StandardButton.No
        assert ("SHA-256" in questions[0][2]) == bool(remapped)
        assert imported and imported[0][2] is preview
    finally:
        dialog.close()
        assert p.close()


def test_import_preview_incompatible_does_not_offer_replace(tmp_path, monkeypatch, qapp, isolated_qsettings):
    p, dialog = _make_dialog(tmp_path, monkeypatch)
    preview = SimpleNamespace(
        compatible=False,
        categories=(),
        source_count=1,
        unavailable_sources=1,
        additional_live_sources=0,
        digest="",
    )
    imported = []
    monkeypatch.setattr(
        "echo_personal_tool.presentation.measurement_storage_dialog.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(tmp_path / "export.json"), "SonoForge (*.json)"),
    )
    monkeypatch.setattr(p, "preview_import", lambda uid, path, callback: callback(preview))
    monkeypatch.setattr(p, "import_study", lambda *args, **kwargs: imported.append(args))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: None)
    try:
        dialog.import_current()
        assert not imported
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


def test_delete_all_reports_stored_preference_change(tmp_path, monkeypatch, qapp, isolated_qsettings):
    p, dialog = _make_dialog(tmp_path, monkeypatch)
    assert not dialog.preferences_changed
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Yes)
    dialog.delete_all()
    assert p.flush()
    assert dialog.preferences_changed
    dialog.close()
    assert p.close()


def test_plain_close_reports_no_preference_change(tmp_path, monkeypatch, qapp):
    p, dialog = _make_dialog(tmp_path, monkeypatch)
    dialog.close()
    assert not dialog.preferences_changed
    assert p.close()


def test_manager_lists_unreadable_records_next_to_valid_ones(tmp_path, monkeypatch, qapp, isolated_qsettings):
    """QH-1a: a damaged record is visible with its status, not silently dropped."""
    from echo_personal_tool.infrastructure.i18n import tr, tr_plural
    from echo_personal_tool.infrastructure.measurement_codec import study_key

    p, dialog = _make_dialog(tmp_path, monkeypatch)
    assert p.flush()
    assert dialog.records.count() == 1

    damaged = tmp_path / (study_key("1.2.9") + ".json")
    damaged.write_bytes(b'{"format": "sonoforge.study-measurements", "nope": 1}')
    dialog.refresh()
    assert p.flush()  # drains the worker callback

    assert dialog.records.count() == 2
    keys = {dialog.records.item(row).data(Qt.ItemDataRole.UserRole) for row in range(dialog.records.count())}
    assert keys == {study_key("1.2.3"), study_key("1.2.9")}
    texts = [dialog.records.item(row).text() for row in range(dialog.records.count())]
    assert any(tr("persistence.record_status.corrupt") in text for text in texts)
    assert any(tr_plural("persistence.record_measurements", 0) in text for text in texts)
    assert tr_plural("persistence.stats_unreadable", 1) in dialog.summary.text()

    # The damaged row stays selectable: deleting it is still a user action.
    row = next(
        row
        for row in range(dialog.records.count())
        if dialog.records.item(row).data(Qt.ItemDataRole.UserRole) == study_key("1.2.9")
    )
    dialog.records.setCurrentRow(row)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Yes)
    dialog.delete_selected()
    assert p.flush()
    assert not damaged.exists()
    assert dialog.records.count() == 1
    dialog.close()
    assert p.close()


def test_manager_failed_listing_is_not_an_empty_store(tmp_path, monkeypatch, qapp, isolated_qsettings):
    """«Не удалось прочитать» must never render as «записей нет» (S-07)."""
    from echo_personal_tool.infrastructure.i18n import tr

    p, dialog = _make_dialog(tmp_path, monkeypatch)
    assert p.flush()
    monkeypatch.setattr(p.repository, "entries", lambda: (_ for _ in ()).throw(PermissionError(13, "denied")))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)
    dialog.refresh()
    assert p.flush()
    assert dialog.records.count() == 0
    assert dialog.summary.text() == tr("persistence.records_failed")
    dialog.close()
    assert p.close()
