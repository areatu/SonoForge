"""Projected 2-D phantom mechanics and sector geometry (no image/file I/O).

These are controlled atlas projections, NOT a 3-D echocardiography simulator.
SUBCOSTAL uses a rotated four-chamber geometry; off-axis cuts are surrogates.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from echo_personal_tool.domain.services.cardiac_atlas import CoupledShapeModel, phase_weight

PHANTOM_VIEWS = ("A4C", "RV_A4C", "A2C", "A3C", "PLAX", "PSAX", "SUBCOSTAL", "UNKNOWN")


@dataclass(frozen=True)
class SectorGeometry:
    size: int
    half_angle: float = 0.68
    near_fraction: float = 0.055
    far_fraction: float = 0.95

    def __post_init__(self) -> None:
        if type(self.size) is not int or not 48 <= self.size <= 512 or not 0.35 <= self.half_angle <= 0.9:
            raise ValueError("invalid sector size/angle")
        if not 0 <= self.near_fraction < self.far_fraction <= 1:
            raise ValueError("invalid sector depth bounds")

    @property
    def origin(self) -> np.ndarray:
        return np.array([(self.size - 1) / 2, 0.0])

    def polar(self, points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        delta = points - self.origin
        return np.linalg.norm(delta, axis=-1), np.arctan2(delta[..., 0], delta[..., 1])

    def contains(self, points: np.ndarray) -> np.ndarray:
        radius, theta = self.polar(points)
        return np.asarray(
            (radius >= self.near_fraction * self.size)
            & (radius <= self.far_fraction * self.size)
            & (np.abs(theta) <= self.half_angle)
            & (points[..., 0] >= 0)
            & (points[..., 0] <= self.size - 1)
            & (points[..., 1] >= 0)
            & (points[..., 1] <= self.size - 1)
        )

    def grid(self) -> np.ndarray:
        yy, xx = np.mgrid[: self.size, : self.size]
        return np.stack([xx, yy], axis=-1).astype(np.float64)


def mechanical_weight(phase: float) -> float:
    """ED=0, ES=.38; fast E-wave and a smaller late A-wave in diastole."""
    phi = phase % 1.0
    if phi <= 0.38:
        return phase_weight(phi)
    # Monotonic relaxation with diastasis; smooth endpoints at ED/ES.
    times = np.array([0.38, 0.68, 0.86, 1.0])
    levels = np.array([1.0, 0.18, 0.12, 0.0])
    i = min(int(np.searchsorted(times, phi, side="right")) - 1, 2)
    t = (phi - times[i]) / (times[i + 1] - times[i])
    t = 0.5 - 0.5 * np.cos(np.pi * t)
    return float(levels[i] * (1 - t) + levels[i + 1] * t)


def cardiac_mesh(model: CoupledShapeModel, phase: float, coefficients: tuple[float, ...]) -> np.ndarray:
    """Shared-node mechanics: counterphase chambers and annular excursion."""
    weight = mechanical_weight(phase)
    # Convert the desired mechanical weight to the atlas' smooth phase parameter.
    atlas_phase = float(0.38 * np.arccos(1 - 2 * weight) / np.pi)
    mesh = model.synthesize(coefficients, phase=atlas_phase)
    if model.view != "PSAX":
        # Move basal nodes towards the ventricular apex (MAPSE/TAPSE surrogate).
        excursion = 5.0 * weight * np.exp(-((model.mean_ed[:, 1] / 30) ** 2))
        mesh[:, 1] += excursion
    return model.constrain(mesh, phase=atlas_phase)


def projection_matrix(view: str, unknown_kind: str) -> np.ndarray:
    angle = {"PLAX": -0.95, "A3C": -0.3, "SUBCOSTAL": 1.05, "RV_A4C": 0.12}.get(view, 0.0)
    # Apical apex at top; subcostal/parasternal rotate the same indexed anatomy.
    angle += np.pi
    c, s = np.cos(angle), np.sin(angle)
    transform = np.array([[c, -s], [s, c]])
    if view == "UNKNOWN":
        if unknown_kind == "foreshortened":
            transform = transform @ np.diag([1.0, 0.48])
        elif unknown_kind == "off_axis":
            transform = transform @ np.array([[0.65, 0.45], [0.0, 1.0]])
    return transform


def place_meshes(
    meshes: np.ndarray, sector: SectorGeometry, view: str, unknown_kind: str
) -> tuple[np.ndarray, float, np.ndarray]:
    """One fixed affine for the ENTIRE cine, never per-frame auto-zoom."""
    transform = projection_matrix(view, unknown_kind)
    projected = meshes @ transform.T
    centre = (projected.min(axis=(0, 1)) + projected.max(axis=(0, 1))) / 2
    projected -= centre
    scale = sector.size * 0.50 / max(float(np.ptp(projected, axis=(0, 1)).max()), 1.0)
    offset = np.array([(sector.size - 1) / 2, sector.size * 0.54])
    for _ in range(30):
        placed = projected * scale + offset
        if sector.contains(placed).all():
            affine = np.vstack([transform.T * scale, offset - centre * scale])
            return placed, float(scale), affine
        scale *= 0.94
    raise ValueError("cannot place cardiac geometry inside sector")


def valve_segments(model: CoupledShapeModel, mesh: np.ndarray, phase: float) -> dict[str, np.ndarray]:
    """Two hinged AV leaflets; an aortic opening in systole, in metric space."""
    valves: dict[str, np.ndarray] = {}
    phi = phase % 1.0
    av_open = float(np.sin(np.pi * np.clip((phi - 0.40) / 0.60, 0, 1)) ** 2)
    for name, prefix in (("MV", "MV"), ("TV", "TV")):
        if f"{prefix}_septal" not in model.landmarks:
            continue
        a, b = (mesh[model.landmarks[f"{prefix}_{side}"]] for side in ("septal", "lateral"))
        span = float(np.linalg.norm(b - a))
        normal = np.array([-(b - a)[1], (b - a)[0]]) / max(span, 1e-8)
        if normal[1] < 0:
            normal *= -1
        tips = [a + (b - a) * (0.5 - 0.32 * av_open), b - (b - a) * (0.5 - 0.32 * av_open)]
        valves[name] = np.array(
            [[a, tips[0] + normal * span * 0.42 * av_open], [b, tips[1] + normal * span * 0.42 * av_open]]
        )
    if "AO" in model.structures:
        a, b = mesh[list(model.structures["AO"])[::3]]
        opening = float(np.sin(np.pi * np.clip(phi / 0.38, 0, 1)) ** 2)
        midpoint = (a + b) / 2
        valves["AV"] = np.array(
            [[a, midpoint * (1 - opening) + a * opening], [b, midpoint * (1 - opening) + b * opening]]
        )
    return valves
