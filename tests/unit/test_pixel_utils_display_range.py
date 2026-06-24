"""Unit tests for pixel display range helpers."""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.infrastructure.pixel_utils import (
    compute_display_levels,
    dr_percentiles_from_slider,
    percentile_range,
)


def test_is_effective_grayscale_detects_b_mode_rgb_packing() -> None:
    from echo_personal_tool.infrastructure.pixel_utils import (
        is_color_frame,
        is_effective_grayscale,
    )

    gray = np.full((64, 48), 120, dtype=np.uint8)
    rgb = np.stack([gray, gray, gray], axis=-1)

    assert is_effective_grayscale(gray)
    assert is_effective_grayscale(rgb)
    assert not is_color_frame(rgb)


def test_is_color_frame_true_for_doppler_like_channels() -> None:
    from echo_personal_tool.infrastructure.pixel_utils import is_color_frame

    frame = np.zeros((64, 48, 3), dtype=np.uint8)
    frame[:, :, 0] = 200
    frame[:, :, 1] = 40
    frame[:, :, 2] = 40

    assert is_color_frame(frame)


def test_to_display_rgb_preserves_dicom_channel_order() -> None:
    from echo_personal_tool.infrastructure.pixel_utils import to_display_rgb

    frame = np.zeros((4, 4, 3), dtype=np.uint8)
    frame[0, 0] = (255, 0, 0)

    rgb = to_display_rgb(frame, channel_order="rgb")
    assert np.array_equal(rgb[0, 0], np.array([255, 0, 0], dtype=np.uint8))

    swapped = to_display_rgb(frame, channel_order="bgr")
    assert np.array_equal(swapped[0, 0], np.array([0, 0, 255], dtype=np.uint8))


def test_apply_window_level_rgb_preserves_red_hue() -> None:
    from echo_personal_tool.infrastructure.pixel_utils import apply_window_level_rgb

    frame = np.zeros((8, 8, 3), dtype=np.uint8)
    frame[..., 0] = 200
    frame[..., 1] = 20
    frame[..., 2] = 20

    adjusted = apply_window_level_rgb(frame, low=0.0, high=255.0)
    assert adjusted[0, 0, 0] > adjusted[0, 0, 1]
    assert adjusted[0, 0, 0] > adjusted[0, 0, 2]


def test_to_grayscale_array_preserves_uint16_range() -> None:
    from echo_personal_tool.infrastructure.pixel_utils import to_grayscale_array

    frame = np.array([[0, 4095]], dtype=np.uint16)
    gray = to_grayscale_array(frame)

    assert gray.dtype == np.float64
    assert gray.max() == pytest.approx(4095.0)


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
