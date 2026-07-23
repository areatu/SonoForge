"""Optical flow based contour refinement for LV/LA boundaries.

Shifts contour points toward wall motion direction using local optical flow
between consecutive frames. Designed to run in a background thread.
"""

from __future__ import annotations

import math

import cv2
import numpy as np


def refine_contour_with_optical_flow(
    frames: list[np.ndarray],
    contour_points: list[tuple[float, float]],
    *,
    current_frame_idx: int,
    fps: float,
    roi_half_size: int = 5,
    shift_fraction: float = 0.4,
    max_shift_px: float = 3.0,
    min_flow_magnitude: float = 0.1,
) -> list[tuple[float, float]]:
    """Refine contour points using local optical flow between consecutive frames.

    For each contour point, computes the average optical flow vector in a small
    ROI around the point across a few neighboring frames. Shifts the point in
    the direction of dominant motion (typically toward the wall boundary).

    Args:
        frames: List of grayscale uint8 frames (full cine).
        contour_points: Current contour point positions [(x, y), ...].
        current_frame_idx: Index of the frame the contour belongs to.
        fps: Frame rate of the cine.
        roi_half_size: Half-size of the ROI around each point (default 5 → 11×11).
        shift_fraction: Fraction of flow vector to apply (0.0–1.0).
        max_shift_px: Maximum allowed shift in pixels per point.
        min_flow_magnitude: Minimum flow magnitude to trigger shift (ignore noise).

    Returns:
        Refined contour points with the same length as input.
    """
    if len(frames) < 3 or len(contour_points) < 3:
        return list(contour_points)

    n_frames = len(frames)
    # Use up to 3 neighboring frames (before and after current)
    neighbor_range = min(3, fps / 10)  # ~0.3 sec window
    start_idx = max(0, int(current_frame_idx - neighbor_range))
    end_idx = min(n_frames - 1, int(current_frame_idx + neighbor_range))

    if end_idx - start_idx < 2:
        return list(contour_points)

    h, w = frames[0].shape[:2]
    refined: list[tuple[float, float]] = []

    for px, py in contour_points:
        ix, iy = int(round(px)), int(round(py))
        # Clamp to image bounds with ROI margin
        if ix < roi_half_size or ix >= w - roi_half_size or iy < roi_half_size or iy >= h - roi_half_size:
            refined.append((px, py))
            continue

        # Accumulate flow vectors from neighboring frame pairs
        flow_sum_x = 0.0
        flow_sum_y = 0.0
        flow_count = 0

        for fi in range(start_idx, end_idx):
            gray_curr = frames[fi]
            gray_next = frames[fi + 1]

            # Sparse optical flow at the point (Lucas-Kanade — much faster than dense)
            p0 = np.array([[ix, iy]], dtype=np.float32).reshape(-1, 1, 2)
            p1, status, _ = cv2.calcOpticalFlowPyrLK(
                gray_curr, gray_next, p0, None,
                winSize=(roi_half_size * 2 + 1, roi_half_size * 2 + 1),
                maxLevel=2,
            )
            if status is not None and status[0][0] == 1:
                dx = float(p1[0][0][0] - p0[0][0][0])
                dy = float(p1[0][0][1] - p0[0][0][1])
                mag = math.hypot(dx, dy)
                if mag >= min_flow_magnitude:
                    flow_sum_x += dx
                    flow_sum_y += dy
                    flow_count += 1

        if flow_count == 0:
            refined.append((px, py))
            continue

        # Average flow vector
        avg_dx = flow_sum_x / flow_count
        avg_dy = flow_sum_y / flow_count
        avg_mag = math.hypot(avg_dx, avg_dy)

        if avg_mag < min_flow_magnitude:
            refined.append((px, py))
            continue

        # Clamp shift magnitude
        scale = min(shift_fraction, max_shift_px / avg_mag) if avg_mag > 0 else 0.0
        shift_x = avg_dx * scale
        shift_y = avg_dy * scale

        new_x = px + shift_x
        new_y = py + shift_y
        refined.append((new_x, new_y))

    return refined


def compute_flow_field_snapshot(
    frames: list[np.ndarray],
    frame_idx: int,
    step: int = 4,
) -> tuple[np.ndarray, np.ndarray] | None:
    """Compute dense optical flow between frame[frame_idx] and frame[frame_idx+1].

    Returns (vx, vy) arrays at `step` pixel resolution, or None if unavailable.
    Used for visualization/debugging.
    """
    if frame_idx < 0 or frame_idx + 1 >= len(frames):
        return None
    gray0 = frames[frame_idx]
    gray1 = frames[frame_idx + 1]
    flow = cv2.calcOpticalFlowFarneback(
        gray0, gray1, None,
        pyr_scale=0.5, levels=3, winsize=15,
        iterations=3, poly_n=5, poly_sigma=1.2, flags=0,
    )
    # Subsample for efficiency
    vx = flow[::step, ::step, 0]
    vy = flow[::step, ::step, 1]
    return vx, vy
