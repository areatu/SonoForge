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
    DEFAULT_NODE_COUNT,
    apex_index_on_open_arc,
    apex_point,
    resample_open_arc,
    resample_open_arc_landmarks,
    smooth_open_arc,
)
from echo_personal_tool.domain.services.segmentation_service import (
    exclude_papillary_concavities,
    lv_cavity_mask_to_open_arc,
)

# Spec §2 v2: rotate around MA centroid when translation leaves >3 px apex residual.
APEX_RESIDUAL_ROTATION_PX = 3.0


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


def _wrap_angle(angle: float) -> float:
    """Wrap radians to (−π, π]."""
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def _rotate_xy(
    point: tuple[float, float],
    origin: tuple[float, float],
    angle_rad: float,
) -> tuple[float, float]:
    dx = point[0] - origin[0]
    dy = point[1] - origin[1]
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)
    return (origin[0] + cos_a * dx - sin_a * dy, origin[1] + sin_a * dx + cos_a * dy)


def _canonical_apex(contour: Contour) -> tuple[float, float] | None:
    """Simpson apex: stored landmark, else farthest arc point from MA chord."""
    if contour.apex_landmark is not None:
        return contour.apex_landmark
    if contour.mitral_annulus is not None and contour.points:
        try:
            return apex_point(contour.points, contour.mitral_annulus)
        except ValueError:
            return None
    return None


def _long_axis_angle(
    annulus: tuple[tuple[float, float], tuple[float, float]],
    apex: tuple[float, float] | None,
) -> float | None:
    """Angle of MA-mid→apex, or MA-chord if apex is missing."""
    mid = _ma_centroid(annulus)
    if apex is not None:
        dx = apex[0] - mid[0]
        dy = apex[1] - mid[1]
        if math.hypot(dx, dy) >= 1e-6:
            return math.atan2(dy, dx)
    septal, lateral = annulus
    dx = lateral[0] - septal[0]
    dy = lateral[1] - septal[1]
    if math.hypot(dx, dy) < 1e-6:
        return None
    return math.atan2(dy, dx)


def compute_rigid_alignment(
    center_contour: Contour,
    neighbor_contour: Contour,
    *,
    residual_threshold: float = APEX_RESIDUAL_ROTATION_PX,
) -> tuple[float, float, float]:
    """MA-centroid translation plus optional rotation if apex residual > threshold.

    Rotation is around the *center* MA centroid (after translation the neighbor
    mid coincides with it). Angle comes from MA-mid→apex, falling back to the
    MA-chord angle. Returns ``(dx, dy, angle_rad)``.
    """
    if center_contour.mitral_annulus is None or neighbor_contour.mitral_annulus is None:
        return (0.0, 0.0, 0.0)
    center_mid = _ma_centroid(center_contour.mitral_annulus)
    neighbor_mid = _ma_centroid(neighbor_contour.mitral_annulus)
    dx = center_mid[0] - neighbor_mid[0]
    dy = center_mid[1] - neighbor_mid[1]
    angle = 0.0
    center_apex = _canonical_apex(center_contour)
    neighbor_apex = _canonical_apex(neighbor_contour)
    translated_apex = None if neighbor_apex is None else (neighbor_apex[0] + dx, neighbor_apex[1] + dy)
    residual = 0.0
    if center_apex is not None and translated_apex is not None:
        residual = math.hypot(translated_apex[0] - center_apex[0], translated_apex[1] - center_apex[1])
    if residual > residual_threshold:
        n_septal, n_lateral = neighbor_contour.mitral_annulus
        translated_annulus = (
            (n_septal[0] + dx, n_septal[1] + dy),
            (n_lateral[0] + dx, n_lateral[1] + dy),
        )
        a_center = _long_axis_angle(center_contour.mitral_annulus, center_apex)
        a_neighbor = _long_axis_angle(translated_annulus, translated_apex)
        if a_center is not None and a_neighbor is not None:
            angle = _wrap_angle(a_center - a_neighbor)
    return (dx, dy, angle)


