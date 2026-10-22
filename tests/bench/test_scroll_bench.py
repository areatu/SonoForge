"""Scroll / navigation benchmarks.

Measures: single frame latency, cache miss penalty, directional prefetch hit rate.

Run:  ECHO_BENCH=1 pytest tests/bench/test_scroll_bench.py -v --benchmark-only
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


# ── Single frame latency ────────────────────────────────────────────


@_BENCH
def test_bench_scroll_single_frame_hit(benchmark, tmp_path: Path) -> None:
    """Scroll forward by 1 frame — all frames in cache (best case)."""
    cache = FrameCache(evict_window=60)
    frames = _make_frames(100)
    cache.load(tmp_path / "c.dcm", frames)
    cache.set_current(50)

    def _scroll_one_frame() -> None:
        cache.set_current(51)
        _ = cache.get(51)

    benchmark(_scroll_one_frame)


@_BENCH
def test_bench_scroll_single_frame_miss(benchmark, tmp_path: Path) -> None:
    """Scroll to a frame outside cache window — forces eviction + miss."""
    cache = FrameCache(evict_window=20)
    frames = _make_frames(200)
    cache.load(tmp_path / "c.dcm", frames)
    cache.set_current(50)

    def _scroll_to_miss() -> None:
        cache.set_current(150)
        try:
            _ = cache.get(150)
        except RuntimeError:
            pass

    benchmark(_scroll_to_miss)


# ── Rapid scroll burst ──────────────────────────────────────────────


@_BENCH
def test_bench_scroll_rapid_forward_20(benchmark, tmp_path: Path) -> None:
    """20 consecutive forward scrolls — simulates wheel spinning."""
    cache = FrameCache(evict_window=40)
    frames = _make_frames(100)
    cache.load(tmp_path / "c.dcm", frames)
    cache.set_current(10)

    def _rapid_scroll() -> None:
        for i in range(10, 30):
            cache.set_current(i)

    benchmark(_rapid_scroll)


@_BENCH
def test_bench_scroll_rapid_backward_20(benchmark, tmp_path: Path) -> None:
    """20 consecutive backward scrolls."""
    cache = FrameCache(evict_window=40)
    frames = _make_frames(100)
    cache.load(tmp_path / "c.dcm", frames)
    cache.set_current(80)

    def _rapid_scroll_back() -> None:
        for i in range(80, 60, -1):
            cache.set_current(i)

    benchmark(_rapid_scroll_back)


# ── Directional prefetch hit rate ───────────────────────────────────


@_BENCH
def test_bench_directional_prefetch_forward(benchmark, tmp_path: Path) -> None:
    """loaded_ahead + nearest_loaded_ahead — forward prefetch query."""
    cache = FrameCache(evict_window=40)
    frames = _make_frames(100)
    cache.load(tmp_path / "c.dcm", frames)

    def _forward_query() -> None:
        for i in range(0, 100, 5):
            _ = cache.loaded_ahead(i)
            _ = cache.nearest_loaded_ahead(i)

    benchmark(_forward_query)


@_BENCH
def test_bench_directional_prefetch_backward(benchmark, tmp_path: Path) -> None:
    """loaded_before + nearest_loaded_before — backward prefetch query."""
    cache = FrameCache(evict_window=40)
    frames = _make_frames(100)
    cache.load(tmp_path / "c.dcm", frames)

    def _backward_query() -> None:
        for i in range(0, 100, 5):
            _ = cache.loaded_before(i)
            _ = cache.nearest_loaded_before(i)

    benchmark(_backward_query)
