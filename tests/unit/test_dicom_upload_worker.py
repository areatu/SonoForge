"""Tests for DicomUploadWorker."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QCoreApplication

from echo_personal_tool.application.workers.dicom_upload_worker import DicomUploadWorker
from echo_personal_tool.domain.models.orthanc import StowResult


@pytest.fixture
def qapp():
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
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
    assert failed == ["Upload cancelled"]
    assert stow.received == []
