from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

pytestmark = pytest.mark.gui
from PySide6.QtWidgets import QApplication

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.domain.models import InstanceMetadata
from echo_personal_tool.infrastructure.system_profiler import PlaybackConfig


@pytest.fixture
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _mp4_instance(path: Path, frames: int = 30) -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid="1.2.3",
        series_uid="1.2.3.4",
        modality="US",
        number_of_frames=frames,
        pixel_spacing=None,
        frame_time_ms=33.3,
        series_description="Test",
        path=path,
        media_format="mp4",
    )


def test_prefetch_starts_batch_worker(qapp, monkeypatch, tmp_path) -> None:
    started: list[object] = []

    class _SpyPool:
        def start(self, worker):
            started.append(worker)

    class _SpyLoader:
        def __init__(self, path, frame_index=0, media_format="mp4", parent=None, total_frames=0, batch_size=0):
            self._batch_size = batch_size
            self._frame_index = frame_index
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
    mp4 = tmp_path / "c.mp4"
    mp4.write_bytes(b"\x00")
    inst = _mp4_instance(mp4, frames=100)
    controller._current_instance = inst
    controller._frame_cache.set_total_frames(mp4, 100)
    controller._frame_cache.put(0, np.zeros((8, 8), dtype=np.uint8))
    controller._state_manager.set_instance(inst, total_frames=100, frame_time_ms=33.3)
    controller._state_manager.set_playing(True)

    controller._prefetch_playback_buffer(0)

    assert len(started) == 1
    assert started[0]._batch_size == 3
    assert started[0]._frame_index == 1


