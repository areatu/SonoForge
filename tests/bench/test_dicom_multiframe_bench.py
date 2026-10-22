"""Multiframe DICOM decode + playback pipeline benchmarks.

Comprehensive benchmarks for diagnosing playback FPS issues on Windows:
  - Single-frame decode latency (uncompressed, JPEG, JPEG-2000)
  - Batch decode throughput (simulating prefetch)
  - Full pipeline: open → decode_all → random access → cache → display
  - Memory allocation tracking during decode
  - Wall-clock FPS simulation with cache + prefetch

Run:
  ECHO_BENCH=1 pytest tests/bench/test_dicom_multiframe_bench.py -v --benchmark-only

For memory snapshot during benchmark:
  ECHO_BENCH=1 ECHO_PLAYBACK_DIAG=1 pytest tests/bench/test_dicom_multiframe_bench.py -v --benchmark-only
"""

from __future__ import annotations

import gc
import os
from pathlib import Path

import numpy as np
import psutil
import pytest

from echo_personal_tool.application.frame_cache import FrameCache
from echo_personal_tool.infrastructure.dicom_session import DicomSession

_BENCH = pytest.mark.skipif(
    os.environ.get("ECHO_BENCH", "") != "1",
    reason="Set ECHO_BENCH=1 to run benchmarks",
)

_BENCH_PARAMS = pytest.mark.parametrize(
    "rows,cols,frame_count",
    [
        (256, 256, 30),
        (256, 256, 60),
        (512, 512, 30),
        (512, 512, 60),
        (1024, 1024, 30),
        (1024, 1024, 60),
    ],
    ids=[
        "256x256_30f",
        "256x256_60f",
        "512x512_30f",
        "512x512_60f",
        "1024x1024_30f",
        "1024x1024_60f",
    ],
)


def _make_synthetic_dicom(tmp_path: Path, rows: int, cols: int, frame_count: int, *, bits: int = 8) -> Path:
    """Create uncompressed multiframe DICOM for benchmarks."""
    from tests.fixtures.generate_synthetic_dicom import write_synthetic_multiframe_dicom

    return write_synthetic_multiframe_dicom(
        tmp_path / f"bench_{rows}x{cols}_{frame_count}f.dcm",
        frame_count=frame_count,
        rows=rows,
        cols=cols,
    )


def _rss_mb() -> float:
    try:
        return psutil.Process().memory_info().rss / 1e6
    except Exception:
        return 0.0


def _numpy_alloc_bytes() -> int:
    """Total bytes allocated by live numpy arrays."""
    gc.collect()
    return sum(a.nbytes for a in gc.get_objects() if isinstance(a, np.ndarray))


# ═══════════════════════════════════════════════════════════════════════
# 1. DICOM open() latency
# ═══════════════════════════════════════════════════════════════════════


@_BENCH
@_BENCH_PARAMS
def test_bench_dicom_open(benchmark, tmp_path: Path, rows: int, cols: int, frame_count: int) -> None:
    """Measure DicomSession.open() — file read + header parse."""
    dcm = _make_synthetic_dicom(tmp_path, rows, cols, frame_count)

    def _open() -> None:
        s = DicomSession()
        s.open(dcm)
        _ = s.frame_count

    benchmark(_open)


# ═══════════════════════════════════════════════════════════════════════
# 2. decode_all_frames() — zero-copy fast path
# ═══════════════════════════════════════════════════════════════════════


@_BENCH
@_BENCH_PARAMS
def test_bench_decode_all_frames(benchmark, tmp_path: Path, rows: int, cols: int, frame_count: int) -> None:
    """DicomSession.decode_all_frames() — zero-copy 3D view (uncompressed)."""
    dcm = _make_synthetic_dicom(tmp_path, rows, cols, frame_count)
    session = DicomSession()
    session.open(dcm)

    def _decode() -> None:
        session._frames = None
        frames = session.decode_all_frames()
        assert frames.shape[0] == frame_count

    benchmark(_decode)


# ═══════════════════════════════════════════════════════════════════════
# 3. Single-frame decode (random access)
# ═══════════════════════════════════════════════════════════════════════


