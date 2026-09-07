from __future__ import annotations

import gc
import threading
from pathlib import Path
from time import perf_counter
from unittest.mock import MagicMock

import numpy as np
import pytest

pytestmark = pytest.mark.gui
from PySide6.QtWidgets import QApplication

from echo_personal_tool.application.app_controller import (
    _GC_MIN_INTERVAL_SEC,
    _LEADING_STATIC_MAX_FRAMES,
    AppController,
)
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
    # Not cfg.batch_size=3: a prefetch run is floored at a quarter second of playback
    # (0.25 s / 33.3 ms = 8 frames at this frame rate) so one thread-pool round-trip
    # amortises over more than a couple of frames.
    assert started[0]._batch_size == 8
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
        # 0.1 s at 33.3 ms/frame -> a 3-frame target, so the 4 cached frames below
        # really are "buffer full" (the default 1.0 s would ask for 30).
        prefetch_seconds=0.1,
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
        # 0.15 s at 33.3 ms/frame rounds to 4, so the target stays at the radius floor
        # of 5 and the batch is capped by the 4 free slots ahead of the playhead.
        prefetch_seconds=0.15,
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


def test_prefetch_small_cine_loads_full_batch(qapp, monkeypatch, tmp_path) -> None:
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


def test_prefetch_small_cine_too_big_falls_back_to_radius(qapp, monkeypatch, tmp_path) -> None:
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
    inst = _mp4_instance(mp4, frames=45)
    controller._current_instance = inst
    # Large frames so the whole cine doesn't fit under a small cap; prefetch
    # must fall back to the radius-limited path instead of one giant batch.
    controller._frame_cache._max_cache_bytes = 5 * 1024 * 1024
    controller._frame_cache.set_total_frames(mp4, 45)
    controller._frame_cache.put(0, np.zeros((400, 400), dtype=np.uint8))
    controller._state_manager.set_instance(inst, total_frames=45, frame_time_ms=33.3)
    controller._state_manager.set_playing(True)

    controller._prefetch_playback_buffer(0)

    assert len(started) == 1
    # Windowed path, not one 44-frame run: the 5 MB cap holds 32 of these 160 KB frames,
    # so the 1 s target (30 frames) is allowed but the batch stays at the adaptive size.
    assert started[0]._batch_size == 8
    assert started[0]._frame_index == 1


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


def _timing_controller(tmp_path, batch_size: int = 8) -> AppController:
    """Controller wired for decode-timing tests: 33.3 ms/frame, request id 7 in flight."""
    controller = AppController()
    controller._playback_config = PlaybackConfig(
        prefetch_radius=10,
        min_buffer=2,
        batch_size=batch_size,
        max_lag_frames=2,
        evict_window=30,
        scroll_debounce_ms=80,
        scroll_batch_size=3,
    )
    controller._adaptive_batch_size = batch_size
    mp4 = tmp_path / "c.mp4"
    mp4.write_bytes(b"\x00")
    inst = _mp4_instance(mp4)
    controller._current_instance = inst
    controller._state_manager.set_instance(inst, total_frames=30, frame_time_ms=33.3)
    controller._prefetch_request_id = 7
    return controller


def test_prefetch_target_capped_by_memory_capacity(qapp, tmp_path) -> None:
    """A budget that retains 7 frames must not be asked to buffer 30 of them.

    Tuning raises the budget and the window first, so the cap only binds once the share of
    available RAM (`_cache_ram_cap_bytes`) is reached - which is the case worth covering:
    frames decoded past what the cache retains are decoded twice.
    """
    controller = _timing_controller(tmp_path)
    controller._cache_ram_cap_bytes = 4_000_000
    cache = controller._frame_cache
    cache.set_total_frames(Path("c.mp4"), total=120)
    cache._max_cache_bytes = 4_000_000
    cache.put(0, np.zeros((512, 512), dtype=np.uint8))  # 262 KB -> 2 MB trim target

    assert cache.capacity_frames() == 7  # half of 4 MB is the trim target
    assert controller._prefetch_target_frames() == 7


def test_adaptive_batch_grows_when_decode_keeps_up(qapp, tmp_path) -> None:
    """2 ms/frame against a 33.3 ms interval: one worker stays ahead, so runs may grow."""
    controller = _timing_controller(tmp_path, batch_size=4)

    controller._on_prefetch_decode_timing(7, count=4, ms=8.0)

    assert controller._prefetch_ema_decode_ms == pytest.approx(2.0)
    assert controller._adaptive_batch_size == 6


