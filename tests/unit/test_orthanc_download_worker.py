"""Unit tests for OrthancDownloadWorker."""

from __future__ import annotations

from pathlib import Path

from echo_personal_tool.application.workers.orthanc_download_worker import (
    OrthancDownloadWorker,
)
from echo_personal_tool.domain.models.orthanc import InstanceInfo
from echo_personal_tool.infrastructure.fake_dicom_web_client import FakeDicomWebClient
from echo_personal_tool.infrastructure.orthanc_cache import OrthancSessionCache

FIXTURES = Path("tests/fixtures/orthanc")
STUDY_UID = "1.2.410.200001.1.1185.2062614048.1.20240404.1120546412.448.1"
SERIES_UID = "1.2.410.200001.1.1185.2062614048.1.20240404.1120546412.448.2"
INSTANCE_UID = "1.2.410.200001.1.1185.2062614048.1.20240404.1120546412.448.3"


class _SignalCapture:
    def __init__(self) -> None:
        self.progress: list[tuple[str, int, int]] = []
        self.series_done: list[tuple[str, str]] = []
        self.done: list[tuple[str, str]] = []
        self.failed: list[tuple[str, str]] = []

    def connect(self, worker: OrthancDownloadWorker) -> None:
        worker.signals.progress.connect(
            lambda series_uid, current, total: self.progress.append(
                (series_uid, current, total)
            )
        )
        worker.signals.series_done.connect(
            lambda series_uid, status: self.series_done.append((series_uid, status))
        )
        worker.signals.done.connect(
            lambda session_id, study_uid: self.done.append((session_id, study_uid))
        )
        worker.signals.failed.connect(
            lambda uid, message: self.failed.append((uid, message))
        )


class _FailingDownloadClient(FakeDicomWebClient):
    def download_instance(
        self, study_uid: str, series_uid: str, instance_uid: str
    ) -> bytes:
        raise TimeoutError("WADO timeout")


class _RetryThenSuccessClient(FakeDicomWebClient):
    def __init__(self, fixtures_dir: Path | None = None) -> None:
        super().__init__(fixtures_dir)
        self._attempts = 0

    def download_instance(
        self, study_uid: str, series_uid: str, instance_uid: str
    ) -> bytes:
        self._attempts += 1
        if self._attempts == 1:
            raise TimeoutError("WADO timeout")
        return super().download_instance(study_uid, series_uid, instance_uid)


class _QueryErrorClient(FakeDicomWebClient):
    def query_instances(
        self, study_uid: str, series_uid: str
    ) -> list[InstanceInfo]:
        raise RuntimeError("QIDO failed")


def test_download_saves_instances_and_emits_done(tmp_path: Path) -> None:
    client = FakeDicomWebClient(FIXTURES)
    cache = OrthancSessionCache(tmp_path)
    session_id = cache.create_session()
    capture = _SignalCapture()

    worker = OrthancDownloadWorker(
        client, cache, session_id, STUDY_UID, [SERIES_UID]
    )
    capture.connect(worker)
    worker.run()

    expected_path = (
        tmp_path / f"session-{session_id}" / STUDY_UID / SERIES_UID / f"{INSTANCE_UID}.dcm"
    )
    assert expected_path.exists()
    assert expected_path.read_bytes()[128:132] == b"DICM"
    assert capture.series_done == [(SERIES_UID, "ok")]
    assert capture.progress == [(SERIES_UID, 1, 1)]
    assert capture.done == [(session_id, STUDY_UID)]
    assert capture.failed == []


def test_download_retries_once_then_succeeds(tmp_path: Path) -> None:
    client = _RetryThenSuccessClient(FIXTURES)
    cache = OrthancSessionCache(tmp_path)
    session_id = cache.create_session()
    capture = _SignalCapture()

    worker = OrthancDownloadWorker(
        client, cache, session_id, STUDY_UID, [SERIES_UID]
    )
    capture.connect(worker)
    worker.run()

    assert client._attempts == 2
    assert capture.series_done == [(SERIES_UID, "ok")]
    assert capture.done == [(session_id, STUDY_UID)]


def test_series_failed_when_download_fails_after_retry(tmp_path: Path) -> None:
    client = _FailingDownloadClient(FIXTURES)
    cache = OrthancSessionCache(tmp_path)
    session_id = cache.create_session()
    capture = _SignalCapture()

    worker = OrthancDownloadWorker(
        client, cache, session_id, STUDY_UID, [SERIES_UID]
    )
    capture.connect(worker)
    worker.run()

    assert capture.series_done == [(SERIES_UID, "failed")]
    assert capture.progress == [(SERIES_UID, 1, 1)]
    assert capture.done == []
    assert capture.failed == []
    assert list((tmp_path / f"session-{session_id}").rglob("*.dcm")) == []


def test_catastrophic_error_emits_failed(tmp_path: Path) -> None:
    client = _QueryErrorClient(FIXTURES)
    cache = OrthancSessionCache(tmp_path)
    session_id = cache.create_session()
    capture = _SignalCapture()

    worker = OrthancDownloadWorker(
        client, cache, session_id, STUDY_UID, [SERIES_UID]
    )
    capture.connect(worker)
    worker.run()

    assert capture.failed == [(STUDY_UID, "QIDO failed")]
    assert capture.done == []
    assert capture.series_done == []
