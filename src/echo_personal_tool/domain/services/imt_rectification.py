"""Bounded rotated-rectangle resampling, used for search but never for mm metrics."""

from __future__ import annotations

from math import ceil

import numpy as np
from scipy.ndimage import distance_transform_edt, map_coordinates

from echo_personal_tool.domain.models.imt import ImtSource
from echo_personal_tool.domain.models.imt_region import region_axes


def sampling_grid(source: ImtSource) -> tuple[np.ndarray, np.ndarray, np.ndarray, tuple[int, int]]:
    origin, u, v, width, height = region_axes(source.roi_polygon)
    shape = (ceil(height - 1e-9), ceil(width - 1e-9))
    return origin, u * width / shape[1], v * height / shape[0], shape


def rectify_crop(crop: np.ndarray, source: ImtSource) -> np.ndarray:
    """Sample only pixels inside the oriented rectangle from its bounded crop."""
    origin, du, dv, shape = sampling_grid(source)
    yy, xx = np.indices(shape, dtype=float)
    x0, y0, _, _ = source.roi
    x = origin[0] - x0 + xx * du[0] + yy * dv[0]
    y = origin[1] - y0 + xx * du[1] + yy * dv[1]
    return np.asarray(map_coordinates(crop, [y, x], order=1, mode="nearest"))


def unrectify_evidence(local: np.ndarray, source: ImtSource) -> np.ndarray:
    """Put search evidence back onto source pixels; outside the rectangle is zero."""
    origin, du, dv, _ = sampling_grid(source)
    x0, y0, x1, y1 = source.roi
    yy, xx = np.indices((y1 - y0, x1 - x0), dtype=float)
    points = np.stack((xx + x0 - origin[0], yy + y0 - origin[1]), axis=-1)
    along = points @ du / float(du @ du)
    depth = points @ dv / float(dv @ dv)
    return np.asarray(map_coordinates(local, [depth, along], order=1, mode="constant", cval=0.0))


def isolate_rectangle(crop: np.ndarray, source: ImtSource) -> np.ndarray:
    """Do not let interpolation/normalisation borrow intense pixels outside ROI."""
    origin, u, v, width, height = region_axes(source.roi_polygon)
    x0, y0, _, _ = source.roi
    yy, xx = np.indices(crop.shape, dtype=float)
    points = np.stack((xx + x0 - origin[0], yy + y0 - origin[1]), axis=-1)
    along, depth = points @ u, points @ v
    outside = (along < 0) | (along >= width) | (depth < 0) | (depth >= height)
    nearest = distance_transform_edt(outside, return_distances=False, return_indices=True)
    return np.asarray(crop[tuple(nearest)])
