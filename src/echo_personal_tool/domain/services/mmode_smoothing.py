"""Smart M-mode smoothing: log compression, spatial Gaussian, temporal EMA."""

from __future__ import annotations

import numpy as np
from scipy.ndimage import gaussian_filter1d


def log_compress(column: np.ndarray) -> np.ndarray:
    """Logarithmic compression like real ultrasound machines.

    Maps wide dynamic range to perceptual brightness scale.
    """
    f32 = column.astype(np.float32)
    return np.log1p(f32) * (255.0 / np.log1p(255.0))


def spatial_smooth(column: np.ndarray, sigma: float = 1.5) -> np.ndarray:
    """1D Gaussian smoothing along depth (axis=0) to remove pixel jaggedness."""
    return gaussian_filter1d(column.astype(np.float32), sigma=sigma, axis=0, mode="nearest")


def temporal_smooth(
    current: np.ndarray,
    previous: np.ndarray | None,
    alpha: float = 0.3,
) -> np.ndarray:
    """Exponential moving average between consecutive frames.

    alpha=0.0 → no change, alpha=1.0 → fully current.
    0.3 gives smooth result while tracking motion.
    """
    if previous is None:
        return current
    return (alpha * current + (1.0 - alpha) * previous).astype(current.dtype)
