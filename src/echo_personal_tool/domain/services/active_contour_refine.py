"""Active contour refinement for open-arc LV endocardial borders."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from scipy import ndimage


@dataclass(frozen=True)
class ActiveContourConfig:
    search_radius_px: float = 8.0
    k_int: float = 0.3
    k_ext: float = 1.0
    k_smooth: float = 0.5
    step_size: float = 0.35
    max_iterations: int = 80
    gradient_samples: int = 17


def refine_open_arc(
    frame: np.ndarray,
    initial_points: Sequence[tuple[float, float]],
    annulus: tuple[tuple[float, float], tuple[float, float]],
    *,
    template_points: Sequence[tuple[float, float]] | None = None,
    config: ActiveContourConfig | None = None,
) -> list[tuple[float, float]]:
    """Refine an open arc toward image edges using a discrete active contour."""
    if len(initial_points) < 3:
        msg = "initial_points must contain at least 3 points"
        raise ValueError(msg)

    cfg = config or ActiveContourConfig()
    gray = _to_grayscale(frame)
    gradient = _gradient_magnitude(gray)
    height, width = gray.shape

    points = [[float(x), float(y)] for x, y in initial_points]
    points[0] = [float(annulus[0][0]), float(annulus[0][1])]
    points[-1] = [float(annulus[1][0]), float(annulus[1][1])]
    template = (
        list(template_points)
        if template_points is not None
        else [tuple(point) for point in points]
    )
    if len(template) != len(points):
        msg = "template_points must match initial_points length"
        raise ValueError(msg)

    radius = max(float(cfg.search_radius_px), 1.0)
    offsets = np.linspace(-radius, radius, cfg.gradient_samples)

    for _ in range(cfg.max_iterations):
        moved = False
        next_points = [point[:] for point in points]
        for index in range(1, len(points) - 1):
            px, py = points[index]
            force_x = cfg.k_int * (template[index][0] - px)
            force_y = cfg.k_int * (template[index][1] - py)
            force_x += cfg.k_smooth * (
                points[index - 1][0] + points[index + 1][0] - 2.0 * px
            )
            force_y += cfg.k_smooth * (
                points[index - 1][1] + points[index + 1][1] - 2.0 * py
            )

            normal_x, normal_y = _outward_normal(index, points)
            best_offset = 0.0
            best_gradient = -1.0
            for offset in offsets:
                sample_x = px + offset * normal_x
                sample_y = py + offset * normal_y
                magnitude = _sample_bilinear(gradient, sample_x, sample_y, height, width)
                if magnitude > best_gradient:
                    best_gradient = magnitude
                    best_offset = float(offset)

            if best_gradient > 0.0:
                force_x += cfg.k_ext * (best_offset / radius) * normal_x
                force_y += cfg.k_ext * (best_offset / radius) * normal_y

            delta_x = cfg.step_size * force_x
            delta_y = cfg.step_size * force_y
            if abs(delta_x) > 1e-6 or abs(delta_y) > 1e-6:
                moved = True
            next_x = _clamp(px + delta_x, 0.0, width - 1.0)
            next_y = _clamp(py + delta_y, 0.0, height - 1.0)
            next_points[index] = [next_x, next_y]

        next_points[0] = [float(annulus[0][0]), float(annulus[0][1])]
        next_points[-1] = [float(annulus[1][0]), float(annulus[1][1])]
        points = next_points
        if not moved:
            break

    return [(point[0], point[1]) for point in points]


def _to_grayscale(frame: np.ndarray) -> np.ndarray:
    array = np.asarray(frame)
    if array.ndim == 3:
        return np.mean(array[..., :3], axis=2, dtype=np.float64)
    return array.astype(np.float64, copy=False)


def _gradient_magnitude(image: np.ndarray) -> np.ndarray:
    blurred = ndimage.gaussian_filter(image, sigma=1.0)
    gradient_x = ndimage.sobel(blurred, axis=1)
    gradient_y = ndimage.sobel(blurred, axis=0)
    return np.hypot(gradient_x, gradient_y)


def _outward_normal(
    index: int,
    points: Sequence[Sequence[float]],
) -> tuple[float, float]:
    previous = points[index - 1]
    current = points[index]
    following = points[index + 1]
    tangent_x = following[0] - previous[0]
    tangent_y = following[1] - previous[1]
    length = float(np.hypot(tangent_x, tangent_y))
    if length <= 1e-6:
        return (0.0, -1.0)
    tangent_x /= length
    tangent_y /= length
    normal_x = -tangent_y
    normal_y = tangent_x
    to_center_x = current[0] - 0.5 * (previous[0] + following[0])
    to_center_y = current[1] - 0.5 * (previous[1] + following[1])
    if normal_x * to_center_x + normal_y * to_center_y > 0.0:
        normal_x = -normal_x
        normal_y = -normal_y
    return (normal_x, normal_y)


def _sample_bilinear(
    values: np.ndarray,
    x: float,
    y: float,
    height: int,
    width: int,
) -> float:
    if x < 0.0 or y < 0.0 or x >= width - 1 or y >= height - 1:
        return 0.0
    x0 = int(x)
    y0 = int(y)
    x1 = x0 + 1
    y1 = y0 + 1
    dx = x - x0
    dy = y - y0
    top = (1.0 - dx) * values[y0, x0] + dx * values[y0, x1]
    bottom = (1.0 - dx) * values[y1, x0] + dx * values[y1, x1]
    return float((1.0 - dy) * top + dy * bottom)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))
