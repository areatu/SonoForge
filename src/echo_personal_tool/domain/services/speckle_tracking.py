"""Core speckle tracking engine: block matching with NCC, pyramidal approach."""

from __future__ import annotations

import logging
from collections.abc import Callable

import cv2
import numpy as np
from scipy.ndimage import gaussian_filter

from echo_personal_tool.domain.models.speckle import (
    MyocardialZone,
    SpeckleConfig,
    TrackingKernel,
    TrackingResult,
)

logger = logging.getLogger(__name__)


def build_gaussian_pyramid(frame: np.ndarray, levels: int) -> list[np.ndarray]:
    pyramid: list[np.ndarray] = [frame]
    current = frame.astype(np.float32)
    for _ in range(1, levels):
        h, w = current.shape[:2]
        if h < 4 or w < 4:
            break
        blurred = gaussian_filter(current, sigma=1.5)
        down = blurred[::2, ::2]
        pyramid.append(down)
        current = down
    return pyramid


def refine_subpixel(
    correlation_map: np.ndarray,
    peak: tuple[int, int],
) -> tuple[float, float]:
    py, px = peak
    h, w = correlation_map.shape
    if py < 1 or py >= h - 1 or px < 1 or px >= w - 1:
        return (0.0, 0.0)
    c_center = correlation_map[py, px]
    col_offset = 0.0
    row_offset = 0.0
    c_left = correlation_map[py, px - 1]
    c_right = correlation_map[py, px + 1]
    denom_x = c_left - 2 * c_center + c_right
    if abs(denom_x) > 1e-10:
        col_offset = 0.5 * (c_left - c_right) / denom_x
    c_up = correlation_map[py - 1, px]
    c_down = correlation_map[py + 1, px]
    denom_y = c_up - 2 * c_center + c_down
    if abs(denom_y) > 1e-10:
        row_offset = 0.5 * (c_up - c_down) / denom_y
    return (float(np.clip(row_offset, -0.5, 0.5)), float(np.clip(col_offset, -0.5, 0.5)))