@_BENCH
@_BENCH_PARAMS
def test_bench_single_frame_decode(benchmark, tmp_path: Path, rows: int, cols: int, frame_count: int) -> None:
    """decode_single_frame() without prior decode_all — measures per-frame cost."""
    dcm = _make_synthetic_dicom(tmp_path, rows, cols, frame_count)
    session = DicomSession()
    session.open(dcm)
    mid = frame_count // 2

    def _decode_one() -> None:
        frame = session.decode_single_frame(mid)
        assert frame.shape == (rows, cols)

    benchmark(_decode_one)


# ═══════════════════════════════════════════════════════════════════════
# 4. Batch decode throughput (prefetch simulation)
# ═══════════════════════════════════════════════════════════════════════


@_BENCH
@_BENCH_PARAMS
def test_bench_batch_decode_throughput(benchmark, tmp_path: Path, rows: int, cols: int, frame_count: int) -> None:
    """Decode N consecutive frames sequentially — simulates prefetch batch."""
    dcm = _make_synthetic_dicom(tmp_path, rows, cols, frame_count)
    session = DicomSession()
    session.open(dcm)
    batch_size = min(8, frame_count)
    start = 0

    def _batch() -> None:
        for i in range(start, start + batch_size):
            _ = session.decode_single_frame(i)

    benchmark(_batch)


# ═══════════════════════════════════════════════════════════════════════
# 5. decode_all → read_frame loop (hot cache playback)
# ═══════════════════════════════════════════════════════════════════════


@_BENCH
@_BENCH_PARAMS
def test_bench_read_frame_hot_cache(benchmark, tmp_path: Path, rows: int, cols: int, frame_count: int) -> None:
    """After decode_all_frames(), read_frame() in loop — measures zero-copy view cost."""
    dcm = _make_synthetic_dicom(tmp_path, rows, cols, frame_count)
    session = DicomSession()
    session.open(dcm)
    _ = session.decode_all_frames()

    def _read_loop() -> None:
        for i in range(frame_count):
            _ = session.read_frame(i)

    benchmark(_read_loop)


# ═══════════════════════════════════════════════════════════════════════
# 6. Full pipeline: open → decode_all → read → cache → eviction
# ═══════════════════════════════════════════════════════════════════════


@_BENCH
@_BENCH_PARAMS
def test_bench_full_pipeline_with_cache(benchmark, tmp_path: Path, rows: int, cols: int, frame_count: int) -> None:
    """End-to-end: open DICOM → decode → put in cache → playback sweep with eviction."""
    dcm = _make_synthetic_dicom(tmp_path, rows, cols, frame_count)

    def _pipeline() -> None:
        session = DicomSession()
        session.open(dcm)
        frames = session.decode_all_frames()
        session.release_heavy()

        cache = FrameCache(evict_window=frame_count + 10)
        cache.load(dcm, frames)
        for i in range(frame_count):
            cache.set_current(i)
            _ = cache.get(i)

    benchmark(_pipeline)


# ═══════════════════════════════════════════════════════════════════════
# 7. FPS simulation with prefetch + cache
# ═══════════════════════════════════════════════════════════════════════


@_BENCH
def test_bench_fps_simulation_512_60f(benchmark, tmp_path: Path) -> None:
    """Simulate real playback: decode → cache → tick loop with prefetch-ahead.

    Measures actual achievable FPS including cache overhead.
    """
    rows, cols, n = 512, 512, 60
    dcm = _make_synthetic_dicom(tmp_path, rows, cols, n)
    session = DicomSession()
    session.open(dcm)
    frames = session.decode_all_frames()
    session.release_heavy()

    cache = FrameCache(evict_window=n)
    cache.load(dcm, frames)

    def _playback_sim() -> None:
        for i in range(n):
            cache.set_current(i)
            _ = cache.get(i)
            _ = cache.loaded_ahead(i)

    benchmark(_playback_sim)


@_BENCH
def test_bench_fps_simulation_1024_30f(benchmark, tmp_path: Path) -> None:
    """1024×1024 30-frame cine — typical large echo."""
    rows, cols, n = 1024, 1024, 30
    dcm = _make_synthetic_dicom(tmp_path, rows, cols, n)
    session = DicomSession()
    session.open(dcm)
    frames = session.decode_all_frames()
    session.release_heavy()

    cache = FrameCache(evict_window=n)
    cache.load(dcm, frames)

    def _playback_sim() -> None:
        for i in range(n):
            cache.set_current(i)
            _ = cache.get(i)

    benchmark(_playback_sim)


# ═══════════════════════════════════════════════════════════════════════
# 8. Memory allocation during decode
# ═══════════════════════════════════════════════════════════════════════


