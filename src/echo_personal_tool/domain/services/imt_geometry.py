"""IMT along local normals in millimetres, not vertical pixel gaps (#558)."""

from __future__ import annotations

import numpy as np
from scipy.ndimage import map_coordinates

from echo_personal_tool.domain.models.imt import Boundary, ImtDraft, ImtPolicy, ImtRefusal, ImtSource
from echo_personal_tool.domain.models.imt_region import contains_points, region_axes


def _boundary(points: Boundary, source: ImtSource) -> np.ndarray:
    try:
        values = np.asarray(points, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ImtRefusal("invalid_boundary") from exc
    if values.ndim != 2 or values.shape[1] != 2 or not 3 <= len(values) <= 1024:
        raise ImtRefusal("invalid_boundary")
    if not np.isfinite(values).all() or np.any(np.diff(values[:, 0]) <= 0):
        raise ImtRefusal("boundary_must_be_finite_x_monotone")
    x0, y0, x1, y1 = source.roi
    if np.any(values < [x0, y0]) or np.any(values >= [x1, y1]) or not contains_points(source.roi_polygon, values):
        raise ImtRefusal("boundary_outside_roi")
    return values


def _cross(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.asarray(a[..., 0] * b[..., 1] - a[..., 1] * b[..., 0])


def _normal_hit(point: np.ndarray, normal: np.ndarray, wall: np.ndarray) -> tuple[float, np.ndarray] | None:
    """Unique forward ray/polyline hit; reject ambiguous geometry, not just pick nearest."""
    segments = np.diff(wall, axis=0)
    delta = wall[:-1] - point
    denominator = _cross(normal, segments)
    safe = np.abs(denominator) > 1e-12
    t = np.divide(_cross(delta, segments), denominator, out=np.full(len(segments), np.nan), where=safe)
    u = np.divide(_cross(delta, normal), denominator, out=np.full(len(segments), np.nan), where=safe)
    valid = (t > 0) & (u >= -1e-9) & (u <= 1 + 1e-9)
    # A polyline vertex belongs to two neighbouring segments, but is one hit.
    hits = np.unique(np.round(t[valid], 9))
    if len(hits) != 1:
        return None
    distance = float(hits[0])
    return distance, point + distance * normal


def measure_boundaries(
    source: ImtSource,
    policy: ImtPolicy,
    lumen_intima: Boundary,
    media_adventitia: Boundary,
    edge_strength: np.ndarray,
    *,
    revision: int = 0,
) -> ImtDraft:
    """Recompute after every edit, with the same geometry and image QC gates.

    edge_strength is the ROI-sized normalised positive axial gradient, supplied
    by the imaging adapter. Invalid/weak/shadowed normals are excluded; their
    absence remains visible in coverage. No partial mean below minimum coverage.
    """
    li, ma = _boundary(lumen_intima, source), _boundary(media_adventitia, source)
    x0, y0, x1, y1 = source.roi
    edge = np.asarray(edge_strength, dtype=float)
    if edge.shape != (y1 - y0, x1 - x0) or not np.isfinite(edge).all() or np.any(edge < 0):
        raise ImtRefusal("invalid_edge_evidence")
    # Compare longitudinal span/order in the selected rectangle's axes.
    # Rotated end caps are not vertical lines in source coordinates.
    local_li, local_ma = li, ma
    if source.roi_polygon:
        origin, u, v, _, _ = region_axes(source.roi_polygon)
        axes = np.column_stack((u, v))
        local_li, local_ma = (li - origin) @ axes, (ma - origin) @ axes
    if not np.allclose(local_li[[0, -1], 0], local_ma[[0, -1], 0], rtol=0, atol=1e-6):
        raise ImtRefusal("boundary_span_mismatch")
    if np.any(np.diff(local_li[:, 0]) <= 0) or np.any(np.diff(local_ma[:, 0]) <= 0):
        raise ImtRefusal("boundary_must_be_finite_x_monotone")
    nodes = np.unique(np.concatenate((local_li[:, 0], local_ma[:, 0])))
    if np.any(np.interp(nodes, local_ma[:, 0], local_ma[:, 1]) <= np.interp(nodes, local_li[:, 0], local_li[:, 1])):
        raise ImtRefusal("boundaries_cross_or_reversed")
    row, col = source.calibration.spacing
    scale = np.array([col, row], dtype=float)
    physical_li, physical_ma = li * scale, ma * scale
    arc = np.concatenate(([0.0], np.cumsum(np.linalg.norm(np.diff(physical_li, axis=0), axis=1))))
    count = min(1024, max(8, int(np.ceil(arc[-1] / min(row, col))) + 1))
    positions = np.linspace(0, arc[-1], count)
    base = np.column_stack([np.interp(positions, arc, physical_li[:, axis]) for axis in (0, 1)])
    tangent = np.gradient(base, axis=0)
    normals = np.column_stack((-tangent[:, 1], tangent[:, 0]))
    normals /= np.linalg.norm(normals, axis=1)[:, None]
    accepted: list[float] = []
    accepted_indices: list[int] = []
    for sample_index, (point, normal) in enumerate(zip(base, normals, strict=True)):
        hit = _normal_hit(point, normal, physical_ma)
        if hit is None:
            continue
        distance, endpoint = hit
        if not policy.min_thickness_mm <= distance <= policy.max_thickness_mm:
            continue
        if distance < policy.min_axial_samples * float(np.linalg.norm(normal * scale)):
            continue
        pixels = np.stack((point / scale, endpoint / scale)) - [x0, y0]
        strengths = map_coordinates(edge, [pixels[:, 1], pixels[:, 0]], order=1, mode="constant", cval=0.0)
        if float(np.min(strengths)) < policy.min_edge_contrast:
            continue
        accepted.append(distance)
        accepted_indices.append(sample_index)
    if not accepted or len(accepted) / count < policy.min_coverage:
        raise ImtRefusal("insufficient_quality_coverage")
    distances = np.asarray(accepted)
    return ImtDraft(
        source=source,
        policy=policy,
        lumen_intima=tuple(map(tuple, li.tolist())),
        media_adventitia=tuple(map(tuple, ma.tolist())),
        distances_mm=tuple(accepted),
        attempted_samples=count,
        accepted_sample_indices=tuple(accepted_indices),
        sampled_length_mm=float(arc[-1]),
        mean_mm=float(np.mean(distances)),
        max_mm=float(np.max(distances)),
        sd_mm=float(np.std(distances)),
        revision=revision,
    )
