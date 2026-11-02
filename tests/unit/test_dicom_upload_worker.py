"""Tests for DicomUploadWorker."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.gui
from PySide6.QtWidgets import QApplication

from echo_personal_tool.application.workers.dicom_upload_worker import (
    DICOM_UPLOAD_FAILURE_MESSAGE,
    UPLOAD_CANCELLED_CODE,
    DicomUploadWorker,
)
from echo_personal_tool.domain.models.orthanc import StowResult


@pytest.fixture
def qapp():
    # QApplication (not QCoreApplication): the shared unit-test fixtures need
    # an app with a stylesheet, and this file must also run in isolation.
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class _StubUploader:
    def __init__(self, outcomes: list[bool]) -> None:
        self._outcomes = outcomes
        self.calls = 0

    def upload_instance(self, dicom_bytes: bytes) -> bool:
        del dicom_bytes
        idx = min(self.calls, len(self._outcomes) - 1)
        self.calls += 1
        return self._outcomes[idx]


class _StubStowClient:
    def __init__(self, result: StowResult) -> None:
        self._result = result
        self.received: list[list[bytes]] = []

    def stow_instances(self, dicom_files: list[bytes]) -> StowResult:
        self.received.append(list(dicom_files))
        return self._result


def test_worker_requires_single_target() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        DicomUploadWorker([b"a"], uploader=MagicMock(), stow_client=MagicMock())


def test_worker_cstore_sequential(qapp) -> None:
    uploader = _StubUploader([True, False, True])
    worker = DicomUploadWorker([b"1", b"2", b"3"], uploader=uploader)
    finished: list[StowResult] = []
    worker.signals.finished.connect(finished.append)
    worker.run()
    assert uploader.calls == 3
    assert finished[0].success_count == 2


def test_worker_stow_batch(qapp) -> None:
    stow = _StubStowClient(StowResult(success_count=2))
    worker = DicomUploadWorker([b"1", b"2"], stow_client=stow)
    finished: list[StowResult] = []
    progress: list[tuple[int, int]] = []
    worker.signals.finished.connect(finished.append)
    worker.signals.progress.connect(lambda c, t: progress.append((c, t)))
    worker.run()
    assert stow.received == [[b"1", b"2"]]
    assert finished[0].success_count == 2
    assert progress == [(2, 2)]


def test_worker_cancel_before_stow(qapp) -> None:
    stow = _StubStowClient(StowResult(success_count=1))
    worker = DicomUploadWorker([b"1"], stow_client=stow)
    failed: list[str] = []
    worker.signals.failed.connect(failed.append)
    worker.cancel()
    worker.run()
    assert failed == [UPLOAD_CANCELLED_CODE]
    assert stow.received == []


# ── QH-4a ER-09: cancellation and safe producer logs ───────────────────


def test_worker_cancel_mid_cstore_emits_stable_code(qapp) -> None:
    holder: dict[str, DicomUploadWorker] = {}

    class _CancellingUploader:
        def __init__(self) -> None:
            self.calls = 0

        def upload_instance(self, dicom_bytes: bytes) -> bool:
            del dicom_bytes
            self.calls += 1
            holder["worker"].cancel()
            return True

    uploader = _CancellingUploader()
    worker = DicomUploadWorker([b"1", b"2", b"3"], uploader=uploader)
    holder["worker"] = worker
    failed: list[str] = []
    worker.signals.failed.connect(failed.append)
    worker.run()

    assert failed == [UPLOAD_CANCELLED_CODE]
    assert uploader.calls == 1
    assert failed[0].strip() == failed[0]
    assert "PHI" not in failed[0]


def test_worker_failure_log_has_no_exception_text(qapp, caplog) -> None:
    class _RaisingUploader:
        def upload_instance(self, dicom_bytes: bytes) -> bool:
            del dicom_bytes
            raise RuntimeError("PHI_QH4A_PRIVATE /private/patient.dcm")

    worker = DicomUploadWorker([b"1"], uploader=_RaisingUploader())
    failed: list[str] = []
    worker.signals.failed.connect(failed.append)
    worker.run()

    assert failed == [DICOM_UPLOAD_FAILURE_MESSAGE]
    assert "operation=dicom.upload code=unexpected error_type=RuntimeError" in caplog.text
    assert "PHI_QH4A_PRIVATE" not in caplog.text
    assert "/private/patient.dcm" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