def test_adaptive_batch_shrinks_when_decode_falls_behind(qapp, tmp_path) -> None:
    """40 ms/frame against a 33.3 ms interval: decode cannot keep up, so runs shorten."""
    controller = _timing_controller(tmp_path, batch_size=16)

    controller._on_prefetch_decode_timing(7, count=2, ms=80.0)

    assert controller._prefetch_ema_decode_ms == pytest.approx(40.0)
    assert controller._adaptive_batch_size == 15


def test_adaptive_batch_holds_inside_the_hysteresis_band(qapp, tmp_path) -> None:
    """Between half an interval and a full interval per frame the size must not move."""
    controller = _timing_controller(tmp_path, batch_size=8)

    controller._on_prefetch_decode_timing(7, count=4, ms=80.0)  # 20 ms/frame

    assert controller._adaptive_batch_size == 8


def test_adaptive_batch_growth_is_capped(qapp, tmp_path) -> None:
    """One run must not hold the decode gate so long that a scroll waits for it."""
    controller = _timing_controller(tmp_path, batch_size=32)

    controller._on_prefetch_decode_timing(7, count=8, ms=1.0)

    assert controller._adaptive_batch_size == 32


def test_adaptive_batch_shrink_stops_at_the_slow_decode_floor(qapp, tmp_path) -> None:
    """Decode slower than playback shrinks runs, but only down to a few frames.

    A run delivers its pixels after the whole batch is decoded, so long runs delay the
    frame nearest the playhead; the floor keeps shrinking from bringing token runs back.
    """
    controller = _timing_controller(tmp_path, batch_size=8)

    for _ in range(12):
        controller._on_prefetch_decode_timing(7, count=1, ms=500.0)  # 500 ms/frame

    assert controller._min_prefetch_batch() == 4
    assert controller._adaptive_batch_size == 4


def test_round_trip_floor_applies_while_decode_keeps_up(qapp, tmp_path) -> None:
    """A size shrunk during a slow patch must not keep producing 1-2 frame runs."""
    controller = _timing_controller(tmp_path, batch_size=8)
    controller._adaptive_batch_size = 2

    controller._on_prefetch_decode_timing(7, count=8, ms=8.0)  # 1 ms/frame

    assert controller._min_prefetch_batch() == 8
    assert max(controller._min_prefetch_batch(), controller._adaptive_batch_size) == 8


def test_decode_timing_ignores_a_superseded_request(qapp, tmp_path) -> None:
    """A stale worker must not steer the batch size of the prefetch that replaced it."""
    controller = _timing_controller(tmp_path, batch_size=8)
    controller._prefetch_request_id = 9

    controller._on_prefetch_decode_timing(7, count=4, ms=8.0)

    assert controller._prefetch_ema_decode_ms == 0.0
    assert controller._adaptive_batch_size == 8


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


# ── Cache sizing for the loaded cine ──────────────────────────────────────────────


def _frame_720p_rgb() -> np.ndarray:
    return np.zeros((720, 1280, 3), dtype=np.uint8)  # 2.76 MB, one 720p RGB frame


def test_tune_playback_cache_grows_budget_and_window(qapp, tmp_path) -> None:
    """A flat 64 MB budget is 0.36 s of 720p RGB; the target needs room for a full second."""
    controller = AppController()
    controller._cache_ram_cap_bytes = 512 * 1024 * 1024
    cache = controller._frame_cache
    cache.set_total_frames(tmp_path / "c.dcm", total=120)
    cache.put(0, _frame_720p_rgb())

    controller._tune_playback_cache(30)

    frame_bytes = 720 * 1280 * 3
    # x2 because the emergency trim stops at half the budget.
    assert cache.memory_budget == cache.budget_for_frames(30) == 2 * 30 * frame_bytes
    assert cache.evict_window == 30
    assert controller._prefetch_target_frames() == 30


