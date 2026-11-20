"""#619: ThumbnailQueueCoordinator owns the queue; AppController only forwards."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.gui
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QWidget

from echo_personal_tool.application.thumbnail_queue_coordinator import ThumbnailQueueCoordinator
from echo_personal_tool.application.thumbnail_scheduler import ThumbnailPriority
from echo_personal_tool.domain.models import InstanceMetadata


class _FakeSignal:
    def __init__(self) -> None:
        self._callbacks: list = []

    def connect(self, callback, *args, **kwargs) -> None:
        self._callbacks.append(callback)

    def emit(self, *args) -> None:
        for callback in list(self._callbacks):
            callback(*args)


class _FakeSignals:
    def __init__(self) -> None:
        self.finished = _FakeSignal()
        self.failed = _FakeSignal()


class _FakeWorker:
    def __init__(self, path, uid, *, number_of_frames, media_format, preview_size, parent=None) -> None:
        self.sop_instance_uid = uid
        self.preview_size = preview_size
        self.signals = _FakeSignals()
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class _RecordingPool:
    def __init__(self) -> None:
        self.started: list = []

    def start(self, worker) -> None:
        self.started.append(worker)

    def setMaxThreadCount(self, n) -> None:
        self.max = n

    def maxThreadCount(self) -> int:
        return getattr(self, "max", 0)


def _instance(uid: str, tmp_path: Path) -> InstanceMetadata:
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


def _coordinator(tmp_path, pool, *, pending=0, playing=False) -> tuple[QWidget, ThumbnailQueueCoordinator]:
    host = QWidget()
    queue = ThumbnailQueueCoordinator(
        parent=host,
        max_in_flight=1,
        thread_pool=pool,
        worker_factory=lambda path, uid, **kw: _FakeWorker(path, uid, **kw),
        pending_decode_provider=lambda: pending,
        is_playing_provider=lambda: playing,
    )
    return host, queue


def test_priority_order_and_in_flight_limit(qapp, tmp_path) -> None:
    pool = _RecordingPool()
    _host, queue = _coordinator(tmp_path, pool)  # max_in_flight=1
    first = _instance("first", tmp_path)
    bg = _instance("bg", tmp_path)
    fg = _instance("fg", tmp_path)
    queue.request_preview(first)
    queue.request_preview(bg, ThumbnailPriority.P2_BACKGROUND)
    queue.request_preview(fg, ThumbnailPriority.P0_VISIBLE_SELECTED)
    # One slot: the first request starts, the other two stay parked.
    assert [w.sop_instance_uid for w in pool.started] == ["first"]
    assert queue.in_flight == {"first": ThumbnailPriority.P2_BACKGROUND}
    # When the slot frees, the visible (P0) request jumps the background one.
    pool.started[0].signals.finished.emit("first", QImage())
    assert [w.sop_instance_uid for w in pool.started] == ["first", "fg"]
    pool.started[1].signals.finished.emit("fg", QImage())
    assert [w.sop_instance_uid for w in pool.started] == ["first", "fg", "bg"]
    pool.started[2].signals.finished.emit("bg", QImage())
    assert queue.workers == {}


def test_stale_generation_completion_is_dropped(qapp, tmp_path) -> None:
    pool = _RecordingPool()
    _host, queue = _coordinator(tmp_path, pool)
    emitted: list = []
    queue.thumbnail_loaded.connect(lambda *args: emitted.append(args))
    first = _instance("same", tmp_path)
    queue.request_preview(first)
    old_worker = pool.started[0]
    queue.reset()
    queue.request_preview(first)
    old_worker.signals.finished.emit("same", QImage())
    assert emitted == []
    pool.started[1].signals.finished.emit("same", QImage())
    assert len(emitted) == 1
    assert queue.workers == {}


def test_reset_cancels_running_workers_and_clears_state(qapp, tmp_path) -> None:
    pool = _RecordingPool()
    _host, queue = _coordinator(tmp_path, pool)
    queue.request_preview(_instance("a", tmp_path))
    worker = pool.started[0]
    queue.reset()
    assert worker.cancelled
    assert queue.in_flight == {}
    assert queue.first_preview_emitted is False


def test_pump_is_gated_by_pending_decode_and_playback(qapp, tmp_path) -> None:
    pool = _RecordingPool()
    pending = [1]
    playing = [False]
    host = QWidget()
    queue = ThumbnailQueueCoordinator(
        parent=host,
        max_in_flight=1,
        thread_pool=pool,
        worker_factory=lambda path, uid, **kw: _FakeWorker(path, uid, **kw),
        pending_decode_provider=lambda: pending[0],
        is_playing_provider=lambda: playing[0],
    )
    queue.request_preview(_instance("x", tmp_path))
    assert pool.started == []
    pending[0] = 0
    queue.pump()
    assert [w.sop_instance_uid for w in pool.started] == ["x"]


def test_preview_box_provider_and_fallback(qapp, tmp_path) -> None:
    pool = _RecordingPool()
    _host, queue = _coordinator(tmp_path, pool)
    assert queue.preview_box() == 96
    queue.set_preview_size_provider(lambda: 264)
    assert queue.preview_box() == 264
    queue.set_preview_size_provider(lambda: 48)
    assert queue.preview_box() == 96
    queue.set_preview_size_provider(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert queue.preview_box() == 96