def test_prefetch_skipped_when_buffer_full(qapp, monkeypatch, tmp_path) -> None:
    started: list[object] = []

    class _SpyPool:
        def start(self, worker):
            started.append(worker)

    monkeypatch.setattr(
        "echo_personal_tool.application.app_controller.FrameLoaderWorker",
        MagicMock,
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
    mp4 = tmp_path / "c.mp4"
    mp4.write_bytes(b"\x00")
    inst = _mp4_instance(mp4, frames=100)
    controller._current_instance = inst
    controller._frame_cache.set_total_frames(mp4, 100)
    controller._frame_cache.put(0, np.zeros((8, 8), dtype=np.uint8))
    controller._frame_cache.put(1, np.ones((8, 8), dtype=np.uint8))
    controller._frame_cache.put(2, np.full((8, 8), 2, dtype=np.uint8))
    controller._frame_cache.put(3, np.full((8, 8), 3, dtype=np.uint8))
    controller._state_manager.set_instance(inst, total_frames=100, frame_time_ms=33.3)
    controller._state_manager.set_playing(True)

    controller._prefetch_playback_buffer(0)

    assert started == []


def test_prefetch_batch_capped_by_radius(qapp, monkeypatch, tmp_path) -> None:
    started: list[object] = []

    class _SpyPool:
        def start(self, worker):
            started.append(worker)

    class _SpyLoader:
        def __init__(self, path, frame_index=0, media_format="mp4", parent=None, total_frames=0, batch_size=0):
            self._batch_size = batch_size
            self._frame_index = frame_index
            self.signals = MagicMock()

    monkeypatch.setattr(
        "echo_personal_tool.application.app_controller.FrameLoaderWorker",
        _SpyLoader,
    )
    controller = AppController(thread_pool=_SpyPool())
    controller._playback_config = PlaybackConfig(
        prefetch_radius=5,
        min_buffer=2,
        batch_size=8,
        max_lag_frames=2,
        evict_window=30,
        scroll_debounce_ms=80,
        scroll_batch_size=3,
    )
    controller._adaptive_batch_size = 8
    mp4 = tmp_path / "c.mp4"
    mp4.write_bytes(b"\x00")
    inst = _mp4_instance(mp4, frames=100)
    controller._current_instance = inst
    controller._frame_cache.set_total_frames(mp4, 100)
    controller._frame_cache.put(0, np.zeros((8, 8), dtype=np.uint8))
    controller._frame_cache.put(1, np.ones((8, 8), dtype=np.uint8))
    controller._state_manager.set_instance(inst, total_frames=100, frame_time_ms=33.3)
    controller._state_manager.set_playing(True)

    controller._prefetch_playback_buffer(0)

    assert len(started) == 1
    assert started[0]._batch_size == 4


def test_advance_playback_skips_on_lag(qapp, tmp_path) -> None:
    controller = AppController()
    controller._playback_config = PlaybackConfig(
        prefetch_radius=3,
        min_buffer=2,
        batch_size=3,
        max_lag_frames=2,
        evict_window=30,
        scroll_debounce_ms=80,
        scroll_batch_size=3,
    )
    controller._prefetch_playback_buffer = lambda *a, **k: None
    mp4 = tmp_path / "c.mp4"
    mp4.write_bytes(b"\x00")
    inst = _mp4_instance(mp4, frames=20)
    controller._current_instance = inst
    controller._frame_cache.set_total_frames(mp4, 20)
    for i in range(5):
        controller._frame_cache.put(i, np.full((4, 4), i, dtype=np.uint8))
    controller._frame_cache.put(8, np.full((4, 4), 8, dtype=np.uint8))
    controller._state_manager.set_instance(inst, total_frames=20, frame_time_ms=33.3)
    controller._state_manager.set_frame(3)
    controller._state_manager._is_playing = True
    controller._pending_decode_id = 0
    controller._pending_load_id = 0
    controller._prefetch_load_id = 0

    controller._advance_playback()

    assert controller.state_manager.snapshot.current_frame_index == 4


def test_advance_playback_lag_skip_to_nearest(qapp, tmp_path) -> None:
    controller = AppController()
    controller._playback_config = PlaybackConfig(
        prefetch_radius=3,
        min_buffer=2,
        batch_size=3,
        max_lag_frames=2,
        evict_window=30,
        scroll_debounce_ms=80,
        scroll_batch_size=3,
    )
    controller._prefetch_playback_buffer = lambda *a, **k: None
    mp4 = tmp_path / "c.mp4"
    mp4.write_bytes(b"\x00")
    inst = _mp4_instance(mp4, frames=20)
    controller._current_instance = inst
    controller._frame_cache.set_total_frames(mp4, 20)
    controller._frame_cache.put(3, np.zeros((4, 4), dtype=np.uint8))
    for i in (5, 6, 7, 8):
        controller._frame_cache.put(i, np.full((4, 4), i, dtype=np.uint8))
    controller._state_manager.set_instance(inst, total_frames=20, frame_time_ms=33.3)
    controller._state_manager.set_frame(3)
    controller._state_manager._is_playing = True
    controller._pending_decode_id = 0
    controller._pending_load_id = 0
    controller._prefetch_load_id = 0
    controller._leading_static_frames[mp4.resolve()] = 0

    controller._advance_playback()

    assert controller.state_manager.snapshot.current_frame_index == 5


def test_lazy_leading_static_detects_static_prefix(qapp, tmp_path) -> None:
    controller = AppController()
    frames = [np.zeros((8, 8), dtype=np.uint8) for _ in range(4)]
    frames.append(np.full((8, 8), 10, dtype=np.uint8))
    path = tmp_path / "x.dcm"
    path.write_bytes(b"\x00")
    controller._frame_cache.set_total_frames(path, total=len(frames))
    for i, f in enumerate(frames):
        controller._frame_cache.put(i, f)
    leading = controller._detect_leading_static_from_cache(path, total=len(frames))
    assert leading == 3


def test_prefetch_cancelled_on_pause(qapp, monkeypatch, tmp_path) -> None:
    class _SpyPool:
        def __init__(self):
            self.started: list = []

        def start(self, worker, *args, **kwargs):
            self.started.append(worker)

    pool = _SpyPool()

    class _SpyLoader:
        def __init__(self, path, frame_index=0, media_format="mp4", parent=None, total_frames=0, batch_size=0):
            self._batch_size = batch_size
            self._frame_index = frame_index
            self.signals = MagicMock()

    monkeypatch.setattr(
        "echo_personal_tool.application.app_controller.FrameLoaderWorker",
        _SpyLoader,
    )
    controller = AppController(thread_pool=pool)
    controller._thread_pool = pool
    controller._playback_config = PlaybackConfig(
        prefetch_radius=3,
        min_buffer=2,
        batch_size=3,
        max_lag_frames=2,
        evict_window=30,
        scroll_debounce_ms=80,
        scroll_batch_size=3,
    )
    mp4 = tmp_path / "c.mp4"
    mp4.write_bytes(b"\x00")
    inst = _mp4_instance(mp4, frames=100)
    controller._current_instance = inst
    controller._frame_cache.set_total_frames(mp4, 100)
    controller._frame_cache.put(0, np.zeros((8, 8), dtype=np.uint8))
    controller._state_manager.set_instance(inst, total_frames=100, frame_time_ms=33.3)
    controller._state_manager._is_playing = True
    controller._prefetch_load_id = 0

    controller._prefetch_playback_buffer(0)
    assert controller._prefetch_load_id != 0

    controller._invalidate_prefetch()
    assert controller._prefetch_load_id == 0


def test_adaptive_batch_increases_on_fast_prefetch(qapp, monkeypatch, tmp_path) -> None:
    controller = AppController()
    controller._playback_config = PlaybackConfig(
        prefetch_radius=10,
        min_buffer=2,
        batch_size=4,
        max_lag_frames=2,
        evict_window=30,
        scroll_debounce_ms=80,
        scroll_batch_size=3,
    )
    controller._adaptive_batch_size = 4
    mp4 = tmp_path / "c.mp4"
    mp4.write_bytes(b"\x00")
    inst = _mp4_instance(mp4)
    controller._current_instance = inst
    controller._prefetch_load_id = 1
    t0 = 1000.0
    monkeypatch.setattr(
        "echo_personal_tool.application.app_controller.perf_counter",
        lambda: t0 + 0.001,
    )
    controller._prefetch_batch_start = t0
    controller._prefetch_ema_latency_ms = 0.0
    frames = [(2, np.zeros((4, 4), dtype=np.uint8))]
    controller._on_prefetch_batch_loaded(1, mp4, frames)
    assert controller._adaptive_batch_size == 6


def test_adaptive_batch_decreases_on_slow_prefetch(qapp, monkeypatch, tmp_path) -> None:
    controller = AppController()
    controller._playback_config = PlaybackConfig(
        prefetch_radius=10,
        min_buffer=2,
        batch_size=8,
        max_lag_frames=2,
        evict_window=30,
        scroll_debounce_ms=80,
        scroll_batch_size=3,
    )
    controller._adaptive_batch_size = 8
    mp4 = tmp_path / "c.mp4"
    mp4.write_bytes(b"\x00")
    inst = _mp4_instance(mp4)
    controller._current_instance = inst
    controller._prefetch_load_id = 2
    controller._prefetch_ema_latency_ms = 80.0
    t0 = 1000.0
    monkeypatch.setattr(
        "echo_personal_tool.application.app_controller.perf_counter",
        lambda: t0 + 0.2,
    )
    controller._prefetch_batch_start = t0
    frames = [(3, np.zeros((4, 4), dtype=np.uint8))]
    controller._on_prefetch_batch_loaded(2, mp4, frames)
    assert controller._adaptive_batch_size == 7


def test_small_loop_prefetch_all_unloaded(qapp, monkeypatch, tmp_path) -> None:
    started: list[object] = []

    class _SpyPool:
        def start(self, worker):
            started.append(worker)

    class _SpyLoader:
        def __init__(self, path, frame_index=0, media_format="mp4", parent=None, total_frames=0, batch_size=0):
            self._batch_size = batch_size
            self._frame_index = frame_index
            self.signals = MagicMock()

    monkeypatch.setattr(
        "echo_personal_tool.application.app_controller.FrameLoaderWorker",
        _SpyLoader,
    )
    controller = AppController(thread_pool=_SpyPool())
    controller._playback_config = PlaybackConfig(
        prefetch_radius=5,
        min_buffer=2,
        batch_size=3,
        max_lag_frames=2,
        evict_window=30,
        scroll_debounce_ms=80,
        scroll_batch_size=3,
    )
    mp4 = tmp_path / "c.mp4"
    mp4.write_bytes(b"\x00")
    inst = _mp4_instance(mp4, frames=45)
    controller._current_instance = inst
    controller._frame_cache.set_total_frames(mp4, 45)
    controller._frame_cache.put(0, np.zeros((8, 8), dtype=np.uint8))
    controller._state_manager.set_instance(inst, total_frames=45, frame_time_ms=33.3)
    controller._state_manager.set_playing(True)

    controller._prefetch_playback_buffer(0)

    assert len(started) == 1
    assert started[0]._batch_size == 44
    assert started[0]._frame_index == 1


def test_advance_playback_double_next_skip(qapp, tmp_path) -> None:
    controller = AppController()
    controller._playback_config = PlaybackConfig(
        prefetch_radius=3,
        min_buffer=2,
        batch_size=3,
        max_lag_frames=10,
        evict_window=30,
        scroll_debounce_ms=80,
        scroll_batch_size=3,
    )
    controller._prefetch_playback_buffer = lambda *a, **k: None
    controller._last_frame_shown_at = 0.0
    mp4 = tmp_path / "c.mp4"
    mp4.write_bytes(b"\x00")
    inst = _mp4_instance(mp4, frames=10)
    controller._current_instance = inst
    controller._frame_cache.set_total_frames(mp4, 10)
    controller._frame_cache.put(0, np.zeros((4, 4), dtype=np.uint8))
    controller._frame_cache.put(2, np.full((4, 4), 2, dtype=np.uint8))
    controller._state_manager.set_instance(inst, total_frames=10, frame_time_ms=33.3)
    controller._state_manager.set_frame(0)
    controller._state_manager._is_playing = True
    controller._pending_decode_id = 0
    controller._pending_load_id = 0
    controller._prefetch_load_id = 0
    controller._playback_warmup_pending = False

    controller._advance_playback()

    assert controller.state_manager.snapshot.current_frame_index == 2