def test_tune_playback_cache_holds_a_short_cine_completely(qapp, tmp_path) -> None:
    """A 60-frame cine is worth caching whole: loop, rewind and scrub then never re-decode."""
    controller = AppController()
    controller._cache_ram_cap_bytes = 512 * 1024 * 1024
    cache = controller._frame_cache
    cache.set_total_frames(tmp_path / "c.dcm", total=60)
    cache.put(0, _frame_720p_rgb())

    controller._tune_playback_cache(30)

    assert cache.memory_budget == cache.budget_for_frames(60)
    assert cache.can_fit_full_cine()
    assert cache.evict_window == 60


def test_tune_playback_cache_short_cine_yields_to_the_ram_cap(qapp, tmp_path) -> None:
    """A machine that cannot afford the whole cine still gets the deepest buffer it can."""
    controller = AppController()
    controller._cache_ram_cap_bytes = 80 * 1024 * 1024
    cache = controller._frame_cache
    cache.set_total_frames(tmp_path / "c.dcm", total=60)
    cache.put(0, _frame_720p_rgb())

    controller._tune_playback_cache(30)

    assert cache.memory_budget == 80 * 1024 * 1024
    assert not cache.can_fit_full_cine()
    assert controller._prefetch_target_frames() == cache.capacity_frames()


def test_tune_playback_cache_respects_the_ram_cap(qapp, tmp_path) -> None:
    """The share of available RAM taken at startup is a hard ceiling."""
    controller = AppController()
    controller._cache_ram_cap_bytes = 40 * 1024 * 1024
    cache = controller._frame_cache
    cache.set_total_frames(tmp_path / "c.dcm", total=120)
    cache.put(0, _frame_720p_rgb())

    controller._tune_playback_cache(30)

    assert cache.memory_budget == 40 * 1024 * 1024
    # 40 MB holds ~7 of these frames after the half-budget trim, so the target follows.
    assert controller._prefetch_target_frames() == cache.capacity_frames()


def test_tune_playback_cache_leaves_small_frames_alone(qapp, tmp_path) -> None:
    """A cine that already fits must not have its budget inflated."""
    controller = AppController()
    controller._cache_ram_cap_bytes = 512 * 1024 * 1024
    cache = controller._frame_cache
    before = cache.memory_budget
    cache.set_total_frames(tmp_path / "c.dcm", total=30)
    cache.put(0, np.zeros((64, 64), dtype=np.uint8))

    controller._tune_playback_cache(30)

    assert cache.memory_budget == before


# ── Leading-static scan: sampled comparison, exact for identical frames ───────────


def _scan_controller(tmp_path, frames: list) -> AppController:
    controller = AppController()
    path = tmp_path / "x.dcm"
    path.write_bytes(b"\x00")
    controller._frame_cache.set_total_frames(path, total=len(frames))
    for i, frame in enumerate(frames):
        if frame is not None:
            controller._frame_cache.put(i, frame)
    return controller


def test_leading_static_scan_counts_near_identical_frames(qapp, tmp_path) -> None:
    base = np.zeros((64, 64, 3), dtype=np.uint8)
    noisy = base.copy()
    noisy[10:14, 10:14] = 1  # mean |diff| over the frame ~0.004: visually frozen
    frames = [base, base.copy(), noisy, np.full((64, 64, 3), 200, dtype=np.uint8)]
    controller = _scan_controller(tmp_path, frames)

    leading = controller._detect_leading_static_from_cache(tmp_path / "x.dcm", total=len(frames))

    assert leading == 2


def test_leading_static_scan_promotes_before_subtracting(qapp, tmp_path) -> None:
    # 0 -> 255 must read as a maximal difference. Unsigned subtraction would wrap it
    # to 1 and silently swallow real motion at the head of the cine.
    frames = [
        np.zeros((32, 32, 3), dtype=np.uint8),
        np.zeros((32, 32, 3), dtype=np.uint8),
        np.full((32, 32, 3), 255, dtype=np.uint8),
    ]
    controller = _scan_controller(tmp_path, frames)

    leading = controller._detect_leading_static_from_cache(tmp_path / "x.dcm", total=len(frames))

    assert leading == 1


def test_leading_static_scan_handles_uint16(qapp, tmp_path) -> None:
    frames = [
        np.full((32, 32), 1000, dtype=np.uint16),
        np.full((32, 32), 1000, dtype=np.uint16),
        np.full((32, 32), 1001, dtype=np.uint16),  # diff 1.0 == threshold: still static
        np.full((32, 32), 60000, dtype=np.uint16),
    ]
    controller = _scan_controller(tmp_path, frames)

    leading = controller._detect_leading_static_from_cache(tmp_path / "x.dcm", total=len(frames))

    assert leading == 2


