"""Open-arc contour geometry utilities."""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from scipy.interpolate import splev, splprep

DEFAULT_NODE_COUNT = 32

SIGMA_SCREEN_PX = 40.0
SENSITIVITY_K = 1.5
WEIGHT_ACTIVE_THRESHOLD = 0.1
MIN_DELTA_NORM = 1e-3


def sigma_from_view_range(
    view_range_width: float,
    viewport_width_px: float,
    *,
    sigma_screen_px: float = SIGMA_SCREEN_PX,
) -> float:
    """Image-space Gaussian σ for a constant screen-brush radius."""
    viewport = max(float(viewport_width_px), 1.0)
    scale = float(view_range_width) / viewport
    return sigma_screen_px * scale


def gaussian_weights(
    points: Sequence[tuple[float, float]],
    cursor: tuple[float, float],
    sigma: float,
    pinned_indices: frozenset[int] = frozenset(),
) -> np.ndarray:
    """Vectorized Gaussian RBF weights from control points to cursor."""
    if not points:
        return np.array([], dtype=np.float64)

    coords = np.asarray(points, dtype=np.float64)
    cursor_xy = np.asarray(cursor, dtype=np.float64)
    diff = coords - cursor_xy
    distances_sq = np.sum(diff * diff, axis=1)

    safe_sigma = max(float(sigma), 1e-6)
    weights = np.exp(-distances_sq / (2.0 * safe_sigma * safe_sigma))

    if pinned_indices:
        for index in pinned_indices:
            if 0 <= index < len(weights):
                weights[index] = 0.0
    return weights


def apply_gaussian_displacement(
    points: Sequence[tuple[float, float]],
    delta: tuple[float, float],
    weights: np.ndarray,
    *,
    sensitivity_k: float = SENSITIVITY_K,
) -> list[tuple[float, float]]:
    """Apply incremental cursor delta with per-point Gaussian weights."""
    if not points:
        return []

    coords = np.asarray(points, dtype=np.float64)
    delta_xy = np.asarray(delta, dtype=np.float64) * float(sensitivity_k)
    shifted = coords + weights[:, np.newaxis] * delta_xy
    return [(float(x), float(y)) for x, y in shifted]


def apex_point(
    arc: Sequence[tuple[float, float]],
    annulus: tuple[tuple[float, float], tuple[float, float]],
) -> tuple[float, float]:
    """Return the point on the arc farthest from the annulus line."""
    if not arc:
        raise ValueError("arc must contain at least one point")

    start, end = annulus
    return max(
        arc,
        key=lambda point: point_line_distance(point, start, end),
    )


def long_axis_endpoints(
    arc: Sequence[tuple[float, float]],
    annulus: tuple[tuple[float, float], tuple[float, float]],
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Base-to-tip long axis endpoints defined by annulus midpoint and apex."""
    base_start, base_end = annulus
    base = (
        (base_start[0] + base_end[0]) / 2.0,
        (base_start[1] + base_end[1]) / 2.0,
    )
    return base, apex_point(arc, annulus)


def resample_open_arc(
    points: list[tuple[float, float]],
    *,
    num_nodes: int = DEFAULT_NODE_COUNT,
) -> list[tuple[float, float]]:
    """Resample open arc to num_nodes with equal arc-length spacing; endpoints fixed."""
    if num_nodes <= 0:
        return []
    if not points:
        return []
    if len(points) == 1:
        return [points[0]] * num_nodes
    if len(points) == 2:
        return _resample_polyline(points, num_nodes=num_nodes)

    dense = sample_spline(points, num_samples=max(num_nodes * 8, 64))
    return _resample_polyline(dense, num_nodes=num_nodes)


def move_node_and_resample(
    points: list[tuple[float, float]],
    *,
    node_index: int,
    x: float,
    y: float,
    num_nodes: int = DEFAULT_NODE_COUNT,
) -> list[tuple[float, float]]:
    """Move one control node, fit spline, return equal-spaced resample."""
    if not points:
        return []
    updated = list(points)
    if node_index < 0 or node_index >= len(updated):
        return resample_open_arc(updated, num_nodes=num_nodes)
    updated[node_index] = (float(x), float(y))
    return resample_open_arc(updated, num_nodes=num_nodes)


def sample_spline(
    points: list[tuple[float, float]],
    *,
    num_samples: int = 100,
) -> list[tuple[float, float]]:
    """Evaluate cubic B-spline through control points (open curve)."""
    if len(points) < 2:
        return list(points)
    if len(points) == 2:
        return _resample_polyline(points, num_nodes=num_samples)

    coords = np.asarray(points, dtype=np.float64).T
    tck, _ = splprep(coords, s=0.0, k=min(3, len(points) - 1))
    u = np.linspace(0.0, 1.0, num_samples)
    x, y = splev(u, tck)
    return [(float(xi), float(yi)) for xi, yi in zip(x, y, strict=True)]


def _resample_polyline(
    points: list[tuple[float, float]],
    *,
    num_nodes: int,
) -> list[tuple[float, float]]:
    if num_nodes <= 0:
        return []
    if len(points) == 1:
        return [points[0]] * num_nodes

    segments = np.diff(np.asarray(points, dtype=np.float64), axis=0)
    seg_lens = np.linalg.norm(segments, axis=1)
    cumulative = np.concatenate([[0.0], np.cumsum(seg_lens)])
    total = cumulative[-1]
    if total == 0.0:
        return [points[0]] * num_nodes

    targets = np.linspace(0.0, total, num_nodes)
    result: list[tuple[float, float]] = []
    for target in targets:
        idx = int(np.searchsorted(cumulative, target, side="right") - 1)
        idx = min(idx, len(points) - 2)
        start_len = cumulative[idx]
        end_len = cumulative[idx + 1]
        if end_len > start_len:
            alpha = (target - start_len) / (end_len - start_len)
        else:
            alpha = 0.0
        start = np.asarray(points[idx], dtype=np.float64)
        end = np.asarray(points[idx + 1], dtype=np.float64)
        pt = start + alpha * (end - start)
        result.append((float(pt[0]), float(pt[1])))
    return result


def point_line_distance(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    x0, y0 = point
    x1, y1 = start
    x2, y2 = end
    dx = x2 - x1
    dy = y2 - y1
    if dx == 0.0 and dy == 0.0:
        return math.hypot(x0 - x1, y0 - y1)

    numerator = abs(dy * x0 - dx * y0 + x2 * y1 - y2 * x1)
    denominator = math.hypot(dx, dy)
    return numerator / denominator


def polygon_area_mm2(
    polygon_points: Sequence[tuple[float, float]],
    pixel_spacing: tuple[float, float],
) -> float:
    """Shoelace area of a closed polygon in mm² (pixel coords: col, row)."""
    if len(polygon_points) < 3:
        return 0.0

    row_spacing, col_spacing = pixel_spacing
    mm_points = [
        (float(col) * col_spacing, float(row) * row_spacing)
        for col, row in polygon_points
    ]
    area = 0.0
    for index, (x1, y1) in enumerate(mm_points):
        x2, y2 = mm_points[(index + 1) % len(mm_points)]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0
