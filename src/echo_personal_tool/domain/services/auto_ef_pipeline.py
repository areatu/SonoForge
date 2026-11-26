"""End-to-end one-click biplane Auto-EF pipeline in the pure domain layer.

Chains view classification (A4C + A2C selection), cardiac phase detection
(ECG / image phase field / cavity-area fallback), multi-view LV cavity
segmentation with optional temporal fusion, biplane Simpson volume/LVEF
calculation, interactive contour edit recalculation, and full provenance.
"""

from __future__ import annotations

import inspect
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any, cast

import numpy as np

from echo_personal_tool.domain.calculations.lvef_simpson import (
    calculate,
    explain_lv_auto_reject_reason,
)
from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.models.ecg import EcgWaveform, RPeakResult
from echo_personal_tool.domain.models.measurements import LvefResult
from echo_personal_tool.domain.models.result_provenance import (
    CalibrationRef,
    Freshness,
    InputReference,
    QCStatus,
    ResultProvenance,
    ResultQC,
    SourceIdentity,
    make_provenance,
    stable_id_for_content,
)
from echo_personal_tool.domain.models.temporal_fusion import TemporalFusionConfig
from echo_personal_tool.domain.ports import IOnnxSegmenter, IViewRecognizer
from echo_personal_tool.domain.services.contour_geometry import apex_point
from echo_personal_tool.domain.services.lv_temporal_fusion import (
    compute_window,
    temporal_fuse,
)
from echo_personal_tool.domain.services.mbs_lite_service import refine_open_arc_contour
from echo_personal_tool.domain.services.phase_source import CinePhaseSource, PhaseRequest
from echo_personal_tool.domain.services.segmentation_service import (
    closed_polygon_to_open_arc,
    exclude_papillary_concavities,
    lv_cavity_mask_to_open_arc,
    mask_to_contour,
    papillary_mask_cleanup,
    smooth_contour,
)

AUTO_EF_RESULT_ID = "lv.ef_bp.auto"
AUTO_EF_ALGO_VERSION = "1.0"
_MIN_VIEW_CONFIDENCE = 0.25


@dataclass(frozen=True)
class AutoEfClipCandidate:
    """One cine clip candidate offered to the Auto-EF study pipeline."""

    sop_instance_uid: str
    frames: Sequence[np.ndarray] | np.ndarray
    pixel_spacing_mm: tuple[float, float] | None = None
    frame_time_ms: float | None = None
    ecg: EcgWaveform | None = None
    r_peak_result: RPeakResult | None = None
    view_override: str | None = None
    ed_override: int | None = None
    es_override: int | None = None
    roi_xyxy: tuple[float, float, float, float] | None = None
    crop_mode: str = "center_square"
    series_uid: str = ""
    is_cine: bool = False


