"""Bounded seeded far-wall search on an operator-selected B-mode ROI (#558).

Research prototype: two positive axial edges in separate seed corridors, not
vessel recognition. First-order dynamic programming penalises slope and limits
per-column jumps. Plaques, rotated/vertical walls and automatic frame selection
are deliberately outside this detector's scope.
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import gaussian_filter
from scipy.signal import find_peaks

from echo_personal_tool.domain.models.imt import Boundary, ImtPolicy, ImtRefusal, ImtSource

BoundaryHint = float | tuple[float, float]


def edge_evidence(image: np.ndarray, source: ImtSource) -> np.ndarray:
    """Read only the bounded crop; reject colour, non-finite and flat images."""
    pixels = np.asarray(image)
    x0, y0, x1, y1 = source.roi
    if pixels.ndim != 2 or pixels.shape[0] < y1 or pixels.shape[1] < x1:
        raise ImtRefusal("grayscale_frame_and_valid_roi_required")
    if pixels.dtype.kind not in "uif":
        raise ImtRefusal("unsupported_pixels")
    crop = np.array(pixels[y0:y1, x0:x1], dtype=float, copy=True)
    if not np.isfinite(crop).all():
        raise ImtRefusal("nonfinite_pixels")
    low, high = np.percentile(crop, [1, 99])
    if high - low <= np.finfo(float).eps * max(1.0, abs(float(high))):
        raise ImtRefusal("flat_roi")
    normalised = np.clip((crop - low) / (high - low), 0.0, 1.0)
    # Technical denoising parameter, not a clinical wall/IMT cutoff.
    return np.asarray(np.maximum(np.gradient(gaussian_filter(normalised, sigma=0.8), axis=0), 0.0))


def _trace(edge: np.ndarray, lower: np.ndarray, upper: np.ndarray, policy: ImtPolicy) -> np.ndarray:
    height, width = edge.shape
    rows = np.arange(height)
    allowed = (rows[:, None] >= np.maximum(1, lower)) & (rows[:, None] <= np.minimum(height - 2, upper))
    if not allowed.any(axis=0).all():
        raise ImtRefusal("seed_corridor_outside_roi")
    cost = np.where(allowed[:, 0], -edge[:, 0], np.inf)
    back = np.zeros((width, height), dtype=np.int16)
    offsets = np.arange(-policy.max_step_px, policy.max_step_px + 1)
    rows = np.arange(height)
    for column in range(1, width):
        candidates = []
        for delta in offsets:
            predecessor = rows - delta
            valid = (predecessor >= 0) & (predecessor < height)
            candidate = cost[np.clip(predecessor, 0, height - 1)] + policy.smoothness_penalty * delta * delta
            candidates.append(np.where(valid, candidate, np.inf))
        table = np.stack(candidates)
        selected = np.argmin(table, axis=0)
        back[column] = rows - offsets[selected]
        cost = np.where(allowed[:, column], np.min(table, axis=0) - edge[:, column], np.inf)
    if not np.isfinite(cost).any():
        raise ImtRefusal("no_continuous_boundary")
    path = np.zeros(width, dtype=int)
    path[-1] = int(np.argmin(cost))
    for column in range(width - 1, 0, -1):
        path[column - 1] = back[column, path[column]]
    refined = path.astype(float)
    for column, row in enumerate(path):
        a, b, c = edge[row - 1 : row + 2, column]
        denominator = a - 2 * b + c
        if denominator < -1e-12:
            refined[column] += np.clip(0.5 * (a - c) / denominator, -0.5, 0.5)
    return refined


def _guide(hint: BoundaryHint, width: int) -> np.ndarray:
    values = np.asarray(hint, dtype=float)
    if values.ndim == 0:
        return np.full(width, float(values))
    if values.shape != (2,):
        raise ImtRefusal("invalid_boundary_hints")
    return np.linspace(float(values[0]), float(values[1]), width)


def detect_boundaries(
    evidence: np.ndarray, source: ImtSource, policy: ImtPolicy, *, lumen_y: BoundaryHint, adventitia_y: BoundaryHint
) -> tuple[Boundary, Boundary]:
    """Hints are full-frame y or (left y, right y) for an inclined wall."""
    x0, y0, x1, y1 = source.roi
    if evidence.shape != (y1 - y0, x1 - x0) or not np.isfinite(evidence).all():
        raise ImtRefusal("invalid_edge_evidence")
    li, ma = _guide(lumen_y, x1 - x0), _guide(adventitia_y, x1 - x0)
    if not np.isfinite([li, ma]).all() or np.any(li < y0 + 1) or np.any(ma >= y1 - 1) or np.any(li >= ma):
        raise ImtRefusal("invalid_boundary_hints")
    li, ma = li - y0, ma - y0
    middle = (li + ma) / 2
    radius = policy.search_radius_px
    first = _trace(evidence, np.floor(li - radius), np.floor(np.minimum(li + radius, middle)), policy)
    second = _trace(evidence, np.ceil(np.maximum(ma - radius, middle)), np.ceil(ma + radius), policy)
    xs = np.arange(x0, x1, dtype=float)
    return (
        tuple((float(x), float(y + y0)) for x, y in zip(xs, first, strict=True)),
        tuple((float(x), float(y + y0)) for x, y in zip(xs, second, strict=True)),
    )


def automatic_hints(evidence: np.ndarray, source: ImtSource, policy: ImtPolicy) -> tuple[float, float]:
    """Seed the two strongest compatible positive edges inside a selected wall ROI.

    This is not vessel/plaque recognition. Existing tracing and normal-distance
    QC remain authoritative and may refuse the proposed pair.
    """
    profile = np.mean(evidence, axis=1)
    peaks, _ = find_peaks(profile, height=policy.min_edge_contrast)
    row_mm = source.calibration.spacing[0]
    candidates = [
        (float(profile[a] + profile[b]), int(a), int(b))
        for a in peaks
        for b in peaks
        if a < b
        and max(policy.min_thickness_mm, policy.min_axial_samples * row_mm)
        <= (b - a) * row_mm
        <= policy.max_thickness_mm
    ]
    if not candidates:
        raise ImtRefusal("two_wall_edges_not_found")
    _, first, second = max(candidates)
    return float(source.roi[1] + first), float(source.roi[1] + second)
