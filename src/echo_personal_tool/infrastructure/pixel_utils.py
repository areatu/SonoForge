"""Pixel format helpers for viewer and thumbnail pipelines."""

from __future__ import annotations

from typing import Literal

import cv2
import numpy as np

ChannelOrder = Literal["rgb", "bgr"]


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


def to_display_rgb(frame: np.ndarray, *, channel_order: ChannelOrder = "bgr") -> np.ndarray:
    """Normalize a color frame to contiguous RGB uint8 for Qt display."""
    if frame.ndim == 2:
        return frame
    if frame.ndim != 3 or frame.shape[2] < 3:
        raise ValueError(f"Unsupported color frame shape: {frame.shape}")
    if channel_order == "rgb":
        return np.ascontiguousarray(frame[..., :3], dtype=np.uint8)
    return bgr_to_rgb(frame)


def apply_window_level_rgb(rgb: np.ndarray, low: float, high: float) -> np.ndarray:
    """Apply window/level via luminance scaling while preserving chroma ratios."""
    source = np.asarray(rgb, dtype=np.float64)
    if source.ndim != 3 or source.shape[2] < 3:
        raise ValueError(f"Expected RGB frame, got shape {source.shape}")
    luminance = np.mean(source[..., :3], axis=2)
    span = max(high - low, 1.0)
    target = (np.clip(luminance, low, high) - low) / span * 255.0
    gain = np.divide(
        target,
        np.maximum(luminance, 1.0),
        out=np.ones_like(luminance),
        where=luminance > 1.0,
    )
    return np.clip(source * gain[..., np.newaxis], 0.0, 255.0).astype(np.uint8)


def is_effective_grayscale(frame: np.ndarray, *, tolerance: int = 12) -> bool:
    """True when RGB channels carry the same luminance (typical US B-mode DICOM packing)."""
    if frame.ndim == 2:
        return True
    if frame.ndim != 3 or frame.shape[2] < 3:
        return False

    step_y = max(1, frame.shape[0] // 128)
    step_x = max(1, frame.shape[1] // 128)
    sample = frame[::step_y, ::step_x, :3]
    red = sample[..., 0].astype(np.int16)
    green = sample[..., 1].astype(np.int16)
    blue = sample[..., 2].astype(np.int16)
    channel_diff = np.maximum(np.abs(red - green), np.abs(green - blue))
    return float(np.percentile(channel_diff, 99)) <= float(tolerance)


def to_grayscale_array(frame: np.ndarray) -> np.ndarray:
    """Luminance as float64 for window/level (preserves uint16 dynamic range)."""
    array = np.asarray(frame, dtype=np.float64)
    if array.ndim == 2:
        return array
    if array.ndim == 3 and array.shape[2] >= 3:
        return np.mean(array[..., :3], axis=2)
    if array.ndim == 3:
        return array[..., 0]
    raise ValueError(f"Unsupported frame shape: {frame.shape}")


def is_color_frame(frame: np.ndarray) -> bool:
    return frame.ndim == 3 and frame.shape[2] >= 3 and not is_effective_grayscale(frame)


def percentile_range(frame: np.ndarray, low_pct: float, high_pct: float) -> tuple[float, float]:
    """Return a clipped percentile range for finite values in *frame*."""
    flat = np.asarray(frame, dtype=np.float64).ravel()
    flat = flat[np.isfinite(flat)]
    if flat.size == 0:
        return 0.0, 1.0

    low_pct = float(np.clip(low_pct, 0.0, 100.0))
    high_pct = float(np.clip(high_pct, 0.0, 100.0))
    low = float(np.percentile(flat, low_pct))
    high = float(np.percentile(flat, high_pct))
    if not np.isfinite(low) or not np.isfinite(high):
        return 0.0, 1.0
    if high < low:
        low, high = high, low
    return low, high


def dr_percentiles_from_slider(slider_value: int) -> tuple[float, float]:
    """Map single DR slider (0–100, default 50) to percentile low/high pair."""
    value = int(np.clip(slider_value, 0, 100))
    if value <= 50:
        low = (50 - value) / 50.0 * 45.0
        return low, 100.0
    high = 100.0 - (value - 50) / 50.0 * 45.0
    return 0.0, high


def compute_display_levels(
    frame: np.ndarray,
    *,
    dr_low_pct: float,
    dr_high_pct: float,
    window_scale: float,
    level_offset: float,
) -> tuple[float, float]:
    """Compute display levels from dynamic-range percentiles and W/L controls."""
    low, high = percentile_range(frame, dr_low_pct, dr_high_pct)
    span = max(high - low, 1.0)
    window = span * max(window_scale, 0.01)
    center = low + span * (0.5 + 0.5 * level_offset)
    return center - window / 2.0, center + window / 2.0
