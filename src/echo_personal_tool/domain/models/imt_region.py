"""Oriented IMT rectangle in source pixels, independent of viewer transforms."""

from __future__ import annotations

from math import hypot, isclose, isfinite

import numpy as np

Polygon = tuple[tuple[float, float], ...]


def region_axes(polygon: Polygon) -> tuple[np.ndarray, np.ndarray, np.ndarray, float, float]:
    """Origin, unit longitudinal/depth axes and lengths (clockwise image space)."""
    points = np.asarray(polygon, dtype=float)
    if points.shape != (4, 2) or not np.isfinite(points).all():
        raise ValueError("invalid_rotated_roi")
    origin = points[0]
    along, depth = points[1] - origin, points[3] - origin
    width, height = hypot(*along), hypot(*depth)
    if not 8 <= width <= 512 or not 8 <= height <= 256:
        raise ValueError("invalid_rotated_roi")
    u, v = along / width, depth / height
    if not np.allclose(points[2], origin + along + depth, atol=1e-6, rtol=0):
        raise ValueError("invalid_rotated_roi")
    if not isclose(float(u @ v), 0.0, abs_tol=1e-6) or u[0] * v[1] - u[1] * v[0] < 0.999999:
        raise ValueError("invalid_rotated_roi")
    # The longitudinal tracer and physical-normal representation are x-monotone.
    if u[0] < 2**-0.5 - 1e-9:
        raise ValueError("roi_angle_limit")
    return origin, u, v, width, height


def validate_region(polygon: Polygon, bbox: tuple[int, int, int, int]) -> None:
    if not polygon:
        return
    region_axes(polygon)
    x0, y0, x1, y1 = bbox
    if any(not isfinite(x + y) or not x0 <= x <= x1 or not y0 <= y <= y1 for x, y in polygon):
        raise ValueError("rotated_roi_outside_frame")


def contains_points(polygon: Polygon, points: np.ndarray) -> bool:
    """Reject manual boundary edits outside the actual rectangle, not just its bbox."""
    if not polygon:
        return True
    origin, u, v, width, height = region_axes(polygon)
    local = np.asarray(points) - origin
    along, depth = local @ u, local @ v
    return bool(np.all((along >= -1e-6) & (along < width) & (depth >= -1e-6) & (depth < height)))
