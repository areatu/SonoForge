"""Edge map and 1D normal-profile snap for LV open-arc contours."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from scipy import ndimage


@dataclass(frozen=True)
class EdgeSnapConfig:
    search_radius_px: float = 12.0
    profile_samples: int = 25
    blur_sigma: float = 1.2
    min_edge_strength: float = 0.0
    inward_only: bool = True
    outward_only: bool = False
    intensity_fallback: bool = False


@dataclass(frozen=True)
class EdgeMap:
    """Precomputed gradient magnitude and direction for edge snapping."""

    magnitude: np.ndarray
    grad_x: np.ndarray
    grad_y: np.ndarray
    height: int
    width: int
    intensity: np.ndarray | None = None


def edge_snap_config_for_source(source: str, *, cine: bool = False) -> EdgeSnapConfig:
    normalized = source.strip().lower()
    if normalized == "ai":
        if cine:
            return EdgeSnapConfig(
                search_radius_px=10.0,
                min_edge_strength=0.0,
                blur_sigma=1.0,
                inward_only=False,
            )
        return EdgeSnapConfig(search_radius_px=16.0, min_edge_strength=0.05)
    if normalized == "manual":
        return EdgeSnapConfig(search_radius_px=10.0, min_edge_strength=0.08)
    return EdgeSnapConfig(search_radius_px=12.0, min_edge_strength=0.06)


def magnetic_edge_snap_config_for_source(source: str) -> EdgeSnapConfig:
    """Bidirectional edge search along outward normal (magnetic uses soft blend)."""
    base = edge_snap_config_for_source(source)
    return EdgeSnapConfig(
        search_radius_px=max(base.search_radius_px + 4.0, 14.0),
        profile_samples=33,
        blur_sigma=base.blur_sigma,
        min_edge_strength=0.0,
        inward_only=False,
        outward_only=True,
        intensity_fallback=True,
    )


def build_edge_map(
    frame: np.ndarray,
    *,
    display_levels: tuple[float, float] | None = None,
    blur_sigma: float = 1.2,
) -> EdgeMap:
    """Build signed-edge cost fields from a grayscale or BGR frame."""
    gray = _to_grayscale(frame)
    if display_levels is not None:
        low, high = display_levels
        if high > low:
            gray = np.clip(gray, low, high)
            gray = (gray - low) / (high - low) * 255.0

    blurred = ndimage.gaussian_filter(gray, sigma=blur_sigma)
    grad_x = ndimage.sobel(blurred, axis=1)
    grad_y = ndimage.sobel(blurred, axis=0)
    magnitude = np.hypot(grad_x, grad_y)
    height, width = gray.shape
    return EdgeMap(
        magnitude=magnitude,
        grad_x=grad_x,
        grad_y=grad_y,
        height=height,
        width=width,
        intensity=blurred,
    )


def outward_normal_at_index(
    points: Sequence[Sequence[float]],
    index: int,
) -> tuple[float, float]:
    """Unit normal pointing away from the arc interior (toward myocardium)."""
    previous = points[index - 1]
    current = points[index]
    following = points[index + 1]
    tangent_x = following[0] - previous[0]
    tangent_y = following[1] - previous[1]
    length = float(np.hypot(tangent_x, tangent_y))
    if length <= 1e-6:
        return (0.0, -1.0)
    tangent_x /= length
    tangent_y /= length
    normal_x = -tangent_y
    normal_y = tangent_x
    centroid_x = sum(float(point[0]) for point in points) / len(points)
    centroid_y = sum(float(point[1]) for point in points) / len(points)
    to_interior_x = centroid_x - current[0]
    to_interior_y = centroid_y - current[1]
    if normal_x * to_interior_x + normal_y * to_interior_y > 0.0:
        normal_x = -normal_x
        normal_y = -normal_y
    return (normal_x, normal_y)


def directed_edge_score(
    edge_map: EdgeMap,
    x: float,
    y: float,
    normal: tuple[float, float],
    *,
    inward_only: bool = True,
) -> float:
    """Directed endocardial edge strength at a sample point (0 = no edge)."""
    normal_x, normal_y = normal
    norm_len = float(np.hypot(normal_x, normal_y))
    if norm_len <= 1e-6:
        return 0.0
    normal_x /= norm_len
    normal_y /= norm_len
    magnitude = _sample_bilinear(edge_map.magnitude, x, y, edge_map)
    if magnitude <= 0.0:
        return 0.0
    gx = _sample_bilinear(edge_map.grad_x, x, y, edge_map)
    gy = _sample_bilinear(edge_map.grad_y, x, y, edge_map)
    grad_len = float(np.hypot(gx, gy))
    if grad_len <= 1e-6:
        return 0.0
    grad_dir_x = gx / grad_len
    grad_dir_y = gy / grad_len
    directional = grad_dir_x * normal_x + grad_dir_y * normal_y
    if inward_only and directional <= 0.0:
        return 0.0
    return float(magnitude * (directional if inward_only else abs(directional)))


def snap_point(
    edge_map: EdgeMap,
    x: float,
    y: float,
    normal: tuple[float, float],
    config: EdgeSnapConfig | None = None,
) -> tuple[float, float] | None:
    """Find strongest directed edge along normal within search radius."""
    cfg = config or EdgeSnapConfig()
    radius = max(float(cfg.search_radius_px), 1.0)
    samples = max(int(cfg.profile_samples), 3)
    if cfg.outward_only:
        offsets = np.linspace(0.0, radius, samples)
    else:
        offsets = np.linspace(-radius, radius, samples)

    normal_x, normal_y = normal
    norm_len = float(np.hypot(normal_x, normal_y))
    if norm_len <= 1e-6:
        return None
    normal_x /= norm_len
    normal_y /= norm_len

    best_score = cfg.min_edge_strength
    best_offset = 0.0
    found = False

    for offset in offsets:
        sample_x = x + float(offset) * normal_x
        sample_y = y + float(offset) * normal_y
        magnitude = _sample_bilinear(edge_map.magnitude, sample_x, sample_y, edge_map)
        if magnitude <= 0.0:
            continue
        gx = _sample_bilinear(edge_map.grad_x, sample_x, sample_y, edge_map)
        gy = _sample_bilinear(edge_map.grad_y, sample_x, sample_y, edge_map)
        grad_len = float(np.hypot(gx, gy))
        if grad_len <= 1e-6:
            continue
        grad_dir_x = gx / grad_len
        grad_dir_y = gy / grad_len
        directional = grad_dir_x * normal_x + grad_dir_y * normal_y
        if cfg.inward_only and directional <= 0.0:
            continue
        score = magnitude * (directional if cfg.inward_only else abs(directional))
        if score > best_score:
            best_score = score
            best_offset = float(offset)
            found = True

    if not found:
        if cfg.intensity_fallback and cfg.outward_only:
            return _snap_intensity_ridge(
                edge_map,
                x,
                y,
                (normal_x, normal_y),
                radius,
                samples,
            )
        return None
    new_x = _clamp(x + best_offset * normal_x, 0.0, edge_map.width - 1.0)
    new_y = _clamp(y + best_offset * normal_y, 0.0, edge_map.height - 1.0)
    return (new_x, new_y)


def snap_magnetic_point(
    edge_map: EdgeMap,
    x: float,
    y: float,
    normal: tuple[float, float],
    config: EdgeSnapConfig | None = None,
) -> tuple[float, float] | None:
    """Magnetic drag snap: combine gradient + intensity ridge, prefer outward pull."""
    cfg = config or magnetic_edge_snap_config_for_source("manual")
    gradient = snap_point(edge_map, x, y, normal, cfg)
    ridge = _snap_intensity_ridge(
        edge_map,
        x,
        y,
        normal,
        max(float(cfg.search_radius_px), 1.0),
        max(int(cfg.profile_samples), 3),
    )
    if gradient is None and ridge is None:
        return None
    if gradient is None:
        return ridge
    if ridge is None:
        return gradient

    normal_x, normal_y = normal
    norm_len = float(np.hypot(normal_x, normal_y))
    if norm_len <= 1e-6:
        return gradient
    normal_x /= norm_len
    normal_y /= norm_len

    def outward_delta(position: tuple[float, float]) -> float:
        return (position[0] - x) * normal_x + (position[1] - y) * normal_y

    return ridge if outward_delta(ridge) > outward_delta(gradient) else gradient


def apply_soft_magnetic_snap(
    points: list[tuple[float, float]],
    weights: Sequence[float],
    edge_map: EdgeMap,
    *,
    strength: float,
    max_radial_px: float,
    weight_threshold: float = 0.15,
    config: EdgeSnapConfig | None = None,
    pinned_indices: frozenset[int] | None = None,
    grab_index: int | None = None,
    min_radial_px: float = 0.35,
) -> list[tuple[float, float]]:
    """Gently pull nodes toward edges along outward normals; cursor motion dominates."""
    if len(points) < 3:
        return list(points)
    pinned = pinned_indices if pinned_indices is not None else frozenset({0, len(points) - 1})
    cfg = config or magnetic_edge_snap_config_for_source("manual")
    blend = max(0.0, min(float(strength), 1.0))
    max_step = max(float(max_radial_px), 0.0)
    if blend <= 0.0 or max_step <= 0.0:
        return list(points)

    updated = list(points)
    for index in range(len(points)):
        if index in pinned:
            continue
        weight = float(weights[index]) if index < len(weights) else 0.0
        grabbed = grab_index is not None and index == grab_index
        if not grabbed and weight < weight_threshold:
            continue

        px, py = points[index]
        normal = outward_normal_at_index(points, index)
        normal_x, normal_y = normal
        norm_len = float(np.hypot(normal_x, normal_y))
        if norm_len <= 1e-6:
            continue
        normal_x /= norm_len
        normal_y /= norm_len

        target = snap_magnetic_point(edge_map, px, py, normal, cfg)
        if target is None:
            continue

        radial = (target[0] - px) * normal_x + (target[1] - py) * normal_y
        if radial <= min_radial_px:
            continue

        influence = 1.0 if grabbed else weight
        step = min(radial, max_step) * blend * influence
        if step <= 1e-6:
            continue
        updated[index] = (
            _clamp(px + step * normal_x, 0.0, edge_map.width - 1.0),
            _clamp(py + step * normal_y, 0.0, edge_map.height - 1.0),
        )
    return updated


def snap_weighted_nodes(
    points: list[tuple[float, float]],
    weights: Sequence[float],
    edge_map: EdgeMap,
    *,
    weight_threshold: float = 0.12,
    config: EdgeSnapConfig | None = None,
    pinned_indices: frozenset[int] | None = None,
    grab_index: int | None = None,
) -> list[tuple[float, float]]:
    """Snap interior nodes with sufficient RBF weight toward edges."""
    if len(points) < 3:
        return list(points)
    pinned = pinned_indices if pinned_indices is not None else frozenset({0, len(points) - 1})
    cfg = config or EdgeSnapConfig()
    updated = list(points)
    for index in range(len(points)):
        if index in pinned:
            continue
        weighted = index < len(weights) and weights[index] >= weight_threshold
        grabbed = grab_index is not None and index == grab_index
        if not weighted and not grabbed:
            continue
        normal = outward_normal_at_index(points, index)
        if cfg.outward_only and cfg.intensity_fallback:
            snapped = snap_magnetic_point(
                edge_map,
                points[index][0],
                points[index][1],
                normal,
                cfg,
            )
        else:
            snapped = snap_point(edge_map, points[index][0], points[index][1], normal, cfg)
        if snapped is not None:
            updated[index] = snapped
    return updated


def _to_grayscale(frame: np.ndarray) -> np.ndarray:
    array = np.asarray(frame)
    if array.ndim == 3:
        return np.mean(array[..., :3], axis=2, dtype=np.float64)
    return array.astype(np.float64, copy=False)


def _sample_bilinear(values: np.ndarray, x: float, y: float, edge_map: EdgeMap) -> float:
    height = edge_map.height
    width = edge_map.width
    if x < 0.0 or y < 0.0 or x >= width - 1 or y >= height - 1:
        return 0.0
    x0 = int(x)
    y0 = int(y)
    x1 = x0 + 1
    y1 = y0 + 1
    dx = x - x0
    dy = y - y0
    top = (1.0 - dx) * values[y0, x0] + dx * values[y0, x1]
    bottom = (1.0 - dx) * values[y1, x0] + dx * values[y1, x1]
    return float((1.0 - dy) * top + dy * bottom)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _snap_intensity_ridge(
    edge_map: EdgeMap,
    x: float,
    y: float,
    normal: tuple[float, float],
    radius: float,
    samples: int,
) -> tuple[float, float] | None:
    """Find strongest intensity transition (bright→dark or dark→bright) along outward normal."""
    if edge_map.intensity is None:
        return None
    normal_x, normal_y = normal
    offsets = np.linspace(0.0, radius, max(samples, 3))
    intensities: list[float] = []
    for offset in offsets:
        sample_x = x + float(offset) * normal_x
        sample_y = y + float(offset) * normal_y
        intensities.append(
            _sample_bilinear(edge_map.intensity, sample_x, sample_y, edge_map),
        )
    best_abs_deriv = 0.0
    best_offset = 0.0
    for index in range(1, len(offsets)):
        deriv = intensities[index] - intensities[index - 1]
        if abs(deriv) > best_abs_deriv:
            best_abs_deriv = abs(deriv)
            best_offset = float(0.5 * (offsets[index] + offsets[index - 1]))
    peak = max(intensities) - min(intensities)
    min_transition = max(0.5, 0.03 * peak)
    if best_abs_deriv <= min_transition:
        return None
    new_x = _clamp(x + best_offset * normal_x, 0.0, edge_map.width - 1.0)
    new_y = _clamp(y + best_offset * normal_y, 0.0, edge_map.height - 1.0)
    return (new_x, new_y)
