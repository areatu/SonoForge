"""Unit tests for active contour refinement."""

from __future__ import annotations

import math

import numpy as np
import pytest

from echo_personal_tool.domain.services.active_contour_refine import (
    ActiveContourConfig,
    refine_open_arc,
)


def _ring_frame(
    size: int = 128,
    *,
    inner_radius: float = 28.0,
    outer_radius: float = 42.0,
) -> np.ndarray:
    center = (size - 1) / 2.0
    y_values, x_values = np.mgrid[0:size, 0:size]
    distance = np.hypot(x_values - center, y_values - center)
    frame = np.zeros((size, size), dtype=np.float64)
    frame[distance <= inner_radius] = 20.0
    frame[(distance > inner_radius) & (distance <= outer_radius)] = 220.0
    return frame


def _circle_arc(
    center: tuple[float, float],
    radius: float,
    *,
    num_points: int = 32,
) -> list[tuple[float, float]]:
    cx, cy = center
    angles = np.linspace(math.pi, 0.0, num_points)
    return [(cx + radius * math.cos(angle), cy - radius * math.sin(angle)) for angle in angles]


def test_refine_open_arc_moves_toward_bright_rim() -> None:
    frame = _ring_frame()
    center = (63.5, 63.5)
    annulus = ((center[0] - 20.0, center[1]), (center[0] + 20.0, center[1]))
    initial = _circle_arc(center, radius=22.0)
    initial[0] = annulus[0]
    initial[-1] = annulus[1]

    refined = refine_open_arc(
        frame,
        initial,
        annulus,
        template_points=initial,
        config=ActiveContourConfig(max_iterations=120, step_size=0.5, k_ext=1.5),
    )

    mid_index = len(refined) // 2
    initial_mid_radius = math.hypot(
        initial[mid_index][0] - center[0],
        initial[mid_index][1] - center[1],
    )
    refined_mid_radius = math.hypot(
        refined[mid_index][0] - center[0],
        refined[mid_index][1] - center[1],
    )
    assert refined_mid_radius > initial_mid_radius


def test_refine_open_arc_preserves_endpoints() -> None:
    frame = _ring_frame()
    center = (63.5, 63.5)
    annulus = ((center[0] - 20.0, center[1]), (center[0] + 20.0, center[1]))
    initial = _circle_arc(center, radius=24.0)

    refined = refine_open_arc(frame, initial, annulus, template_points=initial)

    assert refined[0] == pytest.approx(annulus[0], abs=1e-3)
    assert refined[-1] == pytest.approx(annulus[1], abs=1e-3)


def test_refine_open_arc_requires_three_points() -> None:
    frame = _ring_frame()
    with pytest.raises(ValueError, match="at least 3"):
        refine_open_arc(frame, [(0.0, 0.0), (1.0, 1.0)], ((0.0, 0.0), (1.0, 1.0)))
