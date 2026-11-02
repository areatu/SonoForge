"""Tests for LUT-based window/level (Phase 2 viewer performance)."""

from __future__ import annotations

import numpy as np

from echo_personal_tool.infrastructure.pixel_utils import (
    apply_wl_lut,
    reference_wl_display_uint8,
)


def test_apply_wl_lut_grayscale_uint16() -> None:
    rng = np.random.default_rng(0)
    frame = rng.integers(0, 65535, (128, 128), dtype=np.uint16)
    result = apply_wl_lut(
        frame,
        dr_low_pct=0.0,
        dr_high_pct=100.0,
        window_scale=1.0,
        level_offset=0.0,
    )
    assert result.shape == (128, 128)
    assert result.dtype == np.uint8
    assert result.min() >= 0
    assert result.max() <= 255


def test_apply_wl_lut_preserves_black_uint16() -> None:
    frame = np.zeros((64, 64), dtype=np.uint16)
    result = apply_wl_lut(
        frame,
        dr_low_pct=0.0,
        dr_high_pct=100.0,
        window_scale=0.5,
        level_offset=0.0,
    )
    assert result.max() == 0


def test_apply_wl_lut_matches_reference_uint8() -> None:
    rng = np.random.default_rng(42)
    frame = rng.integers(0, 256, (96, 96), dtype=np.uint8)
    kwargs = dict(
        dr_low_pct=10.0,
        dr_high_pct=90.0,
        window_scale=0.75,
        level_offset=0.1,
    )
    lut_out = apply_wl_lut(frame, **kwargs)
    ref_out = reference_wl_display_uint8(frame, **kwargs)
    assert np.array_equal(lut_out, ref_out)


def test_apply_wl_lut_matches_reference_uint16() -> None:
    rng = np.random.default_rng(7)
    frame = rng.integers(1000, 60000, (64, 64), dtype=np.uint16)
    kwargs = dict(
        dr_low_pct=5.0,
        dr_high_pct=95.0,
        window_scale=0.6,
        level_offset=-0.2,
    )
    lut_out = apply_wl_lut(frame, **kwargs)
    ref_out = reference_wl_display_uint8(frame, **kwargs)
    assert np.array_equal(lut_out, ref_out)


def test_apply_wl_lut_uint8_bright_saturates() -> None:
    frame = np.linspace(0, 255, 32 * 32, dtype=np.uint8).reshape(32, 32)
    result = apply_wl_lut(
        frame,
        dr_low_pct=0.0,
        dr_high_pct=100.0,
        window_scale=1.0,
        level_offset=0.0,
    )
    assert result.max() == 255
    assert result.min() == 0
