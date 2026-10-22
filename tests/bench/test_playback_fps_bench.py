"""Playback FPS pipeline benchmarks.

Measures end-to-end throughput of the playback tick cycle:
  cache lookup → set_current → frame emit → prefetch check

This captures the real-world FPS bottleneck, unlike isolated cache benchmarks.

Run:  ECHO_BENCH=1 pytest tests/bench/test_playback_fps_bench.py -v --benchmark-only
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

_SIZES = {
    "64x64": (64, 64),
    "256x256": (256, 256),
    "512x512": (512, 512),
}


def _make_frames(n: int, size: tuple[int, int], dtype: type = np.uint16) -> np.ndarray:
    rng = np.random.default_rng(42)
    return rng.integers(0, 65535, (n, *size), dtype=dtype)


# ── Hot cache — all frames pre-loaded, no eviction ─────────────────


@_BENCH
def test_bench_fps_hot_cache_64(benchmark) -> None:
    """64×64, all cached — minimum tick overhead."""
    n = 60
    cache = FrameCache(evict_window=n + 10)
    frames = _make_frames(n, _SIZES["64x64"])
    cache.load(Path("/dev/null/cine.dcm"), frames)

    def _tick() -> None:
        for i in range(n):
            cache.set_current(i)
            _ = cache.get(i)
            _ = cache.loaded_ahead(i)

    benchmark(_tick)


@_BENCH
def test_bench_fps_hot_cache_256(benchmark) -> None:
    """256×256, all cached."""
    n = 60
    cache = FrameCache(evict_window=n + 10)
    frames = _make_frames(n, _SIZES["256x256"])
    cache.load(Path("/dev/null/cine.dcm"), frames)

    def _tick() -> None:
        for i in range(n):
            cache.set_current(i)
            _ = cache.get(i)
            _ = cache.loaded_ahead(i)

    benchmark(_tick)


@_BENCH
def test_bench_fps_hot_cache_512(benchmark) -> None:
    """512×512, all cached — typical echo cine."""
    n = 60
    cache = FrameCache(evict_window=n + 10)
    frames = _make_frames(n, _SIZES["512x512"])
    cache.load(Path("/dev/null/cine.dcm"), frames)

    def _tick() -> None:
        for i in range(n):
            cache.set_current(i)
            _ = cache.get(i)
            _ = cache.loaded_ahead(i)

    benchmark(_tick)


# ── Forward + backward playback ────────────────────────────────────


@_BENCH
def test_bench_fps_forward_backward(benchmark) -> None:
    """Forward 30, backward 30 — typical cine loop."""
    n = 30
    cache = FrameCache(evict_window=n + 10)
    frames = _make_frames(n, _SIZES["256x256"])
    cache.load(Path("/dev/null/cine.dcm"), frames)

    def _tick() -> None:
        for i in range(n):
            cache.set_current(i)
            _ = cache.get(i)
        for i in range(n - 1, -1, -1):
            cache.set_current(i)
            _ = cache.get(i)

    benchmark(_tick)


# ── Warmup check overhead ──────────────────────────────────────────


@_BENCH
def test_bench_fps_warmup_check(benchmark) -> None:
    """loaded_ahead + is_loaded checks per tick (warmup gate)."""
    n = 60
    cache = FrameCache(evict_window=n + 10)
    frames = _make_frames(n, _SIZES["256x256"])
    cache.load(Path("/dev/null/cine.dcm"), frames)

    def _tick() -> None:
        for i in range(n):
            _ = cache.loaded_ahead(i)
            _ = cache.is_loaded((i + 1) % n)
            _ = cache.is_loaded((i + 2) % n)

    benchmark(_tick)


# ── Large cine ─────────────────────────────────────────────────────


@_BENCH
def test_bench_fps_large_cine_200(benchmark) -> None:
    """200-frame cine, all cached — large study playback."""
    n = 200
    cache = FrameCache(evict_window=n + 10)
    frames = _make_frames(n, _SIZES["256x256"])
    cache.load(Path("/dev/null/cine.dcm"), frames)

    def _tick() -> None:
        for i in range(n):
            cache.set_current(i)
            _ = cache.get(i)

    benchmark(_tick)


# ── Pin/unpin cycle (real playback emits pin per frame) ────────────


@_BENCH
def test_bench_fps_pin_cycle(benchmark) -> None:
    """Simulates pin/unpin per frame — mirrors _emit_cached_frame."""
    n = 60
    cache = FrameCache(evict_window=n + 10)
    frames = _make_frames(n, _SIZES["256x256"])
    cache.load(Path("/dev/null/cine.dcm"), frames)
    cache.set_current(0)

    def _tick() -> None:
        prev = 0
        for i in range(n):
            cache.set_current(i)
            _ = cache.get(i)
            if prev != i:
                cache.unpin(prev)
            cache.pin(i)
            prev = i

    benchmark(_tick)


# ── FPS report benchmark ───────────────────────────────────────────


@_BENCH
def test_bench_fps_report_256(benchmark) -> None:
    """Report achieved FPS for 256×256 60-frame cine."""
    n = 60
    cache = FrameCache(evict_window=n + 10)
    frames = _make_frames(n, _SIZES["256x256"])
    cache.load(Path("/dev/null/cine.dcm"), frames)

    def _tick() -> None:
        for i in range(n):
            cache.set_current(i)
            _ = cache.get(i)

    benchmark(_tick)
