"""End-to-end playback FPS benchmarks.

Simulates the full _advance_playback tick cycle from app_controller.py
without Qt dependencies. Measures the actual per-frame overhead that
determines whether playback can sustain target FPS.

Pipeline simulated per tick:
  1. State snapshot (dataclass copy)
  2. Frame cache: is_loaded(next) → set_current → get → pin/unpin
  3. Prefetch check: loaded_ahead + nearest_loaded_ahead
  4. Optional: resolve_cine_segment_roi_xyxy (ROI computation)

Run:  ECHO_BENCH=1 pytest tests/bench/test_playback_e2e_bench.py -v --benchmark-only
"""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path
from typing import NamedTuple

import numpy as np
import pytest

from echo_personal_tool.application.frame_cache import FrameCache
from echo_personal_tool.domain.services.segment_roi import resolve_cine_segment_roi_xyxy

_BENCH = pytest.mark.skipif(
    os.environ.get("ECHO_BENCH", "") != "1",
    reason="Set ECHO_BENCH=1 to run benchmarks",
)

_SIZES = {
    "256x256": (256, 256),
    "512x512": (512, 512),
}


def _make_frames(n: int, size: tuple[int, int], dtype: type = np.uint16) -> np.ndarray:
    rng = np.random.default_rng(42)
    return rng.integers(0, 65535, (n, *size), dtype=dtype)


class _FakeState(NamedTuple):
    current_frame_index: int
    total_frames: int
    is_playing: bool
    frame_time_ms: float


def _make_state(idx: int, total: int, playing: bool = True, ft: float = 33.3) -> _FakeState:
    return _FakeState(current_frame_index=idx, total_frames=total, is_playing=playing, frame_time_ms=ft)


# ── Full tick: hot cache, 512×512 (typical echo cine) ──────────────


@_BENCH
def test_bench_e2e_tick_512(benchmark) -> None:
    """Full tick cycle: state snapshot → cache lookup → set_current → get → pin/unpin."""
    n = 60
    frames = _make_frames(n, _SIZES["512x512"])
    cache = FrameCache(evict_window=n + 10)
    cache.load(Path("/dev/null/cine.dcm"), frames)

    def _tick() -> None:
        for i in range(n):
            state = _make_state(i, n)
            next_idx = (state.current_frame_index + 1) % state.total_frames
            if cache.is_loaded(next_idx):
                cache.set_current(next_idx)
                _ = cache.get(next_idx)
                if i > 0:
                    cache.unpin(i - 1)
                cache.pin(next_idx)

    benchmark(_tick)


# ── Full tick with prefetch buffer check ────────────────────────────


@_BENCH
def test_bench_e2e_tick_with_prefetch_check(benchmark) -> None:
    """Tick + loaded_ahead + nearest_loaded_ahead + is_loaded (realistic warmup gate)."""
    n = 60
    frames = _make_frames(n, _SIZES["512x512"])
    cache = FrameCache(evict_window=n + 10)
    cache.load(Path("/dev/null/cine.dcm"), frames)

    prefetch_radius = 10
    min_buffer = 5

    def _tick() -> None:
        for i in range(n):
            state = _make_state(i, n)
            current = state.current_frame_index
            next_idx = (current + 1) % state.total_frames

            if cache.is_loaded(next_idx):
                cache.set_current(next_idx)
                _ = cache.get(next_idx)
                if i > 0:
                    cache.unpin(i - 1)
                cache.pin(next_idx)

                ahead = cache.loaded_ahead(next_idx)
                if ahead < min_buffer:
                    _ = cache.nearest_loaded_ahead(next_idx)
                    _ = cache.is_loaded((next_idx + 1) % n)
                    _ = cache.is_loaded((next_idx + 2) % n)

    benchmark(_tick)


# ── Full tick with ROI computation ──────────────────────────────────


@_BENCH
def test_bench_e2e_tick_with_roi_compute(benchmark) -> None:
    """Tick + resolve_cine_segment_roi_xyxy per frame (cine ROI path)."""
    n = 60
    frames = _make_frames(n, _SIZES["512x512"])
    cache = FrameCache(evict_window=n + 10)
    cache.load(Path("/dev/null/cine.dcm"), frames)

    roi_cache: dict[int, tuple[float, float, float, float] | None] = {}

    def _tick() -> None:
        for i in range(n):
            state = _make_state(i, n)
            next_idx = (state.current_frame_index + 1) % state.total_frames
            if cache.is_loaded(next_idx):
                cache.set_current(next_idx)
                pixels = cache.get(next_idx)
                if i > 0:
                    cache.unpin(i - 1)
                cache.pin(next_idx)
                if next_idx not in roi_cache:
                    roi_cache[next_idx] = resolve_cine_segment_roi_xyxy(pixels)

    benchmark(_tick)


