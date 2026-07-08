#!/usr/bin/env python3
"""Tier-1 bench runner: evaluate LV auto-segmentation against gold annotations."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

# Ensure project root is on sys.path for package imports.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.services.bench_lvef import (
    _compute_pair_lvef,
    _gold_frame_to_contour,
    _resolve_pixel_spacing,
)
from echo_personal_tool.domain.services.bench_metrics import (
    aggregate_bench_results,
    annulus_endpoint_error,
    mask_iou,
    zero_edit_accept,
)
from echo_personal_tool.domain.services.gold_store import frame_instance_key, load_gold
from echo_personal_tool.domain.services.segment_roi import (
    echonet_crop_mode_for_media,
    resolve_segment_roi_xyxy,
)
from echo_personal_tool.domain.services.segmentation_service import (
    exclude_papillary_concavities,
    open_arc_from_cavity_mask,
    papillary_mask_cleanup,
)
from echo_personal_tool.infrastructure.dicom_reader import DicomReaderImpl
from echo_personal_tool.infrastructure.onnx_engine import OnnxInferenceEngine


def _load_dicom_frame(path: Path, frame_index: int) -> np.ndarray:
    reader = DicomReaderImpl()
    return reader.read_pixels(path, frame_index)


def _run_auto_segment(
    frame: np.ndarray,
    *,
    instance_path: Path | None,
    phase: str,
    engine: OnnxInferenceEngine,
) -> Contour | None:
    """Run full auto-segment pipeline on a single frame, return Contour or None."""
    gray = frame
    if frame.ndim == 3 and frame.shape[2] == 3:
        gray = np.mean(frame[..., :3], axis=2).astype(np.uint8)

    media_format = "dicom" if instance_path is not None else "mp4"
    roi_xyxy = resolve_segment_roi_xyxy(
        gray,
        media_format=media_format,
        instance_path=instance_path,
    )
    crop_mode = echonet_crop_mode_for_media(media_format)
    mask = engine.segment(gray, roi_xyxy=roi_xyxy, crop_mode=crop_mode)

    mask_int = np.count_nonzero(mask)
    if mask_int < 80:
        return None

    cleaned = papillary_mask_cleanup(mask, phase=phase)
    try:
        open_points, annulus, apex = open_arc_from_cavity_mask(
            cleaned,
            original_shape=gray.shape[:2],
        )
    except ValueError:
        return None

    refined_points = exclude_papillary_concavities(open_points, annulus, apex, phase=phase)
    contour = Contour(
        phase=phase,
        view="A4C",
        chamber="LV",
        mitral_annulus=annulus,
        apex_landmark=apex,
        points=refined_points,
        source="ai",
        num_nodes=len(refined_points),
    )
    return contour


def _contour_to_mask(contour: Contour, shape: tuple[int, int]) -> np.ndarray:
    """Convert contour points to a binary mask for IoU computation."""
    mask = np.zeros(shape, dtype=np.uint8)
    pts = np.array(contour.closed_polygon_points(), dtype=np.int32)
    if len(pts) >= 3:
        import cv2
        cv2.fillPoly(mask, [pts], 1)
    return mask


def _gold_frame_matches_instance(
    gold_frame: dict,
    instance_path: Path,
    *,
    study: dict,
) -> bool:
    frame_path = gold_frame.get("instance_path")
    if frame_path:
        return Path(str(frame_path)).name == instance_path.name
    return frame_instance_key(gold_frame, study=study) == instance_path.name


def _find_gold_frame(
    gold: dict,
    *,
    instance_path: Path,
    frame_index: int,
    phase: str,
) -> dict | None:
    for gf in gold.get("frames", []):
        if gf.get("frame_index") != frame_index or gf.get("phase") != phase:
            continue
        if _gold_frame_matches_instance(gf, instance_path, study=gold):
            return gf
    return None


def run_bench(
    manifest_path: Path,
    *,
    output_path: Path | None = None,
    models_dir: Path | None = None,
) -> dict:
    """Run Tier-1 bench on all manifest entries × {ED, ES}.

    Two-pass structure per manifest entry:
      1. Frame pass: run auto segment for ED and ES; store contours + per-frame metrics.
      2. Pair pass: if both contours and gold exist, compute LVEF delta and zero-edit.
    """
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    studies = manifest.get("studies", [])
    if not studies:
        print("No studies in manifest.")
        return {}

    gold_dir = manifest_path.parent / "gold"
    engine = OnnxInferenceEngine(models_dir=models_dir)

    rows: list[dict] = []
    # Per-instance pair data: key = (study_id, instance_name)
    pair_data: dict[tuple[str, str], dict] = {}

    for study in studies:
        study_id = study["study_id"]
        instance_path = Path(study["instance_path"])
        instance_key = (study_id, instance_path.name)
        gold_path = gold_dir / f"lv_{study_id}.json"
        if not gold_path.is_file():
            legacy = gold_dir / f"{study_id}.json"
            if legacy.is_file():
                gold_path = legacy

        if not gold_path.is_file():
            print(f"  SKIP {study_id}: no gold file")
            continue
        gold = load_gold(gold_path)

        # Resolve pixel spacing once per instance
        spacing = _resolve_pixel_spacing(gold, instance_path)

        for phase_key, frame_key in [("ED", "ed_frame"), ("ES", "es_frame")]:
            frame_index = study.get(frame_key)
            if frame_index is None:
                continue

            try:
                frame = _load_dicom_frame(instance_path, frame_index)
            except Exception as exc:
                print(f"  SKIP {study_id} {phase_key}: {exc}")
                continue

            contour = _run_auto_segment(
                frame, instance_path=instance_path, phase=phase_key, engine=engine,
            )

            row: dict = {
                "study_id": study_id,
                "instance": instance_path.name,
                "phase": phase_key,
                "frame_index": frame_index,
            }

            if contour is None:
                row["reject"] = True
                row["reject_reason"] = "pipeline_failed"
                row["iou"] = 0.0
                row["septal_err"] = None
                row["lateral_err"] = None
                row["lvef_auto"] = None
                row["lvef_gold"] = None
                row["lvef_delta"] = None
                row["lvef_skip_reason"] = "pipeline_failed"
                row["zero_edit"] = False
                row["light_edit"] = False
                row["pair_complete"] = False
                rows.append(row)
                continue

            row["reject"] = False

            # Find matching gold frame (per DICOM instance, not global frame_index)
            gold_frame = _find_gold_frame(
                gold,
                instance_path=instance_path,
                frame_index=frame_index,
                phase=phase_key,
            )

            if gold_frame is None:
                row["reject_reason"] = "no_gold_frame"
                row["iou"] = None
                row["septal_err"] = None
                row["lateral_err"] = None
                row["lvef_auto"] = None
                row["lvef_gold"] = None
                row["lvef_delta"] = None
                row["lvef_skip_reason"] = "missing_gold"
                row["zero_edit"] = False
                row["light_edit"] = False
                row["pair_complete"] = False
                rows.append(row)
                continue

            # Compute IoU
            gold_mask = np.zeros(frame.shape[:2], dtype=np.uint8)
            gold_pts = np.array(gold_frame["points"], dtype=np.int32)
            if len(gold_pts) >= 3:
                import cv2
                cv2.fillPoly(gold_mask, [gold_pts], 1)
            pred_mask = _contour_to_mask(contour, frame.shape[:2])
            iou = mask_iou(pred_mask, gold_mask)
            row["iou"] = round(iou, 4)

            # Annulus endpoint error
            if contour.mitral_annulus and gold_frame.get("mitral_annulus"):
                gold_ann = gold_frame["mitral_annulus"]
                pred_ann = (
                    (float(contour.mitral_annulus[0][0]), float(contour.mitral_annulus[0][1])),
                    (float(contour.mitral_annulus[1][0]), float(contour.mitral_annulus[1][1])),
                )
                gold_ann_tuple = (
                    (float(gold_ann[0][0]), float(gold_ann[0][1])),
                    (float(gold_ann[1][0]), float(gold_ann[1][1])),
                )
                se, le = annulus_endpoint_error(pred_ann, gold_ann_tuple)
                row["septal_err"] = round(se, 2)
                row["lateral_err"] = round(le, 2)
            else:
                row["septal_err"] = None
                row["lateral_err"] = None

            row["reject_reason"] = None
            row["zero_edit"] = False
            row["light_edit"] = False
            row["lvef_auto"] = None
            row["lvef_gold"] = None
            row["lvef_delta"] = None
            row["lvef_skip_reason"] = None
            row["pair_complete"] = False

            # Store contour + gold for pair pass
            pd = pair_data.setdefault(instance_key, {
                "spacing": spacing,
                "auto": {},
                "gold": {},
                "rows": {},
            })
            pd["auto"][phase_key.lower()] = contour
            pd["gold"][phase_key.lower()] = gold_frame
            pd["rows"][phase_key.lower()] = row

            rows.append(row)

    # --- Pair pass: compute LVEF delta per instance ---
    for instance_key, pd in pair_data.items():
        auto_ed = pd["auto"].get("ed")
        auto_es = pd["auto"].get("es")
        gold_ed = pd["gold"].get("ed")
        gold_es = pd["gold"].get("es")
        spacing = pd["spacing"]

        # Need both auto contours, both gold frames, and spacing
        if not all([auto_ed, auto_es, gold_ed, gold_es, spacing]):
            # Mark skip reason on existing rows
            for phase_key in ("ed", "es"):
                row = pd["rows"].get(phase_key)
                if row is None:
                    continue
                if row.get("reject"):
                    continue  # already has skip reason from frame pass
                if spacing is None:
                    row["lvef_skip_reason"] = "no_pixel_spacing"
                elif not auto_ed or not auto_es:
                    row["lvef_skip_reason"] = "missing_ed" if not auto_ed else "missing_es"
                elif not gold_ed or not gold_es:
                    row["lvef_skip_reason"] = "missing_gold"
            continue

        gold_ed_contour = _gold_frame_to_contour(gold_ed)
        gold_es_contour = _gold_frame_to_contour(gold_es)

        pair_result = _compute_pair_lvef(auto_ed, auto_es, gold_ed_contour, gold_es_contour, spacing)

        # Apply pair result to both ED and ES rows
        for phase_key in ("ed", "es"):
            row = pd["rows"].get(phase_key)
            if row is None or row.get("reject"):
                continue
            row["lvef_auto"] = pair_result["lvef_auto"]
            row["lvef_gold"] = pair_result["lvef_gold"]
            row["lvef_delta"] = pair_result["lvef_delta"]
            row["lvef_skip_reason"] = pair_result["lvef_skip_reason"]
            row["pair_complete"] = (
                pair_result["lvef_skip_reason"] is None
                and pair_result["lvef_delta"] is not None
            )

    # --- Zero-edit pass: compute zero_edit for each non-reject row ---
    for row in rows:
        if row.get("reject"):
            row["zero_edit"] = False
            continue
        iou = row.get("iou")
        delta = row.get("lvef_delta")
        row["zero_edit"] = zero_edit_accept(delta, iou if iou is not None else 0.0)

    # Aggregate
    summary = aggregate_bench_results(rows)

    # Gate A median: deduplicate lvef_delta by instance (use ED rows only to avoid 2x)
    deduped_deltas = [
        r["lvef_delta"]
        for r in rows
        if r.get("lvef_delta") is not None
        and r.get("pair_complete")
        and r.get("phase") == "ED"
    ]
    if deduped_deltas:
        s = sorted(deduped_deltas)
        n = len(s)
        summary["median_lvef_delta"] = s[n // 2] if n % 2 == 1 else (s[n // 2 - 1] + s[n // 2]) / 2.0

    # Print summary
    print(f"\n=== Tier-1 Bench Results ({len(rows)} frames) ===")
    for k, v in summary.items():
        if v is not None:
            print(f"  {k}: {v}")

    median_iou = summary.get("median_iou")
    median_lvef = summary.get("median_lvef_delta")
    reject_rate = summary.get("reject_rate")
    zero_rate = summary.get("zero_edit_rate")
    print("\n--- Gate Check (release targets) ---")
    if median_iou is not None:
        print(f"  IoU > 0.82:        {median_iou:.4f}  {'PASS' if median_iou > 0.82 else 'FAIL'}")
    if median_lvef is not None:
        print(f"  |ΔLVEF| < 5%:      {median_lvef:.2f}  {'PASS' if median_lvef < 5.0 else 'FAIL'}")
    else:
        print("  |ΔLVEF| < 5%:      n/a (LVEF not computed in this bench run)")
    if zero_rate is not None:
        print(f"  Zero-edit ≥ 60%:   {zero_rate:.1%}  {'PASS' if zero_rate >= 0.60 else 'FAIL'}")
    if reject_rate is not None:
        print(f"  Reject < 15%:      {reject_rate:.1%}  {'PASS' if reject_rate < 0.15 else 'FAIL'}")

    # Write CSV
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = list(rows[0].keys()) if rows else []
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        print(f"\nCSV: {output_path}")

    return {"rows": rows, "summary": summary}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Tier-1 bench: evaluate LV auto-segmentation vs gold",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("bench/tier1/manifest.json"),
        help="Path to Tier-1 manifest.json",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Output CSV path (default: bench/tier1/reports/<timestamp>.csv)",
    )
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=None,
        help="Override models directory",
    )
    args = parser.parse_args()

    if not args.manifest.is_file():
        print(f"Manifest not found: {args.manifest}")
        return 1

    output = args.report
    if output is None:
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output = args.manifest.parent / "reports" / f"bench_{ts}.csv"

    result = run_bench(args.manifest, output_path=output, models_dir=args.models_dir)
    return 0 if result.get("rows") else 1


if __name__ == "__main__":
    raise SystemExit(main())
