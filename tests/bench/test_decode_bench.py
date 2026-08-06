"""Decode / cache benchmarks.

Measures: single frame decode, parallel batch, eviction cost, zero-copy vs copy.

Run:  ECHO_BENCH=1 pytest tests/bench/test_decode_bench.py -v --benchmark-only
"""

from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest

from echo_personal_tool.application.frame_cache import FrameCache
from echo_personal_tool.infrastructure.dicom_session import (
    DicomSession,
    _decode_compressed_frame,
    _decode_uncompressed_frame,
)

_BENCH = pytest.mark.skipif(
    os.environ.get("ECHO_BENCH", "") != "1",
    reason="Set ECHO_BENCH=1 to run benchmarks",
)


# ── Uncompressed decode: zero-copy vs copy ──────────────────────────


def _make_raw_pixel_data(rows: int, cols: int, bpp: int, n_frames: int) -> bytes:
    """Create synthetic uncompressed DICOM pixel data."""
    frame_bytes = rows * cols * bpp
    return bytes(n_frames * frame_bytes)


@_BENCH
def test_bench_decode_uncompressed_zero_copy(benchmark) -> None:
    """np.frombuffer view without .copy() — zero-copy path."""
    rows, cols, bpp = 256, 256, 2
    raw = _make_raw_pixel_data(rows, cols, bpp, n_frames=10)
    offsets = [(i * rows * cols * bpp, rows * cols * bpp) for i in range(10)]

    def _decode_all() -> None:
        for offset, size in offsets:
            _ = _decode_uncompressed_frame(raw, offset, size, rows, cols, bpp)

    benchmark(_decode_all)


@_BENCH
def test_bench_decode_uncompressed_with_copy(benchmark) -> None:
    """np.frombuffer + .copy() — old path for comparison."""
    rows, cols, bpp = 256, 256, 2
    raw = _make_raw_pixel_data(rows, cols, bpp, n_frames=10)
    offsets = [(i * rows * cols * bpp, rows * cols * bpp) for i in range(10)]

    def _decode_all_copy() -> None:
        for offset, size in offsets:
            chunk = raw[offset : offset + size]
            _ = np.frombuffer(chunk, dtype=np.uint16).reshape(rows, cols).copy()

    benchmark(_decode_all_copy)


# ── pydicom + pylibjpeg decode (compressed codecs) ──────────────────


def _make_test_dicom(
    tmp_path: Path, use_jpeg: bool, use_jpeg2000: bool, rows: int, cols: int, frame_count: int
) -> Path:
    """Create synthetic DICOM file for decode benchmarks."""
    from tests.fixtures.generate_synthetic_dicom import (
        write_synthetic_jpeg2000_multiframe_dicom,
        write_synthetic_jpeg_multiframe_dicom,
        write_synthetic_multiframe_dicom,
    )

    if use_jpeg:
        return write_synthetic_jpeg_multiframe_dicom(
            tmp_path / "jpeg.dcm",
            frame_count=frame_count,
            rows=rows,
            cols=cols,
        )
    if use_jpeg2000:
        return write_synthetic_jpeg2000_multiframe_dicom(
            tmp_path / "j2k.dcm",
            frame_count=frame_count,
            rows=rows,
            cols=cols,
        )
    return write_synthetic_multiframe_dicom(
        tmp_path / "raw.dcm",
        frame_count=frame_count,
        rows=rows,
        cols=cols,
    )


@_BENCH
def test_bench_dicom_session_open(benchmark, tmp_path: Path) -> None:
    """DicomSession.open(): read file bytes + pydicom header parse."""
    dcm = _make_test_dicom(tmp_path, use_jpeg=False, use_jpeg2000=False, rows=256, cols=256, frame_count=60)

    def _open() -> None:
        session = DicomSession()
        session.open(dcm)
        _ = session.frame_count

    benchmark(_open)


@_BENCH
def test_bench_dicom_session_decode_uncompressed(benchmark, tmp_path: Path) -> None:
    """DicomSession.decode_all_frames(): uncompressed, 60×256×256.

    Resets _frames before each call to avoid measuring cache-hit path.
    """
    dcm = _make_test_dicom(tmp_path, use_jpeg=False, use_jpeg2000=False, rows=256, cols=256, frame_count=60)
    session = DicomSession()
    session.open(dcm)

    def _decode() -> None:
        session._frames = None  # force full re-decode
        frames = session.decode_all_frames()
        assert frames.shape[0] == 60

    benchmark(_decode)


@_BENCH
def test_bench_dicom_session_decode_jpeg(benchmark, tmp_path: Path) -> None:
    """DicomSession.decode_all_frames(): JPEG Baseline, 30×256×256.

    Resets _frames before each call to avoid measuring cache-hit path.
    """
    dcm = _make_test_dicom(tmp_path, use_jpeg=True, use_jpeg2000=False, rows=256, cols=256, frame_count=30)
    session = DicomSession()
    session.open(dcm)

    def _decode() -> None:
        session._frames = None  # force full re-decode
        frames = session.decode_all_frames()
        assert frames.shape[0] == 30

    benchmark(_decode)


@_BENCH
def test_bench_dicom_session_decode_jpeg2000(benchmark, tmp_path: Path) -> None:
    """DicomSession.decode_all_frames(): JPEG-2000 via pylibjpeg-openjpeg, 30×256×256."""
    try:
        import openjpeg  # noqa: F401
    except ImportError:
        pytest.skip("openjpeg not available")

    dcm = _make_test_dicom(tmp_path, use_jpeg=False, use_jpeg2000=True, rows=256, cols=256, frame_count=30)
    session = DicomSession()
    session.open(dcm)

    def _decode() -> None:
        session._frames = None  # force full re-decode
        frames = session.decode_all_frames()
        assert frames.shape[0] == 30

    benchmark(_decode)


