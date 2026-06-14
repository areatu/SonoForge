"""Open-arc contour geometry utilities."""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from scipy.interpolate import splev, splprep

DEFAULT_NODE_COUNT = 32  # Число узлов после ресемплинга открытой дуги.

# R-key open-arc smoothing (manual/model LV after node edits).
SMOOTH_OPEN_ARC_ITERATIONS = 8
SMOOTH_OPEN_ARC_BLEND = 0.45

SIGMA_SCREEN_PX = 40.0  # Базовый радиус "кисти" в экранных пикселях для zoom-aware sigma.
SENSITIVITY_K = 0.4  # Глобальный коэффициент чувствительности смещения узлов.
MAX_DRAG_STEP_PX = 9.0  # Максимальная длина вектора смещения за один drag-шаг.
WEIGHT_ACTIVE_THRESHOLD = 0.01  # Порог веса для визуального "активен/не активен".
MIN_DELTA_NORM = 1e-4  # Минимальный шаг курсора для игнорирования микродрожания.
SIGMA_ARC_SPACING_MULT = 4.5  # Множитель sigma от среднего шага узлов (legacy/adaptive path).
SIGMA_CLOSE_SPACING_MULT = 1.5  # Sigma рядом с контуром: локальное влияние.
SIGMA_FAR_SPACING_MULT = 3.0  # Sigma вдали от контура: более широкое влияние.
SIGMA_CLOSE_BLEND_SPACING = 2.5  # Длина зоны плавного перехода close->far в единицах spacing.
CURSOR_DISTANCE_SIGMA_GAIN = 0.75  # Дополнительный рост sigma при удалении курсора.
MAX_INFLUENCE_TIER_NODES = 7  # Верхний лимит количества одновременно затрагиваемых узлов.
TIER1_MAX_SPACING_RATIO = 0.35  # До 0.35*spacing -> tier 1 (1 узел).
TIER2_MAX_SPACING_RATIO = 1.05  # До 1.05*spacing -> tier 2 (3 узла).
TIER3_MAX_SPACING_RATIO = 2.05  # До 2.05*spacing -> tier 3 (5 узлов).
TIER4_MAX_SPACING_RATIO = 2.75  # До 2.75*spacing -> tier 4 (7 узлов).
HOVER_MAX_SPACING_RATIO = 3.05  # Дальше 3.05*spacing зона считается "вне захвата".
TIER_OFFSET_WEIGHTS: dict[int, dict[int, float]] = {
    1: {0: 1.0},
    3: {0: 1.0, 1: 0.55},
    5: {0: 1.0, 1: 0.6, 2: 0.4},
    7: {0: 1.0, 1: 0.65, 2: 0.5, 3: 0.35},
}


def sigma_from_view_range(
    view_range_width: float,
    viewport_width_px: float,
    *,
    sigma_screen_px: float = SIGMA_SCREEN_PX,
) -> float:
    """Image-space Gaussian σ for a constant screen-brush radius."""
    viewport = max(float(viewport_width_px), 1.0)
    scale = float(view_range_width) / viewport
    return sigma_screen_px * scale


def gaussian_weights(
    points: Sequence[tuple[float, float]],
    cursor: tuple[float, float],
    sigma: float,
    pinned_indices: frozenset[int] = frozenset(),
) -> np.ndarray:
    """Vectorized Gaussian RBF weights from control points to cursor."""
    if not points:
        return np.array([], dtype=np.float64)

    coords = np.asarray(points, dtype=np.float64)
    cursor_xy = np.asarray(cursor, dtype=np.float64)
    diff = coords - cursor_xy
    distances_sq = np.sum(diff * diff, axis=1)

    safe_sigma = max(float(sigma), 1e-6)
    weights = np.exp(-distances_sq / (2.0 * safe_sigma * safe_sigma))

    if pinned_indices:
        for index in pinned_indices:
            if 0 <= index < len(weights):
                weights[index] = 0.0
    return weights


def open_arc_polyline_length(points: Sequence[tuple[float, float]]) -> float:
    """Total polyline length along control points."""
    if len(points) < 2:
        return 0.0
    coords = np.asarray(points, dtype=np.float64)
    segments = np.diff(coords, axis=0)
    return float(np.sum(np.linalg.norm(segments, axis=1)))


def sigma_from_arc_spacing(
    points: Sequence[tuple[float, float]],
    *,
    spacing_multiplier: float = SIGMA_ARC_SPACING_MULT,
) -> float:
    """Gaussian sigma from equal arc spacing between control points."""
    length = open_arc_polyline_length(points)
    if len(points) < 2 or length <= 0.0:
        return 0.0
    spacing = length / max(len(points) - 1, 1)
    return spacing * spacing_multiplier


