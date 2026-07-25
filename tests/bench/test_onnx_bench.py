"""ONNX model inference latency benchmarks.

Measures per-frame inference latency for the segmentation ONNX model.

Run:  ECHO_BENCH=1 pytest tests/bench/test_onnx_bench.py -v --benchmark-only
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from echo_personal_tool.infrastructure.onnx_engine import OnnxInferenceEngine

_bench = pytest.mark.bench


def _has_onnx_model() -> bool:
    """Check if the ONNX model file exists on disk."""
    try:
        engine = OnnxInferenceEngine()
        return engine.is_available()
    except Exception:
        return False


_skip_no_model = pytest.mark.skipif(
    os.environ.get("ECHO_BENCH", "") != "1" or not _has_onnx_model(),
    reason="Set ECHO_BENCH=1 and ensure ONNX model is installed",
)


@_bench
@_skip_no_model
def test_bench_onnx_single_frame_112(benchmark) -> None:
    """Single frame inference at 112x112 (default model input size)."""
    engine = OnnxInferenceEngine()
    frame = np.random.default_rng(42).integers(0, 255, (256, 256), dtype=np.uint8)

    def _infer() -> np.ndarray:
        return engine.segment(frame)

    result = benchmark(_infer)
    assert result.ndim == 2


@_bench
@_skip_no_model
def test_bench_onnx_single_frame_256(benchmark) -> None:
    """Single frame inference at 256x256 input."""
    engine = OnnxInferenceEngine()
    frame = np.random.default_rng(42).integers(0, 255, (256, 256), dtype=np.uint8)

    def _infer() -> np.ndarray:
        return engine.segment(frame, crop_mode="center_square")

    result = benchmark(_infer)
    assert result.shape == (256, 256)


@_bench
@_skip_no_model
def test_bench_onnx_single_frame_512(benchmark) -> None:
    """Single frame inference at 512x512 input (upscale required)."""
    engine = OnnxInferenceEngine()
    frame = np.random.default_rng(42).integers(0, 255, (512, 512), dtype=np.uint8)

    def _infer() -> np.ndarray:
        return engine.segment(frame)

    result = benchmark(_infer)
    assert result.shape == (512, 512)


@_bench
@_skip_no_model
def test_bench_onnx_batch_10_frames(benchmark) -> None:
    """Batch of 10 frames — measures sustained throughput."""
    engine = OnnxInferenceEngine()
    frames = [
        np.random.default_rng(i).integers(0, 255, (256, 256), dtype=np.uint8)
        for i in range(10)
    ]

    def _batch() -> None:
        for frame in frames:
            engine.segment(frame)

    benchmark(_batch)


@_bench
@_skip_no_model
def test_bench_onnx_with_roi(benchmark) -> None:
    """Inference with ROI crop (simulates user-selected region)."""
    engine = OnnxInferenceEngine()
    frame = np.random.default_rng(42).integers(0, 255, (512, 512), dtype=np.uint8)

    def _infer_roi() -> np.ndarray:
        return engine.segment(frame, roi_xyxy=(50.0, 50.0, 400.0, 400.0))

    result = benchmark(_infer_roi)
    assert result.ndim == 2


@_bench
@_skip_no_model
def test_bench_onnx_crop_mode_center_square(benchmark) -> None:
    """Inference with explicit center_square crop mode."""
    engine = OnnxInferenceEngine()
    frame = np.random.default_rng(42).integers(0, 255, (300, 400), dtype=np.uint8)

    def _infer() -> np.ndarray:
        return engine.segment(frame, crop_mode="center_square")

    result = benchmark(_infer)
    assert result.ndim == 2


@_bench
@_skip_no_model
def test_bench_onnx_color_frame(benchmark) -> None:
    """Inference on a color (H, W, 3) frame."""
    engine = OnnxInferenceEngine()
    frame = np.random.default_rng(42).integers(0, 255, (256, 256, 3), dtype=np.uint8)

    def _infer() -> np.ndarray:
        return engine.segment(frame)

    result = benchmark(_infer)
    assert result.ndim == 2


@_bench
@_skip_no_model
def test_bench_onnx_repeated_inference_warmup(benchmark) -> None:
    """Repeated inference — measures hot-path latency (model already loaded)."""
    engine = OnnxInferenceEngine()
    frame = np.random.default_rng(42).integers(0, 255, (256, 256), dtype=np.uint8)
    # Warm up
    engine.segment(frame)

    def _hot_path() -> np.ndarray:
        return engine.segment(frame)

    benchmark(_hot_path)
