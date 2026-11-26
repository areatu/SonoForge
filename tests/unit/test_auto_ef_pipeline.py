"""Unit and gold-accuracy tests for the pure-domain Biplane Auto-EF pipeline."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from echo_personal_tool.domain.models.ecg import RPeakResult
from echo_personal_tool.domain.models.result_provenance import Freshness, QCStatus
from echo_personal_tool.domain.models.temporal_fusion import TemporalFusionConfig
from echo_personal_tool.domain.models.view_recognition import RecognizedView
from echo_personal_tool.domain.services.auto_ef_pipeline import (
    AutoEfClipCandidate,
    recalculate_auto_ef,
    run_auto_ef_pipeline,
    select_apical_clips,
    select_ed_es_frames,
)


def _draw_lv_dome(height: int, width: int, rx: int, ry: int) -> np.ndarray:
    canvas = np.zeros((height, width), dtype=np.uint8)
    cx, cy = width // 2, int(height * 0.62)
    pts = []
    for i in range(33):
        theta = np.pi * i / 32.0
        x = int(round(cx - rx * np.cos(theta)))
        y = int(round(cy - ry * np.sin(theta)))
        pts.append([x, y])
    cv2.fillPoly(canvas, [np.asarray(pts, dtype=np.int32)], 255)
    return canvas


def _synthetic_cycle(n_frames: int = 14, *, ed_rx: int = 38, es_rx: int = 24) -> list[np.ndarray]:
    frames: list[np.ndarray] = []
    for t in range(n_frames):
        alpha = 0.5 * (1.0 - np.cos(2.0 * np.pi * (t - 3) / n_frames))
        rx = int(round((1.0 - alpha) * ed_rx + alpha * es_rx))
        ry = int(round((1.0 - alpha) * 68 + alpha * 50))
        frames.append(_draw_lv_dome(160, 160, rx, ry))
    return frames


class _ThresholdSegmenter:
    def __init__(self, available: bool = True) -> None:
        self._available = available
        self.calls: int = 0

    def is_available(self) -> bool:
        return self._available

    def segment(self, frame: np.ndarray, **_kwargs: Any) -> np.ndarray:
        self.calls += 1
        return (frame > 127).astype(np.uint8)


class _MappingRecognizer:
    def __init__(self, mapping: dict[int, tuple[str, float]]) -> None:
        self._mapping = mapping

    def is_available(self) -> bool:
        return True

    def recognize(self, frames: Any) -> RecognizedView:
        tag = int(frames[0][0, 0])
        view, conf = self._mapping.get(tag, ("UNKNOWN", 0.1))
        return RecognizedView(view=view, confidence=conf)


def test_select_apical_clips_picks_highest_confidence_and_honors_override() -> None:
    f1 = _synthetic_cycle(4)
    f1[0][0, 0] = 1
    f2 = _synthetic_cycle(4)
    f2[0][0, 0] = 2
    f3 = _synthetic_cycle(4)
    f3[0][0, 0] = 3
    rec = _MappingRecognizer({1: ("A4C", 0.62), 2: ("A4C", 0.91), 3: ("A2C", 0.84)})
    c1 = AutoEfClipCandidate(sop_instance_uid="u1", frames=f1)
    c2 = AutoEfClipCandidate(sop_instance_uid="u2", frames=f2)
    c3 = AutoEfClipCandidate(sop_instance_uid="u3", frames=f3)

    sel4, sel2 = select_apical_clips([c1, c2, c3], rec)
    assert sel4 is not None and sel4[0].sop_instance_uid == "u2"
    assert sel2 is not None and sel2[0].sop_instance_uid == "u3"

    c_override = replace(c1, view_override="A2C")
    sel4_b, sel2_b = select_apical_clips([c_override, c2], rec)
    assert sel4_b is not None and sel4_b[0].sop_instance_uid == "u2"
    assert sel2_b is not None and sel2_b[0].sop_instance_uid == "u1"


def test_select_ed_es_frames_override_ecg_and_cavity_area() -> None:
    frames = _synthetic_cycle(14)
    seg = _ThresholdSegmenter()

    c_ovr = AutoEfClipCandidate(sop_instance_uid="u.ovr", frames=frames, ed_override=2, es_override=9)
    ed, es, src, conf, _, _ = select_ed_es_frames(c_ovr, frames, seg)
    assert (ed, es, src, conf) == (2, 9, "override", 1.0)

    c_area = AutoEfClipCandidate(sop_instance_uid="u.area", frames=frames)
    ed_a, es_a, src_a, _, _, _ = select_ed_es_frames(c_area, frames, seg)
    assert src_a == "cavity_area"
    assert ed_a == 3
    assert es_a == 10

    r_peaks = RPeakResult(
        r_peak_indices=np.array([0, 100], dtype=np.int64),
        r_peak_times_ms=np.array([0.0, 500.0]),
        heart_rate_bpm=75.0,
        rr_intervals_ms=np.array([500.0]),
        confidence=0.95,
    )
    c_ecg = AutoEfClipCandidate(
        sop_instance_uid="u.ecg",
        frames=frames,
        frame_time_ms=50.0,
        r_peak_result=r_peaks,
    )
    _, _, src_ecg, _, _, _ = select_ed_es_frames(c_ecg, frames, seg)
    assert src_ecg in {"ecg", "cavity_area"}


def test_run_auto_ef_pipeline_biplane_and_monoplane_fallback() -> None:
    seg4 = _ThresholdSegmenter()
    seg2 = _ThresholdSegmenter()
    c4 = AutoEfClipCandidate(
        sop_instance_uid="sop.a4c",
        frames=_synthetic_cycle(14, ed_rx=40, es_rx=25),
        pixel_spacing_mm=(0.5, 0.5),
        view_override="A4C",
    )
    c2 = AutoEfClipCandidate(
        sop_instance_uid="sop.a2c",
        frames=_synthetic_cycle(14, ed_rx=36, es_rx=23),
        pixel_spacing_mm=(0.5, 0.5),
        view_override="A2C",
    )

    res = run_auto_ef_pipeline(
        [c4, c2],
        study_uid="study.bp.1",
        a4c_segmenter=seg4,
        a2c_segmenter=seg2,
        bsa_m2=1.85,
        temporal_fusion=TemporalFusionConfig(window=2),
    )
    assert res.is_biplane is True
    assert res.method == "simpson_biplan"
    assert res.lvef_percent is not None and 40.0 < res.lvef_percent < 85.0
    assert res.edv_ml is not None and res.esv_ml is not None and res.edv_ml > res.esv_ml
    assert res.sv_ml is not None and res.sv_ml > 0.0
    assert res.edvi_ml_m2 is not None and res.esvi_ml_m2 is not None
    assert len(res.contours) == 4
    assert all(c.review_pending for c in res.contours)
    assert res.provenance.freshness == Freshness.FRESH
    assert res.provenance.qc.status == QCStatus.REVIEW
    assert seg2.calls > 0

    mono = run_auto_ef_pipeline([c4], study_uid="study.mono.1", a4c_segmenter=seg4)
    assert mono.is_biplane is False
    assert mono.lvef_percent is not None
    assert "monoplane_fallback_missing_second_view" in mono.warnings


def test_short_two_frame_clip_skips_temporal_fusion_and_segmenter_unavailable() -> None:
    seg = _ThresholdSegmenter()
    two_frames = [_draw_lv_dome(160, 160, 40, 68), _draw_lv_dome(160, 160, 24, 50)]
    c_short = AutoEfClipCandidate(
        sop_instance_uid="sop.2f",
        frames=two_frames,
        pixel_spacing_mm=(0.5, 0.5),
        view_override="A4C",
    )
    res = run_auto_ef_pipeline(
        [c_short],
        study_uid="study.2f",
        a4c_segmenter=seg,
        temporal_fusion=TemporalFusionConfig(window=2),
    )
    assert res.lvef_percent is not None
    # 2 frames for area scan + 2 frames for ED/ES segmentation = 4 calls (no neighbor fusion)
    assert seg.calls == 4

    unavail = run_auto_ef_pipeline(
        [c_short],
        study_uid="study.unavail",
        a4c_segmenter=_ThresholdSegmenter(available=False),
    )
    assert unavail.lvef_percent is None
    assert "segmenter_unavailable" in unavail.warnings
    assert unavail.provenance.freshness == Freshness.UNAVAILABLE


def test_recalculate_auto_ef_updates_volume_provenance_and_confirmation() -> None:
    seg = _ThresholdSegmenter()
    c4 = AutoEfClipCandidate(
        sop_instance_uid="sop.a4c",
        frames=_synthetic_cycle(6, ed_rx=40, es_rx=25),
        pixel_spacing_mm=(0.5, 0.5),
        view_override="A4C",
    )
    c2 = AutoEfClipCandidate(
        sop_instance_uid="sop.a2c",
        frames=_synthetic_cycle(6, ed_rx=38, es_rx=24),
        pixel_spacing_mm=(0.5, 0.5),
        view_override="A2C",
    )
    initial = run_auto_ef_pipeline([c4, c2], study_uid="study.edit", a4c_segmenter=seg, a2c_segmenter=seg)
    assert initial.edv_ml is not None and initial.lvef_percent is not None
    ed_a4c = next(c for c in initial.contours if c.view == "A4C" and c.phase == "ed")

    # Expand A4C ED contour laterally from its centroid -> EDV & LVEF must increase!
    cx = float(np.mean([p[0] for p in ed_a4c.points]))
    expanded_pts = [((x - cx) * 1.18 + cx, y) for x, y in ed_a4c.points]
    assert ed_a4c.mitral_annulus is not None
    expanded_ma = (expanded_pts[0], expanded_pts[-1])
    edited_contour = replace(
        ed_a4c,
        points=expanded_pts,
        mitral_annulus=expanded_ma,
        source="ai_edited",
        review_pending=False,
    )

    updated = recalculate_auto_ef(initial, [edited_contour], operator_confirmed=False)
    assert updated.edv_ml is not None and updated.edv_ml > initial.edv_ml
    assert updated.lvef_percent is not None and updated.lvef_percent > initial.lvef_percent
    assert updated.provenance.revision == initial.provenance.revision + 1
    assert updated.provenance.inputs != initial.provenance.inputs
    edited_after = next(c for c in updated.contours if c.view == "A4C" and c.phase == "ed")
    assert edited_after.source == "ai_edited"
    assert edited_after.review_pending is False

    confirmed = recalculate_auto_ef(updated, updated.contours, operator_confirmed=True)
    assert confirmed.provenance.qc.status == QCStatus.VALID
    assert all(not c.review_pending for c in confirmed.contours)


def test_onnx_engine_a2c_inference_fallback_resolution(tmp_path: Path, monkeypatch: Any) -> None:
    from echo_personal_tool.infrastructure import onnx_engine
    from echo_personal_tool.infrastructure.onnx_engine import OnnxInferenceEngine

    monkeypatch.setattr(onnx_engine, "_create_session", lambda _path: object())

    manifest = {
        "schema_version": 2,
        "models": {
            "echonet_a2c_resnet50": {
                "filename": "echonet_a2c_resnet50.onnx",
                "sha256": None,
                "status": "not_exported",
            },
            "echonet_seg_resnet50": {
                "filename": "echonet_seg_resnet50.onnx",
                "sha256": None,
                "status": "ready",
            },
        },
        "a2c_inference": {
            "active_model": "echonet_a2c_resnet50",
            "fallback_model": "echonet_seg_resnet50",
        },
    }
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "model_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (models_dir / "echonet_seg_resnet50.onnx").write_bytes(b"fake-onnx")

    engine = OnnxInferenceEngine(models_dir=models_dir, manifest_section="a2c_inference")
    assert (
        onnx_engine._resolve_effective_model_id(models_dir, manifest, manifest_section="a2c_inference")
        == "echonet_seg_resnet50"
    )
    assert engine.model_id == "echonet_seg_resnet50"


def test_gold_biplane_auto_ef_within_5_percent_tolerance() -> None:
    from bench.bench_auto_ef import evaluate_gold_biplane

    gold_dir = Path(__file__).resolve().parents[2] / "gold"
    summary = evaluate_gold_biplane(gold_dir, max_studies=20, n_frames=16)
    assert summary.study_count == 20
    assert summary.mean_abs_delta_ef <= 2.5
    assert summary.max_abs_delta_ef <= 5.0
    assert summary.within_5pct_ratio == 1.0
