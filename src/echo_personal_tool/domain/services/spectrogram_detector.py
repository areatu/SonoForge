"""Detect the spectral Doppler spectrogram region in a composite echo frame."""

from __future__ import annotations

import numpy as np


def detect_spectrogram_roi(
    frame: np.ndarray,
    *,
    search_top_fraction: float = 0.35,
    search_bottom_fraction: float = 0.95,
) -> tuple[float, float, float, float] | None:
    """Detect the bounding box of the spectral Doppler spectrogram.

    Scans the bottom portion of the frame for a dark rectangular region
    with horizontal grid lines (typical of Doppler spectrograms).

    Returns (x0, y0, x1, y1) in pixel coordinates, or None if not found.
    """
    if frame.ndim == 3:
        gray = np.mean(frame, axis=2).astype(np.float32)
    else:
        gray = frame.astype(np.float32)

    h, w = gray.shape
    y_start = int(h * search_top_fraction)
    y_end = int(h * search_bottom_fraction)

    if y_end <= y_start + 20:
        return None

    region = gray[y_start:y_end, :]
    if region.size == 0:
        return None

    # The spectrogram has a dark background with bright signal peaks.
    # B-mode is bright tissue. Use the brightest rows as reference.
    row_mean = np.mean(region, axis=1)

    # Find the brightest 20% of rows (B-mode reference)
    bright_ref = np.percentile(row_mean, 80)
    # Spectrogram rows are significantly darker than B-mode
    dark_threshold = bright_ref * 0.5
    spectrogram_rows = np.where(row_mean < dark_threshold)[0]

    if len(spectrogram_rows) < 10:
        return None

    # The spectrogram is a contiguous block of dark rows
    # Find the largest contiguous block
    gaps = np.diff(spectrogram_rows)
    split_points = np.where(gaps > 5)[0]

    if len(split_points) == 0:
        # Single contiguous block
        sy0 = spectrogram_rows[0]
        sy1 = spectrogram_rows[-1]
    else:
        # Find the largest block
        blocks = np.split(spectrogram_rows, split_points + 1)
        largest = max(blocks, key=len)
        if len(largest) < 10:
            return None
        sy0 = largest[0]
        sy1 = largest[-1]

    # Convert back to frame coordinates
    y0 = float(y_start + sy0)
    y1 = float(y_start + sy1)

    # Detect horizontal extent: find columns with significant content
    spectrogram_region = gray[int(y0) : int(y1), :]
    col_mean = np.mean(spectrogram_region, axis=0)

    # Spectrogram spans most of the width (excluding B-mode overlay on sides)
    bright_cols = np.where(col_mean > np.median(col_mean) * 0.3)[0]
    if len(bright_cols) < w * 0.3:
        return None

    x0 = float(bright_cols[0])
    x1 = float(bright_cols[-1])

    # Validate: spectrogram should be at least 20% of frame height
    if (y1 - y0) < h * 0.15:
        return None

    return (x0, y0, x1, y1)
