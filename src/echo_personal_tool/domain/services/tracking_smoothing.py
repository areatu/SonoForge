"""Spatial and temporal spline smoothing for STE trajectories."""

from __future__ import annotations

import numpy as np
from scipy.interpolate import UnivariateSpline
from scipy.signal import savgol_filter

from echo_personal_tool.domain.models.speckle import (
    SpeckleConfig,
    TrackingKernel,
    TrackingResult,
)


def _layer_groups(kernels: list[TrackingKernel]) -> dict[str, list[int]]:
    groups: dict[str, list[int]] = {}
    for i, kernel in enumerate(kernels):
        groups.setdefault(kernel.layer, []).append(i)
    return groups


def _fit_cubic_smoothing_spline(
    x: np.ndarray,
    y: np.ndarray,
    smoothing: float,
) -> UnivariateSpline:
    """Cubic smoothing spline; CubicSpline has no smoothing parameter ``s``."""
    return UnivariateSpline(x, y, s=max(float(smoothing), 0.0), k=3)


def interpolate_invalid_kernels(
    positions: np.ndarray,
    ncc_scores: np.ndarray,
    kernels: list[TrackingKernel],
    ncc_threshold: float = 0.3,
) -> np.ndarray:
    """Replace invalid kernel positions with interpolated values from valid neighbors.

    For each frame, if a kernel is invalid (NCC < threshold), interpolate its
    position from the nearest valid kernels along the contour.

    Args:
        positions: (n_frames, n_kernels, 2) kernel positions.
        ncc_scores: (n_frames, n_kernels) NCC scores.
        kernels: list of TrackingKernel with layer info.
        ncc_threshold: minimum NCC to consider a kernel valid.

    Returns:
        (n_frames, n_kernels, 2) interpolated positions.
    """
    out = positions.copy()
    n_frames, n_kernels, _ = out.shape

    groups = _layer_groups(kernels)
    for _layer, indices in groups.items():
        idx = sorted(indices, key=lambda i: kernels[i].node_index)
        idx_arr = np.array(idx, dtype=np.intp)
        n_layer = len(idx)
        if n_layer < 3:
            continue

        for t in range(n_frames):
            layer_ncc = ncc_scores[t, idx_arr]
            valid = layer_ncc >= ncc_threshold

            if valid.all():
                continue

            valid_indices = np.where(valid)[0]

            if len(valid_indices) < 2:
                continue

            for j in range(n_layer):
                if valid[j]:
                    continue

                left_valid = valid_indices[valid_indices < j]
                right_valid = valid_indices[valid_indices > j]

                if len(left_valid) > 0 and len(right_valid) > 0:
                    li = left_valid[-1]
                    ri = right_valid[0]
                    dist_total = ri - li
                    if dist_total > 0:
                        alpha = (j - li) / dist_total
                        out[t, idx_arr[j], :] = out[t, idx_arr[li], :] * (1.0 - alpha) + out[t, idx_arr[ri], :] * alpha
                elif len(left_valid) > 0:
                    li = left_valid[-1]
                    out[t, idx_arr[j], :] = out[t, idx_arr[li], :]
                elif len(right_valid) > 0:
                    ri = right_valid[0]
                    out[t, idx_arr[j], :] = out[t, idx_arr[ri], :]

    return out


def smooth_trajectories(
    positions: np.ndarray,
    ncc_scores: np.ndarray,
    kernels: list[TrackingKernel],
    config: SpeckleConfig,
) -> np.ndarray:
    """Apply quality-weighted spatial then temporal smoothing.

    Uses per-kernel NCC weights for spline fitting: high-NCC kernels
    have more influence on the smoothed curve shape.
    """
    out = positions.copy()
    n_frames, n_kernels, _ = out.shape
    if config.spatial_smoothing <= 0 and config.temporal_smoothing <= 0:
        return out

    groups = _layer_groups(kernels)
    for _layer, indices in groups.items():
        idx = sorted(indices, key=lambda i: kernels[i].node_index)
        if len(idx) < 4:
            continue
        if config.spatial_smoothing > 0:
            for t in range(n_frames):
                pts = out[t, idx, :]
                weights = np.clip(ncc_scores[t, idx], 0.01, 1.0)
                s = config.spatial_smoothing * len(idx)
                if config.quality_weighted_smoothing:
                    s *= float(np.mean(1.0 - weights) + 0.1)
                t_param = np.arange(len(idx), dtype=np.float64)
                k = min(3, len(idx) - 1)  # spline degree can't exceed n_points - 1
                cs_x = UnivariateSpline(t_param, pts[:, 0], w=weights, s=s, k=k)
                cs_y = UnivariateSpline(t_param, pts[:, 1], w=weights, s=s, k=k)
                out[t, idx, 0] = cs_x(t_param)
                out[t, idx, 1] = cs_y(t_param)

    if config.temporal_smoothing > 0 and n_frames >= 4:
        # Savitzky-Golay: a local polynomial filter that follows the systolic
        # peak without the overshoot/flattening of a heavy smoothing spline
        # (the old `s = temporal_smoothing * n_frames` essentially straightened
        # the whole trajectory when many kernels had been interpolated).
        window = int(round(2.0 * config.temporal_smoothing + 3.0))
        window = max(3, window)
        if window % 2 == 0:
            window += 1
        window = min(window, n_frames - (1 - n_frames % 2))
        if window < 3:
            window = 3
        polyorder = min(2, window - 1)
        times = np.arange(n_frames, dtype=np.float64)
        for i in range(n_kernels):
            xs = out[:, i, 0].copy()
            ys = out[:, i, 1].copy()
            if config.quality_weighted_smoothing:
                # Re-interpolate low-confidence frames in time before filtering
                # so high-NCC frames dominate the smoothed trajectory.
                weights = np.clip(ncc_scores[:, i], 0.0, 1.0)
                strong = weights >= 0.5
                if strong.sum() >= 2:
                    xs = np.interp(times, times[strong], xs[strong])
                    ys = np.interp(times, times[strong], ys[strong])
            out[:, i, 0] = savgol_filter(xs, window, polyorder, mode="interp")
            out[:, i, 1] = savgol_filter(ys, window, polyorder, mode="interp")
    return out