def test_leading_static_scan_stops_at_the_frame_cap(qapp, tmp_path) -> None:
    frames = [np.zeros((16, 16, 3), dtype=np.uint8) for _ in range(40)]
    controller = _scan_controller(tmp_path, frames)

    leading = controller._detect_leading_static_from_cache(tmp_path / "x.dcm", total=len(frames))

    assert leading == _LEADING_STATIC_MAX_FRAMES - 1


def test_leading_static_scan_stops_at_a_cache_gap(qapp, tmp_path) -> None:
    frames = [
        np.zeros((16, 16, 3), dtype=np.uint8),
        np.zeros((16, 16, 3), dtype=np.uint8),
        None,  # evicted: the scan must not look past the hole
        np.zeros((16, 16, 3), dtype=np.uint8),
    ]
    controller = _scan_controller(tmp_path, frames)

    leading = controller._detect_leading_static_from_cache(tmp_path / "x.dcm", total=len(frames))

    assert leading == 1


def test_leading_static_scan_needs_frame_zero(qapp, tmp_path) -> None:
    controller = AppController()
    path = tmp_path / "x.dcm"
    path.write_bytes(b"\x00")
    controller._frame_cache.set_total_frames(path, total=4)
    controller._frame_cache.put(1, np.zeros((16, 16, 3), dtype=np.uint8))

    assert controller._detect_leading_static_from_cache(path, total=4) == 0


# ── Event-driven playback wake-ups (replacing blind 16 ms polling) ────────────────


def _playing_controller(tmp_path, frames: int = 12, *, playing: bool = True) -> AppController:
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
    mp4 = tmp_path / "c.mp4"
    mp4.write_bytes(b"\x00")
    inst = _mp4_instance(mp4, frames=frames)
    controller._current_instance = inst
    controller._frame_cache.set_total_frames(mp4, frames)
    controller._state_manager.set_instance(inst, total_frames=frames, frame_time_ms=33.3)
    controller._state_manager._is_playing = playing
    controller._pending_decode_id = 0
    controller._pending_load_id = 0
    controller._prefetch_load_id = 0
    controller._leading_static_frames[mp4.resolve()] = 0
    return controller


def test_wake_playback_timer_arms_an_immediate_tick_while_polling(qapp, tmp_path) -> None:
    controller = _playing_controller(tmp_path)
    controller._reschedule_playback_timer(poll=True)
    assert controller._playback_poll_pending is True
    assert controller._timer.interval() == controller._playback_poll_interval_ms

    controller._wake_playback_timer()

    assert controller._timer.interval() == 1


def test_wake_playback_timer_stays_out_of_paced_playback(qapp, tmp_path) -> None:
    controller = _playing_controller(tmp_path)
    controller._reschedule_playback_timer()
    paced = controller._timer.interval()

    controller._wake_playback_timer()

    assert controller._playback_poll_pending is False
    assert controller._timer.interval() == paced


def test_wake_playback_timer_is_quiet_while_paused(qapp, tmp_path) -> None:
    controller = _playing_controller(tmp_path, playing=False)
    controller._playback_poll_pending = True
    controller._timer.setInterval(controller._playback_poll_interval_ms)

    controller._wake_playback_timer()

    assert controller._timer.interval() == controller._playback_poll_interval_ms


def test_batch_delivery_wakes_the_playback_timer(qapp, tmp_path) -> None:
    controller = _playing_controller(tmp_path)
    controller._prefetch_load_id = 5
    controller._reschedule_playback_timer(poll=True)
    controller._timer.setInterval(controller._playback_poll_interval_ms)

    controller._on_prefetch_batch_loaded(
        5,
        controller._current_instance.path,
        [(1, np.full((4, 4), 1, dtype=np.uint8))],
    )

    assert controller._frame_cache.is_loaded(1)
    assert controller._timer.interval() == 1


