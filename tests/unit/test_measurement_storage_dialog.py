from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QMessageBox

from echo_personal_tool.application.measurement_persistence import MeasurementPersistence
from echo_personal_tool.application.study_measurement_session import StudyMeasurementSessionStore
from echo_personal_tool.presentation.measurement_storage_dialog import MeasurementStorageDialog

pytestmark = pytest.mark.gui


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
