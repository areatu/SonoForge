"""Research-only carotid IMT drafts, never an automatic clinical diagnosis (#558)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import isfinite

from echo_personal_tool.domain.measurement_catalog import measurement_for_caliper
from echo_personal_tool.domain.models.calibration import CalibrationConfidence, CalibrationContext

Point = tuple[float, float]
Boundary = tuple[Point, ...]


class ImtRefusal(ValueError):
    """Stable refusal code; callers must not invent a fallback measurement."""


@dataclass(frozen=True)
class ImtPolicy:
    """Explicit research settings, NOT validated clinical acceptance thresholds.

    Physical search limits and quality gates must be supplied by the study
    protocol. The code intentionally does not choose a diagnostic IMT cutoff.
    """

    min_thickness_mm: float
    max_thickness_mm: float
    min_coverage: float
    min_edge_contrast: float
    min_axial_samples: float = 2.0
    search_radius_px: int = 6
    max_step_px: int = 1
    smoothness_penalty: float = 0.03

    def __post_init__(self) -> None:
        values = (
            self.min_thickness_mm,
            self.max_thickness_mm,
            self.min_coverage,
            self.min_edge_contrast,
            self.min_axial_samples,
            self.smoothness_penalty,
        )
        if not all(isfinite(v) for v in values):
            raise ImtRefusal("invalid_policy")
        if not 0 < self.min_thickness_mm < self.max_thickness_mm:
            raise ImtRefusal("invalid_thickness_limits")
        if not 0 < self.min_coverage <= 1 or not 0 < self.min_edge_contrast <= 1:
            raise ImtRefusal("invalid_quality_limits")
        if type(self.search_radius_px) is not int or type(self.max_step_px) is not int:
            raise ImtRefusal("invalid_search_limits")
        if self.min_axial_samples < 1 or not 1 <= self.search_radius_px <= 128 or not 1 <= self.max_step_px <= 4:
            raise ImtRefusal("invalid_search_limits")
        if self.smoothness_penalty < 0:
            raise ImtRefusal("invalid_search_limits")


@dataclass(frozen=True)
class ImtSource:
    """The operator-selected longitudinal B-mode frame and far-wall segment.

    Generation is supplied by the application lifecycle; calibration is the
    authoritative context selected for the entire ROI, not a copied spacing.
    Phase must be explicit, including 'operator_selected' when ECG is absent.
    """

    study_uid: str
    instance_uid: str
    generation: int
    frame_index: int
    frame_count: int
    side: str
    phase: str
    calibration: CalibrationContext
    roi: tuple[int, int, int, int]  # half-open x0, y0, x1, y1 in source pixels
    segment: str = "CCA_far_wall"
    clip_mode: str = "2d"

    def __post_init__(self) -> None:
        if any(type(v) is not int for v in (self.generation, self.frame_index, self.frame_count)):
            raise ImtRefusal("invalid_source")
        if (
            not self.study_uid
            or not self.instance_uid
            or self.generation < 0
            or not 0 <= self.frame_index < self.frame_count
        ):
            raise ImtRefusal("invalid_source")
        if self.side not in ("R", "L") or self.segment != "CCA_far_wall" or not self.phase:
            raise ImtRefusal("invalid_context")
        if self.clip_mode != "2d":
            raise ImtRefusal("bmode_required")
        if type(self.roi) is not tuple or len(self.roi) != 4 or any(type(v) is not int for v in self.roi):
            raise ImtRefusal("invalid_roi")
        x0, y0, x1, y1 = self.roi
        if x0 < 0 or y0 < 0 or x1 - x0 < 8 or y1 - y0 < 8:
            raise ImtRefusal("invalid_roi")
        if x1 - x0 > 512 or y1 - y0 > 256:
            raise ImtRefusal("roi_too_large")
        context = self.calibration
        if not isinstance(context, CalibrationContext):
            raise ImtRefusal("calibration_required")
        row, col = context.spacing
        if not 1e-50 <= min(row, col) <= max(row, col) <= 1e50 or max(row, col) / min(row, col) > 1e6:
            raise ImtRefusal("numerically_unstable_scale")
        if context.confidence not in (CalibrationConfidence.MEASURED, CalibrationConfidence.DERIVED):
            raise ImtRefusal("unverified_calibration")
        if context.assumption is not None or context.assumed_isotropic:
            raise ImtRefusal("unverified_calibration")
        if (
            (context.frame_index is not None and context.frame_index != self.frame_index)
            or not context.applies_to_frame(self.frame_index)
            or not context.contains_bbox(self.roi)
        ):
            raise ImtRefusal("calibration_scope_mismatch")

    @property
    def caliper_label(self) -> str:
        return f"IMT-{self.side}"

    @property
    def measurement_key(self) -> str:
        key = measurement_for_caliper(self.caliper_label)
        if key is None:
            raise ImtRefusal("catalogue_mapping_missing")
        return key


@dataclass(frozen=True)
class ImtDraft:
    """Geometry, QC and mm statistics; a correction always requires new review."""

    source: ImtSource
    policy: ImtPolicy
    lumen_intima: Boundary
    media_adventitia: Boundary
    distances_mm: tuple[float, ...]
    attempted_samples: int
    accepted_sample_indices: tuple[int, ...]
    sampled_length_mm: float
    mean_mm: float
    max_mm: float
    sd_mm: float  # population SD of accepted equidistant normal samples
    revision: int = 0
    confirmed: bool = False
    method: str = "research_imt_dp_v1"

    @property
    def coverage(self) -> float:
        return len(self.distances_mm) / self.attempted_samples

    def confirm(self, current: ImtSource) -> ImtDraft:
        """Explicit operator acceptance; a changed frame/scale cannot be confirmed."""
        if current != self.source:
            raise ImtRefusal("stale_draft")
        return replace(self, confirmed=True)

    def report_record(self, current: ImtSource) -> dict[str, object]:
        """Explicit research export only; no implicit linear-caliper conversion."""
        if not self.confirmed:
            raise ImtRefusal("confirmation_required")
        if current != self.source:
            raise ImtRefusal("stale_draft")
        return {
            "measurement_key": self.source.measurement_key,
            "caliper_label": self.source.caliper_label,
            "study_uid": self.source.study_uid,
            "instance_uid": self.source.instance_uid,
            "generation": self.source.generation,
            "frame_index": self.source.frame_index,
            "frame_count": self.source.frame_count,
            "side": self.source.side,
            "segment": self.source.segment,
            "phase": self.source.phase,
            "roi": self.source.roi,
            "calibration": self.source.calibration.signature(),
            "lumen_intima": self.lumen_intima,
            "media_adventitia": self.media_adventitia,
            "mean_mm": self.mean_mm,
            "max_mm": self.max_mm,
            "sd_mm": self.sd_mm,
            "sampled_length_mm": self.sampled_length_mm,
            "accepted_sample_indices": self.accepted_sample_indices,
            "distances_mm": self.distances_mm,
            "accepted_samples": len(self.distances_mm),
            "attempted_samples": self.attempted_samples,
            "coverage": self.coverage,
            "revision": self.revision,
            "confirmed": True,
            "method": self.method,
            "research_only": True,
            "policy": {name: getattr(self.policy, name) for name in self.policy.__dataclass_fields__},
        }
