"""Project accepted measurement evidence onto series, without upward domain imports."""

from __future__ import annotations

from collections.abc import Mapping
from math import isfinite

from echo_personal_tool.application.study_measurement_session import StudyMeasurementData
from echo_personal_tool.domain.services.study_view_resolver import StudyViewCue

_PLAX = frozenset({"Ao", "Ao Sinus", "Ao Junction", "Prox Ao", "LA", "LA_AP", "IVS", "IVSd", "LVIDd", "LVEDD", "LVESD"})
_RV = frozenset({"TAPSE", "RV_FAC", "FAC", "RV_base", "RV basal", "RV mid", "RV_FW"})


def study_measurement_cues(
    data: StudyMeasurementData, instance_to_series: Mapping[str, str]
) -> tuple[StudyViewCue, ...]:
    """Never assign a study-wide or unbound scalar to a guessed clip.

    Only SOP-bound spatial calipers and accepted chamber contours contribute.
    Doppler/M-mode TAPSE cannot imply a 2D acquisition; its series must be mapped
    by the caller to the corresponding 2D series, not automatically by UID order.
    """
    found: set[StudyViewCue] = set()
    for item in data.linear_measurements:
        series = instance_to_series.get(item.sop_instance_uid)
        if series is None or item.doppler or item.start is None or item.end is None:
            continue
        if item.pixel_length <= 0 or not all(isfinite(v) for point in (item.start, item.end) for v in point):
            continue
        if item.label in _PLAX:
            found.add(StudyViewCue(series, "plax_linear"))
        elif item.label in _RV:
            found.add(StudyViewCue(series, "rv_measurement"))
    atrial: dict[str, set[str]] = {}
    for contour in data.contours:
        series = instance_to_series.get(contour.sop_instance_uid or "")
        if series is None or contour.review_pending or len(contour.points) < 3:
            continue
        if not all(isfinite(v) for point in contour.points for v in point):
            continue
        if contour.chamber in {"RV", "RV_FW"}:
            found.add(StudyViewCue(series, "rv_measurement"))
        if contour.chamber == "LA" and contour.view in {"A4C", "A2C"}:
            atrial.setdefault(contour.view, set()).add(series)
    if {"A4C", "A2C"} <= atrial.keys():
        for series in atrial["A4C"] | atrial["A2C"]:
            found.add(StudyViewCue(series, "la_biplane"))
    return tuple(sorted(found, key=lambda cue: (cue.series_uid, cue.kind)))
