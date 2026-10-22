"""Detect horizontal grid lines in a Doppler spectrogram ROI."""

from __future__ import annotations

import numpy as np


def detect_doppler_grid_lines(
    frame: np.ndarray,
    *,
    x0: int,
    y0: int,
    width: int,
    height: int,
    min_line_spacing_px: int = 10,
) -> list[float]:
    """Detect horizontal grid lines inside a spectrogram region.

    Returns sorted Y positions (in frame coordinates) of detected grid lines.
    Grid lines are brighter horizontal bands spanning the full ROI width,
    typical of velocity scale markings on Doppler spectrograms.
    """
    if frame.ndim == 3:
        gray = np.mean(frame, axis=2).astype(np.float32)
    else:
        gray = frame.astype(np.float32)

    h, w = gray.shape
    rx0 = max(0, int(x0))
    ry0 = max(0, int(y0))
    rx1 = min(w, rx0 + int(width))
    ry1 = min(h, ry0 + int(height))

    if rx1 <= rx0 or ry1 <= ry0:
        return []

    strip = gray[ry0:ry1, rx0:rx1]
    if strip.size == 0:
        return []

    # Mean intensity per row across the full ROI width
    row_mean = np.mean(strip, axis=1)

    # Grid lines are brighter than the dark spectral background.
    # Use a threshold based on the row-level distribution.
    row_median = np.median(row_mean)
    row_std = np.std(row_mean)

    if row_std < 2.0:
        return []

    bright_threshold = max(row_median + 1.0 * row_std, 25.0)
    bright_rows = np.where(row_mean > bright_threshold)[0]

    if len(bright_rows) == 0:
        return []

    # Cluster adjacent bright rows into single grid line positions
    candidates = _cluster_to_centers(bright_rows, min_line_spacing_px)

    # Filter out top/bottom margins
    margin_top = int(strip.shape[0] * 0.05)
    margin_bottom = int(strip.shape[0] * 0.05)
    candidates = [ry0 + c for c in candidates if margin_top <= c < strip.shape[0] - margin_bottom]

    return sorted(candidates)


def _cluster_to_centers(rows: np.ndarray, min_distance: float) -> list[float]:
    """Cluster adjacent bright rows and return center of each cluster."""
    if len(rows) == 0:
        return []
    sorted_rows = np.sort(rows)
    clusters: list[list[float]] = [[float(sorted_rows[0])]]
    for r in sorted_rows[1:]:
        if r - clusters[-1][-1] <= min_distance:
            clusters[-1].append(float(r))
        else:
            clusters.append([float(r)])
    return [sum(c) / len(c) for c in clusters]
