"""Domain models for speckle tracking echocardiography."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class TrackingKernel:
    """A single speckle tracking kernel (correlation block)."""

    center: tuple[float, float]
    radius: int = 10
    node_index: int = 0
    layer: str = "endo"


@dataclass(frozen=True)
class MyocardialZone:
    """Dual-contour myocardial region between endocardium and epicardium."""

    endo_points: np.ndarray
    epi_points: np.ndarray
    thickness_mm: float
    pixel_spacing: tuple[float, float]

    def __post_init__(self) -> None:
        object.__setattr__(self, "endo_points", self.endo_points.copy())
        object.__setattr__(self, "epi_points", self.epi_points.copy())


@dataclass
class TrackingResult:
    """Result of speckle tracking between two frames."""

    frame_index: int
    displacements: np.ndarray
    ncc_scores: np.ndarray
    valid_mask: np.ndarray
    kernel_positions: np.ndarray


@dataclass(frozen=True)
class SpeckleConfig:
    """Configuration for speckle tracking."""

    kernel_size: int = 12
    search_radius: int = 15
    pyramid_levels: int = 2
    ncc_threshold: float = 0.5
    outlier_sigma: float = 3.0
    subpixel: bool = True
    wall_thickness_mm: float = 8.0


@dataclass(frozen=True)
class StrainResult:
    """Computed strain results."""

    longitudinal: np.ndarray
    radial: np.ndarray
    gls: float
    strain_rate: np.ndarray | None = None
    ed_index: int = 0
    es_index: int = 0
    heart_rate_bpm: float = 0.0
    phases: dict[str, int] = field(default_factory=dict)
    zone: MyocardialZone | None = None
    kernels: list[TrackingKernel] = field(default_factory=list)
    last_displacements: np.ndarray | None = None
    last_ncc_scores: np.ndarray | None = None
    last_valid_mask: np.ndarray | None = None
    cumulative_displacements: np.ndarray | None = None
    per_kernel_longitudinal: np.ndarray | None = None
    ed_contour: np.ndarray | None = None
    es_contour: np.ndarray | None = None
