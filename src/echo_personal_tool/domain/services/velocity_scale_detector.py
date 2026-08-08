"""Detect tick marks on the Doppler velocity scale strip (right of spectrogram)."""

from __future__ import annotations

import numpy as np

from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi


def _cluster_to_tops(rows: np.ndarray, min_distance: float) -> list[float]:
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
    return [clusters[i][0] for i in range(len(clusters))]


def detect_velocity_scale_ticks(
    frame: np.ndarray,
    *,
    roi: DopplerSpectrogramRoi,
    strip_width_px: int = 40,
    min_tick_spacing_px: int = 5,
) -> list[float]:
    """Detect y-positions of velocity-scale tick marks in the strip right of *roi*.

    Returns sorted y-positions (frame coordinates). Empty list when none found.
    """
    if frame.ndim == 3:
        gray = np.mean(frame, axis=2).astype(np.float32)
    else:
        gray = frame.astype(np.float32)

    h, w = gray.shape
    strip_x0 = min(int(roi.x1), w - 1)
    strip_x1 = min(strip_x0 + strip_width_px, w)
    if strip_x1 <= strip_x0:
        return []

    y0 = max(0, int(roi.y0))
    y1 = min(h, int(roi.y0 + roi.height))
    sub = gray[y0:y1, strip_x0:strip_x1]
    if sub.size == 0:
        return []

    col_max = np.max(sub, axis=1)
    row_median = np.median(col_max)
    row_std = np.std(col_max)
    if row_std < 2.0:
        return []

    bright_threshold = max(row_median + 1.5 * row_std, 30.0)
    bright_rows = np.where(col_max > bright_threshold)[0]
    if len(bright_rows) == 0:
        return []

    candidates = _cluster_to_tops(bright_rows, min_tick_spacing_px)
    margin_top = int(sub.shape[0] * 0.04)
    margin_bottom = int(sub.shape[0] * 0.04)
    candidates = [c for c in candidates if margin_top <= c < sub.shape[0] - margin_bottom]
    return sorted(float(y0 + c) for c in candidates)