def block_match_single(
    reference_pyramid: list[np.ndarray],
    target_pyramid: list[np.ndarray],
    center: tuple[float, float],
    config: SpeckleConfig,
) -> tuple[float, float, float]:
    half = config.kernel_size // 2
    orig_cx, orig_cy = center
    cx, cy = center
    dx_total, dy_total = 0.0, 0.0
    best_ncc = 0.0

    for level in range(config.pyramid_levels - 1, -1, -1):
        scale = 2**level
        ref_cx_l = orig_cx / scale
        ref_cy_l = orig_cy / scale
        cx_l = cx / scale
        cy_l = cy / scale
        half_l = half // scale
        if half_l < 1:
            half_l = 1
        search_r = config.search_radius // scale

        ref_l = reference_pyramid[level]
        tgt_l = target_pyramid[level]
        h_l, w_l = tgt_l.shape[:2]

        k_h = 2 * half_l
        k_w = 2 * half_l
        k_x0 = int(round(ref_cx_l)) - half_l
        k_y0 = int(round(ref_cy_l)) - half_l
        if k_x0 < 0 or k_y0 < 0 or k_x0 + k_w > ref_l.shape[1] or k_y0 + k_h > ref_l.shape[0]:
            continue
        k_level = ref_l[k_y0 : k_y0 + k_h, k_x0 : k_x0 + k_w].astype(np.float32)

        x0 = max(0, int(cx_l) - search_r)
        y0 = max(0, int(cy_l) - search_r)
        x1 = min(w_l, int(cx_l) + search_r + 1)
        y1 = min(h_l, int(cy_l) + search_r + 1)

        if x1 - x0 < k_w or y1 - y0 < k_h:
            continue

        search_region = tgt_l[y0:y1, x0:x1].astype(np.float32)
        if search_region.shape[0] < k_h or search_region.shape[1] < k_w:
            continue

        result = cv2.matchTemplate(search_region, k_level, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        best_ncc = float(max_val)
        best_dx = max_loc[0] + k_w / 2.0 - (cx_l - x0)
        best_dy = max_loc[1] + k_h / 2.0 - (cy_l - y0)

        if level == 0 and config.subpixel and best_ncc > 0:
            py_r, px_r = max_loc
            if 1 <= py_r < result.shape[0] - 1 and 1 <= px_r < result.shape[1] - 1:
                corr_3x3 = result[py_r - 1 : py_r + 2, px_r - 1 : px_r + 2]
                sub_dy, sub_dx = refine_subpixel(corr_3x3, (1, 1))
                best_dx += sub_dx
                best_dy += sub_dy

        dx_total += best_dx * scale
        dy_total += best_dy * scale
        cx += best_dx * scale
        cy += best_dy * scale

    return (dx_total, dy_total, max(0.0, best_ncc))


def track_frame_pair(
    reference: np.ndarray,
    target: np.ndarray,
    kernels: list[TrackingKernel],
    config: SpeckleConfig,
    zone_mask: np.ndarray | None = None,
) -> TrackingResult:
    pyramids_ref = build_gaussian_pyramid(reference.astype(np.float32), config.pyramid_levels)
    pyramids_tgt = build_gaussian_pyramid(target.astype(np.float32), config.pyramid_levels)

    n = len(kernels)
    displacements = np.zeros((n, 2), dtype=np.float64)
    ncc_scores = np.zeros(n, dtype=np.float64)
    positions = np.zeros((n, 2), dtype=np.float64)

    for i, kernel_obj in enumerate(kernels):
        dx, dy, ncc = block_match_single(pyramids_ref, pyramids_tgt, kernel_obj.center, config)
        displacements[i] = [dx, dy]
        ncc_scores[i] = ncc
        positions[i] = [
            kernel_obj.center[0] + dx,
            kernel_obj.center[1] + dy,
        ]

    valid_mask = ncc_scores >= config.ncc_threshold

    if zone_mask is not None:
        h, w = zone_mask.shape
        for i in range(n):
            px = int(round(positions[i, 0]))
            py = int(round(positions[i, 1]))
            if px < 0 or px >= w or py < 0 or py >= h:
                valid_mask[i] = False
            elif not zone_mask[py, px]:
                valid_mask[i] = False

    if config.outlier_sigma > 0 and valid_mask.sum() > 3:
        # Spatial consistency: flag kernels whose displacement vector deviates
        # from the median of the valid population (robust MAD z-score). This
        # catches "jumped-to-search-boundary" matches while leaving coherent
        # whole-wall motion (e.g. the large ED→ES displacement) untouched.
        valid_disp = displacements[valid_mask]
        med = np.median(valid_disp, axis=0)
        dev = np.linalg.norm(valid_disp - med, axis=1)
        mad = np.median(np.abs(dev - np.median(dev))) + 1e-9
        z = dev / (1.4826 * mad)
        valid_mask[valid_mask] &= z <= config.outlier_sigma

    return TrackingResult(
        frame_index=0,
        displacements=displacements,
        ncc_scores=ncc_scores,
        valid_mask=valid_mask,
        kernel_positions=positions,
    )


def track_frame_from_reference(
    reference: np.ndarray,
    target: np.ndarray,
    reference_kernels: list[TrackingKernel],
    config: SpeckleConfig,
    zone_mask: np.ndarray | None = None,
) -> TrackingResult:
    kernels = [
        TrackingKernel(
            center=k.center,
            node_index=k.node_index,
            layer=k.layer,
            radius=k.radius,
            aha_segment=k.aha_segment,
            arc_length_param=k.arc_length_param,
        )
        for k in reference_kernels
    ]
    return track_frame_pair(reference, target, kernels, config, zone_mask)


def build_zone_mask(
    zone: MyocardialZone,
    frame_shape: tuple[int, int],
) -> np.ndarray:
    h, w = frame_shape
    mask = np.zeros((h, w), dtype=np.uint8)
    epi = np.round(zone.epi_points).astype(np.int32)
    endo = np.round(zone.endo_points).astype(np.int32)
    if len(epi) >= 3:
        cv2.fillPoly(mask, [epi], 1)
    if len(endo) >= 3:
        hole = np.zeros((h, w), dtype=np.uint8)
        cv2.fillPoly(hole, [endo], 1)
        mask = mask & ~hole
    return mask.astype(bool)


def _outward_normals(points: np.ndarray) -> np.ndarray:
    """Unit normals pointing away from the contour centroid (outward for the LV).

    For the open A4C endocardial contour the centroid lies inside the LV cavity,
    so flipping each normal away from the centroid yields the epicardial
    direction. This mirrors ``SpeckleOverlay.show_myocardial_zone_dynamic`` and
    avoids the septal-lateral midpoint heuristic used by ``myocardial_zone``.
    """
    pts = np.asarray(points, dtype=np.float64)
    n = len(pts)
    if n < 2:
        return np.zeros_like(pts)
    tangents = np.zeros_like(pts)
    tangents[0] = pts[1] - pts[0]
    tangents[-1] = pts[-1] - pts[-2]
    tangents[1:-1] = pts[2:] - pts[:-2]
    normals = np.column_stack([-tangents[:, 1], tangents[:, 0]])
    norms = np.linalg.norm(normals, axis=1, keepdims=True)
    norms[norms < 1e-10] = 1.0
    normals = normals / norms
    to_center = np.mean(pts, axis=0) - pts
    dot = np.sum(normals * to_center, axis=1)
    normals[dot > 0] *= -1.0
    return normals


def build_zone_mask_from_kernels(
    kernel_positions: np.ndarray,
    layer_mask: np.ndarray,
    frame_shape: tuple[int, int],
    wall_thickness_px: int = 20,
    epi_layer_mask: np.ndarray | None = None,
) -> np.ndarray:
    """Build the myocardial ring mask from tracked kernel positions.

    Reconstructs endo/epi contours and subtracts the endocardial polygon from
    the epicardial one — the same geometry as ``build_zone_mask``. If no
    epicardial layer is available, the endo contour is expanded outward along
    smooth normals.

    The previous convex-hull approach is kept only as a last-resort fallback:
    for the open A4C contour the convex hull of the endo border wraps around the
    LV cavity, so the mask covered mostly blood pool instead of myocardium.
    """
    h, w = frame_shape
    endo_pts = np.asarray(kernel_positions[layer_mask], dtype=np.float64)
    if len(endo_pts) < 3:
        return np.zeros((h, w), dtype=bool)

    epi_pts: np.ndarray | None = None
    if epi_layer_mask is not None and int(epi_layer_mask.sum()) >= 3:
        epi_pts = np.asarray(kernel_positions[epi_layer_mask], dtype=np.float64)

    if epi_pts is None:
        epi_pts = endo_pts + _outward_normals(endo_pts) * float(wall_thickness_px)

    mask = np.zeros((h, w), dtype=np.uint8)
    epi_poly = np.round(epi_pts).astype(np.int32)
    endo_poly = np.round(endo_pts).astype(np.int32)
    cv2.fillPoly(mask, [epi_poly], 1)
    cv2.fillPoly(mask, [endo_poly], 0)
    mask = mask.astype(bool)

    # Slight dilation so the constraint stays lenient to epi motion/noise.
    pad = max(2, int(wall_thickness_px // 8))
    structuring = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * pad + 1, 2 * pad + 1))
    if mask.any():
        mask = cv2.dilate(mask.astype(np.uint8), structuring, iterations=1).astype(bool)
    else:
        # Last-resort fallback for degenerate geometry (few collinear points).
        hull = cv2.convexHull(endo_poly)
        if hull is not None and len(hull) >= 3:
            cv2.fillPoly(mask.astype(np.uint8), [hull], 1)
            mask = cv2.dilate(mask.astype(np.uint8), structuring, iterations=1).astype(bool)
    return mask


def preprocess_echo_frame(
    frame: np.ndarray,
    clahe_clip: float = 2.0,
    clahe_grid: int = 8,
    log_compress: bool = True,
    median_ksize: int = 3,
) -> np.ndarray:
    f = frame.copy()
    if f.ndim == 3 and f.shape[2] >= 3:
        f = np.mean(f[:, :, :3].astype(np.float64), axis=2).astype(np.float32)
    if log_compress and f.max() > 0:
        f = np.log1p(f.astype(np.float64)) / np.log1p(f.max())
    f_uint8 = np.clip(f * 255, 0, 255).astype(np.uint8)
    clahe = cv2.createCLAHE(clipLimit=clahe_clip, tileGridSize=(clahe_grid, clahe_grid))
    f_uint8 = clahe.apply(f_uint8)
    if median_ksize > 1:
        f_uint8 = cv2.medianBlur(f_uint8, median_ksize)
    return f_uint8.astype(np.float32) / 255.0


def track_cine_bidirectional(
    frames: np.ndarray,
    initial_kernels: list[TrackingKernel],
    ed_index: int,
    config: SpeckleConfig,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[TrackingResult]:
    n_frames = frames.shape[0]
    ed_index = int(np.clip(ed_index, 0, n_frames - 1))
    ed_centers = np.array([k.center for k in initial_kernels], dtype=np.float64)
    ed_frame = frames[ed_index]
    n_kernels = len(initial_kernels)

    positions = np.zeros((n_frames, n_kernels, 2), dtype=np.float64)
    ncc_all = np.zeros((n_frames, n_kernels), dtype=np.float64)
    valid_all = np.zeros((n_frames, n_kernels), dtype=bool)
    positions[ed_index] = ed_centers
    ncc_all[ed_index] = 1.0
    valid_all[ed_index] = True

    for t in range(n_frames):
        if t == ed_index:
            if progress_callback:
                progress_callback(t + 1, n_frames)
            continue

        fwd = track_frame_from_reference(ed_frame, frames[t], initial_kernels, config)
        p_fwd = fwd.kernel_positions
        w_fwd = fwd.ncc_scores
        v_fwd = fwd.valid_mask

        positions[t] = p_fwd
        ncc_all[t] = w_fwd
        valid_all[t] = v_fwd

        if config.bidirectional:
            bwd_kernels = [
                TrackingKernel(
                    center=(float(p_fwd[i, 0]), float(p_fwd[i, 1])),
                    node_index=initial_kernels[i].node_index,
                    layer=initial_kernels[i].layer,
                    radius=initial_kernels[i].radius,
                    aha_segment=initial_kernels[i].aha_segment,
                    arc_length_param=initial_kernels[i].arc_length_param,
                )
                for i in range(n_kernels)
            ]
            bwd = track_frame_pair(frames[t], ed_frame, bwd_kernels, config)
            for i in range(n_kernels):
                if v_fwd[i] and bwd.valid_mask[i]:
                    closure_err = float(np.linalg.norm(bwd.kernel_positions[i] - ed_centers[i]))
                    if closure_err > config.search_radius * 0.8:
                        valid_all[t, i] = False
                    else:
                        ncc_all[t, i] = (w_fwd[i] + bwd.ncc_scores[i]) / 2.0

        if progress_callback:
            progress_callback(t + 1, n_frames)

    results: list[TrackingResult] = []
    for t in range(n_frames):
        if t == ed_index:
            continue
        disp = positions[t] - positions[ed_index]
        results.append(
            TrackingResult(
                frame_index=t,
                displacements=disp,
                ncc_scores=ncc_all[t],
                valid_mask=valid_all[t],
                kernel_positions=positions[t],
                reference_frame=ed_index,
            )
        )
    return results


def track_cine_incremental(
    frames: np.ndarray,
    initial_kernels: list[TrackingKernel],
    ed_index: int,
    config: SpeckleConfig,
    progress_callback: Callable[[int, int], None] | None = None,
    zone_mask: np.ndarray | None = None,
    wall_thickness_px: int = 20,
    n_iterations: int = 2,
) -> list[TrackingResult]:
    """ED-anchored tracking with progressive zone deformation and iterative refinement.

    Two-pass approach:
    1. Coarse pass: track without zone constraint to get approximate positions
    2. Fine pass(s): re-track with zone mask interpolated between ED and ES positions
       Repeat n_iterations times, using previous result as new ED positions.

    Args:
        frames: (N, H, W) preprocessed CINE frames.
        initial_kernels: kernels at ED frame.
        ed_index: ED frame index.
        config: tracking configuration.
        progress_callback: optional (current, total) progress reporter.
        zone_mask: static zone mask (used as fallback).
        wall_thickness_px: wall thickness for progressive zone.
        n_iterations: number of refinement iterations (1 = no refinement).

    Returns:
        List of TrackingResult for each frame (excluding ED).
    """
    n_frames = frames.shape[0]
    ed_index = int(np.clip(ed_index, 0, n_frames - 1))
    n_kernels = len(initial_kernels)
    ed_centers = np.array([k.center for k in initial_kernels], dtype=np.float64)
    ed_frame = frames[ed_index]
    frame_shape = frames.shape[1:3]
    endo_mask = np.array([k.layer == "endo" for k in initial_kernels], dtype=bool)
    epi_mask = np.array([k.layer == "epi" for k in initial_kernels], dtype=bool)

    coarse_positions = np.zeros((n_frames, n_kernels, 2), dtype=np.float64)
    coarse_ncc = np.zeros((n_frames, n_kernels), dtype=np.float64)
    coarse_valid = np.zeros((n_frames, n_kernels), dtype=bool)
    coarse_positions[ed_index] = ed_centers
    coarse_ncc[ed_index] = 1.0
    coarse_valid[ed_index] = True

    for t in range(n_frames):
        if t == ed_index:
            continue
        match = track_frame_from_reference(ed_frame, frames[t], initial_kernels, config)
        coarse_positions[t] = match.kernel_positions
        coarse_ncc[t] = match.ncc_scores
        coarse_valid[t] = match.valid_mask

    es_index = ed_index
    best_area = 0.0
    for t in range(n_frames):
        endo_pts = coarse_positions[t, endo_mask, :]
        if len(endo_pts) >= 3:
            hull = cv2.convexHull(endo_pts.astype(np.float32))
            area = cv2.contourArea(hull)
            if area < best_area or best_area == 0:
                best_area = area
                es_index = t

    if es_index == ed_index:
        es_index = min(ed_index + n_frames // 3, n_frames - 1)

    logger.info(
        "STE progressive zone: ed=%d, es=%d, n_frames=%d, iterations=%d",
        ed_index,
        es_index,
        n_frames,
        n_iterations,
    )

    current_ed_centers = ed_centers.copy()
    final_positions_prev = coarse_positions

    for iteration in range(n_iterations):
        final_positions = np.zeros((n_frames, n_kernels, 2), dtype=np.float64)
        final_ncc = np.zeros((n_frames, n_kernels), dtype=np.float64)
        final_valid = np.zeros((n_frames, n_kernels), dtype=bool)
        final_positions[ed_index] = current_ed_centers
        final_ncc[ed_index] = 1.0
        final_valid[ed_index] = True

        if iteration == 0:
            es_positions = coarse_positions[es_index]
        else:
            es_positions = final_positions_prev[es_index]

        total_span = max(abs(es_index - ed_index), 1)

        for t in range(n_frames):
            if t == ed_index:
                if progress_callback:
                    progress_callback(t + 1, n_frames)
                continue

            span = abs(t - ed_index)
            alpha = min(span / total_span, 1.0)
            interp_centers = current_ed_centers * (1.0 - alpha) + es_positions * alpha

            interp_kernels = [
                TrackingKernel(
                    center=(float(interp_centers[i, 0]), float(interp_centers[i, 1])),
                    node_index=initial_kernels[i].node_index,
                    layer=initial_kernels[i].layer,
                    radius=initial_kernels[i].radius,
                    aha_segment=initial_kernels[i].aha_segment,
                    arc_length_param=initial_kernels[i].arc_length_param,
                )
                for i in range(n_kernels)
            ]

            progressive_mask = build_zone_mask_from_kernels(
                interp_centers,
                endo_mask,
                frame_shape,
                wall_thickness_px,
                epi_layer_mask=epi_mask,
            )
            if progressive_mask.any():
                frame_mask: np.ndarray | None = progressive_mask
            elif zone_mask is not None:
                frame_mask = zone_mask
            else:
                frame_mask = None

            match = track_frame_from_reference(
                ed_frame,
                frames[t],
                interp_kernels,
                config,
                frame_mask,
            )

            final_positions[t] = match.kernel_positions
            final_ncc[t] = match.ncc_scores
            final_valid[t] = match.valid_mask

            if config.bidirectional:
                bwd_kernels = [
                    TrackingKernel(
                        center=(float(match.kernel_positions[i, 0]), float(match.kernel_positions[i, 1])),
                        node_index=initial_kernels[i].node_index,
                        layer=initial_kernels[i].layer,
                        radius=initial_kernels[i].radius,
                        aha_segment=initial_kernels[i].aha_segment,
                        arc_length_param=initial_kernels[i].arc_length_param,
                    )
                    for i in range(n_kernels)
                ]
                bwd = track_frame_pair(frames[t], ed_frame, bwd_kernels, config)
                for i in range(n_kernels):
                    if match.valid_mask[i] and bwd.valid_mask[i]:
                        closure_err = float(np.linalg.norm(bwd.kernel_positions[i] - current_ed_centers[i]))
                        if closure_err > config.search_radius * 0.8:
                            final_valid[t, i] = False
                        else:
                            final_ncc[t, i] = (match.ncc_scores[i] + bwd.ncc_scores[i]) / 2.0

            if progress_callback:
                progress_callback(t + 1, n_frames)

        final_positions_prev = final_positions.copy()

        if iteration < n_iterations - 1:
            mean_positions = np.mean(final_positions, axis=0)
            current_ed_centers = mean_positions
            logger.info("STE refinement iteration %d done, updating ED centers", iteration + 1)

    results: list[TrackingResult] = []
    for t in range(n_frames):
        if t == ed_index:
            continue
        disp = final_positions[t] - final_positions[ed_index]
        results.append(
            TrackingResult(
                frame_index=t,
                displacements=disp,
                ncc_scores=final_ncc[t],
                valid_mask=final_valid[t],
                kernel_positions=final_positions[t],
                reference_frame=ed_index,
            )
        )
    return results


def track_cine_sequential(
    frames: np.ndarray,
    initial_kernels: list[TrackingKernel],
    ed_index: int,
    config: SpeckleConfig,
    progress_callback: Callable[[int, int], None] | None = None,
    zone_mask: np.ndarray | None = None,
) -> list[TrackingResult]:
    """Frame-to-frame tracking with per-step re-anchoring.

    Matches every frame against its immediate predecessor instead of jumping
    from ED. Inter-frame myocardial motion is small (sub-pixel to a couple of
    pixels), so NCC stays high through the whole cycle and the myocardial zone
    is followed accurately. ED-anchored modes decorrelate near end-systole
    because the speckle pattern changes with the large accumulated displacement
    (and out-of-plane motion), after which invalid kernels are merely
    interpolated rather than tracked.

    Invalid kernels keep their last known position so they can re-lock on the
    next frame; optional forward-backward consistency (``config.bidirectional``)
    rejects kernels whose round trip does not close.

    Returns one ``TrackingResult`` per frame except ``ed_index``; displacements
    and positions are anchored to ED (positions are shifted so the ED frame
    coincides with the initial kernel centers).
    """
    n_frames = frames.shape[0]
    ed_index = int(np.clip(ed_index, 0, n_frames - 1))
    n_kernels = len(initial_kernels)
    ed_centers = np.array([k.center for k in initial_kernels], dtype=np.float64)

    positions = np.zeros((n_frames, n_kernels, 2), dtype=np.float64)
    ncc = np.zeros((n_frames, n_kernels), dtype=np.float64)
    valid = np.zeros((n_frames, n_kernels), dtype=bool)
    positions[0] = ed_centers
    ncc[0] = 1.0
    valid[0] = True

    current = list(initial_kernels)

    for i in range(n_frames - 1):
        match = track_frame_pair(frames[i], frames[i + 1], current, config, zone_mask)

        prev_pos = positions[i]
        for j in range(n_kernels):
            positions[i + 1, j] = match.kernel_positions[j] if match.valid_mask[j] else prev_pos[j]
        ncc[i + 1] = match.ncc_scores
        valid[i + 1] = match.valid_mask

        if config.bidirectional:
            bwd_kernels = [
                TrackingKernel(
                    center=(float(positions[i + 1, j, 0]), float(positions[i + 1, j, 1])),
                    node_index=k.node_index,
                    layer=k.layer,
                    radius=k.radius,
                    aha_segment=k.aha_segment,
                    arc_length_param=k.arc_length_param,
                )
                for j, k in enumerate(current)
            ]
            bwd = track_frame_pair(frames[i + 1], frames[i], bwd_kernels, config, zone_mask)
            for j in range(n_kernels):
                if valid[i + 1, j] and bwd.valid_mask[j]:
                    closure_err = float(np.linalg.norm(bwd.kernel_positions[j] - prev_pos[j]))
                    if closure_err > config.search_radius:
                        valid[i + 1, j] = False
                    else:
                        ncc[i + 1, j] = (ncc[i + 1, j] + bwd.ncc_scores[j]) / 2.0

        current = [
            TrackingKernel(
                center=(float(positions[i + 1, j, 0]), float(positions[i + 1, j, 1])),
                node_index=k.node_index,
                layer=k.layer,
                radius=k.radius,
                aha_segment=k.aha_segment,
                arc_length_param=k.arc_length_param,
            )
            for j, k in enumerate(current)
        ]

        if progress_callback:
            progress_callback(i + 1, n_frames - 1)

    # Zero out any drift accumulated before ED so ED is the exact anchor.
    positions -= (positions[ed_index] - ed_centers)[None, :, :]

    results: list[TrackingResult] = []
    for t in range(n_frames):
        if t == ed_index:
            continue
        results.append(
            TrackingResult(
                frame_index=t,
                displacements=positions[t] - positions[ed_index],
                ncc_scores=ncc[t],
                valid_mask=valid[t],
                kernel_positions=positions[t],
                reference_frame=ed_index,
            )
        )
    return results


def track_cine(
    frames: np.ndarray,
    initial_kernels: list[TrackingKernel],
    config: SpeckleConfig,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[TrackingResult]:
    if config.bidirectional and config.ed_anchored:
        return track_cine_bidirectional(
            frames,
            initial_kernels,
            ed_index=0,
            config=config,
            progress_callback=progress_callback,
        )
    n_frames = frames.shape[0]
    results: list[TrackingResult] = []
    current_kernels = list(initial_kernels)
    for i in range(n_frames - 1):
        result = track_frame_pair(frames[i], frames[i + 1], current_kernels, config)
        result.frame_index = i + 1
        results.append(result)
        for j, kernel in enumerate(current_kernels):
            if result.valid_mask[j]:
                new_x = float(result.kernel_positions[j, 0])
                new_y = float(result.kernel_positions[j, 1])
                current_kernels[j] = TrackingKernel(
                    center=(new_x, new_y),
                    radius=kernel.radius,
                    node_index=kernel.node_index,
                    layer=kernel.layer,
                    aha_segment=kernel.aha_segment,
                    arc_length_param=kernel.arc_length_param,
                )
        if progress_callback:
            progress_callback(i + 1, n_frames - 1)
    return results
