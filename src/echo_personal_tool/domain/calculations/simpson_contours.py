"""Shared filtering, grouping, and pixel-to-millimeter conversion for Simpson contours."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from echo_personal_tool.domain.models import Contour

Point = tuple[float, float]
PixelSpacing = tuple[float, float]
Annulus = tuple[Point, Point] | None
ContourGeometryMM = tuple[tuple[Point, ...], Annulus]

SIMPSON_VIEWS = ("A4C", "A2C")
_VALID_PHASES = frozenset({"ed", "es"})


@dataclass(frozen=True)
class GroupedSimpsonContours:
    """The accepted contours and their physical geometry, grouped by view/phase."""

    contours_by_view: dict[str, dict[str, Contour]]
    geometry_mm_by_view: dict[str, dict[str, ContourGeometryMM]]


def contour_to_mm(contour: Contour, pixel_spacing: PixelSpacing) -> ContourGeometryMM:
    """Convert a contour's closed polygon and annulus from pixels to millimeters."""
    row_spacing, col_spacing = pixel_spacing
    polygon_points = contour.closed_polygon_points()
    points_mm = tuple((float(col) * col_spacing, float(row) * row_spacing) for col, row in polygon_points)
    annulus_mm: Annulus = None
    if contour.mitral_annulus is not None:
        annulus_mm = (
            (
                float(contour.mitral_annulus[0][0]) * col_spacing,
                float(contour.mitral_annulus[0][1]) * row_spacing,
            ),
            (
                float(contour.mitral_annulus[1][0]) * col_spacing,
                float(contour.mitral_annulus[1][1]) * row_spacing,
            ),
        )
    return points_mm, annulus_mm


def group_simpson_contours(
    contours: Iterable[Contour],
    *,
    chamber: str,
    pixel_spacing: PixelSpacing,
) -> GroupedSimpsonContours:
    """Filter usable chamber contours and group them by normalized view/phase.

    Pending review contours and views/phases outside the Simpson contract are
    ignored. If multiple accepted contours share a view/phase, the last one in
    the input sequence remains authoritative, matching the existing calculation
    behavior.
    """
    grouped_contours: dict[str, dict[str, Contour]] = {view: {} for view in SIMPSON_VIEWS}
    grouped_mm: dict[str, dict[str, ContourGeometryMM]] = {view: {} for view in SIMPSON_VIEWS}
    chamber_key = chamber.upper()

    for contour in contours:
        if contour.chamber.upper() != chamber_key or contour.review_pending:
            continue
        phase = contour.phase.casefold()
        view = contour.view.casefold().upper()
        if phase not in _VALID_PHASES or view not in grouped_contours:
            continue
        grouped_contours[view][phase] = contour
        grouped_mm[view][phase] = contour_to_mm(contour, pixel_spacing)

    return GroupedSimpsonContours(grouped_contours, grouped_mm)
