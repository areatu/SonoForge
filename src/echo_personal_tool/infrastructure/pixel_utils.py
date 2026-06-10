"""Pixel format helpers for viewer and thumbnail pipelines."""

from __future__ import annotations

import cv2
import numpy as np


def to_bgr_uint8(frame: np.ndarray) -> np.ndarray:
    """Normalize decoded frames to contiguous BGR uint8 (H, W, 3) or grayscale (H, W)."""
    arr = np.asarray(frame)
    if arr.ndim == 2:
        return np.ascontiguousarray(arr, dtype=np.uint8)
    if arr.ndim == 3 and arr.shape[2] == 1:
        return np.ascontiguousarray(arr[:, :, 0], dtype=np.uint8)
    if arr.ndim == 3 and arr.shape[2] == 4:
        bgr = cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)
        return np.ascontiguousarray(bgr, dtype=np.uint8)
    if arr.ndim == 3 and arr.shape[2] >= 3:
        return np.ascontiguousarray(arr[:, :, :3], dtype=np.uint8)
    raise ValueError(f"Unsupported frame shape: {arr.shape}")


def to_grayscale_uint8(frame: np.ndarray) -> np.ndarray:
    """Convert a frame to grayscale uint8 (H, W)."""
    bgr = to_bgr_uint8(frame)
    if bgr.ndim == 2:
        return bgr
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    return np.ascontiguousarray(gray, dtype=np.uint8)


def bgr_to_rgb(frame: np.ndarray) -> np.ndarray:
    """Convert BGR (H, W, 3) to RGB for PyQtGraph display."""
    if frame.ndim == 2:
        return frame
    return np.ascontiguousarray(frame[:, :, ::-1], dtype=np.uint8)


def is_color_frame(frame: np.ndarray) -> bool:
    return frame.ndim == 3 and frame.shape[2] >= 3
