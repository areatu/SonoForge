"""Detect the spectral Doppler spectrogram region in a composite echo frame."""

from __future__ import annotations

import numpy as np


def _dark_bands(
    gray: np.ndarray, dark_threshold: float, min_rows: int, gap_tol: int = 8
) -> list[tuple[int, int]]:
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
    dark_threshold = (
        float(np.percentile(row_mean_all, 10))
        + float(np.percentile(row_mean_all, 50))
    ) / 2.0
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

    return (x0, float(y0), x1, float(y1))
