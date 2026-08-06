"""Rendering path benchmarks.

Measures: pixel conversion, W/L LUT, color Doppler RGB, identity cache.

Run:  ECHO_BENCH=1 pytest tests/bench/test_rendering_bench.py -v --benchmark-only
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from echo_personal_tool.infrastructure.pixel_utils import (
    apply_wl_lut,
    is_color_frame,
    is_effective_grayscale,
    to_display_rgb,
    to_grayscale_array,
    to_grayscale_uint8,
)

_BENCH = pytest.mark.skipif(
    os.environ.get("ECHO_BENCH", "") != "1",
    reason="Set ECHO_BENCH=1 to run benchmarks",
)


def _uint8_gray(w: int = 512, h: int = 512) -> np.ndarray:
    rng = np.random.default_rng(7)
    return rng.integers(0, 255, (h, w), dtype=np.uint8)


def _uint16_gray(w: int = 512, h: int = 512) -> np.ndarray:
    rng = np.random.default_rng(7)
    return rng.integers(0, 65535, (h, w), dtype=np.uint16)


def _color_frame(w: int = 512, h: int = 512) -> np.ndarray:
    rng = np.random.default_rng(7)
    return rng.integers(0, 255, (h, w, 3), dtype=np.uint8)


# ── W/L LUT ────────────────────────────────────────────────────────


@_BENCH
def test_bench_wl_lut_uint16(benchmark) -> None:
    """Window/Level via LUT on 512x512 uint16."""
    frame = _uint16_gray()
    benchmark(
        apply_wl_lut,
        frame,
        dr_low_pct=5.0,
        dr_high_pct=95.0,
        window_scale=0.8,
        level_offset=0.0,
    )


@_BENCH
def test_bench_wl_lut_uint8(benchmark) -> None:
    """Window/Level via LUT on 512x512 uint8."""
    frame = _uint8_gray()
    benchmark(
        apply_wl_lut,
        frame,
        dr_low_pct=5.0,
        dr_high_pct=95.0,
        window_scale=0.8,
        level_offset=0.0,
    )


# ── Grayscale conversion ───────────────────────────────────────────


@_BENCH
def test_bench_to_grayscale_uint8(benchmark) -> None:
    """BGR → grayscale uint8 (used during decode)."""
    frame = np.random.default_rng(7).integers(0, 255, (512, 512, 3), dtype=np.uint8)
    benchmark(to_grayscale_uint8, frame)


@_BENCH
def test_bench_to_grayscale_array_float64(benchmark) -> None:
    """Full float64 grayscale conversion (legacy path)."""
    frame = _uint8_gray()
    benchmark(to_grayscale_array, frame)


# ── Color Doppler ──────────────────────────────────────────────────


@_BENCH
def test_bench_to_display_rgb(benchmark) -> None:
    """BGR → RGB conversion for color Doppler display."""
    frame = _color_frame()
    benchmark(to_display_rgb, frame, channel_order="bgr")


@_BENCH
def test_bench_color_frame_detection(benchmark) -> None:
    """is_color_frame check — called every frame in show_frame_fast."""
    gray = _uint8_gray()
    color = _color_frame()

    def _detect() -> None:
        for _ in range(100):
            _ = is_color_frame(gray)
            _ = is_color_frame(color)

    benchmark(_detect)


@_BENCH
def test_bench_grayscale_check(benchmark) -> None:
    """is_effective_grayscale — display mode caching check."""
    gray = _uint8_gray()
    color = _color_frame()

    def _check() -> None:
        for _ in range(100):
            _ = is_effective_grayscale(gray)
            _ = is_effective_grayscale(color)

    benchmark(_check)
