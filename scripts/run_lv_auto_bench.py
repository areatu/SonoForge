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
from echo_personal_tool.domain.services.bench_metrics import (
    aggregate_bench_results,
    annulus_endpoint_error,
    mask_iou,
)
from echo_personal_tool.domain.services.gold_store import load_gold
from echo_personal_tool.domain.services.segment_roi import (
    echonet_crop_mode_for_media,
    resolve_segment_roi_xyxy,
)
from echo_personal_tool.domain.services.segmentation_service import (
    exclude_papillary_concavities,
    mask_to_contour,
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


def run_bench(
    manifest_path: Path,
    *,
    output_path: Path | None = None,
    models_dir: Path | None = None,
) -> dict:
    """Run Tier-1 bench on all manifest entries × {ED, ES}."""
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    studies = manifest.get("studies", [])
    if not studies:
        print("No studies in manifest.")
        return {}

    gold_dir = manifest_path.parent / "gold"
    engine = OnnxInferenceEngine(models_dir=models_dir)

    rows: list[dict] = []

    for study in studies:
        study_id = study["study_id"]
        instance_path = Path(study["instance_path"])
        gold_path = gold_dir / f"lv_{study_id}.json"
        if not gold_path.is_file():
            legacy = gold_dir / f"{study_id}.json"
            if legacy.is_file():
                gold_path = legacy

        if not gold_path.is_file():
            print(f"  SKIP {study_id}: no gold file")
            continue
        gold = load_gold(gold_path)

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
                "phase": phase_key,
                "frame_index": frame_index,
            }

            if contour is None:
                row["reject"] = True
                row["reject_reason"] = "pipeline_failed"
                row["iou"] = 0.0
                row["septal_err"] = None
                row["lateral_err"] = None
                row["lvef_delta"] = None
                row["zero_edit"] = False
                row["light_edit"] = False
                rows.append(row)
                continue

            row["reject"] = False

            # Find matching gold frame
            gold_frame = None
            for gf in gold.get("frames", []):
                if gf.get("frame_index") == frame_index and gf.get("phase") == phase_key:
                    gold_frame = gf
                    break

            if gold_frame is None:
                row["reject_reason"] = "no_gold_frame"
                row["iou"] = None
                row["septal_err"] = None
                row["lateral_err"] = None
                row["lvef_delta"] = None
                row["zero_edit"] = False
                row["light_edit"] = False
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
            row["lvef_delta"] = None
            rows.append(row)

    # Aggregate
    summary = aggregate_bench_results(rows)

    # Print summary
    print(f"\n=== Tier-1 Bench Results ({len(rows)} frames) ===")
    for k, v in summary.items():
        if v is not None:
            print(f"  {k}: {v}")

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
