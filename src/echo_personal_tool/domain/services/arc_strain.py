"""Open-arc material-line machinery shared by the chamber strain services.

The LA strain (plan А.6) and the RV free-wall strain (plan А.7) measure the
same physical thing — the Lagrangian length change of a drawn material line —
with the same speckle machinery: kernels sampled on the drawn polyline, the
bidirectional tracker propagating them from the frame the contour was drawn
on, and the strain of the arc length against its length at the end-diastole
frame. The chamber-specific parts (phase windows, which metrics the curve
carries, which contour belongs to which chamber) live in :mod:`la_strain` and
:mod:`rv_strain`; this module holds only what is identical for both, so the
two chambers cannot drift apart in the definition of the measurement.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from echo_personal_tool.domain.models.speckle import SpeckleConfig, TrackingKernel
from echo_personal_tool.domain.services.speckle_tracking import track_cine_bidirectional
from echo_personal_tool.domain.services.strain_computation import lagrangian_strain_pct

#: A shorter arc cannot carry a meaningful strain curve.
MIN_ARC_POINTS = 3


def build_arc_kernels(arc_points: np.ndarray, *, kernel_radius: int) -> list[TrackingKernel]:
    """One tracking kernel per arc node, ordered along the open arc."""
    points = np.asarray(arc_points, dtype=np.float64).reshape(-1, 2)
    return [
        TrackingKernel(
            center=(float(p[0]), float(p[1])),
            radius=int(kernel_radius),
            node_index=i,
            layer="endo",
            aha_segment=0,  # the AHA model is an LV contract; a drawn wall arc is not in it
        )
        for i, p in enumerate(points)
    ]


def track_arc(
    frames: np.ndarray,
    arc_points: np.ndarray,
    anchor_index: int,
    config: SpeckleConfig,
    *,
    kernel_radius: int,
    progress_callback: Callable[[int, int], None] | None = None,
) -> tuple[np.ndarray, float, float] | None:
    """Track the arc through the window, anchored at ``anchor_index``.

    Returns ``(positions (n_frames, n_nodes, 2), ncc_mean, valid_fraction)``
    or ``None`` when the arc is too short to track. The anchor frame is the
    frame the *contour was drawn on* (ED or ES — either works: the strain
    reference below re-anchors the zero at the ED frame via its tracked
    positions).
    """
    points = np.asarray(arc_points, dtype=np.float64).reshape(-1, 2)
    if points.shape[0] < MIN_ARC_POINTS or frames.ndim != 3:
        return None
    anchor = int(np.clip(int(anchor_index), 0, frames.shape[0] - 1))
    kernels = build_arc_kernels(points, kernel_radius=kernel_radius)
    results = track_cine_bidirectional(
        frames,
        kernels,
        ed_index=anchor,
        config=config,
        progress_callback=progress_callback,
    )
    if not results:
        return None
    positions = np.stack([result.kernel_positions for result in results], axis=0)
    ncc = np.stack([result.ncc_scores for result in results], axis=0)
    valid = np.stack([result.valid_mask for result in results], axis=0)
    tracked = np.delete(np.arange(ncc.shape[0]), anchor)
    if tracked.size == 0:
        return None
    ncc_mean = float(np.nanmean(ncc[tracked]))
    valid_fraction = float(np.mean(valid[tracked]))
    return positions, ncc_mean, valid_fraction


def arc_strain_curve(
    positions: np.ndarray,
    ed_index: int,
    pixel_spacing: tuple[float, float],
) -> np.ndarray:
    """Lagrangian arc-length strain of the tracked arc, zeroed at ``ed_index``.

    The strain zero sits at *ventricular* end-diastole — the reference length
    is measured on the tracked positions at the ED frame — regardless of which
    frame anchored the kernels. Both ventricles and the atria using this
    module share the convention: ED is the start of the measured beat.
    """
    positions = np.asarray(positions, dtype=np.float64)
    n_frames = positions.shape[0]
    curve = np.full(n_frames, np.nan, dtype=np.float64)
    ed = int(np.clip(int(ed_index), 0, n_frames - 1))
    avg = float(np.mean(pixel_spacing)) if len(pixel_spacing) else 1.0
    if avg <= 0.0:
        return curve

    def arc_len(t: int) -> float:
        diffs = np.diff(positions[t], axis=0)
        return float(np.sum(np.linalg.norm(diffs, axis=1)) * avg)

    l0 = arc_len(ed)
    if l0 < 1e-6:
        return curve
    for t in range(n_frames):
        curve[t] = lagrangian_strain_pct(arc_len(t), l0)
    return curve
