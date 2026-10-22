"""Real DICOM file FPS benchmark.

Loads actual DICOM frames and measures playback pipeline throughput.

Run:  ECHO_BENCH=1 pytest tests/bench/test_playback_real_dicom_bench.py -v --benchmark-only
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pydicom
import pytest

from echo_personal_tool.application.frame_cache import FrameCache

_BENCH = pytest.mark.skipif(
    os.environ.get("ECHO_BENCH", "") != "1",
    reason="Set ECHO_BENCH=1 to run benchmarks",
)

_REAL_DICOM = Path(
    os.environ.get(
        "ECHO_REAL_DICOM",
        "",
    )
)


def _load_real_frames() -> tuple[np.ndarray, dict]:
    """Load all frames from real DICOM file."""
    ds = pydicom.dcmread(str(_REAL_DICOM), force=True)
    n_frames = int(str(ds.get("NumberOfFrames", 1)))
    rows = int(str(ds.get("Rows", 0)))
    cols = int(str(ds.get("Columns", 0)))
    frame_time = float(str(ds.get("FrameTime", 33.3)))
    pixel_array = ds.pixel_array  # (n_frames, rows, cols) or (rows, cols)
    if pixel_array.ndim == 2:
        pixel_array = pixel_array[np.newaxis, ...]
    # Ensure contiguous uint16
    frames = np.ascontiguousarray(pixel_array, dtype=np.uint16)
    info = {
        "n_frames": n_frames,
        "rows": rows,
        "cols": cols,
        "frame_time_ms": frame_time,
        "fps": 1000.0 / frame_time if frame_time > 0 else 0,
    }
    return frames, info


@pytest.fixture(scope="module")
def real_frames():
    if not _REAL_DICOM.exists():
        pytest.skip(f"Real DICOM not found: {_REAL_DICOM}")
    return _load_real_frames()


# ── Hot cache playback (all frames pre-loaded) ─────────────────────


@_BENCH
def test_bench_real_fps_hot_cache(benchmark, real_frames) -> None:
    """Full 124-frame playback loop with real DICOM data."""
    frames, info = real_frames
    n = info["n_frames"]
    cache = FrameCache(evict_window=n + 10)
    cache.load(_REAL_DICOM, frames)

    def _tick() -> None:
        for i in range(n):
            cache.set_current(i)
            _ = cache.get(i)

    benchmark(_tick)


# ── With pin/unpin (mirrors _emit_cached_frame) ────────────────────


@_BENCH
def test_bench_real_fps_pin_cycle(benchmark, real_frames) -> None:
    """Playback with pin/unpin per frame — realistic overhead."""
    frames, info = real_frames
    n = info["n_frames"]
    cache = FrameCache(evict_window=n + 10)
    cache.load(_REAL_DICOM, frames)
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


# ── Forward + backward (cine loop) ─────────────────────────────────


@_BENCH
def test_bench_real_fps_forward_backward(benchmark, real_frames) -> None:
    """Forward then backward — typical echo cine playback."""
    frames, info = real_frames
    n = info["n_frames"]
    cache = FrameCache(evict_window=n + 10)
    cache.load(_REAL_DICOM, frames)

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
def test_bench_real_fps_warmup_check(benchmark, real_frames) -> None:
    """loaded_ahead + is_loaded per tick — warmup gate simulation."""
    frames, info = real_frames
    n = info["n_frames"]
    cache = FrameCache(evict_window=n + 10)
    cache.load(_REAL_DICOM, frames)

    def _tick() -> None:
        for i in range(n):
            _ = cache.loaded_ahead(i)
            _ = cache.is_loaded((i + 1) % n)
            _ = cache.is_loaded((i + 2) % n)

    benchmark(_tick)


# ── Partial cache (simulates prefetch) ─────────────────────────────


@_BENCH
def test_bench_real_fps_partial_cache(benchmark, real_frames) -> None:
    """Only first 30 frames cached — simulates playback during prefetch."""
    frames, info = real_frames
    n = info["n_frames"]
    cache = FrameCache(evict_window=n + 10)
    # Only load first 30 frames
    cache.load(_REAL_DICOM, frames[:30])

    loaded_count = 0

    def _tick() -> None:
        nonlocal loaded_count
        for i in range(n):
            cache.set_current(i)
            if cache.is_loaded(i):
                _ = cache.get(i)
                loaded_count += 1

    benchmark(_tick)


# ── Single frame decode + cache put ────────────────────────────────


@_BENCH
def test_bench_real_single_frame_decode(benchmark, real_frames) -> None:
    """Decode one frame from real DICOM and put into cache."""
    frames, info = real_frames
    n = info["n_frames"]
    cache = FrameCache(evict_window=n + 10)
    cache.set_total_frames(_REAL_DICOM, total=n)

    frame_idx = n // 2  # middle frame
    frame_data = frames[frame_idx]

    def _decode_and_put() -> None:
        cache.put(frame_idx, frame_data)

    benchmark(_decode_and_put)
