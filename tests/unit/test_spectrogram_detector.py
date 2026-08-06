"""Tests for spectrogram_detector."""

from __future__ import annotations

import numpy as np

from echo_personal_tool.domain.services.spectrogram_detector import (
    detect_spectrogram_roi,
)


def _make_composite_frame(
    height: int = 600,
    width: int = 1200,
    bmode_height: float = 0.5,
    spec_bg_intensity: float = 15.0,
    bmode_intensity: float = 80.0,
) -> np.ndarray:
    """Create a synthetic composite frame with B-mode top and spectrogram bottom."""
    frame = np.zeros((height, width), dtype=np.uint8)

    # B-mode region (top): bright tissue-like
    bmode_end = int(height * bmode_height)
    frame[:bmode_end, :] = bmode_intensity

    # Spectrogram region (bottom): dark background with some signal
    spec_start = bmode_end
    frame[spec_start:, :] = spec_bg_intensity

    # Add some bright signal peaks in spectrogram
    for y in range(spec_start + 20, height - 20, 40):
        frame[y : y + 3, width // 4 : 3 * width // 4] = 120

    return frame


def test_detect_spectrogram_basic():
    frame = _make_composite_frame()
    roi = detect_spectrogram_roi(frame)
    assert roi is not None
    x0, y0, x1, y1 = roi
    assert y0 > 200  # should be in the bottom half
    assert y1 > y0
    assert x1 > x0


def test_detect_spectrogram_no_spectrogram():
    # Uniform bright frame — no spectrogram
    frame = np.full((600, 1200), 80, dtype=np.uint8)
    roi = detect_spectrogram_roi(frame)
    assert roi is None


def test_detect_spectrogram_small_frame():
    frame = _make_composite_frame(height=50, width=100)
    roi = detect_spectrogram_roi(frame)
    # Small frame may or may not detect — just shouldn't crash
    assert roi is None or isinstance(roi, tuple)


def test_detect_spectrogram_returns_frame_coords():
    frame = _make_composite_frame(height=800, width=1600)
    roi = detect_spectrogram_roi(frame)
    assert roi is not None
    x0, y0, x1, y1 = roi
    assert 0 <= x0 < 1600
    assert 0 <= y0 < 800
    assert x0 < x1 <= 1600
    assert y0 < y1 <= 800
