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
        self.progress: list[tuple[int, int, str]] = []
        self.series_done: list[tuple[str, str]] = []
        self.done: list[tuple[str, str]] = []
        self.failed: list[tuple[str, str]] = []
        self.cancelled: list[str] = []

    def connect(self, worker: OrthancDownloadWorker) -> None:
        worker.signals.progress.connect(
            lambda current, total, series_uid: self.progress.append((current, total, series_uid))
        )
        worker.signals.series_done.connect(lambda series_uid, status: self.series_done.append((series_uid, status)))
        worker.signals.done.connect(lambda session_id, study_uid: self.done.append((session_id, study_uid)))
        worker.signals.failed.connect(lambda uid, message: self.failed.append((uid, message)))
        worker.signals.cancelled.connect(lambda session_id: self.cancelled.append(session_id))


class _FailingDownloadClient(FakeDicomWebClient):
    def download_instance(self, study_uid: str, series_uid: str, instance_uid: str) -> bytes:
        raise TimeoutError("WADO timeout")


class _QueryErrorClient(FakeDicomWebClient):
    def query_instances(self, study_uid: str, series_uid: str) -> list[InstanceInfo]:
        raise RuntimeError("QIDO failed")


class _SlowDownloadClient(FakeDicomWebClient):
    def __init__(self, worker: OrthancDownloadWorker, fixtures_dir: Path | None = None) -> None:
        super().__init__(fixtures_dir)
        self._worker = worker
        self._calls = 0

    def download_instance(self, study_uid: str, series_uid: str, instance_uid: str) -> bytes:
        self._calls += 1
        if self._calls == 1:
            self._worker.cancel()
        return super().download_instance(study_uid, series_uid, instance_uid)


def test_download_saves_instances_and_emits_done(tmp_path: Path) -> None:
    client = FakeDicomWebClient(FIXTURES)
    cache = OrthancSessionCache(tmp_path)
    session_id = cache.create_session()
    capture = _SignalCapture()

    worker = OrthancDownloadWorker(client, cache, session_id, STUDY_UID, [SERIES_UID])
    capture.connect(worker)
    worker.run()

    expected_path = tmp_path / f"session-{session_id}" / STUDY_UID / SERIES_UID / f"{INSTANCE_UID}.dcm"
    assert expected_path.exists()
    assert expected_path.read_bytes()[128:132] == b"DICM"
    assert capture.progress
    assert capture.progress[-1][0] == capture.progress[-1][1]  # current == total
    assert len(capture.done) == 1
    assert capture.done[0][1] == STUDY_UID
    assert capture.failed == []
    assert capture.cancelled == []


def test_series_failed_when_download_fails(tmp_path: Path) -> None:
    client = _FailingDownloadClient(FIXTURES)
    cache = OrthancSessionCache(tmp_path)
    session_id = cache.create_session()
    capture = _SignalCapture()

    worker = OrthancDownloadWorker(client, cache, session_id, STUDY_UID, [SERIES_UID])
    capture.connect(worker)
    worker.run()

    assert capture.progress
    assert len(capture.failed) == 1
    assert capture.failed[0][0] == STUDY_UID
    assert "0/1" in capture.failed[0][1]
    assert list((tmp_path / f"session-{session_id}").rglob("*.dcm")) == []


def test_catastrophic_error_emits_failed(tmp_path: Path) -> None:
    client = _QueryErrorClient(FIXTURES)
    cache = OrthancSessionCache(tmp_path)
    session_id = cache.create_session()
    capture = _SignalCapture()

    worker = OrthancDownloadWorker(client, cache, session_id, STUDY_UID, [SERIES_UID])
    capture.connect(worker)
    worker.run()

    assert capture.failed == [(STUDY_UID, "QIDO failed")]
    assert capture.done == []


def test_cancel_clears_session_and_emits_cancelled(tmp_path: Path) -> None:
    cache = OrthancSessionCache(tmp_path)
    session_id = cache.create_session()
    capture = _SignalCapture()

    worker = OrthancDownloadWorker(
        FakeDicomWebClient(FIXTURES),
        cache,
        session_id,
        STUDY_UID,
        [SERIES_UID],
    )
    client = _SlowDownloadClient(worker, FIXTURES)
    worker._client = client
    capture.connect(worker)
    worker.run()

    assert capture.cancelled == [session_id]
    assert capture.done == []
    assert not (tmp_path / f"session-{session_id}").exists()
