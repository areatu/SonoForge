"""Temporal Static Noise Filter for ultrasound cine loops.

Suppresses stationary bright pixels (sensor noise, fixed-pattern artifacts)
by estimating per-pixel temporal statistics and applying a confidence-weighted
attenuation.  The filter operates in display-only mode — original pixel data
is never mutated.

Model:  I_t(x,y) = S_t(x,y) + N_s(x,y) + n_t(x,y)
Goal:   estimate N_s and suppress it via  I'_t = I_t - alpha * C * M
where M is temporal median, C is confidence mask, alpha is strength.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

import numpy as np
from scipy import ndimage

logger = logging.getLogger(__name__)


class FilterMode(Enum):
    """How the filter attenuates detected static noise."""

    SUBTRACT = "subtract"  # I' = I - alpha * C * M  (shift toward black)
    CLIP = "clip"  # I' = min(I, dynamic_ceiling)  (clamp peaks)


@dataclass
class StaticNoiseFilterParams:
    """User-tuneable parameters for the static noise filter."""

    strength: int = 0  # 0-100, 0 = off
    sensitivity: int = 3  # MAD threshold (1-10, lower = more aggressive)
    min_brightness: int = 60  # minimum median brightness to consider as noise
    mode: FilterMode = FilterMode.SUBTRACT


@dataclass
class StaticNoiseCalibration:
    """Pre-computed temporal statistics for a cine loop.

    Built once when a new DICOM instance is loaded, then reused for every
    frame display until the instance changes.
    """

    median_frame: np.ndarray | None = None  # (H, W) float32, temporal median
    mad_frame: np.ndarray | None = None  # (H, W) float32, temporal MAD
    cone_mask: np.ndarray | None = None  # (H, W) bool, inside US cone
    isolation_map: np.ndarray | None = None  # (H, W) float32, spatial isolation
    cluster_size_map: np.ndarray | None = None  # (H, W) int32, connected component size
    confidence_map: np.ndarray | None = None  # (H, W) float32 [0..1]
    frame_shape: tuple[int, int] | None = None  # (H, W)
    is_valid: bool = False

    def invalidate(self) -> None:
        """Clear all cached data."""
        self.median_frame = None
        self.mad_frame = None
        self.cone_mask = None
        self.isolation_map = None
        self.cluster_size_map = None
        self.confidence_map = None
        self.frame_shape = None
        self.is_valid = False


def _detect_cone_mask(median_frame: np.ndarray, percentile: float = 15.0) -> np.ndarray:
    """Detect the ultrasound cone / active area from the temporal median.

    Pixels brighter than a low percentile of non-zero values are considered
    inside the cone.  Returns a boolean mask (H, W).
    """
    mf = median_frame.astype(np.float32)
    nonzero = mf[mf > 0]
    if nonzero.size == 0:
        return np.zeros_like(mf, dtype=bool)
    threshold = float(np.percentile(nonzero, percentile))
    return mf > threshold


def _compute_isolation(median_frame: np.ndarray, kernel_size: int = 11) -> np.ndarray:
    """Spatial isolation: |M - local_median(M)|.

    High isolation means the pixel is much brighter than its neighbourhood,
    typical for hot-pixel defects.
    """
    mf = median_frame.astype(np.float32)
    local_med = ndimage.median_filter(mf, size=kernel_size)
    return np.abs(mf - local_med)


def _compute_cluster_size_map(
    bright_static_mask: np.ndarray, min_cluster: int = 1
) -> np.ndarray:
    """Label connected components and return per-pixel cluster size.

    Small clusters (hot pixels) get high weight; large clusters (anatomy,
    overlays) get low weight.
    """
    labeled, num = ndimage.label(bright_static_mask)
    if num == 0:
        return np.zeros_like(bright_static_mask, dtype=np.int32)
    sizes = ndimage.sum(np.ones_like(bright_static_mask, dtype=np.float32), labeled, range(1, num + 1))
    sizes = np.array(sizes, dtype=np.int32)
    size_map = np.zeros_like(bright_static_mask, dtype=np.int32)
    for i in range(1, num + 1):
        size_map[labeled == i] = sizes[i - 1]
    return size_map


def _build_confidence_map(
    median_frame: np.ndarray,
    mad_frame: np.ndarray,
    cone_mask: np.ndarray,
    isolation_map: np.ndarray,
    cluster_size_map: np.ndarray,
    *,
    sensitivity: int = 3,
    min_brightness: int = 60,
) -> np.ndarray:
    """Build a per-pixel confidence map C(x,y) in [0..1].

    High confidence = pixel is likely stationary noise, safe to suppress.
    """
    h, w = median_frame.shape
    C = np.zeros((h, w), dtype=np.float32)

    # --- Factor 1: High brightness ---
    # Normalize median brightness to [0..1] above min_brightness
    bright_norm = np.clip((median_frame.astype(np.float32) - min_brightness) / (255.0 - min_brightness), 0.0, 1.0)

    # --- Factor 2: Low temporal variation ---
    # MAD below sensitivity threshold → likely static
    # Use inverse: lower MAD → higher weight
    mad_thresh = float(sensitivity) * 2.0  # scale slider to pixel units
    low_var = np.clip(1.0 - mad_frame.astype(np.float32) / max(mad_thresh, 1.0), 0.0, 1.0)

    # --- Factor 3: Spatial isolation ---
    # Normalize isolation to [0..1]; cap at 50 for stability
    iso_norm = np.clip(isolation_map.astype(np.float32) / 50.0, 0.0, 1.0)

    # --- Factor 4: Small cluster size ---
    # Small clusters (< 20 px) → high weight; large clusters → low weight
    cluster_norm = np.clip(1.0 - cluster_size_map.astype(np.float32) / 20.0, 0.0, 1.0)

    # --- Factor 5: Inside cone ---
    cone_f = cone_mask.astype(np.float32)

    # Weighted combination
    C = 0.30 * bright_norm + 0.30 * low_var + 0.20 * iso_norm + 0.10 * cluster_norm + 0.10 * cone_f
    C = np.clip(C, 0.0, 1.0)

    # Zero out outside cone entirely
    C[~cone_mask] = 0.0

    return C


def calibrate_static_noise(
    frames: np.ndarray, sensitivity: int = 3, min_brightness: int = 60
) -> StaticNoiseCalibration:
    """Build temporal statistics from a full cine stack.

    Parameters
    ----------
    frames : np.ndarray
        Shape (T, H, W) or (T, H, W, C).  Grayscale preferred; if colour,
        converted to grayscale first.
    sensitivity : int
        MAD threshold (1-10).
    min_brightness : int
        Minimum median brightness to consider as noise.

    Returns
    -------
    StaticNoiseCalibration
        Pre-computed maps ready for per-frame filtering.
    """
    cal = StaticNoiseCalibration()

    if frames.ndim == 4:
        # Colour → grayscale
        frames = np.mean(frames.astype(np.float32), axis=3)

    if frames.ndim != 3 or frames.shape[0] < 2:
        logger.warning("StaticNoiseFilter: need at least 2 frames, got %s", frames.shape)
        return cal

    frames = frames.astype(np.float32)
    t, h, w = frames.shape
    cal.frame_shape = (h, w)

    logger.info("StaticNoiseFilter: calibrating on %d frames (%dx%d)", t, h, w)

    # Temporal median and MAD
    cal.median_frame = np.median(frames, axis=0)
    abs_dev = np.abs(frames - cal.median_frame[np.newaxis, :, :])
    cal.mad_frame = np.median(abs_dev, axis=0) * 1.4826  # robust σ estimate

    # Cone mask
    cal.cone_mask = _detect_cone_mask(cal.median_frame)

    # Spatial isolation
    cal.isolation_map = _compute_isolation(cal.median_frame)

    # Candidate static bright pixels (for cluster analysis)
    candidate_mask = (
        (cal.mad_frame < float(sensitivity) * 2.0)
        & (cal.median_frame > float(min_brightness))
        & cal.cone_mask
    )

    # Cluster size map
    cal.cluster_size_map = _compute_cluster_size_map(candidate_mask)

    # Confidence map
    cal.confidence_map = _build_confidence_map(
        cal.median_frame,
        cal.mad_frame,
        cal.cone_mask,
        cal.isolation_map,
        cal.cluster_size_map,
        sensitivity=sensitivity,
        min_brightness=min_brightness,
    )

    n_candidates = int(np.sum(candidate_mask))
    n_cone = int(np.sum(cal.cone_mask))
    pct = 100.0 * n_candidates / max(n_cone, 1)
    logger.info(
        "StaticNoiseFilter: cone=%d px, candidates=%d px (%.2f%%), max confidence=%.2f",
        n_cone,
        n_candidates,
        pct,
        float(cal.confidence_map.max()) if cal.confidence_map is not None else 0.0,
    )

    cal.is_valid = True
    return cal


def apply_static_filter(
    frame: np.ndarray,
    cal: StaticNoiseCalibration,
    params: StaticNoiseFilterParams,
) -> np.ndarray:
    """Apply static noise suppression to a single frame (display-only).

    Parameters
    ----------
    frame : np.ndarray
        Grayscale (H, W) uint8 or float32.
    cal : StaticNoiseCalibration
        Pre-computed calibration from :func:`calibrate_static_noise`.
    params : StaticNoiseFilterParams
        Current slider values.

    Returns
    -------
    np.ndarray
        Filtered frame, same dtype and shape as input.
    """
    if params.strength <= 0 or not cal.is_valid:
        return frame

    if cal.confidence_map is None or cal.median_frame is None:
        return frame

    alpha = params.strength / 100.0  # map 0-100 to 0.0-1.0
    C = cal.confidence_map
    M = cal.median_frame

    # Ensure frame is float for arithmetic
    src_dtype = frame.dtype
    f = frame.astype(np.float32)

    if params.mode == FilterMode.SUBTRACT:
        # I' = I - alpha * C * M
        f = f - alpha * C * M
    elif params.mode == FilterMode.CLIP:
        # Compute a dynamic ceiling from the non-static signal
        # For each pixel, ceiling = frame value but static peaks are clamped
        # down toward the temporal median
        ceiling = f - alpha * C * (f - M)
        f = np.minimum(f, ceiling)

    # Clip to valid range
    if src_dtype == np.uint8:
        f = np.clip(f, 0.0, 255.0)
    elif src_dtype == np.uint16:
        f = np.clip(f, 0.0, 65535.0)
    else:
        f = np.clip(f, 0.0, 255.0)

    return f.astype(src_dtype)


def render_noise_overlay(
    frame_shape: tuple[int, int],
    cal: StaticNoiseCalibration,
    params: StaticNoiseFilterParams,
) -> np.ndarray | None:
    """Render a red overlay highlighting pixels suppressed by the filter.

    Returns an RGBA image (H, W, 4) or None if filter is off / not calibrated.
    """
    if params.strength <= 0 or not cal.is_valid or cal.confidence_map is None:
        return None

    h, w = frame_shape
    alpha = params.strength / 100.0
    C = cal.confidence_map * alpha

    overlay = np.zeros((h, w, 4), dtype=np.uint8)
    overlay[:, :, 0] = 255  # red channel
    overlay[:, :, 3] = (C * 160).astype(np.uint8)  # alpha: max 160 for readability
    return overlay
