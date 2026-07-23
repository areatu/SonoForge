"""Stepped ±N px border search with per-node locking for manual R refine."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from echo_personal_tool.domain.services.contour_edge_snap import (
    build_edge_map,
    directed_edge_score,
    outward_normal_at_index,
)

MAX_REFINE_STEP = 30
REFINE_STEP_STRIDE = 3
REFINE_STEP_STRIDE_AI = 5
LOCK_SCORE_MIN = 12.0
REFINE_SMOOTH_BLEND = 0.70
REFINE_SMOOTH_ITERATIONS = 6


def next_refine_step(
    current_step: int,
    *,
    stride: int | None = None,
    source: str = "manual",
) -> int:
    """Next ±N px search radius for one R press.

    AI contours start with a larger stride (5 px) because they are
    typically farther from the true wall than user-drawn contours.
    """
    if stride is None:
        stride = REFINE_STEP_STRIDE_AI if source == "ai" else REFINE_STEP_STRIDE
    step_stride = max(1, int(stride))
    if current_step <= 0:
        return min(step_stride, MAX_REFINE_STEP)
    return min(current_step + step_stride, MAX_REFINE_STEP)


@dataclass(frozen=True)
class SteppedRefineResult:
    points: list[tuple[float, float]]
    locked_indices: frozenset[int]
    step: int
    newly_locked: int


def smooth_refined_open_arc(
    points: Sequence[tuple[float, float]],
    annulus: tuple[tuple[float, float], tuple[float, float]],
    *,
    locked_indices: frozenset[int],
    blend: float | None = None,
    iterations: int | None = None,
) -> list[tuple[float, float]]:
    """Taubin smooth after edge snap; locked nodes and MV ends stay fixed."""
    from echo_personal_tool.domain.services.contour_geometry import smooth_open_arc

    if len(points) < 3:
        return list(points)
    smooth_blend = REFINE_SMOOTH_BLEND if blend is None else float(blend)
    smooth_iters = REFINE_SMOOTH_ITERATIONS if iterations is None else int(iterations)
    if smooth_blend <= 0.0 or smooth_iters <= 0:
        return list(points)
    return smooth_open_arc(
        points,
        annulus,
        iterations=smooth_iters,
        blend=min(max(smooth_blend, 0.0), 0.95),
        pinned_indices=locked_indices,
        taubin=True,
    )


def run_stepped_refine_pass(
    frame,
    points: Sequence[tuple[float, float]],
    *,
    annulus: tuple[tuple[float, float], tuple[float, float]],
    locked_indices: frozenset[int],
    step: int,
    display_levels: tuple[float, float] | None = None,
    lock_score_min: float = LOCK_SCORE_MIN,
    smooth_blend: float | None = None,
    smooth_iterations: int | None = None,
    cine: bool = False,
) -> SteppedRefineResult:
    """One R pass: ±step px edge search, then Laplacian smooth (locked nodes pinned)."""
    if len(points) < 3:
        return SteppedRefineResult(list(points), locked_indices, step, 0)

    step_px = max(1, min(int(step), MAX_REFINE_STEP))
    effective_lock_min = 0.0 if cine else lock_score_min
    edge_map = build_edge_map(frame, display_levels=display_levels, blur_sigma=0.5 if cine else 1.0)
    updated = list(points)
    new_locked = set(locked_indices)
    newly_locked = 0

    if cine:
        search_offsets = np.linspace(-step_px, step_px, max(7, step_px * 2 + 1)).tolist()
    else:
        search_offsets = [0, -step_px, step_px]

    for index in range(1, len(points) - 1):
        if index in locked_indices:
            continue
        px, py = points[index]
        normal = outward_normal_at_index(points, index)
        nx, ny = normal

        best_score = 0.0
        best_pos = (px, py)
        for offset in search_offsets:
            sample_x = px + float(offset) * nx
            sample_y = py + float(offset) * ny
            score = directed_edge_score(edge_map, sample_x, sample_y, normal)
            if score > best_score:
                best_score = score
                best_pos = (sample_x, sample_y)

        if best_score >= effective_lock_min:
            updated[index] = best_pos
            if index not in new_locked:
                newly_locked += 1
            new_locked.add(index)

    smoothed = smooth_refined_open_arc(
        updated,
        annulus,
        locked_indices=frozenset(new_locked),
        blend=smooth_blend,
        iterations=smooth_iterations,
    )

    return SteppedRefineResult(
        points=smoothed,
        locked_indices=frozenset(new_locked),
        step=step_px,
        newly_locked=newly_locked,
    )


def format_stepped_refine_status(
    *,
    step: int,
    locked_count: int,
    interior_count: int,
    newly_locked: int,
) -> str:
    if interior_count <= 0:
        return f"step:{step} locked:0/0"
    if locked_count >= interior_count:
        return f"complete locked:{locked_count}/{interior_count}"
    if newly_locked == 0:
        return f"step:{step} locked:{locked_count}/{interior_count} (no edge)"
    return f"step:{step} locked:{locked_count}/{interior_count} (+{newly_locked})"
