"""Detect horizontal tick marks in the depth scale strip of B-mode frames."""

from __future__ import annotations

import numpy as np


def detect_depth_scale_ticks(
    frame: np.ndarray,
    *,
    x_center: int,
    search_half_width_px: int = 15,
    min_tick_spacing_px: int = 8,
) -> list[float]:
    if frame.ndim == 3:
        gray = np.mean(frame, axis=2).astype(np.float32)
    else:
        gray = frame.astype(np.float32)

    h, w = gray.shape
    x0 = max(0, x_center - search_half_width_px)
    x1 = min(w, x_center + search_half_width_px + 1)
    strip = gray[:, x0:x1]

    if strip.size == 0 or strip.shape[1] == 0:
        return []

    row_max = np.max(strip, axis=1)
    row_median = np.median(row_max)
    row_std = np.std(row_max)

    if row_std < 2.0:
        return []

    bright_threshold = max(row_median + 1.5 * row_std, 30.0)
    bright_rows = np.where(row_max > bright_threshold)[0]

    if len(bright_rows) == 0:
        return []

    candidates = _cluster_to_tops(bright_rows, min_tick_spacing_px)

    margin_top = int(h * 0.08)
    margin_bottom = int(h * 0.05)
    candidates = [c for c in candidates if margin_top <= c < h - margin_bottom]

    return sorted(candidates)


def _cluster_to_tops(rows: np.ndarray, min_distance: float) -> list[float]:
    if len(rows) == 0:
        return []
    sorted_rows = np.sort(rows)
    clusters: list[list[float]] = [[sorted_rows[0]]]
    for r in sorted_rows[1:]:
        if r - clusters[-1][-1] <= min_distance:
            clusters[-1].append(float(r))
        else:
            clusters.append([float(r)])
    return [clusters[i][0] for i in range(len(clusters))]


def find_best_scale_column(frame: np.ndarray, x_range: tuple[int, int] = (85, 99)) -> int:
    if frame.ndim == 3:
        gray = np.mean(frame, axis=2).astype(np.float32)
    else:
        gray = frame.astype(np.float32)
    h, w = gray.shape
    x_lo = int(w * x_range[0] / 100)
    x_hi = int(w * x_range[1] / 100)
    best_x = 0
    best_count = 0
    for x_center in range(x_lo, x_hi, 5):
        ticks = detect_depth_scale_ticks(frame, x_center=x_center)
        if len(ticks) > best_count:
            best_count = len(ticks)
            best_x = x_center
    return best_x


def find_scale_ticks(frame: np.ndarray) -> list[float]:
    best_x = find_best_scale_column(frame)
    if best_x == 0:
        return []
    return detect_depth_scale_ticks(frame, x_center=best_x)
