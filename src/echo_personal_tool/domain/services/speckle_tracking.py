"""Core speckle tracking engine: block matching with NCC, pyramidal approach."""

from __future__ import annotations

from collections.abc import Callable

import cv2
import numpy as np
from scipy.ndimage import gaussian_filter

from echo_personal_tool.domain.models.speckle import (
    SpeckleConfig,
    TrackingKernel,
    TrackingResult,
)


def build_gaussian_pyramid(frame: np.ndarray, levels: int) -> list[np.ndarray]:
    """Build Gaussian pyramid with anti-aliasing blur before downsampling.

    Args:
        frame: (H, W) grayscale image (uint8 or float).
        levels: number of pyramid levels including original.

    Returns:
        List of downsampled frames: [original, 1/2, 1/4, ...].
    """
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


def _extract_patch(frame: np.ndarray, cx: float, cy: float, half: int) -> np.ndarray | None:
    """Extract a patch centered at (cx, cy) with given half-size."""
    h, w = frame.shape[:2]
    x0 = int(round(cx)) - half
    y0 = int(round(cy)) - half
    x1 = x0 + 2 * half
    y1 = y0 + 2 * half
    if x0 < 0 or y0 < 0 or x1 > w or y1 > h:
        return None
    return frame[y0:y1, x0:x1]


def refine_subpixel(
    correlation_map: np.ndarray,
    peak: tuple[int, int],
) -> tuple[float, float]:
    """Parabolic interpolation on 3x3 neighborhood around correlation peak.

    Args:
        correlation_map: 2D correlation values.
        peak: (row, col) integer peak position.

    Returns:
        (row_offset, col_offset) sub-pixel displacement.
    """
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
    """Track one kernel from reference frame to target frame.

    Uses pyramidal coarse-to-fine approach with OpenCV matchTemplate.
    Reference kernel is always extracted from the original center position
    (not drifting with search updates) for consistent matching.

    Args:
        reference_pyramid: pre-built Gaussian pyramid of reference frame.
        target_pyramid: pre-built Gaussian pyramid of target frame.
        center: (x, y) kernel center in reference frame (level 0 coords).
        config: tracking configuration.

    Returns:
        (dx, dy, ncc_score) displacement and confidence.
    """
    half = config.kernel_size // 2
    orig_cx, orig_cy = center
    cx, cy = center
    dx_total, dy_total = 0.0, 0.0
    best_ncc = 0.0

    for level in range(config.pyramid_levels - 1, -1, -1):
        scale = 2 ** level
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

        result = cv2.matchTemplate(search_region, k_level.astype(np.float32), cv2.TM_CCOEFF_NORMED)
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
) -> TrackingResult:
    """Track all kernels from one frame to the next.

    Builds Gaussian pyramids once per frame pair, then tracks all kernels.

    Args:
        reference: source frame (H, W).
        target: destination frame (H, W).
        kernels: list of TrackingKernel to track.
        config: tracking configuration.

    Returns:
        TrackingResult with displacements, NCC scores, and valid mask.
    """
    pyramids_ref = build_gaussian_pyramid(reference.astype(np.float32), config.pyramid_levels)
    pyramids_tgt = build_gaussian_pyramid(target.astype(np.float32), config.pyramid_levels)

    n = len(kernels)
    displacements = np.zeros((n, 2), dtype=np.float64)
    ncc_scores = np.zeros(n, dtype=np.float64)
    positions = np.zeros((n, 2), dtype=np.float64)

    for i, kernel_obj in enumerate(kernels):
        dx, dy, ncc = block_match_single(
            pyramids_ref, pyramids_tgt, kernel_obj.center, config
        )
        displacements[i] = [dx, dy]
        ncc_scores[i] = ncc
        positions[i] = [
            kernel_obj.center[0] + dx,
            kernel_obj.center[1] + dy,
        ]

    valid_mask = ncc_scores >= config.ncc_threshold
    if config.outlier_sigma > 0 and valid_mask.sum() > 3:
        median_disp = np.median(displacements[valid_mask], axis=0)
        mad = np.median(np.abs(displacements[valid_mask] - median_disp), axis=0)
        mad[mad < 0.1] = 0.1
        outlier = np.any(np.abs(displacements - median_disp) > config.outlier_sigma * mad, axis=1)
        valid_mask &= ~outlier

    return TrackingResult(
        frame_index=0,
        displacements=displacements,
        ncc_scores=ncc_scores,
        valid_mask=valid_mask,
        kernel_positions=positions,
    )


def track_cine(
    frames: np.ndarray,
    initial_kernels: list[TrackingKernel],
    config: SpeckleConfig,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[TrackingResult]:
    """Track kernels across entire CINE loop.

    Forward tracking from frame 0 to N-1.

    Args:
        frames: (N, H, W) uint8 or float array.
        initial_kernels: kernels at frame 0.
        config: tracking configuration.
        progress_callback: optional (current, total) progress reporter.

    Returns:
        List of TrackingResult for each frame transition (N-1 results).
    """
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
                )

        if progress_callback:
            progress_callback(i + 1, n_frames - 1)

    return results
