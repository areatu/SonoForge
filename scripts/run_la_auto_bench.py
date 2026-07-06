#!/usr/bin/env python3
"""LA auto-segmentation bench: evaluate against gold annotations (A4C ES only).

Per study: load A4C ES frame → LA auto pipeline → IoU, MV errors, LAV vs gold → CSV summary.

Requirements:
    pip install numpy scipy opencv-python-headless pydicom onnxruntime

Usage:
    python scripts/run_la_auto_bench.py --gold-root /path/to/gold
    python scripts/run_la_auto_bench.py --gold-root /path/to/gold --report bench/la/bench.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

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
from echo_personal_tool.domain.services.la_segmentation_service import (
    explain_la_auto_reject_reason,
    la_mask_to_contour,
)
from echo_personal_tool.domain.services.segment_roi import (
    echonet_crop_mode_for_media,
    resolve_segment_roi_xyxy,
)
from echo_personal_tool.infrastructure.dicom_reader import DicomReaderImpl
from echo_personal_tool.infrastructure.onnx_engine import OnnxInferenceEngine


def _load_dicom_frame(path: Path, frame_index: int) -> np.ndarray:
    reader = DicomReaderImpl()
    return reader.read_pixels(path, frame_index)


def _run_la_auto_segment(
    frame: np.ndarray,
    *,
    instance_path: Path | None,
    engine: OnnxInferenceEngine,
) -> tuple[Contour | None, int]:
    """Run LA auto-segment pipeline. Returns (contour, mask_pixels) or (None, 0)."""
    gray = frame
    if frame.ndim == 3 and frame.shape[2] == 3:
        gray = np.mean(frame[..., :3], axis=2).astype(np.uint8)

    media_format = "dicom" if instance_path is not None else "mp4"
    roi_xyxy = resolve_segment_roi_xyxy(
        gray, media_format=media_format, instance_path=instance_path,
    )
    crop_mode = echonet_crop_mode_for_media(media_format)
    mask = engine.segment(gray, roi_xyxy=roi_xyxy, crop_mode=crop_mode)

    mask_pixels = int(np.count_nonzero(mask))
    if mask_pixels < 80:
        return None, mask_pixels

    try:
        open_points, annulus, apex = la_mask_to_contour(mask, num_nodes=32)
    except ValueError:
        return None, mask_pixels

    contour = Contour(
        phase="ES",
        view="A4C",
        chamber="LA",
        mitral_annulus=annulus,
        apex_landmark=apex,
        points=open_points,
        source="ai",
        num_nodes=32,
    )
    return contour, mask_pixels


def _contour_to_mask(contour: Contour, shape: tuple[int, int]) -> np.ndarray:
    """Convert contour points to a binary mask for IoU computation."""
    mask = np.zeros(shape, dtype=np.uint8)
    pts = np.array(contour.closed_polygon_points(), dtype=np.int32)
    if len(pts) >= 3:
        import cv2
        cv2.fillPoly(mask, [pts], 1)
    return mask


def _lav_delta_ml(
    auto_contour: Contour,
    gold_frame: dict,
    pixel_spacing: tuple[float, float] | None,
) -> float | None:
    """Compute |LAV_auto - LAV_gold| in mL using area-length method."""
    if pixel_spacing is None:
        return None
    from echo_personal_tool.domain.calculations.chamber_simpson import chamber_simpson_volume_ml
    auto_vol = chamber_simpson_volume_ml(auto_contour, pixel_spacing)
    # Build gold contour for volume
    gold_pts = gold_frame.get("points", [])
    gold_ma = gold_frame.get("mitral_annulus")
    if not gold_pts or not gold_ma or auto_vol is None:
        return None
    gold_contour = Contour(
        phase="ES", view="A4C", chamber="LA",
        mitral_annulus=(
            (float(gold_ma[0][0]), float(gold_ma[0][1])),
            (float(gold_ma[1][0]), float(gold_ma[1][1])),
        ),
        points=[(float(p[0]), float(p[1])) for p in gold_pts],
        source="manual",
    )
    gold_vol = chamber_simpson_volume_ml(gold_contour, pixel_spacing)
    if gold_vol is None or auto_vol is None:
        return None
    return abs(auto_vol - gold_vol)


def run_bench(
    gold_root: Path,
    *,
    output_path: Path | None = None,
    models_dir: Path | None = None,
) -> dict:
    """Run LA bench on all gold studies (A4C ES only)."""
    gold_dir = gold_root / "gold"
    if not gold_dir.is_dir():
        print(f"Gold directory not found: {gold_dir}")
        return {}

    gold_files = sorted(gold_dir.glob("la_*.json"))
    if not gold_files:
        print("No LA gold files found.")
        return {}

    engine = OnnxInferenceEngine(
        models_dir=models_dir, manifest_section="la_inference",
    )
    if not engine.is_available():
        print("LA ONNX model not available. Run finetune_la_seg.py first.")
        return {}

    rows: list[dict] = []

    for gold_path in gold_files:
        try:
            gold = load_gold(gold_path)
        except Exception as exc:
            print(f"  SKIP {gold_path.name}: {exc}")
            continue

        study_id = gold.get("study_id", "")
        instance_path_str = gold.get("instance_path", "")
        if not instance_path_str:
            print(f"  SKIP {study_id}: no instance_path")
            continue
        instance_path = Path(instance_path_str)

        # Find ES frame
        es_frame = None
        for frame in gold.get("frames", []):
            if frame.get("phase") == "ES" and frame.get("view") == "A4C":
                es_frame = frame
                break
        if es_frame is None:
            print(f"  SKIP {study_id}: no ES A4C frame in gold")
            continue

        frame_index = es_frame.get("frame_index", 0)
        pixel_spacing = tuple(gold.get("pixel_spacing_mm", [0.15, 0.15]))
        ps = (float(pixel_spacing[0]), float(pixel_spacing[1])) if len(pixel_spacing) >= 2 else None

        try:
            frame = _load_dicom_frame(instance_path, frame_index)
        except Exception as exc:
            print(f"  SKIP {study_id}: {exc}")
            continue

        contour, mask_pixels = _run_la_auto_segment(
            frame, instance_path=instance_path, engine=engine,
        )

        row: dict = {
            "study_id": study_id,
            "phase": "ES",
            "frame_index": frame_index,
            "mask_pixels": mask_pixels,
        }

        if contour is None:
            row["reject"] = True
            row["reject_reason"] = "pipeline_failed"
            row["iou"] = 0.0
            row["septal_err"] = None
            row["lateral_err"] = None
            row["lav_delta_ml"] = None
            row["zero_edit"] = False
            row["light_edit"] = False
            rows.append(row)
            continue

        # Quality gate
        reject_reason = explain_la_auto_reject_reason(contour, ps, mask_pixels=mask_pixels)
        if reject_reason is not None:
            row["reject"] = True
            row["reject_reason"] = reject_reason
            row["iou"] = 0.0
            row["septal_err"] = None
            row["lateral_err"] = None
            row["lav_delta_ml"] = None
            row["zero_edit"] = False
            row["light_edit"] = False
            rows.append(row)
            continue

        row["reject"] = False
        row["reject_reason"] = None

        # IoU
        gold_mask = np.zeros(frame.shape[:2], dtype=np.uint8)
        gold_pts = np.array(es_frame.get("points", []), dtype=np.int32)
        if len(gold_pts) >= 3:
            import cv2
            cv2.fillPoly(gold_mask, [gold_pts], 1)
        pred_mask = _contour_to_mask(contour, frame.shape[:2])
        iou = mask_iou(pred_mask, gold_mask)
        row["iou"] = round(iou, 4)

        # MV endpoint error
        if contour.mitral_annulus and es_frame.get("mitral_annulus"):
            gold_ann = es_frame["mitral_annulus"]
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

        # LAV delta
        row["lav_delta_ml"] = None
        lav_delta = _lav_delta_ml(contour, es_frame, ps)
        if lav_delta is not None:
            row["lav_delta_ml"] = round(lav_delta, 2)

        row["zero_edit"] = False
        row["light_edit"] = False
        rows.append(row)

    # Aggregate
    summary = aggregate_bench_results(rows)

    # LA-specific gates
    n = len(rows)
    n_reject = sum(1 for r in rows if r.get("reject"))
    ious = [r["iou"] for r in rows if r.get("iou") is not None]
    lav_deltas = [r["lav_delta_ml"] for r in rows if r.get("lav_delta_ml") is not None]
    mv_se = [r["septal_err"] for r in rows if r.get("septal_err") is not None]
    mv_le = [r["lateral_err"] for r in rows if r.get("lateral_err") is not None]

    def _median(vals: list[float]) -> float | None:
        if not vals:
            return None
        s = sorted(vals)
        return s[len(s) // 2] if len(s) % 2 else (s[len(s) // 2 - 1] + s[len(s) // 2]) / 2

    summary["n_studies"] = n
    summary["median_iou"] = _median(ious)
    summary["median_lav_delta_ml"] = _median(lav_deltas)
    summary["median_mv_septal_err_px"] = _median(mv_se)
    summary["median_mv_lateral_err_px"] = _median(mv_le)
    summary["reject_rate"] = n_reject / n if n else None

    # Gate check
    median_iou = summary.get("median_iou")
    median_lav = summary.get("median_lav_delta_ml")
    reject_rate = summary.get("reject_rate")

    print(f"\n=== LA Auto Bench Results ({n} studies) ===")
    for k, v in summary.items():
        if v is not None:
            print(f"  {k}: {v}")

    print("\n--- Gate Check ---")
    if median_iou is not None:
        passed = median_iou > 0.78
        print(f"  IoU > 0.78:     {median_iou:.4f}  {'PASS' if passed else 'FAIL'}")
    if median_lav is not None:
        passed = median_lav < 5.0
        print(f"  |ΔLAV| < 5ml:   {median_lav:.2f} ml  {'PASS' if passed else 'FAIL'}")
    if reject_rate is not None:
        passed = reject_rate < 0.20
        print(f"  Reject < 20%:   {reject_rate:.1%}  {'PASS' if passed else 'FAIL'}")

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
        description="LA auto-segmentation bench vs gold (A4C ES only)",
    )
    parser.add_argument(
        "--gold-root", type=Path, required=True,
        help="Gold dataset root (contains gold/la_*.json)",
    )
    parser.add_argument(
        "--report", type=Path, default=None,
        help="Output CSV path (default: bench/la/reports/<timestamp>.csv)",
    )
    parser.add_argument(
        "--models-dir", type=Path, default=None,
        help="Override models directory",
    )
    args = parser.parse_args()

    output = args.report
    if output is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output = Path("bench/la/reports") / f"bench_{ts}.csv"

    result = run_bench(args.gold_root, output_path=output, models_dir=args.models_dir)
    return 0 if result.get("rows") else 1


if __name__ == "__main__":
    raise SystemExit(main())
