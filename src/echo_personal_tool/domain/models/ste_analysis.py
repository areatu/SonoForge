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
from typing import Any

import numpy as np

from echo_personal_tool.domain.models.measurements import ContourLineage, StrainReport
from echo_personal_tool.domain.models.speckle import StrainResult
from echo_personal_tool.domain.services.myocardial_work import myocardial_work_from_analysis
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
DEFINITION_LAYERS = (
    "LV layers endo/mid/epi of one segmentation; a layer's GLS is the peak of "
    "that layer's global longitudinal curve — the same definition as the "
    "reported GLS, computed on the layer's own material line (issue 646)"
)
#: Voigt 2015 requires the report to declare the sampling extent, the handling of
#: LV translation and the regularization — otherwise "GLS" is not comparable.
DEFINITION_COMPARABILITY = (
    "comparable only together with the declared ROI sampling extent, "
    "LV translation compensation and regularization settings"
)
#: Which wall sits on which side of the image is part of a segment name: the
#: module assumes the vendor convention (apex up, the view's first wall on the
#: left of the screen) unless the user declares a mirrored display.
DEFINITION_SEGMENT_SIDES = "left / right wall of the displayed image under the view's side convention"

ANALYSIS_SCHEMA_VERSION = 2


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


@dataclass(frozen=True)
class StrainAnalysis:
    """One analysed view: values, provenance and quality in one record."""

    view: str = "A4C"
    #: The endocardial contour this view was tracked from (issue 555), with
    #: its identity, clip and frame. Provenance only — outside equality, like
    #: the Simpson lineage: two analyses are the same measurement whether or
    #: not the caller recorded where the contour came from.
    source_contour: ContourLineage | None = field(default=None, compare=False)
    schema_version: int = ANALYSIS_SCHEMA_VERSION
    segmentation: str = "AHA-18"
    definition_gls: str = DEFINITION_GLS
    definition_ess: str = DEFINITION_ESS
    definition_ttp: str = DEFINITION_TTP
    layer: str = DEFINITION_LAYER
    definition_layers: str = DEFINITION_LAYERS
    definition_comparability: str = DEFINITION_COMPARABILITY
    definition_segment_sides: str = DEFINITION_SEGMENT_SIDES
    # Spatial extent of the sampling (mm) and the processing that shaped the
    # number: kernel footprint, node spacing, regularization text, whether LV
    # translation was compensated, and the acquisition frame rate.
    sampling_kernel_mm: float = 0.0
    sampling_node_spacing_mm: float = 0.0
    regularization: str = ""
    # "left=inferoseptal / right=anterolateral" (+ mirrored marker): segment
    # names are only comparable when the side convention is declared.
    segment_sides: str = ""
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
    #: А.5 burned-ECG strip located in the clip's pixels — ``(row_start,
    #: row_end, col_start, col_end)`` or ``None``; the study metadata remembers
    #: where the vendor drew the strip (it travels with the strain record).
    burned_ecg_strip: tuple[int, int, int, int] | None = None
    #: А.6 LA strain of this view (plan #644): reservoir/conduit/booster
    #: magnitudes in percent (``None`` where not measurable) and the NCC mean
    #: of the LA arc tracking. All ``None`` when the clip has no LA contour.
    la_reservoir_pct: float | None = None
    la_conduit_pct: float | None = None
    la_booster_pct: float | None = None
    la_tracking_quality: float | None = None
    #: А.7 RV free-wall strain of this view (plan #645): the peak-systolic
    #: GLS of the traced free wall (LV sign convention) and the NCC mean of
    #: the wall tracking. Both ``None`` when the clip has no free-wall trace.
    rv_gls_pct: float | None = None
    rv_tracking_quality: float | None = None
    #: А.8 layered strain of this view (plan #646): per-layer GLS
    #: (``endo``/``mid``/``epi``, same definition as ``gls`` — the endocardial
    #: entry repeats it as the layer-record cross-check) and the transmural
    #: gradient ``GLS_epi − GLS_endo`` in percentage points (positive when the
    #: endocardium deforms more — the normal direction). Empty/``None`` when
    #: the run produced no layer curves.
    layer_gls: dict[str, float | None] = field(default_factory=dict)
    transmural_gradient_pp: float | None = None
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
            "source_contour": (
                None
                if self.source_contour is None
                else {
                    "measurement_id": self.source_contour.measurement_id,
                    "revision": self.source_contour.revision,
                    "sop_instance_uid": self.source_contour.sop_instance_uid,
                    "frame_index": self.source_contour.frame_index,
                }
            ),
            "segmentation": self.segmentation,
            "definitions": {
                "gls": self.definition_gls,
                "ess": self.definition_ess,
                "ttp": self.definition_ttp,
                "layer": self.layer,
                "layers": self.definition_layers,
                "comparability": self.definition_comparability,
                "segment_sides_convention": self.definition_segment_sides,
            },
            "sampling": {
                "kernel_mm": _finite(self.sampling_kernel_mm),
                "node_spacing_mm": _finite(self.sampling_node_spacing_mm),
                "translation_compensation": self.translation_compensation,
                "regularization": self.regularization,
                "segment_sides": self.segment_sides,
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
                # А.8: written only when the run measured layers — the wire
                # shape of a single-layer analysis stays what it was.
                "layer_gls": {layer: _finite(self.layer_gls.get(layer)) for layer in sorted(self.layer_gls)}
                if self.layer_gls
                else {},
                "transmural_gradient_pp": _finite(self.transmural_gradient_pp) if self.layer_gls else None,
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
    def from_result(
        cls,
        result: StrainResult,
        *,
        view: str | None = None,
        source: ContourLineage | None = None,
    ) -> StrainAnalysis:
        """Build the record from a worker result (the only conversion point).

        ``source`` is the endocardial contour the tracking was launched on
        (issue 555).  The worker result itself carries no clip identity, so the
        caller that knows the contour passes it here; without it the analysis
        honestly records no lineage.
        """
        metrics = getattr(result, "segment_metrics", {}) or {}
        segment_ess = {int(seg): _finite(getattr(metric, "ess", None)) for seg, metric in metrics.items()}
        la_metrics = getattr(result, "la_strain", None)
        rv_metrics = getattr(result, "rv_strain", None)
        # А.8 (issue 646): the gradient is derived from the result's layer
        # GLS values here, so the record, the report and the window all read
        # the same number from the same conversion point.
        layer_gls = {str(layer): _finite(value) for layer, value in (getattr(result, "layer_gls", {}) or {}).items()}
        from echo_personal_tool.domain.services.layered_strain import transmural_gradient_pp

        finite_layer_gls = {layer: value for layer, value in layer_gls.items() if value is not None}
        gradient = transmural_gradient_pp(finite_layer_gls)
        return cls(
            view=normalise_view(view or getattr(result, "view", "A4C")),
            source_contour=source if source is not None and source.recorded else None,
            gls=_finite(result.gls),
            ess=_finite(getattr(result, "ess", None)),
            peak=_finite(getattr(result, "peak_strain", None)),
            gls_segment_mean=_finite(getattr(result, "gls_segment_mean", None)),
            time_to_peak_ms=_finite(getattr(result, "time_to_peak_ms", None)),
            post_systolic_index=_finite(getattr(result, "post_systolic_index", None)),
            drift=_finite(getattr(result, "drift_measured", None)),
            is_post_systolic=bool(getattr(result, "is_post_systolic", False)),
            burned_ecg_strip=_strip_tuple(getattr(result, "burned_ecg_strip", None)),
            la_reservoir_pct=None if la_metrics is None else _finite(la_metrics.reservoir_pct),
            la_conduit_pct=None if la_metrics is None else _finite(la_metrics.conduit_pct),
            la_booster_pct=None if la_metrics is None else _finite(la_metrics.booster_pct),
            la_tracking_quality=_finite(getattr(result, "la_tracking_quality", None)),
            rv_gls_pct=None if rv_metrics is None else _finite(rv_metrics.gls_pct),
            rv_tracking_quality=_finite(getattr(result, "rv_tracking_quality", None)),
            layer_gls=layer_gls,
            transmural_gradient_pp=gradient,
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
            segment_sides=str(getattr(result, "segment_sides", "")),
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
        values = [value for view in views if (value := self.analyses[view].gls) is not None and np.isfinite(value)]
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


def strain_report_from_study(
    study: StrainStudy,
    *,
    contour_source: str = "manual",
    blood_pressure: tuple[float, float] | None = None,
) -> StrainReport | None:
    """Project a :class:`StrainStudy` onto the protocol record (plan §5.3 п.6).

    The study holds everything the strain window needs; the protocol needs the
    reportable subset and nothing invented. Views without a finite GLS are left
    out entirely instead of being written as ``0``, and ``gls_average`` is taken
    from :meth:`StrainStudy.gls_average` so the report and the UI can never
    disagree about which views entered the average.

    ``blood_pressure`` — the cuff ``(SBP, DBP)`` mmHg from the report header:
    when supplied, every view with a usable curve gets its Myocardial Work
    loop (plan А.9, :mod:`myocardial_work`) and the protocol carries the
    per-view GWI/GCW/GWW/GWE with the mean over the views. Without it the MW
    fields stay empty — the loop is never built from an invented pressure.

    Returns ``None`` when no view has a usable number — a study without strain
    simply has no strain section in the report.
    """
    gls_by_view: list[tuple[str, float]] = []
    qc_by_view: list[tuple[str, str]] = []
    avc_by_view: list[tuple[str, str]] = []
    lineage_by_view: list[tuple[str, ContourLineage]] = []
    mw_by_view: list[tuple[str, float, float, float, float]] = []
    la_by_view: list[tuple[str, float, float | None, float | None]] = []
    rv_by_view: list[tuple[str, float]] = []
    layers_by_view: list[tuple[str, float, float | None, float | None]] = []
    layer_gradients: list[float] = []
    for view in study.views_measured():
        analysis = study.analyses[view]
        value = _finite(analysis.gls)
        if value is None:
            continue
        gls_by_view.append((view, value))
        qc_by_view.append((view, analysis.qc_status))
        avc_by_view.append((view, analysis.avc_source))
        if analysis.source_contour is not None:
            lineage_by_view.append((view, analysis.source_contour))
        la_reservoir = _finite(analysis.la_reservoir_pct)
        if la_reservoir is not None:
            la_by_view.append(
                (
                    view,
                    la_reservoir,
                    _finite(analysis.la_conduit_pct),
                    _finite(analysis.la_booster_pct),
                )
            )
        rv_gls = _finite(analysis.rv_gls_pct)
        if rv_gls is not None:
            rv_by_view.append((view, rv_gls))
        # А.8 (issue 646): a view enters the layer rows when its run measured
        # the endocardial layer curve — mid/epi may be missing on their own.
        layer_endo = _finite(analysis.layer_gls.get("endo"))
        if layer_endo is not None:
            layers_by_view.append(
                (
                    view,
                    layer_endo,
                    _finite(analysis.layer_gls.get("mid")),
                    _finite(analysis.layer_gls.get("epi")),
                )
            )
            view_gradient = _finite(analysis.transmural_gradient_pp)
            if view_gradient is not None:
                layer_gradients.append(view_gradient)
        if blood_pressure is not None:
            work = myocardial_work_from_analysis(
                analysis.global_curve,
                ed_index=analysis.ed_index,
                avc_index=analysis.avc_index,
                sbp_mmhg=float(blood_pressure[0]),
                dbp_mmhg=float(blood_pressure[1]),
            )
            cycle = work.cycles[0] if work.cycles else None
            if cycle is not None:
                mw_by_view.append((view, cycle.gwi_mmhg_pct, cycle.gcw_mmhg_pct, cycle.gww_mmhg_pct, cycle.gwe_percent))
    if not gls_by_view:
        return None

    la_summary: dict[str, float | None] = {"la_reservoir_pct": None, "la_conduit_pct": None, "la_booster_pct": None}
    if la_by_view:
        # Mean over the views that produced each phase — conduit/booster may
        # be missing on one view while reservoir exists on both.

        def _column(column: int) -> list[float]:
            out: list[float] = []
            for row in la_by_view:
                item = row[column]
                if item is not None:
                    out.append(float(item))
            return out

        for key, column in (("la_reservoir_pct", 1), ("la_conduit_pct", 2), ("la_booster_pct", 3)):
            values = _column(column)
            la_summary[key] = float(np.mean(values)) if values else None

    rv_gls_pct: float | None = None
    if rv_by_view:
        rv_gls_pct = float(np.mean([row[1] for row in rv_by_view]))

    layer_summary: dict[str, float | None] = {"layer_mid_pct": None, "layer_epi_pct": None, "layer_gradient_pp": None}
    if layers_by_view:
        # Means cover the views that produced each layer; the gradient mean
        # covers the views that measured both layers — never averaged from
        # missing halves.
        mids = [row[2] for row in layers_by_view if row[2] is not None]
        epis = [row[3] for row in layers_by_view if row[3] is not None]
        layer_summary["layer_mid_pct"] = float(np.mean(mids)) if mids else None
        layer_summary["layer_epi_pct"] = float(np.mean(epis)) if epis else None
        layer_summary["layer_gradient_pp"] = float(np.mean(layer_gradients)) if layer_gradients else None

    first = study.analyses[gls_by_view[0][0]]
    mw_summary: dict[str, float | None] = {
        "gwi_mmhg_pct": None,
        "gcw_mmhg_pct": None,
        "gww_mmhg_pct": None,
        "gwe_percent": None,
    }
    if mw_by_view:
        for index, key in enumerate(("gwi_mmhg_pct", "gcw_mmhg_pct", "gww_mmhg_pct", "gwe_percent"), start=1):
            mw_summary[key] = float(np.mean([row[index] for row in mw_by_view]))
    return StrainReport(
        gls_by_view=tuple(gls_by_view),
        qc_by_view=tuple(qc_by_view),
        gls_average=study.gls_average(),
        views_valid=study.views_valid(),
        segmentation=first.segmentation,
        avc_source_by_view=tuple(avc_by_view),
        segments_missing=len(study.missing_segments()),
        mw_by_view=tuple(mw_by_view),
        gwi_mmhg_pct=mw_summary["gwi_mmhg_pct"],
        gcw_mmhg_pct=mw_summary["gcw_mmhg_pct"],
        gww_mmhg_pct=mw_summary["gww_mmhg_pct"],
        gwe_percent=mw_summary["gwe_percent"],
        blood_pressure_mmhg=(float(blood_pressure[0]), float(blood_pressure[1]))
        if blood_pressure is not None
        else None,
        burned_ecg_strip=next(
            (
                analysis.burned_ecg_strip
                for analysis in study.analyses.values()
                if analysis.burned_ecg_strip is not None
            ),
            None,
        ),
        la_strain_by_view=tuple(la_by_view),
        la_reservoir_pct=la_summary["la_reservoir_pct"],
        la_conduit_pct=la_summary["la_conduit_pct"],
        la_booster_pct=la_summary["la_booster_pct"],
        rv_strain_by_view=tuple(rv_by_view),
        rv_gls_pct=rv_gls_pct,
        layer_gls_by_view=tuple(layers_by_view),
        layer_mid_pct=layer_summary["layer_mid_pct"],
        layer_epi_pct=layer_summary["layer_epi_pct"],
        layer_gradient_pp=layer_summary["layer_gradient_pp"],
        contour_source=contour_source,
        lineage_by_view=tuple(lineage_by_view),
    )


def _strip_tuple(value: object) -> tuple[int, int, int, int] | None:
    """A 4-int strip rect from the result record, ``None`` when absent/malformed."""
    if not isinstance(value, tuple) or len(value) != 4 or not all(isinstance(v, (int, float)) for v in value):
        return None
    return (int(value[0]), int(value[1]), int(value[2]), int(value[3]))


def study_from_results(results: Mapping[str, StrainResult]) -> StrainStudy:
    """Convenience helper: ``{view: StrainResult}`` → :class:`StrainStudy`."""
    return StrainStudy.from_analyses(StrainAnalysis.from_result(result, view=view) for view, result in results.items())
