"""Pure NumPy/SciPy segmentation preprocessing and postprocessing."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import numpy as np
from scipy import ndimage

from echo_personal_tool.domain.services.contour_geometry import resample_open_arc, smooth_open_arc

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


@dataclass(frozen=True)
class EchoNetCropTransform:
    """Maps 112×112 ONNX mask back to full-frame pixel coordinates."""

    frame_height: int
    frame_width: int
    crop_y0: int
    crop_x0: int
    crop_height: int
    crop_width: int

    @property
    def crop_size(self) -> int:
        """Square crop edge length (center_square mode only)."""
        if self.crop_height != self.crop_width:
            msg = "crop_size is only defined for square EchoNet crops"
            raise AttributeError(msg)
        return self.crop_height


class EchoNetCropMode(str, Enum):
    CENTER_SQUARE = "center_square"
    FULL_ROI = "full_roi"


def resolve_echonet_roi_bounds(
    frame_shape: tuple[int, int],
    *,
    roi_xyxy: tuple[float, float, float, float] | None = None,
) -> tuple[int, int, int, int]:
    """B-mode ROI rectangle in pixel coords (y0, x0, y1, x1)."""
    height, width = frame_shape
    if roi_xyxy is None:
        return 0, 0, height, width

    x0f, y0f, x1f, y1f = roi_xyxy
    region_x0 = int(np.clip(round(x0f), 0, max(width - 1, 0)))
    region_y0 = int(np.clip(round(y0f), 0, max(height - 1, 0)))
    region_x1 = int(np.clip(round(x1f), region_x0 + 1, width))
    region_y1 = int(np.clip(round(y1f), region_y0 + 1, height))
    return region_y0, region_x0, region_y1, region_x1


def crop_frame_for_echonet(
    frame: np.ndarray,
    *,
    roi_xyxy: tuple[float, float, float, float] | None = None,
    crop_mode: str | EchoNetCropMode = EchoNetCropMode.CENTER_SQUARE,
) -> tuple[np.ndarray, EchoNetCropTransform]:
    """Extract B-mode ROI for EchoNet (resize to 112×112 in prepare_tensor)."""
    mode = EchoNetCropMode(crop_mode) if isinstance(crop_mode, str) else crop_mode
    array = np.asarray(frame)
    height, width = array.shape[:2]
    y0, x0, y1, x1 = resolve_echonet_roi_bounds((height, width), roi_xyxy=roi_xyxy)
    region_height = y1 - y0
    region_width = x1 - x0
    if mode is EchoNetCropMode.FULL_ROI:
        crop_y0, crop_x0 = y0, x0
        crop_height, crop_width = region_height, region_width
    else:
        crop_size = min(region_height, region_width)
        crop_y0 = y0 + (region_height - crop_size) // 2
        crop_x0 = x0 + (region_width - crop_size) // 2
        crop_height = crop_width = crop_size
    transform = EchoNetCropTransform(
        frame_height=height,
        frame_width=width,
        crop_y0=crop_y0,
        crop_x0=crop_x0,
        crop_height=crop_height,
        crop_width=crop_width,
    )
    return (
        array[crop_y0 : crop_y0 + crop_height, crop_x0 : crop_x0 + crop_width],
        transform,
    )


def embed_echonet_mask(mask: np.ndarray, transform: EchoNetCropTransform) -> np.ndarray:
    """Place 112×112 ONNX mask into full-frame coordinates."""
    full = np.zeros((transform.frame_height, transform.frame_width), dtype=np.uint8)
    if transform.crop_height <= 0 or transform.crop_width <= 0:
        return full

    array = np.asarray(mask)
    if array.ndim != 2 or array.size == 0:
        return full

    zoom_y = transform.crop_height / array.shape[0]
    zoom_x = transform.crop_width / array.shape[1]
    upscaled = ndimage.zoom(array.astype(np.float32), (zoom_y, zoom_x), order=1)
    upscaled = (upscaled >= 0.5).astype(np.uint8)
    paste_h = min(transform.crop_height, upscaled.shape[0])
    paste_w = min(transform.crop_width, upscaled.shape[1])
    y0, x0 = transform.crop_y0, transform.crop_x0
    full[y0 : y0 + paste_h, x0 : x0 + paste_w] = upscaled[:paste_h, :paste_w]
    return full


def prepare_tensor(
    frame: np.ndarray,
    *,
    target_size: int = 112,
    fixed_mean: list[float] | None = None,
    fixed_std: list[float] | None = None,
) -> np.ndarray:
    """RGB/BGR or grayscale H×W → (1, 3, H, W) float32, normalized."""
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

    if fixed_mean is not None and fixed_std is not None:
        normalized = _normalize_fixed(rgb, fixed_mean, fixed_std)
    else:
        normalized = _normalize_per_frame(rgb)
    chw = np.transpose(normalized, (2, 0, 1))
    return np.expand_dims(chw, axis=0).astype(np.float32, copy=False)


def logits_to_mask(
    logits: np.ndarray,
    threshold: float | None = None,
    *,
    adaptive: bool = True,
) -> np.ndarray:
    """(1,1,h,w) or (h,w) logits → binary mask (h,w) uint8 {0,1}.

    When adaptive=True and threshold is None, uses Otsu threshold clamped to [0.35, 0.65].
    """
    array = np.asarray(logits, dtype=np.float32)
    if array.ndim == 4:
        array = array[0, 0]
    elif array.ndim == 3:
        array = array[0]
    elif array.ndim != 2:
        msg = "logits must have shape (1, 1, h, w), (1, h, w), or (h, w)"
        raise ValueError(msg)

    if array.min() < 0.0 or array.max() > 1.0:
        array = 1.0 / (1.0 + np.exp(-np.clip(array, -50.0, 50.0)))

    if threshold is not None:
        return (array >= threshold).astype(np.uint8)

    if adaptive and array.size > 0:
        try:
            effective = float(np.clip(_otsu_threshold(array), 0.35, 0.65))
        except Exception:
            effective = 0.5
        return (array >= effective).astype(np.uint8)

    return (array >= 0.5).astype(np.uint8)


def _otsu_threshold(array: np.ndarray) -> float:
    """Otsu threshold on float [0, 1] array (256-bin histogram)."""
    hist, bin_edges = np.histogram(array.ravel(), bins=256, range=(0.0, 1.0))
    total = hist.sum()
    if total == 0:
        return 0.5
    bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2.0
    weight_bg = 0.0
    mean_bg = 0.0
    best_var = -1.0
    best_thresh = 0.5
    for i, count in enumerate(hist):
        weight_bg += count
        if weight_bg == 0:
            continue
        weight_fg = total - weight_bg
        if weight_fg == 0:
            break
        mean_bg += count * bin_centers[i]
        mean_bg_val = mean_bg / weight_bg
        mean_fg_val = (np.dot(bin_centers, hist) - mean_bg) / weight_fg
        var_between = weight_bg * weight_fg * (mean_bg_val - mean_fg_val) ** 2
        if var_between > best_var:
            best_var = var_between
            best_thresh = bin_centers[i]
    return best_thresh


def papillary_mask_cleanup(
    mask: np.ndarray,
    *,
    phase: str | None = None,
    long_axis_hint: tuple[tuple[float, float], tuple[float, float]] | None = None,
) -> np.ndarray:
    """Morphological closing along LV long axis to remove papillary notches.

    Phase-aware parameters (v1.5):
      ED: se_length_ratio=0.04, clamp [5, 15]
      ES: se_length_ratio=0.06, clamp [6, 18]

    When long_axis_hint is provided, the SE ellipse is rotated to align
    with the LV long axis (septal→apex or annulus→apex direction).
    """
    binary = np.asarray(mask) > 0
    if not binary.any():
        return np.zeros_like(binary, dtype=np.uint8)

    ys, xs = np.where(binary)
    top_y, bottom_y = int(ys.min()), int(ys.max())
    axis_length = float(bottom_y - top_y + 1)

    if phase == "ES":
        se_ratio, se_min, se_max = 0.06, 6, 18
    else:
        se_ratio, se_min, se_max = 0.04, 5, 15

    se_len = int(np.clip(se_ratio * axis_length, se_min, se_max))

    # Compute rotation angle from long_axis_hint or mask bbox
    angle = 0.0
    if long_axis_hint is not None:
        (ax0, ay0), (ax1, ay1) = long_axis_hint
        angle = math.degrees(math.atan2(ay1 - ay0, ax1 - ax0))
    else:
        # Derive from mask bbox: top (narrow) → bottom (wide) = long axis
        mid_x = float(xs.mean())
        angle = 90.0  # default: vertical (top→bottom)

    # Build rotated elliptical SE
    ry = max(se_len // 2, 1)
    rx = max(se_len // 3, 1)  # narrower along short axis
    cy, cx = se_len // 2, se_len // 2
    y_grid, x_grid = np.ogrid[:se_len, :se_len]
    # Rotate grid points around center
    rad = math.radians(angle)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    xr = (x_grid - cx) * cos_a + (y_grid - cy) * sin_a
    yr = -(x_grid - cx) * sin_a + (y_grid - cy) * cos_a
    structure = ((xr / rx) ** 2 + (yr / ry) ** 2 <= 1.0).astype(np.uint8)

    closed = ndimage.binary_closing(binary, structure=structure)
    filled = ndimage.binary_fill_holes(closed)
    labeled, count = ndimage.label(filled)
    if count == 0:
        return filled.astype(np.uint8)
    counts = np.bincount(labeled.ravel())
    counts[0] = 0
    largest = int(np.argmax(counts))
    return (labeled == largest).astype(np.uint8)


def _signed_depth_to_chord(
    point: tuple[float, float],
    chord_start: tuple[float, float],
    chord_end: tuple[float, float],
    *,
    inward_reference: tuple[float, float],
) -> float:
    """Negative depth = point is on inward_reference side of chord (concavity)."""
    x0, y0 = point
    x1, y1 = chord_start
    x2, y2 = chord_end
    ref_cross = (x2 - x1) * (inward_reference[1] - y1) - (y2 - y1) * (inward_reference[0] - x1)
    sign = -1.0 if ref_cross >= 0.0 else 1.0
    numer = abs((y2 - y1) * x0 - (x2 - x1) * y0 + x2 * y1 - y2 * x1)
    denom = math.hypot(x2 - x1, y2 - y1)
    if denom == 0.0:
        return 0.0
    return sign * numer / denom


def _project_onto_segment(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> tuple[float, float]:
    sx, sy = start
    ex, ey = end
    px, py = point
    dx, dy = ex - sx, ey - sy
    denom = dx * dx + dy * dy
    if denom == 0.0:
        return start
    t = max(0.0, min(1.0, ((px - sx) * dx + (py - sy) * dy) / denom))
    return (sx + t * dx, sy + t * dy)


def exclude_papillary_concavities(
    open_points: list[tuple[float, float]],
    annulus: tuple[tuple[float, float], tuple[float, float]],
    apex: tuple[float, float],
    *,
    depth_threshold_ratio: float | None = None,
    min_depth_px: float = 2.0,
    phase: str | None = None,
) -> list[tuple[float, float]]:
    """Push interior nodes outward when concave vs MA–apex chord (ASE papillary rule).

    Phase-aware defaults (v1.5):
      ED: depth_threshold_ratio=0.04
      ES: depth_threshold_ratio=0.05
    """
    if len(open_points) < 3:
        return list(open_points)

    if depth_threshold_ratio is None:
        depth_threshold_ratio = 0.05 if phase == "ES" else 0.04

    septal, lateral = annulus
    ma_mid = (
        (septal[0] + lateral[0]) / 2.0,
        (septal[1] + lateral[1]) / 2.0,
    )
    ma_len = math.hypot(lateral[0] - septal[0], lateral[1] - septal[1])
    threshold = max(min_depth_px, depth_threshold_ratio * ma_len)

    adjusted = [(float(x), float(y)) for x, y in open_points]
    for index in range(1, len(adjusted) - 1):
        depth = _signed_depth_to_chord(
            adjusted[index],
            ma_mid,
            apex,
            inward_reference=septal,
        )
        if depth < -threshold:
            adjusted[index] = _project_onto_segment(adjusted[index], ma_mid, apex)

    return smooth_open_arc(adjusted, annulus, apex=apex, iterations=4, blend=0.0)


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

    return [(x * scale_x, y * scale_y) for x, y in boundary]


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


def _normalize_fixed(
    rgb: np.ndarray,
    mean: list[float],
    std: list[float],
) -> np.ndarray:
    """Normalize with fixed dataset mean/std (v1.1)."""
    normalized = np.empty_like(rgb, dtype=np.float32)
    for channel in range(3):
        m = mean[channel] * 255.0 if max(mean) <= 1.0 else mean[channel]
        s = std[channel] * 255.0 if max(std) <= 1.0 else std[channel]
        if s > 0.0:
            normalized[..., channel] = (rgb[..., channel] - m) / s
        else:
            normalized[..., channel] = rgb[..., channel] - m
    return normalized


def _mask_boundary_points_in_band(
    mask: np.ndarray,
    y_low: int,
    y_high: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Extract boundary pixel coords (ys, xs) of mask within a Y band."""
    import cv2

    band = np.zeros_like(mask)
    y0 = max(0, y_low)
    y1 = min(mask.shape[0], y_high + 1)
    band[y0:y1, :] = mask[y0:y1, :]

    if not band.any():
        return np.array([], dtype=np.int32), np.array([], dtype=np.int32)

    contours, _ = cv2.findContours(band, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return np.array([], dtype=np.int32), np.array([], dtype=np.int32)

    largest = max(contours, key=cv2.contourArea)
    pts = largest[:, 0, :]  # shape (N, 2) → columns are x, y
    return pts[:, 1].astype(np.int32), pts[:, 0].astype(np.int32)


def _snap_annulus_to_mask_boundary(
    septal: tuple[float, float],
    lateral: tuple[float, float],
    mask: np.ndarray,
    *,
    basal_y_range: tuple[int, int],
    search_radius_px: float = 16.0,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Snap annulus endpoints to basal mask opening (septal=leftmost, lateral=rightmost).

    Half-plane split uses the MA midpoint, not the image center.
    """
    y_low, y_high = basal_y_range
    bys, bxs = _mask_boundary_points_in_band(mask, y_low, y_high)
    if bys.size == 0:
        return septal, lateral

    split_x = (septal[0] + lateral[0]) / 2.0

    def _snap_one(
        point: tuple[float, float],
        *,
        is_septal: bool,
    ) -> tuple[float, float]:
        px, py = point
        half_mask = bxs <= split_x if is_septal else bxs >= split_x
        if not np.any(half_mask):
            return point
        hys = bys[half_mask]
        hxs = bxs[half_mask]
        dists = np.sqrt((hxs - px) ** 2 + (hys - py) ** 2)
        nearby = dists <= search_radius_px
        if not np.any(nearby):
            best = int(np.argmin(dists))
            if dists[best] > search_radius_px:
                return point
            return (float(hxs[best]), float(hys[best]))
        hys_n = hys[nearby]
        hxs_n = hxs[nearby]
        pick = int(np.argmin(hxs_n)) if is_septal else int(np.argmax(hxs_n))
        return (float(hxs_n[pick]), float(hys_n[pick]))

    snapped_septal = _snap_one(septal, is_septal=True)
    snapped_lateral = _snap_one(lateral, is_septal=False)

    if snapped_septal[0] > snapped_lateral[0]:
        snapped_septal, snapped_lateral = snapped_lateral, snapped_septal
    return snapped_septal, snapped_lateral


def _blend_annulus_with_arc_tips(
    annulus: tuple[tuple[float, float], tuple[float, float]],
    open_points: list[tuple[float, float]],
    *,
    max_blend_dist_px: float = 8.0,
    blend_weight: float = 0.3,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Blend annulus endpoints toward open-arc first/last nodes when close."""
    if not open_points or len(open_points) < 2:
        return annulus

    septal, lateral = annulus
    first = open_points[0]
    last = open_points[-1]

    def _blend(
        pt: tuple[float, float],
        tip: tuple[float, float],
    ) -> tuple[float, float]:
        dist = math.hypot(tip[0] - pt[0], tip[1] - pt[1])
        if dist > max_blend_dist_px or dist < 1e-6:
            return pt
        return (
            pt[0] + blend_weight * (tip[0] - pt[0]),
            pt[1] + blend_weight * (tip[1] - pt[1]),
        )

    return _blend(septal, first), _blend(lateral, last)


def _trace_boundary(component: np.ndarray) -> list[tuple[int, int]]:
    """Outer boundary of the largest filled component (x, y) pixel coords."""
    import cv2

    mask_uint8 = (np.asarray(component) > 0).astype(np.uint8) * 255
    if not mask_uint8.any():
        return []

    contours, _ = cv2.findContours(mask_uint8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return []

    largest = max(contours, key=cv2.contourArea)
    if len(largest) < 3:
        return []

    return [(int(point[0][0]), int(point[0][1])) for point in largest]


def _closest_boundary_index(
    boundary: list[tuple[float, float]],
    target: tuple[float, float],
) -> int:
    best_index = 0
    best_distance = float("inf")
    for index, point in enumerate(boundary):
        distance = (point[0] - target[0]) ** 2 + (point[1] - target[1]) ** 2
        if distance < best_distance:
            best_distance = distance
            best_index = index
    return best_index


def _walk_boundary(
    boundary: list[tuple[float, float]],
    start_index: int,
    end_index: int,
    *,
    step: int,
) -> list[tuple[float, float]]:
    if not boundary:
        return []
    path: list[tuple[float, float]] = []
    index = start_index
    for _ in range(len(boundary) + 1):
        path.append(boundary[index])
        if index == end_index:
            break
        index = (index + step) % len(boundary)
    return path


def _boundary_open_arc(
    boundary: list[tuple[float, float]],
    septal: tuple[float, float],
    lateral: tuple[float, float],
    apex: tuple[float, float],
) -> list[tuple[float, float]]:
    """Boundary segment from septal to lateral through the cavity (contains apex)."""
    if len(boundary) < 3:
        return [septal, lateral]

    septal_index = _closest_boundary_index(boundary, septal)
    lateral_index = _closest_boundary_index(boundary, lateral)
    forward = _walk_boundary(boundary, septal_index, lateral_index, step=1)
    backward = _walk_boundary(boundary, septal_index, lateral_index, step=-1)

    def _min_apex_distance(path: list[tuple[float, float]]) -> float:
        if not path:
            return float("inf")
        return min(math.hypot(point[0] - apex[0], point[1] - apex[1]) for point in path)

    chosen = forward if _min_apex_distance(forward) <= _min_apex_distance(backward) else backward
    if len(chosen) < 2:
        return [septal, *chosen, lateral]
    return chosen


def _band_horizontal_width(
    ys: np.ndarray,
    xs: np.ndarray,
    y_low: int,
    y_high: int,
) -> float:
    in_band = (ys >= y_low) & (ys <= y_high)
    if not np.any(in_band):
        return 0.0
    band_xs = xs[in_band]
    return float(np.max(band_xs) - np.min(band_xs))


def _mitral_annulus_endpoints(
    ann_xs: np.ndarray,
    ann_ys: np.ndarray,
    *,
    trim_percentile: float = 12.0,
    prefer_high_y: bool | None = None,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Septal/lateral MV points with independent Y (sloped annulus), trimmed from mask edges.

    When ``prefer_high_y`` is set, snap each endpoint to basal-most points in the
    side bucket (higher y for bottom annulus, lower y for top annulus).
    """
    if ann_xs.size < 2:
        msg = "cannot locate mitral annulus on cavity mask"
        raise ValueError(msg)

    x_cut_low = float(np.percentile(ann_xs, trim_percentile))
    x_cut_high = float(np.percentile(ann_xs, 100.0 - trim_percentile))
    septal_mask = ann_xs <= x_cut_low
    lateral_mask = ann_xs >= x_cut_high
    if np.any(septal_mask):
        sx = ann_xs[septal_mask]
        sy = ann_ys[septal_mask]
        if prefer_high_y is None:
            septal = (float(np.mean(sx)), float(np.mean(sy)))
        else:
            target = np.max(sy) if prefer_high_y else np.min(sy)
            pick = np.isclose(sy, target)
            septal = (float(np.mean(sx[pick])), float(target))
    else:
        min_index = int(np.argmin(ann_xs))
        septal = (float(ann_xs[min_index]), float(ann_ys[min_index]))
    if np.any(lateral_mask):
        lx = ann_xs[lateral_mask]
        ly = ann_ys[lateral_mask]
        if prefer_high_y is None:
            lateral = (float(np.mean(lx)), float(np.mean(ly)))
        else:
            target = np.max(ly) if prefer_high_y else np.min(ly)
            pick = np.isclose(ly, target)
            lateral = (float(np.mean(lx[pick])), float(target))
    else:
        max_index = int(np.argmax(ann_xs))
        lateral = (float(ann_xs[max_index]), float(ann_ys[max_index]))
    if septal[0] > lateral[0]:
        septal, lateral = lateral, septal
    return septal, lateral


def _annulus_and_apex_from_mask_pixels(
    ys: np.ndarray,
    xs: np.ndarray,
    *,
    y_min: int,
    y_max: int,
    annulus_end: str = "auto",
    mask: np.ndarray | None = None,
) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]]:
    """Annulus = wider cavity opening; apex = opposite narrow end (A4C)."""
    height = y_max - y_min + 1
    band_depth = max(3, int(round(0.12 * height)))
    apex_band = max(3, int(round(0.08 * height)))

    top_band = (y_min, y_min + band_depth)
    bottom_band = (y_max - band_depth, y_max)
    top_width = _band_horizontal_width(ys, xs, *top_band)
    bottom_width = _band_horizontal_width(ys, xs, *bottom_band)

    if annulus_end == "top":
        annulus_at_bottom = False
    elif annulus_end == "bottom":
        annulus_at_bottom = True
    else:
        annulus_at_bottom = bottom_width > top_width

    if annulus_at_bottom:
        annulus_mask = (ys >= bottom_band[0]) & (ys <= bottom_band[1])
        apex_mask = (ys >= y_min) & (ys <= y_min + apex_band)
        apex_y = float(y_min + apex_band / 2.0)
        basal_y_range = (bottom_band[0], bottom_band[1])
    else:
        annulus_mask = (ys >= top_band[0]) & (ys <= top_band[1])
        apex_mask = (ys >= y_max - apex_band) & (ys <= y_max)
        apex_y = float(y_max - apex_band / 2.0)
        basal_y_range = (top_band[0], top_band[1])

    ann_xs = xs[annulus_mask]
    ann_ys = ys[annulus_mask]
    if ann_xs.size < 2:
        msg = "cannot locate mitral annulus on cavity mask"
        raise ValueError(msg)

    septal, lateral = _mitral_annulus_endpoints(
        ann_xs,
        ann_ys,
        prefer_high_y=annulus_at_bottom,
    )

    # Boundary snap when full mask is available
    if mask is not None:
        septal, lateral = _snap_annulus_to_mask_boundary(
            septal,
            lateral,
            mask,
            basal_y_range=basal_y_range,
        )

    if np.any(apex_mask):
        apex = (float(np.median(xs[apex_mask])), float(np.median(ys[apex_mask])))
    else:
        apex = (float(np.median(xs)), apex_y)
    return septal, lateral, apex


def _fallback_annulus_wider_band(
    ys: np.ndarray,
    xs: np.ndarray,
    *,
    y_min: int,
    y_max: int,
    mask: np.ndarray | None = None,
) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]]:
    """Fallback A: wider annulus band (18% instead of 12%) for fragmented masks."""
    height = y_max - y_min + 1
    band_depth = max(3, int(round(0.18 * height)))
    apex_band = max(3, int(round(0.08 * height)))

    top_band = (y_min, y_min + band_depth)
    bottom_band = (y_max - band_depth, y_max)
    top_width = _band_horizontal_width(ys, xs, *top_band)
    bottom_width = _band_horizontal_width(ys, xs, *bottom_band)

    annulus_at_bottom = bottom_width >= top_width

    if annulus_at_bottom:
        annulus_mask = (ys >= bottom_band[0]) & (ys <= bottom_band[1])
        apex_mask = (ys >= y_min) & (ys <= y_min + apex_band)
        apex_y = float(y_min + apex_band / 2.0)
        basal_y_range = (bottom_band[0], bottom_band[1])
    else:
        annulus_mask = (ys >= top_band[0]) & (ys <= top_band[1])
        apex_mask = (ys >= y_max - apex_band) & (ys <= y_max)
        apex_y = float(y_max - apex_band / 2.0)
        basal_y_range = (top_band[0], top_band[1])

    ann_xs = xs[annulus_mask]
    ann_ys = ys[annulus_mask]
    if ann_xs.size < 2:
        msg = "fallback A: cannot locate mitral annulus with wider band"
        raise ValueError(msg)

    septal, lateral = _mitral_annulus_endpoints(
        ann_xs,
        ann_ys,
        trim_percentile=8.0,
        prefer_high_y=annulus_at_bottom,
    )

    # Boundary snap when full mask is available
    if mask is not None:
        septal, lateral = _snap_annulus_to_mask_boundary(
            septal,
            lateral,
            mask,
            basal_y_range=basal_y_range,
        )

    if np.any(apex_mask):
        apex = (float(np.median(xs[apex_mask])), float(np.median(ys[apex_mask])))
    else:
        apex = (float(np.median(xs)), apex_y)
    return septal, lateral, apex


def _fallback_annulus_sector_chord(
    ys: np.ndarray,
    xs: np.ndarray,
    *,
    y_min: int,
    y_max: int,
) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]]:
    """Fallback B: widest horizontal span in basal 25% as provisional MA."""
    height = y_max - y_min + 1
    basal_depth = max(3, int(round(0.25 * height)))
    basal_band = (y_min, y_min + basal_depth)

    basal_ys = ys[(ys >= basal_band[0]) & (ys <= basal_band[1])]
    basal_xs = xs[(ys >= basal_band[0]) & (ys <= basal_band[1])]
    if basal_xs.size < 2:
        msg = "fallback B: basal band too narrow for sector chord"
        raise ValueError(msg)

    min_x = float(np.min(basal_xs))
    max_x = float(np.max(basal_xs))
    min_y_at_min = float(np.mean(basal_ys[basal_xs == np.min(basal_xs)]))
    max_y_at_max = float(np.mean(basal_ys[basal_xs == np.max(basal_xs)]))

    septal = (min_x, min_y_at_min)
    lateral = (max_x, max_y_at_max)
    if septal[0] > lateral[0]:
        septal, lateral = lateral, septal

    apex = (float(np.median(xs)), float(y_max - height * 0.04))
    return septal, lateral, apex


_MA_ONNX_MODEL_PATH = Path(__file__).resolve().parent.parent.parent.parent.parent / "models" / "ma_landmark_224.onnx"
_MA_ONNX_CROP = 224
_MA_ONNX_BLEND_WEIGHT = 0.35


def _blend_landmark(
    base: tuple[float, float],
    ref: tuple[float, float],
    weight: float,
) -> tuple[float, float]:
    return (
        base[0] + weight * (ref[0] - base[0]),
        base[1] + weight * (ref[1] - base[1]),
    )


def _try_refine_annulus_with_onnx(
    septal: tuple[float, float],
    lateral: tuple[float, float],
    mask: np.ndarray,
    frame_shape: tuple[int, int],
    *,
    blend_weight: float = _MA_ONNX_BLEND_WEIGHT,
    max_offset_px: float = 25.0,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Post-process geometry landmarks with MA ONNX when prediction is plausible."""
    if not _MA_ONNX_MODEL_PATH.is_file():
        return septal, lateral
    try:
        onnx_septal, onnx_lateral = _predict_ma_onnx_keypoints(mask, frame_shape)
    except Exception:
        return septal, lateral

    for base, pred in ((septal, onnx_septal), (lateral, onnx_lateral)):
        if math.hypot(pred[0] - base[0], pred[1] - base[1]) > max_offset_px:
            return septal, lateral

    septal = _blend_landmark(septal, onnx_septal, blend_weight)
    lateral = _blend_landmark(lateral, onnx_lateral, blend_weight)
    if septal[0] > lateral[0]:
        septal, lateral = lateral, septal
    return septal, lateral


def _predict_ma_onnx_keypoints(
    mask: np.ndarray,
    frame_shape: tuple[int, int],
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Run MA landmark ONNX and return (septal, lateral) in full-frame coords."""
    import onnxruntime as ort

    if not _MA_ONNX_MODEL_PATH.is_file():
        msg = f"MA landmark ONNX not found: {_MA_ONNX_MODEL_PATH}"
        raise FileNotFoundError(msg)

    binary = np.asarray(mask) > 0
    ys, xs = np.where(binary)
    x_min, x_max = int(xs.min()), int(xs.max())
    y_min, y_max = int(ys.min()), int(ys.max())

    mid_x = (x_min + x_max) / 2.0
    mid_y = (y_min + y_max) / 2.0
    half = _MA_ONNX_CROP / 2.0
    x0 = int(np.clip(mid_x - half, 0, max(frame_shape[1] - _MA_ONNX_CROP, 0)))
    y0 = int(np.clip(mid_y - half, 0, max(frame_shape[0] - _MA_ONNX_CROP, 0)))

    crop = mask[y0 : y0 + _MA_ONNX_CROP, x0 : x0 + _MA_ONNX_CROP]
    if crop.shape[0] < _MA_ONNX_CROP or crop.shape[1] < _MA_ONNX_CROP:
        padded = np.zeros((_MA_ONNX_CROP, _MA_ONNX_CROP), dtype=crop.dtype)
        padded[: crop.shape[0], : crop.shape[1]] = crop
        crop = padded
    inp = crop.astype(np.float32)[np.newaxis, np.newaxis, ...]

    sess = ort.InferenceSession(str(_MA_ONNX_MODEL_PATH))
    out = sess.run(None, {"input": inp})[0]  # (1, 2, 224, 224)

    keypoints: list[tuple[float, float]] = []
    for k in range(2):
        hm = out[0, k]
        py, px = np.unravel_index(hm.argmax(), hm.shape)
        keypoints.append((float(px) + x0, float(py) + y0))

    septal, lateral = keypoints
    if septal[0] > lateral[0]:
        septal, lateral = lateral, septal
    return septal, lateral


def _ma_onnx_fallback(
    mask: np.ndarray,
    original_shape: tuple[int, int],
) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]]:
    """Fallback C: MA ONNX landmark regressor."""
    binary = np.asarray(mask) > 0
    ys, xs = np.where(binary)
    y_min, y_max = int(ys.min()), int(ys.max())
    height = y_max - y_min + 1

    septal, lateral = _predict_ma_onnx_keypoints(mask, original_shape)
    apex = (float(np.median(xs)), float(y_max - height * 0.04))
    return septal, lateral, apex


def open_arc_from_cavity_mask(
    mask: np.ndarray,
    *,
    original_shape: tuple[int, int] | None = None,
    num_nodes: int = 32,
    view_hint: str = "A4C",
    annulus_end: str = "auto",
) -> tuple[
    list[tuple[float, float]],
    tuple[tuple[float, float], tuple[float, float]],
    tuple[float, float],
]:
    """Build A4C LV open arc: annulus = wider cavity opening, arc via apex side."""
    view = (view_hint or "A4C").upper()
    binary = np.asarray(mask) > 0
    if not binary.any():
        msg = "empty cavity mask"
        raise ValueError(msg)

    labeled, component_count = ndimage.label(binary)
    if component_count == 0:
        msg = "empty cavity mask"
        raise ValueError(msg)

    counts = np.bincount(labeled.ravel())
    counts[0] = 0
    largest_label = int(np.argmax(counts))
    component = labeled == largest_label

    ys, xs = np.where(component)
    y_min = int(ys.min())
    y_max = int(ys.max())
    x_min = int(xs.min())
    x_max = int(xs.max())
    height = y_max - y_min + 1
    width = x_max - x_min + 1
    if height < 10 or width < 10:
        msg = "cavity mask bounding box too small"
        raise ValueError(msg)

    component_mask = component.astype(np.uint8)
    try:
        septal, lateral, apex = _annulus_and_apex_from_mask_pixels(
            ys,
            xs,
            y_min=y_min,
            y_max=y_max,
            annulus_end=annulus_end,
            mask=component_mask,
        )
    except ValueError:
        try:
            septal, lateral, apex = _fallback_annulus_wider_band(
                ys,
                xs,
                y_min=y_min,
                y_max=y_max,
                mask=component_mask,
            )
        except ValueError:
            try:
                septal, lateral, apex = _fallback_annulus_sector_chord(
                    ys,
                    xs,
                    y_min=y_min,
                    y_max=y_max,
                )
            except ValueError:
                frame_h, frame_w = original_shape or binary.shape[:2]
                septal, lateral, apex = _ma_onnx_fallback(
                    component_mask,
                    (frame_h, frame_w),
                )

    if view == "A4C" and annulus_end == "auto":
        annulus_mid_y = (septal[1] + lateral[1]) / 2.0
        if annulus_mid_y < apex[1]:
            try:
                septal, lateral, apex = _annulus_and_apex_from_mask_pixels(
                    ys,
                    xs,
                    y_min=y_min,
                    y_max=y_max,
                    annulus_end="bottom",
                    mask=component_mask,
                )
            except ValueError:
                pass  # keep the original flip result

    frame_shape = original_shape or binary.shape[:2]
    septal, lateral = _try_refine_annulus_with_onnx(
        septal,
        lateral,
        component_mask,
        frame_shape,
    )

    boundary = mask_to_contour(component_mask, frame_shape)
    if len(boundary) < 4:
        msg = "cavity boundary too short"
        raise ValueError(msg)

    # Preliminary arc for tip-guided MA refinement, then rebuild arc with final MA.
    open_points = _boundary_open_arc(boundary, septal, lateral, apex)
    septal, lateral = _blend_annulus_with_arc_tips(
        (septal, lateral),
        open_points,
        max_blend_dist_px=12.0,
        blend_weight=0.3,
    )
    open_points = _boundary_open_arc(boundary, septal, lateral, apex)
    annulus = (septal, lateral)

    resampled = resample_open_arc(open_points, num_nodes=max(num_nodes, 4))
    if len(resampled) < 3:
        resampled = [septal, apex, lateral]
    resampled[0] = septal
    resampled[-1] = lateral
    return resampled, annulus, apex


def closed_polygon_to_open_arc(
    points: list[tuple[float, float]],
    *,
    view_hint: str = "A4C",
) -> tuple[list[tuple[float, float]], tuple[tuple[float, float], tuple[float, float]]]:
    """Convert closed AI polygon to open arc using longest chord as mitral annulus."""
    del view_hint
    if len(points) < 4:
        msg = "closed polygon must have at least 4 points"
        raise ValueError(msg)

    best_length = -1.0
    best_i = 0
    best_j = 1
    for i in range(len(points)):
        for j in range(i + 1, len(points)):
            dx = points[j][0] - points[i][0]
            dy = points[j][1] - points[i][1]
            length = dx * dx + dy * dy
            if length > best_length:
                best_length = length
                best_i, best_j = i, j

    septal = points[best_i]
    lateral = points[best_j]
    annulus = (septal, lateral)

    ordered: list[tuple[float, float]] = [septal]
    index = (best_i + 1) % len(points)
    while index != best_j:
        ordered.append(points[index])
        index = (index + 1) % len(points)
    ordered.append(lateral)
    return ordered, annulus


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
