"""Benchmark harness for one-click Biplane Auto-EF on gold annotations."""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from bench.bench_lvef import _gold_frame_to_contour
from echo_personal_tool.domain.calculations.lvef_simpson import calculate
from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.services.auto_ef_pipeline import (
    AutoEfClipCandidate,
    run_auto_ef_pipeline,
)


@dataclass(frozen=True)
class AutoEfBenchSummary:
    """Aggregate accuracy summary across gold Auto-EF evaluations."""

    mode: str
    study_count: int
    mean_abs_delta_ef: float
    median_abs_delta_ef: float
    p90_abs_delta_ef: float
    max_abs_delta_ef: float
    within_5pct_ratio: float


class _MaskThresholdSegmenter:
    """Deterministic binary-frame segmenter for offline gold polygon replay."""

    def is_available(self) -> bool:
        return True

    def segment(self, frame: np.ndarray, **_kwargs: Any) -> np.ndarray:
        return (frame > 127).astype(np.uint8)


def synthesize_cardiac_cycle_frames(
    ed_contour: Contour,
    es_contour: Contour,
    *,
    n_frames: int = 16,
    ed_anchor: int = 4,
) -> list[np.ndarray]:
    """Rasterize a smooth sinusoidal cardiac cycle from gold ED/ES contours."""
    ed_poly = np.round(np.asarray(ed_contour.closed_polygon_points(), dtype=np.float64)).astype(np.int32)
    es_poly = np.round(np.asarray(es_contour.closed_polygon_points(), dtype=np.float64)).astype(np.int32)
    all_pts = np.vstack([ed_poly, es_poly])
    width = int(np.ceil(all_pts[:, 0].max())) + 32
    height = int(np.ceil(all_pts[:, 1].max())) + 32
    frames: list[np.ndarray] = []
    for t in range(n_frames):
        alpha = 0.5 * (1.0 - math.cos(2.0 * math.pi * (t - ed_anchor) / n_frames))
        canvas = np.zeros((height, width), dtype=np.uint8)
        if ed_poly.shape == es_poly.shape:
            pts = np.round((1.0 - alpha) * ed_poly + alpha * es_poly).astype(np.int32)
        else:
            pts = ed_poly if alpha < 0.5 else es_poly
        cv2.fillPoly(canvas, [pts], 255)
        frames.append(canvas)
    return frames


def load_gold_lv_pairs(gold_dir: Path) -> tuple[tuple[float, float], list[tuple[str, Contour, Contour]]]:
    """Load (sop_instance_uid, gold_ed, gold_es) pairs from gold/lv_*.json."""
    paths = sorted(gold_dir.glob("lv_*.json"))
    if not paths:
        raise FileNotFoundError(f"No gold/lv_*.json files found in {gold_dir}")
    doc = json.loads(paths[0].read_text(encoding="utf-8"))
    raw_spacing = doc.get("pixel_spacing_mm") or [0.5, 0.5]
    spacing = (float(raw_spacing[0]), float(raw_spacing[1]))
    by_uid: dict[str, dict[str, dict[str, Any]]] = {}
    for frame in doc.get("frames", []):
        uid = str(frame.get("sop_instance_uid") or "")
        phase = str(frame.get("phase") or "").upper()
        if uid and phase in {"ED", "ES"}:
            by_uid.setdefault(uid, {})[phase] = frame

    pairs: list[tuple[str, Contour, Contour]] = []
    for uid, phases in by_uid.items():
        if "ED" in phases and "ES" in phases:
            pairs.append((uid, _gold_frame_to_contour(phases["ED"]), _gold_frame_to_contour(phases["ES"])))
    return spacing, pairs


def evaluate_gold_biplane(
    gold_dir: Path,
    *,
    max_studies: int | None = None,
    n_frames: int = 16,
) -> AutoEfBenchSummary:
    """Evaluate end-to-end biplane Auto-EF pipeline across paired gold LV clips."""
    spacing, pairs = load_gold_lv_pairs(gold_dir)
    seg = _MaskThresholdSegmenter()
    deltas: list[float] = []
    pair_indices = list(range(0, len(pairs) - 1, 2))
    if max_studies is not None:
        pair_indices = pair_indices[:max_studies]

    for idx in pair_indices:
        uid4, ged4, ges4 = pairs[idx]
        uid2, raw_ed2, raw_es2 = pairs[idx + 1]
        ged2 = replace(raw_ed2, view="A2C")
        ges2 = replace(raw_es2, view="A2C")
        gold_res = calculate((ged4, ges4, ged2, ges2), spacing)
        if gold_res is None or gold_res.lvef_percent is None:
            continue
        cand4 = AutoEfClipCandidate(
            sop_instance_uid=uid4,
            frames=synthesize_cardiac_cycle_frames(ged4, ges4, n_frames=n_frames),
            pixel_spacing_mm=spacing,
            view_override="A4C",
        )
        cand2 = AutoEfClipCandidate(
            sop_instance_uid=uid2,
            frames=synthesize_cardiac_cycle_frames(ged2, ges2, n_frames=n_frames),
            pixel_spacing_mm=spacing,
            view_override="A2C",
        )
        auto_res = run_auto_ef_pipeline(
            (cand4, cand2),
            study_uid=f"gold.biplane.{idx // 2}",
            a4c_segmenter=seg,
            a2c_segmenter=seg,
        )
        if auto_res.lvef_percent is None:
            continue
        deltas.append(abs(auto_res.lvef_percent - gold_res.lvef_percent))

    if not deltas:
        raise RuntimeError("No valid biplane gold pairs evaluated")
    arr = np.asarray(deltas, dtype=np.float64)
    return AutoEfBenchSummary(
        mode="biplane_mask_replay",
        study_count=int(arr.size),
        mean_abs_delta_ef=round(float(arr.mean()), 3),
        median_abs_delta_ef=round(float(np.median(arr)), 3),
        p90_abs_delta_ef=round(float(np.percentile(arr, 90)), 3),
        max_abs_delta_ef=round(float(arr.max()), 3),
        within_5pct_ratio=round(float((arr <= 5.0).mean()), 4),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate Biplane Auto-EF on gold LV annotations")
    parser.add_argument("--gold-dir", type=Path, default=Path("gold"))
    parser.add_argument("--max-studies", type=int, default=None)
    parser.add_argument("--n-frames", type=int, default=16)
    args = parser.parse_args(argv)
    summary = evaluate_gold_biplane(args.gold_dir, max_studies=args.max_studies, n_frames=args.n_frames)
    print(json.dumps(summary.__dict__, indent=2))
    return 0 if summary.max_abs_delta_ef <= 5.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
