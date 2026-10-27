"""Conservative image proxies for cardiac phase navigation (not segmentation).

Ignore the static black sector surround and compensate per-frame gain/offset
before measuring dark-pool area or brightness. A periodic gain adjustment must
not become a heartbeat. Anatomy eligibility is decided separately from these
signals: periodic pixels alone cannot identify an echocardiographic view.
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import binary_fill_holes, label


def image_phase_signals(gray_frames: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return dark fraction, mean intensity and motion on one shared tissue ROI.

    No temporal decimation: frame positions remain those of the source cine.
    Motion has no phase polarity and is only supporting rhythm evidence.
    Empty vectors mean that the image cannot support that particular proxy.
    """
    empty = np.zeros(0, dtype=np.float64)
    prepared = _normalised_roi(gray_frames)
    if prepared is None:
        return empty, empty, empty
    roi, foreground = prepared
    pixels = roi[:, foreground]
    intensity = np.asarray(pixels.mean(axis=1), dtype=np.float64)
    difference = np.abs(np.diff(pixels, axis=0)).mean(axis=1)
    motion = np.concatenate([difference[:1], difference])
    threshold = _otsu_threshold(np.median(pixels, axis=0))
    dark = empty
    if np.isfinite(threshold):
        fraction = (pixels < threshold).mean(axis=1)
        # Do not amplify a one-pixel oscillation into a unit-variance cycle.
        span = float(np.percentile(fraction, 95) - np.percentile(fraction, 5))
        if 0.02 <= float(fraction.mean()) <= 0.85 and span >= 0.01:
            dark = np.asarray(fraction, dtype=np.float64)
    if float(np.ptp(intensity)) < 0.005:
        intensity = empty
    return dark, intensity, np.asarray(motion, dtype=np.float64)


def _normalised_roi(gray_frames: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    arr = np.asarray(gray_frames, dtype=np.float32)
    if arr.ndim != 3 or arr.shape[0] < 4 or not np.isfinite(arr).all():
        return None
    h, w = arr.shape[1:]
    # Exclude the text/ruler margins and the usual bottom ECG band. The mask
    # below follows the tissue sector rather than assuming the LV is central.
    roi = arr[:, int(h * 0.12) : int(h * 0.82), int(w * 0.08) : int(w * 0.92)]
    if min(roi.shape[1:]) < 4:
        return None
    low, high = np.percentile(roi, [1, 99])
    if high - low < 1e-6:
        return None
    tissue = np.percentile(roi, 90, axis=0) > low + 0.03 * (high - low)
    tissue = binary_fill_holes(tissue)
    components, count = label(tissue)
    if count == 0:
        return None
    sizes = np.bincount(components.ravel())
    sizes[0] = 0
    foreground = components == int(np.argmax(sizes))
    if int(foreground.sum()) < max(32, int(0.10 * foreground.size)):
        return None
    values = roi[:, foreground]
    black = np.percentile(values, 2, axis=1)
    white = np.percentile(values, 95, axis=1)
    contrast = white - black
    if np.any(contrast < 1e-6):
        return None
    normalised = np.clip((roi - black[:, None, None]) / contrast[:, None, None], 0.0, 1.0)
    return normalised, foreground


def _otsu_threshold(values: np.ndarray) -> float:
    flat = np.asarray(values, dtype=np.float64).ravel()
    low, high = np.percentile(flat, [1, 99])
    if flat.size < 8 or high <= low:
        return float("nan")
    hist, edges = np.histogram(flat, bins=64, range=(low, high))
    centres = (edges[:-1] + edges[1:]) / 2.0
    weights = np.cumsum(hist).astype(np.float64)
    sums = np.cumsum(hist * centres)
    foreground = weights[-1] - weights
    valid = (weights > 0) & (foreground > 0)
    variance = np.zeros_like(weights)
    variance[valid] = (
        weights[valid]
        * foreground[valid]
        * (sums[valid] / weights[valid] - (sums[-1] - sums[valid]) / foreground[valid]) ** 2
    )
    return float(edges[int(np.argmax(variance)) + 1])
