from __future__ import annotations

import numpy as np

from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi
from echo_personal_tool.domain.services.depth_scale_detector import (
    detect_depth_scale_ticks,
    find_scale_ticks_in_roi,
)


def _synthetic_b_mode_with_ticks(
    height: int = 200,
    width: int = 120,
    tick_spacing: int = 20,
    tick_width: int = 3,
    x_center: int = 110,
) -> np.ndarray:
    frame = np.zeros((height, width), dtype=np.uint8)
    for y in range(tick_spacing, height - tick_spacing, tick_spacing):
        x0 = max(0, x_center - tick_width // 2)
        x1 = min(width, x_center + tick_width // 2 + 1)
        frame[y, x0:x1] = 255
    return frame


def test_detects_regular_ticks() -> None:
    frame = _synthetic_b_mode_with_ticks(height=200, tick_spacing=20)
    ticks = detect_depth_scale_ticks(frame, x_center=110, search_half_width_px=8)
    assert len(ticks) >= 5
    spacings = [ticks[i + 1] - ticks[i] for i in range(len(ticks) - 1)]
    assert all(abs(s - 20) <= 2 for s in spacings)


def test_returns_empty_for_blank_frame() -> None:
    frame = np.zeros((200, 120), dtype=np.uint8)
    ticks = detect_depth_scale_ticks(frame, x_center=110)
    assert ticks == []


def test_ignores_center_region() -> None:
    frame = np.zeros((200, 120), dtype=np.uint8)
    for y in range(20, 200, 20):
        frame[y, 108:113] = 255
    ticks = detect_depth_scale_ticks(frame, x_center=60, search_half_width_px=8)
    assert ticks == []


def test_detects_thin_ticks_with_noise() -> None:
    rng = np.random.default_rng(42)
    frame = rng.integers(0, 40, size=(300, 150), dtype=np.uint8)
    for y in range(20, 280, 25):
        frame[y, 135:142] = rng.integers(150, 255, size=(7,), dtype=np.uint8)
    ticks = detect_depth_scale_ticks(frame, x_center=138, search_half_width_px=10)
    assert len(ticks) >= 5


def _make_frame_with_ticks(height=400, width=600, tick_positions=None, tick_width=30):
    """Create a synthetic frame with bright horizontal tick marks."""
    frame = np.zeros((height, width), dtype=np.uint8)
    if tick_positions is None:
        tick_positions = [50, 100, 150, 200, 250, 300, 350]
    for y in tick_positions:
        frame[y, 100:100 + tick_width] = 200
    return frame


class TestFindScaleTicksInRoi:
    def test_detects_ticks_in_roi(self):
        """Ticks within ROI are detected with correct Y positions."""
        frame = _make_frame_with_ticks()
        roi = DopplerSpectrogramRoi(x0=80, y0=0, width=80, height=400)
        ticks = find_scale_ticks_in_roi(frame, roi)
        assert len(ticks) >= 3
        # Ticks should be near expected positions
        for expected in [50, 100, 150]:
            assert any(abs(t - expected) < 5 for t in ticks)

    def test_ignores_ticks_outside_roi(self):
        """Ticks outside ROI horizontal range are not detected."""
        frame = _make_frame_with_ticks()
        # ROI far from tick column (ticks at x=100-130, ROI at x=300-380)
        roi = DopplerSpectrogramRoi(x0=300, y0=0, width=80, height=400)
        ticks = find_scale_ticks_in_roi(frame, roi)
        assert len(ticks) == 0

    def test_empty_roi(self):
        """Zero-width ROI returns empty list."""
        frame = _make_frame_with_ticks()
        roi = DopplerSpectrogramRoi(x0=100, y0=0, width=0, height=400)
        ticks = find_scale_ticks_in_roi(frame, roi)
        assert ticks == []