def test_leading_scan_delivery_wakes_the_playback_timer(qapp, tmp_path) -> None:
    controller = _playing_controller(tmp_path)
    controller._prefetch_load_id = 9
    controller._reschedule_playback_timer(poll=True)
    controller._timer.setInterval(controller._playback_poll_interval_ms)

    controller._on_leading_scan_batch_loaded(
        9,
        controller._current_instance.path.resolve(),
        controller._frame_cache.frame_count(),
        [(1, np.zeros((4, 4), dtype=np.uint8))],
    )

    assert controller._frame_cache.is_loaded(1)
    assert controller._timer.interval() == 1


def test_wake_up_before_the_cadence_does_not_advance_twice(qapp, tmp_path) -> None:
    controller = _playing_controller(tmp_path)
    for i in range(4):
        controller._frame_cache.put(i, np.full((4, 4), i, dtype=np.uint8))
    controller._state_manager.set_frame(0)
    controller._last_frame_shown_at = perf_counter()
    controller._reschedule_playback_timer(poll=True)

    controller._wake_playback_timer()
    controller._advance_playback()

    # The tick only re-aims the timer: the next frame is still not due.
    assert controller.state_manager.snapshot.current_frame_index == 0
    assert controller._timer.interval() > 1


def test_warmup_completion_starts_the_cadence_immediately(qapp, tmp_path) -> None:
    controller = _playing_controller(tmp_path)
    for i in range(4):
        controller._frame_cache.put(i, np.full((4, 4), i, dtype=np.uint8))
    controller._state_manager.set_frame(0)
    controller._playback_warmup_pending = True
    controller._last_frame_shown_at = perf_counter() - 1.0
    controller._reschedule_playback_timer(poll=True)

    controller._advance_playback()

    assert controller._playback_warmup_pending is False
    assert controller._playback_poll_pending is True
    assert controller._timer.interval() == 1

    controller._advance_playback()

    # No extra frame interval is paid for the buffer that just finished filling.
    assert controller.state_manager.snapshot.current_frame_index == 1


def test_pause_clears_the_poll_flag(qapp, tmp_path) -> None:
    controller = _playing_controller(tmp_path)
    controller._reschedule_playback_timer(poll=True)
    assert controller._playback_poll_pending is True

    controller.set_playing(False)

    assert controller._playback_poll_pending is False
    assert controller._playback_warmup_pending is False


# ── Deferred GC: throttled, and never while the cadence is running ────────────────


class _SyncThread:
    """Runs the target inline so a test never races a real background thread."""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._target = target
        self._args = tuple(args)
        self._kwargs = kwargs or {}

    def start(self) -> None:
        self._target(*self._args, **self._kwargs)


@pytest.fixture
def gc_recorder(monkeypatch):
    passes: list[tuple] = []
    monkeypatch.setattr(threading, "Thread", _SyncThread)
    monkeypatch.setattr(gc, "collect", lambda *a, **k: passes.append(a or (2,)))
    return passes


# Assertions key off `_last_gc_collect_at`, which is stamped only when this controller
# actually dispatches a collection: other controllers left over from earlier tests in this
# module can drain their own worker sets (and collect) while the event loop turns.


def test_deferred_gc_is_skipped_while_playing(qapp, tmp_path, gc_recorder) -> None:
    controller = _playing_controller(tmp_path)

    controller._deferred_gc_collect()

    assert controller._last_gc_collect_at == 0.0


def test_deferred_gc_throttles_between_drains(qapp, tmp_path, gc_recorder) -> None:
    controller = _playing_controller(tmp_path, playing=False)

    controller._deferred_gc_collect()
    first = controller._last_gc_collect_at
    controller._deferred_gc_collect()

    assert first > 0.0
    assert controller._last_gc_collect_at == first
    assert gc_recorder[-1] == (0,)  # generation 0 only, not a full collection

    controller._last_gc_collect_at -= _GC_MIN_INTERVAL_SEC + 0.1
    controller._deferred_gc_collect()

    assert controller._last_gc_collect_at > first


def test_deferred_gc_runs_when_paused_again(qapp, tmp_path, gc_recorder) -> None:
    controller = _playing_controller(tmp_path)
    controller._deferred_gc_collect()
    assert controller._last_gc_collect_at == 0.0

    controller._state_manager._is_playing = False
    controller._deferred_gc_collect()

    assert controller._last_gc_collect_at > 0.0
    assert gc_recorder[-1] == (0,)