def apply_rigid_to_xy(
    point: tuple[float, float],
    dx: float,
    dy: float,
    origin: tuple[float, float],
    angle_rad: float,
) -> tuple[float, float]:
    """Translate then rotate around *origin* (center MA centroid)."""
    translated = (point[0] + dx, point[1] + dy)
    if abs(angle_rad) < 1e-12:
        return translated
    return _rotate_xy(translated, origin, angle_rad)


def apply_rigid_to_mask(
    mask: np.ndarray,
    dx: float,
    dy: float,
    origin: tuple[float, float],
    angle_rad: float,
) -> np.ndarray:
    """Apply the same rigid transform as ``apply_rigid_to_xy`` to a binary mask."""
    if abs(angle_rad) < 1e-12:
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            return mask
        shifted = ndimage.shift(mask.astype(np.float32), shift=(dy, dx), order=0)
        return (shifted >= 0.5).astype(np.uint8)
    # Inverse: p_in = C - T + R^{-1}(p_out - C)
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)
    cx, cy = origin
    matrix = np.array([[cos_a, -sin_a], [sin_a, cos_a]], dtype=np.float64)
    offset = np.array(
        [
            cy - dy - cos_a * cy + sin_a * cx,
            cx - dx - cos_a * cx - sin_a * cy,
        ],
        dtype=np.float64,
    )
    rotated = ndimage.affine_transform(
        mask.astype(np.float32),
        matrix,
        offset=offset,
        order=0,
        mode="constant",
        cval=0.0,
    )
    return (rotated >= 0.5).astype(np.uint8)


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


def _aligned_vote_masks(
    *,
    center_mask: np.ndarray,
    neighbor_masks: dict[int, np.ndarray],
    neighbor_ids: list[int],
    alignment_params: dict[int, tuple[float, float, float]],
    rotation_origin: tuple[float, float],
) -> list[np.ndarray]:
    """Center mask plus neighbors after MA-centroid translation and optional rotation."""
    aligned = [center_mask]
    for i in neighbor_ids:
        dx, dy, angle = alignment_params.get(i, (0.0, 0.0, 0.0))
        aligned.append(apply_rigid_to_mask(neighbor_masks[i], dx, dy, rotation_origin, angle))
    return aligned


def _apply_rigid_to_contour(
    contour: Contour,
    dx: float,
    dy: float,
    origin: tuple[float, float],
    angle_rad: float,
) -> Contour:
    aligned_points = [apply_rigid_to_xy(p, dx, dy, origin, angle_rad) for p in contour.points]
    aligned_annulus = None
    if contour.mitral_annulus is not None:
        septal, lateral = contour.mitral_annulus
        aligned_annulus = (
            apply_rigid_to_xy(septal, dx, dy, origin, angle_rad),
            apply_rigid_to_xy(lateral, dx, dy, origin, angle_rad),
        )
    aligned_apex = None
    if contour.apex_landmark is not None:
        aligned_apex = apply_rigid_to_xy(contour.apex_landmark, dx, dy, origin, angle_rad)
    return Contour(
        phase=contour.phase,
        view=contour.view,
        chamber=contour.chamber,
        points=aligned_points,
        source=contour.source,
        mitral_annulus=aligned_annulus,
        apex_landmark=aligned_apex,
        num_nodes=contour.num_nodes,
        frame_index=contour.frame_index,
        sop_instance_uid=contour.sop_instance_uid,
    )


