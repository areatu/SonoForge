"""Full pipeline benchmarks: DICOM open -> decode -> basic measurement.

Uses synthetic DICOM files to benchmark the end-to-end path from disk
read through frame decode to pixel-level measurement readiness.

Run:  ECHO_BENCH=1 pytest tests/bench/test_full_pipeline_bench.py -v --benchmark-only
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from echo_personal_tool.application.frame_cache import FrameCache
from echo_personal_tool.infrastructure.dicom_session import DicomSession
from echo_personal_tool.infrastructure.pixel_utils import (
    apply_wl_lut,
    to_grayscale_uint8,
)

from tests.fixtures.generate_synthetic_dicom import (
    write_synthetic_jpeg_multiframe_dicom,
    write_synthetic_multiframe_dicom,
)

_bench = pytest.mark.bench
_skip_bench = pytest.mark.skipif(
    os.environ.get("ECHO_BENCH", "") != "1",
    reason="Set ECHO_BENCH=1 to run benchmarks",
)


@_bench
@_skip_bench
def test_bench_pipeline_open_decode_wl(benchmark, tmp_path: Path) -> None:
    """DICOM open -> decode all -> apply window/level LUT."""
    dcm = write_synthetic_multiframe_dicom(
        tmp_path / "cine.dcm",
        frame_count=60,
        rows=256,
        cols=256,
    )

    def _pipeline() -> None:
        session = DicomSession()
        session.open(dcm)
        frames = session.decode_all_frames()
        for i in range(frames.shape[0]):
            _ = apply_wl_lut(
                frames[i],
                dr_low_pct=5.0,
                dr_high_pct=95.0,
                window_scale=0.8,
                level_offset=0.0,
            )

    benchmark(_pipeline)


@_bench
@_skip_bench
def test_bench_pipeline_open_decode_grayscale(benchmark, tmp_path: Path) -> None:
    """DICOM open -> decode all -> convert each frame to grayscale uint8."""
    dcm = write_synthetic_multiframe_dicom(
        tmp_path / "gray.dcm",
        frame_count=30,
        rows=256,
        cols=256,
    )

    def _pipeline() -> None:
        session = DicomSession()
        session.open(dcm)
        frames = session.decode_all_frames()
        for i in range(frames.shape[0]):
            _ = to_grayscale_uint8(frames[i])

    benchmark(_pipeline)


@_bench
@_skip_bench
def test_bench_pipeline_open_decode_framecache(benchmark, tmp_path: Path) -> None:
    """DICOM open -> decode -> load into FrameCache -> sweep current."""
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
        for i in range(0, 60, 5):
            cache.set_current(i)

    benchmark(_pipeline)


@_bench
@_skip_bench
def test_bench_pipeline_jpeg_open_decode_wl(benchmark, tmp_path: Path) -> None:
    """JPEG-compressed DICOM open -> decode -> window/level."""
    dcm = write_synthetic_jpeg_multiframe_dicom(
        tmp_path / "jpeg_cine.dcm",
        frame_count=30,
        rows=256,
        cols=256,
    )

    def _pipeline() -> None:
        session = DicomSession()
        session.open(dcm)
        frames = session.decode_all_frames()
        for i in range(frames.shape[0]):
            _ = apply_wl_lut(
                frames[i],
                dr_low_pct=5.0,
                dr_high_pct=95.0,
                window_scale=0.8,
                level_offset=0.0,
            )

    benchmark(_pipeline)


@_bench
@_skip_bench
def test_bench_pipeline_single_frame_random_access(benchmark, tmp_path: Path) -> None:
    """DICOM open -> random-access decode of single frames (no full decode)."""
    dcm = write_synthetic_multiframe_dicom(
        tmp_path / "random.dcm",
        frame_count=60,
        rows=512,
        cols=512,
    )

    def _random_access() -> None:
        session = DicomSession()
        session.open(dcm)
        for idx in (0, 15, 30, 45, 59):
            frame = session.decode_single_frame(idx)
            assert frame.shape == (512, 512)

    benchmark(_random_access)


@_bench
@_skip_bench
def test_bench_pipeline_30_frame_cine(benchmark, tmp_path: Path) -> None:
    """Standard 30-frame cine: open -> decode -> grayscale -> FrameCache."""
    dcm = write_synthetic_multiframe_dicom(
        tmp_path / "cine30.dcm",
        frame_count=30,
        rows=256,
        cols=256,
    )
    cache = FrameCache(evict_window=40)

    def _cine() -> None:
        session = DicomSession()
        session.open(dcm)
        frames = session.decode_all_frames()
        gray = np.stack([to_grayscale_uint8(frames[i]) for i in range(frames.shape[0])])
        cache.load(dcm, gray)

    benchmark(_cine)


@_bench
@_skip_bench
def test_bench_pipeline_60_frame_high_res(benchmark, tmp_path: Path) -> None:
    """High-resolution 60-frame cine (512x512)."""
    dcm = write_synthetic_multiframe_dicom(
        tmp_path / "hr_cine.dcm",
        frame_count=60,
        rows=512,
        cols=512,
    )

    def _hr_pipeline() -> None:
        session = DicomSession()
        session.open(dcm)
        frames = session.decode_all_frames()
        assert frames.shape[0] == 60
        for i in range(0, 60, 10):
            _ = apply_wl_lut(
                frames[i],
                dr_low_pct=5.0,
                dr_high_pct=95.0,
                window_scale=0.8,
                level_offset=0.0,
            )

    benchmark(_hr_pipeline)


@_bench
@_skip_bench
def test_bench_pipeline_open_only(benchmark, tmp_path: Path) -> None:
    """DICOM open (header parse) only — no pixel decode."""
    dcm = write_synthetic_multiframe_dicom(
        tmp_path / "header.dcm",
        frame_count=60,
        rows=512,
        cols=512,
    )

    def _open_only() -> None:
        session = DicomSession()
        session.open(dcm)
        _ = session.frame_count

    benchmark(_open_only)
