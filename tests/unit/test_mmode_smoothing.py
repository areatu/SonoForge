from __future__ import annotations

import numpy as np

from echo_personal_tool.domain.services.mmode_smoothing import (
    enhance_contrast,
    spatial_smooth,
    temporal_smooth,
)


def test_enhance_contrast_stretches() -> None:
    # Uniform column — no stretch possible
    col = np.full(100, 128, dtype=np.uint8)
    result = enhance_contrast(col, clip_pct=1.0)
    np.testing.assert_array_equal(result, col)


def test_enhance_contrast_range() -> None:
    col = np.array([10, 50, 100, 150, 200], dtype=np.uint8)
    result = enhance_contrast(col, clip_pct=1.0)
    assert result.dtype == np.uint8
    assert result[0] < result[-1]


def test_enhance_contrast_preserves_order() -> None:
    col = np.array([10, 50, 200], dtype=np.uint8)
    result = enhance_contrast(col, clip_pct=1.0)
    assert result[0] < result[1] < result[2]


def test_spatial_smooth_reduces_jaggedness() -> None:
    col = np.zeros(100, dtype=np.float32)
    col[45:55] = 255.0
    smoothed = spatial_smooth(col, sigma=0.8)
    # Edges should be softened
    assert smoothed[44] > 0.0
    assert smoothed[55] > 0.0
    # Center still bright
    assert smoothed[50] > 200.0


def test_spatial_smooth_preserves_structure() -> None:
    col = np.zeros(100, dtype=np.float32)
    col[20:80] = 128.0
    smoothed = spatial_smooth(col, sigma=0.8)
    assert smoothed[50] > 100.0  # Center still bright
    assert smoothed[0] < 10.0  # Edge still dark


def test_temporal_smooth_no_previous() -> None:
    col = np.full(10, 128, dtype=np.uint8)
    result = temporal_smooth(col, None, alpha=0.3)
    np.testing.assert_array_equal(result, col)


def test_temporal_smooth_blends() -> None:
    prev = np.full(10, 100, dtype=np.uint8)
    curr = np.full(10, 200, dtype=np.uint8)
    result = temporal_smooth(curr, prev, alpha=0.3)
    # 0.3 * 200 + 0.7 * 100 = 130
    expected = int(0.3 * 200 + 0.7 * 100)
    assert abs(int(result[0]) - expected) <= 1


def test_temporal_smooth_alpha_1() -> None:
    prev = np.full(10, 0, dtype=np.uint8)
    curr = np.full(10, 255, dtype=np.uint8)
    result = temporal_smooth(curr, prev, alpha=1.0)
    np.testing.assert_array_equal(result, curr)
