"""Provenance of the derived report values (origin of a Teichholz / Simpson row).

These helpers answer one question: *which clip and which contour* did a value
come from?  ``report_builder`` uses them to fill the ``origin`` of a derived
row, so the printed sheet cites the real acquisition instead of «происхождение
не записано».  They live here, next to nothing else, because ``report_builder``
is at its module-size ceiling (issue 474) and they are a self-contained group: the
domain models they read are the only dependency.

Pure domain: no Qt, no I/O.
"""

from __future__ import annotations

from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
from echo_personal_tool.domain.models.value_origin import (
    METHOD_PLANIMETER,
    ClipSource,
    ValueOrigin,
    derived_origin,
    measurement_origin,
)

#: Labels of the calipers a Teichholz / Simpson LV volume is derived from.
LVEDD_ALIASES = {"lvedd", "lvidd", "lv_edd", "lv_end_diastolic_diameter"}
LVESD_ALIASES = {"lvesd", "lvids", "lv_esd", "lv_end_systolic_diameter"}


def linear_caliper_origin(snapshot: MeasurementSnapshot, aliases: set[str], method_id: str) -> ValueOrigin | None:
    """Origin of a linear caliper whose label matches one of ``aliases``.

    The caliper carries the clip/frame it was drawn on, so a derived volume
    reports the real source instead of «происхождение не записано».
    """
    for measurement in snapshot.linear_measurements:
        if measurement.label.strip().casefold() in aliases:
            return measurement_origin(
                method_id,
                measurement_id=measurement.measurement_id,
                revision=measurement.revision,
                sop_instance_uid=measurement.sop_instance_uid,
                frame_index=measurement.frame_index,
            )
    return None


def lineage_source(lineage: object) -> ClipSource | None:
    """The clip of a :class:`ContourLineage`, when the contour recorded one."""
    if lineage is None:
        return None
    uid = str(getattr(lineage, "sop_instance_uid", "") or "")
    if not uid:
        return None
    return ClipSource(uid, getattr(lineage, "frame_index", None))


def caliper_pair_origin(snapshot: MeasurementSnapshot, method_id: str) -> ValueOrigin:
    """Origin of a value derived from *both* LV calipers (EF, stroke volume).

    Both clips are cited, in the order they appear in the study, and the
    identity is the diastolic caliper — the one the formula is anchored on.
    """
    sources: list[ClipSource] = []
    ids: list[str] = []
    for origin in (
        linear_caliper_origin(snapshot, LVEDD_ALIASES, method_id),
        linear_caliper_origin(snapshot, LVESD_ALIASES, method_id),
    ):
        if origin is None:
            continue
        for source in origin.sources:
            if source not in sources:
                sources.append(source)
        if origin.measurement_id and origin.measurement_id not in ids:
            ids.append(origin.measurement_id)
    return derived_origin(method_id, sources=tuple(sources), measurement_ids=tuple(ids))


def planimeter_origin(item: object) -> ValueOrigin:
    """Origin of one planimeter result from the contour it was traced on."""
    lineage = getattr(item, "contour", None)
    if lineage is None:
        # A result stored before the lineage was kept: the method is known,
        # the clip was never recorded.
        return measurement_origin(METHOD_PLANIMETER)
    source = lineage_source(lineage)
    return measurement_origin(
        METHOD_PLANIMETER,
        measurement_id=str(getattr(lineage, "measurement_id", "") or ""),
        revision=int(getattr(lineage, "revision", 0) or 0),
        sop_instance_uid=source.sop_instance_uid if source is not None else "",
        frame_index=source.frame_index if source is not None else None,
    )


def simpson_origin(
    lvef: object,
    *,
    method_id: str,
    views: tuple[str, ...] | None = None,
    phase: str = "both",
) -> ValueOrigin:
    """Origin of a Simpson value from the contours it was traced from.

    ``phase`` selects the contours that took part: ``"ed"`` for the diastolic
    volume, ``"es"`` for the systolic one, ``"both"`` for EF and stroke
    volume. ``views`` narrows the citation to the views the value was actually
    computed from: a 4C volume must not cite the 2C clip, while a biplane
    volume is the sum of both. Lineage the contours did not record stays
    unrecorded — the helper never invents a clip.
    """
    sources: list[ClipSource] = []
    ids: list[str] = []
    for view, metrics in (("a4c", getattr(lvef, "a4c", None)), ("a2c", getattr(lvef, "a2c", None))):
        if metrics is None:
            continue
        if views is not None and view not in views:
            continue
        for name in ("ed_contour", "es_contour"):
            if phase == "ed" and name != "ed_contour":
                continue
            if phase == "es" and name != "es_contour":
                continue
            lineage = getattr(metrics, name, None)
            if lineage is None:
                continue
            source = lineage_source(lineage)
            if source is not None and source not in sources:
                sources.append(source)
            identifier = str(getattr(lineage, "measurement_id", "") or "")
            if identifier and identifier not in ids:
                ids.append(identifier)
    return derived_origin(method_id, sources=tuple(sources), measurement_ids=tuple(ids))