def nearest_control_point_index(
    points: Sequence[tuple[float, float]],
    cursor: tuple[float, float],
    *,
    pinned_indices: frozenset[int] = frozenset(),
) -> int:
    """Index of the unpinned control point closest to the cursor."""
    if not points:
        return 0

    coords = np.asarray(points, dtype=np.float64)
    cursor_xy = np.asarray(cursor, dtype=np.float64)
    distances_sq = np.sum((coords - cursor_xy) ** 2, axis=1)
    if pinned_indices:
        for index in pinned_indices:
            if 0 <= index < len(distances_sq):
                distances_sq[index] = np.inf
    return int(np.argmin(distances_sq))


def minimum_cursor_distance(
    points: Sequence[tuple[float, float]],
    cursor: tuple[float, float],
    *,
    pinned_indices: frozenset[int] = frozenset(),
) -> float:
    """Minimum distance from cursor to any unpinned control point."""
    if not points:
        return float("inf")

    coords = np.asarray(points, dtype=np.float64)
    cursor_xy = np.asarray(cursor, dtype=np.float64)
    distances = np.linalg.norm(coords - cursor_xy, axis=1)
    if pinned_indices:
        for index in pinned_indices:
            if 0 <= index < len(distances):
                distances[index] = np.inf
    return float(np.min(distances))


def minimum_distance_to_polyline(
    points: Sequence[tuple[float, float]],
    cursor: tuple[float, float],
) -> float:
    """Minimum distance from cursor to the polyline through control points."""
    if not points:
        return float("inf")
    if len(points) == 1:
        px, py = points[0]
        return math.hypot(cursor[0] - px, cursor[1] - py)

    min_dist = float("inf")
    cursor_x, cursor_y = float(cursor[0]), float(cursor[1])
    for index in range(len(points) - 1):
        ax, ay = points[index]
        bx, by = points[index + 1]
        min_dist = min(
            min_dist,
            _point_segment_distance(cursor_x, cursor_y, ax, ay, bx, by),
        )
    return min_dist


def _point_segment_distance(
    px: float,
    py: float,
    ax: float,
    ay: float,
    bx: float,
    by: float,
) -> float:
    dx = bx - ax
    dy = by - ay
    if dx == 0.0 and dy == 0.0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    proj_x = ax + t * dx
    proj_y = ay + t * dy
    return math.hypot(px - proj_x, py - proj_y)


def expand_sigma_for_cursor_distance(
    base_sigma: float,
    cursor_distance: float,
    *,
    gain: float = CURSOR_DISTANCE_SIGMA_GAIN,
) -> float:
    """Widen influence when the cursor is far from the contour."""
    safe_sigma = max(float(base_sigma), 1e-6)
    distance = max(float(cursor_distance), 0.0)
    return safe_sigma * (1.0 + gain * distance / safe_sigma)


def arc_spacing(points: Sequence[tuple[float, float]]) -> float:
    """Average spacing between consecutive control points along the arc."""
    length = open_arc_polyline_length(points)
    if len(points) < 2 or length <= 0.0:
        return 0.0
    return length / max(len(points) - 1, 1)


def influence_tier_for_arc_distance(
    arc_distance: float,
    spacing: float,
) -> int | None:
    """Return 1, 3, 5, or 7 active nodes; None when cursor is too far from the arc."""
    if spacing <= 0.0:
        return None
    ratio = max(float(arc_distance), 0.0) / spacing
    if ratio > HOVER_MAX_SPACING_RATIO:
        return None
    if ratio <= TIER1_MAX_SPACING_RATIO:
        return 1
    if ratio <= TIER2_MAX_SPACING_RATIO:
        return 3
    if ratio <= TIER3_MAX_SPACING_RATIO:
        return 5
    if ratio <= TIER4_MAX_SPACING_RATIO:
        return 7
    return None


def tiered_influence_weights(
    points: Sequence[tuple[float, float]],
    grab_index: int,
    *,
    tier: int,
    pinned_indices: frozenset[int] = frozenset(),
) -> np.ndarray:
    """Build arc-index weights for a discrete 1/3/5/7-node influence tier."""
    count = len(points)
    weights = np.zeros(count, dtype=np.float64)
    if count == 0 or tier not in TIER_OFFSET_WEIGHTS:
        return weights

    center = max(0, min(grab_index, count - 1))
    half = (tier - 1) // 2
    profile = TIER_OFFSET_WEIGHTS[tier]
    for offset in range(-half, half + 1):
        index = center + offset
        if index < 0 or index >= count or index in pinned_indices:
            continue
        weights[index] = profile.get(abs(offset), 0.0)
    return weights


