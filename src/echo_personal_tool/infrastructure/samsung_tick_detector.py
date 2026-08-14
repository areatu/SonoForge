"""Samsung tick mark detection for sweep speed calibration.

Empirically calibrated on Samsung RS85 captures: the time-axis ruler is a
horizontal line near the bottom of the frame (y ~= 868-872 for 884-row frames)
with small vertical ticks whose spacing is LINEAR in the sweep frequency:

    spacing_px = frequency_hz / 5        (i.e. k_constant = 0.2 px per Hz)

Detector locates the row band that yields the most uniform periodic column
structure across the whole frame, so it does not depend on a hard-coded ruler
position and stays robust to banner text and the full-width Doppler axis line.

Samsung Doppler frames also have velocity scales on the left and right sides
with horizontal ticks. These are used to refine ROI boundaries.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)

# Detection parameters
_BAND_HEIGHT = 7  # rows examined as a vertical tick window
_MIN_VERTICAL_HITS = 2  # bright pixels a column must stack within the band
_MAX_TICK_WIDTH_PX = 6  # reject wide structures (axis line, text glyphs)
_CLUSTER_GAP_PX = 3  # merge columns closer than this into one tick
_MIN_SPACING_PX = 4  # ticks spaced closer than this are treated as one
_MIN_TICKS = 5  # fewer detected ticks => unreliable (B-mode can have 2-3 false ticks)
_BRIGHTNESS_THRESHOLD = 40  # grayscale level considered "on"
_SCAN_STEP_PX = 2  # row stride while searching for the best band
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
    band_y: float = 0.0  # y position of the detected tick band (center)


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
    # band_y is the center of the detected band (where the ticks are)
    band_y = float(best_y0) + _BAND_HEIGHT / 2.0
    logger.debug(
        "Best tick ruler at y=%d (band_y=%.1f): spacing=%.2f, ticks=%d",
        best_y0,
        band_y,
        spacing,
        len(centers),
    )
    return TickDetectionResult(
        tick_positions=centers,
        spacing_px=float(spacing),
        confidence=float(best[1]),
        band_y=band_y,
    )


# ---------------------------------------------------------------------------
# Velocity scale detection (vertical scales on left/right sides)
# ---------------------------------------------------------------------------
# Samsung velocity scales are vertical axes on the left and right sides of the
# spectral band with horizontal ticks marking velocity values.
# The scales are NOT at the frame edges - they're just outside the spectral band.

_VELOCITY_TICK_MIN_HEIGHT = 2  # minimum bright pixels in a row for a tick
_VELOCITY_TICK_MAX_HEIGHT = 8  # reject wide horizontal structures
_VELOCITY_TICK_CLUSTER_GAP = 4  # merge rows closer than this
_VELOCITY_MIN_TICKS = 4  # fewer ticks => unreliable (need real velocity scale)
_VELOCITY_BRIGHTNESS_THRESHOLD = 40
_VELOCITY_SEARCH_WIDTH_PX = 30  # search width around each scale
_VELOCITY_MIN_UNIFORMITY = 0.7  # minimum uniformity for reliable scale


@dataclass
class VelocityScaleResult:
    """Detected velocity scale on one side of the frame."""

    tick_rows: list[float]
    top_y: float
    bottom_y: float
    axis_top_y: float  # top of the axis line (full velocity scale height)
    axis_bottom_y: float  # bottom of the axis line
    x_center: float
    confidence: float


def _detect_vertical_scale_at_x(
    gray: np.ndarray,
    x_center: int,
    search_half_width: int = _VELOCITY_SEARCH_WIDTH_PX,
    y_range: tuple[int, int] | None = None,
) -> VelocityScaleResult | None:
    """Detect a vertical velocity scale near x_center.

    Looks for a vertical axis line with horizontal ticks extending from it.
    The scale is a thin vertical bright line with periodic horizontal marks.

    Args:
        y_range: Optional (y0, y1) to limit vertical search. When provided,
            the axis-brightness threshold uses the band height instead of
            full frame height, fixing detection on narrow spectral bands.
    """
    h, w = gray.shape
    x0 = max(0, x_center - search_half_width)
    x1 = min(w, x_center + search_half_width + 1)

    if y_range is not None:
        y0, y1 = y_range
        y0 = max(0, y0)
        y1 = min(h - 1, y1)
        search_h = y1 - y0 + 1
    else:
        y0, y1 = 0, h - 1
        search_h = h

    strip = gray[y0 : y1 + 1, x0:x1]

    if strip.size == 0:
        return None

    # Look for the vertical axis line: a column with many bright pixels
    col_bright = (strip > _VELOCITY_BRIGHTNESS_THRESHOLD).sum(axis=0)
    # Use search height for threshold, not full frame height, so narrow
    # spectral bands (e.g. 86 px in an 800 px frame) are still detected.
    axis_candidates = np.where(col_bright > search_h * 0.3)[0]

    if len(axis_candidates) == 0:
        return None

    # Use the center of the axis region
    axis_x_local = int(np.mean(axis_candidates))
    axis_x_global = x0 + axis_x_local

    # Find the full vertical extent of the axis line.
    # The axis is a continuous vertical bright column; find its top and bottom.
    axis_col = strip[:, axis_x_local]
    axis_bright_rows = np.where(axis_col > _VELOCITY_BRIGHTNESS_THRESHOLD)[0]
    if len(axis_bright_rows) == 0:
        return None
    # Cluster consecutive bright rows to find the main axis extent
    axis_clusters: list[list[int]] = [[axis_bright_rows[0]]]
    for r in axis_bright_rows[1:]:
        if r - axis_clusters[-1][-1] <= 3:
            axis_clusters[-1].append(r)
        else:
            axis_clusters.append([r])
    # Use the longest cluster as the axis extent
    longest_cluster = max(axis_clusters, key=len)
    axis_top_y = float(y0 + longest_cluster[0])
    axis_bottom_y = float(y0 + longest_cluster[-1])

    # Now look for horizontal ticks extending from the axis
    # A tick is a short horizontal bright segment starting at the axis
    # Look for rows where there's a bright pixel at the axis and a few pixels away
    tick_rows = []
    for y in range(y0, y1 + 1):
        # Check if there's a bright pixel at the axis
        if gray[y, axis_x_global] <= _VELOCITY_BRIGHTNESS_THRESHOLD:
            continue
        # Look for bright pixels extending to the right (for left scale) or left (for right scale)
        # We check both directions to be generic
        has_extension = False
        # Check right side
        for dx in range(3, min(15, w - axis_x_global)):
            if gray[y, axis_x_global + dx] > _VELOCITY_BRIGHTNESS_THRESHOLD:
                has_extension = True
                break
        if not has_extension:
            # Check left side
            for dx in range(3, min(15, axis_x_global)):
                if gray[y, axis_x_global - dx] > _VELOCITY_BRIGHTNESS_THRESHOLD:
                    has_extension = True
                    break
        if has_extension:
            tick_rows.append(float(y))

    if len(tick_rows) < _VELOCITY_MIN_TICKS:
        return None

    # Cluster consecutive rows into ticks
    clusters: list[list[float]] = [[tick_rows[0]]]
    for r in tick_rows[1:]:
        if r - clusters[-1][-1] <= _VELOCITY_TICK_CLUSTER_GAP:
            clusters[-1].append(r)
        else:
            clusters.append([r])

    # Get center of each cluster
    tick_centers = [float(sum(c) / len(c)) for c in clusters]
    # Filter out ticks that are too thick
    tick_centers = [tc for tc, c in zip(tick_centers, clusters) if len(c) <= _VELOCITY_TICK_MAX_HEIGHT]

    if len(tick_centers) < _VELOCITY_MIN_TICKS:
        return None

    # Compute vertical extent and uniformity
    top_y = min(tick_centers)
    bottom_y = max(tick_centers)
    gaps = np.diff(tick_centers)
    if len(gaps) == 0:
        return None
    median_gap = float(np.median(gaps))
    std_gap = float(np.std(gaps))
    uniformity = 1.0 - min(std_gap / median_gap, 1.0) if median_gap > 0 else 0.0

    if uniformity < _VELOCITY_MIN_UNIFORMITY:
        return None

    count_factor = min(len(tick_centers) / 10.0, 1.0)
    confidence = uniformity * count_factor

    return VelocityScaleResult(
        tick_rows=tick_centers,
        top_y=top_y,
        bottom_y=bottom_y,
        axis_top_y=axis_top_y,
        axis_bottom_y=axis_bottom_y,
        x_center=float(axis_x_global),
        confidence=confidence,
    )


def detect_velocity_scales(
    pixel_array: np.ndarray,
    band_x_range: tuple[float, float] | None = None,
    band_y: float | None = None,
    channel_order: str = "rgb",
) -> tuple[VelocityScaleResult | None, VelocityScaleResult | None]:
    """Detect left and right velocity scales flanking the spectral band.

    Args:
        pixel_array: RGB or grayscale image.
        band_x_range: Optional (x0, x1) of the spectral band. If provided,
            scales are searched just outside this range. Otherwise searches
            the outer 20% of frame width.
        band_y: Optional y-center of the time scale (bottom of spectral band).
            If provided, velocity scale search is limited to the vertical extent
            of the spectral band rather than the full frame height.
        channel_order: Color channel order for 3D input.

    Returns:
        Tuple of (left_scale, right_scale). Each is None if not detected.
    """
    if pixel_array.ndim not in (2, 3):
        return None, None
    if pixel_array.size == 0:
        return None, None

    if pixel_array.ndim == 3:
        if channel_order == "bgr":
            gray = 0.114 * pixel_array[..., 0] + 0.587 * pixel_array[..., 1] + 0.299 * pixel_array[..., 2]
        else:
            gray = 0.299 * pixel_array[..., 0] + 0.587 * pixel_array[..., 1] + 0.114 * pixel_array[..., 2]
    else:
        gray = pixel_array.copy()
    gray = np.asarray(gray, dtype=np.float32)

    h, w = gray.shape

    if band_x_range is not None:
        band_x0, band_x1 = band_x_range
        # Left scale: just to the left of the band
        left_x_center = max(_VELOCITY_SEARCH_WIDTH_PX, int(band_x0) - _VELOCITY_SEARCH_WIDTH_PX)
        # Right scale: just to the right of the band
        right_x_center = min(w - _VELOCITY_SEARCH_WIDTH_PX - 1, int(band_x1) + _VELOCITY_SEARCH_WIDTH_PX)
    else:
        # Search in outer regions
        left_x_center = int(w * 0.1)
        right_x_center = int(w * 0.9)

    # Limit vertical search to spectral band height when band_y is known.
    # Without this, the axis-brightness threshold (30% of full frame height)
    # fails for narrow spectral bands (e.g. 86px in an 800px frame = 10.75%).
    if band_y is not None:
        y_range = (0, min(h - 1, int(band_y) + _VELOCITY_SEARCH_WIDTH_PX))
    else:
        y_range = (0, h - 1)

    left_scale = _detect_vertical_scale_at_x(gray, left_x_center, y_range=y_range)
    right_scale = _detect_vertical_scale_at_x(gray, right_x_center, y_range=y_range)

    return left_scale, right_scale


@dataclass
class SamsungDopplerScales:
    """Complete set of detected scales for a Samsung Doppler frame."""

    time_scale: TickDetectionResult
    left_velocity_scale: VelocityScaleResult | None
    right_velocity_scale: VelocityScaleResult | None
    refined_roi: tuple[float, float, float, float] | None = field(default=None)
    # refined_roi is (x0, y0, x1, y1) or None if detection failed


def detect_samsung_doppler_scales(
    pixel_array: np.ndarray,
    channel_order: str = "rgb",
) -> SamsungDopplerScales:
    """Detect all Doppler scales and compute refined ROI for Samsung frames.

    Detects:
    - Time scale at bottom (vertical ticks) for sweep frequency
    - Left velocity scale (horizontal ticks) for left ROI boundary
    - Right velocity scale (horizontal ticks) for right ROI boundary

    Returns SamsungDopplerScales with refined ROI boundaries based on scales.
    """
    time_scale = detect_ticks(pixel_array, channel_order=channel_order)

    # First pass: get rough band x range from time scale ticks
    band_x_range = None
    if time_scale.confidence >= 0.3 and len(time_scale.tick_positions) >= 2:
        # The time scale spans the width of the spectral band
        band_x_min = min(time_scale.tick_positions)
        band_x_max = max(time_scale.tick_positions)
        # Add some margin for the velocity scales
        margin = (band_x_max - band_x_min) * 0.15
        band_x_range = (band_x_min - margin, band_x_max + margin)

    # Detect velocity scales using the band x range and time scale y position
    left_scale, right_scale = detect_velocity_scales(
        pixel_array,
        band_x_range=band_x_range,
        band_y=time_scale.band_y,
        channel_order=channel_order,
    )

    # Compute refined ROI from detected scales
    refined_roi = None

    # Require BOTH time scale AND at least one velocity scale for valid Doppler.
    # Without velocity scales, it's likely B-mode, not spectral Doppler.
    # Time scale must have >= 5 ticks (real Doppler has 10-30+).
    # Velocity scale must have >= 4 ticks with high uniformity.
    has_time_scale = time_scale.confidence >= 0.4 and len(time_scale.tick_positions) >= 5
    has_left_scale = left_scale is not None and left_scale.confidence >= 0.4 and len(left_scale.tick_rows) >= 4
    has_right_scale = right_scale is not None and right_scale.confidence >= 0.4 and len(right_scale.tick_rows) >= 4

    if has_time_scale and (has_left_scale or has_right_scale):
        h, w = pixel_array.shape[:2] if pixel_array.ndim == 2 else pixel_array.shape[:2]

        # Bottom boundary: y position of the time scale (from detected band_y)
        bottom_y = time_scale.band_y

        # Left boundary: from left velocity scale
        if has_left_scale:
            left_x = left_scale.x_center + 5  # Just inside the scale
        else:
            # Default: leftmost tick position minus margin
            left_x = min(time_scale.tick_positions) - 10

        # Right boundary: from right velocity scale
        if has_right_scale:
            right_x = right_scale.x_center - 5  # Just inside the scale
        else:
            # Default: rightmost tick position plus margin
            right_x = max(time_scale.tick_positions) + 10

        # Top boundary: top of the highest velocity scale AXIS LINE.
        # The axis line extends through the full spectral band height,
        # while ticks may not reach the very top/bottom.
        top_y_candidates = []
        if has_left_scale:
            top_y_candidates.append(left_scale.axis_top_y)
        if has_right_scale:
            top_y_candidates.append(right_scale.axis_top_y)

        if top_y_candidates:
            top_y = min(top_y_candidates)
        else:
            # Should not happen since we require at least one scale
            top_y = bottom_y * 0.3

        # --- ROI constraints ---
        # 1. Width must be >= 90% of frame width
        roi_width = right_x - left_x
        min_width = w * 0.9
        if roi_width < min_width:
            # Expand symmetrically to meet minimum width
            deficit = min_width - roi_width
            left_x -= deficit / 2
            right_x += deficit / 2
            # Clamp to frame bounds
            left_x = max(0.0, left_x)
            right_x = min(float(w), right_x)

        # 2. Height must be 30%-70% of frame height
        roi_height = bottom_y - top_y
        min_height = h * 0.3
        max_height = h * 0.7
        if roi_height < min_height:
            # Expand upward (keep bottom fixed at time scale)
            top_y = bottom_y - min_height
        elif roi_height > max_height:
            # Shrink from top (keep bottom fixed)
            top_y = bottom_y - max_height

        # 3. ROI must be in lower half of frame
        if top_y < h * 0.5:
            top_y = h * 0.5
        # Ensure bottom doesn't exceed frame
        bottom_y = min(bottom_y, float(h))

        # Final validation
        if right_x > left_x and bottom_y > top_y:
            refined_roi = (left_x, top_y, right_x, bottom_y)
            logger.debug(
                "Refined ROI from scales: (%.1f, %.1f, %.1f, %.1f)",
                left_x,
                top_y,
                right_x,
                bottom_y,
            )

    return SamsungDopplerScales(
        time_scale=time_scale,
        left_velocity_scale=left_scale,
        right_velocity_scale=right_scale,
        refined_roi=refined_roi,
    )
