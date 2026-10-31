"""Display, window/level and colour-detection helpers for image pipelines.

Pure array algorithms (QH-4b / S2-03 #307): these functions only normalize
and transform NumPy arrays, perform no I/O and carry no Qt state, so they live
in the algorithmic ``echo_personal_tool.imaging`` package instead of
``infrastructure``.  The legacy ``infrastructure.pixel_utils`` module
re-exports them unchanged.
"""

from __future__ import annotations

import cv2
import numpy as np

from echo_personal_tool.imaging.pixels import (
    ChannelOrder,
    bgr_to_rgb,
    to_bgr_uint8,
    to_grayscale_uint8,
)

__all__ = [
    "COLOR_CHANNEL_SPREAD",
    "COLOR_PIXEL_SHARE",
    "ChannelOrder",
    "apply_wl_lut",
    "apply_window_level_rgb",
    "bgr_to_rgb",
    "color_pixel_share",
    "compute_display_levels",
    "decolor_frame",
    "despeckle_frame",
    "dr_percentiles_from_slider",
    "grayscale_source_array",
    "is_color_frame",
    "is_effective_grayscale",
    "percentile_range",
    "reference_wl_display_uint8",
    "to_bgr_uint8",
    "to_display_rgb",
    "to_grayscale_array",
    "to_grayscale_uint8",
]


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
    """Apply window/level via luminance scaling. Uses float32 to halve memory."""
    source = np.asarray(rgb, dtype=np.float32)
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
    result = source.copy()  # Allocation 1: float32 owned copy
    result[..., :3] *= gain[..., np.newaxis]  # In-place multiply (0 allocations)
    np.clip(result, 0.0, 255.0, out=result)  # In-place clip (0 allocations)
    return result.astype(np.uint8)  # Allocation 2: uint8 output


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
    """Luminance as float32 for WL/edge computation. Returns WRITABLE array."""
    arr = np.asarray(frame)
    if arr.ndim == 2:
        if arr.dtype == np.float32:
            return arr.copy() if not arr.flags.writeable else arr
        return arr.astype(np.float32)

    if arr.ndim == 3 and arr.shape[2] >= 3:
        arr = np.ascontiguousarray(arr)  # Safety for cv2
        gray_u8 = cv2.cvtColor(arr[..., :3], cv2.COLOR_RGB2GRAY)
        return gray_u8.astype(np.float32)

    if arr.ndim == 3:
        return arr[..., 0].astype(np.float32)
    raise ValueError(f"Unsupported frame shape: {frame.shape}")


#: Channel spread (max − min over RGB) above which a pixel is «coloured».
#: JPEG chroma noise and the slighest tint of a packed B-mode frame stay well
#: below it, while a colour Doppler jet — even a dim one — is far above.
COLOR_CHANNEL_SPREAD = 32
#: Share of coloured pixels that makes the whole frame a colour frame.  A
#: spectral Doppler screen carries a small 2D colour reference in the corner
#: (typically 0.3–3 % of the frame): the old «99th percentile of the channel
#: spread» test threw that away and showed ЦДК in grayscale (UI acceptance
#: 2026-10-23, item 6).  One pixel in a thousand is enough evidence of colour.
COLOR_PIXEL_SHARE = 0.001


