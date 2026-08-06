"""Temporal fusion for LV Auto: neighbor-aware contour on frame N.

Pure NumPy functions — no Qt dependency. Uses v1.5 per-frame masks
and produces a fused contour on the anchor frame.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import ndimage

from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.models.temporal_fusion import (
    TemporalFusionConfig,
    TemporalFusionResult,
)
from echo_personal_tool.domain.services.contour_geometry import (
    smooth_open_arc,
)
from echo_personal_tool.domain.services.segmentation_service import (
    exclude_papillary_concavities,
    open_arc_from_cavity_mask,
    papillary_mask_cleanup,
)


def compute_window(
    anchor: int,
    total_frames: int,
    window: int = 2,
) -> list[int]:
    """Frame indices in [anchor-W .. anchor+W] clamped to [0, total_frames-1]."""
    return [i for i in range(max(0, anchor - window), min(total_frames, anchor + window + 1))]


def align_mask_to_anchor(
    mask_t: np.ndarray,
    centroid_t: tuple[float, float],
    centroid_n: tuple[float, float],
) -> np.ndarray:
    """Translate mask_t so its MA centroid aligns with anchor centroid."""
    dx = centroid_n[0] - centroid_t[0]
    dy = centroid_n[1] - centroid_t[1]
    shifted = ndimage.shift(mask_t.astype(np.float32), shift=(dy, dx), order=0)
    return (shifted >= 0.5).astype(np.uint8)


def mask_vote_fusion(
    masks: list[np.ndarray],
    threshold: int = 3,
) -> np.ndarray:
    """Per-pixel vote across aligned masks. Returns binary fused mask."""
    if not masks:
        return np.zeros((1, 1), dtype=np.uint8)
    canvas = np.zeros_like(masks[0], dtype=np.int32)
    for m in masks:
        canvas += m.astype(np.int32)
    return (canvas >= threshold).astype(np.uint8)


def _component_wise_median(
    points_list: list[tuple[float, float]],
) -> tuple[float, float]:
    """Median of 2D point list component-wise."""
    xs = [p[0] for p in points_list]
    ys = [p[1] for p in points_list]
    return (float(np.median(xs)), float(np.median(ys)))


def _ma_centroid(
    annulus: tuple[tuple[float, float], tuple[float, float]],
) -> tuple[float, float]:
    """Midpoint of septal/lateral MA endpoints."""
    septal, lateral = annulus
    return ((septal[0] + lateral[0]) / 2.0, (septal[1] + lateral[1]) / 2.0)


def _ma_length(
    annulus: tuple[tuple[float, float], tuple[float, float]],
) -> float:
    """Distance between septal and lateral MA endpoints."""
    septal, lateral = annulus
    return math.hypot(lateral[0] - septal[0], lateral[1] - septal[1])


def clamp_nodes_to_center(
    median_points: list[tuple[float, float]],
    center_points: list[tuple[float, float]],
    shift_cap: float,
    apex_index: int | None = None,
    apex_shift_cap: float | None = None,
) -> list[tuple[float, float]]:
    """Clamp each node to center ± shift_cap. Apex node uses tighter cap."""
    result = []
    for idx, (m, c) in enumerate(zip(median_points, center_points)):
        cap = apex_shift_cap if (idx == apex_index and apex_shift_cap is not None) else shift_cap
        dx = m[0] - c[0]
        dy = m[1] - c[1]
        dist = math.hypot(dx, dy)
        if dist <= cap or dist == 0.0:
            result.append(m)
        else:
            scale = cap / dist
            result.append((c[0] + dx * scale, c[1] + dy * scale))
    return result


def fuse_annulus_endpoints(
    center_annulus: tuple[tuple[float, float], tuple[float, float]],
    neighbor_annuli: list[tuple[tuple[float, float], tuple[float, float]]],
    delta: float,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Fuse septal and lateral endpoints separately with δ clamp."""
    if not neighbor_annuli:
        return center_annulus

    center_septal, center_lateral = center_annulus
    septal_positions = [center_septal] + [a[0] for a in neighbor_annuli]
    lateral_positions = [center_lateral] + [a[1] for a in neighbor_annuli]

    fused_septal = _clamp_point_to_center(
        _component_wise_median(septal_positions),
        center_septal,
        delta,
    )
    fused_lateral = _clamp_point_to_center(
        _component_wise_median(lateral_positions),
        center_lateral,
        delta,
    )
    return (fused_septal, fused_lateral)


def _clamp_point_to_center(
    median_pt: tuple[float, float],
    center_pt: tuple[float, float],
    delta: float,
) -> tuple[float, float]:
    dx = median_pt[0] - center_pt[0]
    dy = median_pt[1] - center_pt[1]
    dist = math.hypot(dx, dy)
    if dist <= delta or dist == 0.0:
        return median_pt
    scale = delta / dist
    return (center_pt[0] + dx * scale, center_pt[1] + dy * scale)


