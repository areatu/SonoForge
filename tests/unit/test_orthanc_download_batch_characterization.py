"""Characterization harness for the Orthanc download batch (S-03a, #530).

These tests pin the behaviour the dialog has today, before the batch state
moves into ``application/download_batch.py``.  They deliberately drive the
real dialog methods, but replace the worker/thread pool with deterministic
fakes: no PACS, no network, no QThreadPool, and disk writes only under
``tmp_path``.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QDialog

from echo_personal_tool.domain.models import StudyMetadata

pytestmark = pytest.mark.gui


def _metadata(study_uid: str) -> StudyMetadata:
    return StudyMetadata(study_uid=study_uid, study_datetime=datetime(2024, 1, 1), series=())


class _FakeSignal:
    def __init__(self) -> None:
        self._slots: list = []

    def connect(self, slot) -> None:
        self._slots.append(slot)

    def emit(self, *args) -> None:
        for slot in list(self._slots):
            slot(*args)


class _FakeWorker:
    """Only the seam the dialog touches: signals + cancel()."""

    def __init__(self) -> None:
        self.signals = SimpleNamespace(
            progress=_FakeSignal(),
            status=_FakeSignal(),
            done=_FakeSignal(),
            failed=_FakeSignal(),
            partial_failed=_FakeSignal(),
            cancelled=_FakeSignal(),
            series_done=_FakeSignal(),
            studies_ready=_FakeSignal(),
        )
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class _FakePool:
    def __init__(self) -> None:
        self.workers: list[_FakeWorker] = []

    def start(self, worker: _FakeWorker) -> None:
        self.workers.append(worker)


@pytest.fixture(autouse=True)
def _qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture()
def dialog(monkeypatch):
    from PySide6.QtCore import QTimer

    from echo_personal_tool.presentation.orthanc_study_dialog import OrthancStudyDialog

    client = MagicMock()
    client.ping.return_value = True
    cache = MagicMock()
    cache.create_session.return_value = "test-session"
    cache.session_path.return_value = MagicMock(exists=MagicMock(return_value=True))
    with (
        patch.object(OrthancStudyDialog, "_init_network"),
        patch.object(QTimer, "singleShot"),
    ):
        d = OrthancStudyDialog(client, cache)
    d._force_close_timer.stop()
    d._init_timer.stop()
    # Every worker started by the batch lands in this pool, including the
    # next study started from a done/failed callback.
    d._characterization_pool = _FakePool()
    monkeypatch.setattr(
        "echo_personal_tool.presentation.orthanc_study_dialog.QThreadPool.globalInstance",
        lambda: d._characterization_pool,
    )
    yield d
    d.blockSignals(True)
    for child in d.findChildren(QTimer):
        child.stop()
        child.blockSignals(True)


def _start(dialog, pool: _FakePool, studies: list[tuple[str, list[str]]]) -> None:
    """Call the real ``_on_load`` with the selection and workers faked."""

    dialog._make_download_worker = lambda _study_uid, _series_uids: _FakeWorker()  # type: ignore[method-assign]
    with (
        patch.object(dialog, "_ensure_selection_ready", return_value=True),
        patch.object(dialog, "_collect_all_checked_series", return_value=studies),
    ):
        dialog._on_load()


def test_successful_batch_reports_counters_studies_and_result(dialog):
    pool = dialog._characterization_pool
    _start(dialog, pool, [("study-1", ["s1"]), ("study-2", ["s2"])])
    assert dialog._downloading is True
    assert dialog._total_studies == 2
    # The first worker owns study-1; only study-2 is still queued.
    assert dialog._pending_downloads == [("study-2", ["s2"])]

    first = _metadata("study-1")
    second = _metadata("study-2")
    with patch.object(dialog, "accept") as accepted:
        pool.workers[0].signals.studies_ready.emit([first])
        pool.workers[0].signals.done.emit("test-session", "study-1")
        assert dialog._completed_downloads == 1
        assert dialog._downloading is True
        pool.workers[1].signals.studies_ready.emit([second])
        pool.workers[1].signals.done.emit("test-session", "study-2")

    assert dialog._downloading is False
    assert dialog._completed_downloads == 2
    assert dialog._failed_downloads == 0
    assert dialog._pending_downloads == []
    assert dialog.downloaded_studies() == [first, second]
    assert dialog.result_data() == ("test-session", "study-1")
    accepted.assert_called_once()


def test_partial_failure_keeps_successful_study_and_warns(dialog):
    pool = dialog._characterization_pool
    _start(dialog, pool, [("study-1", ["s1"]), ("study-2", ["s2"])])
    saved = _metadata("study-1")

    with (
        patch.object(dialog, "accept") as accepted,
        patch("echo_personal_tool.presentation.orthanc_study_dialog.QMessageBox") as box,
    ):
        pool.workers[0].signals.studies_ready.emit([saved])
        pool.workers[0].signals.done.emit("test-session", "study-1")
        # The callback immediately starts the next queued study.
        assert dialog._pending_downloads == []
        pool.workers[1].signals.failed.emit("study-2", "connection reset")

    assert dialog._downloading is False
    assert dialog._completed_downloads == 2
    assert dialog._failed_downloads == 1
    assert dialog.downloaded_studies() == [saved]
    assert dialog.result_data() == ("test-session", "study-1")
    assert dialog._partial_download_warnings == []
    box.warning.assert_called_once()
    accepted.assert_called_once()


def test_cancel_and_close_during_download_waits_for_worker(dialog):
    pool = dialog._characterization_pool
    _start(dialog, pool, [("study-1", ["s1"]), ("study-2", ["s2"])])
    worker = pool.workers[0]

    event = QCloseEvent()
    dialog.closeEvent(event)

    assert event.isAccepted() is False
    assert worker.cancelled is True
    assert dialog._close_pending is True
    assert dialog._downloading is True
    assert dialog._force_close_timer.isActive() is True

    with patch.object(dialog, "accept") as accepted:
        worker.signals.cancelled.emit("test-session")

    assert dialog._downloading is False
    assert dialog.result_data() is None
    assert dialog.downloaded_studies() == []
    accepted.assert_not_called()
    dialog._reject_timer.stop()


def test_continue_in_background_then_batch_restores_the_dialog(dialog):
    pool = dialog._characterization_pool
    _start(dialog, pool, [("study-1", ["s1"])])
    dialog.show()
    assert dialog.isVisible() is True

    dialog._continue_in_background()

    assert dialog._background_requested is True
    assert dialog.isVisible() is False
    assert dialog._downloading is True

    study = _metadata("study-1")
    with patch.object(dialog, "accept") as accepted:
        pool.workers[0].signals.studies_ready.emit([study])
        pool.workers[0].signals.done.emit("test-session", "study-1")

    assert dialog._downloading is False
    assert dialog._background_requested is True
    assert dialog.isVisible() is True
    assert dialog.downloaded_studies() == [study]
    accepted.assert_called_once()


def test_disk_export_survives_batch_and_forgets_cache_session(dialog, tmp_path):
    dialog._downloading = True
    dialog._session_id = "test-session"
    dialog._save_to_disk_path = str(tmp_path)
    dialog._cache.session_path.return_value = tmp_path
    plan = [(tmp_path / "src.dcm", tmp_path / "Instance" / "1" / "x.dcm")]
    options = MagicMock(name="options")

    with (
        patch.object(dialog, "_session_export_plan", return_value=plan),
        patch("echo_personal_tool.presentation.dicom_export_dialog.DicomExportDialog") as export_dialog,
        patch("echo_personal_tool.presentation.dicom_export_dialog.load_preview_frame", return_value=None),
        patch("echo_personal_tool.presentation.ui_animations.exec_animated") as exec_animated,
        patch.object(dialog, "_start_export_worker") as start_export,
        patch.object(dialog, "accept"),
        patch("echo_personal_tool.presentation.orthanc_study_dialog.QMessageBox"),
    ):
        exec_animated.return_value = QDialog.DialogCode.Accepted
        export_dialog.return_value.chosen_options.return_value = options
        export_dialog.return_value.evaluation_record.return_value = "files=1"
        dialog._on_disk_download_done()

    assert dialog._downloading is True  # still busy while files are written
    start_export.assert_called_once_with(plan, options)

    with (
        patch.object(dialog, "accept") as accepted,
        patch("echo_personal_tool.presentation.orthanc_study_dialog.QMessageBox"),
    ):
        dialog._on_export_finished(SimpleNamespace(exported=1, failed=0, unverified=0, lines=(), cancelled=False))

    assert dialog._downloading is False
    assert dialog._session_id is None
    assert dialog._worker is None
    assert dialog.completed_disk_download_path() == tmp_path
    assert dialog._find_btn.isEnabled()
    accepted.assert_called_once()


def test_new_batch_does_not_inherit_previous_counters_or_studies(dialog):
    pool = dialog._characterization_pool
    old = _metadata("study-old")
    with patch.object(dialog, "accept"):
        _start(dialog, pool, [("study-old", ["s"])])
        pool.workers[0].signals.studies_ready.emit([old])
        pool.workers[0].signals.done.emit("test-session", "study-old")
    assert dialog.downloaded_studies() == [old]
    assert dialog.result_data() == ("test-session", "study-old")

    _start(dialog, pool, [("study-new", ["s"])])

    assert dialog._completed_downloads == 0
    assert dialog._failed_downloads == 0
    assert dialog._total_studies == 1
    assert dialog._pending_downloads == []
    assert dialog._partial_download_warnings == []
    assert dialog.downloaded_studies() == []
    assert dialog.result_data() is None

    new = _metadata("study-new")
    with patch.object(dialog, "accept"):
        pool.workers[1].signals.studies_ready.emit([new])
        pool.workers[1].signals.done.emit("test-session", "study-new")

    assert dialog.downloaded_studies() == [new]
    assert dialog.result_data() == ("test-session", "study-new")
