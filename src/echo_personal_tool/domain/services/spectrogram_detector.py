"""Detect the spectral Doppler spectrogram region in a composite echo frame."""

from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)


def _dark_bands(gray: np.ndarray, dark_threshold: float, min_rows: int, gap_tol: int = 8) -> list[tuple[int, int]]:
    """Return [(y0, y1), ...] dark row bands, bridging gaps of <= gap_tol.

    Bridges thin bright ruler/grid lines so a Doppler panel stays one band.
    """
    row_mean = np.mean(gray, axis=1)
    dark = row_mean < dark_threshold
    bands: list[tuple[int, int]] = []
    start: int | None = None
    in_band = False
    gap = 0
    for y, is_dark in enumerate(dark):
        if is_dark and not in_band:
            start = y
            in_band = True
            gap = 0
        elif is_dark and in_band:
            gap = 0
        elif not is_dark and in_band:
            gap += 1
            if gap > gap_tol:
                if y - gap_tol - start >= min_rows:
                    bands.append((start, y - gap_tol))
                in_band = False
    if in_band and len(gray) - start >= min_rows:
        bands.append((start, len(gray)))
    return bands


def _extend_to_time_scale(gray: np.ndarray, dark_band_y1: int) -> int:
    """Extend the dark band bottom downward to include the time scale ruler.

    The spectral Doppler band is DARK, and the time scale ruler sits BELOW
    it as a thin bright horizontal axis line with small vertical ticks.
    B-mode frames have a black strip at the bottom but NO bright axis line.

    This function scans rows below the dark band for the axis line and
    returns the extended y1 that includes the ruler.
    """
    h, w = gray.shape
    # Scan up to 80px below the dark band (typical ruler height is 10-40px).
    scan_limit = min(h, dark_band_y1 + 80)
    if dark_band_y1 >= scan_limit:
        return dark_band_y1

    # Compute brightness profile of rows below the dark band.
    rows_below = gray[dark_band_y1:scan_limit, :]
    if rows_below.size == 0:
        return dark_band_y1
    row_means = np.mean(rows_below, axis=1)

    # The dark band is near-black; the time scale axis is a bright line.
    # Find the first row with a significant brightness jump (>20 levels above
    # the dark band mean).
    dark_mean = float(np.mean(gray[max(0, dark_band_y1 - 20) : dark_band_y1, :])) if dark_band_y1 > 20 else 40.0
    bright_threshold = max(dark_mean + 20.0, 50.0)

    for i, mean_val in enumerate(row_means):
        if mean_val > bright_threshold:
            # Found the axis line. The ruler extends a few rows below.
            # Return y1 as the axis line row + small margin for ticks.
            extended_y1 = dark_band_y1 + i + 8
            logger.debug(
                "_extend_to_time_scale: extended y1 from %d to %d (axis at row %d, mean=%.1f)",
                dark_band_y1,
                extended_y1,
                dark_band_y1 + i,
                mean_val,
            )
            return min(extended_y1, h)

    return dark_band_y1


def detect_spectrogram_roi(
    frame: np.ndarray,
    *,
    search_top_fraction: float = 0.35,
    search_bottom_fraction: float = 0.95,
    region_bounds: tuple[float, float, float, float] | None = None,
) -> tuple[float, float, float, float] | None:
    """Locate the spectral Doppler spectrogram bounding box.

    Scans the full frame height for contiguous dark bands and returns the
    bounding box of the *lowest* band broad enough to be a Doppler panel
    (Doppler panels sit at the bottom of composite echo frames). If no band is
    found, falls back to ``region_bounds`` when supplied; otherwise ``None``.

    Returns (x0, y0, x1, y1) in pixel coordinates.
    """
    if frame.ndim == 3:
        a = np.asarray(frame)
        if a.shape[-1] in (1, 3, 4):
            gray = np.mean(a, axis=2).astype(np.float32)
        else:
            gray = a[0].astype(np.float32)
    else:
        gray = frame.astype(np.float32)

    h, w = gray.shape
    if h < 30 or w < 30:
        return None

    band_min_rows = max(10, int(h * 0.10))
    row_mean_all = np.mean(gray, axis=1)
    dark_threshold = (float(np.percentile(row_mean_all, 10)) + float(np.percentile(row_mean_all, 50))) / 2.0
    if dark_threshold <= 1.0:
        if region_bounds is not None:
            return tuple(float(v) for v in region_bounds)
        return None

    bands = _dark_bands(gray, dark_threshold, band_min_rows)
    if not bands:
        if region_bounds is not None:
            return tuple(float(v) for v in region_bounds)
        return None

    # Prefer the lowest band (Doppler panel at the bottom).
    y0, y1 = bands[-1]

    # Detect horizontal extent within the chosen band.
    band_region = gray[int(y0) : int(y1), :]
    col_mean = np.mean(band_region, axis=0)
    bright_cols = np.where(col_mean > np.median(col_mean) * 0.3)[0]
    if len(bright_cols) < w * 0.3:
        if region_bounds is not None:
            return tuple(float(v) for v in region_bounds)
        return None

    x0 = float(bright_cols[0])
    x1 = float(bright_cols[-1] + 1)

    if (y1 - y0) < h * 0.10:
        if region_bounds is not None:
            return tuple(float(v) for v in region_bounds)
        return None

    # Extend y1 downward to include the time scale ruler below the dark band.
    # The ruler is a thin bright horizontal axis line with vertical ticks.
    y1 = _extend_to_time_scale(gray, y1)

    return (x0, float(y0), x1, float(y1))
