"""Viewer performance benchmarks (Phase 0).

Run explicitly:
  ECHO_BENCH=1 pytest tests/bench/test_viewer_perf.py -v --benchmark-only

Baseline table (512×512 uint16, Linux dev, 2026-07-02, pytest-benchmark):
| Metric | Before (reference_wl path) | After (apply_wl_lut) | Target |
|--------|---------------------------|----------------------|--------|
| W/L p50 | ~8.4 ms | ~4.0 ms | <3 ms |
| W/L mean | ~10.7 ms | ~4.1 ms | <5 ms |
| FrameCache get | ~0.10 µs | ~0.10 µs | <0.1 ms |
| FrameCache evict sweep (200 frames) | ~2.0 µs | ~2.0 µs | <1 ms |

Update this table when re-running on reference hardware.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np
import pytest

from echo_personal_tool.application.frame_cache import FrameCache
from echo_personal_tool.infrastructure.pixel_utils import (
    apply_wl_lut,
    reference_wl_display_uint8,
)

_BENCH = pytest.mark.skipif(
    os.environ.get("ECHO_BENCH", "") != "1",
    reason="Set ECHO_BENCH=1 to run performance benchmarks",
)


def _legacy_wl_path(frame: np.ndarray) -> np.ndarray:
    """Simulate pre-LUT CPU path (float percentile + linear map)."""
    return reference_wl_display_uint8(
        frame,
        dr_low_pct=0.0,
        dr_high_pct=100.0,
        window_scale=0.8,
        level_offset=0.0,
    )


@pytest.fixture
def uint16_frame() -> np.ndarray:
    rng = np.random.default_rng(0)
    return rng.integers(0, 65535, (512, 512), dtype=np.uint16)


@_BENCH
def test_bench_wl_lut(benchmark, uint16_frame: np.ndarray) -> None:
    benchmark(
        apply_wl_lut,
        uint16_frame,
        dr_low_pct=0.0,
        dr_high_pct=100.0,
        window_scale=0.8,
        level_offset=0.0,
    )


@_BENCH
def test_bench_wl_legacy(benchmark, uint16_frame: np.ndarray) -> None:
    benchmark(_legacy_wl_path, uint16_frame)


@_BENCH
def test_bench_frame_cache_get(benchmark, tmp_path: Path) -> None:
    frames = np.zeros((50, 64, 64), dtype=np.uint8)
    cache = FrameCache()
    cache.load(tmp_path / "c.dcm", frames)
    benchmark(lambda: cache.get(25))


@_BENCH
def test_bench_frame_cache_evict(benchmark, tmp_path: Path) -> None:
    n = 200
    frames = np.arange(n * 4 * 4, dtype=np.uint16).reshape(n, 4, 4)
    cache = FrameCache(evict_window=20)
    cache.load(tmp_path / "c.dcm", frames)

    def _evict_sweep() -> None:
        for i in range(0, n, 10):
            cache.set_current(i)

    benchmark(_evict_sweep)


def test_wl_lut_faster_than_legacy_sanity(uint16_frame: np.ndarray) -> None:
    """Quick sanity (runs in default suite): LUT not slower than legacy on tiny frame."""
    small = uint16_frame[:64, :64]
    t0 = time.perf_counter()
    for _ in range(5):
        _legacy_wl_path(small)
    legacy_ms = (time.perf_counter() - t0) * 1000
    t0 = time.perf_counter()
    for _ in range(5):
        apply_wl_lut(
            small,
            dr_low_pct=0.0,
            dr_high_pct=100.0,
            window_scale=0.8,
            level_offset=0.0,
        )
    lut_ms = (time.perf_counter() - t0) * 1000
    assert lut_ms <= legacy_ms * 1.5 + 1.0
