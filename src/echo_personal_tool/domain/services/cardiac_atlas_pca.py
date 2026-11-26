"""Deterministic local-only atlas refinement and annotation correspondence.

No file access. Missing chambers are masked, not labelled as average anatomy.
Training data must have reviewed open-arc node order and an explicit phase.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

import numpy as np

from echo_personal_tool.domain.services.cardiac_atlas import CoupledShapeModel
from echo_personal_tool.domain.services.cardiac_atlas_geometry import CanonicalFrame, points_array, resample_arc


@dataclass(frozen=True)
class AtlasObservation:
    phase: str
    points: np.ndarray


def align_local_contours(
    model: CoupledShapeModel,
    contours: Mapping[str, object],
    *,
    reference_chamber: str,
    septal: tuple[float, float],
    lateral: tuple[float, float],
    apex: tuple[float, float],
    phase: str,
    pixel_spacing_mm: tuple[float, float] | None = None,
) -> AtlasObservation:
    """Align all chambers by ONE reference frame (never independently Procrustes each).

    Calibrated records preserve mm sizes; uncalibrated records are scaled by
    reference annulus span and only refine normalized shape, not clinical size.
    Shared-node observations from two contours must agree within 3 mm.
    """
    key = reference_chamber.upper()
    if phase.upper() not in {"ED", "ES"} or key not in model.structures or key in model.closed_structures:
        raise ValueError("an explicit ED/ES phase and an open reference chamber are required")
    source = CanonicalFrame.from_landmarks(septal, lateral, apex, pixel_spacing_mm=pixel_spacing_mm)
    base = model.mean(phase)
    ref_ids = model.structures[key]
    ref_points = base[[ref_ids[0], ref_ids[-1], model.landmarks[f"{key}_apex"]]]
    target = CanonicalFrame.from_landmarks(
        tuple(ref_points[0]), tuple(ref_points[1]), tuple(ref_points[2]), pixel_spacing_mm=(1, 1)
    )
    scale = 1.0 if pixel_spacing_mm is not None else float(np.linalg.norm(ref_points[1] - ref_points[0]))
    result = np.full_like(base, np.nan)
    totals = np.zeros(len(base))
    sums = np.zeros_like(base)
    for name, raw in contours.items():
        if name not in model.structures or name == "IVS":
            raise ValueError(f"unknown/unsupported training structure: {name}")
        ids = model.structures[name]
        aligned = target.atlas_to_image(source.image_to_atlas(points_array(raw)) * scale)
        if name not in model.closed_structures and np.linalg.norm(aligned[0] - aligned[-1]) < 1e-6:
            raise ValueError("open chamber arcs must not repeat the basal closing chord")
        if len(aligned) == len(ids):
            sampled = aligned
        elif name in model.closed_structures:
            sampled = resample_arc(aligned, len(ids), closed=True)
        else:
            # Closed polygons / swapped endpoints are not silently accepted as open arcs.
            if np.linalg.norm(aligned[0] - aligned[-1]) < 1e-6:
                raise ValueError("open chamber arcs must not repeat the basal closing chord")
            sampled = resample_arc(aligned, len(ids))
        for i, point in zip(ids, sampled):
            if totals[i] and np.linalg.norm(sums[i] / totals[i] - point) > 3.0:
                raise ValueError("inconsistent shared valve/septum annotation")
            sums[i] += point
            totals[i] += 1
    valid = totals > 0
    if not valid.any():
        raise ValueError("no observed atlas nodes")
    result[valid] = sums[valid] / totals[valid, None]
    return AtlasObservation(phase.upper(), result)


def fit_atlas_pca(
    model: CoupledShapeModel,
    observations: Sequence[AtlasObservation],
    *,
    max_modes: int = 8,
    iterations: int = 12,
) -> CoupledShapeModel:
    """Masked PCA with deterministic EM completion and per-phase mean updates.

    Mean/mode candidates are topology-constrained at synthesis time. When a
    node was never observed its mean stays analytic and learned modes are zero
    there. Fewer than two records are rejected, not called a statistical atlas.
    """
    if len(observations) < 2 or not 1 <= max_modes <= 32 or not 1 <= iterations <= 100:
        raise ValueError("PCA requires >=2 observations, 1..32 modes and 1..100 iterations")
    arrays: list[np.ndarray] = []
    phases: list[str] = []
    for sample in observations:
        arr = np.asarray(sample.points, dtype=np.float64)
        if arr.shape != model.mean_ed.shape or np.isinf(arr).any() or sample.phase not in {"ED", "ES"}:
            raise ValueError("invalid atlas observation")
        if not np.array_equal(np.isfinite(arr[:, 0]), np.isfinite(arr[:, 1])):
            raise ValueError("missing nodes must mask both coordinates")
        if not np.isfinite(arr).any():
            raise ValueError("empty atlas observation")
        arrays.append(arr)
        phases.append(sample.phase)
    stack = np.stack(arrays)
    observed = np.isfinite(stack)
    means = {"ED": model.mean_ed.copy(), "ES": model.mean_es.copy()}
    for phase in ("ED", "ES"):
        indices = [i for i, value in enumerate(phases) if value == phase]
        if not indices:
            continue
        count = observed[indices].sum(axis=0)
        sums = np.where(observed[indices], stack[indices], 0).sum(axis=0)
        candidate = means[phase].copy()
        np.divide(sums, count, out=candidate, where=count > 0)
        means[phase] = model.constrain(candidate, phase=phase)
    bases = np.stack([means[phase] for phase in phases])
    residual = (stack - bases).reshape(len(stack), -1)
    mask = observed.reshape(len(stack), -1)
    filled = np.where(mask, residual, 0.0)
    k = min(max_modes, len(stack) - 1, filled.shape[1])
    for _ in range(iterations):
        u, singular, vt = np.linalg.svd(filled, full_matrices=False)
        reconstruction = (u[:, :k] * singular[:k]) @ vt[:k]
        filled = np.where(mask, residual, reconstruction)
    _, singular, vt = np.linalg.svd(filled, full_matrices=False)
    # Remove arbitrary SVD sign so JSON is stable across repeat runs/toolchains.
    components = vt[:k].copy()
    for row in components:
        pivot = int(np.argmax(np.abs(row)))
        if row[pivot] < 0:
            row *= -1
    components[:, ~mask.any(axis=0)] = 0
    variances = singular[:k] ** 2 / (len(stack) - 1)
    if not np.any(variances > 1e-12):
        return replace(
            model, mean_ed=means["ED"], mean_es=means["ES"], provenance="local_pca_zero_variance_unvalidated"
        )
    return replace(
        model,
        mean_ed=means["ED"],
        mean_es=means["ES"],
        modes=components.reshape(k, -1, 2),
        eigenvalues=variances,
        mode_names=tuple(f"local_pc_{i + 1}" for i in range(k)),
        provenance="local_masked_pca_unvalidated",
    )