def color_pixel_share(frame: np.ndarray, *, tolerance: int = COLOR_CHANNEL_SPREAD) -> float:
    """Share of sampled pixels whose RGB channels differ by more than *tolerance*.

    Sampling keeps the check cheap enough to run per frame (``tests/bench``);
    the sample is the same ~128 × 128 grid :func:`is_effective_grayscale` uses,
    so a tiny colour box is still represented (at 800 × 600 one sample is
    ~48 pixels, i.e. the 0.1 % floor is a handful of samples).
    """
    if frame.ndim != 3 or frame.shape[2] < 3:
        return 0.0
    step_y = max(1, frame.shape[0] // 128)
    step_x = max(1, frame.shape[1] // 128)
    sample = np.asarray(frame[::step_y, ::step_x, :3], dtype=np.int16)
    if sample.size == 0:
        return 0.0
    red, green, blue = sample[..., 0], sample[..., 1], sample[..., 2]
    spread = np.maximum(np.maximum(red, green), blue) - np.minimum(np.minimum(red, green), blue)
    return float(np.count_nonzero(spread > tolerance)) / float(spread.size)


def is_color_frame(frame: np.ndarray) -> bool:
    """Whether the frame carries colour (ЦДК, colour M-mode, ECG overlay).

    A frame is colour as soon as :data:`COLOR_PIXEL_SHARE` of it is coloured:
    the display keeps the source RGB (the grayscale copy is what measurements
    and calibration run on), so a colour Doppler clip is never shown in gray.
    """
    return color_pixel_share(frame) >= COLOR_PIXEL_SHARE


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


def grayscale_source_array(frame: np.ndarray) -> np.ndarray:
    """Return 2-D source values for LUT window/level (preserves dtype).
    MAY BE READ-ONLY — caller must not mutate."""
    source = np.asarray(frame)
    if source.ndim == 3:
        if source.shape[2] >= 3:
            if source.dtype == np.uint16:
                return np.mean(source[..., :3], axis=2).astype(np.uint16)
            return np.mean(source[..., :3], axis=2).astype(source.dtype)
        return source[..., 0]
    return source


def apply_wl_lut(
    frame: np.ndarray,
    *,
    dr_low_pct: float,
    dr_high_pct: float,
    window_scale: float,
    level_offset: float,
) -> np.ndarray:
    """Apply window/level via precomputed LUT (OpenCV vectorized).

    Matches ``compute_display_levels`` + linear map to uint8 display.
    Returns grayscale uint8 (H, W).
    """
    gray_f = to_grayscale_array(frame)
    low, high = compute_display_levels(
        gray_f,
        dr_low_pct=dr_low_pct,
        dr_high_pct=dr_high_pct,
        window_scale=window_scale,
        level_offset=level_offset,
    )
    span = max(high - low, 1.0)
    src = grayscale_source_array(frame)
    if src.dtype == np.uint16:
        lut = np.clip(
            (np.arange(65536, dtype=np.float64) - low) / span * 255.0,
            0.0,
            255.0,
        ).astype(np.uint8)
        return lut[src]
    src_u8 = src if src.dtype == np.uint8 else np.clip(src, 0, 255).astype(np.uint8)
    lut = np.clip(
        (np.arange(256, dtype=np.float64) - low) / span * 255.0,
        0.0,
        255.0,
    ).astype(np.uint8)
    return cv2.LUT(src_u8, lut)


def reference_wl_display_uint8(
    frame: np.ndarray,
    *,
    dr_low_pct: float,
    dr_high_pct: float,
    window_scale: float,
    level_offset: float,
) -> np.ndarray:
    """CPU reference for ``apply_wl_lut`` (percentile + linear map)."""
    gray_f = to_grayscale_array(frame)
    low, high = compute_display_levels(
        gray_f,
        dr_low_pct=dr_low_pct,
        dr_high_pct=dr_high_pct,
        window_scale=window_scale,
        level_offset=level_offset,
    )
    span = max(high - low, 1.0)
    out = np.clip((gray_f - low) / span * 255.0, 0.0, 255.0)
    return out.astype(np.uint8)


def despeckle_frame(frame: np.ndarray) -> np.ndarray:
    """Apply bilateral filter to reduce ultrasound speckle noise."""
    if frame.ndim != 2 or frame.dtype != np.uint8:
        return frame
    return cv2.bilateralFilter(frame, d=5, sigmaColor=50, sigmaSpace=50)


def decolor_frame(frame: np.ndarray) -> np.ndarray:
    """Remove color overlays (Doppler, ECG, hard-overlays) from a frame.

    Strategy: detect high-saturation pixels (colored overlays) and set them
    to black, so colored overlays disappear entirely. Low-saturation pixels
    (B-mode tissue) are converted to grayscale normally.
    """
    if frame.ndim != 3 or frame.shape[2] < 3 or frame.dtype != np.uint8:
        return frame
    # Convert to grayscale for B-mode content
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    # Detect colored overlay pixels via HSV saturation
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1]
    overlay_mask = saturation > 40
    # Set overlay pixels to black
    gray[overlay_mask] = 0
    return gray
