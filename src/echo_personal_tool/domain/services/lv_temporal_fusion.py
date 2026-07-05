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
from echo_personal_tool.domain.services.segmentation_service import (
    exclude_papillary_concavities,
    mask_to_contour,
    open_arc_from_cavity_mask,
    papillary_mask_cleanup,
)
from echo_personal_tool.domain.services.contour_geometry import (
    apex_point,
    smooth_open_arc,
)


def compute_window(
    anchor: int,
    total_frames: int,
    window: int = 2,
) -> list[int]:
    """Frame indices in [anchor-W .. anchor+W] clamped to [0, total_frames-1]."""
    return [
        i
        for i in range(max(0, anchor - window), min(total_frames, anchor + window + 1))
    ]


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
) -> list[tuple[float, float]]:
    """Clamp each node to center ± shift_cap."""
    result = []
    for m, c in zip(median_points, center_points):
        dx = m[0] - c[0]
        dy = m[1] - c[1]
        dist = math.hypot(dx, dy)
        if dist <= shift_cap or dist == 0.0:
            result.append(m)
        else:
            scale = shift_cap / dist
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
    valid_neighbor_ids = sorted(
        i for i in neighbor_masks if i in neighbor_contours
    )
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
    for i in valid_neighbor_ids:
        c = neighbor_contours[i]
        if c.mitral_annulus is not None:
            t_centroid = _ma_centroid(c.mitral_annulus)
            aligned = align_mask_to_anchor(neighbor_masks[i], t_centroid, center_centroid)
        else:
            aligned = neighbor_masks[i]
        aligned_masks.append(aligned)

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
    center_nodes = center_contour.points

    # Resample all arcs to 32 nodes (center is already 32 from open_arc)
    neighbor_node_lists = []
    for i in valid_neighbor_ids:
        c = neighbor_contours[i]
        pts = c.points
        if len(pts) == len(open_points):
            neighbor_node_lists.append(pts)

    if neighbor_node_lists:
        median_nodes = [
            _component_wise_median([center_nodes[j]] + [nl[j] for nl in neighbor_node_lists])
            for j in range(len(open_points))
        ]
        fused_nodes = clamp_nodes_to_center(median_nodes, center_nodes, shift_cap)
    else:
        fused_nodes = list(open_points)

    # --- 5. Annulus fusion ---
    neighbor_annuli = [
        neighbor_contours[i].mitral_annulus
        for i in valid_neighbor_ids
        if neighbor_contours[i].mitral_annulus is not None
    ]
    delta = config.annulus_max_shift_ratio(phase) * ma_len
    fused_annulus = fuse_annulus_endpoints(annulus, neighbor_annuli, delta)
    fused_nodes[0] = fused_annulus[0]
    fused_nodes[-1] = fused_annulus[1]

    # --- 6. Apex direction lock ---
    if config.apex_direction_lock:
        neighbor_apices = [
            neighbor_contours[i].apex_landmark
            for i in valid_neighbor_ids
            if neighbor_contours[i].apex_landmark is not None
        ]
        center_apex = center_contour.apex_landmark or apex
        epsilon = config.apex_max_shift_ratio(phase) * ma_len
        fused_apex = apply_apex_direction_lock(
            apex, neighbor_apices, center_apex, epsilon
        )
    else:
        fused_apex = apex

    # --- 7. Concavity exclusion + smooth ---
    refined = exclude_papillary_concavities(
        fused_nodes, fused_annulus, fused_apex, phase=phase,
    )
    smoothed = smooth_open_arc(refined, fused_annulus, apex=fused_apex, iterations=4, blend=0.0)

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
        neighbor_contours={i: neighbor_contours[i] for i in valid_neighbor_ids},
        frames_used=1 + len(valid_neighbor_ids),
        frames_requested=len(neighbor_masks) + 1,
        config=config,
    )
