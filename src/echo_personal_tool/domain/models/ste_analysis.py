"""Analysis model with provenance, and the multi-view strain study (plan §4.4).

Problem this solves
-------------------
Every number the module displays used to be reachable only through the widgets:
the curve panel re-derived its own curves, the bull's-eye had its own segment
map, the export wrote a handful of keys without the definitions behind them, and
nothing kept the results of the other apical views. A number could therefore not
be reproduced, compared with a vendor report or checked clinically.

:class:`StrainAnalysis` is the single serialisable record of one analysed view:
what was measured (definitions, window, ED/ES/AVC with their sources), how well
(gate, coverage, QC status), and what came out (GLS, ESS, peak, TTP, PSI, drift,
per-segment values and curves). :class:`StrainStudy` combines up to three apical
views into the biplane/three-view average (``GLS_AV``) the user asked for —
exactly like a vendor report: per-view GLS, the average over the views that
passed QC, and the 18-segment merge.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

import numpy as np

from echo_personal_tool.domain.models.speckle import StrainResult
from echo_personal_tool.domain.services.segment_map import (
    normalise_view,
    segment_ids_in_bullseye_order,
    view_segment_ids,
)

# The definition strings are part of the exported record: a strain number
# without its definition is not a measurement (Voigt 2015, plan §3.1).
DEFINITION_GLS = "GLS = peak of the global longitudinal strain curve over one cardiac cycle (Lagrangian, endocardial)"
DEFINITION_ESS = "ESS = longitudinal strain at aortic valve closure (AVC)"
DEFINITION_TTP = "TTP = time from end-diastole to the segment strain peak"
DEFINITION_LAYER = "endocardial layer (kernels on the endocardial contour)"
#: Voigt 2015 requires the report to declare the sampling extent, the handling of
#: LV translation and the regularization — otherwise "GLS" is not comparable.
DEFINITION_COMPARABILITY = (
    "comparable only together with the declared ROI sampling extent, "
    "LV translation compensation and regularization settings"
)

ANALYSIS_SCHEMA_VERSION = 2


def _finite(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


@dataclass(frozen=True)
class StrainAnalysis:
    """One analysed view: values, provenance and quality in one record."""

    view: str = "A4C"
    schema_version: int = ANALYSIS_SCHEMA_VERSION
    segmentation: str = "AHA-18"
    definition_gls: str = DEFINITION_GLS
    definition_ess: str = DEFINITION_ESS
    definition_ttp: str = DEFINITION_TTP
    layer: str = DEFINITION_LAYER
    definition_comparability: str = DEFINITION_COMPARABILITY
    # Spatial extent of the sampling (mm) and the processing that shaped the
    # number: kernel footprint, node spacing, regularization text, whether LV
    # translation was compensated, and the acquisition frame rate.
    sampling_kernel_mm: float = 0.0
    sampling_node_spacing_mm: float = 0.0
    regularization: str = ""
    translation_compensation: bool = False
    frame_rate_hz: float = 0.0
    gls: float | None = None
    ess: float | None = None
    peak: float | None = None
    gls_segment_mean: float | None = None
    time_to_peak_ms: float | None = None
    post_systolic_index: float | None = None
    drift: float | None = None
    is_post_systolic: bool = False
    ed_index: int = 0
    es_index: int = 0
    avc_index: int = 0
    avc_source: str = "es"
    avc_confidence: float = 0.0
    window_start: int = 0
    window_end: int = 0
    ed_es_source: str = "image"
    cycle_estimated: bool = False
    tracking_preset: str = "standard"
    tracking_quality_mean: float = 0.0
    qc_status: str = "invalid"
    qc_reasons: tuple[str, ...] = ()
    qc_coverage: float = 0.0
    qc_interpolated_fraction: float = 0.0
    qc_consistency_delta: float = 0.0
    # Metric cross-checks (plan §7.5, F4): gap between the reported global
    # strain and the independent segment-mean estimate, and the share of the
    # endocardial line whose end-systolic strain has the opposite sign.
    qc_estimate_spread_pp: float = 0.0
    qc_sign_flip_fraction: float = 0.0
    # Position noise (mm) and the estimated arc-length bias it causes, divided by
    # the measured contraction (plan §7.5, F6). 1.0 = the measurement is noise.
    qc_noise_to_signal: float = 0.0
    qc_noise_mm: float = 0.0
    # Wall visibility (clinical review Q4): tissue that left the sector is not
    # measured, and the report states how much of the wall was excluded.
    qc_visibility_loss: float = 0.0
    qc_excluded_nodes: int = 0
    qc_excluded_segments: tuple[int, ...] = ()
    # Round-trip verification of the tracking (clinical review Q6).
    qc_closure_median_mm: float = 0.0
    qc_closure_p95_mm: float = 0.0
    qc_rejected_fraction: float = 0.0
    qc_unverified_fraction: float = 0.0
    kernels_accepted: int = 0
    kernels_total: int = 0
    heart_rate_bpm: float = 0.0
    segment_values: dict[int, float] = field(default_factory=dict)
    segment_quality: dict[int, float] = field(default_factory=dict)
    segment_ttp_ms: dict[int, float] = field(default_factory=dict)
    segment_ess: dict[int, float] = field(default_factory=dict)
    segment_curves: dict[int, np.ndarray] = field(default_factory=dict)
    global_curve: np.ndarray | None = None
    node_curves: np.ndarray | None = None
    frame_time_ms: float = 33.3

    @property
    def is_valid(self) -> bool:
        return self.qc_status == "valid"

    def to_dict(self, *, with_curves: bool = False) -> dict:
        """JSON-serialisable record (curves are opt-in — they are long)."""
        data: dict = {
            "schema_version": self.schema_version,
            "view": self.view,
            "segmentation": self.segmentation,
            "definitions": {
                "gls": self.definition_gls,
                "ess": self.definition_ess,
                "ttp": self.definition_ttp,
                "layer": self.layer,
                "comparability": self.definition_comparability,
            },
            "sampling": {
                "kernel_mm": _finite(self.sampling_kernel_mm),
                "node_spacing_mm": _finite(self.sampling_node_spacing_mm),
                "translation_compensation": self.translation_compensation,
                "regularization": self.regularization,
                "frame_rate_hz": _finite(self.frame_rate_hz),
            },
            "values": {
                "gls": self.gls,
                "ess": self.ess,
                "peak": self.peak,
                "gls_segment_mean": self.gls_segment_mean,
                "time_to_peak_ms": self.time_to_peak_ms,
                "post_systolic_index": self.post_systolic_index,
                "drift": self.drift,
                "is_post_systolic": self.is_post_systolic,
            },
            "frames": {
                "ed": self.ed_index,
                "es": self.es_index,
                "avc": self.avc_index,
                "avc_source": self.avc_source,
                "avc_confidence": self.avc_confidence,
                "analysis_window": [self.window_start, self.window_end],
                "ed_es_source": self.ed_es_source,
                "cycle_estimated": self.cycle_estimated,
                "frame_time_ms": self.frame_time_ms,
            },
            "quality": {
                "status": self.qc_status,
                "reasons": list(self.qc_reasons),
                "coverage": self.qc_coverage,
                "interpolated_fraction": self.qc_interpolated_fraction,
                "consistency_delta": self.qc_consistency_delta,
                "estimate_spread_pp": self.qc_estimate_spread_pp,
                "sign_flip_fraction": self.qc_sign_flip_fraction,
                "noise_to_signal": self.qc_noise_to_signal,
                "noise_mm": self.qc_noise_mm,
                "visibility_loss": self.qc_visibility_loss,
                "excluded_nodes": self.qc_excluded_nodes,
                "excluded_segments": list(self.qc_excluded_segments),
                "closure_median_mm": self.qc_closure_median_mm,
                "closure_p95_mm": self.qc_closure_p95_mm,
                "rejected_fraction": self.qc_rejected_fraction,
                "unverified_fraction": self.qc_unverified_fraction,
                "tracking_ncc_mean": self.tracking_quality_mean,
                "kernels_accepted": self.kernels_accepted,
                "kernels_total": self.kernels_total,
                "preset": self.tracking_preset,
                "heart_rate_bpm": self.heart_rate_bpm,
            },
            "segments": {str(seg): _finite(self.segment_values.get(seg)) for seg in sorted(self.segment_values)},
            "segment_quality": {str(seg): _finite(value) for seg, value in sorted(self.segment_quality.items())},
            "segment_ttp_ms": {str(seg): _finite(value) for seg, value in sorted(self.segment_ttp_ms.items())},
            "segment_ess": {str(seg): _finite(value) for seg, value in sorted(self.segment_ess.items())},
        }
        if with_curves:
            data["curves"] = {
                "global": None if self.global_curve is None else np.asarray(self.global_curve).tolist(),
                "segments": {
                    str(seg): np.asarray(curve).tolist() for seg, curve in sorted(self.segment_curves.items())
                },
            }
        return data

    @classmethod
    def from_result(cls, result: StrainResult, *, view: str | None = None) -> StrainAnalysis:
        """Build the record from a worker result (the only conversion point)."""
        metrics = getattr(result, "segment_metrics", {}) or {}
        segment_ess = {int(seg): _finite(getattr(metric, "ess", None)) for seg, metric in metrics.items()}
        return cls(
            view=normalise_view(view or getattr(result, "view", "A4C")),
            gls=_finite(result.gls),
            ess=_finite(getattr(result, "ess", None)),
            peak=_finite(getattr(result, "peak_strain", None)),
            gls_segment_mean=_finite(getattr(result, "gls_segment_mean", None)),
            time_to_peak_ms=_finite(getattr(result, "time_to_peak_ms", None)),
            post_systolic_index=_finite(getattr(result, "post_systolic_index", None)),
            drift=_finite(getattr(result, "drift_measured", None)),
            is_post_systolic=bool(getattr(result, "is_post_systolic", False)),
            ed_index=int(result.ed_index),
            es_index=int(result.es_index),
            avc_index=int(getattr(result, "avc_index", result.es_index)),
            avc_source=str(getattr(result, "avc_source", "es")),
            avc_confidence=float(getattr(result, "avc_confidence", 0.0)),
            window_start=int(result.tracking_window_start),
            window_end=int(getattr(result, "analysis_window_end", result.tracking_window_end)),
            ed_es_source=str(result.ed_es_source),
            sampling_kernel_mm=float(getattr(result, "sampling_kernel_mm", 0.0)),
            sampling_node_spacing_mm=float(getattr(result, "sampling_node_spacing_mm", 0.0)),
            regularization=str(getattr(result, "regularization", "")),
            translation_compensation=bool(getattr(result, "translation_compensation_applied", False)),
            frame_rate_hz=float(getattr(result, "frame_rate_hz", 0.0)),
            cycle_estimated=bool(getattr(result, "cycle_estimated", False)),
            tracking_preset=str(result.config_preset),
            tracking_quality_mean=float(result.tracking_quality_mean),
            qc_status=str(getattr(result, "qc_status", "invalid")),
            qc_reasons=tuple(getattr(result, "qc_reasons", ()) or ()),
            qc_coverage=float(getattr(result, "qc_coverage", 0.0)),
            qc_interpolated_fraction=float(getattr(result, "qc_interpolated_fraction", 0.0)),
            qc_consistency_delta=float(getattr(result, "qc_consistency_delta", 0.0)),
            qc_estimate_spread_pp=float(getattr(result, "qc_estimate_spread_pp", 0.0)),
            qc_sign_flip_fraction=float(getattr(result, "qc_sign_flip_fraction", 0.0)),
            qc_noise_to_signal=float(getattr(result, "qc_noise_to_signal", 0.0)),
            qc_noise_mm=float(getattr(result, "qc_noise_mm", 0.0)),
            qc_visibility_loss=float(getattr(result, "qc_visibility_loss", 0.0)),
            qc_closure_median_mm=float(getattr(result, "qc_closure_median_mm", 0.0)),
            qc_closure_p95_mm=float(getattr(result, "qc_closure_p95_mm", 0.0)),
            qc_rejected_fraction=float(getattr(result, "qc_rejected_fraction", 0.0)),
            qc_unverified_fraction=float(getattr(result, "qc_unverified_fraction", 0.0)),
            qc_excluded_nodes=int(getattr(result, "qc_excluded_nodes", 0)),
            qc_excluded_segments=tuple(int(seg) for seg in (getattr(result, "qc_excluded_segments", ()) or ())),
            kernels_accepted=int(result.kernels_accepted_count),
            kernels_total=int(result.kernels_total_count),
            heart_rate_bpm=float(result.heart_rate_bpm),
            segment_values={int(k): float(v) for k, v in (result.segment_strain or {}).items()},
            segment_quality={int(k): float(v) for k, v in (result.segment_quality or {}).items()},
            segment_ttp_ms={int(k): float(v) for k, v in (getattr(result, "segment_ttp_ms", {}) or {}).items()},
            segment_ess={seg: value for seg, value in segment_ess.items() if value is not None},
            segment_curves={int(k): np.asarray(v, dtype=np.float64) for k, v in (result.segment_curves or {}).items()},
            global_curve=None if result.longitudinal is None else np.asarray(result.longitudinal, dtype=np.float64),
            node_curves=None if getattr(result, "node_curves", None) is None else np.asarray(result.node_curves),
            frame_time_ms=float(result.frame_time_ms),
        )


@dataclass(frozen=True)
class StrainStudy:
    """Up to three apical views and their average (``GLS_AV``)."""

    analyses: dict[str, StrainAnalysis] = field(default_factory=dict)

    VIEW_ORDER: tuple[str, ...] = ("A4C", "A2C", "A3C")
    # EACVI: at most one excluded segment per view for the average to stay valid.
    MIN_VIEWS_FOR_AVERAGE: int = 1

    def with_view(self, analysis: StrainAnalysis) -> StrainStudy:
        """Return a copy with this view replaced (the newest run wins)."""
        updated = dict(self.analyses)
        updated[normalise_view(analysis.view)] = analysis
        return StrainStudy(analyses=updated)

    def view_gls(self, view: str) -> float | None:
        analysis = self.analyses.get(normalise_view(view))
        return None if analysis is None else analysis.gls

    def views_measured(self) -> tuple[str, ...]:
        return tuple(view for view in self.VIEW_ORDER if view in self.analyses)

    def views_valid(self) -> tuple[str, ...]:
        return tuple(view for view in self.VIEW_ORDER if view in self.analyses and self.analyses[view].is_valid)

    def gls_average(self, *, only_valid: bool = True) -> float | None:
        """``GLS_AV`` = mean of the per-view GLS values that passed QC.

        With ``only_valid=False`` every measured view counts, which is what a
        report needs when the user overrides the QC status.
        """
        views = self.views_valid() if only_valid else self.views_measured()
        values = [self.analyses[view].gls for view in views]
        values = [value for value in values if value is not None and np.isfinite(value)]
        if len(values) < self.MIN_VIEWS_FOR_AVERAGE:
            return None
        return float(np.mean(values))

    def merged_segments(self, *, only_valid: bool = True) -> dict[int, float]:
        """18-segment merge: the first measured value per segment wins.

        Views do not overlap in the standard 18-segment model, so no averaging
        between views happens here — a segment that only A2C can see is taken
        from A2C alone, and its view is recorded in :meth:`segment_sources`.
        """
        merged: dict[int, float] = {}
        for view in self.VIEW_ORDER:
            analysis = self.analyses.get(view)
            if analysis is None or (only_valid and not analysis.is_valid):
                continue
            for seg, value in analysis.segment_values.items():
                if seg in merged or value is None or not np.isfinite(value):
                    continue
                merged[int(seg)] = float(value)
        return merged

    def segment_sources(self) -> dict[int, str]:
        """Which view each merged segment came from."""
        sources: dict[int, str] = {}
        for view in self.VIEW_ORDER:
            analysis = self.analyses.get(view)
            if analysis is None:
                continue
            for seg in analysis.segment_values:
                sources.setdefault(int(seg), view)
        return sources

    def bullseye_segments(self, *, only_valid: bool = True) -> dict[int, float]:
        """Merged segments in bull's-eye order (all 18 slots present)."""
        merged = self.merged_segments(only_valid=only_valid)
        return {seg: merged[seg] for seg in segment_ids_in_bullseye_order() if seg in merged}

    def missing_segments(self) -> tuple[int, ...]:
        """Segments no analysed view can measure (never fabricated)."""
        available: set[int] = set()
        for view in self.views_measured():
            available.update(view_segment_ids(view))
        merged = set(self.merged_segments())
        return tuple(sorted(available - merged))

    def to_dict(self, *, with_curves: bool = False) -> dict:
        return {
            "schema_version": ANALYSIS_SCHEMA_VERSION,
            "views_measured": list(self.views_measured()),
            "views_valid": list(self.views_valid()),
            "gls_by_view": {view: self.view_gls(view) for view in self.views_measured()},
            "gls_average": self.gls_average(),
            "segments_merged": {str(seg): value for seg, value in sorted(self.merged_segments().items())},
            "segment_sources": {str(seg): view for seg, view in sorted(self.segment_sources().items())},
            "analyses": {
                view: analysis.to_dict(with_curves=with_curves) for view, analysis in sorted(self.analyses.items())
            },
        }

    @classmethod
    def from_analyses(cls, analyses: Iterable[StrainAnalysis]) -> StrainStudy:
        study = cls()
        for analysis in analyses:
            study = study.with_view(analysis)
        return study


def study_from_results(results: Mapping[str, StrainResult]) -> StrainStudy:
    """Convenience helper: ``{view: StrainResult}`` → :class:`StrainStudy`."""
    return StrainStudy.from_analyses(StrainAnalysis.from_result(result, view=view) for view, result in results.items())