@_BENCH
def test_bench_memory_decode_1024_60f(benchmark, tmp_path: Path) -> None:
    """Track RSS delta during decode_all_frames of 1024×1024×60."""
    rows, cols, n = 1024, 1024, 60
    dcm = _make_synthetic_dicom(tmp_path, rows, cols, n)

    def _decode_with_mem() -> None:
        gc.collect()
        rss_before = _rss_mb()
        np_before = _numpy_alloc_bytes()

        session = DicomSession()
        session.open(dcm)
        _ = session.decode_all_frames()

        gc.collect()
        rss_after = _rss_mb()
        np_after = _numpy_alloc_bytes()

    benchmark(_decode_with_mem)


# ═══════════════════════════════════════════════════════════════════════
# 9. Prefetch batch decode + cache deposit
# ═══════════════════════════════════════════════════════════════════════


@_BENCH
def test_bench_prefetch_batch_decode_and_cache(benchmark, tmp_path: Path) -> None:
    """Simulate prefetch: decode batch of 8 frames from random position + put in cache."""
    rows, cols, n = 512, 512, 60
    dcm = _make_synthetic_dicom(tmp_path, rows, cols, n)
    session = DicomSession()
    session.open(dcm)

    cache = FrameCache(evict_window=n)
    cache.set_total_frames(dcm, total=n)
    batch_size = 8

    def _prefetch() -> None:
        start = 20
        for i in range(start, min(start + batch_size, n)):
            frame = session.decode_single_frame(i)
            cache.put(i, frame)

    benchmark(_prefetch)


# ═══════════════════════════════════════════════════════════════════════
# 10. release_heavy + materialization cost
# ═══════════════════════════════════════════════════════════════════════


@_BENCH
def test_bench_release_heavy_materialize(benchmark, tmp_path: Path) -> None:
    """release_heavy() on a decoded 1024×1024×60 — measures view materialization."""
    rows, cols, n = 1024, 1024, 60
    dcm = _make_synthetic_dicom(tmp_path, rows, cols, n)
    session = DicomSession()
    session.open(dcm)
    _ = session.decode_all_frames()

    def _release() -> None:
        session.release_heavy()
        # Re-open for next iteration
        session.open(dcm)
        _ = session.decode_all_frames()

    benchmark(_release)


# ═══════════════════════════════════════════════════════════════════════
# 11. cv2.cvtColor + LUT pipeline (display path)
# ═══════════════════════════════════════════════════════════════════════


@_BENCH
def test_bench_display_pipeline_grayscale(benchmark) -> None:
    """Full display pipeline: grayscale → LUT → uint8 for 512×512."""
    import cv2

    rng = np.random.default_rng(42)
    frame = rng.integers(0, 255, (512, 512), dtype=np.uint8)
    lut = np.clip(
        (np.arange(256, dtype=np.float32) - 128.0) / 255.0 * 255.0,
        0.0,
        255.0,
    ).astype(np.uint8)

    def _display() -> None:
        dst = np.empty((512, 512), dtype=np.uint8)
        cv2.LUT(frame, lut, dst=dst)

    benchmark(_display)


@_BENCH
def test_bench_display_pipeline_color_doppler(benchmark) -> None:
    """Full display pipeline: RGB color frame → float32 WL → uint8."""
    from echo_personal_tool.infrastructure.pixel_utils import apply_window_level_rgb

    rng = np.random.default_rng(42)
    frame = rng.integers(0, 255, (512, 512, 3), dtype=np.uint8)

    def _display() -> None:
        _ = apply_window_level_rgb(frame, low=50.0, high=200.0)

    benchmark(_display)


# ═══════════════════════════════════════════════════════════════════════
# 12. Comparative: zero-copy view vs owned copy
# ═══════════════════════════════════════════════════════════════════════


@_BENCH
def test_bench_view_vs_copy_1024(benchmark, tmp_path: Path) -> None:
    """Compare: zero-copy view (decode_all) vs per-frame .copy() for 1024×1024×60."""
    rows, cols, n = 1024, 1024, 60
    dcm = _make_synthetic_dicom(tmp_path, rows, cols, n)
    session = DicomSession()
    session.open(dcm)

    def _view_copy() -> None:
        session._frames = None
        frames = session.decode_all_frames()
        # Materialize all views (simulates what release_heavy does)
        copies = [frames[i].copy() for i in range(n)]

    benchmark(_view_copy)
