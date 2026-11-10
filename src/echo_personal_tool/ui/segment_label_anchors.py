"""Pure anchor placement for AHA segment labels around tracked myocardial walls."""

from __future__ import annotations

import numpy as np

from echo_personal_tool.domain.models.speckle import TrackingKernel


def segment_label_anchors(
    kernels: list[TrackingKernel],
    positions: np.ndarray | None,
    *,
    layer: str = "endo",
    offset_px: float = 22.0,
) -> list[tuple[int, float, float]]:
    """Anchor of each segment name: next to its nodes, outside the wall.

    Returns ``(segment_id, x, y)`` sorted by segment id. The anchor is the mean
    position of the segment's nodes moved *away from the cavity* by
    ``offset_px``, so the name lands beyond the myocardium instead of on top of
    the border the reader is judging. Kernels without an AHA segment, without a
    finite position or from another layer are skipped; a degenerate direction
    falls back to a fixed one, keeping the overlay deterministic.
    """
    if not kernels or positions is None or len(positions) == 0:
        return []

    node_points: list[np.ndarray] = []
    per_segment: dict[int, list[np.ndarray]] = {}
    for i, kernel in enumerate(kernels):
        if kernel.layer != layer or i >= len(positions):
            continue
        x, y = float(positions[i, 0]), float(positions[i, 1])
        if not (np.isfinite(x) and np.isfinite(y)):
            continue
        segment = int(kernel.aha_segment)
        if segment <= 0:
            continue
        point = np.array([x, y], dtype=np.float64)
        per_segment.setdefault(segment, []).append(point)
        node_points.append(point)
    if not per_segment:
        return []

    cavity = np.mean(np.vstack(node_points), axis=0)
    anchors: list[tuple[int, float, float]] = []
    for segment, points in sorted(per_segment.items()):
        node = np.mean(np.vstack(points), axis=0)
        direction = node - cavity
        norm = float(np.linalg.norm(direction))
        direction = np.array([0.0, 1.0]) if norm < 1e-9 else direction / norm
        anchor = node + direction * float(offset_px)
        anchors.append((segment, float(anchor[0]), float(anchor[1])))
    return anchors


__all__ = ["segment_label_anchors"]
