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


def _make_two_band_frame(height: int = 884, width: int = 1180) -> np.ndarray:
    """Composite with bright B-mode on top and TWO dark bands (modal):
    an upper strip (y~400-561, 162 rows) and a lower Doppler panel
    (y~704-823, 120 rows). Upper band is TALLER than lower so the old
    largest-band logic picks the wrong (upper) panel."""
    frame = np.full((height, width), 150, dtype=np.uint8)
    frame[400:562, :] = 12
    frame[704:824, :] = 12
    frame[720:740, width // 4 : 3 * width // 4] = 120
    return frame


def test_detect_prefers_lowest_of_two_bands() -> None:
    frame = _make_two_band_frame()
    roi = detect_spectrogram_roi(frame)
    assert roi is not None
    x0, y0, x1, y1 = roi
    # Prefer the lower (Doppler) panel, not the upper strip
    assert y0 >= 650
    assert y0 < y1
    assert (y1 - y0) >= 100


def test_detect_region_bounds_fallback() -> None:
    # Uniform bright frame (no visible bands) -> falls back to region_bounds
    frame = np.full((884, 1180), 200, dtype=np.uint8)
    roi = detect_spectrogram_roi(frame, region_bounds=(0.0, 100.0, 1179.0, 473.0))
    assert roi is not None
    x0, y0, x1, y1 = roi
    assert y0 == 100.0
    assert y1 == 473.0


def test_detect_no_band_no_region_returns_none() -> None:
    frame = np.full((884, 1180), 200, dtype=np.uint8)
    roi = detect_spectrogram_roi(frame)
    assert roi is None


# ── strict mode: visual proof of a spectrum (require_time_axis) ───────────


def _make_bmode_sector_with_letterbox(height: int = 600, width: int = 1200) -> np.ndarray:
    """B-mode sector frame: bright fan, black letterbox rows at the bottom.

    The letterbox is exactly the shape that used to pass as a «spectrum» and
    re-trigger the manual Doppler-calibration prompt on a plain B-mode clip.
    """
    frame = np.zeros((height, width), dtype=np.uint8)
    apex_x = width // 2
    for y in range(40, 480):
        half = 10 + int(300 * (y - 40) / 440)
        frame[y, max(0, apex_x - half) : min(width, apex_x + half)] = 150
    # rows 480..600 stay black — the letterbox «dark band»; a faint ECG trace
    # inside it (as real clips overlay one) keeps the column profile uneven,
    # which is what let the legacy extent heuristic accept the letterbox.
    frame[540:543, 100:700] = 100
    return frame


def _make_spectrum_with_ruler(height: int = 600, width: int = 1200) -> np.ndarray:
    """Composite: B-mode top, dark spectrum, bright time ruler, thin letterbox."""
    frame = np.zeros((height, width), dtype=np.uint8)
    frame[:300, :] = 80  # B-mode
    frame[300:520, :] = 15  # spectral strip
    for y in range(320, 510, 30):
        frame[y : y + 3, width // 4 : 3 * width // 4] = 120  # signal
    frame[522:534, :] = 200  # bright time-scale ruler below the strip
    frame[534:, :] = 5  # letterbox under the ruler
    return frame


def test_strict_rejects_bmode_letterbox() -> None:
    frame = _make_bmode_sector_with_letterbox()
    assert detect_spectrogram_roi(frame) is not None  # legacy: the false positive
    assert detect_spectrogram_roi(frame, require_time_axis=True) is None


def test_strict_rejects_dark_band_without_ruler() -> None:
    frame = _make_composite_frame()
    assert detect_spectrogram_roi(frame) is not None  # legacy keeps working
    assert detect_spectrogram_roi(frame, require_time_axis=True) is None


def test_strict_detects_spectrum_with_ruler() -> None:
    frame = _make_spectrum_with_ruler()
    roi = detect_spectrogram_roi(frame, require_time_axis=True)
    assert roi is not None
    x0, y0, x1, y1 = roi
    assert 280 <= y0 < 330  # the spectral strip, not the letterbox below the ruler
    assert y1 > 520  # the returned box includes the ruler
    assert x1 > x0


def test_strict_skips_region_bounds_fallback() -> None:
    frame = np.full((884, 1180), 200, dtype=np.uint8)
    roi = detect_spectrogram_roi(
        frame, region_bounds=(0.0, 100.0, 1179.0, 473.0), require_time_axis=True
    )
    assert roi is None
