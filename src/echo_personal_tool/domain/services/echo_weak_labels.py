"""Three real anchors + weak atlas interpolation, never dense physician gold.

No files, patient metadata or inferred missing chambers. An optional in-memory
sector permits bounded gradient refinement without changing any real anchor.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from echo_personal_tool.domain.services.active_contour_refine import ActiveContourConfig, refine_open_arc
from echo_personal_tool.domain.services.cardiac_atlas import CoupledShapeModel, fit_chamber_landmarks
from echo_personal_tool.domain.services.cardiac_atlas_geometry import CanonicalFrame, edges_cross, points_array


@dataclass(frozen=True)
class WeakShapeTarget:
    view: str
    chamber: str
    phase: str
    points: np.ndarray
    node_weights: np.ndarray
    anchor_indices: tuple[int, int, int]
    gradient_refined: bool
    units: str = "annulus_span"
    source: str = "weak_three_point_atlas"


def reconstruct_weak_shape(
    model: CoupledShapeModel,
    chamber: str,
    anchors: np.ndarray,
    *,
    phase: str,
    image: np.ndarray | None = None,
    node_count: int = 81,
    interpolation_weight: float = 0.15,
) -> WeakShapeTarget:
    if chamber not in {"LV", "LA", "RV"} or phase not in {"ED", "ES"}:
        raise ValueError("weak targets need an explicit chamber and ED/ES")
    if not 5 <= node_count <= 129 or node_count % 2 != 1 or not 0 < interpolation_weight <= 0.25:
        raise ValueError("invalid weak target sampling/weight")
    anchor = points_array(anchors)
    if anchor.shape != (3, 2):
        raise ValueError("three measured anchors required")
    septal, lateral, apex = [(float(x), float(y)) for x, y in anchor]
    # Reject clinically unusable near-collinear / tiny triangles, not just NaNs.
    span = float(np.linalg.norm(anchor[1] - anchor[0]))
    depth = abs(float(np.linalg.det(np.stack([anchor[1] - anchor[0], anchor[2] - anchor[0]])))) / max(span, 1e-8)
    if span < 3 or depth < span * 0.1 or depth > span * 8:
        raise ValueError("degenerate weak anchors")
    placed = np.asarray(
        fit_chamber_landmarks(model, chamber, septal, lateral, apex, phase=phase, num_points=node_count)
    )
    midpoint = node_count // 2
    refined = False
    if image is not None:
        frame = np.asarray(image, float)
        if frame.ndim != 2 or min(frame.shape) < 16 or not np.isfinite(frame).all():
            raise ValueError("invalid anonymous sector")
        if np.any(placed < 0) or np.any(placed[:, 0] >= frame.shape[1]) or np.any(placed[:, 1] >= frame.shape[0]):
            raise ValueError("weak contour outside supplied sector")
        cfg = ActiveContourConfig(
            search_radius_px=min(3.0, span * 0.1), k_int=0.7, k_ext=0.7, k_smooth=0.08, max_iterations=12
        )
        halves = [placed[: midpoint + 1], placed[midpoint:]]
        candidates: list[np.ndarray] = []
        for part in halves:
            coordinates = [(float(x), float(y)) for x, y in part]
            candidates.append(
                np.asarray(
                    refine_open_arc(frame, coordinates, (coordinates[0], coordinates[-1]), config=cfg), dtype=float
                )
            )
        candidate = np.vstack([candidates[0], candidates[1][1:]])
        if (
            np.ptp(frame) > 1e-8
            and np.max(np.linalg.norm(candidate - placed, axis=1)) <= span * 0.15
            and not edges_cross(candidate, candidate, same=True)
        ):
            refined = bool(np.max(np.abs(candidate - placed)) > 1e-8)
            placed = candidate
    placed[[0, midpoint, -1]] = anchor[[0, 2, 1]]
    if edges_cross(placed, placed, same=True):
        raise ValueError("invalid weak contour topology")
    canonical = CanonicalFrame.from_landmarks(septal, lateral, apex)
    points = canonical.image_to_atlas(placed)
    weights = np.full(node_count, interpolation_weight)
    weights[[0, midpoint, -1]] = 1.0
    return WeakShapeTarget(model.view, chamber, phase, points, weights, (0, node_count - 1, midpoint), refined)
