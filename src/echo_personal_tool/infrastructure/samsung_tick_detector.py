"""Samsung tick mark detection for sweep speed calibration.

Empirically calibrated on Samsung RS85 captures: the time-axis ruler is a
horizontal line near the bottom of the frame (y ~= 868-872 for 884-row frames)
with small vertical ticks whose spacing is LINEAR in the sweep frequency:

    spacing_px = frequency_hz / 5        (i.e. k_constant = 0.2 px per Hz)

Detector locates the row band that yields the most uniform periodic column
structure across the whole frame, so it does not depend on a hard-coded ruler
position and stays robust to banner text and the full-width Doppler axis line.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)

# Detection parameters
_BAND_HEIGHT = 7           # rows examined as a vertical tick window
_MIN_VERTICAL_HITS = 2     # bright pixels a column must stack within the band
_MAX_TICK_WIDTH_PX = 6     # reject wide structures (axis line, text glyphs)
_CLUSTER_GAP_PX = 3        # merge columns closer than this into one tick
_MIN_SPACING_PX = 4        # ticks spaced closer than this are treated as one
_MIN_TICKS = 2             # fewer detected ticks => unreliable measurement
_BRIGHTNESS_THRESHOLD = 40  # grayscale level considered "on"
_SCAN_STEP_PX = 2          # row stride while searching for the best band
_FULL_CONFIDENCE_TICK_COUNT = 20
# Samsung places the time-scale ruler at a fixed height from the bottom of the
# frame; detection is restricted to the bottom slice of the image.
_BOTTOM_SCAN_FRACTION = 0.15


@dataclass
class TickDetectionResult:
    """Result of tick mark detection."""
    tick_positions: list[float]
    spacing_px: float
    confidence: float


def _tick_score(gray: np.ndarray, y0: int, band_height: int) -> tuple | None:
    """Score a horizontal band as a candidate tick ruler.

    Returns (score, uniformity, median_gap, tick_centers) or None if the band
    does not hold a plausible ruler.
    """
    h, w = gray.shape
    y1 = min(h, y0 + band_height)
    band = gray[y0:y1, :]
    cnt = (band > _BRIGHTNESS_THRESHOLD).sum(axis=0)
    cols = np.where(cnt >= _MIN_VERTICAL_HITS)[0]
    if len(cols) < _MIN_TICKS:
        return None

    # Cluster consecutive columns into individual ticks via center-of-mass
    centers: list[float] = []
    start = cols[0]
    prev = cols[0]
    for x in cols[1:]:
        if x - prev > _CLUSTER_GAP_PX:
            width = prev - start + 1
            if width <= _MAX_TICK_WIDTH_PX:
                centers.append((start + prev) / 2.0)
            start = x
        prev = x
    width = prev - start + 1
    if width <= _MAX_TICK_WIDTH_PX:
        centers.append((start + prev) / 2.0)

    centers.sort()
    if len(centers) < _MIN_TICKS:
        return None

    gaps = np.diff(centers)
    gaps = gaps[gaps > _MIN_SPACING_PX]
    if len(gaps) < _MIN_TICKS - 1:
        return None

    median_gap = float(np.median(gaps))
    std_gap = float(np.std(gaps))
    uniformity = 1.0 - min(std_gap / median_gap, 1.0) if median_gap > 0 else 0.0
    count_factor = min(len(centers) / _FULL_CONFIDENCE_TICK_COUNT, 1.0)
    score = uniformity * count_factor
    return score, uniformity, median_gap, centers


def detect_ticks(
    pixel_array: np.ndarray,
    roi_bottom_fraction: float | None = None,
    channel_order: str = "rgb",
) -> TickDetectionResult:
    """Detect vertical tick marks in the time scale region.

    Scans the whole frame for the row band with the most uniform periodic
    column structure, which corresponds to the sweep-speed time ruler.

    Args:
        pixel_array: RGB or grayscale image as numpy array.
        roi_bottom_fraction: Deprecated, accepted for backwards compatibility.
        channel_order: Color channel order for 3D input: "rgb" (default) or
            "bgr".

    Returns:
        TickDetectionResult with positions, spacing, and confidence.
    """
    if pixel_array.ndim not in (2, 3):
        raise ValueError(f"Expected 2D or 3D array, got shape {pixel_array.shape}")
    if pixel_array.size == 0:
        raise ValueError("Input array is empty")

    if pixel_array.ndim == 3:
        if channel_order == "bgr":
            gray = 0.114 * pixel_array[..., 0] + 0.587 * pixel_array[..., 1] + 0.299 * pixel_array[..., 2]
        else:
            gray = 0.299 * pixel_array[..., 0] + 0.587 * pixel_array[..., 1] + 0.114 * pixel_array[..., 2]
    else:
        gray = pixel_array.copy()
    gray = np.asarray(gray, dtype=np.float32)

    h = gray.shape[0]
    best: tuple | None = None
    best_y0 = 0
    scan_top = int(h * (1.0 - _BOTTOM_SCAN_FRACTION))
    for y0 in range(scan_top, max(scan_top + 1, h - _BAND_HEIGHT + 1), _SCAN_STEP_PX):
        cand = _tick_score(gray, y0, _BAND_HEIGHT)
        if cand is None:
            continue
        if best is None or cand[0] > best[0]:
            best = (cand[0], cand[1], cand[2], cand[3])
            best_y0 = y0

    if best is None:
        return TickDetectionResult(tick_positions=[], spacing_px=0.0, confidence=0.0)

    _, _, spacing, centers = best
    logger.debug("Best tick ruler at y=%d: spacing=%.2f, ticks=%d", best_y0, spacing, len(centers))
    return TickDetectionResult(
        tick_positions=centers,
        spacing_px=float(spacing),
        confidence=float(best[1]),
    )