@_BENCH
def test_bench_dicom_session_single_frame_random_access(benchmark, tmp_path: Path) -> None:
    """decode_single_frame(45) without decoding all frames first."""
    dcm = _make_test_dicom(tmp_path, use_jpeg=False, use_jpeg2000=False, rows=512, cols=512, frame_count=60)
    session = DicomSession()
    session.open(dcm)

    def _random_access() -> None:
        frame = session.decode_single_frame(45)
        assert frame.shape == (512, 512)

    benchmark(_random_access)


@_BENCH
def test_bench_decode_fragment_jpeg2000_single(benchmark) -> None:
    """pylibjpeg-openjpeg: decode single J2K fragment 512×512."""
    try:
        import openjpeg
    except ImportError:
        pytest.skip("openjpeg not available")

    import numpy as np

    frame = np.random.default_rng(42).integers(0, 255, (512, 512), dtype=np.uint8)
    encoded = openjpeg.encode(frame)

    def _decode() -> None:
        decoded = _decode_compressed_frame(encoded, 512, 512, "1.2.840.10008.1.2.4.90")
        assert decoded is not None
        assert decoded.shape == (512, 512)

    benchmark(_decode)


@_BENCH
def test_bench_decode_fragment_jpeg_cv2(benchmark) -> None:
    """cv2.imdecode: decode single JPEG fragment 512×512."""
    import cv2
    import numpy as np

    frame = np.random.default_rng(42).integers(0, 255, (512, 512), dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", frame)
    assert ok

    def _decode() -> None:
        decoded = _decode_compressed_frame(encoded.tobytes(), 512, 512, "1.2.840.10008.1.2.4.50")
        assert decoded is not None
        assert decoded.shape == (512, 512)

    benchmark(_decode)


@_BENCH
def test_bench_pydicom_pixel_array_fallback(benchmark, tmp_path: Path) -> None:
    """pydicom.pixel_array fallback — full DICOM parse with pixel decode."""
    import pydicom
    from tests.fixtures.generate_synthetic_dicom import write_synthetic_multiframe_dicom

    from echo_personal_tool.infrastructure.dicom_session import stack_pixel_array

    dcm = write_synthetic_multiframe_dicom(
        tmp_path / "fallback.dcm",
        frame_count=30,
        rows=256,
        cols=256,
    )
    raw = dcm.read_bytes()

    def _fallback() -> None:
        ds = pydicom.dcmread(BytesIO(raw), force=True)
        arr = stack_pixel_array(ds.pixel_array)
        assert arr.shape[0] == 30

    benchmark(_fallback)


# ── FrameCache eviction cost ────────────────────────────────────────


@_BENCH
def test_bench_evict_200_frames_sweep(benchmark, tmp_path: Path) -> None:
    """set_current() sweep over 200-frame cache — measures _evict() cost."""
    n = 200
    frames = np.arange(n * 8 * 8, dtype=np.uint16).reshape(n, 8, 8)
    cache = FrameCache(evict_window=20)
    cache.load(tmp_path / "c.dcm", frames)

    def _sweep() -> None:
        for i in range(0, n, 10):
            cache.set_current(i)

    benchmark(_sweep)


@_BENCH
def test_bench_evict_with_pinned_frames(benchmark, tmp_path: Path) -> None:
    """Eviction with 5 pinned frames — tests pin guard overhead."""
    n = 100
    frames = np.arange(n * 8 * 8, dtype=np.uint16).reshape(n, 8, 8)
    cache = FrameCache(evict_window=20)
    cache.load(tmp_path / "c.dcm", frames)
    for i in range(0, n, 20):
        cache.pin(i)

    def _sweep_pinned() -> None:
        for i in range(0, n, 5):
            cache.set_current(i)

    benchmark(_sweep_pinned)


# ── FrameCache.frames property (memoized) ───────────────────────────


@_BENCH
def test_bench_frames_property_first_call(benchmark, tmp_path: Path) -> None:
    """First .frames call — triggers np.stack reconstruction."""
    n = 60
    frames = np.arange(n * 16 * 16, dtype=np.uint16).reshape(n, 16, 16)
    cache = FrameCache(evict_window=40)
    cache.load(tmp_path / "c.dcm", frames)

    def _rebuild() -> None:
        cache._cached_frames = None  # force rebuild
        _ = cache.frames

    benchmark(_rebuild)


@_BENCH
def test_bench_frames_property_cached(benchmark, tmp_path: Path) -> None:
    """Subsequent .frames calls — should return cached result."""
    n = 60
    frames = np.arange(n * 16 * 16, dtype=np.uint16).reshape(n, 16, 16)
    cache = FrameCache(evict_window=40)
    cache.load(tmp_path / "c.dcm", frames)
    _ = cache.frames  # prime cache

    def _cached_call() -> None:
        _ = cache.frames

    benchmark(_cached_call)


# ── bisect vs linear eviction ───────────────────────────────────────


@_BENCH
def test_bench_sorted_keys_eviction_logic(benchmark, tmp_path: Path) -> None:
    """Sorted keys + bisect eviction — the optimized path."""
    n = 500
    frames = np.arange(n * 4 * 4, dtype=np.uint8).reshape(n, 4, 4)
    cache = FrameCache(evict_window=30)
    cache.load(tmp_path / "c.dcm", frames)

    def _evict_many() -> None:
        for i in range(0, n, 5):
            cache.set_current(i)

    benchmark(_evict_many)
