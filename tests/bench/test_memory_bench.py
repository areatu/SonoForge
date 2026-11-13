"""Memory usage benchmarks.

Measures: peak RAM for cine playback, FrameCache memory tracking,
zero-copy view lifetime, eviction memory reclamation.

Run:  ECHO_BENCH=1 pytest tests/bench/test_memory_bench.py -v --benchmark-only

These are informational benchmarks — they log memory deltas rather than
asserting hard limits (hardware-dependent).
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


def _mem_mb() -> float:
    """Current process RSS in MB (approximate)."""
    try:
        import psutil

        return psutil.Process().memory_info().rss / 1e6
    except ImportError:
        return 0.0


def _make_frames(n: int, h: int = 64, w: int = 64, dtype: type = np.uint8) -> np.ndarray:
    rng = np.random.default_rng(42)
    return rng.integers(0, 255, (n, h, w), dtype=dtype)


# ── Peak RAM for cine sizes ─────────────────────────────────────────


@_BENCH
def test_bench_mem_30_frame_cine(benchmark, tmp_path: Path) -> None:
    """Peak RSS delta for 30-frame cine in FrameCache."""
    n, h, w = 30, 256, 256
    frames = _make_frames(n, h, w, dtype=np.uint16)

    def _load_and_evict() -> None:
        cache = FrameCache(evict_window=40)
        cache.load(tmp_path / "c.dcm", frames)
        for i in range(n):
            cache.set_current(i)

    mem_before = _mem_mb()
    benchmark(_load_and_evict)
    mem_after = _mem_mb()
    delta = mem_after - mem_before
    if delta > 0:
        print(f"\n  RSS delta: {delta:.1f} MB")


@_BENCH
def test_bench_mem_200_frame_cine(benchmark, tmp_path: Path) -> None:
    """Peak RSS for 200-frame cine with active eviction."""
    n, h, w = 200, 128, 128
    frames = _make_frames(n, h, w, dtype=np.uint16)

    def _load_and_sweep() -> None:
        cache = FrameCache(evict_window=30)
        cache.load(tmp_path / "c.dcm", frames)
        for i in range(0, n, 3):
            cache.set_current(i)

    mem_before = _mem_mb()
    benchmark(_load_and_sweep)
    mem_after = _mem_mb()
    delta = mem_after - mem_before
    if delta > 0:
        print(f"\n  RSS delta: {delta:.1f} MB")


# ── FrameCache memory_bytes tracking ────────────────────────────────


@_BENCH
def test_bench_memory_bytes_tracking(benchmark, tmp_path: Path) -> None:
    """memory_bytes() call overhead — used for RAM warnings."""
    n = 100
    frames = _make_frames(n, 64, 64, dtype=np.uint16)
    cache = FrameCache(evict_window=30)
    cache.load(tmp_path / "c.dcm", frames)

    def _track() -> None:
        for i in range(0, n, 5):
            cache.set_current(i)
            _ = cache.memory_bytes()

    benchmark(_track)


# ── Zero-copy view vs heap allocation ──────────────────────────────


@_BENCH
def test_bench_zero_copy_view_lifetime(benchmark) -> None:
    """frombuffer view — stays alive as long as parent bytes exists."""
    raw = bytes(256 * 256)

    def _create_views() -> None:
        views = []
        for _ in range(100):
            v = np.frombuffer(raw, dtype=np.uint8).reshape(256, 256)
            views.append(v)
        # views keep raw alive via reference

    benchmark(_create_views)


@_BENCH
def test_bench_heap_copy_allocation(benchmark) -> None:
    """frombuffer + copy — independent heap allocation per frame."""
    raw = bytes(256 * 256)

    def _create_copies() -> None:
        copies = []
        for _ in range(100):
            v = np.frombuffer(raw, dtype=np.uint8).reshape(256, 256).copy()
            copies.append(v)

    benchmark(_create_copies)


# ── Eviction memory reclamation ────────────────────────────────────


@_BENCH
def test_bench_eviction_reclaims_memory(benchmark, tmp_path: Path) -> None:
    """Verify eviction reduces memory_bytes()."""
    n = 200
    frames = _make_frames(n, 128, 128, dtype=np.uint16)
    # Force eviction: with the default 2 GB budget the whole cine fits and
    # set_current() intentionally leaves it resident.
    cache = FrameCache(evict_window=20, max_cache_bytes=frames.nbytes // 2)
    cache.load(tmp_path / "c.dcm", frames)
    full_mem = cache.memory_bytes()

    def _evict_and_check() -> None:
        cache.set_current(100)
        current = cache.memory_bytes()
        assert current < full_mem
        assert cache.peak_memory_bytes() >= full_mem

    benchmark(_evict_and_check)


@_BENCH
def test_bench_twenty_tab_switches_plateau(tmp_path: Path) -> None:
    """RSS after 20 tab switches: peak per tab, plateau after workers finish.

    The unit suite proves the buffers are collectible; this benchmark records
    the process-level RSS and the cache's own high-water mark, which is the
    acceptance evidence for #545 on the machine that runs it.
    """
    rss_start = _mem_mb()
    peaks: list[int] = []

    def _one_tab(tab: int) -> None:
        frames = _make_frames(24, 256, 256, dtype=np.uint16)
        cache = FrameCache(evict_window=4, max_cache_bytes=1_500_000)
        cache.load(tmp_path / f"tab-{tab}.dcm", frames)
        cache.set_current(tab % 24)
        peaks.append(cache.peak_memory_bytes())
        cache.clear()
        del cache, frames

    for tab in range(20):
        _one_tab(tab)
    rss_end = _mem_mb()
    assert len(peaks) == 20
    print(
        f"\n  RSS: {rss_start:.1f} -> {rss_end:.1f} MB, "
        f"max per-tab cache peak {max(peaks) / 1e6:.1f} MB, "
        f"final cache peak {peaks[-1] / 1e6:.1f} MB"
    )
