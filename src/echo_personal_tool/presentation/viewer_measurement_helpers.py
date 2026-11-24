"""Pure helpers extracted from :class:`ViewerWidget` (issue #474 decomposition).

These functions used to live as private methods of ``ViewerWidget``.  They
touch no viewer state — only measurement/contour values and catalog formatting
— so they live here as module-level functions to keep ``ViewerWidget`` from
growing past its size ceiling.
"""

from __future__ import annotations

from dataclasses import replace

from echo_personal_tool.domain.measurement_catalog import format_measurement
from echo_personal_tool.domain.models import Contour
from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
from echo_personal_tool.domain.services.nomenclature import catalog_label
from echo_personal_tool.domain.services.organ_volumes import (
    bladder_volume_ml,
    organ_volume_ml,
    thyroid_lobe_volume_ml,
)


def with_measurement_identity(contour: Contour) -> Contour:
    """Give a freshly drawn contour its stable id (item 10 of the 2026-11-06 list).

    A name has to be addressable: the picker that names the polygon right
    after it closes and the report card that renames it later both travel
    by ``measurement_id``, and a document without one could not tell two
    polygons of one frame apart.
    """
    if contour.measurement_id:
        return contour
    from echo_personal_tool.domain.services.doppler_repeats import new_measurement_id

    return replace(contour, measurement_id=new_measurement_id())


def derived_volume_lines(deduped: dict[str, LinearMeasurement]) -> list[str]:
    """Volume lines for completed three-dimension triplets (mirrors report).

    When the third dimension of a bladder, thyroid lobe or the generic
    «объём по трём измерениям» triplet is measured, the results overlay
    shows the computed volume — the same approved arithmetic the report
    already prints, so the physician does not have to open the report to
    see it (issue 558 follow-up).  Only calibrated (millimetre) calipers
    produce a volume; a partial or uncalibrated triplet yields nothing.
    """
    by_label: dict[str, LinearMeasurement] = {}
    for m in deduped.values():
        if m.millimeter_length is None:
            continue
        by_label.setdefault(m.label, m)

    def val(label: str) -> float | None:
        mm = by_label.get(label)
        if mm is None or mm.millimeter_length is None:
            return None
        return float(mm.millimeter_length)

    lines: list[str] = []

    def emit(measurement_id: str, volume_ml: float | None) -> None:
        if volume_ml is None:
            return
        lines.append(f"{catalog_label(measurement_id)}: {format_measurement(measurement_id, volume_ml, 'mL')} mL")

    # Bladder: length × width × depth (depth, or the legacy height).
    length = val("BL-L")
    width = val("BL-W")
    depth = val("BL-D") if "BL-D" in by_label else val("BL-H")
    if length is not None and width is not None and depth is not None:
        emit("bladder.volume", bladder_volume_ml(length, width, depth))

    # Thyroid lobes (Brunn) plus the total when both lobes are complete.
    lobe_volumes: list[float] = []
    for side, labels in (
        ("r", ("TH-R-H", "TH-R-W", "TH-R-TH")),
        ("l", ("TH-L-H", "TH-L-W", "TH-L-TH")),
    ):
        height, w, thick = val(labels[0]), val(labels[1]), val(labels[2])
        if height is None or w is None or thick is None:
            continue
        volume = thyroid_lobe_volume_ml(height, w, thick)
        if volume is not None:
            emit(f"thyroid.{side}_volume", volume)
            lobe_volumes.append(volume)
    if len(lobe_volumes) == 2:
        emit("thyroid.volume", sum(lobe_volumes))

    # Generic «объём по трём измерениям»: consecutive ORGAN-VOL-1/2/3.
    triplet: list[float] = []
    for m in deduped.values():
        if m.millimeter_length is None:
            continue
        if m.label == "ORGAN-VOL-1":
            triplet = [float(m.millimeter_length)]
        elif m.label == "ORGAN-VOL-2" and len(triplet) == 1:
            triplet.append(float(m.millimeter_length))
        elif m.label == "ORGAN-VOL-3" and len(triplet) == 2:
            triplet.append(float(m.millimeter_length))
            if all(v > 0.0 for v in triplet):
                emit("organ.volume", organ_volume_ml(*triplet))
            triplet = []
        elif m.label.startswith("ORGAN-VOL-"):
            triplet = []
    return lines
