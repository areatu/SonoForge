"""Segmentation accuracy metrics for Tier-1 bench evaluation."""

from __future__ import annotations

import math

import numpy as np


def mask_iou(pred: np.ndarray, gold: np.ndarray) -> float:
    """Intersection-over-Union of two binary masks."""
    p = np.asarray(pred, dtype=bool)
    g = np.asarray(gold, dtype=bool)
    inter = np.count_nonzero(p & g)
    union = np.count_nonzero(p | g)
    if union == 0:
        return 1.0 if not p.any() and not g.any() else 0.0
    return float(inter) / float(union)


def annulus_endpoint_error(
    pred_annulus: tuple[tuple[float, float], tuple[float, float]],
    gold_annulus: tuple[tuple[float, float], tuple[float, float]],
) -> tuple[float, float]:
    """L2 distance for each annulus endpoint (septal, lateral) in pixels."""
    (px, py), (lx, ly) = pred_annulus
    (gx, gy), (hx, hy) = gold_annulus
    septal_err = math.hypot(px - gx, py - gy)
    lateral_err = math.hypot(lx - hx, ly - hy)
    return septal_err, lateral_err


def lvef_delta(lvef_auto: float | None, lvef_gold: float | None) -> float | None:
    """Absolute difference between auto and gold LVEF (%), or None if either is missing."""
    if lvef_auto is None or lvef_gold is None:
        return None
    return abs(lvef_auto - lvef_gold)


def lvef_reject_gate(lvef_delta_pct: float | None, threshold: float = 15.0) -> bool:
    """Reject contour if |ΔLVEF| exceeds threshold (product safety gate)."""
    if lvef_delta_pct is None:
        return False
    return lvef_delta_pct > threshold


def zero_edit_accept(lvef_delta_pct: float | None, iou: float) -> bool:
    """Accept without edits: |ΔLVEF| ≤ 5% or IoU ≥ 0.80."""
    if lvef_delta_pct is not None and lvef_delta_pct <= 5.0:
        return True
    return iou >= 0.80


def light_edit_accept(lvef_delta_pct: float | None, iou: float, num_edits: int) -> bool:
    """Accept with ≤2 edits: same thresholds as zero-edit."""
    if num_edits > 2:
        return False
    return zero_edit_accept(lvef_delta_pct, iou)


def aggregate_bench_results(rows: list[dict]) -> dict:
    """Compute summary statistics from per-frame bench result rows.

    Each row should have keys: iou, septal_err, lateral_err,
    lvef_delta, zero_edit, light_edit, reject.
    """
    if not rows:
        return {
            "total": 0,
            "median_iou": None,
            "median_septal_err": None,
            "median_lateral_err": None,
            "median_lvef_delta": None,
            "zero_edit_rate": None,
            "light_edit_rate": None,
            "reject_rate": None,
        }

    def _median(values: list[float]) -> float | None:
        if not values:
            return None
        s = sorted(values)
        n = len(s)
        if n % 2 == 1:
            return s[n // 2]
        return (s[n // 2 - 1] + s[n // 2]) / 2.0

    ious = [r["iou"] for r in rows if r.get("iou") is not None]
    septal = [r["septal_err"] for r in rows if r.get("septal_err") is not None]
    lateral = [r["lateral_err"] for r in rows if r.get("lateral_err") is not None]
    lvef_deltas = [r["lvef_delta"] for r in rows if r.get("lvef_delta") is not None]

    total = len(rows)
    n_reject = sum(1 for r in rows if r.get("reject"))
    n_accept = total - n_reject
    n_zero = sum(1 for r in rows if r.get("zero_edit"))
    n_light = sum(1 for r in rows if r.get("light_edit"))

    return {
        "total": total,
        "median_iou": _median(ious),
        "median_septal_err": _median(septal),
        "median_lateral_err": _median(lateral),
        "median_lvef_delta": _median(lvef_deltas),
        "zero_edit_rate": n_zero / total if total else None,
        "light_edit_rate": n_light / total if total else None,
        "reject_rate": n_reject / total if total else None,
    }