def apply_apex_direction_lock(
    fused_apex: tuple[float, float],
    neighbor_apices: list[tuple[float, float]],
    center_apex: tuple[float, float],
    epsilon: float,
) -> tuple[float, float]:
    """If ≥2 neighbors have apex more apical (smaller y) than center, cap fused apex."""
    if not neighbor_apices:
        return fused_apex
    count_more_apical = sum(1 for a in neighbor_apices if a[1] < center_apex[1])
    if count_more_apical >= 2 and fused_apex[1] > center_apex[1] + epsilon:
        return (fused_apex[0], center_apex[1] + epsilon)
    return fused_apex


def compute_neighbor_confidence(
    anchor_contour: Contour,
    neighbor_contour: Contour,
    *,
    phase: str,
) -> float:
    """Score 0.0–1.0 based on landmark stability and shape consistency.

    Higher score = neighbor is more similar to anchor = should contribute more.
    """
    if (
        anchor_contour.mitral_annulus is None
        or neighbor_contour.mitral_annulus is None
        or len(anchor_contour.points) < 3
        or len(neighbor_contour.points) < 3
    ):
        return 0.0

    # Landmark stability: MA midpoint shift relative to MA length
    a_septal, a_lateral = anchor_contour.mitral_annulus
    n_septal, n_lateral = neighbor_contour.mitral_annulus
    a_ma_mid = ((a_septal[0] + a_lateral[0]) / 2, (a_septal[1] + a_lateral[1]) / 2)
    n_ma_mid = ((n_septal[0] + n_lateral[0]) / 2, (n_septal[1] + n_lateral[1]) / 2)
    ma_len = _ma_length(anchor_contour.mitral_annulus)
    if ma_len < 1e-6:
        return 0.0
    ma_shift = math.hypot(a_ma_mid[0] - n_ma_mid[0], a_ma_mid[1] - n_ma_mid[1])
    landmark_score = max(0.0, 1.0 - (ma_shift / ma_len) * 2.0)

    # Shape consistency: arc span ratio
    a_span = _arc_span(anchor_contour.points)
    n_span = _arc_span(neighbor_contour.points)
    if a_span < 1e-6 or n_span < 1e-6:
        return landmark_score
    span_ratio = min(a_span, n_span) / max(a_span, n_span)
    shape_score = span_ratio

    return 0.6 * landmark_score + 0.4 * shape_score


def _arc_span(points: list[tuple[float, float]]) -> float:
    """Max pairwise distance in point list."""
    if len(points) < 2:
        return 0.0
    max_span = 0.0
    for i, first in enumerate(points):
        for second in points[i + 1 :]:
            span = math.hypot(second[0] - first[0], second[1] - first[1])
            max_span = max(max_span, span)
    return max_span


def reject_outlier_neighbors(
    anchor_contour: Contour,
    neighbor_contours: dict[int, Contour],
    *,
    max_shift_ratio: float = 0.15,
) -> dict[int, Contour]:
    """Remove neighbors whose landmarks deviate more than max_shift_ratio * long_axis."""
    if anchor_contour.mitral_annulus is None:
        return neighbor_contours
    ma_len = _ma_length(anchor_contour.mitral_annulus)
    if ma_len < 1e-6:
        return neighbor_contours
    max_shift = max_shift_ratio * ma_len
    center_apex = anchor_contour.apex_landmark

    accepted: dict[int, Contour] = {}
    for idx, nc in neighbor_contours.items():
        if nc.mitral_annulus is None:
            continue
        # Check MA midpoint shift
        a_mid = _ma_centroid(anchor_contour.mitral_annulus)
        n_mid = _ma_centroid(nc.mitral_annulus)
        ma_shift = math.hypot(a_mid[0] - n_mid[0], a_mid[1] - n_mid[1])
        if ma_shift > max_shift:
            continue
        # Check apex shift if both have apex landmarks
        if center_apex is not None and nc.apex_landmark is not None:
            apex_shift = math.hypot(
                center_apex[0] - nc.apex_landmark[0],
                center_apex[1] - nc.apex_landmark[1],
            )
            if apex_shift > max_shift:
                continue
        accepted[idx] = nc
    return accepted


