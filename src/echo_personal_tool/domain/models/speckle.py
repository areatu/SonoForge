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
    aha_segment: int = 0
    arc_length_param: float = 0.0


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
    reference_frame: int = 0


@dataclass(frozen=True)
class SpeckleConfig:
    """Configuration for speckle tracking."""

    kernel_size: int = 12
    search_radius: int = 8
    pyramid_levels: int = 2
    ncc_threshold: float = 0.3
    outlier_sigma: float = 0
    subpixel: bool = True
    wall_thickness_mm: float = 8.0
    bidirectional: bool = True
    ed_anchored: bool = True
    tracking_mode: str = "sequential"
    spatial_smoothing: float = 1.0
    temporal_smoothing: float = 1.0
    quality_weighted_smoothing: bool = True
    drift_compensation: bool = True
    global_motion_compensation: bool = True
    min_segment_quality: float = 0.4
    min_kernel_quality: float = 0.3
    # Forward-backward closure error, as a fraction of ``search_radius``; a
    # match whose round trip exceeds this is rejected.
    closure_error_threshold: float = 0.5

    @classmethod
    def preset_standard(cls) -> SpeckleConfig:
        return cls(
            kernel_size=12,
            search_radius=8,
            bidirectional=True,
            drift_compensation=True,
            tracking_mode="sequential",
            ncc_threshold=0.3,
            outlier_sigma=0,
        )

    @classmethod
    def preset_research(cls) -> SpeckleConfig:
        return cls(
            kernel_size=18,
            search_radius=18,
            spatial_smoothing=1.2,
            temporal_smoothing=1.1,
            tracking_mode="sequential",
        )

    @classmethod
    def preset_debug(cls) -> SpeckleConfig:
        return cls(
            bidirectional=False,
            spatial_smoothing=0.0,
            temporal_smoothing=0.0,
            drift_compensation=False,
        )


from echo_personal_tool.domain.models.ecg import EcgWaveform, RPeakResult


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
    tracked_es_positions: np.ndarray | None = None
    tracked_ed_positions: np.ndarray | None = None
    tracked_positions_all: np.ndarray | None = None
    raw_tracked_positions: np.ndarray | None = None
    ncc_all_frames: np.ndarray | None = None
    es_ncc_scores: np.ndarray | None = None
    es_valid_mask: np.ndarray | None = None
    segment_strain: dict[int, float] = field(default_factory=dict)
    segment_quality: dict[int, float] = field(default_factory=dict)
    drift_compensation_applied: bool = False
    tracking_quality_mean: float = 0.0
    cycle_count: int = 1
    config_preset: str = "standard"
    tracking_window_start: int = 0
    tracking_window_end: int = 0
    ncc_threshold: float = 0.3
    kernels_accepted_count: int = 0
    kernels_rejected_count: int = 0
    kernels_total_count: int = 0
    # ECG fields
    ecg_waveform: EcgWaveform | None = None
    r_peak_result: RPeakResult | None = None
    ed_es_source: str = "image"
    ed_es_confidence: float = 0.0
    ed_es_quality: str = "unknown"
    ecg_trace_for_display: np.ndarray | None = None
