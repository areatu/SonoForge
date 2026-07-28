"""Douglas-Peucker polygon point reduction."""

from __future__ import annotations


def _perpendicular_distance(
    point: tuple[float, float],
    line_start: tuple[float, float],
    line_end: tuple[float, float],
) -> float:
    dx = line_end[0] - line_start[0]
    dy = line_end[1] - line_start[1]
    length_sq = dx * dx + dy * dy
    if length_sq < 1e-12:
        return ((point[0] - line_start[0]) ** 2 + (point[1] - line_start[1]) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((point[0] - line_start[0]) * dx + (point[1] - line_start[1]) * dy) / length_sq))
    proj_x = line_start[0] + t * dx
    proj_y = line_start[1] + t * dy
    return ((point[0] - proj_x) ** 2 + (point[1] - proj_y) ** 2) ** 0.5


def _douglas_peucker(
    points: list[tuple[float, float]],
    epsilon: float,
) -> list[tuple[float, float]]:
    if len(points) <= 2:
        return list(points)

    max_dist = 0.0
    max_index = 0
    for i in range(1, len(points) - 1):
        dist = _perpendicular_distance(points[i], points[0], points[-1])
        if dist > max_dist:
            max_dist = dist
            max_index = i

    if max_dist > epsilon:
        left = _douglas_peucker(points[: max_index + 1], epsilon)
        right = _douglas_peucker(points[max_index:], epsilon)
        return left[:-1] + right

    return [points[0], points[-1]]


def reduce_polygon_points(
    points: list[tuple[float, float]],
    *,
    epsilon: float = 2.0,
    closed: bool = False,
) -> list[tuple[float, float]]:
    """Reduce polygon points using Douglas-Peucker algorithm.

    Args:
        points: Raw polygon vertices.
        epsilon: Maximum perpendicular distance for point removal.
        closed: If True, ensure first and last points are identical.
    """
    if len(points) <= 2:
        return list(points)

    reduced = _douglas_peucker(points, epsilon)

    if closed and len(reduced) >= 2:
        if reduced[0] != reduced[-1]:
            reduced.append(reduced[0])

    return reduced