# ── Forward + backward with full tick (cine loop) ───────────────────


@_BENCH
def test_bench_e2e_forward_backward(benchmark) -> None:
    """Forward 30 + backward 30 with full tick — typical cine loop."""
    n = 30
    frames = _make_frames(n, _SIZES["512x512"])
    cache = FrameCache(evict_window=n + 10)
    cache.load(Path("/dev/null/cine.dcm"), frames)

    def _tick() -> None:
        prev = 0
        for i in range(n):
            cache.set_current(i)
            _ = cache.get(i)
            if prev != i:
                cache.unpin(prev)
            cache.pin(i)
            prev = i
        for i in range(n - 1, -1, -1):
            cache.set_current(i)
            _ = cache.get(i)
            if prev != i:
                cache.unpin(prev)
            cache.pin(i)
            prev = i

    benchmark(_tick)


# ── Large cine with full tick ───────────────────────────────────────


@_BENCH
def test_bench_e2e_large_cine_200(benchmark) -> None:
    """200-frame cine, full tick — large study playback."""
    n = 200
    frames = _make_frames(n, _SIZES["256x256"])
    cache = FrameCache(evict_window=n + 10)
    cache.load(Path("/dev/null/cine.dcm"), frames)

    def _tick() -> None:
        prev = 0
        for i in range(n):
            state = _make_state(i, n)
            next_idx = (state.current_frame_index + 1) % state.total_frames
            if cache.is_loaded(next_idx):
                cache.set_current(next_idx)
                _ = cache.get(next_idx)
                if prev != next_idx:
                    cache.unpin(prev)
                cache.pin(next_idx)
                prev = next_idx

    benchmark(_tick)


# ── Lag-skip simulation (cache miss + skip to nearest) ──────────────


@_BENCH
def test_bench_e2e_lag_skip_sim(benchmark) -> None:
    """Simulate lag-skip: next frame missing, skip to nearest loaded ahead."""
    n = 60
    frames = _make_frames(n, _SIZES["512x512"])
    cache = FrameCache(evict_window=n + 10)
    # Only load even frames (skip odd = simulating decode lag)
    cache.load(Path("/dev/null/cine.dcm"), frames[::2] * 1)  # noqa: avoid copy warning
    cache.clear()
    cache.set_total_frames(Path("/dev/null/cine.dcm"), total=n)
    for i in range(0, n, 2):
        cache.put(i, frames[i])

    def _tick() -> None:
        for i in range(0, n - 1):
            next_idx = (i + 1) % n
            if cache.is_loaded(next_idx):
                cache.set_current(next_idx)
                _ = cache.get(next_idx)
            else:
                skip_to = cache.nearest_loaded_ahead(i)
                if skip_to is not None:
                    cache.set_current(skip_to)
                    _ = cache.get(skip_to)

    benchmark(_tick)


# ── 256×256 baseline comparison ─────────────────────────────────────


@_BENCH
def test_bench_e2e_tick_256(benchmark) -> None:
    """Full tick at 256×256 — smaller frame baseline."""
    n = 60
    frames = _make_frames(n, _SIZES["256x256"])
    cache = FrameCache(evict_window=n + 10)
    cache.load(Path("/dev/null/cine.dcm"), frames)

    def _tick() -> None:
        for i in range(n):
            state = _make_state(i, n)
            next_idx = (state.current_frame_index + 1) % state.total_frames
            if cache.is_loaded(next_idx):
                cache.set_current(next_idx)
                _ = cache.get(next_idx)
                if i > 0:
                    cache.unpin(i - 1)
                cache.pin(next_idx)

    benchmark(_tick)


# ── Double-next skip simulation ─────────────────────────────────────


@_BENCH
def test_bench_e2e_double_next_skip(benchmark) -> None:
    """Simulate double-next skip: next missing but next+1 loaded."""
    n = 60
    frames = _make_frames(n, _SIZES["512x512"])
    cache = FrameCache(evict_window=n + 10)
    cache.load(Path("/dev/null/cine.dcm"), frames)

    # Remove every other frame to force double-next path
    for i in range(1, n, 2):
        if i in cache._frame_store:
            del cache._frame_store[i]
            cache._sorted_keys.remove(i)

    def _tick() -> None:
        for i in range(0, n - 2):
            next_idx = (i + 1) % n
            if cache.is_loaded(next_idx):
                cache.set_current(next_idx)
                _ = cache.get(next_idx)
            else:
                next_next = (next_idx + 1) % n
                if cache.is_loaded(next_next):
                    cache.set_current(next_next)
                    _ = cache.get(next_next)

    benchmark(_tick)
