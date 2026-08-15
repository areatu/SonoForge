"""Unit tests for OrthancDownloadWorker."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

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


class TestDownloadClientReuse:
    def test_reuses_thread_local_client_per_thread(self, tmp_path: Path) -> None:
        """_attempt_download should reuse thread-local client instead of
        creating a new one per download — this prevents connection churn
        that causes 'Server disconnected without sending a response' errors."""
        client = FakeDicomWebClient(FIXTURES)
        cache = OrthancSessionCache(tmp_path)
        session_id = cache.create_session()
        worker = OrthancDownloadWorker(
            client,
            cache,
            session_id,
            STUDY_UID,
            [SERIES_UID],
            base_url="http://localhost:8042",
        )

        mock_thread_client = MagicMock()
        mock_thread_client.download_instance.return_value = b"test_data"

        with patch.object(worker, "_make_thread_client", return_value=mock_thread_client) as mock_make:
            result1 = worker._attempt_download(STUDY_UID, SERIES_UID, INSTANCE_UID)
            result2 = worker._attempt_download(STUDY_UID, SERIES_UID, INSTANCE_UID)
            assert result1 == b"test_data"
            assert result2 == b"test_data"
            # Should create only one client per thread (not per download)
            assert mock_make.call_count == 1

    def test_no_settings_uses_shared_client(self, tmp_path: Path) -> None:
        """When no server_settings/base_url, uses self._client directly."""
        client = FakeDicomWebClient(FIXTURES)
        cache = OrthancSessionCache(tmp_path)
        session_id = cache.create_session()
        worker = OrthancDownloadWorker(client, cache, session_id, STUDY_UID, [SERIES_UID])

        with patch.object(worker, "_make_thread_client") as mock_make:
            result = worker._attempt_download(STUDY_UID, SERIES_UID, INSTANCE_UID)
            assert result is not None
            mock_make.assert_not_called()

    def test_thread_client_not_used_for_downloads(self, tmp_path: Path) -> None:
        """_thread_client (used for query_instances in run()) must NOT be reused
        for downloads to avoid thread-safety issues. Downloads use thread-local clients."""
        client = FakeDicomWebClient(FIXTURES)
        cache = OrthancSessionCache(tmp_path)
        session_id = cache.create_session()
        worker = OrthancDownloadWorker(
            client,
            cache,
            session_id,
            STUDY_UID,
            [SERIES_UID],
            base_url="http://localhost:8042",
        )

        worker._thread_client = MagicMock()
        worker._thread_client.download_instance.return_value = b"should_not_be_used"

        mock_dl_client = MagicMock()
        mock_dl_client.download_instance.return_value = b"thread_local_data"

        with patch.object(worker, "_make_thread_client", return_value=mock_dl_client):
            result = worker._attempt_download(STUDY_UID, SERIES_UID, INSTANCE_UID)
            assert result == b"thread_local_data"
            # _thread_client.download_instance should NOT have been called
            worker._thread_client.download_instance.assert_not_called()


class TestRetryBackoff:
    def test_exponential_backoff_delays(self, tmp_path: Path) -> None:
        """Retry should use exponential backoff: 1s, 2s, 4s (not fixed 1s)."""
        client = FakeDicomWebClient(FIXTURES)
        cache = OrthancSessionCache(tmp_path)
        session_id = cache.create_session()
        worker = OrthancDownloadWorker(client, cache, session_id, STUDY_UID, [SERIES_UID])

        # Patch _attempt_download to always fail and track sleep calls
        call_count = 0

        original_attempt = worker._attempt_download

        def failing_attempt(study_uid, series_uid, instance_uid):
            return None

        worker._attempt_download = failing_attempt

        sleeps: list[int] = []
        original_sleep = worker._interruptible_sleep

        def tracking_sleep(seconds: int) -> None:
            sleeps.append(seconds)
            # Don't actually sleep

        worker._interruptible_sleep = tracking_sleep

        worker._download_one(STUDY_UID, SERIES_UID, INSTANCE_UID)

        # 3 attempts, 2 retries with exponential backoff: 2^0=1, 2^1=2
        assert sleeps == [1, 2], f"Expected [1, 2], got {sleeps}"

    def test_interruptible_sleep_responds_to_cancel(self, tmp_path: Path) -> None:
        """_interruptible_sleep should exit immediately when _cancelled is set."""
        import time

        client = FakeDicomWebClient(FIXTURES)
        cache = OrthancSessionCache(tmp_path)
        session_id = cache.create_session()
        worker = OrthancDownloadWorker(client, cache, session_id, STUDY_UID, [SERIES_UID])

        worker._cancelled.set()
        start = time.monotonic()
        worker._interruptible_sleep(10)  # Would sleep 10s if not interrupted
        elapsed = time.monotonic() - start
        assert elapsed < 1.0, f"Sleep took {elapsed:.2f}s, should be near-instant"

    def test_timeout_reduced_to_60s(self, tmp_path: Path) -> None:
        """Download timeout should be 60s (not 300s) when no server_settings."""
        cache = OrthancSessionCache(tmp_path)
        session_id = cache.create_session()
        worker = OrthancDownloadWorker(
            FakeDicomWebClient(FIXTURES),
            cache,
            session_id,
            STUDY_UID,
            [SERIES_UID],
            base_url="http://localhost:8042",
        )
        with patch(
            "echo_personal_tool.application.workers.orthanc_download_worker.OrthancDicomWebClient"
        ) as mock_client_cls:
            mock_client_cls.return_value = MagicMock()
            worker._make_thread_client()
            args, kwargs = mock_client_cls.call_args
            assert kwargs["timeout"] == 60.0, f"Expected timeout=60.0, got {kwargs.get('timeout')}"

    def test_server_settings_timeout_uses_60s_floor(self, tmp_path: Path) -> None:
        """When server_settings present, download timeout is max(net*10, 60)."""
        from echo_personal_tool.infrastructure.server_settings import ServerSettings

        settings = ServerSettings(
            description="test",
            url="http://localhost:8042",
            network_timeout=30.0,  # 30 * 10 = 300, floor is 60
        )
        cache = OrthancSessionCache(tmp_path)
        session_id = cache.create_session()
        worker = OrthancDownloadWorker(
            FakeDicomWebClient(FIXTURES),
            cache,
            session_id,
            STUDY_UID,
            [SERIES_UID],
            server_settings=settings,
        )
        client = worker._make_thread_client()
        assert client._timeout == 60.0, f"Expected timeout=60.0, got {client._timeout}"


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
