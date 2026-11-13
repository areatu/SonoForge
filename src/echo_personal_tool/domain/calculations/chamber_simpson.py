"""Simpson volumes for LA, RA, and RV, including the true LA biplane method.

The true biplane method couples the corresponding disks of A4C and A2C taken
at the same phase.  It is implemented for the left atrium, where biplane
disk summation is a guideline-validated 2D volume.  RA and RV keep the
single-plane volume (or the explicitly descriptive mean of two monoplanes):
the formula being available does not make biplane RV EF a validated 2D
measurement.
"""

from __future__ import annotations

import math

from echo_personal_tool.domain.calculations.lvef_simpson import _build_view_metrics, biplane_volume_ml
from echo_personal_tool.domain.calculations.simpson_contours import ContourGeometryMM, group_simpson_contours
from echo_personal_tool.domain.models import Contour, LvViewMetrics
from echo_personal_tool.domain.models.measurements import ChamberSimpsonResult
from echo_personal_tool.domain.models.value_origin import (
    METHOD_SIMPSON_BIPLANE,
    METHOD_SIMPSON_MEAN_MONOPLANE,
    METHOD_SIMPSON_MONOPLANE,
)
from echo_personal_tool.domain.services.contour_geometry import polygon_area_mm2

_SUPPORTED_CHAMBERS = {"LA", "RA", "RV"}
#: Only the LA has a guideline-validated 2D biplane disk volume.  RA volume
#: is single-plane and RV EF is not a validated 2D biplane measurement, so the
#: formula must not silently upgrade those chambers to a different method.
_BIPLANE_CHAMBERS = frozenset({"LA"})


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

    grouped = group_simpson_contours(contours, chamber=chamber_key, pixel_spacing=pixel_spacing)
    grouped_contours = grouped.contours_by_view
    grouped_mm = grouped.geometry_mm_by_view

    a4c = _build_view_metrics(grouped_mm["A4C"], grouped_contours["A4C"], pixel_spacing)
    a2c = _build_view_metrics(grouped_mm["A2C"], grouped_contours["A2C"], pixel_spacing)
    if a4c is None and a2c is None:
        return None

    ef_percent: float | None = None
    method: str | None = None
    biplane_ed_ml = _biplane_phase_volume_ml(grouped_mm, chamber=chamber_key, phase="ed")
    biplane_es_ml = _biplane_phase_volume_ml(grouped_mm, chamber=chamber_key, phase="es")
    if biplane_es_ml is not None and biplane_ed_ml is not None and biplane_es_ml > biplane_ed_ml:
        # Both phases exist but contradict each other: do not publish a
        # confirmed biplane volume from an impossible ED/ES pair.
        biplane_es_ml = None
    if biplane_es_ml is not None:
        method = METHOD_SIMPSON_BIPLANE
        if biplane_ed_ml is not None:
            ef_percent = (biplane_ed_ml - biplane_es_ml) / biplane_ed_ml * 100.0
    else:
        # No true biplane result: keep the explicitly descriptive mean (or a
        # single-plane value).  It must not inherit the biplane method id.
        per_view_volumes: dict[str, tuple[float, float]] = {}
        for view, metrics in (("A4C", a4c), ("A2C", a2c)):
            if metrics is None:
                continue
            if metrics.edv_ml is not None and metrics.esv_ml is not None:
                per_view_volumes[view] = (metrics.edv_ml, metrics.esv_ml)
        if per_view_volumes:
            edv_ml = sum(volume[0] for volume in per_view_volumes.values()) / len(per_view_volumes)
            esv_ml = sum(volume[1] for volume in per_view_volumes.values()) / len(per_view_volumes)
            if edv_ml > 0.0:
                ef_percent = (edv_ml - esv_ml) / edv_ml * 100.0
                method = METHOD_SIMPSON_MEAN_MONOPLANE if len(per_view_volumes) == 2 else METHOD_SIMPSON_MONOPLANE

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
        biplane_es_ml=biplane_es_ml,
        biplane_verified=biplane_es_ml is not None,
    )


def _biplane_phase_volume_ml(
    grouped_mm: dict[str, dict[str, ContourGeometryMM]],
    *,
    chamber: str,
    phase: str,
) -> float | None:
    """Coupled-disk volume for one phase, only when both views are comparable."""
    if chamber not in _BIPLANE_CHAMBERS:
        return None
    geometry_a = grouped_mm["A4C"].get(phase)
    geometry_b = grouped_mm["A2C"].get(phase)
    if geometry_a is None or geometry_b is None:
        return None
    points_a, annulus_a = geometry_a
    points_b, annulus_b = geometry_b
    # Paired disks need an anatomical long axis in both views.  A closed
    # freehand polygon has only a y-span fallback and is not a biplane input.
    if annulus_a is None or annulus_b is None:
        return None
    volume = biplane_volume_ml(points_a, annulus_a, points_b, annulus_b)
    if volume is None or not math.isfinite(volume) or volume <= 0.0:
        return None
    return volume


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


def mean_es_volume_ml(
    a4c: LvViewMetrics | None,
    a2c: LvViewMetrics | None,
) -> float | None:
    """Arithmetic mean of two available ES volumes — descriptive only.

    Deliberately does not carry a biplane name: the mean of two monoplane
    volumes is not the biplane disk method and must not be indexed or compared
    with biplane reference ranges.
    """
    values: list[float] = []
    for metrics in (a4c, a2c):
        volume = metrics.esv_ml if metrics is not None else None
        if volume is not None and math.isfinite(volume) and volume > 0.0:
            values.append(volume)
    if len(values) == 2:
        return sum(values) / 2.0
    return None


def confirmed_biplane_es_volume_ml(result: ChamberSimpsonResult | None) -> float | None:
    """The biplane ES volume only when a true biplane method produced it.

    ``biplane_verified`` is part of the result, not of the current UI state:
    legacy documents without the flag keep loading, but their averaged
    monoplane value can never feed a biplane index (F08 / issue 548).  The
    method id must name the true biplane method as well: a verified-looking
    value with an unknown method is still not a clinical biplane result.
    """
    if result is None or result.method != METHOD_SIMPSON_BIPLANE:
        return None
    if not result.biplane_verified or result.biplane_es_ml is None:
        return None
    value = result.biplane_es_ml
    if not math.isfinite(value) or value <= 0.0:
        return None
    return value


def confirmed_biplane_index_ml_m2(index: float | None, result: ChamberSimpsonResult | None) -> float | None:
    """Index only a confirmed true biplane volume; an averaged one has no index."""
    if confirmed_biplane_es_volume_ml(result) is None:
        return None
    if index is None or not math.isfinite(index) or index <= 0.0:
        return None
    return index
