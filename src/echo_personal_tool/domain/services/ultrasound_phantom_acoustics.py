"""Bounded phenomenological B-mode acoustics; pure NumPy/SciPy, no clinical data.

Rayleigh scatterers live in material coordinates and are sampled through a
smooth inverse tissue displacement. This is not a calibrated wave solver.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import gaussian_filter, map_coordinates, zoom

from echo_personal_tool.domain.services.cardiac_atlas_geometry import polygon_interior
from echo_personal_tool.domain.services.ultrasound_phantom_geometry import SectorGeometry


@dataclass(frozen=True)
class AcousticSettings:
    angular_exponent: float = 3.0
    attenuation: float = 1.3
    tgc: float = 0.9
    tgc_curve: float = 0.2
    speckle_correlation: float = 0.97
    shadow_angle: float = 0.18
    shadow_width: float = 0.04
    shadow_strength: float = 0.5
    reverberation: float = 0.10
    psf_width: float = 0.7

    def __post_init__(self) -> None:
        values = np.array(
            [
                self.angular_exponent,
                self.attenuation,
                self.tgc,
                self.tgc_curve,
                self.speckle_correlation,
                self.shadow_angle,
                self.shadow_width,
                self.shadow_strength,
                self.reverberation,
                self.psf_width,
            ]
        )
        if not np.isfinite(values).all():
            raise ValueError("nonfinite acoustic parameter")
        if not 0 <= self.angular_exponent <= 12 or not 0 <= self.attenuation <= 6:
            raise ValueError("invalid angular response/attenuation")
        if not -3 <= self.tgc <= 3 or not -2 <= self.tgc_curve <= 2:
            raise ValueError("invalid TGC")
        if not 0 <= self.speckle_correlation <= 1 or not 0 <= self.shadow_strength <= 1:
            raise ValueError("invalid correlation/shadow")
        if not -1 <= self.shadow_angle <= 1 or not 0.005 <= self.shadow_width <= 0.5:
            raise ValueError("invalid shadow geometry")
        if not 0 <= self.reverberation <= 1 or not 0.2 <= self.psf_width <= 3:
            raise ValueError("invalid reverberation/PSF")


def specular_response(normal: np.ndarray, ray: np.ndarray, exponent: float = 3.0) -> np.ndarray:
    """Wall normal parallel to beam -> 1; perpendicular -> dropout, not absent GT."""
    norm = np.linalg.norm(normal, axis=-1) * np.linalg.norm(ray, axis=-1)
    cosine = np.sum(normal * ray, axis=-1) / np.maximum(norm, 1e-12)
    return np.asarray(np.abs(np.clip(cosine, -1, 1)) ** exponent)


def depth_gain(radius: np.ndarray, theta: np.ndarray, size: int, settings: AcousticSettings) -> np.ndarray:
    depth = radius / size
    attenuation_tgc = np.exp((settings.tgc - settings.attenuation) * depth + settings.tgc_curve * depth**2)
    shadow = 1 - settings.shadow_strength * np.exp(
        -0.5 * ((theta - settings.shadow_angle) / settings.shadow_width) ** 2
    )
    # Shadow starts below a simulated rib, not at the transducer itself.
    return np.asarray(attenuation_tgc * np.where(depth > 0.18, shadow, 1.0))


def depth_psf(image: np.ndarray, settings: AcousticSettings) -> np.ndarray:
    """Blur in (r, theta), not image axes: transverse width grows with radius.

    Fixed angular sigma gives w_perp(r) proportional to r, while axial sigma
    stays fixed in pixels. Resampling itself adds a small interpolation PSF.
    """
    size = image.shape[0]
    sector = SectorGeometry(size)
    radial_samples, angular_samples = size * 2, size * 3
    radii = np.linspace(0, size * 1.5, radial_samples)
    angles = np.linspace(-np.pi / 2, np.pi / 2, angular_samples)
    rr, tt = np.meshgrid(radii, angles, indexing="ij")
    source_x = sector.origin[0] + rr * np.sin(tt)
    source_y = rr * np.cos(tt)
    polar = map_coordinates(image, [source_y, source_x], order=1, mode="constant")
    polar = gaussian_filter(
        polar,
        sigma=(
            settings.psf_width * 0.6 / (radii[1] - radii[0]),
            settings.psf_width * 3.0 / (size * (angles[1] - angles[0])),
        ),
    )
    radius, theta = sector.polar(sector.grid())
    return np.asarray(
        map_coordinates(
            polar,
            [radius / (radii[1] - radii[0]), (theta + np.pi / 2) / (angles[1] - angles[0])],
            order=1,
            mode="constant",
        )
    )


def inverse_tissue_map(reference: np.ndarray, current: np.ndarray, size: int) -> np.ndarray:
    """Smooth inverse displacement on a coarse grid, interpolated to image pixels.

    This interpolation is an approximate tissue motion field, not exact fluid
    mechanics or an independent optical-flow ground truth.
    """
    axis = np.linspace(0, size - 1, 20)
    yy, xx = np.meshgrid(axis, axis, indexing="ij")
    grid = np.stack([xx, yy], axis=-1)
    delta = grid[..., None, :] - current
    weights = 1 / (np.sum(delta**2, axis=-1) + (size * 0.035) ** 2)
    displacement = (weights @ (reference - current)) / weights.sum(axis=-1)[..., None]
    dense = zoom(displacement, (size / 20, size / 20, 1), order=1)
    yy_full, xx_full = np.mgrid[:size, :size]
    return np.asarray(np.stack([xx_full, yy_full], axis=-1) + dense)


def advected_rayleigh(real: np.ndarray, imag: np.ndarray, inverse_map: np.ndarray) -> np.ndarray:
    coords = [inverse_map[..., 1], inverse_map[..., 0]]
    re = map_coordinates(real, coords, order=1, mode="reflect")
    im = map_coordinates(imag, coords, order=1, mode="reflect")
    # sqrt(re²+im²) is Rayleigh at lattice samples; interpolation introduces PSF correlation.
    return np.asarray(np.hypot(re, im) / np.sqrt(np.pi / 2))


def render_reflectivity(
    sector: SectorGeometry,
    contours: dict[str, np.ndarray],
    closed: tuple[str, ...],
    valves: dict[str, np.ndarray],
    settings: AcousticSettings,
    *,
    liver: bool = False,
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    grid = sector.grid()
    flat = grid.reshape(-1, 2)
    # Diffuse extracardiac tissue; the subcostal window adds a liver-like near-field layer.
    image = np.full(len(flat), 0.22)
    if liver:
        image += 0.13 * np.exp(-(((flat[:, 1] / sector.size - 0.20) / 0.12) ** 2))
    masks: dict[str, np.ndarray] = {}
    sector_mask = sector.contains(grid)
    for name, arc in contours.items():
        if name == "IVS":
            continue
        inside = polygon_interior(flat, arc).reshape(sector.size, sector.size)
        masks[name] = inside & sector_mask
        image[inside.ravel()] = 0.025 if name in {"LV", "LA", "RV", "RA"} else 0.04
    # Accumulate separate wall responses with max: shared interfaces are not counted twice.
    wall = np.zeros(len(flat))
    for name, arc in contours.items():
        ends = np.roll(arc, -1, axis=0) if name in closed else arc[1:]
        for a, b in zip(arc, ends):
            wall = np.maximum(wall, segment_echo(flat, a, b, sector, settings))
    for segments in valves.values():
        for a, b in segments:
            wall = np.maximum(wall, segment_echo(flat, a, b, sector, settings, valve=True))
    return (image + wall).reshape(sector.size, sector.size), masks


def segment_echo(
    grid: np.ndarray,
    a: np.ndarray,
    b: np.ndarray,
    sector: SectorGeometry,
    settings: AcousticSettings,
    *,
    valve: bool = False,
) -> np.ndarray:
    vector = b - a
    length_sq = float(vector @ vector)
    if length_sq < 1e-12:
        return np.zeros(len(grid))
    t = np.clip((grid - a) @ vector / length_sq, 0, 1)
    nearest = a + t[:, None] * vector
    distance = np.linalg.norm(grid - nearest, axis=-1)
    normal = np.array([-vector[1], vector[0]])
    angular = specular_response(normal, nearest - sector.origin, settings.angular_exponent)
    # Broad diffuse myocardium plus narrow specular endocardium/leaflets.
    width = max(0.6, sector.size * 0.004)
    diffuse = (0.05 if valve else 0.12) * np.exp(-0.5 * (distance / (width * 2)) ** 2)
    return np.asarray(diffuse + 0.9 * angular * np.exp(-0.5 * (distance / width) ** 2))
