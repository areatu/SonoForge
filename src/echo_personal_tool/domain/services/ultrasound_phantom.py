"""ML.2 reproducible atlas-driven B-mode cine (pure NumPy/SciPy).

A phenomenological projected phantom, not a clinically validated ultrasound
simulator. No external datasets, patient images, Qt, torch, ONNX or file I/O.
Ground truth is geometry BEFORE acoustic dropout, in image pixel coordinates.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from echo_personal_tool.domain.services.cardiac_atlas import CoupledShapeModel, build_cardiac_atlas
from echo_personal_tool.domain.services.ultrasound_phantom_acoustics import (
    AcousticSettings,
    advected_rayleigh,
    depth_gain,
    depth_psf,
    inverse_tissue_map,
    render_reflectivity,
)
from echo_personal_tool.domain.services.ultrasound_phantom_geometry import (
    PHANTOM_VIEWS as PHANTOM_VIEWS,
)
from echo_personal_tool.domain.services.ultrasound_phantom_geometry import (
    SectorGeometry,
    cardiac_mesh,
    place_meshes,
    valve_segments,
)


@dataclass(frozen=True)
class PhantomConfig:
    view: str = "A4C"
    seed: int = 0
    size: int = 224
    fps: int = 50
    frames_per_cycle: int = 50
    cycles: int = 1
    half_angle: float = 0.68
    coefficients: tuple[float, ...] = ()
    unknown_kind: str = "off_axis"
    randomize_acoustics: bool = True

    def __post_init__(self) -> None:
        if any(type(value) is not int for value in (self.size, self.fps, self.frames_per_cycle, self.cycles)):
            raise ValueError("size and timing values must be integers")
        if self.view not in PHANTOM_VIEWS:
            raise ValueError("unsupported phantom view")
        if not isinstance(self.seed, int) or not 0 <= self.seed < 2**63:
            raise ValueError("seed must be a nonnegative 63-bit integer")
        if not 30 <= self.fps <= 60 or not 12 <= self.frames_per_cycle <= 120 or not 1 <= self.cycles <= 3:
            raise ValueError("invalid cine timing (30..60 FPS, 12..120 frames/cycle, 1..3 cycles)")
        if self.size**2 * self.frames_per_cycle * self.cycles > 40_000_000:
            raise ValueError("cine exceeds bounded memory budget")
        if len(self.coefficients) > 256 or not np.isfinite(self.coefficients).all():
            raise ValueError("invalid atlas coefficients")
        if self.unknown_kind not in {"off_axis", "foreshortened", "rib_occluded"}:
            raise ValueError("invalid UNKNOWN surrogate")
        SectorGeometry(self.size, self.half_angle)


@dataclass(frozen=True)
class PhantomCine:
    frames: np.ndarray  # uint8, T×H×W
    phases: np.ndarray  # actual ventricular cycle fraction, including sampled ED/ES
    contours: dict[str, np.ndarray]  # T×N×2, open arcs except closed_structures
    masks: dict[str, np.ndarray]  # boolean T×H×W, acoustic visibility does not erase GT
    landmarks: dict[str, np.ndarray]  # T×2 in pixels
    valves: dict[str, np.ndarray]  # T×2×2×2, two leaflets/segments
    sector_mask: np.ndarray
    pixel_spacing_mm: tuple[float, float]
    config: PhantomConfig
    acoustics: AcousticSettings
    closed_structures: tuple[str, ...]
    atlas_provenance: str
    coefficients: tuple[float, ...]

    @property
    def ed_frame(self) -> int:
        return 0

    @property
    def es_frame(self) -> int:
        return int(np.argmin(np.abs(self.phases - 0.38)))


def cine_phases(frames_per_cycle: int, cycles: int) -> np.ndarray:
    """Uniform physical sampling; ES annotation is the nearest actual sample.

    Do not overwrite a sample's phase to force ES: that would introduce a
    nonuniform timestep into an otherwise uniform-FPS DICOM cine.
    """
    return np.asarray((np.arange(frames_per_cycle * cycles) % frames_per_cycle) / frames_per_cycle)


def sampled_acoustics(rng: np.random.Generator) -> AcousticSettings:
    """Clip-level domain randomization, not framewise gain flicker."""
    return AcousticSettings(
        angular_exponent=float(rng.uniform(2, 6)),
        attenuation=float(rng.uniform(0.8, 2.2)),
        tgc=float(rng.uniform(0.5, 1.6)),
        tgc_curve=float(rng.uniform(-0.3, 0.4)),
        speckle_correlation=float(rng.uniform(0.93, 0.99)),
        shadow_angle=float(rng.uniform(-0.45, 0.45)),
        shadow_width=float(rng.uniform(0.025, 0.09)),
        shadow_strength=float(rng.uniform(0.15, 0.7)),
        reverberation=float(rng.uniform(0.04, 0.14)),
        psf_width=float(rng.uniform(0.5, 1.1)),
    )


def generate_cine(
    config: PhantomConfig, *, acoustics: AcousticSettings | None = None, atlas_model: CoupledShapeModel | None = None
) -> PhantomCine:
    """Same seed/config/runtime -> same pixels and labels; never use global RNG."""
    geometry_rng, texture_rng = (np.random.default_rng(s) for s in np.random.SeedSequence(config.seed).spawn(2))
    settings = acoustics or (sampled_acoustics(texture_rng) if config.randomize_acoustics else AcousticSettings())
    if config.view == "UNKNOWN" and config.unknown_kind == "rib_occluded":
        settings = replace(settings, shadow_angle=0.0, shadow_width=0.35, shadow_strength=0.98)
    atlas_view = "A4C" if config.view in {"SUBCOSTAL", "UNKNOWN"} else config.view
    model = atlas_model if atlas_model is not None else build_cardiac_atlas(atlas_view)
    if model.view != atlas_view:
        raise ValueError("injected atlas does not match projected view")
    coefficients = config.coefficients or tuple(
        float(x) for x in geometry_rng.uniform(-2.0, 2.0, len(model.eigenvalues)) * np.sqrt(model.eigenvalues)
    )
    phases = cine_phases(config.frames_per_cycle, config.cycles)
    metric = np.array([cardiac_mesh(model, float(p), coefficients) for p in phases])
    sector = SectorGeometry(config.size, config.half_angle)
    meshes, scale, affine = place_meshes(metric, sector, config.view, config.unknown_kind)
    contours = {name: meshes[:, list(indices)] for name, indices in model.structures.items()}
    landmarks = {name: meshes[:, idx] for name, idx in model.landmarks.items()}
    if "AO" in contours:
        landmarks["Ao_root"] = contours["AO"][:, [0, -1]].mean(axis=1)
    valves: dict[str, list[np.ndarray]] = {}
    for phase, nodes in zip(phases, metric):
        for name, segments in valve_segments(model, nodes, float(phase)).items():
            placed = segments @ affine[:2] + affine[2]
            valves.setdefault(name, []).append(placed)
    valve_arrays = {name: np.array(values) for name, values in valves.items()}
    frames, masks = render_cine(
        config, sector, meshes, contours, valve_arrays, model.closed_structures, settings, texture_rng
    )
    return PhantomCine(
        frames,
        phases,
        contours,
        masks,
        landmarks,
        valve_arrays,
        sector.contains(sector.grid()),
        (1 / scale, 1 / scale),
        config,
        settings,
        model.closed_structures,
        model.provenance,
        coefficients,
    )


def render_cine(
    config: PhantomConfig,
    sector: SectorGeometry,
    meshes: np.ndarray,
    contours: dict[str, np.ndarray],
    valves: dict[str, np.ndarray],
    closed: tuple[str, ...],
    settings: AcousticSettings,
    rng: np.random.Generator,
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    count = len(meshes)
    frames = np.empty((count, config.size, config.size), dtype=np.uint8)
    masks: dict[str, np.ndarray] = {}
    grid = sector.grid()
    radius, theta = sector.polar(grid)
    gain = depth_gain(radius, theta, sector.size, settings)
    sector_mask = sector.contains(grid)
    reverberation = settings.reverberation * np.exp(-radius / (config.size * 0.12)) * (0.5 + 0.5 * np.cos(radius * 1.4))
    real, imag = rng.normal(size=(2, config.size, config.size))
    rho = settings.speckle_correlation
    for i, mesh in enumerate(meshes):
        reflectivity, frame_masks = render_reflectivity(
            sector,
            {k: v[i] for k, v in contours.items()},
            closed,
            {k: v[i] for k, v in valves.items()},
            settings,
            liver=config.view == "SUBCOSTAL",
        )
        for name, mask in frame_masks.items():
            if name not in masks:
                masks[name] = np.empty_like(frames, dtype=bool)
            masks[name][i] = mask
        if i:
            innovation = rng.normal(size=(2, config.size, config.size))
            real = rho * real + np.sqrt(1 - rho**2) * innovation[0]
            imag = rho * imag + np.sqrt(1 - rho**2) * innovation[1]
        inverse_map = inverse_tissue_map(meshes[0], mesh, config.size)
        speckle = advected_rayleigh(real, imag, inverse_map)
        signal = depth_psf(reflectivity * speckle * gain + reverberation, settings)
        compressed = np.log1p(np.maximum(signal, 0) * 8) / np.log(1 + 8 * 2.5)
        frames[i] = np.where(sector_mask, np.clip(compressed * 255, 0, 255), 0).astype(np.uint8)
    return frames, masks
