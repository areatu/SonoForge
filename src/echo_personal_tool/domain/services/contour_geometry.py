"""Open-arc contour geometry utilities."""

from __future__ import annotations

import math
from typing import Sequence


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
        key=lambda point: _point_line_distance(point, start, end),
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


def _point_line_distance(
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
