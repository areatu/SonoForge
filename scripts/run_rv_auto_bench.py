#!/usr/bin/env python3
"""Offline RV ML.3 candidate benchmark; no clinical measurement state is modified.

Rejected/missing predictions count against coverage and IoU. FAC is paired only
within one source instance and needs both ED/ES. Reports contain opaque IDs only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for entry in (ROOT, ROOT / "src"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import pydicom  # noqa: E402
from scipy import ndimage  # noqa: E402
from scipy.spatial import ConvexHull, QhullError  # noqa: E402
from scripts.generate_synthetic_echo_corpus import validate_output  # noqa: E402

from echo_personal_tool.domain.calculations.rv_fac import fac_percent  # noqa: E402
from echo_personal_tool.domain.services.bench_metrics import mask_iou  # noqa: E402
from echo_personal_tool.domain.services.cardiac_atlas_geometry import polygon_interior  # noqa: E402
from echo_personal_tool.domain.services.gold_store import load_gold  # noqa: E402
from echo_personal_tool.infrastructure.echo_template_engine import EchoTemplateEngine  # noqa: E402


def estimated_sector_mask(frame: np.ndarray) -> np.ndarray | None:
    """Image-only convex support estimate, not GT; explicit acquisition masks preferred.

    Largest component discards disconnected scanner text; convex filling retains
    a radial shadow/dropout. This heuristic can fail on connected overlays.
    """
    gray = frame.mean(axis=2) if frame.ndim == 3 else frame
    binary = gray > max(float(np.percentile(gray, 5)), 0)
    labels, count = ndimage.label(binary)
    if not count:
        return None
    areas = np.bincount(labels.ravel())
    areas[0] = 0
    y, x = np.where(labels == areas.argmax())
    if len(x) < 20:
        return None
    points = np.column_stack([x, y])[:: max(1, len(x) // 4096)]
    try:
        hull = points[ConvexHull(points).vertices]
    except QhullError:
        return None
    yy, xx = np.mgrid[: gray.shape[0], : gray.shape[1]]
    return polygon_interior(np.column_stack([xx.ravel(), yy.ravel()]), hull).reshape(gray.shape)


def contour_mask(points, shape):
    mask = np.zeros(shape, np.uint8)
    cv2.fillPoly(mask, [np.rint(points).astype(np.int32)], 1)
    return mask


def evaluate_rv_gold(paths: list[Path], engine, *, sector_masks: Path | None = None) -> dict:
    rows, pairs = [], {}
    for path in paths:
        gold = load_gold(path)
        for record in gold["frames"]:
            if str(record.get("chamber", gold.get("chamber", ""))).upper() != "RV":
                continue
            view = record.get("view", gold.get("view", ""))
            if view not in {"A4C", "RV_A4C"}:
                continue
            source = Path(record.get("instance_path") or gold.get("instance_path", ""))
            if not source.is_absolute():
                source = path.parent / source
            key = str(source.resolve())
            uid = hashlib.sha256(key.encode()).hexdigest()[:16]
            ds = pydicom.dcmread(source)
            frames = ds.pixel_array
            index = int(record["frame_index"])
            frame = frames[index] if int(getattr(ds, "NumberOfFrames", 1)) > 1 else frames
            if index < 0 or (int(getattr(ds, "NumberOfFrames", 1)) == 1 and index != 0):
                raise ValueError("gold frame outside source")
            spacing = record.get("pixel_spacing_mm", gold.get("pixel_spacing_mm"))
            spacing = tuple(map(float, spacing)) if spacing is not None else None
            if sector_masks:
                sector = np.load(sector_masks / f"{source.stem}.npy", allow_pickle=False)
            else:
                sector = estimated_sector_mask(frame)
            start = time.perf_counter()
            prediction = engine.predict(
                frame,
                phase=record["phase"],
                frame_index=index,
                pixel_spacing=spacing,
                sector_mask=sector,
                requested_view=view,
            )
            elapsed = (time.perf_counter() - start) * 1000
            rv = next((c for c in prediction.contours if c.chamber == "RV"), None)
            gt = contour_mask(record["points"], frame.shape[:2])
            pm = contour_mask(rv.points, frame.shape[:2]) if rv is not None else np.zeros_like(gt)
            gt_area, predicted_area = float(gt.sum()), float(pm.sum())
            area_error = abs(predicted_area - gt_area) / max(gt_area, 1) * 100 if rv is not None else None
            annulus_error = None
            anchors = record.get("tricuspid_annulus", record.get("mitral_annulus"))
            if rv is not None and anchors is not None and spacing is not None:
                delta = (np.asarray(rv.mitral_annulus) - anchors) * np.asarray(spacing)[::-1]
                annulus_error = float(np.linalg.norm(delta, axis=1).mean())
            row = {
                "instance": uid,
                "phase": record["phase"],
                "iou": mask_iou(pm, gt),
                "area_error_pct": area_error,
                "area_error_mm2": abs(predicted_area - gt_area) * float(spacing[0] * spacing[1])
                if rv is not None and spacing is not None
                else None,
                "tv_error_mm": annulus_error,
                "rejected": rv is None,
                "reason": prediction.reject_reason,
                "pipeline_ms": elapsed,
            }
            rows.append(row)
            pair = pairs.setdefault((key, view), {})
            if record["phase"] in pair:
                raise ValueError("duplicate instance/view/phase gold; curate before benchmarking")
            pair[record["phase"]] = (gt_area, predicted_area if rv is not None else None)
    if not rows:
        raise ValueError("no compatible RV gold frames")
    fac_errors = []
    for phases in pairs.values():
        if "ED" in phases and "ES" in phases and phases["ED"][1] is not None and phases["ES"][1] is not None:
            gold_fac = fac_percent(phases["ED"][0], phases["ES"][0])
            auto_fac = fac_percent(phases["ED"][1], phases["ES"][1])
            if gold_fac is not None and auto_fac is not None:
                fac_errors.append(abs(gold_fac - auto_fac))

    def median(name):
        values = [r[name] for r in rows if r[name] is not None]
        return float(np.median(values)) if values else None

    return {
        "schema_version": 1,
        "clinical_validated": False,
        "frames": len(rows),
        "rejected": sum(r["rejected"] for r in rows),
        "median_iou_all_frames": median("iou"),
        "median_area_error_pct_accepted": median("area_error_pct"),
        "median_tv_error_mm_accepted": median("tv_error_mm"),
        "instances": len(pairs),
        "fac_pairs_total": sum("ED" in phases and "ES" in phases for phases in pairs.values()),
        "fac_pairs_evaluable": len(fac_errors),
        "median_fac_error_pp": float(np.median(fac_errors)) if fac_errors else None,
        "pipeline_p95_ms": float(np.percentile([r["pipeline_ms"] for r in rows], 95)),
        "sector_source": "explicit_acquisition_mask" if sector_masks else "image_support_heuristic",
        "rows": rows,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, action="append", required=True)
    parser.add_argument("--models-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sector-masks", type=Path)
    args = parser.parse_args(argv)
    try:
        output = validate_output(args.output)
        engine = EchoTemplateEngine(args.models_dir, allow_unvalidated=True)
        report = evaluate_rv_gold(args.gold, engine, sector_masks=args.sector_masks)
        output.mkdir(parents=True)
        (output / "rv_bench.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    except (ValueError, OSError, KeyError) as exc:
        sys.stderr.write(f"RV benchmark failed: {type(exc).__name__}\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
