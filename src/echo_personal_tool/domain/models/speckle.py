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
    # Temporal low-pass of the strain curves before the metrics are read
    # (peak systolic strain, ESS, TTP). Speckle tracking is noisy frame to
    # frame and an unfiltered *peak* is biased by single-frame spikes, which
    # is what made the segmental numbers swing while the global curve looked
    # plausible. 0 or 1 disables the filter.
    curve_smoothing_frames: int = 9
    quality_weighted_smoothing: bool = True
    drift_compensation: bool = True
    global_motion_compensation: bool = True
    # Wall-band containment of the tracked kernels. Measurement on the kinematic
    # phantom (plan §7.5, F2) showed it clips genuine systolic excursion — the
    # band is built from the *ED* geometry while the endocardium legitimately
    # travels further inward, and a rigid rotation of the wall is read as
    # contraction — so it no longer runs in the default pipeline. Kept for A/B
    # comparison; ``tests/unit/test_kernel_containment.py`` covers the function.
    wall_clamp: bool = False
    min_segment_quality: float = 0.4
    min_kernel_quality: float = 0.3
    # Forward-backward closure error, as a fraction of ``search_radius``; a
    # match whose round trip exceeds this is rejected.
    closure_error_threshold: float = 0.5
    # When False (default), the tracker never pushes kernels toward
    # physiologically "expected" radial directions — motion comes only from the
    # NCC block matching. Setting this to True lets apply_motion_model gently
    # nudge endo/epi kernels that contradict contraction, which can mask poor
    # matches but also fabricate motion that is not present in the image.
    physiology_prior: bool = False

    @classmethod
    def preset_standard(cls) -> SpeckleConfig:
        # tracking_mode="border": vendor-style wall-border propagation. The ED
        # endo/epi contours are tracked frame-to-frame and kernels stay between
        # the moving borders, instead of independent kernels confined to the
        # static ED band (which froze systolic motion and let dots blow through
        # the epicardium). Measured on gold clips: better ES wall containment
        # and less catastrophic mis-tracking than "sequential".
        return cls(
            kernel_size=12,
            search_radius=8,
            bidirectional=True,
            drift_compensation=True,
            tracking_mode="border",
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
    # QC fields: honest measurement quality separate from raw NCC fidelity.
    # ``tracking_quality_mean`` stays the NCC mean; ``qc_score`` is the validity
    # confidence from ``domain.services.quality`` (fidelity x coverage x ...),
    # so it can be low even when NCC reads >90% (issue #3).
    qc_score: float = 0.0
    qc_physiology_ok: bool = True
    qc_physiology_reasons: tuple[str, ...] = ()
    gls_source: str = "curve"
    # Validity status: "valid" | "review" | "invalid" — never derived from NCC
    # alone. ``qc_reasons`` holds i18n keys, ``qc_notes`` human-readable details.
    qc_status: str = "invalid"
    qc_reasons: tuple[str, ...] = ()
    qc_notes: tuple[str, ...] = ()
    qc_coverage: float = 0.0
    qc_interpolated_fraction: float = 0.0
    qc_consistency_delta: float = 0.0
    # Metric cross-checks (plan §7.5, F4): gap between the reported global
    # strain and the independent segment-mean estimate, and the share of the
    # endocardial line whose end-systolic strain has the opposite sign.
    qc_estimate_spread_pp: float = 0.0
    qc_sign_flip_fraction: float = 0.0
    # Per-node strain curves along the tracked material line (single definition,
    # see ``strain_computation.compute_node_longitudinal_curves``). Columns match
    # ``node_indices``; values are NaN outside the tracked window.
    node_curves: np.ndarray | None = None
    node_indices: tuple[int, ...] = ()
    # Per-segment curves over the same time base — the only source the UI may
    # plot, so the numbers on the screen cannot diverge from the model.
    segment_curves: dict[int, np.ndarray] = field(default_factory=dict)
    # Provenance needed to interpret the segment ids: an AHA segment number is
    # only meaningful together with the apical view it was measured in.
    view: str = "A4C"
    segment_model: str = "AHA-18"
    # Clinical metrics over the analysed cycle (plan §3.5, phase 2). ``gls`` is
    # the peak of the global curve (AVC-independent); ``ess`` is the value at
    # aortic valve closure. ``drift_measured`` is the residual strain at the end
    # of the window — reported, never silently removed.
    avc_index: int = 0
    avc_source: str = "es"
    avc_confidence: float = 0.0
    ess: float = float("nan")
    gls_peak_frame: int | None = None
    time_to_peak_ms: float = float("nan")
    post_systolic_index: float = float("nan")
    drift_measured: float = float("nan")
    is_post_systolic: bool = False
    peak_strain: float = float("nan")
    # Per-segment metrics and their time-to-peak (TTP bull's-eye input).
    segment_metrics: dict[int, object] = field(default_factory=dict)
    segment_ttp_ms: dict[int, float] = field(default_factory=dict)
    # Cross-check: mean of the segment peaks (NOT the reported GLS).
    gls_segment_mean: float = float("nan")
    analysis_window_end: int = 0
    cycle_estimated: bool = False
    # ECG fields
    ecg_waveform: EcgWaveform | None = None
    r_peak_result: RPeakResult | None = None
    frame_time_ms: float = 33.3
    # The cine frames (N,H,W[,C]) that tracking ran on, so the results window
    # can always animate kernels over the real ultrasound without depending on
    # the main viewer's frame cache still holding the whole clip.
    cine_frames: np.ndarray | None = None
    ed_es_source: str = "image"
    ed_es_confidence: float = 0.0
    ed_es_quality: str = "unknown"
    ecg_trace_for_display: np.ndarray | None = None
