"""Decode gate: one decoding worker per file, parked requests served by priority.

Concurrent `FrameLoaderWorker`s for the same cine file cannot decode in parallel - they
serialise on the shared session / video-reader lock - so they only occupy `QThreadPool`
threads, and a scroll target submitted behind a playback prefetch batch waits for the
whole batch. The gate keeps one owner per file and lets it adopt the parked requests in
priority order.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

pytestmark = pytest.mark.gui

import cv2
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from echo_personal_tool.application.decode_gate import DecodeGate, DecodePriority
from echo_personal_tool.application.workers.frame_loader_worker import FrameLoaderWorker


@pytest.fixture
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def png(tmp_path) -> Path:
    path = tmp_path / "frame.png"
    cv2.imwrite(str(path), np.full((8, 8, 3), 128, dtype=np.uint8))
    return path


class _FakeWorker:
    """Duck-typed worker: the gate only needs `decode_path` and `priority`."""

    def __init__(self, path: Path, priority: DecodePriority = DecodePriority.PLAYBACK) -> None:
        self.decode_path = path
        self.priority = priority


class TestGateClaims:
    def test_first_worker_claims_the_file(self, tmp_path) -> None:
        gate = DecodeGate()
        file_a = tmp_path / "a.dcm"

        assert gate.enter(_FakeWorker(file_a)) is True
        assert gate.is_busy(file_a) is True

    def test_second_worker_for_the_same_file_parks(self, tmp_path) -> None:
        gate = DecodeGate()
        file_a = tmp_path / "a.dcm"

        assert gate.enter(_FakeWorker(file_a)) is True
        assert gate.enter(_FakeWorker(file_a)) is False
        assert gate.parked_count(file_a) == 1

    def test_other_files_are_not_blocked(self, tmp_path) -> None:
        gate = DecodeGate()
        file_a = tmp_path / "a.dcm"
        file_b = tmp_path / "b.dcm"

        assert gate.enter(_FakeWorker(file_a)) is True
        assert gate.enter(_FakeWorker(file_b)) is True

    def test_the_same_file_through_a_different_path_spelling_is_one_claim(self, tmp_path) -> None:
        gate = DecodeGate()
        file_a = tmp_path / "a.dcm"
        file_a.write_bytes(b"")
        via_dot = tmp_path / "." / "a.dcm"

        assert gate.enter(_FakeWorker(file_a)) is True
        assert gate.enter(_FakeWorker(via_dot)) is False


class TestGateOrdering:
    def test_parked_requests_are_served_by_priority(self, tmp_path) -> None:
        gate = DecodeGate()
        file_a = tmp_path / "a.dcm"
        owner = _FakeWorker(file_a)
        prefetch = _FakeWorker(file_a, DecodePriority.PLAYBACK)
        target = _FakeWorker(file_a, DecodePriority.INTERACTIVE)
        neighbors = _FakeWorker(file_a, DecodePriority.NEIGHBORS)
        background = _FakeWorker(file_a, DecodePriority.BACKGROUND)

        gate.enter(owner)
        for worker in (background, prefetch, neighbors, target):
            assert gate.enter(worker) is False

        assert gate.next_parked(owner) is target
        assert gate.next_parked(target) is neighbors
        assert gate.next_parked(neighbors) is prefetch
        assert gate.next_parked(prefetch) is background
        assert gate.next_parked(background) is None

    def test_same_priority_is_served_first_come_first_served(self, tmp_path) -> None:
        gate = DecodeGate()
        file_a = tmp_path / "a.dcm"
        owner = _FakeWorker(file_a)
        first = _FakeWorker(file_a)
        second = _FakeWorker(file_a)

        gate.enter(owner)
        gate.enter(first)
        gate.enter(second)

        assert gate.next_parked(owner) is first
        assert gate.next_parked(first) is second

    def test_file_is_free_again_once_the_queue_drains(self, tmp_path) -> None:
        gate = DecodeGate()
        file_a = tmp_path / "a.dcm"
        owner = _FakeWorker(file_a)
        parked = _FakeWorker(file_a)

        gate.enter(owner)
        gate.enter(parked)
        assert gate.next_parked(owner) is parked
        assert gate.next_parked(parked) is None
        assert gate.is_busy(file_a) is False
        assert gate.enter(_FakeWorker(file_a)) is True


class TestGateRelease:
    def test_release_hands_back_parked_workers(self, tmp_path) -> None:
        gate = DecodeGate()
        file_a = tmp_path / "a.dcm"
        owner = _FakeWorker(file_a)
        parked = _FakeWorker(file_a)

        gate.enter(owner)
        gate.enter(parked)

        assert gate.release(owner) == [parked]
        assert gate.is_busy(file_a) is False

    def test_release_by_a_non_owner_keeps_the_claim(self, tmp_path) -> None:
        gate = DecodeGate()
        file_a = tmp_path / "a.dcm"
        owner = _FakeWorker(file_a)
        stranger = _FakeWorker(file_a)

        gate.enter(owner)

        assert gate.release(stranger) == []
        assert gate.is_busy(file_a) is True
        assert gate.next_parked(owner) is None


class TestWorkerIntegration:
    def test_worker_without_a_gate_decodes_immediately(self, qapp, png) -> None:
        worker = FrameLoaderWorker(png, media_format="png")
        received: list[np.ndarray] = []
        worker.signals.finished.connect(received.append, Qt.ConnectionType.DirectConnection)

        worker.run()

        assert len(received) == 1
        assert received[0].shape[:2] == (8, 8)

    def test_parked_worker_is_decoded_by_the_owner(self, qapp, png) -> None:
        gate = DecodeGate()
        owner = FrameLoaderWorker(png, media_format="png")
        parked = FrameLoaderWorker(png, media_format="png")
        owner.decode_gate = gate
        parked.decode_gate = gate
        received: list[np.ndarray] = []
        parked.signals.finished.connect(received.append, Qt.ConnectionType.DirectConnection)

        assert gate.enter(owner) is True
        parked.run()  # arrives while the owner is decoding -> parks, emits nothing yet
        assert received == []

        adopted = gate.next_parked(owner)
        assert adopted is parked
        adopted._decode_request()

        assert len(received) == 1
        assert gate.release(adopted) == []

    def test_owner_adopts_a_request_that_parked_mid_decode(self, qapp, png, monkeypatch) -> None:
        gate = DecodeGate()
        owner = FrameLoaderWorker(png, media_format="png")
        late = FrameLoaderWorker(png, media_format="png")
        owner.decode_gate = gate
        late.decode_gate = gate
        late.priority = DecodePriority.INTERACTIVE
        received: list[np.ndarray] = []
        late.signals.finished.connect(received.append, Qt.ConnectionType.DirectConnection)

        original = FrameLoaderWorker._decode_request

        def _decode(self):
            original(self)
            if self is owner:
                late.run()  # submitted while the owner is busy

        monkeypatch.setattr(FrameLoaderWorker, "_decode_request", _decode)

        owner.run()

        assert len(received) == 1
        assert gate.is_busy(png) is False

    def test_video_worker_bypasses_the_gate(self, qapp, tmp_path, monkeypatch) -> None:
        """MP4 is seek-bound: it must not queue behind another request for the same file."""
        video = tmp_path / "c.mp4"
        video.write_bytes(b"")
        gate = DecodeGate()
        owner = FrameLoaderWorker(video, media_format="mp4")
        second = FrameLoaderWorker(video, media_format="mp4")
        for worker in (owner, second):
            worker.decode_gate = gate
        decoded: list[FrameLoaderWorker] = []
        monkeypatch.setattr(FrameLoaderWorker, "_decode_request", lambda self: decoded.append(self))

        assert gate.enter(owner) is True
        second.run()

        assert decoded == [second]
        assert gate.parked_count(video) == 0

    def test_ungated_format_never_probes_the_gate(self, qapp, tmp_path, monkeypatch) -> None:
        """Regression guard: probing the gate between mp4 batch frames cost ~60 ms per frame.

        Seek-bound video keeps its read order to itself; a gate probe per frame disturbed
        it enough to triple the scroll latency (MJPEG 720p: 38 -> 101 ms over 12 seeks).
        """
        video = tmp_path / "c.mp4"
        gate = DecodeGate()
        worker = FrameLoaderWorker(video, media_format="mp4")
        worker.decode_gate = gate
        probed: list[FrameLoaderWorker] = []
        monkeypatch.setattr(DecodeGate, "steal", lambda self, owner: probed.append(owner))

        worker._drain_higher_priority()

        assert probed == []

    def test_gated_format_probes_the_gate_between_frames(self, qapp, tmp_path, monkeypatch) -> None:
        dcm = tmp_path / "c.dcm"
        gate = DecodeGate()
        worker = FrameLoaderWorker(dcm, media_format="dicom")
        worker.decode_gate = gate
        probed: list[FrameLoaderWorker] = []
        monkeypatch.setattr(DecodeGate, "steal", lambda self, owner: probed.append(owner) or None)

        worker._drain_higher_priority()

        assert probed == [worker]

    def test_drain_serves_only_requests_that_outrank_the_owner(self, qapp, png) -> None:
        gate = DecodeGate()
        owner = FrameLoaderWorker(png, media_format="png")
        urgent = FrameLoaderWorker(png, media_format="png")
        later = FrameLoaderWorker(png, media_format="png")
        for worker in (owner, urgent, later):
            worker.decode_gate = gate
        owner.priority = DecodePriority.PLAYBACK
        urgent.priority = DecodePriority.INTERACTIVE
        later.priority = DecodePriority.BACKGROUND
        decoded: list[FrameLoaderWorker] = []
        for worker in (urgent, later):
            worker.signals.finished.connect(lambda _px, w=worker: decoded.append(w), Qt.ConnectionType.DirectConnection)

        assert gate.enter(owner) is True
        urgent.run()  # both park: the owner holds the file
        later.run()

        owner._drain_higher_priority()

        assert decoded == [urgent]  # BACKGROUND does not outrank PLAYBACK
        assert gate.parked_count(png) == 1
        assert gate.is_busy(png) is True  # the owner keeps the file and resumes its batch

    def test_interactive_target_overtakes_a_queued_prefetch_batch(self, qapp, png) -> None:
        gate = DecodeGate()
        owner = FrameLoaderWorker(png, media_format="png")
        batch = FrameLoaderWorker(png, frame_index=0, media_format="png", total_frames=4, batch_size=4)
        target = FrameLoaderWorker(png, frame_index=2, media_format="png", total_frames=4, batch_size=1)
        for worker in (owner, batch, target):
            worker.decode_gate = gate
        batch.priority = DecodePriority.PLAYBACK
        target.priority = DecodePriority.INTERACTIVE
        decoded: list[FrameLoaderWorker] = []
        for worker in (batch, target):
            worker.signals.finished.connect(lambda _px, w=worker: decoded.append(w), Qt.ConnectionType.DirectConnection)
            worker.signals.batch_finished.connect(
                lambda _res, w=worker: decoded.append(w), Qt.ConnectionType.DirectConnection
            )

        assert gate.enter(owner) is True
        batch.run()
        target.run()
        assert decoded == []

        # Drain the way FrameLoaderWorker.run() does.
        current = owner
        while True:
            nxt = gate.next_parked(current)
            if nxt is None:
                break
            nxt._decode_request()
            current = nxt

        assert decoded == [target, batch]
        assert gate.is_busy(png) is False


class TestCoalescing:
    def test_newer_interactive_target_supersedes_the_parked_one(self, qapp, png) -> None:
        gate = DecodeGate()
        owner = FrameLoaderWorker(png, media_format="png")
        stale = FrameLoaderWorker(png, frame_index=3, media_format="png")
        newest = FrameLoaderWorker(png, frame_index=9, media_format="png")
        for worker in (owner, stale, newest):
            worker.decode_gate = gate
            worker.priority = DecodePriority.INTERACTIVE
        cancelled: list[FrameLoaderWorker] = []
        stale.signals.cancelled.connect(lambda: cancelled.append(stale), Qt.ConnectionType.DirectConnection)

        assert gate.enter(owner) is True
        stale.run()  # parks
        newest.run()  # parks and supersedes the stale target

        assert cancelled == [stale]
        assert gate.parked_count(png) == 1
        assert gate.next_parked(owner) is newest
        assert gate.next_parked(newest) is None

    def test_speculative_requests_survive_a_new_target(self, qapp, png) -> None:
        gate = DecodeGate()
        owner = FrameLoaderWorker(png, media_format="png")
        batch = FrameLoaderWorker(png, frame_index=0, media_format="png", total_frames=4, batch_size=4)
        neighbors = FrameLoaderWorker(png, frame_index=1, media_format="png", total_frames=4, batch_size=2)
        target = FrameLoaderWorker(png, frame_index=3, media_format="png")
        owner.priority = DecodePriority.INTERACTIVE
        batch.priority = DecodePriority.PLAYBACK
        neighbors.priority = DecodePriority.NEIGHBORS
        target.priority = DecodePriority.INTERACTIVE
        for worker in (owner, batch, neighbors, target):
            worker.decode_gate = gate

        assert gate.enter(owner) is True
        batch.run()
        neighbors.run()
        target.run()

        assert gate.parked_count(png) == 3
        assert gate.next_parked(owner) is target
        assert gate.next_parked(target) is neighbors
        assert gate.next_parked(neighbors) is batch

    def test_cancel_parked_emits_the_cancelled_signal(self, qapp, png) -> None:
        worker = FrameLoaderWorker(png, media_format="png")
        cancelled: list[bool] = []
        worker.signals.cancelled.connect(lambda: cancelled.append(True), Qt.ConnectionType.DirectConnection)

        worker.cancel_parked()

        assert cancelled == [True]


class TestControllerWiring:
    def _controller(self, monkeypatch, tmp_path):
        from echo_personal_tool.application.app_controller import AppController
        from echo_personal_tool.domain.models import InstanceMetadata
        from echo_personal_tool.infrastructure.system_profiler import PlaybackConfig

        started: list[object] = []

        class _SpyPool:
            def start(self, worker):
                started.append(worker)

        class _SpyLoader:
            """Stands in for FrameLoaderWorker: records the gate assignment."""

            def __init__(self, path, frame_index=0, media_format="mp4", parent=None, total_frames=0, batch_size=0):
                self._path = path
                self._frame_index = frame_index
                self._batch_size = batch_size
                self.signals = MagicMock()

        monkeypatch.setattr(
            "echo_personal_tool.application.app_controller.FrameLoaderWorker",
            _SpyLoader,
        )
        controller = AppController(thread_pool=_SpyPool())
        controller._playback_config = PlaybackConfig(
            prefetch_radius=3,
            min_buffer=2,
            batch_size=3,
            max_lag_frames=2,
            evict_window=30,
            scroll_debounce_ms=80,
            scroll_batch_size=3,
        )
        path = tmp_path / "c.mp4"
        path.write_bytes(b"\x00")
        instance = InstanceMetadata(
            sop_instance_uid="1.2.3",
            series_uid="1.2.3.4",
            modality="US",
            number_of_frames=100,
            pixel_spacing=None,
            frame_time_ms=33.3,
            series_description="Test",
            path=path,
            media_format="mp4",
        )
        controller._current_instance = instance
        controller._frame_cache.set_total_frames(path, 100)
        controller._frame_cache.put(0, np.zeros((8, 8), dtype=np.uint8))
        controller._state_manager.set_instance(instance, total_frames=100, frame_time_ms=33.3)
        controller._state_manager.set_playing(True)
        return controller, started, path

    def test_prefetch_batch_is_marked_as_playback_priority(self, qapp, monkeypatch, tmp_path) -> None:
        controller, started, _path = self._controller(monkeypatch, tmp_path)

        controller._prefetch_playback_buffer(0)

        assert len(started) == 1
        assert started[0].priority == DecodePriority.PLAYBACK
        assert started[0].decode_gate is controller._decode_gate

    def test_scroll_target_is_marked_interactive(self, qapp, monkeypatch, tmp_path) -> None:
        controller, started, _path = self._controller(monkeypatch, tmp_path)

        controller._start_scroll_target_load(7, scroll=True)

        assert len(started) == 1
        assert started[0].priority == DecodePriority.INTERACTIVE
        assert started[0].decode_gate is controller._decode_gate
