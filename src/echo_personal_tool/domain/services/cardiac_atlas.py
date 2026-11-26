"""Coupled cardiac shape/appearance priors (ML.1, issue #689).

Analytic seeds are NOT population norms or clinically validated segmentation.
A single node table owns shared valves/septum: a PCA displacement cannot tear
an interface into two independent copies. Defaults in existing services stay
unchanged; atlas use is explicit. No Qt, torch, ONNX runtime or external data.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

import numpy as np

from echo_personal_tool.domain.services.cardiac_atlas_geometry import (
    CanonicalFrame,
    edges_cross,
    points_array,
    polygon_interior,
    resample_arc,
)
from echo_personal_tool.domain.services.cardiac_atlas_templates import (
    ATLAS_VIEWS as ATLAS_VIEWS,
)
from echo_personal_tool.domain.services.cardiac_atlas_templates import (
    analytic_atlas_seed,
)

ATLAS_SCHEMA_VERSION = 1


def phase_weight(phase: str | float) -> float:
    """ED=0, ES=0.38 of a cycle; smooth periodic interpolation (atria anti-phase)."""
    if isinstance(phase, str):
        if phase.upper() not in {"ED", "ES"}:
            raise ValueError("phase must be ED, ES or a finite cycle fraction")
        return 0.0 if phase.upper() == "ED" else 1.0
    if not np.isfinite(phase):
        raise ValueError("non-finite cardiac phase")
    phi = float(phase) % 1.0
    t = phi / 0.38 if phi <= 0.38 else (1.0 - phi) / 0.62
    return float(0.5 - 0.5 * np.cos(np.pi * t))


@dataclass(frozen=True)
class CoupledShapeModel:
    """All structures index one N×2 mesh; modes are K×N×2 in millimetres.

    Open chamber arcs are septal→apex/roof→lateral; their closing chord is
    anatomical valve plane, not an inferred wall. IVS is an open interface.
    """

    view: str
    structures: Mapping[str, tuple[int, ...]]
    landmarks: Mapping[str, int]
    mean_ed: np.ndarray
    mean_es: np.ndarray
    modes: np.ndarray
    eigenvalues: np.ndarray
    mode_names: tuple[str, ...]
    closed_structures: tuple[str, ...] = ()
    provenance: str = "analytic_seed_unvalidated"

    def __post_init__(self) -> None:
        if self.view not in ATLAS_VIEWS:
            raise ValueError("unsupported atlas view")
        ed, es = points_array(self.mean_ed).copy(), points_array(self.mean_es).copy()
        modes = np.asarray(self.modes, dtype=np.float64).copy()
        variances = np.asarray(self.eigenvalues, dtype=np.float64).copy()
        if variances.ndim != 1 or not len(variances):
            raise ValueError("atlas needs a nonempty eigenvalue vector")
        if ed.shape != es.shape or modes.shape != (len(variances), len(ed), 2):
            raise ValueError("inconsistent atlas/mode dimensions")
        if variances.ndim != 1 or len(self.mode_names) != len(variances):
            raise ValueError("inconsistent mode metadata")
        if not np.isfinite(modes).all() or not np.isfinite(variances).all() or np.any(variances < 0):
            raise ValueError("invalid atlas modes/eigenvalues")
        structures = {str(k): tuple(v) for k, v in self.structures.items()}
        landmarks = dict(self.landmarks)
        if "LV" not in structures or any(name not in structures for name in self.closed_structures):
            raise ValueError("missing core structure or unknown closed structure")
        for indices in structures.values():
            if len(indices) < 2 or len(set(indices)) != len(indices):
                raise ValueError("invalid/repeated topology indices")
            if any(type(i) is not int or i < 0 or i >= len(ed) for i in indices):
                raise ValueError("invalid topology indices")
        if any(type(i) is not int or i < 0 or i >= len(ed) for i in landmarks.values()):
            raise ValueError("invalid landmark index")
        if "LA" in structures and (structures["LV"][0], structures["LV"][-1]) != (
            structures["LA"][0],
            structures["LA"][-1],
        ):
            raise ValueError("LV and LA must share the MV chord node identities")
        for chamber in structures:
            if chamber not in self.closed_structures and chamber != "IVS":
                if landmarks.get(f"{chamber}_apex") not in structures[chamber]:
                    raise ValueError("missing chamber apex/roof landmark")
        object.__setattr__(self, "structures", MappingProxyType(structures))
        object.__setattr__(self, "landmarks", MappingProxyType(landmarks))
        for name, value in (("mean_ed", ed), ("mean_es", es), ("modes", modes), ("eigenvalues", variances)):
            value.setflags(write=False)
            object.__setattr__(self, name, value)
        if self.violations(ed) or self.violations(es):
            raise ValueError("invalid mean topology")

    def mean(self, phase: str | float = "ED") -> np.ndarray:
        weight = phase_weight(phase)
        return np.asarray((1 - weight) * self.mean_ed + weight * self.mean_es, dtype=np.float64)

    def violations(self, points: object) -> tuple[str, ...]:
        arr = points_array(points)
        if arr.shape != self.mean_ed.shape:
            raise ValueError("shape does not match atlas")
        chambers = {name: arr[list(ids)] for name, ids in self.structures.items() if name != "IVS"}
        problems: list[str] = []
        for name, poly in chambers.items():
            area = abs(float(np.sum(poly[:, 0] * np.roll(poly[:, 1], -1) - poly[:, 1] * np.roll(poly[:, 0], -1)))) / 2
            if area < 1e-6 or edges_cross(poly, poly, same=True):
                problems.append(f"{name}: degenerate/self-intersecting")
        names = list(chambers)
        for i, name in enumerate(names):
            a = chambers[name]
            for other in names[i + 1 :]:
                b = chambers[other]
                centres = np.vstack([a.mean(axis=0), b.mean(axis=0)])
                contained_centres = polygon_interior(centres, a) & polygon_interior(centres, b)
                if (
                    edges_cross(a, b)
                    or polygon_interior(a, b).any()
                    or polygon_interior(b, a).any()
                    or contained_centres.any()
                ):
                    problems.append(f"{name}/{other}: overlapping cavities")
        return tuple(problems)

    def constrain(self, candidate: object, *, phase: str | float = "ED") -> np.ndarray:
        """Backtrack towards the mean if a deformation breaks chamber topology."""
        arr = points_array(candidate)
        base = self.mean(phase)
        if arr.shape != base.shape:
            raise ValueError("shape does not match atlas")
        if self.violations(base):
            raise ValueError("interpolated mean has invalid topology")
        for _ in range(18):
            if not self.violations(arr):
                return arr.copy()
            arr = (arr + base) / 2
        return base

    def synthesize(self, coefficients: Sequence[float] = (), *, phase: str | float = "ED") -> np.ndarray:
        coeff = np.zeros(len(self.eigenvalues), dtype=np.float64)
        supplied = np.asarray(coefficients, dtype=np.float64)
        if supplied.ndim != 1 or len(supplied) > len(coeff) or not np.isfinite(supplied).all():
            raise ValueError("invalid shape coefficients")
        coeff[: len(supplied)] = supplied
        limits = 3.0 * np.sqrt(self.eigenvalues)
        coeff = np.clip(coeff, -limits, limits)
        proposed = self.mean(phase) + np.einsum("k,knd->nd", coeff, self.modes)
        return self.constrain(proposed, phase=phase)

    def fit(
        self,
        observations: object,
        *,
        weights: Sequence[float] | None = None,
        phase: str | float = "ED",
        ridge: float = 1.0,
    ) -> ShapeFit:
        """Weighted ridge fit. Zero-weight/NaN nodes are missing, not zero pixels.

        Coefficients are bounded to ±3σ and topology is checked after fitting.
        Entirely missing walls therefore retain the coupled smooth prior.
        """
        observed = np.asarray(observations, dtype=np.float64)
        base = self.mean(phase)
        if observed.shape != base.shape or not np.isfinite(ridge) or ridge <= 0:
            raise ValueError("invalid observations or ridge")
        w = np.ones(len(base)) if weights is None else np.asarray(weights, dtype=np.float64)
        if w.shape != (len(base),) or not np.isfinite(w).all() or np.any(w < 0):
            raise ValueError("invalid node weights")
        valid = np.isfinite(observed).all(axis=1) & (w > 0)
        design = self.modes[:, valid, :].reshape(len(self.eigenvalues), -1).T
        residual = (observed[valid] - base[valid]).ravel()
        root_weights = np.repeat(np.sqrt(w[valid]), 2)
        a, y = design * root_weights[:, None], residual * root_weights
        penalty = ridge / np.maximum(self.eigenvalues, 1e-12)
        coeff = np.linalg.solve(a.T @ a + np.diag(penalty), a.T @ y)
        coeff = np.clip(coeff, -3 * np.sqrt(self.eigenvalues), 3 * np.sqrt(self.eigenvalues))
        raw = base + np.einsum("k,knd->nd", coeff, self.modes)
        fitted = self.constrain(raw, phase=phase)
        # Constrain backtracks on the same ray; report coefficients of the actual result.
        delta = raw - base
        denom = float(np.sum(delta * delta))
        if denom > 1e-20:
            coeff *= float(np.sum((fitted - base) * delta)) / denom
        rms = (
            float(np.sqrt(np.average(np.sum((fitted[valid] - observed[valid]) ** 2, axis=1), weights=w[valid])))
            if valid.any()
            else 0.0
        )
        return ShapeFit(fitted, coeff, rms, int(valid.sum()))

    def to_dict(self) -> dict[str, Any]:
        """JSON-compatible numeric artifact. Contains no paths, identifiers or images."""
        return {
            "schema_version": ATLAS_SCHEMA_VERSION,
            "units": "mm",
            "view": self.view,
            "structures": {k: list(v) for k, v in self.structures.items()},
            "landmarks": dict(self.landmarks),
            "mean_ed": self.mean_ed.tolist(),
            "mean_es": self.mean_es.tolist(),
            "modes": self.modes.tolist(),
            "eigenvalues": self.eigenvalues.tolist(),
            "mode_names": list(self.mode_names),
            "closed_structures": list(self.closed_structures),
            "provenance": self.provenance,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CoupledShapeModel:
        if data.get("schema_version") != ATLAS_SCHEMA_VERSION or data.get("units") != "mm":
            raise ValueError("unsupported atlas schema or units")
        return cls(
            view=str(data["view"]),
            structures={k: tuple(v) for k, v in data["structures"].items()},
            landmarks=dict(data["landmarks"]),
            mean_ed=np.asarray(data["mean_ed"]),
            mean_es=np.asarray(data["mean_es"]),
            modes=np.asarray(data["modes"]),
            eigenvalues=np.asarray(data["eigenvalues"]),
            mode_names=tuple(data["mode_names"]),
            closed_structures=tuple(data["closed_structures"]),
            provenance=str(data.get("provenance", "local_unvalidated")),
        )


@dataclass(frozen=True)
class ShapeFit:
    points: np.ndarray
    coefficients: np.ndarray
    rms: float
    observed_nodes: int


@dataclass(frozen=True)
class MeanAppearanceTemplate:
    """Analytic expected echogenicity, variance and boundary confidence in [0,1].

    A deterministic tissue prior, not an ultrasound simulator or a patient mean.
    Low RV free-wall reliability models typical dropout, not missing anatomy.
    """

    mean: np.ndarray
    variance: np.ndarray
    boundary_confidence: np.ndarray
    bounds: tuple[float, float, float, float]


def build_mean_appearance(
    model: CoupledShapeModel,
    *,
    phase: str | float = "ED",
    size: int = 128,
) -> MeanAppearanceTemplate:
    if not 16 <= size <= 512:
        raise ValueError("appearance grid must be 16..512")
    points = model.synthesize(phase=phase)
    low, high = points.min(axis=0) - 10, points.max(axis=0) + 10
    yy, xx = np.meshgrid(np.linspace(low[1], high[1], size), np.linspace(low[0], high[0], size), indexing="ij")
    grid = np.column_stack([xx.ravel(), yy.ravel()])
    image = np.full(len(grid), 0.28)
    confidence = np.full(len(grid), 0.5)
    for chamber, indices in model.structures.items():
        if chamber == "IVS":
            continue
        poly = points[list(indices)]
        image[polygon_interior(grid, poly)] = 0.06
    for chamber, indices in model.structures.items():
        poly = points[list(indices)]
        # Segment distances, not just node dots, produce a continuous wall band.
        ends = np.roll(poly, -1, axis=0)
        if chamber == "IVS":
            poly, ends = poly[:-1], poly[1:]
        wall_dist = np.full(len(grid), np.inf)
        for a, b in zip(poly, ends):
            v = b - a
            t = np.clip((grid - a) @ v / max(float(v @ v), 1e-12), 0, 1)
            wall_dist = np.minimum(wall_dist, np.linalg.norm(grid - a - t[:, None] * v, axis=1))
        response = np.exp(-0.5 * (wall_dist / 1.3) ** 2)
        image = np.maximum(image, 0.8 * response)
        reliable = 0.35 if chamber == "RV" else 0.9
        confidence = np.where(response > 0.4, reliable, confidence)
    # Shared septum and fibrous valve anchors remain reliable even near RV dropout.
    for idx in set(model.structures.get("IVS", ())) | set(model.landmarks.values()):
        near = np.linalg.norm(grid - points[idx], axis=1) < 2.0
        confidence[near] = 0.95
    variance = 0.02 + 0.16 * (1 - confidence)
    shape = (size, size)
    return MeanAppearanceTemplate(
        image.reshape(shape),
        variance.reshape(shape),
        confidence.reshape(shape),
        (float(low[0]), float(low[1]), float(high[0]), float(high[1])),
    )


def build_cardiac_atlas(view: str = "A4C") -> CoupledShapeModel:
    """Build the versioned analytic seed; learned artifacts are explicitly injected."""
    return CoupledShapeModel(*analytic_atlas_seed(view))


def fit_chamber_landmarks(
    model: CoupledShapeModel,
    chamber: str,
    septal: tuple[float, float],
    lateral: tuple[float, float],
    apex: tuple[float, float],
    *,
    phase: str | float = "ED",
    num_points: int = 81,
    pixel_spacing_mm: tuple[float, float] | None = None,
) -> list[tuple[float, float]]:
    """Place a smooth prior using three exact anchors, with metric-aware alignment.

    This single-chamber adapter does not infer other chambers from arbitrary
    user clicks. Coupled inference uses ``model.fit`` in a common frame instead.
    """
    key = chamber.upper()
    if key not in model.structures or key in model.closed_structures or key == "IVS":
        raise ValueError("chamber is not an open arc in this projection")
    frame = CanonicalFrame.from_landmarks(septal, lateral, apex, pixel_spacing_mm=pixel_spacing_mm)
    mesh = model.synthesize(phase=phase)
    arc = mesh[list(model.structures[key])]
    apex_idx = model.landmarks[f"{key}_apex"]
    source = np.vstack([arc[0], arc[-1], mesh[apex_idx]])
    target = frame.image_to_atlas([septal, lateral, apex])
    affine = np.linalg.solve(np.column_stack([source, np.ones(3)]), target)
    placed = frame.atlas_to_image(np.column_stack([arc, np.ones(len(arc))]) @ affine)
    # Split at the topological apex to preserve all three exact user landmarks.
    split = model.structures[key].index(apex_idx)
    first_count = num_points // 2 + 1
    if num_points < 5:
        raise ValueError("at least five arc points required")
    first = resample_arc(placed[: split + 1], first_count)
    last = resample_arc(placed[split:], num_points - first_count + 1)
    result = np.vstack([first, last[1:]])
    result[0], result[first_count - 1], result[-1] = septal, apex, lateral
    return [(float(x), float(y)) for x, y in result]
