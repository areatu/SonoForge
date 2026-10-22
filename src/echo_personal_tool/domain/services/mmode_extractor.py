from __future__ import annotations

import numpy as np
from scipy.ndimage import map_coordinates


def extract_mmode_column(
    frame: np.ndarray,
    start: tuple[float, float],
    end: tuple[float, float],
    num_samples: int = 256,
) -> np.ndarray:
    # Convert to 2D grayscale if needed
    if frame.ndim == 3:
        frame = np.mean(frame[..., :3], axis=2).astype(frame.dtype)
    t = np.linspace(0.0, 1.0, num_samples)
    xs = start[0] + t * (end[0] - start[0])
    ys = start[1] + t * (end[1] - start[1])
    coords = np.array([ys, xs])
    result = map_coordinates(
        frame.astype(np.float32),
        coords,
        order=1,
        mode="nearest",
    )
    return result.astype(frame.dtype)
