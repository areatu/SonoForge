"""Pure NumPy/SciPy segmentation preprocessing and postprocessing."""

from __future__ import annotations

import numpy as np
from scipy import ndimage

_NEIGHBOR_OFFSETS: tuple[tuple[int, int], ...] = (
    (1, 0),
    (1, 1),
    (0, 1),
    (-1, 1),
    (-1, 0),
    (-1, -1),
    (0, -1),
    (1, -1),
)


def prepare_tensor(frame: np.ndarray, *, target_size: int = 112) -> np.ndarray:
    """RGB/BGR or grayscale H×W → (1, 3, H, W) float32, per-frame mean/std norm."""
    array = np.asarray(frame, dtype=np.float32)
    if array.ndim == 2:
        resized = _resize_spatial(array, target_size=target_size)
        rgb = np.stack([resized, resized, resized], axis=-1)
    elif array.ndim == 3 and array.shape[2] == 3:
        resized = _resize_spatial(array, target_size=target_size)
        rgb = resized
    else:
        msg = "frame must be grayscale H×W or color H×W×3"
        raise ValueError(msg)

    normalized = _normalize_per_frame(rgb)
    chw = np.transpose(normalized, (2, 0, 1))
    return np.expand_dims(chw, axis=0).astype(np.float32, copy=False)


def logits_to_mask(logits: np.ndarray, threshold: float = 0.5) -> np.ndarray:
    """(1,1,h,w) or (h,w) logits → binary mask (h,w) uint8 {0,1}."""
    array = np.asarray(logits, dtype=np.float32)
    if array.ndim == 4:
        array = array[0, 0]
    elif array.ndim == 3:
        array = array[0]
    elif array.ndim != 2:
        msg = "logits must have shape (1, 1, h, w), (1, h, w), or (h, w)"
        raise ValueError(msg)

    if array.min() < 0.0 or array.max() > 1.0:
        array = 1.0 / (1.0 + np.exp(-array))

    return (array >= threshold).astype(np.uint8)


def mask_to_contour(
    mask: np.ndarray,
    original_shape: tuple[int, int],
) -> list[tuple[float, float]]:
    """Largest connected component → closed polygon in original pixel coords."""
    binary = np.asarray(mask) > 0
    if not binary.any():
        return []

    labeled, component_count = ndimage.label(binary)
    if component_count == 0:
        return []

    counts = np.bincount(labeled.ravel())
    counts[0] = 0
    largest_label = int(np.argmax(counts))
    component = labeled == largest_label

    boundary = _trace_boundary(component)
    if len(boundary) < 3:
        return []

    mask_height, mask_width = binary.shape
    original_height, original_width = original_shape
    scale_x = original_width / mask_width
    scale_y = original_height / mask_height

    return [
        (x * scale_x, y * scale_y)
        for x, y in boundary
    ]


def smooth_contour(
    points: list[tuple[float, float]],
    *,
    num_nodes: int = 32,
) -> list[tuple[float, float]]:
    """Resample closed contour to num_nodes for spline editing."""
    if num_nodes <= 0:
        return []
    if not points:
        return []
    if len(points) == 1:
        return [points[0]] * num_nodes

    coords = np.asarray(points, dtype=np.float64)
    closed = np.vstack([coords, coords[0]])
    segments = np.diff(closed, axis=0)
    segment_lengths = np.linalg.norm(segments, axis=1)
    cumulative = np.concatenate([[0.0], np.cumsum(segment_lengths)])
    total_length = cumulative[-1]
    if total_length == 0.0:
        return [tuple(coords[0]) for _ in range(num_nodes)]

    targets = np.linspace(0.0, total_length, num_nodes, endpoint=False)
    resampled: list[tuple[float, float]] = []
    for target in targets:
        index = int(np.searchsorted(cumulative, target, side="right") - 1)
        index = min(index, len(coords) - 1)
        start_length = cumulative[index]
        end_length = cumulative[index + 1]
        if end_length > start_length:
            alpha = (target - start_length) / (end_length - start_length)
        else:
            alpha = 0.0
        start = coords[index]
        end = coords[(index + 1) % len(coords)]
        point = start + alpha * (end - start)
        resampled.append((float(point[0]), float(point[1])))
    return resampled


def _resize_spatial(array: np.ndarray, *, target_size: int) -> np.ndarray:
    height, width = array.shape[:2]
    if height == 0 or width == 0:
        msg = "frame must have non-zero height and width"
        raise ValueError(msg)

    zoom_y = target_size / height
    zoom_x = target_size / width
    if array.ndim == 2:
        return ndimage.zoom(array, (zoom_y, zoom_x), order=3)

    return ndimage.zoom(array, (zoom_y, zoom_x, 1.0), order=3)


def _normalize_per_frame(rgb: np.ndarray) -> np.ndarray:
    normalized = np.empty_like(rgb, dtype=np.float32)
    for channel in range(3):
        values = rgb[..., channel]
        mean = float(values.mean())
        std = float(values.std())
        if std > 0.0:
            normalized[..., channel] = (values - mean) / std
        else:
            normalized[..., channel] = values - mean
    return normalized


def _trace_boundary(component: np.ndarray) -> list[tuple[int, int]]:
    mask = component.astype(bool)
    height, width = mask.shape
    if not mask.any():
        return []

    start_y = int(np.argmax(mask.any(axis=1)))
    start_x = int(np.argmax(mask[start_y]))
    start = (start_x, start_y)

    contour: list[tuple[int, int]] = []
    current_x, current_y = start
    direction_index = 4

    for _ in range(height * width + 1):
        contour.append((current_x, current_y))
        found = False
        for offset in range(8):
            check_index = (direction_index + offset - 2) % 8
            dx, dy = _NEIGHBOR_OFFSETS[check_index]
            next_x = current_x + dx
            next_y = current_y + dy
            if 0 <= next_x < width and 0 <= next_y < height and mask[next_y, next_x]:
                current_x, current_y = next_x, next_y
                direction_index = check_index
                found = True
                break
        if not found:
            break
        if current_x == start[0] and current_y == start[1] and len(contour) > 2:
            break

    return _simplify_contour(contour)


def _simplify_contour(contour: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if len(contour) <= 2:
        return contour

    simplified: list[tuple[int, int]] = [contour[0]]
    for point in contour[1:]:
        if point != simplified[-1]:
            simplified.append(point)
    if len(simplified) > 2 and simplified[0] == simplified[-1]:
        simplified.pop()
    return simplified
