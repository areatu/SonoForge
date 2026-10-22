"""Simpson monoplane/biplane volumes for LA, RA, and RV (same mechanics as LV)."""

from __future__ import annotations

from echo_personal_tool.domain.calculations.lvef_simpson import (
    _build_view_metrics,
    _contour_to_mm,
)
from echo_personal_tool.domain.models import Contour, LvViewMetrics
from echo_personal_tool.domain.models.measurements import ChamberSimpsonResult
from echo_personal_tool.domain.services.contour_geometry import polygon_area_mm2

_VALID_PHASES = {"ed", "es"}
_VALID_VIEWS = {"A4C", "A2C"}
_SUPPORTED_CHAMBERS = {"LA", "RA", "RV"}


def calculate_chamber(
    contours: tuple[Contour, ...],
    chamber: str,
    pixel_spacing: tuple[float, float] | None,
) -> ChamberSimpsonResult | None:
    """Compute Simpson volumes for LA, RA, or RV from open-arc contours."""
    chamber_key = chamber.upper()
    if chamber_key not in _SUPPORTED_CHAMBERS:
        return None
    if pixel_spacing is None:
        return None

    row_spacing, col_spacing = pixel_spacing
    if row_spacing <= 0.0 or col_spacing <= 0.0:
        return None

    grouped_contours: dict[str, dict[str, Contour]] = {"A4C": {}, "A2C": {}}
    grouped_mm: dict[
        str,
        dict[
            str,
            tuple[
                tuple[tuple[float, float], ...],
                tuple[tuple[float, float], tuple[float, float]] | None,
            ],
        ],
    ] = {"A4C": {}, "A2C": {}}

    for contour in contours:
        if contour.chamber.upper() != chamber_key:
            continue
        phase = contour.phase.casefold()
        view = contour.view.casefold().upper()
        if phase not in _VALID_PHASES or view not in _VALID_VIEWS:
            continue
        grouped_contours[view][phase] = contour
        grouped_mm[view][phase] = _contour_to_mm(contour, pixel_spacing)

    a4c = _build_view_metrics(grouped_mm["A4C"], grouped_contours["A4C"], pixel_spacing)
    a2c = _build_view_metrics(grouped_mm["A2C"], grouped_contours["A2C"], pixel_spacing)
    if a4c is None and a2c is None:
        return None

    per_view_volumes: dict[str, tuple[float, float]] = {}
    for view, metrics in (("A4C", a4c), ("A2C", a2c)):
        if metrics is None:
            continue
        if metrics.edv_ml is not None and metrics.esv_ml is not None:
            per_view_volumes[view] = (metrics.edv_ml, metrics.esv_ml)

    ef_percent: float | None = None
    method: str | None = None
    if per_view_volumes:
        edv_ml = sum(volume[0] for volume in per_view_volumes.values()) / len(per_view_volumes)
        esv_ml = sum(volume[1] for volume in per_view_volumes.values()) / len(per_view_volumes)
        if edv_ml > 0.0:
            ef_percent = (edv_ml - esv_ml) / edv_ml * 100.0
            method = "simpson_biplan" if len(per_view_volumes) == 2 else "simpson_monoplan"

    max_volume_ml = _max_volume_ml(a4c, a2c)
    area_cm2 = _area_cm2_from_contours(grouped_contours, pixel_spacing)

    return ChamberSimpsonResult(
        chamber=chamber_key,
        a4c=a4c,
        a2c=a2c,
        area_cm2=area_cm2,
        max_volume_ml=max_volume_ml,
        ef_percent=ef_percent,
        method=method,
    )


def _area_cm2_from_contours(
    grouped_contours: dict[str, dict[str, Contour]],
    pixel_spacing: tuple[float, float],
) -> float | None:
    for view in ("A4C", "A2C"):
        for phase in ("es", "ed"):
            contour = grouped_contours[view].get(phase)
            if contour is None:
                continue
            area_mm2 = polygon_area_mm2(contour.closed_polygon_points(), pixel_spacing)
            if area_mm2 > 0.0:
                return area_mm2 / 100.0
    return None


def _max_volume_ml(
    a4c: LvViewMetrics | None,
    a2c: LvViewMetrics | None,
) -> float | None:
    candidates: list[float] = []
    for metrics in (a4c, a2c):
        if metrics is None:
            continue
        for value in (metrics.edv_ml, metrics.esv_ml):
            if value is not None and value > 0.0:
                candidates.append(value)
    if not candidates:
        return None
    return max(candidates)


def es_volume_from_view(metrics: LvViewMetrics | None) -> float | None:
    """Prefer ES volume; fall back to ED for single-phase chamber contours."""
    if metrics is None:
        return None
    if metrics.esv_ml is not None and metrics.esv_ml > 0.0:
        return metrics.esv_ml
    if metrics.edv_ml is not None and metrics.edv_ml > 0.0:
        return metrics.edv_ml
    return None


def biplane_es_volume_ml(
    a4c: LvViewMetrics | None,
    a2c: LvViewMetrics | None,
) -> float | None:
    """Average ES (or ED) volumes when both views are available."""
    values: list[float] = []
    for metrics in (a4c, a2c):
        volume = es_volume_from_view(metrics)
        if volume is not None:
            values.append(volume)
    if len(values) == 2:
        return sum(values) / 2.0
    return None