def temporal_fuse(
    center_mask: np.ndarray,
    neighbor_masks: dict[int, np.ndarray],
    center_contour: Contour,
    neighbor_contours: dict[int, Contour],
    anchor_frame_index: int,
    phase: str,
    config: TemporalFusionConfig,
    original_shape: tuple[int, int],
) -> TemporalFusionResult:
    """Full temporal fusion pipeline on anchor frame N.

    1. Align neighbor masks to anchor via MA centroid translation.
    2. Mask vote fusion.
    3. Papillary cleanup + open_arc on fused mask.
    4. Node clamp (median of neighbors clamped to center ± shift_cap).
    5. Annulus fusion with δ.
    6. Apex direction lock.
    7. Papillary concavity exclusion + smooth.
    """
    valid_neighbor_ids = sorted(i for i in neighbor_masks if i in neighbor_contours)
    all_masks = [center_mask] + [neighbor_masks[i] for i in valid_neighbor_ids]
    all_contours = [center_contour] + [neighbor_contours[i] for i in valid_neighbor_ids]

    # --- 1. Compute centroids for alignment ---
    center_ma = center_contour.mitral_annulus
    if center_ma is None:
        # Cannot align without MA — fall back to center-only
        return TemporalFusionResult(
            anchor_frame_index=anchor_frame_index,
            fused_contour=center_contour,
            center_contour=center_contour,
            neighbor_contours={i: neighbor_contours[i] for i in valid_neighbor_ids},
            frames_used=1,
            frames_requested=len(neighbor_masks) + 1,
            config=config,
        )

    center_centroid = _ma_centroid(center_ma)

    aligned_masks = [center_mask]
    # Store alignment deltas for point alignment
    alignment_deltas: dict[int, tuple[float, float]] = {}
    for i in valid_neighbor_ids:
        c = neighbor_contours[i]
        if c.mitral_annulus is not None:
            t_centroid = _ma_centroid(c.mitral_annulus)
            dx = center_centroid[0] - t_centroid[0]
            dy = center_centroid[1] - t_centroid[1]
            alignment_deltas[i] = (dx, dy)
            aligned = align_mask_to_anchor(neighbor_masks[i], t_centroid, center_centroid)
        else:
            alignment_deltas[i] = (0.0, 0.0)
            aligned = neighbor_masks[i]
        aligned_masks.append(aligned)

    # Align neighbor contour points to anchor canvas
    aligned_neighbor_contours: dict[int, Contour] = {}
    for i in valid_neighbor_ids:
        c = neighbor_contours[i]
        dx, dy = alignment_deltas.get(i, (0.0, 0.0))
        aligned_points = [(x + dx, y + dy) for x, y in c.points]
        aligned_annulus = None
        if c.mitral_annulus is not None:
            (sx, sy), (lx, ly) = c.mitral_annulus
            aligned_annulus = ((sx + dx, sy + dy), (lx + dx, ly + dy))
        aligned_apex = None
        if c.apex_landmark is not None:
            aligned_apex = (c.apex_landmark[0] + dx, c.apex_landmark[1] + dy)
        aligned_neighbor_contours[i] = Contour(
            phase=c.phase,
            view=c.view,
            chamber=c.chamber,
            points=aligned_points,
            source=c.source,
            mitral_annulus=aligned_annulus,
            apex_landmark=aligned_apex,
            num_nodes=c.num_nodes,
            frame_index=c.frame_index,
            sop_instance_uid=c.sop_instance_uid,
        )

    # --- 1b. Outlier rejection ---
    if config.outlier_rejection:
        aligned_neighbor_contours = reject_outlier_neighbors(
            center_contour,
            aligned_neighbor_contours,
            max_shift_ratio=config.max_neighbor_shift_ratio,
        )
        # Rebuild valid_neighbor_ids and aligned_masks after rejection
        valid_neighbor_ids = sorted(aligned_neighbor_contours.keys())
        aligned_masks = [center_mask]
        alignment_deltas_filtered: dict[int, tuple[float, float]] = {}
        for i in valid_neighbor_ids:
            c = neighbor_contours[i]
            if c.mitral_annulus is not None:
                t_centroid = _ma_centroid(c.mitral_annulus)
                dx = center_centroid[0] - t_centroid[0]
                dy = center_centroid[1] - t_centroid[1]
                alignment_deltas_filtered[i] = (dx, dy)
                aligned_masks.append(align_mask_to_anchor(neighbor_masks[i], t_centroid, center_centroid))
            else:
                alignment_deltas_filtered[i] = (0.0, 0.0)
                aligned_masks.append(neighbor_masks[i])

    # --- 1c. Compute neighbor confidence scores ---
    confidence_scores: dict[int, float] = {}
    if config.confidence_weighted:
        for i in valid_neighbor_ids:
            nc = aligned_neighbor_contours.get(i, neighbor_contours[i])
            confidence_scores[i] = compute_neighbor_confidence(
                center_contour,
                nc,
                phase=phase,
            )
        # Filter by minimum confidence
        valid_neighbor_ids = [
            i for i in valid_neighbor_ids if confidence_scores.get(i, 0.0) >= config.min_confidence_score
        ]

    # --- 2. Mask vote fusion ---
    threshold = min(config.vote_threshold, len(aligned_masks))
    fused_mask = mask_vote_fusion(aligned_masks, threshold=threshold)

    # --- 3. Papillary cleanup + open arc ---
    fused_mask = papillary_mask_cleanup(fused_mask, phase=phase)
    if int(np.count_nonzero(fused_mask)) < 80:
        return TemporalFusionResult(
            anchor_frame_index=anchor_frame_index,
            fused_contour=center_contour,
            center_contour=center_contour,
            neighbor_contours={i: neighbor_contours[i] for i in valid_neighbor_ids},
            frames_used=1,
            frames_requested=len(neighbor_masks) + 1,
            config=config,
        )

    try:
        open_points, annulus, apex = open_arc_from_cavity_mask(
            fused_mask,
            original_shape=original_shape,
            num_nodes=32,
        )
    except ValueError:
        return TemporalFusionResult(
            anchor_frame_index=anchor_frame_index,
            fused_contour=center_contour,
            center_contour=center_contour,
            neighbor_contours={i: neighbor_contours[i] for i in valid_neighbor_ids},
            frames_used=1,
            frames_requested=len(neighbor_masks) + 1,
            config=config,
        )

    # --- 4. Node clamp ---
    ma_len = _ma_length(annulus)
    shift_cap = config.max_node_shift_ratio(phase) * ma_len
    apex_shift_cap = config.apex_max_shift_ratio(phase) * ma_len
    center_nodes = center_contour.points

    # Find apex index (node closest to apex landmark)
    apex_idx = None
    if center_contour.apex_landmark is not None:
        apex_pt = center_contour.apex_landmark
        min_dist = float("inf")
        for j, pt in enumerate(center_nodes):
            d = math.hypot(pt[0] - apex_pt[0], pt[1] - apex_pt[1])
            if d < min_dist:
                min_dist = d
                apex_idx = j

    # Resample all arcs to 32 nodes (center is already 32 from open_arc)
    neighbor_node_lists = []
    for i in valid_neighbor_ids:
        c = aligned_neighbor_contours.get(i, neighbor_contours[i])
        pts = c.points
        if len(pts) == len(open_points):
            neighbor_node_lists.append(pts)

    if neighbor_node_lists:
        median_nodes = [
            _component_wise_median([center_nodes[j]] + [nl[j] for nl in neighbor_node_lists])
            for j in range(len(open_points))
        ]
        fused_nodes = clamp_nodes_to_center(
            median_nodes,
            center_nodes,
            shift_cap,
            apex_index=apex_idx,
            apex_shift_cap=apex_shift_cap,
        )
    else:
        fused_nodes = list(open_points)

    # --- 5. Annulus fusion ---
    # Use center_contour.mitral_annulus as reference for δ clamp (spec §5.1)
    center_annulus = center_contour.mitral_annulus or annulus
    neighbor_annuli = [
        aligned_neighbor_contours[i].mitral_annulus
        for i in valid_neighbor_ids
        if aligned_neighbor_contours[i].mitral_annulus is not None
    ]
    delta = config.annulus_max_shift_ratio(phase) * ma_len
    fused_annulus = fuse_annulus_endpoints(center_annulus, neighbor_annuli, delta)
    fused_nodes[0] = fused_annulus[0]
    fused_nodes[-1] = fused_annulus[1]

    # --- 6. Apex direction lock ---
    if config.apex_direction_lock:
        neighbor_apices = [
            aligned_neighbor_contours[i].apex_landmark
            for i in valid_neighbor_ids
            if aligned_neighbor_contours[i].apex_landmark is not None
        ]
        center_apex = center_contour.apex_landmark or apex
        epsilon = config.apex_max_shift_ratio(phase) * ma_len
        fused_apex = apply_apex_direction_lock(apex, neighbor_apices, center_apex, epsilon)
    else:
        fused_apex = apex

    # --- 7. Concavity exclusion + smooth ---
    refined = exclude_papillary_concavities(
        fused_nodes,
        fused_annulus,
        fused_apex,
        phase=phase,
    )
    smoothed = smooth_open_arc(refined, fused_annulus, apex=fused_apex, iterations=4, blend=0.45)

    fused_contour = Contour(
        phase=center_contour.phase,
        view=center_contour.view,
        chamber=center_contour.chamber,
        points=smoothed,
        source="ai",
        mitral_annulus=fused_annulus,
        apex_landmark=fused_apex,
        num_nodes=len(smoothed),
        frame_index=anchor_frame_index,
        sop_instance_uid=center_contour.sop_instance_uid,
        review_pending=True,
    )

    return TemporalFusionResult(
        anchor_frame_index=anchor_frame_index,
        fused_contour=fused_contour,
        center_contour=center_contour,
        neighbor_contours={i: aligned_neighbor_contours[i] for i in valid_neighbor_ids},
        frames_used=1 + len(valid_neighbor_ids),
        frames_requested=len(neighbor_masks) + 1,
        config=config,
    )