@dataclass(frozen=True)
class AutoEfViewSelection:
    """Resolved apical view clip, cardiac phases, and segmented ED/ES contours."""

    view: str
    sop_instance_uid: str
    series_uid: str
    view_confidence: float
    view_source: str
    ed_frame_index: int
    es_frame_index: int
    phase_source: str
    phase_confidence: float
    heart_rate_bpm: float | None
    ed_contour: Contour | None
    es_contour: Contour | None
    ed_frame: np.ndarray | None = None
    es_frame: np.ndarray | None = None
    pixel_spacing_mm: tuple[float, float] | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class AutoEfPipelineResult:
    """Complete result of one-click Auto-EF with contours and provenance."""

    study_uid: str
    a4c: AutoEfViewSelection | None
    a2c: AutoEfViewSelection | None
    contours: tuple[Contour, ...]
    pixel_spacing_mm: tuple[float, float] | None
    lvef_result: LvefResult | None
    edvi_ml_m2: float | None
    esvi_ml_m2: float | None
    provenance: ResultProvenance
    warnings: tuple[str, ...] = ()

    @property
    def lvef_percent(self) -> float | None:
        return self.lvef_result.lvef_percent if self.lvef_result is not None else None

    @property
    def method(self) -> str | None:
        return self.lvef_result.method if self.lvef_result is not None else None

    @property
    def edv_ml(self) -> float | None:
        if self.lvef_result is None:
            return None
        if self.lvef_result.edv_bi_ml is not None:
            return self.lvef_result.edv_bi_ml
        if self.lvef_result.a4c is not None and self.lvef_result.a4c.edv_ml is not None:
            return self.lvef_result.a4c.edv_ml
        if self.lvef_result.a2c is not None:
            return self.lvef_result.a2c.edv_ml
        return None

    @property
    def esv_ml(self) -> float | None:
        if self.lvef_result is None:
            return None
        if self.lvef_result.esv_bi_ml is not None:
            return self.lvef_result.esv_bi_ml
        if self.lvef_result.a4c is not None and self.lvef_result.a4c.esv_ml is not None:
            return self.lvef_result.a4c.esv_ml
        if self.lvef_result.a2c is not None:
            return self.lvef_result.a2c.esv_ml
        return None

    @property
    def sv_ml(self) -> float | None:
        return self.lvef_result.sv_ml if self.lvef_result is not None else None

    @property
    def is_biplane(self) -> bool:
        return bool(self.lvef_result is not None and self.lvef_result.method == "simpson_biplan")


def _frames_list(frames: Sequence[np.ndarray] | np.ndarray) -> list[np.ndarray]:
    if isinstance(frames, np.ndarray):
        if frames.ndim == 2 or (frames.ndim == 3 and frames.shape[2] == 3):
            return [frames]
        return [np.asarray(frames[i]) for i in range(frames.shape[0])]
    return [np.asarray(frame) for frame in frames]


def _sample_view_frames(frames: list[np.ndarray], max_samples: int = 8) -> list[np.ndarray]:
    if len(frames) <= max_samples:
        return frames
    indices = np.linspace(0, len(frames) - 1, num=max_samples, dtype=int)
    return [frames[int(i)] for i in indices]


def _call_segmenter(
    segmenter: IOnnxSegmenter,
    frame: np.ndarray,
    *,
    roi_xyxy: tuple[float, float, float, float] | None,
    crop_mode: str,
) -> np.ndarray:
    try:
        sig = inspect.signature(segmenter.segment)
        accepts_kwargs = "roi_xyxy" in sig.parameters or any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
        )
    except (TypeError, ValueError):
        accepts_kwargs = False
    if accepts_kwargs:
        return cast(np.ndarray, cast(Any, segmenter).segment(frame, roi_xyxy=roi_xyxy, crop_mode=crop_mode))
    return segmenter.segment(frame)


def select_apical_clips(
    candidates: Sequence[AutoEfClipCandidate],
    view_recognizer: IViewRecognizer | None,
    *,
    min_confidence: float = _MIN_VIEW_CONFIDENCE,
) -> tuple[tuple[AutoEfClipCandidate, float, str] | None, tuple[AutoEfClipCandidate, float, str] | None]:
    """Select highest-confidence A4C and A2C clips from study candidates."""
    scored: list[tuple[str, float, str, AutoEfClipCandidate]] = []
    for clip in candidates:
        frames = _frames_list(clip.frames)
        if not frames:
            continue
        if clip.view_override:
            label = clip.view_override.strip().upper()
            if label in {"A4C", "A2C"}:
                scored.append((label, 1.0, "override", clip))
            continue
        if view_recognizer is None:
            continue
        recognized = view_recognizer.recognize(_sample_view_frames(frames))
        label = str(recognized.view).strip().upper()
        conf = float(recognized.confidence)
        if label in {"A4C", "A2C"} and conf >= min_confidence:
            scored.append((label, conf, "classifier", clip))

    best_a4c = max((item for item in scored if item[0] == "A4C"), key=lambda x: x[1], default=None)
    used_uid = best_a4c[3].sop_instance_uid if best_a4c is not None else None
    a2c_pool = [item for item in scored if item[0] == "A2C" and item[3].sop_instance_uid != used_uid]
    best_a2c = max(a2c_pool, key=lambda x: x[1], default=None)
    return (
        (best_a4c[3], best_a4c[1], best_a4c[2]) if best_a4c is not None else None,
        (best_a2c[3], best_a2c[1], best_a2c[2]) if best_a2c is not None else None,
    )


