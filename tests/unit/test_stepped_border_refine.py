"""Unit tests for stepped border refine (R key)."""

from __future__ import annotations

import math

import numpy as np

from echo_personal_tool.domain.services.stepped_border_refine import (
    run_stepped_refine_pass,
    smooth_refined_open_arc,
)


def _ring_frame(size: int = 128) -> np.ndarray:
    center = (size - 1) / 2.0
    y_values, x_values = np.mgrid[0:size, 0:size]
    distance = np.hypot(x_values - center, y_values - center)
    frame = np.zeros((size, size), dtype=np.float64)
    frame[(distance > 28.0) & (distance <= 42.0)] = 220.0
    return frame


def _inner_arc(center: float, radius: float, *, count: int = 32) -> list[tuple[float, float]]:
    septal = (center - 20.0, center)
    lateral = (center + 20.0, center)
    angles = np.linspace(math.pi, 0.0, count)
    points = [(center + radius * math.cos(angle), center - radius * math.sin(angle)) for angle in angles]
    points[0] = septal
    points[-1] = lateral
    return points


def test_next_refine_step_uses_stride() -> None:
    from echo_personal_tool.domain.services.stepped_border_refine import (
        MAX_REFINE_STEP,
        next_refine_step,
    )

    assert next_refine_step(0, stride=3) == 3
    assert next_refine_step(3, stride=3) == 6
    assert next_refine_step(MAX_REFINE_STEP - 1, stride=3) == MAX_REFINE_STEP


def _open_arc_roughness(points: list[tuple[float, float]]) -> float:
    total = 0.0
    for index in range(1, len(points) - 1):
        x0, y0 = points[index - 1]
        x1, y1 = points[index]
        x2, y2 = points[index + 1]
        total += abs(x0 - 2.0 * x1 + x2) + abs(y0 - 2.0 * y1 + y2)
    return total


def test_smooth_refined_open_arc_reduces_roughness_and_pins_locked() -> None:
    center = 63.5
    points = _inner_arc(center, 30.0)
    annulus = (points[0], points[-1])
    jagged = list(points)
    for index in range(2, len(jagged) - 2, 2):
        x, y = jagged[index]
        jagged[index] = (x + 7.0, y - 5.0)
    locked = frozenset({5, 10})
    locked_positions = {index: jagged[index] for index in locked}

    smoothed = smooth_refined_open_arc(jagged, annulus, locked_indices=locked)
    assert _open_arc_roughness(smoothed) < _open_arc_roughness(jagged)
    for index, position in locked_positions.items():
        assert smoothed[index] == position


def test_stepped_refine_locks_nodes_on_endocardial_rim() -> None:
    frame = _ring_frame()
    center = 63.5
    points = _inner_arc(center, 22.0)
    annulus = (points[0], points[-1])

    result = run_stepped_refine_pass(
        frame,
        points,
        annulus=annulus,
        locked_indices=frozenset(),
        step=6,
    )

    assert result.newly_locked > 0
    assert len(result.locked_indices) == result.newly_locked
    mid_index = len(points) // 2
    refined_radius = math.hypot(
        result.points[mid_index][0] - center,
        result.points[mid_index][1] - center,
    )
    assert refined_radius > 24.0


def test_stepped_refine_locked_nodes_do_not_move_on_next_pass() -> None:
    frame = _ring_frame()
    center = 63.5
    points = _inner_arc(center, 22.0)
    annulus = (points[0], points[-1])

    first = run_stepped_refine_pass(frame, points, annulus=annulus, locked_indices=frozenset(), step=6)
    locked_positions = {index: first.points[index] for index in first.locked_indices}
    second = run_stepped_refine_pass(
        frame,
        first.points,
        annulus=annulus,
        locked_indices=first.locked_indices,
        step=7,
    )
    for index, position in locked_positions.items():
        assert second.points[index] == position


def test_stepped_refine_expands_search_without_infinite_growth() -> None:
    frame = _ring_frame()
    center = 63.5
    points = _inner_arc(center, 30.0)
    annulus = (points[0], points[-1])
    locked = frozenset()
    current = points
    max_radius = 0.0
    for step in range(1, 6):
        result = run_stepped_refine_pass(
            frame,
            current,
            annulus=annulus,
            locked_indices=locked,
            step=step,
        )
        locked = result.locked_indices
        current = result.points
        max_radius = max(math.hypot(current[i][0] - center, current[i][1] - center) for i in range(1, len(current) - 1))
    assert max_radius <= 43.0
