"""Real offscreen workbench widgets and ownership of local I/O callbacks."""

import threading
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QMenu, QWidget

from echo_personal_tool.application.ml_workbench import LocalMLWorkbench
from echo_personal_tool.application.workers.ml_workbench_worker import MLWorkbenchWorker
from echo_personal_tool.domain.models.training_archive import ArchiveWriteError
from echo_personal_tool.presentation.ml_workbench_dialog import (
    MLWorkbenchDialog,
    _preview_pixmap,
    populate_local_tools_menu,
)
from tests.unit.test_ml_workbench import collect

pytestmark = pytest.mark.gui


@pytest.fixture
def dialog(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "config"))
    monkeypatch.delenv("SONOFORGE_LOCAL_TRAINING_ARCHIVE", raising=False)
    monkeypatch.delenv("SONOFORGE_LOCAL_TRAINING_ARCHIVE_DIR", raising=False)
    result = MLWorkbenchDialog()
    qtbot.addWidget(result)
    result._directory.setText(str(tmp_path / "workspace"))
    return result


def wait_for_job(qtbot, dialog):
    qtbot.waitUntil(lambda: dialog._job is None, timeout=10000)


def test_refresh_preview_filter_curation_and_report(qtbot, dialog):
    bench = LocalMLWorkbench(Path(dialog._directory.text()))
    collect(bench, chamber="RV")
    dialog._refresh()
    wait_for_job(qtbot, dialog)
    assert dialog._table.rowCount() == 1
    assert "BLOCKED" in dialog._report.toPlainText()
    dialog._chamber_filter.setCurrentIndex(dialog._chamber_filter.findData("LA"))
    assert dialog._table.isRowHidden(0)
    dialog._chamber_filter.setCurrentIndex(dialog._chamber_filter.findData("RV"))
    assert not dialog._table.isRowHidden(0)
    dialog._table.selectRow(0)
    wait_for_job(qtbot, dialog)
    assert dialog._image.pixmap() is not None
    assert not dialog._image.pixmap().isNull()
    dialog._decide(False, True)
    wait_for_job(qtbot, dialog)
    assert bench.inventory()["report"]["reviewed_current_records"] == 1
    dialog._decide(True, False)
    wait_for_job(qtbot, dialog)
    assert bench.inventory()["report"]["selected_records"] == 0
    assert len(bench.archive.records()) == 1


def test_settings_are_explicit_and_survive_restart(dialog, monkeypatch):
    from echo_personal_tool.application.training_archive_runtime import local_archive_capture

    assert not dialog._enabled.isChecked()
    dialog._enabled.setChecked(True)
    dialog._quota.setValue(32)
    dialog._save_settings()
    capture = local_archive_capture(permitted=True)
    assert capture is not None
    assert capture.archive.quota_bytes == 32 * 1024**2
    assert not dialog._pause.isEnabled()  # no fake live rebind when collection was off at startup
    enabled_dialog = MLWorkbenchDialog(capture=capture)
    enabled_dialog._pause.setChecked(True)
    assert capture.paused
    enabled_dialog.close()


def test_stale_close_does_not_publish_and_worker_failure_is_static(qtbot, dialog):
    started, release = threading.Event(), threading.Event()

    def action():
        started.set()
        release.wait(5)
        return {"records": [{"should_not": "publish"}]}

    dialog._run(action)
    qtbot.waitUntil(started.is_set)
    generation = dialog._generation
    dialog.close()
    release.set()
    assert QThreadPool.globalInstance().waitForDone(10000)
    qtbot.wait(20)
    assert dialog._generation > generation
    assert dialog._records == []


def test_workspace_change_invalidates_previous_result(qtbot, dialog, tmp_path):
    bench = LocalMLWorkbench(Path(dialog._directory.text()))
    collect(bench)
    dialog._refresh()
    wait_for_job(qtbot, dialog)
    old_generation = dialog._generation
    dialog._directory.setText(str(tmp_path / "another"))
    dialog._completed(old_generation, bench.inventory())
    assert dialog._records == []
    assert dialog._bench is None
    assert dialog._report.toPlainText() == ""


@pytest.mark.parametrize(
    "error_type",
    [
        ArchiveWriteError,
        OSError,
        ValueError,
        KeyError,
        IndexError,
        TypeError,
        RuntimeError,
        EOFError,
        OverflowError,
        MemoryError,
    ],
)
def test_failed_job_does_not_echo_patient_path(qtbot, dialog, error_type):
    def fail():
        raise error_type("/secret-patient-name/clinical-data")

    dialog._run(fail)
    wait_for_job(qtbot, dialog)
    assert "secret-patient" not in dialog._status.text()
    assert dialog._tabs.isEnabled()


def test_dev_only_full_menu_and_image_formats(qtbot):
    parent = QWidget()
    qtbot.addWidget(parent)
    full, presenter = QMenu(parent), QMenu(parent)
    populate_local_tools_menu(parent, full, lambda: None, "full", object())
    populate_local_tools_menu(parent, presenter, lambda: None, "presenter", object())
    assert any(a.objectName() == "localMLWorkbench" for a in full.actions())
    assert not any(a.objectName() == "localMLWorkbench" for a in presenter.actions())
    for shape in ((16, 16), (16, 16, 1), (16, 16, 3), (16, 16, 4)):
        assert not _preview_pixmap(np.ones(shape, dtype=np.uint16), [[1, 1], [5, 5], [8, 1]]).isNull()


def test_worker_does_not_swallow_programming_errors(qapp):
    def fail():
        raise AssertionError("broken worker invariant")

    worker = MLWorkbenchWorker(7, fail)
    failures = []
    worker.signals.failed.connect(failures.append)
    with pytest.raises(AssertionError, match="broken worker invariant"):
        worker.run()
    assert failures == []


def test_frozen_build_has_no_ml_workbench_menu(qtbot, monkeypatch):
    import sys

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    parent = QWidget()
    qtbot.addWidget(parent)
    menu = QMenu(parent)
    populate_local_tools_menu(parent, menu, lambda: None, "full", object())
    assert not any(action.objectName() == "localMLWorkbench" for action in menu.actions())