def _select_phases_by_cavity_area(
    frames: list[np.ndarray],
    segmenter: IOnnxSegmenter,
    *,
    roi_xyxy: tuple[float, float, float, float] | None,
    crop_mode: str,
) -> tuple[int, int, int, int]:
    if len(frames) == 1:
        a0 = int(np.count_nonzero(_call_segmenter(segmenter, frames[0], roi_xyxy=roi_xyxy, crop_mode=crop_mode)))
        return 0, 0, a0, a0
    if len(frames) == 2:
        m0 = _call_segmenter(segmenter, frames[0], roi_xyxy=roi_xyxy, crop_mode=crop_mode)
        m1 = _call_segmenter(segmenter, frames[1], roi_xyxy=roi_xyxy, crop_mode=crop_mode)
        a0, a1 = int(np.count_nonzero(m0)), int(np.count_nonzero(m1))
        return (0, 1, a0, a1) if a0 >= a1 else (1, 0, a1, a0)
    stride = max(1, len(frames) // 24)
    sampled = list(range(0, len(frames), stride))
    areas = {
        idx: int(np.count_nonzero(_call_segmenter(segmenter, frames[idx], roi_xyxy=roi_xyxy, crop_mode=crop_mode)))
        for idx in sampled
    }
    ed_idx = max(sampled, key=lambda idx: areas[idx])
    es_candidates = [idx for idx in sampled if idx != ed_idx]
    es_idx = min(es_candidates, key=lambda idx: areas[idx])
    return ed_idx, es_idx, areas[ed_idx], areas[es_idx]


def select_ed_es_frames(
    clip: AutoEfClipCandidate,
    frames: list[np.ndarray],
    segmenter: IOnnxSegmenter,
) -> tuple[int, int, str, float, float | None, tuple[str, ...]]:
    """Determine (ed_idx, es_idx, phase_source, confidence, hr_bpm, warnings)."""
    n_frames = len(frames)
    if (
        clip.ed_override is not None
        and clip.es_override is not None
        and 0 <= clip.ed_override < n_frames
        and 0 <= clip.es_override < n_frames
        and clip.ed_override != clip.es_override
    ):
        return int(clip.ed_override), int(clip.es_override), "override", 1.0, None, ()

    if n_frames >= 6 and (clip.ecg is not None or clip.r_peak_result is not None):
        gray_stack = np.stack(
            [f.mean(axis=2) if (f.ndim == 3 and f.shape[2] == 3) else f for f in frames],
            axis=0,
        )
        decision = CinePhaseSource().resolve(
            PhaseRequest(
                n_frames=n_frames,
                frame_time_ms=clip.frame_time_ms,
                ecg=clip.ecg,
                r_peak_result=clip.r_peak_result,
                frames=gray_stack,
            )
        )
        ed_idx = int(decision.mapping.ed_frame_index)
        es_idx = int(decision.mapping.es_frame_index)
        if 0 <= ed_idx < n_frames and 0 <= es_idx < n_frames and ed_idx != es_idx and decision.confidence > 0.0:
            return (
                ed_idx,
                es_idx,
                decision.source,
                float(decision.confidence),
                decision.heart_rate_bpm,
                decision.warnings,
            )

    ed_idx, es_idx, max_area, min_area = _select_phases_by_cavity_area(
        frames,
        segmenter,
        roi_xyxy=clip.roi_xyxy,
        crop_mode=clip.crop_mode,
    )
    if max_area > 0 and max_area > min_area and ed_idx != es_idx:
        return ed_idx, es_idx, "cavity_area", 0.85, None, ()

    if n_frames >= 6:
        gray_stack = np.stack(
            [f.mean(axis=2) if (f.ndim == 3 and f.shape[2] == 3) else f for f in frames],
            axis=0,
        )
        decision = CinePhaseSource().resolve(
            PhaseRequest(
                n_frames=n_frames,
                frame_time_ms=clip.frame_time_ms,
                ecg=None,
                r_peak_result=None,
                frames=gray_stack,
            )
        )
        b_ed = int(decision.mapping.ed_frame_index)
        b_es = int(decision.mapping.es_frame_index)
        if 0 <= b_ed < n_frames and 0 <= b_es < n_frames and b_ed != b_es and decision.confidence > 0.0:
            return (
                b_ed,
                b_es,
                decision.source,
                float(decision.confidence),
                decision.heart_rate_bpm,
                decision.warnings,
            )

    return ed_idx, es_idx, "cavity_area", 0.5, None, ("phase_fallback_cavity_area",)


def _mask_to_lv_contour(
    mask: np.ndarray,
    frame: np.ndarray,
    *,
    phase: str,
    view: str,
    frame_index: int,
    sop_instance_uid: str,
    auto_refine: bool,
    is_cine: bool,
) -> tuple[Contour, np.ndarray] | None:
    original_shape = (int(frame.shape[0]), int(frame.shape[1]))
    try:
        open_points, annulus, apex, cleaned = lv_cavity_mask_to_open_arc(
            mask,
            original_shape=original_shape,
            phase=phase,
            view_hint=view,
            num_nodes=32,
        )
    except ValueError:
        cleaned = papillary_mask_cleanup(mask, phase=phase)
        if int(np.count_nonzero(cleaned)) < 80:
            return None
        closed_pts = smooth_contour(mask_to_contour(cleaned, original_shape), num_nodes=32)
        if not closed_pts:
            return None
        try:
            open_points, annulus = closed_polygon_to_open_arc(closed_pts, view_hint=view)
        except ValueError:
            return None
        apex = apex_point(open_points, annulus)

    refined_pts = exclude_papillary_concavities(open_points, annulus, apex, phase=phase)
    draft = Contour(
        phase=phase.lower(),
        view=view.upper(),
        chamber="LV",
        mitral_annulus=annulus,
        apex_landmark=apex,
        points=refined_pts,
        source="ai",
        num_nodes=len(refined_pts),
        frame_index=frame_index,
        sop_instance_uid=sop_instance_uid,
        review_pending=True,
    )
    if auto_refine:
        refined, _ = refine_open_arc_contour(frame, draft, cine=is_cine)
        draft = replace(refined, phase=phase.lower(), view=view.upper(), review_pending=True)
    return draft, cleaned


def _segment_phase_with_fusion(
    clip: AutoEfClipCandidate,
    frames: list[np.ndarray],
    frame_index: int,
    *,
    phase: str,
    view: str,
    segmenter: IOnnxSegmenter,
    temporal_fusion: TemporalFusionConfig | None,
    auto_refine: bool,
) -> tuple[Contour | None, tuple[str, ...]]:
    center_frame = frames[frame_index]
    raw_mask = _call_segmenter(
        segmenter,
        center_frame,
        roi_xyxy=clip.roi_xyxy,
        crop_mode=clip.crop_mode,
    )
    built = _mask_to_lv_contour(
        raw_mask,
        center_frame,
        phase=phase,
        view=view,
        frame_index=frame_index,
        sop_instance_uid=clip.sop_instance_uid,
        auto_refine=auto_refine,
        is_cine=clip.is_cine,
    )
    if built is None:
        return None, (f"{view.lower()}_{phase.lower()}_segmentation_empty",)
    contour, center_mask = built

    min_frames_for_fusion = max(12, 4 * temporal_fusion.window + 4) if temporal_fusion is not None else 0
    if temporal_fusion is not None and len(frames) >= min_frames_for_fusion:
        window_indices = [
            idx for idx in compute_window(frame_index, len(frames), temporal_fusion.window) if idx != frame_index
        ]
        neighbor_masks: dict[int, np.ndarray] = {}
        neighbor_contours: dict[int, Contour] = {}
        for idx in window_indices:
            n_mask = _call_segmenter(
                segmenter,
                frames[idx],
                roi_xyxy=clip.roi_xyxy,
                crop_mode=clip.crop_mode,
            )
            n_built = _mask_to_lv_contour(
                n_mask,
                frames[idx],
                phase=phase,
                view=view,
                frame_index=idx,
                sop_instance_uid=clip.sop_instance_uid,
                auto_refine=False,
                is_cine=clip.is_cine,
            )
            if n_built is not None:
                neighbor_contours[idx] = n_built[0]
                neighbor_masks[idx] = n_built[1]
        if neighbor_contours:
            fused = temporal_fuse(
                center_mask=center_mask,
                neighbor_masks=neighbor_masks,
                center_contour=contour,
                neighbor_contours=neighbor_contours,
                anchor_frame_index=frame_index,
                phase=phase,
                config=temporal_fusion,
                original_shape=(int(center_frame.shape[0]), int(center_frame.shape[1])),
            )
            contour = replace(
                fused.fused_contour,
                phase=phase.lower(),
                view=view.upper(),
                frame_index=frame_index,
                sop_instance_uid=clip.sop_instance_uid,
                review_pending=True,
            )

    reject = explain_lv_auto_reject_reason(contour, clip.pixel_spacing_mm, roi_xyxy=clip.roi_xyxy)
    if reject is not None:
        return contour, (f"{view.lower()}_{phase.lower()}_quality_review",)
    return contour, ()


def _contour_input_ref(contour: Contour, *, revision: int = 0) -> InputReference:
    serialized = ";".join(f"{x:.2f},{y:.2f}" for x, y in contour.points)
    ma_str = ""
    if contour.mitral_annulus is not None:
        (sx, sy), (lx, ly) = contour.mitral_annulus
        ma_str = f"{sx:.2f},{sy:.2f}:{lx:.2f},{ly:.2f}"
    digest = stable_id_for_content(contour.view, contour.phase, contour.sop_instance_uid or "", serialized, ma_str)
    return InputReference(
        measurement_id=f"contour.{contour.view.lower()}.{contour.phase.lower()}.{digest}",
        revision=revision,
        kind="contour",
        label=f"{contour.view}_{contour.phase.upper()}",
    )


def build_auto_ef_provenance(
    *,
    study_uid: str,
    contours: Sequence[Contour],
    pixel_spacing_mm: tuple[float, float] | None,
    lvef_result: LvefResult | None,
    a4c: AutoEfViewSelection | None,
    a2c: AutoEfViewSelection | None,
    warnings: Sequence[str],
    model_id: str = "echonet_seg_resnet50",
    model_hash: str = "",
    revision: int = 0,
    operator_confirmed: bool = False,
) -> ResultProvenance:
    """Build v7-compliant ResultProvenance for an Auto-EF result."""
    safe_study_uid = study_uid.strip() or "study.unknown"
    primary = a4c if a4c is not None else a2c
    source = SourceIdentity(
        study_uid=safe_study_uid,
        sop_instance_uid=primary.sop_instance_uid if primary is not None else "",
        series_uid=primary.series_uid if primary is not None else "",
        ed_index=primary.ed_frame_index if primary is not None else None,
        es_index=primary.es_frame_index if primary is not None else None,
        view="BIPLANE" if (a4c is not None and a2c is not None) else (primary.view if primary else ""),
        chamber="LV",
    )
    calibration: tuple[CalibrationRef, ...] = ()
    if pixel_spacing_mm is not None and pixel_spacing_mm[0] > 0 and pixel_spacing_mm[1] > 0:
        calibration = (
            CalibrationRef(
                kind="pixel",
                value=(float(pixel_spacing_mm[0]), float(pixel_spacing_mm[1])),
                source_instance_uid=source.sop_instance_uid,
            ),
        )
    has_ef = lvef_result is not None and lvef_result.lvef_percent is not None
    is_biplane = bool(lvef_result is not None and lvef_result.method == "simpson_biplan")
    method_id = "auto_ef_simpson_biplane" if is_biplane else "auto_ef_simpson_monoplane"
    qc_status = (
        QCStatus.INVALID.value
        if not has_ef
        else (
            QCStatus.VALID.value
            if (operator_confirmed and is_biplane and not any(c.review_pending for c in contours))
            else QCStatus.REVIEW.value
        )
    )
    qc = ResultQC(
        status=qc_status,
        coverage=1.0 if is_biplane else (0.5 if has_ef else 0.0),
        reasons=tuple(dict.fromkeys(warnings)),
        fallback="" if is_biplane else ("monoplane_only" if has_ef else "unavailable"),
    )
    freshness = Freshness.FRESH.value if has_ef else Freshness.UNAVAILABLE.value
    return make_provenance(
        result_id=AUTO_EF_RESULT_ID,
        method_id=method_id,
        family="simpson",
        source=source,
        inputs=tuple(_contour_input_ref(c, revision=revision) for c in contours),
        calibration=calibration,
        units="%",
        definition="Biplane method of disks LVEF = (EDV - ESV) / EDV * 100",
        qc=qc,
        freshness=freshness,
        revision=revision,
        algorithm_version=AUTO_EF_ALGO_VERSION,
        model_id=model_id,
        model_hash=model_hash,
    )


def _indexed_volumes(
    lvef_result: LvefResult | None,
    bsa_m2: float | None,
) -> tuple[float | None, float | None]:
    if lvef_result is None or bsa_m2 is None or bsa_m2 <= 0:
        return None, None
    edv = lvef_result.edv_bi_ml
    esv = lvef_result.esv_bi_ml
    if edv is None and lvef_result.a4c is not None:
        edv = lvef_result.a4c.edv_ml
        esv = lvef_result.a4c.esv_ml
    elif edv is None and lvef_result.a2c is not None:
        edv = lvef_result.a2c.edv_ml
        esv = lvef_result.a2c.esv_ml
    return (
        (edv / bsa_m2) if edv is not None else None,
        (esv / bsa_m2) if esv is not None else None,
    )


def _run_view_branch(
    view: str,
    selected: tuple[AutoEfClipCandidate, float, str],
    segmenter: IOnnxSegmenter,
    *,
    temporal_fusion: TemporalFusionConfig | None,
    auto_refine: bool,
) -> AutoEfViewSelection:
    clip, view_conf, view_src = selected
    frames = _frames_list(clip.frames)
    ed_idx, es_idx, phase_src, phase_conf, hr_bpm, phase_warns = select_ed_es_frames(
        clip,
        frames,
        segmenter,
    )
    ed_contour, ed_warns = _segment_phase_with_fusion(
        clip,
        frames,
        ed_idx,
        phase="ED",
        view=view,
        segmenter=segmenter,
        temporal_fusion=temporal_fusion,
        auto_refine=auto_refine,
    )
    es_contour, es_warns = _segment_phase_with_fusion(
        clip,
        frames,
        es_idx,
        phase="ES",
        view=view,
        segmenter=segmenter,
        temporal_fusion=temporal_fusion,
        auto_refine=auto_refine,
    )
    return AutoEfViewSelection(
        view=view,
        sop_instance_uid=clip.sop_instance_uid,
        series_uid=clip.series_uid,
        view_confidence=view_conf,
        view_source=view_src,
        ed_frame_index=ed_idx,
        es_frame_index=es_idx,
        phase_source=phase_src,
        phase_confidence=phase_conf,
        heart_rate_bpm=hr_bpm,
        ed_contour=ed_contour,
        es_contour=es_contour,
        ed_frame=frames[ed_idx] if 0 <= ed_idx < len(frames) else None,
        es_frame=frames[es_idx] if 0 <= es_idx < len(frames) else None,
        pixel_spacing_mm=clip.pixel_spacing_mm,
        warnings=(*phase_warns, *ed_warns, *es_warns),
    )


def run_auto_ef_pipeline(
    candidates: Sequence[AutoEfClipCandidate],
    *,
    study_uid: str,
    a4c_segmenter: IOnnxSegmenter,
    a2c_segmenter: IOnnxSegmenter | None = None,
    view_recognizer: IViewRecognizer | None = None,
    pixel_spacing_override: tuple[float, float] | None = None,
    bsa_m2: float | None = None,
    temporal_fusion: TemporalFusionConfig | None = None,
    auto_refine: bool = True,
    model_id: str = "echonet_seg_resnet50",
    model_hash: str = "",
) -> AutoEfPipelineResult:
    """Execute full one-click Auto-EF pipeline across study clip candidates."""
    warnings: list[str] = []
    eff_a2c = a2c_segmenter if (a2c_segmenter is not None and a2c_segmenter.is_available()) else a4c_segmenter

    if not a4c_segmenter.is_available():
        prov = build_auto_ef_provenance(
            study_uid=study_uid,
            contours=(),
            pixel_spacing_mm=pixel_spacing_override,
            lvef_result=None,
            a4c=None,
            a2c=None,
            warnings=("segmenter_unavailable",),
            model_id=model_id,
            model_hash=model_hash,
        )
        return AutoEfPipelineResult(
            study_uid=study_uid,
            a4c=None,
            a2c=None,
            contours=(),
            pixel_spacing_mm=pixel_spacing_override,
            lvef_result=None,
            edvi_ml_m2=None,
            esvi_ml_m2=None,
            provenance=prov,
            warnings=("segmenter_unavailable",),
        )

    sel_a4c, sel_a2c = select_apical_clips(candidates, view_recognizer)
    a4c_branch = (
        _run_view_branch("A4C", sel_a4c, a4c_segmenter, temporal_fusion=temporal_fusion, auto_refine=auto_refine)
        if sel_a4c is not None
        else None
    )
    a2c_branch = (
        _run_view_branch("A2C", sel_a2c, eff_a2c, temporal_fusion=temporal_fusion, auto_refine=auto_refine)
        if sel_a2c is not None
        else None
    )

    if a4c_branch is None and a2c_branch is None:
        warnings.append("no_apical_views_detected")
    elif a4c_branch is None or a2c_branch is None:
        warnings.append("monoplane_fallback_missing_second_view")

    contours: list[Contour] = []
    for branch in (a4c_branch, a2c_branch):
        if branch is not None:
            warnings.extend(branch.warnings)
            if branch.ed_contour is not None:
                contours.append(branch.ed_contour)
            if branch.es_contour is not None:
                contours.append(branch.es_contour)

    spacing = pixel_spacing_override
    if spacing is None and a4c_branch is not None and a4c_branch.pixel_spacing_mm is not None:
        spacing = a4c_branch.pixel_spacing_mm
    if spacing is None and a2c_branch is not None and a2c_branch.pixel_spacing_mm is not None:
        spacing = a2c_branch.pixel_spacing_mm
    if spacing is None:
        warnings.append("missing_pixel_spacing")
        calc_spacing: tuple[float, float] | None = (1.0, 1.0)
    else:
        calc_spacing = spacing

    calc_contours = tuple(replace(c, review_pending=False) for c in contours)
    lvef = calculate(calc_contours, calc_spacing) if calc_contours else None
    edvi, esvi = _indexed_volumes(lvef, bsa_m2) if spacing is not None else (None, None)
    dedup_warnings = tuple(dict.fromkeys(warnings))
    prov = build_auto_ef_provenance(
        study_uid=study_uid,
        contours=contours,
        pixel_spacing_mm=spacing,
        lvef_result=lvef,
        a4c=a4c_branch,
        a2c=a2c_branch,
        warnings=dedup_warnings,
        model_id=model_id,
        model_hash=model_hash,
    )
    return AutoEfPipelineResult(
        study_uid=study_uid,
        a4c=a4c_branch,
        a2c=a2c_branch,
        contours=tuple(contours),
        pixel_spacing_mm=spacing,
        lvef_result=lvef,
        edvi_ml_m2=edvi,
        esvi_ml_m2=esvi,
        provenance=prov,
        warnings=dedup_warnings,
    )


def recalculate_auto_ef(
    previous: AutoEfPipelineResult,
    updated_contours: Sequence[Contour],
    *,
    bsa_m2: float | None = None,
    operator_confirmed: bool = False,
) -> AutoEfPipelineResult:
    """Recalculate biplane/monoplane Auto-EF after contour editing or confirmation."""
    prev_by_key = {(c.view.upper(), c.phase.lower()): c for c in previous.contours}
    merged: dict[tuple[str, str], Contour] = dict(prev_by_key)
    for item in updated_contours:
        key = (item.view.upper(), item.phase.lower())
        prior = prev_by_key.get(key)
        edited = prior is None or list(prior.points) != list(item.points) or prior.mitral_annulus != item.mitral_annulus
        new_source = "ai_edited" if (edited and item.source in {"ai", "ai_edited"}) else item.source
        merged[key] = replace(
            item,
            view=item.view.upper(),
            phase=item.phase.lower(),
            source=new_source,
            review_pending=False if (edited or operator_confirmed) else item.review_pending,
            num_nodes=len(item.points),
        )

    ordered = [merged[k] for k in (("A4C", "ed"), ("A4C", "es"), ("A2C", "ed"), ("A2C", "es")) if k in merged]
    calc_spacing = previous.pixel_spacing_mm if previous.pixel_spacing_mm is not None else (1.0, 1.0)
    calc_contours = tuple(replace(c, review_pending=False) for c in ordered)
    lvef = calculate(calc_contours, calc_spacing) if calc_contours else None
    edvi, esvi = _indexed_volumes(lvef, bsa_m2) if previous.pixel_spacing_mm is not None else (None, None)

    new_a4c = (
        replace(
            previous.a4c,
            ed_contour=merged.get(("A4C", "ed"), previous.a4c.ed_contour),
            es_contour=merged.get(("A4C", "es"), previous.a4c.es_contour),
        )
        if previous.a4c is not None
        else None
    )
    new_a2c = (
        replace(
            previous.a2c,
            ed_contour=merged.get(("A2C", "ed"), previous.a2c.ed_contour),
            es_contour=merged.get(("A2C", "es"), previous.a2c.es_contour),
        )
        if previous.a2c is not None
        else None
    )
    prov = build_auto_ef_provenance(
        study_uid=previous.study_uid,
        contours=ordered,
        pixel_spacing_mm=previous.pixel_spacing_mm,
        lvef_result=lvef,
        a4c=new_a4c,
        a2c=new_a2c,
        warnings=previous.warnings,
        model_id=previous.provenance.method.model_id,
        model_hash=previous.provenance.method.model_hash,
        revision=previous.provenance.revision + 1,
        operator_confirmed=operator_confirmed or all(not c.review_pending for c in ordered),
    )
    return AutoEfPipelineResult(
        study_uid=previous.study_uid,
        a4c=new_a4c,
        a2c=new_a2c,
        contours=tuple(ordered),
        pixel_spacing_mm=previous.pixel_spacing_mm,
        lvef_result=lvef,
        edvi_ml_m2=edvi,
        esvi_ml_m2=esvi,
        provenance=prov,
        warnings=previous.warnings,
    )
