"""Thumbnail scheduling behavior in AppController."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.application.thumbnail_scheduler import ThumbnailPriority
from echo_personal_tool.domain.models import InstanceMetadata


class _FakeSignal:
    def __init__(self) -> None:
        self._callbacks: list = []

    def connect(self, callback) -> None:
        self._callbacks.append(callback)

    def emit(self, *args) -> None:
        for callback in list(self._callbacks):
            callback(*args)


class _FakeThumbnailWorker:
    def __init__(
        self,
        path: Path,
        sop_instance_uid: str,
        number_of_frames: int,
        media_format: str,
        parent=None,
    ) -> None:
        self.path = Path(path)
        self.sop_instance_uid = sop_instance_uid
        self.number_of_frames = number_of_frames
        self.media_format = media_format
        self.parent = parent
        self.signals = SimpleNamespace(
            finished=_FakeSignal(),
            failed=_FakeSignal(),
        )


class _FakeFrameLoaderWorker:
    def __init__(
        self,
        path: Path,
        frame_index: int,
        media_format: str,
        parent=None,
    ) -> None:
        self.path = Path(path)
        self.frame_index = frame_index
        self.media_format = media_format
        self.parent = parent
        self.signals = SimpleNamespace(
            finished=_FakeSignal(),
            failed=_FakeSignal(),
        )


class _FakeVideoReader:
    def __init__(self) -> None:
        self.frame_count = 16
        self.fps = 25.0

    def __enter__(self) -> _FakeVideoReader:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def open(self, _path: Path) -> None:
        return None


class _RecordingThreadPool:
    def __init__(self) -> None:
        self.started: list[object] = []

    def start(self, worker) -> None:
        self.started.append(worker)


class _SlotLimitedThreadPool:
    def __init__(self, max_running: int) -> None:
        self.max_running = max_running
        self.running: list[object] = []
        self.queued: list[object] = []

    def start(self, worker) -> None:
        if len(self.running) < self.max_running:
            self.running.append(worker)
            return
        self.queued.append(worker)


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _thumbnail_instance(uid: str, tmp_path: Path) -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid=uid,
        series_uid="series",
        modality="US",
        number_of_frames=8,
        pixel_spacing=None,
        frame_time_ms=33.3,
        series_description="Thumbs",
        path=tmp_path / f"{uid}.mp4",
        media_format="mp4",
    )


def test_load_instance_not_blocked_by_thumbnail_backlog(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "echo_personal_tool.application.app_controller.ThumbnailLoaderWorker",
        _FakeThumbnailWorker,
    )
    monkeypatch.setattr(
        "echo_personal_tool.application.app_controller.FrameLoaderWorker",
        _FakeFrameLoaderWorker,
    )
    monkeypatch.setattr(
        "echo_personal_tool.application.app_controller.VideoReader",
        _FakeVideoReader,
    )

    thread_pool = _SlotLimitedThreadPool(max_running=3)
    controller = AppController(thread_pool=thread_pool, thumbnail_max_in_flight=2)
    backlog_instances = [
        _thumbnail_instance(f"thumb-{index}", tmp_path) for index in range(8)
    ]

    controller.request_thumbnail_previews(
        backlog_instances,
        ThumbnailPriority.P2_BACKGROUND,
    )

    running_thumbnail_workers = [
        worker for worker in thread_pool.running if isinstance(worker, _FakeThumbnailWorker)
    ]
    assert len(running_thumbnail_workers) == 2

    main_instance = _thumbnail_instance("main-uid", tmp_path)
    controller.load_instance(main_instance)

    running_frame_workers = [
        worker for worker in thread_pool.running if isinstance(worker, _FakeFrameLoaderWorker)
    ]
    queued_frame_workers = [
        worker for worker in thread_pool.queued if isinstance(worker, _FakeFrameLoaderWorker)
    ]
    assert len(running_frame_workers) == 1
    assert queued_frame_workers == []
    assert running_frame_workers[0].path == main_instance.path


def test_p0_thumbnail_request_preempts_background(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "echo_personal_tool.application.app_controller.ThumbnailLoaderWorker",
        _FakeThumbnailWorker,
    )

    thread_pool = _RecordingThreadPool()
    controller = AppController(thread_pool=thread_pool, thumbnail_max_in_flight=1)
    bg1 = _thumbnail_instance("bg-1", tmp_path)
    bg2 = _thumbnail_instance("bg-2", tmp_path)
    p0 = _thumbnail_instance("p0", tmp_path)

    controller.request_thumbnail_preview(bg1, ThumbnailPriority.P2_BACKGROUND)
    controller.request_thumbnail_preview(bg2, ThumbnailPriority.P2_BACKGROUND)
    controller.request_thumbnail_preview(p0, ThumbnailPriority.P0_VISIBLE_SELECTED)

    assert isinstance(thread_pool.started[0], _FakeThumbnailWorker)
    assert thread_pool.started[0].sop_instance_uid == "bg-1"

    thread_pool.started[0].signals.finished.emit(
        "bg-1",
        QImage(4, 4, QImage.Format.Format_Grayscale8),
    )

    started_uids = [
        worker.sop_instance_uid
        for worker in thread_pool.started
        if isinstance(worker, _FakeThumbnailWorker)
    ]
    assert started_uids[:2] == ["bg-1", "p0"]


def test_duplicate_thumbnail_requests_do_not_spawn_duplicate_workers(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "echo_personal_tool.application.app_controller.ThumbnailLoaderWorker",
        _FakeThumbnailWorker,
    )

    thread_pool = _RecordingThreadPool()
    controller = AppController(thread_pool=thread_pool, thumbnail_max_in_flight=1)
    dup = _thumbnail_instance("dup", tmp_path)

    controller.request_thumbnail_preview(dup, ThumbnailPriority.P1_NEAR_VISIBLE)
    controller.request_thumbnail_preview(dup, ThumbnailPriority.P0_VISIBLE_SELECTED)
    controller.request_thumbnail_previews([dup, dup], ThumbnailPriority.P0_VISIBLE_SELECTED)

    started_dup_workers = [
        worker
        for worker in thread_pool.started
        if isinstance(worker, _FakeThumbnailWorker) and worker.sop_instance_uid == "dup"
    ]
    assert len(started_dup_workers) == 1


def test_pending_thumbnail_set_replaced_by_scheduler_state(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "echo_personal_tool.application.app_controller.ThumbnailLoaderWorker",
        _FakeThumbnailWorker,
    )

    thread_pool = _RecordingThreadPool()
    controller = AppController(thread_pool=thread_pool, thumbnail_max_in_flight=1)
    dup = _thumbnail_instance("dup-state", tmp_path)
    assert controller._thumbnail_max_in_flight == 1

    controller.request_thumbnail_preview(dup, ThumbnailPriority.P1_NEAR_VISIBLE)
    controller.request_thumbnail_preview(dup, ThumbnailPriority.P0_VISIBLE_SELECTED)
    controller.request_thumbnail_previews([dup, dup], ThumbnailPriority.P0_VISIBLE_SELECTED)

    assert controller._thumbnail_in_flight == {
        "dup-state": ThumbnailPriority.P1_NEAR_VISIBLE
    }
    started_dup_workers = [
        worker
        for worker in thread_pool.started
        if isinstance(worker, _FakeThumbnailWorker) and worker.sop_instance_uid == "dup-state"
    ]
    assert len(started_dup_workers) == 1

    thread_pool.started[0].signals.finished.emit(
        "dup-state",
        QImage(4, 4, QImage.Format.Format_Grayscale8),
    )
    assert controller._thumbnail_in_flight == {}


def test_thumbnail_failure_releases_slot_and_dispatches_next(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "echo_personal_tool.application.app_controller.ThumbnailLoaderWorker",
        _FakeThumbnailWorker,
    )

    thread_pool = _RecordingThreadPool()
    controller = AppController(thread_pool=thread_pool, thumbnail_max_in_flight=1)
    first = _thumbnail_instance("fail-1", tmp_path)
    second = _thumbnail_instance("next-2", tmp_path)

    controller.request_thumbnail_preview(first, ThumbnailPriority.P1_NEAR_VISIBLE)
    controller.request_thumbnail_preview(second, ThumbnailPriority.P1_NEAR_VISIBLE)

    assert isinstance(thread_pool.started[0], _FakeThumbnailWorker)
    assert thread_pool.started[0].sop_instance_uid == "fail-1"

    thread_pool.started[0].signals.failed.emit("fail-1", "decode error")

    started_uids = [
        worker.sop_instance_uid
        for worker in thread_pool.started
        if isinstance(worker, _FakeThumbnailWorker)
    ]
    assert started_uids[:2] == ["fail-1", "next-2"]
