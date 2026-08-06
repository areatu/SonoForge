"""Integration pipeline benchmarks.

Measures full end-to-end paths:
  - Synthetic DICOM disk → ScanWorker → StudyMetadata
  - Synthetic DICOM disk → DicomSession → decoded frames
  - Thumbnail generation: DicomReader → QImage
  - ThumbnailGallery population

Run:  ECHO_BENCH=1 pytest tests/bench/test_pipeline_bench.py -v --benchmark-only
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from echo_personal_tool.application.frame_cache import FrameCache
from echo_personal_tool.application.workers.scan_worker import ScanWorker
from echo_personal_tool.infrastructure.dicom_reader import DicomReaderImpl
from echo_personal_tool.infrastructure.dicom_session import DicomSession
from echo_personal_tool.infrastructure.local_scanner import LocalMediaDirectoryScanner

_BENCH = pytest.mark.skipif(
    os.environ.get("ECHO_BENCH", "") != "1",
    reason="Set ECHO_BENCH=1 to run benchmarks",
)

_FRAME_SIZES = [(64, 64), (256, 256), (512, 512)]


# ── Helpers ──────────────────────────────────────────────────────────


def _write_synthetic_study(
    root: Path,
    *,
    series_count: int = 3,
    frames_per_series: int = 10,
    rows: int = 64,
    cols: int = 64,
    use_jpeg: bool = False,
    use_jpeg2000: bool = False,
) -> Path:
    """Create a synthetic study with multiple series on disk.

    Returns the study root path.
    """
    from tests.fixtures.generate_synthetic_dicom import (
        write_synthetic_jpeg2000_multiframe_dicom,
        write_synthetic_jpeg_multiframe_dicom,
        write_synthetic_multiframe_dicom,
    )

    study_dir = root / "studies" / "syn-study-1"
    study_dir.mkdir(parents=True, exist_ok=True)

    for s_idx in range(series_count):
        series_dir = study_dir / f"series-{s_idx}"
        series_dir.mkdir(parents=True, exist_ok=True)

        for _ in range(1):
            if use_jpeg:
                write_synthetic_jpeg_multiframe_dicom(
                    series_dir / "img.dcm",
                    frame_count=frames_per_series,
                    rows=rows,
                    cols=cols,
                )
            elif use_jpeg2000:
                write_synthetic_jpeg2000_multiframe_dicom(
                    series_dir / "img.dcm",
                    frame_count=frames_per_series,
                    rows=rows,
                    cols=cols,
                )
            else:
                write_synthetic_multiframe_dicom(
                    series_dir / "img.dcm",
                    frame_count=frames_per_series,
                    rows=rows,
                    cols=cols,
                )

    return study_dir


# ── Scan pipeline ────────────────────────────────────────────────────


@_BENCH
def test_bench_scan_small_study(benchmark, tmp_path: Path) -> None:
    """Scan 3 series × 1 file (small 64×64)."""
    _write_synthetic_study(tmp_path, series_count=3, frames_per_series=1, rows=64, cols=64)
    scanner = LocalMediaDirectoryScanner()

    def _scan() -> object:
        return scanner.scan(tmp_path / "studies")

    result = benchmark(_scan)
    studies = list(result)
    assert len(studies) >= 1


@_BENCH
def test_bench_scan_large_study(benchmark, tmp_path: Path) -> None:
    """Scan 5 series × 1 file (medium 256×256, header-only)."""
    _write_synthetic_study(tmp_path, series_count=5, frames_per_series=1, rows=256, cols=256)
    scanner = LocalMediaDirectoryScanner()

    def _scan() -> object:
        return scanner.scan(tmp_path / "studies")

    result = benchmark(_scan)
    studies = list(result)
    assert len(studies) >= 1


@_BENCH
def test_bench_scan_study_multiframe(benchmark, tmp_path: Path) -> None:
    """Scan study with 3 series × multiframe (header-only, no pixel decode)."""
    _write_synthetic_study(tmp_path, series_count=3, frames_per_series=60, rows=256, cols=256)
    scanner = LocalMediaDirectoryScanner()

    def _scan() -> object:
        return scanner.scan(tmp_path / "studies")

    result = benchmark(_scan)
    studies = list(result)
    assert len(studies) >= 1


# ── Full pipeline: disk → decode → FrameCache ────────────────────────


@_BENCH
def test_bench_pipeline_uncompressed_decode(benchmark, tmp_path: Path) -> None:
    """Full: open DICOM → decode all frames → load into FrameCache."""
    from tests.fixtures.generate_synthetic_dicom import write_synthetic_multiframe_dicom

    dcm = write_synthetic_multiframe_dicom(
        tmp_path / "cine.dcm",
        frame_count=60,
        rows=256,
        cols=256,
    )
    cache = FrameCache(evict_window=40)

    def _pipeline() -> None:
        session = DicomSession()
        session.open(dcm)
        frames = session.decode_all_frames()
        cache.load(dcm, frames)
        _ = cache.frame_count  # accessed after each round

    benchmark(_pipeline)
    assert cache.memory_bytes() > 0


@_BENCH
def test_bench_pipeline_jpeg_decode(benchmark, tmp_path: Path) -> None:
    """Full: JPEG-encapsulated DICOM → decode → FrameCache."""
    from tests.fixtures.generate_synthetic_dicom import write_synthetic_jpeg_multiframe_dicom

    dcm = write_synthetic_jpeg_multiframe_dicom(
        tmp_path / "jpeg.dcm",
        frame_count=30,
        rows=256,
        cols=256,
    )
    cache = FrameCache(evict_window=40)

    def _pipeline() -> None:
        session = DicomSession()
        session.open(dcm)
        frames = session.decode_all_frames()
        cache.load(dcm, frames)

    benchmark(_pipeline)


@_BENCH
def test_bench_pipeline_jpeg2000_decode(benchmark, tmp_path: Path) -> None:
    """Full: JPEG-2000 DICOM → decode → FrameCache (uses pylibjpeg-openjpeg)."""
    try:
        import openjpeg  # noqa: F401
    except ImportError:
        pytest.skip("openjpeg not available")

    from tests.fixtures.generate_synthetic_dicom import write_synthetic_jpeg2000_multiframe_dicom

    dcm = write_synthetic_jpeg2000_multiframe_dicom(
        tmp_path / "j2k.dcm",
        frame_count=30,
        rows=256,
        cols=256,
    )
    cache = FrameCache(evict_window=40)

    def _pipeline() -> None:
        session = DicomSession()
        session.open(dcm)
        frames = session.decode_all_frames()
        cache.load(dcm, frames)

    benchmark(_pipeline)


# ── Thumbnail generation ─────────────────────────────────────────────


@_BENCH
def test_bench_thumbnail_decode_single(benchmark, tmp_path: Path) -> None:
    """Decode first frame and convert to QImage (thumbnail path)."""
    from tests.fixtures.generate_synthetic_dicom import write_synthetic_multiframe_dicom

    dcm = write_synthetic_multiframe_dicom(
        tmp_path / "thumb.dcm",
        frame_count=60,
        rows=256,
        cols=256,
    )

    def _thumbnail() -> None:
        pixels = DicomReaderImpl().read_pixels(dcm, frame_index=0)
        _ = np.ascontiguousarray(pixels)

    benchmark(_thumbnail)


# ── First-frame latency (user-perceived) ─────────────────────────────


@_BENCH
def test_bench_first_frame_latency(benchmark, tmp_path: Path) -> None:
    """Time from open() to first decoded frame — user perception."""
    from tests.fixtures.generate_synthetic_dicom import write_synthetic_multiframe_dicom

    dcm = write_synthetic_multiframe_dicom(
        tmp_path / "latency.dcm",
        frame_count=60,
        rows=512,
        cols=512,
    )

    def _first_frame() -> None:
        session = DicomSession()
        session.open(dcm)
        _ = session.decode_first_frame()

    benchmark(_first_frame)


# ── ScanWorker end-to-end (QRunnable dispatch) ───────────────────────


@_BENCH
def test_bench_scanworker_dispatch(benchmark, tmp_path: Path) -> None:
    """ScanWorker.run() — full dispatch overhead.

    NOTE: This test does NOT start the worker on a real QThreadPool
    since pytest-benchmark runs in the main thread. It calls run()
    synchronously to measure the scanning logic itself.
    """
    _write_synthetic_study(tmp_path, series_count=3, frames_per_series=1, rows=64, cols=64)
    from PySide6.QtCore import QObject

    dummy_parent = QObject()
    worker = ScanWorker(tmp_path / "studies", parent=dummy_parent)

    def _run_sync() -> None:
        worker.run()

    benchmark(_run_sync)
