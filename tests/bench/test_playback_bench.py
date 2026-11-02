"""Playback pipeline benchmarks.

Measures: FPS simulation, prefetch batch latency, warmup timing,
double-next skip gain, small-loop full prefetch.

Run:  ECHO_BENCH=1 pytest tests/bench/test_playback_bench.py -v --benchmark-only
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from echo_personal_tool.application.frame_cache import FrameCache

_BENCH = pytest.mark.skipif(
    os.environ.get("ECHO_BENCH", "") != "1",
    reason="Set ECHO_BENCH=1 to run benchmarks",
)

_FRAME_SIZE = (64, 64)


def _make_frames(n: int, dtype: type = np.uint8) -> np.ndarray:
    rng = np.random.default_rng(42)
    return rng.integers(0, 255, (n, *_FRAME_SIZE), dtype=dtype)


# ── FPS simulation ──────────────────────────────────────────────────


@_BENCH
def test_bench_playback_fps_30_frame_loop(benchmark) -> None:
    """Simulate 30-frame playback loop: get frame, advance, repeat."""
    cache = FrameCache(evict_window=40)
    frames = _make_frames(30)
    cache.load(Path("/dev/null/cine.dcm"), frames)

    def _playback_loop() -> None:
        for i in range(30):
            cache.set_current(i)
            _ = cache.get(i)

    benchmark(_playback_loop)


@_BENCH
def test_bench_playback_fps_100_frame_loop(benchmark) -> None:
    """100-frame loop — simulates playback with prefetch (pre-loaded cache)."""
    cache = FrameCache(evict_window=100)
    frames = _make_frames(100)
    cache.load(Path("/dev/null/cine.dcm"), frames)

    def _playback_loop() -> None:
        for i in range(100):
            cache.set_current(i)
            _ = cache.get(i)

    benchmark(_playback_loop)


# ── Prefetch batch ──────────────────────────────────────────────────


@_BENCH
def test_bench_prefetch_batch_load(benchmark, tmp_path: Path) -> None:
    """Simulate prefetch: batch-put 8 frames into cache."""
    cache = FrameCache(evict_window=40)
    cache.set_total_frames(tmp_path / "c.dcm", total=200)
    frames_batch = _make_frames(8)

    def _prefetch_batch() -> None:
        for i in range(8):
            cache.put(i, frames_batch[i])

    benchmark(_prefetch_batch)


@_BENCH
def test_bench_small_loop_full_prefetch(benchmark, tmp_path: Path) -> None:
    """For cine ≤ 60 frames: prefetch all unloaded in one pass."""
    n = 45
    cache = FrameCache(evict_window=40)
    frames = _make_frames(n)
    cache.load(tmp_path / "c.dcm", frames)
    cache.set_current(0)

    def _full_prefetch() -> None:
        unloaded = [i for i in range(n) if not cache.is_loaded(i)]
        for i in unloaded:
            pass  # simulate: would decode and put

    benchmark(_full_prefetch)


# ── Warmup gate ─────────────────────────────────────────────────────


@_BENCH
def test_bench_warmup_loaded_ahead_count(benchmark, tmp_path: Path) -> None:
    """Count loaded frames ahead — called every tick during warmup."""
    n = 60
    cache = FrameCache(evict_window=40)
    frames = _make_frames(n)
    cache.load(tmp_path / "c.dcm", frames)

    def _count_ahead() -> None:
        for i in range(0, n, 5):
            _ = cache.loaded_ahead(i)

    benchmark(_count_ahead)


# ── Double-next skip ────────────────────────────────────────────────


@_BENCH
def test_bench_double_next_skip_check(benchmark, tmp_path: Path) -> None:
    """Check is_loaded for next and next+1 — double-next skip logic."""
    n = 60
    cache = FrameCache(evict_window=40)
    frames = _make_frames(n)
    cache.load(tmp_path / "c.dcm", frames)
    cache.set_current(30)

    def _double_next_check() -> None:
        for i in range(30, 58):
            next_idx = (i + 1) % n
            next_next = (next_idx + 1) % n
            _ = cache.is_loaded(next_idx)
            _ = cache.is_loaded(next_next)

    benchmark(_double_next_check)
