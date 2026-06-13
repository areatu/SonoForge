"""Unit tests for pixel display range helpers."""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.infrastructure.pixel_utils import (
    compute_display_levels,
    dr_percentiles_from_slider,
    percentile_range,
)


def test_percentile_range_clips_and_ignores_non_finite_values() -> None:
    frame = np.array([np.nan, -5.0, 0.0, 10.0, np.inf], dtype=float)

    low, high = percentile_range(frame, -20.0, 120.0)

    assert low == pytest.approx(-5.0)
    assert high == pytest.approx(10.0)


def test_percentile_range_returns_default_for_empty_or_non_finite_frames() -> None:
    assert percentile_range(np.array([], dtype=float), 10.0, 90.0) == (0.0, 1.0)
    assert percentile_range(np.array([np.nan, np.inf], dtype=float), 10.0, 90.0) == (
        0.0,
        1.0,
    )


def test_dr_percentiles_from_slider_center_is_full_range() -> None:
    low, high = dr_percentiles_from_slider(50)
    assert low == pytest.approx(0.0)
    assert high == pytest.approx(100.0)


def test_dr_percentiles_from_slider_left_clips_dark() -> None:
    low, high = dr_percentiles_from_slider(0)
    assert low == pytest.approx(45.0)
    assert high == pytest.approx(100.0)


def test_compute_display_levels_uses_percentile_range_and_wl_math() -> None:
    frame = np.array([0.0, 10.0, 20.0, 30.0], dtype=float)

    low, high = compute_display_levels(
        frame,
        dr_low_pct=25.0,
        dr_high_pct=75.0,
        window_scale=0.5,
        level_offset=0.0,
    )

    assert low == pytest.approx(11.25)
    assert high == pytest.approx(18.75)
