"""LVEF pairing helpers for Tier-1 bench evaluation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from echo_personal_tool.domain.calculations.lvef_simpson import calculate
from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.services.bench_metrics import lvef_delta


def _gold_frame_to_contour(gold_frame: dict[str, Any]) -> Contour:
    """Convert a gold annotation frame dict into a Contour object."""
    phase = gold_frame["phase"].lower()
    points = [tuple(p) for p in gold_frame["points"]]
    ma = gold_frame.get("mitral_annulus")
    mitral_annulus = None
    if ma is not None:
        mitral_annulus = (tuple(ma[0]), tuple(ma[1]))
    return Contour(
        phase=phase,
        view="A4C",
        chamber="LV",
        points=points,
        source="gold",
        mitral_annulus=mitral_annulus,
        review_pending=False,
        num_nodes=len(points),
    )


def _resolve_pixel_spacing(
    gold: dict[str, Any],
    instance_path: Path,
) -> tuple[float, float] | None:
    """Resolve pixel spacing: gold dict → DICOM metadata → None."""
    # 1. Gold pixel_spacing_mm
    ps = gold.get("pixel_spacing_mm")
    if ps is not None and len(ps) == 2:
        row, col = float(ps[0]), float(ps[1])
        if row > 0 and col > 0:
            return (row, col)

    # 2. DICOM metadata
    if instance_path.is_file():
        try:
            from echo_personal_tool.infrastructure.dicom_reader import DicomReaderImpl

            meta = DicomReaderImpl().read_metadata(instance_path)
            if meta.pixel_spacing is not None:
                return meta.pixel_spacing
        except Exception:
            pass

    return None


def _compute_pair_lvef(
    auto_ed: Contour | None,
    auto_es: Contour | None,
    gold_ed: Contour | None,
    gold_es: Contour | None,
    spacing: tuple[float, float] | None,
) -> dict[str, Any]:
    """Compute LVEF for auto and gold contour pairs.

    Returns dict with keys: lvef_auto, lvef_gold, lvef_delta, lvef_skip_reason,
    and optionally edv_auto, esv_auto, edv_gold, esv_gold.
    """
    result: dict[str, Any] = {
        "lvef_auto": None,
        "lvef_gold": None,
        "lvef_delta": None,
        "lvef_skip_reason": None,
    }

    if spacing is None:
        result["lvef_skip_reason"] = "no_pixel_spacing"
        return result

    if auto_ed is None or auto_es is None:
        result["lvef_skip_reason"] = "missing_auto"
        return result

    if gold_ed is None or gold_es is None:
        result["lvef_skip_reason"] = "missing_gold"
        return result

    auto_result = calculate((auto_ed, auto_es), spacing)
    gold_result = calculate((gold_ed, gold_es), spacing)

    if auto_result is None or auto_result.lvef_percent is None:
        result["lvef_skip_reason"] = "calculate_failed"
        return result
    if gold_result is None or gold_result.lvef_percent is None:
        result["lvef_skip_reason"] = "calculate_failed"
        return result

    result["lvef_auto"] = round(auto_result.lvef_percent, 2)
    result["lvef_gold"] = round(gold_result.lvef_percent, 2)
    result["lvef_delta"] = round(lvef_delta(auto_result.lvef_percent, gold_result.lvef_percent) or 0.0, 2)

    # Diagnostic volumes
    if auto_result.a4c and auto_result.a4c.edv_ml is not None:
        result["edv_auto"] = round(auto_result.a4c.edv_ml, 2)
    if auto_result.a4c and auto_result.a4c.esv_ml is not None:
        result["esv_auto"] = round(auto_result.a4c.esv_ml, 2)
    if gold_result.a4c and gold_result.a4c.edv_ml is not None:
        result["edv_gold"] = round(gold_result.a4c.edv_ml, 2)
    if gold_result.a4c and gold_result.a4c.esv_ml is not None:
        result["esv_gold"] = round(gold_result.a4c.esv_ml, 2)

    return result