def adaptive_rbf_sigma(
    points: Sequence[tuple[float, float]],
    cursor: tuple[float, float],
    view_range_width: float,
    viewport_width_px: float,
    *,
    pinned_indices: frozenset[int] = frozenset(),
) -> float:
    """Sigma shrinks when cursor is near the arc; grows when cursor moves away."""
    length = open_arc_polyline_length(points)
    if len(points) < 2 or length <= 0.0:
        return sigma_from_view_range(view_range_width, viewport_width_px)

    spacing = length / max(len(points) - 1, 1)
    min_dist = minimum_distance_to_polyline(points, cursor)
    sigma_close = spacing * SIGMA_CLOSE_SPACING_MULT
    sigma_view = sigma_from_view_range(view_range_width, viewport_width_px)
    sigma_far = max(sigma_view, spacing * SIGMA_FAR_SPACING_MULT)

    blend_span = max(spacing * SIGMA_CLOSE_BLEND_SPACING, 1e-6)
    blend = min(1.0, min_dist / blend_span)
    sigma = sigma_close + blend * (sigma_far - sigma_close)

    if min_dist > blend_span:
        excess = min_dist - blend_span
        sigma *= 1.0 + CURSOR_DISTANCE_SIGMA_GAIN * excess / max(sigma, 1e-6)

    return max(sigma_close * 0.85, sigma)


def effective_rbf_sigma(
    points: Sequence[tuple[float, float]],
    cursor: tuple[float, float],
    view_range_width: float,
    viewport_width_px: float,
    *,
    pinned_indices: frozenset[int] = frozenset(),
) -> float:
    """Alias for adaptive_rbf_sigma."""
    return adaptive_rbf_sigma(
        points,
        cursor,
        view_range_width,
        viewport_width_px,
        pinned_indices=pinned_indices,
    )


def rbf_influence_weights(
    points: Sequence[tuple[float, float]],
    cursor: tuple[float, float],
    grab_index: int,
    view_range_width: float,
    viewport_width_px: float,
    *,
    pinned_indices: frozenset[int] = frozenset(),
) -> tuple[np.ndarray, float, int | None]:
    """Discrete 1/3/5/7-node zones along the arc; highlight matches movable nodes."""
    if not points:
        return np.array([], dtype=np.float64), float("inf"), None

    spacing = arc_spacing(points)
    if spacing <= 0.0:
        spacing = sigma_from_view_range(view_range_width, viewport_width_px)

    arc_distance = minimum_distance_to_polyline(points, cursor)
    tier = influence_tier_for_arc_distance(arc_distance, spacing)
    if tier is None:
        return np.zeros(len(points), dtype=np.float64), arc_distance, None

    count = len(points)
    index = max(0, min(grab_index, count - 1))
    weights = tiered_influence_weights(
        points,
        index,
        tier=tier,
        pinned_indices=pinned_indices,
    )
    return weights, arc_distance, tier


def apply_gaussian_displacement(
    points: Sequence[tuple[float, float]],
    delta: tuple[float, float],
    weights: np.ndarray,
    *,
    sensitivity_k: float = SENSITIVITY_K,
    max_drag_step_px: float = MAX_DRAG_STEP_PX,
) -> list[tuple[float, float]]:
    """Apply incremental cursor delta with per-point Gaussian weights."""
    if not points:
        return []

    coords = np.asarray(points, dtype=np.float64)
    delta_xy = np.asarray(delta, dtype=np.float64) * float(sensitivity_k)
    max_step = max(float(max_drag_step_px), 0.0)
    if max_step > 0.0:
        step_norm = float(np.linalg.norm(delta_xy))
        if step_norm > max_step:
            delta_xy *= max_step / step_norm
    shifted = coords + weights[:, np.newaxis] * delta_xy
    return [(float(x), float(y)) for x, y in shifted]


def apex_point(
    arc: Sequence[tuple[float, float]],
    annulus: tuple[tuple[float, float], tuple[float, float]],
) -> tuple[float, float]:
    """Return the point on the arc farthest from the annulus line."""
    if not arc:
        raise ValueError("arc must contain at least one point")

    start, end = annulus
    return max(
        arc,
        key=lambda point: point_line_distance(point, start, end),
    )