def apply_motion_model(
    positions: np.ndarray,
    ncc_scores: np.ndarray,
    kernels: list[TrackingKernel],
    ed_index: int,
    ncc_threshold: float = 0.3,
    strength: float = 0.3,
) -> np.ndarray:
    """Apply physiological motion model constraints during systole.

    During systole (t > ed_index) both the endocardium and the epicardium move
    inward (toward the LV cavity centre); the endocardium moves more, which
    manifests as wall thickening. The constraint only corrects kernels that
    moved in the opposite (outward) direction, gently pulling them back without
    overriding the actual tracking results.

    Args:
        positions: (n_frames, n_kernels, 2) smoothed positions.
        ncc_scores: (n_frames, n_kernels) NCC scores.
        kernels: list of TrackingKernel with layer info.
        ed_index: ED frame index.
        ncc_threshold: minimum NCC for valid kernels.
        strength: constraint strength (0.0 = no effect, 1.0 = full constraint).

    Returns:
        (n_frames, n_kernels, 2) constrained positions.
    """
    out = positions.copy()
    n_frames, n_kernels, _ = out.shape

    ed_positions = positions[ed_index]
    lv_center = np.mean(ed_positions, axis=0)

    for t in range(ed_index + 1, n_frames):
        alpha = (t - ed_index) / max(n_frames - 1 - ed_index, 1)

        for i in range(n_kernels):
            if ncc_scores[t, i] < ncc_threshold:
                continue

            pos = out[t, i]
            ed_pos = ed_positions[i]
            to_center = lv_center - ed_pos
            to_center_norm = np.linalg.norm(to_center)
            if to_center_norm < 1e-6:
                continue
            to_center = to_center / to_center_norm

            displacement = pos - ed_pos
            disp_along_center = np.dot(displacement, to_center)

            kernel = kernels[i]
            if kernel.layer in ("endo", "epi"):
                expected_sign = 1.0
            else:
                continue

            if disp_along_center * expected_sign < 0:
                correction = -disp_along_center * to_center * strength * alpha
                out[t, i] = pos + correction

    return out


def extract_trajectories(
    tracking_results: list[TrackingResult],
    initial_kernels: list[TrackingKernel],
    ed_index: int = 0,
) -> tuple[np.ndarray, np.ndarray]:
    """Build (n_frames, n_kernels, 2) positions and NCC matrix from results."""
    n_kernels = len(initial_kernels)
    n_frames = len(tracking_results) + 1
    positions = np.zeros((n_frames, n_kernels, 2), dtype=np.float64)
    ncc_matrix = np.zeros((n_frames, n_kernels), dtype=np.float64)

    positions[ed_index] = np.array(
        [kernel.center for kernel in initial_kernels],
        dtype=np.float64,
    )
    ncc_matrix[ed_index] = 1.0

    for result in tracking_results:
        frame = int(result.frame_index)
        positions[frame] = result.kernel_positions
        ncc_matrix[frame] = result.ncc_scores

    last_valid = positions[ed_index].copy()
    for t in range(n_frames):
        if t == ed_index:
            continue
        if np.allclose(positions[t], 0.0):
            positions[t] = last_valid
        else:
            last_valid = positions[t]

    return positions, ncc_matrix


def re_smooth_trajectories(
    raw_positions: np.ndarray,
    ncc_scores: np.ndarray,
    kernels: list[TrackingKernel],
    smoothness: float,
    *,
    quality_weighted: bool = True,
) -> np.ndarray:
    """Re-smooth pre-interpolated positions with a new smoothness factor.

    Args:
        raw_positions: (n_frames, n_kernels, 2) positions after interpolation.
        ncc_scores: (n_frames, n_kernels) NCC quality scores.
        kernels: tracking kernels with layer info.
        smoothness: 0.0 = no smoothing, 1.0 = standard, 2.0 = heavy.
        quality_weighted: use NCC-weighted spline fitting.

    Returns:
        (n_frames, n_kernels, 2) re-smoothed positions.
    """
    cfg = SpeckleConfig(
        spatial_smoothing=smoothness,
        temporal_smoothing=smoothness,
        quality_weighted_smoothing=quality_weighted,
    )
    return smooth_trajectories(raw_positions, ncc_scores, kernels, cfg)
