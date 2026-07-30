"""Right ventricular fractional area change (FAC)."""

from __future__ import annotations

from echo_personal_tool.domain.models import Contour
from echo_personal_tool.domain.services.contour_geometry import polygon_area_mm2
from echo_personal_tool.infrastructure.i18n import tr


def rv_area_mm2(
    contour: Contour,
    pixel_spacing: tuple[float, float],
) -> float | None:
    """Closed RV cavity area from open-arc contour and TV annulus chord."""
    points = contour.closed_polygon_points()
    if len(points) < 3:
        return None
    area = polygon_area_mm2(points, pixel_spacing)
    return area if area > 0.0 else None


def format_rv_area_overlay_line(
    contour: Contour,
    pixel_spacing: tuple[float, float] | None,
    *,
    spacing_calibrated: bool = True,
) -> str:
    """Frame overlay for RV FAC contour: phase and area only."""
    phase = contour.phase.upper()
    if pixel_spacing is None:
        return tr("domain.rv_fac.no_area", phase=phase)
    area = rv_area_mm2(contour, pixel_spacing)
    if area is None:
        return tr("domain.rv_fac.no_area", phase=phase)
    unit = "mm²" if spacing_calibrated else "px²"
    return f"RV FAC {phase}: {area:.1f} {unit}"


def fac_percent(
    ed_area_mm2: float,
    es_area_mm2: float,
) -> float | None:
    """FAC = (ED area − ES area) / ED area × 100%."""
    if ed_area_mm2 <= 0.0:
        return None
    return (ed_area_mm2 - es_area_mm2) / ed_area_mm2 * 100.0


def from_rv_contours(
    contours: tuple[Contour, ...],
    pixel_spacing: tuple[float, float],
) -> float | None:
    """Compute FAC from RV ED and ES closed or open-arc contours on A4C."""
    ed_area: float | None = None
    es_area: float | None = None
    for contour in contours:
        if contour.chamber.upper() != "RV":
            continue
        points = contour.closed_polygon_points()
        if len(points) < 3:
            continue
        area = polygon_area_mm2(points, pixel_spacing)
        if area <= 0.0:
            continue
        if contour.phase.upper() == "ED":
            ed_area = area
        elif contour.phase.upper() == "ES":
            es_area = area
    if ed_area is None or es_area is None:
        return None
    return fac_percent(ed_area, es_area)