def apex_index_on_open_arc(
    points: Sequence[tuple[float, float]],
    annulus: tuple[tuple[float, float], tuple[float, float]],
) -> int:
    """Index of the interior node farthest from the mitral annulus chord."""
    if len(points) < 3:
        return max(0, len(points) // 2)
    septal, lateral = annulus
    return max(
        range(1, len(points) - 1),
        key=lambda index: point_line_distance(points[index], septal, lateral),
    )


def pin_open_arc_landmarks(
    points: list[tuple[float, float]],
    *,
    septal: tuple[float, float],
    lateral: tuple[float, float],
    apex: tuple[float, float] | None = None,
    pin_apex: bool = False,
) -> list[tuple[float, float]]:
    """Force MA endpoints onto resampled open-arc nodes; apex pin is opt-in."""
    if len(points) < 3:
        return points
    pinned = list(points)
    pinned[0] = septal
    pinned[-1] = lateral
    if not pin_apex:
        return pinned
    apex_xy = apex if apex is not None else apex_point(pinned, (septal, lateral))
    if apex is not None:
        apex_index = _closest_interior_index(pinned, apex_xy)
    else:
        apex_index = apex_index_on_open_arc(pinned, (septal, lateral))
    pinned[apex_index] = apex_xy
    return pinned


def mitral_apex_param(
    apex: tuple[float, float],
    septal: tuple[float, float],
    lateral: tuple[float, float],
) -> float:
    """Return u ∈ [0,1] of apex projection onto the mitral annulus chord."""
    ma_dx = lateral[0] - septal[0]
    ma_dy = lateral[1] - septal[1]
    ma_length_sq = ma_dx * ma_dx + ma_dy * ma_dy
    if ma_length_sq <= 0.0:
        return 0.5
    t = ((apex[0] - septal[0]) * ma_dx + (apex[1] - septal[1]) * ma_dy) / ma_length_sq
    return max(0.0, min(1.0, t))


def _closest_interior_index(
    points: Sequence[tuple[float, float]],
    target: tuple[float, float],
) -> int:
    """Index of the interior node closest to target (excludes endpoints)."""
    if len(points) < 3:
        return max(0, len(points) // 2)
    return min(
        range(1, len(points) - 1),
        key=lambda index: (points[index][0] - target[0]) ** 2
        + (points[index][1] - target[1]) ** 2,
    )


def resample_open_arc_landmarks(
    points: list[tuple[float, float]],
    *,
    septal: tuple[float, float],
    lateral: tuple[float, float],
    apex: tuple[float, float],
    num_nodes: int = DEFAULT_NODE_COUNT,
    u_apex: float | None = None,
) -> list[tuple[float, float]]:
    """Uniform arc-length resample; only MA endpoints are pinned."""
    del apex, u_apex
    if num_nodes < 3:
        return pin_open_arc_landmarks(
            list(points),
            septal=septal,
            lateral=lateral,
        )

    if len(points) >= max(num_nodes, 8):
        resampled = _resample_polyline(list(points), num_nodes=num_nodes)
    else:
        resampled = resample_open_arc(list(points), num_nodes=num_nodes)

    resampled[0] = septal
    resampled[-1] = lateral
    return resampled


def smooth_open_arc(
    points: Sequence[tuple[float, float]],
    annulus: tuple[tuple[float, float], tuple[float, float]],
    *,
    apex: tuple[float, float] | None = None,
    iterations: int = SMOOTH_OPEN_ARC_ITERATIONS,
    blend: float = SMOOTH_OPEN_ARC_BLEND,
) -> list[tuple[float, float]]:
    """Laplacian smooth interior nodes; MA endpoints stay fixed."""
    if len(points) < 3:
        return [(float(x), float(y)) for x, y in points]

    septal, lateral = annulus
    coords = [[float(x), float(y)] for x, y in points]
    coords[0] = [float(septal[0]), float(septal[1])]
    coords[-1] = [float(lateral[0]), float(lateral[1])]
    pinned = {0, len(coords) - 1}

    for _ in range(max(int(iterations), 1)):
        next_coords = [point[:] for point in coords]
        for index in range(1, len(coords) - 1):
            if index in pinned:
                continue
            neighbor_x = 0.5 * (coords[index - 1][0] + coords[index + 1][0])
            neighbor_y = 0.5 * (coords[index - 1][1] + coords[index + 1][1])
            next_coords[index][0] = (1.0 - blend) * coords[index][0] + blend * neighbor_x
            next_coords[index][1] = (1.0 - blend) * coords[index][1] + blend * neighbor_y
        next_coords[0] = [float(septal[0]), float(septal[1])]
        next_coords[-1] = [float(lateral[0]), float(lateral[1])]
        coords = next_coords

    return [(point[0], point[1]) for point in coords]


def long_axis_endpoints(
    arc: Sequence[tuple[float, float]],
    annulus: tuple[tuple[float, float], tuple[float, float]],
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Base-to-tip long axis endpoints defined by annulus midpoint and apex."""
    base_start, base_end = annulus
    base = (
        (base_start[0] + base_end[0]) / 2.0,
        (base_start[1] + base_end[1]) / 2.0,
    )
    return base, apex_point(arc, annulus)


def resample_open_arc(
    points: list[tuple[float, float]],
    *,
    num_nodes: int = DEFAULT_NODE_COUNT,
) -> list[tuple[float, float]]:
    """Resample open arc to num_nodes with equal arc-length spacing; endpoints fixed."""
    if num_nodes <= 0:
        return []
    if not points:
        return []
    if len(points) == 1:
        return [points[0]] * num_nodes
    if len(points) == 2:
        return _resample_polyline(points, num_nodes=num_nodes)

    dense = sample_spline(points, num_samples=max(num_nodes * 8, 64))
    return _resample_polyline(dense, num_nodes=num_nodes)


def move_node_and_resample(
    points: list[tuple[float, float]],
    *,
    node_index: int,
    x: float,
    y: float,
    num_nodes: int = DEFAULT_NODE_COUNT,
) -> list[tuple[float, float]]:
    """Move one control node, fit spline, return equal-spaced resample."""
    if not points:
        return []
    updated = list(points)
    if node_index < 0 or node_index >= len(updated):
        return resample_open_arc(updated, num_nodes=num_nodes)
    updated[node_index] = (float(x), float(y))
    return resample_open_arc(updated, num_nodes=num_nodes)


def sample_spline(
    points: list[tuple[float, float]],
    *,
    num_samples: int = 100,
) -> list[tuple[float, float]]:
    """Evaluate cubic B-spline through control points (open curve)."""
    if len(points) < 2:
        return list(points)
    if len(points) == 2:
        return _resample_polyline(points, num_nodes=num_samples)

    coords = np.asarray(points, dtype=np.float64).T
    tck, _ = splprep(coords, s=0.0, k=min(3, len(points) - 1))
    u = np.linspace(0.0, 1.0, num_samples)
    x, y = splev(u, tck)
    return [(float(xi), float(yi)) for xi, yi in zip(x, y, strict=True)]


def _resample_polyline(
    points: list[tuple[float, float]],
    *,
    num_nodes: int,
) -> list[tuple[float, float]]:
    if num_nodes <= 0:
        return []
    if len(points) == 1:
        return [points[0]] * num_nodes

    segments = np.diff(np.asarray(points, dtype=np.float64), axis=0)
    seg_lens = np.linalg.norm(segments, axis=1)
    cumulative = np.concatenate([[0.0], np.cumsum(seg_lens)])
    total = cumulative[-1]
    if total == 0.0:
        return [points[0]] * num_nodes

    targets = np.linspace(0.0, total, num_nodes)
    result: list[tuple[float, float]] = []
    for target in targets:
        idx = int(np.searchsorted(cumulative, target, side="right") - 1)
        idx = min(idx, len(points) - 2)
        start_len = cumulative[idx]
        end_len = cumulative[idx + 1]
        if end_len > start_len:
            alpha = (target - start_len) / (end_len - start_len)
        else:
            alpha = 0.0
        start = np.asarray(points[idx], dtype=np.float64)
        end = np.asarray(points[idx + 1], dtype=np.float64)
        pt = start + alpha * (end - start)
        result.append((float(pt[0]), float(pt[1])))
    return result


def point_line_distance(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    x0, y0 = point
    x1, y1 = start
    x2, y2 = end
    dx = x2 - x1
    dy = y2 - y1
    if dx == 0.0 and dy == 0.0:
        return math.hypot(x0 - x1, y0 - y1)

    numerator = abs(dy * x0 - dx * y0 + x2 * y1 - y2 * x1)
    denominator = math.hypot(dx, dy)
    return numerator / denominator


def polygon_area_mm2(
    polygon_points: Sequence[tuple[float, float]],
    pixel_spacing: tuple[float, float],
) -> float:
    """Shoelace area of a closed polygon in mm² (pixel coords: col, row)."""
    if len(polygon_points) < 3:
        return 0.0

    row_spacing, col_spacing = pixel_spacing
    mm_points = [
        (float(col) * col_spacing, float(row) * row_spacing)
        for col, row in polygon_points
    ]
    area = 0.0
    for index, (x1, y1) in enumerate(mm_points):
        x2, y2 = mm_points[(index + 1) % len(mm_points)]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0