def _resample_arc_to_nodes(
    contour: Contour,
    *,
    num_nodes: int = DEFAULT_NODE_COUNT,
) -> list[tuple[float, float]]:
    """Resample an open arc to *num_nodes* using that frame's aligned MA."""
    points = list(contour.points)
    if len(points) < 2:
        return points
    annulus = contour.mitral_annulus
    if annulus is not None:
        septal, lateral = annulus
        apex = contour.apex_landmark or points[len(points) // 2]
        return resample_open_arc_landmarks(
            points,
            septal=septal,
            lateral=lateral,
            apex=apex,
            num_nodes=num_nodes,
        )
    return resample_open_arc(points, num_nodes=num_nodes)


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
    frames_requested: int | None = None,
) -> TemporalFusionResult:
    """Full temporal fusion pipeline on anchor frame N.

    1. Align neighbors to anchor (MA-centroid translation; rotate if apex residual > 3 px).
    2. Mask vote fusion (after outlier + confidence filters rebuild the vote set).
    3. Two-pass ``lv_cavity_mask_to_open_arc`` on the fused LV mask.
    4. Interior nodes: resample, median, clamp (apex node stricter).
    5. Canonical apex + direction lock, then annulus fuse + pin.
    6. Papillary concavity exclusion + smooth (refine on frame N is the controller).
    """
    valid_neighbor_ids = sorted(i for i in neighbor_masks if i in neighbor_contours)
    requested = frames_requested if frames_requested is not None else len(neighbor_masks) + 1

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
            frames_requested=requested,
            config=config,
        )

    center_centroid = _ma_centroid(center_ma)

    alignment_params: dict[int, tuple[float, float, float]] = {}
    aligned_neighbor_contours: dict[int, Contour] = {}
    for i in valid_neighbor_ids:
        c = neighbor_contours[i]
        dx, dy, angle = compute_rigid_alignment(center_contour, c)
        alignment_params[i] = (dx, dy, angle)
        aligned_neighbor_contours[i] = _apply_rigid_to_contour(c, dx, dy, center_centroid, angle)

    aligned_masks = _aligned_vote_masks(
        center_mask=center_mask,
        neighbor_masks=neighbor_masks,
        neighbor_ids=valid_neighbor_ids,
        alignment_params=alignment_params,
        rotation_origin=center_centroid,
    )

    # --- 1b. Outlier rejection ---
    if config.outlier_rejection:
        aligned_neighbor_contours = reject_outlier_neighbors(
            center_contour,
            aligned_neighbor_contours,
            max_shift_ratio=config.max_neighbor_shift_ratio,
        )
        valid_neighbor_ids = sorted(aligned_neighbor_contours.keys())
        aligned_masks = _aligned_vote_masks(
            center_mask=center_mask,
            neighbor_masks=neighbor_masks,
            neighbor_ids=valid_neighbor_ids,
            alignment_params=alignment_params,
            rotation_origin=center_centroid,
        )

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
        valid_neighbor_ids = [
            i for i in valid_neighbor_ids if confidence_scores.get(i, 0.0) >= config.min_confidence_score
        ]
        aligned_masks = _aligned_vote_masks(
            center_mask=center_mask,
            neighbor_masks=neighbor_masks,
            neighbor_ids=valid_neighbor_ids,
            alignment_params=alignment_params,
            rotation_origin=center_centroid,
        )

    # --- 2. Mask vote fusion ---
    n_valid = len(aligned_masks)
    threshold = min(config.vote_threshold, n_valid)
    fused_mask = mask_vote_fusion(aligned_masks, threshold=threshold)

    # --- 3. Two-pass open arc (LV) / LA contour ---
    is_la = (center_contour.chamber or "").upper() == "LA"
    if is_la:
        from echo_personal_tool.domain.services.la_segmentation_service import la_mask_to_contour

        if int(np.count_nonzero(fused_mask)) < 80:
            return TemporalFusionResult(
                anchor_frame_index=anchor_frame_index,
                fused_contour=center_contour,
                center_contour=center_contour,
                neighbor_contours={i: neighbor_contours[i] for i in valid_neighbor_ids},
                frames_used=1,
                frames_requested=requested,
                config=config,
            )
        try:
            open_points, annulus, apex = la_mask_to_contour(fused_mask, num_nodes=DEFAULT_NODE_COUNT)
        except ValueError:
            return TemporalFusionResult(
                anchor_frame_index=anchor_frame_index,
                fused_contour=center_contour,
                center_contour=center_contour,
                neighbor_contours={i: neighbor_contours[i] for i in valid_neighbor_ids},
                frames_used=1,
                frames_requested=requested,
                config=config,
            )
    else:
        if int(np.count_nonzero(fused_mask)) < 80:
            return TemporalFusionResult(
                anchor_frame_index=anchor_frame_index,
                fused_contour=center_contour,
                center_contour=center_contour,
                neighbor_contours={i: neighbor_contours[i] for i in valid_neighbor_ids},
                frames_used=1,
                frames_requested=requested,
                config=config,
            )

        try:
            open_points, annulus, apex, fused_mask = lv_cavity_mask_to_open_arc(
                fused_mask,
                original_shape=original_shape,
                phase=phase,
                view_hint=center_contour.view or "A4C",
                num_nodes=DEFAULT_NODE_COUNT,
            )
        except ValueError:
            return TemporalFusionResult(
                anchor_frame_index=anchor_frame_index,
                fused_contour=center_contour,
                center_contour=center_contour,
                neighbor_contours={i: neighbor_contours[i] for i in valid_neighbor_ids},
                frames_used=1,
                frames_requested=requested,
                config=config,
            )

    # --- 4. Node clamp ---
    ma_len = _ma_length(annulus)
    shift_cap = config.max_node_shift_ratio(phase) * ma_len
    apex_shift_cap = config.apex_max_shift_ratio(phase) * ma_len
    n_nodes = DEFAULT_NODE_COUNT
    center_nodes = _resample_arc_to_nodes(center_contour, num_nodes=n_nodes)

    # Apex node = interior node farthest from MA chord (Simpson / A1)
    apex_idx = None
    if len(center_nodes) >= 3:
        apex_idx = apex_index_on_open_arc(center_nodes, center_contour.mitral_annulus or annulus)


    neighbor_node_lists: list[list[tuple[float, float]]] = []
    for i in valid_neighbor_ids:
        c = aligned_neighbor_contours.get(i, neighbor_contours[i])
        pts = _resample_arc_to_nodes(c, num_nodes=n_nodes)
        if len(pts) != n_nodes and len(pts) >= 2:
            pts = resample_open_arc(pts, num_nodes=n_nodes)
        if len(pts) != n_nodes:
            pts = list(open_points)
        neighbor_node_lists.append(pts)

    if neighbor_node_lists and len(center_nodes) == n_nodes:
        median_nodes = [
            _component_wise_median([center_nodes[j]] + [nl[j] for nl in neighbor_node_lists])
            for j in range(n_nodes)
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

    # --- 5. Canonical apex + direction lock (before annulus pin) ---
    clamp_annulus = center_contour.mitral_annulus or annulus
    try:
        fused_apex = apex_point(fused_nodes, clamp_annulus)
    except ValueError:
        fused_apex = apex
    if config.apex_direction_lock:
        neighbor_apices = [
            canonical
            for i in valid_neighbor_ids
            if (canonical := _canonical_apex(aligned_neighbor_contours[i])) is not None
        ]
        center_apex = _canonical_apex(center_contour) or fused_apex
        epsilon = config.apex_max_shift_ratio(phase) * ma_len
        fused_apex = apply_apex_direction_lock(fused_apex, neighbor_apices, center_apex, epsilon)
    if apex_idx is not None and 0 < apex_idx < len(fused_nodes) - 1:
        fused_nodes[apex_idx] = fused_apex

    # --- 6. Annulus fusion then pin endpoints ---
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

    # --- 7. Concavity exclusion + smooth ---
    if is_la:
        smoothed = smooth_open_arc(fused_nodes, fused_annulus, apex=fused_apex, iterations=4, blend=0.45)
    else:
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
        frames_requested=requested,
        config=config,
    )
