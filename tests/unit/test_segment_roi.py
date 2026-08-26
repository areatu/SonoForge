"""Unit tests for DICOM vs cine segment ROI selection."""

from __future__ import annotations

import numpy as np

from echo_personal_tool.domain.services.segment_roi import (
    ECHONET_CROP_CENTER_SQUARE,
    echonet_crop_mode_for_media,
    resolve_cine_segment_roi_xyxy,
    resolve_segment_roi_xyxy,
)


def _make_doppler_frame(
    height: int = 600,
    width: int = 800,
    tick_spacing_px: int = 30,
    spectral_mean: float = 25.0,
) -> np.ndarray:
    """Create a synthetic Doppler-like frame with tick marks in the bottom ruler area.

    Structure (top to bottom):
    - Top 55%: bright B-mode tissue (~140)
    - 55%-85%: dark spectral band (spectral_mean, near-black)
    - Bottom 15%: time ruler with periodic bright vertical ticks on dark background
    """
    frame = np.zeros((height, width, 3), dtype=np.uint8)

    # Bright B-mode tissue at top
    frame[: int(height * 0.55), :] = 140

    # Dark spectral band (above ruler)
    spectral_top = int(height * 0.55)
    spectral_bottom = int(height * 0.85)
    frame[spectral_top:spectral_bottom, :] = int(spectral_mean)

    # Time ruler region at bottom 15% with periodic bright vertical ticks
    ruler_top = int(height * 0.85)
    ruler_bottom = height
    ruler_height = ruler_bottom - ruler_top
    # Dark ruler background
    frame[ruler_top:ruler_bottom, :] = 20

    # Draw periodic bright vertical ticks (1-5 px wide, >4px apart)
    x = 20
    while x < width - 20:
        tick_w = np.random.randint(1, 6)
        frame[ruler_top:ruler_bottom, x : x + tick_w] = 200
        x += tick_spacing_px

    return frame


def _make_bmode_frame(
    height: int = 600,
    width: int = 800,
    top_mean: int = 140,
    bottom_mean: int = 40,
) -> np.ndarray:
    """Create a synthetic B-mode frame (no tick marks)."""
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[: int(height * 0.62), :] = top_mean
    frame[int(height * 0.62) :, :] = bottom_mean
    return frame


def test_echonet_crop_mode_uses_center_square_for_cine_and_dicom() -> None:
    assert echonet_crop_mode_for_media("dicom") == ECHONET_CROP_CENTER_SQUARE
    assert echonet_crop_mode_for_media("mp4") == ECHONET_CROP_CENTER_SQUARE


def test_resolve_cine_roi_returns_none_for_bmode() -> None:
    """B-mode frames (no tick marks) should return None — no Doppler ROI."""
    frame = _make_bmode_frame(height=600, width=800)
    roi = resolve_cine_segment_roi_xyxy(frame)
    assert roi is None


def test_resolve_cine_roi_returns_none_for_plain_bmode_with_ui() -> None:
    """B-mode with UI elements but no periodic ticks → None."""
    height, width = 800, 1276
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[: int(height * 0.62), 350:910] = 130
    frame[: int(height * 0.62), 1220:1270] = 200
    frame[int(height * 0.62) :, :] = 40
    roi = resolve_cine_segment_roi_xyxy(frame)
    assert roi is None


def test_resolve_cine_roi_detects_doppler_frame() -> None:
    """Doppler frame with ticks → valid ROI."""
    frame = _make_doppler_frame(height=600, width=800, tick_spacing_px=30)
    roi = resolve_cine_segment_roi_xyxy(frame)

    assert roi is not None
    x0, y0, x1, y1 = roi
    assert x0 >= 0.0
    assert y0 >= 0.0
    assert x1 <= 800.0
    assert y1 <= 600.0
    assert x1 > x0
    assert y1 > y0
    # ROI should cover most of the frame width (>= 90%)
    assert (x1 - x0) >= 800 * 0.9


def test_resolve_segment_roi_mp4_returns_none_for_bmode(tmp_path) -> None:
    """MP4 B-mode without DICOM tags → None (no Doppler content)."""
    frame = _make_bmode_frame(height=600, width=800)
    fake_path = tmp_path / "clip.mp4"

    roi = resolve_segment_roi_xyxy(
        frame,
        media_format="mp4",
        instance_path=fake_path,
    )
    assert roi is None


def test_resolve_segment_roi_mp4_returns_roi_for_doppler(tmp_path) -> None:
    """MP4 Doppler frame → valid ROI."""
    frame = _make_doppler_frame(height=600, width=800, tick_spacing_px=30)
    fake_path = tmp_path / "clip.mp4"

    roi = resolve_segment_roi_xyxy(
        frame,
        media_format="mp4",
        instance_path=fake_path,
    )
    assert roi is not None


def test_frozen_cine_roi_reused_across_frames() -> None:
    """When frozen_cine_roi is provided, it is returned as-is for mp4 format."""
    frame_a = _make_doppler_frame(height=600, width=800, tick_spacing_px=30)
    frame_b = _make_doppler_frame(height=600, width=800, tick_spacing_px=35)

    roi_a = resolve_cine_segment_roi_xyxy(frame_a)
    assert roi_a is not None

    roi_b_live = resolve_cine_segment_roi_xyxy(frame_b)
    assert roi_b_live is not None

    roi_b_frozen = resolve_segment_roi_xyxy(
        frame_b,
        media_format="mp4",
        frozen_cine_roi=roi_a,
    )
    assert roi_b_frozen == roi_a


def test_frozen_cine_roi_none_falls_back_to_heuristic() -> None:
    """When frozen_cine_roi is None, falls back to live detection."""
    frame = _make_doppler_frame(height=600, width=800, tick_spacing_px=30)
    roi_live = resolve_cine_segment_roi_xyxy(frame)

    roi_result = resolve_segment_roi_xyxy(
        frame,
        media_format="mp4",
        frozen_cine_roi=None,
    )
    assert roi_result == roi_live
