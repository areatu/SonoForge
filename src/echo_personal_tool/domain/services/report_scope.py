"""The report of a study profile shows that profile's measurements only.

One study («папка») can hold the measurements of several examinations: a
physician may start an echocardiography clip, notice the thyroid and switch
the study type in the header.  The measurements stay in the study — that is
the point of the study-wide snapshot — but the *report* must print the
examination the physician is reporting on.  Otherwise the thyroid protocol
carries the left-ventricle sizes and, worse, the Teichholz calculations
derived from them.

The rule is the same one the panel follows: a tool belongs to a study when
its section is one of the study's sections and — for a study that names its
tools (the organ studies) — when the study lists it.  A measurement therefore
belongs to a study when the catalog maps its caliper label to one of those
tools.  Labels the catalog does not know (a free-form caliper the physician
drew) are kept: they are an observation about the organ on screen, not the
instrument of another study.

Only the snapshot is narrowed; the stored measurements are untouched, so
switching the profile back brings the whole study back.
"""

from __future__ import annotations

from dataclasses import replace

from echo_personal_tool.domain.measurement_catalog import (
    CALIPER_TO_MEASUREMENT,
    CATALOG,
)
from echo_personal_tool.domain.models.measurements import MeasurementSnapshot, PlanimeterResult
from echo_personal_tool.domain.study_profiles import StudyProfile

#: Caliper label of a tool, by tool id (organ and vessel tools keep theirs).
_CALIPER_TO_TOOL = {tool.payload.caliper_label: tool.id for tool in CATALOG.values() if tool.payload.caliper_label}

#: Tools that produce a measurement, by the measurement's id.  A caliper label
#: resolves through the measurement («LVEDD» → «lv.lvedd» → «lv.linear_ed»), and
#: an instrument may produce several: the M-mode and the 2D caliper both draw
#: «LVEDD», so a label can point at more than one tool.
_MEASUREMENT_TO_TOOLS: dict[str, frozenset[str]] = {}
for _tool in CATALOG.values():
    for _key in _tool.result_keys:
        _MEASUREMENT_TO_TOOLS[_key] = _MEASUREMENT_TO_TOOLS.get(_key, frozenset()) | {_tool.id}


def allowed_tool_ids(profile: StudyProfile) -> frozenset[str]:
    """Ids of the catalog tools this study can measure with."""
    return frozenset(
        tool.id
        for tool in CATALOG.values()
        if profile.allows(tool.section) and profile.allows_tool(tool.id, section_key=tool.section)
    )


def tools_for_label(label: str) -> frozenset[str]:
    """Catalog tools that can produce a measurement with this caliper label.

    Empty for a label the catalog does not know: a free-form caliper.
    """
    measurement_id = CALIPER_TO_MEASUREMENT.get(label)
    if measurement_id is not None:
        return _MEASUREMENT_TO_TOOLS.get(measurement_id, frozenset())
    tool_id = _CALIPER_TO_TOOL.get(label)
    if tool_id is not None:
        return frozenset({tool_id})
    return frozenset()


def allow_label(label: str, allowed: frozenset[str]) -> bool:
    """Whether a measurement with this caliper label belongs to the study.

    An unknown label is a free-form caliper: keep it, the physician drew it on
    this study's picture.
    """
    tools = tools_for_label(label)
    if not tools:
        return True
    return not tools.isdisjoint(allowed)


def restrict_snapshot_to_profile(
    snapshot: MeasurementSnapshot,
    profile: StudyProfile,
) -> MeasurementSnapshot:
    """The study's snapshot with the measurements of the other studies removed.

    Measurements of tools outside the study go, and so do the echocardiography
    results that the study does not produce — a thyroid protocol must not print
    the Teichholz numbers of a clip measured before the profile was switched.
    """
    allowed = allowed_tool_ids(profile)
    restricted = replace(
        snapshot,
        linear_measurements=tuple(
            measurement for measurement in snapshot.linear_measurements if allow_label(measurement.label, allowed)
        ),
        vessel_measurements=tuple(
            measurement for measurement in snapshot.vessel_measurements if allow_label(measurement.label, allowed)
        ),
        planimeter=tuple(result for result in snapshot.planimeter if _planimeter_belongs(result, allowed)),
    )
    if profile.cardiac:
        return restricted
    # The results the echocardiography produced from those measurements: the
    # Teichholz numbers of a clip measured before the profile was switched are
    # the other study's values, not this one's.
    return replace(
        restricted,
        doppler=None,
        display_doppler=None,
        lvef=None,
        teichholz=None,
        la_volume=None,
        la_simpson=None,
        ra_simpson=None,
        rv_simpson=None,
        lvm_g=None,
        rwt=None,
        rv_fac_percent=None,
        diastology_grade=None,
        indexed=None,
        strain=None,
        calculations=None,
    )


def _planimeter_belongs(result: PlanimeterResult, allowed: frozenset[str]) -> bool:
    """Area contours belong to every study; a spline volume only to its own.

    The area tool («Площадь») is part of every study's general section, so its
    contours stay.  The spline volume («Объём») is an echocardiography
    instrument: without it in the study the volume contour is another study's.
    """
    if result.kind != "volume":
        return True
    return "tool.volume" in allowed
