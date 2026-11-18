"""Choose report inputs *before* computing volumes, indexes and their lineage.

The source tuples are in acquisition order. No frame number, file name, UUID
or clock is a timestamp. An edit keeps its slot; a newly acquired source goes
at the end. Selection only projects these tuples, never changes the study.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TypeVar

from echo_personal_tool.domain.measurement_catalog import format_measurement, measurement_for_caliper
from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement, is_unnamed_caliper_label
from echo_personal_tool.domain.models.report_repeat import ReportCandidate, ReportRepeat
from echo_personal_tool.domain.models.value_origin import ClipSource
from echo_personal_tool.domain.models.vessel_measurement import VesselMeasurement

_Source = Contour | LinearMeasurement | VesselMeasurement
_T = TypeVar("_T", Contour, LinearMeasurement, VesselMeasurement)


def named_parameter(kind: str, name: str) -> str:
    """Key a named observation without copying free clinical text into user settings."""
    return f"{kind}.{hashlib.sha256(name.encode()).hexdigest()}"


def linear_parameter(item: LinearMeasurement) -> str:
    known = measurement_for_caliper(item.label)
    if known is None:
        label = item.label.strip().casefold()
        if label in {"lvidd", "lv_edd", "lv_end_diastolic_diameter", "lvedd"}:
            known = "lv.lvedd"
        elif label in {"lvids", "lv_esd", "lv_end_systolic_diameter", "lvesd"}:
            known = "lv.lvesd"
    kind = f"spectral.{item.doppler_mode}" if item.doppler else "linear"
    return f"{kind}.{known}" if known else named_parameter(kind, item.label)


@dataclass(frozen=True)
class _Family:
    key: str
    rows: tuple[str, ...]
    phase: str = ""


# Rows produced by the supported non-LV chamber tools. LA 2C has no
# single-plane volume row on the sheet; it contributes to the biplane row.
_CHAMBER_ROWS = {
    ("LA", "a4c"): ("la.area", "la.lav_a4c", "la.lavi_a4c"),
    ("LA", "a2c"): ("la.lav_bp", "la.lavi_bp"),
    ("RA", "a4c"): ("ra.area", "ra.vol", "ra.ravi"),
    ("RV", "a4c"): ("rv.fac", "rv.edv_a4c"),
}


def _family(item: _Source) -> _Family | None:
    if isinstance(item, LinearMeasurement):
        # Unnamed distances are drawings. Consecutive general volume triplets
        # can describe *different organs*: three dimensions are not repeats.
        if is_unnamed_caliper_label(item.label) or item.label.startswith("ORGAN-VOL-"):
            return None
        key = linear_parameter(item)
        if key in ("linear.lv.lvedd", "linear.lv.lvesd"):
            return _Family("lv.diameter_pair", (key,), "ed" if key.endswith("lvedd") else "es")
        if item.doppler:
            return _Family(key, tuple(f"{key}.{part}" for part in ("dt", "dv", "pg")))
        return _Family(key, (key,))
    if isinstance(item, VesselMeasurement):
        key = named_parameter("vessel", item.label)
        return _Family(key, tuple(f"{key}.{part}" for part in ("psv", "edv", "ri", "sd")))
    chamber, view, phase = item.chamber.upper(), item.view.lower(), item.phase.lower()
    if item.review_pending:
        return None  # keep the original pending contour and its review notice
    if chamber == "LV" and view in {"a4c", "a2c"} and phase in {"ed", "es"}:
        key = f"lv.simpson.{view}"
        return _Family(key, tuple(f"lv.{part}_{view}" for part in ("length", "edv", "esv", "edvi", "esvi")), phase)
    if (rows := _CHAMBER_ROWS.get((chamber, view))) and phase in {"ed", "es"}:
        return _Family(f"{chamber.lower()}.simpson.{view}", rows, phase)
    if chamber in {"AREA", "VOL"} and item.measurement_label:
        kind = "area" if chamber == "AREA" else "volume"
        key = named_parameter(f"planimeter.{kind}", item.measurement_label)
        return _Family(key, (key,))
    return None


def _acquisitions(entries: list[tuple[int, _Family]], sources: tuple[_T, ...]) -> list[tuple[int, ...]]:
    """Pair consecutive opposite phases of the *same clip*, ignoring other tools.

    There is only one stored Simpson contour per (clip, view, phase); a clip
    may contain several ED → ES caliper sequences. In competing sequences,
    never borrow a missing half from a different clip or the next cycle.
    """
    runs: list[tuple[int, ...]] = []
    pending: dict[str, tuple[int, str]] = {}
    for index, family in entries:
        if not family.phase:
            runs.append((index,))
            continue
        clip = sources[index].sop_instance_uid or ""
        previous = pending.pop(clip, None)
        if previous is not None:
            if previous[1] != family.phase:
                runs.append((previous[0], index))
                continue
            runs.append((previous[0],))
        if family.key == "lv.diameter_pair" and family.phase == "es":
            runs.append((index,))  # isolated ES does not start the next ED → ES cycle
        else:
            pending[clip] = (index, family.phase)
    runs.extend((index,) for index, _ in pending.values())
    return sorted(runs, key=lambda run: run[-1])


def _diastolic_walls(
    sources: tuple[_T, ...], families: dict[str, list[tuple[int, _Family]]]
) -> dict[int, list[tuple[int, str]]]:
    """Keep the same-frame IVSd/LVEDD/LVPWd tool acquisition together.

    Only attach a wall parameter if its readings really have corresponding ED
    anchors. Standalone wall calipers remain independently selectable.
    """
    diameters = families.get("lv.diameter_pair", [])
    if len(diameters) <= len({family.phase for _, family in diameters}):
        return {}
    anchors = {
        (sources[i].sop_instance_uid, sources[i].frame_index): i for i, family in diameters if family.phase == "ed"
    }
    attached: dict[int, list[tuple[int, str]]] = defaultdict(list)
    for wall in ("linear.lv.ivsd", "linear.lv.lvpwd"):
        entries = families.get(wall, [])
        slots = [(sources[i].sop_instance_uid, sources[i].frame_index) for i, _ in entries]
        if entries and all(uid and frame is not None and (uid, frame) in anchors for uid, frame in slots):
            for (i, _), slot in zip(entries, slots):
                attached[anchors[slot]].append((i, wall))
            del families[wall]
    return attached


def _with_walls(run: tuple[int, ...], walls: dict[int, list[tuple[int, str]]]) -> tuple[int, ...]:
    companions = [i for anchor in run for i, _ in walls.get(anchor, ())]
    return tuple(sorted((*run, *companions)))


def _description(item: _Source) -> str:
    if isinstance(item, LinearMeasurement):
        return item.display_text()
    if isinstance(item, VesselMeasurement):
        psv = format_measurement("vessel.psv", item.psv_cm_s, "cm/s")
        edv = format_measurement("vessel.edv", item.edv_cm_s, "cm/s")
        return f"PSV {psv} / EDV {edv} cm/s"
    return item.measurement_label or f"{item.chamber} {item.view} {item.phase.upper()}"


def contour_candidate_text(item: Contour, spacing: tuple[float, float], calibrated: bool) -> str:
    """Use the very same resolved grid and units as the printed contour result."""
    from echo_personal_tool.domain.calculations.lvef_simpson import format_contour_overlay
    from echo_personal_tool.domain.calculations.planimeter import format_area_result, format_volume_result

    if item.chamber.upper() in {"AREA", "VOL"}:
        formatter = format_area_result if item.chamber.upper() == "AREA" else format_volume_result
        return formatter(item, spacing, spacing_calibrated=calibrated)
    if item.chamber.upper() == "RV":
        from echo_personal_tool.domain.calculations.rv_fac import format_rv_area_overlay_line

        return format_rv_area_overlay_line(item, spacing, spacing_calibrated=calibrated)
    return format_contour_overlay(item, spacing, spacing_calibrated=calibrated)


def candidate_readings(
    item: _T,
    *,
    pixel_spacing: tuple[float, float] | None = None,
    spacing_calibrated: bool = True,
) -> tuple[tuple[str, float], ...]:
    """Norm label and value of one acquisition's readings (2026-11-18, item 1).

    The hover card colours a candidate by these readings against the norms of
    the reference handbook, so each reading carries the label the report row
    resolves its norm with (``LVEDV``, ``Ao Sinus``…).  A reading without a
    norm simply stays unjudged; selection never invents one.
    """
    if isinstance(item, LinearMeasurement):
        if item.doppler or item.millimeter_length is None:
            return ()
        return ((item.label, item.millimeter_length),)
    if isinstance(item, Contour) and pixel_spacing is not None and spacing_calibrated and not item.review_pending:
        from echo_personal_tool.domain.calculations.lvef_simpson import simpson_volume_ml_from_contour

        chamber, view, phase = item.chamber.upper(), item.view.lower(), item.phase.lower()
        if chamber == "LV" and view in {"a4c", "a2c"} and phase in {"ed", "es"}:
            volume = simpson_volume_ml_from_contour(item, pixel_spacing)
            return (("LVEDV" if phase == "ed" else "LVESV", volume),) if volume is not None else ()
        if chamber in {"LA", "RA"} and (chamber, view) in _CHAMBER_ROWS and phase in {"ed", "es"}:
            volume = simpson_volume_ml_from_contour(item, pixel_spacing)
            return (("LAV" if chamber == "LA" else "RAV", volume),) if volume is not None else ()
    return ()


def _candidate(
    sources: tuple[_T, ...],
    run: tuple[int, ...],
    members: tuple[int, ...],
    describe: Callable[[_T], str],
    readings_of: Callable[[_T], tuple[tuple[str, float], ...]] | None = None,
) -> ReportCandidate:
    # Pin the acquisition, not its ordinal or its optional same-frame wall
    # readings. Older calipers without a UUID use their actual storage slot.
    identity = []
    for index in run:
        item = sources[index]
        slot = item.phase if isinstance(item, Contour) else item.label
        ref = item.measurement_id or (item.frame_index, slot)
        identity.append((item.sop_instance_uid, ref))
    parts = []
    readings: list[tuple[tuple[str, float], ...]] = []
    for index in members:
        item = sources[index]
        parts.append((describe(item), ClipSource(item.sop_instance_uid or "", item.frame_index)))
        if readings_of is not None:
            readings.append(readings_of(item))
    return ReportCandidate(json.dumps(identity, separators=(",", ":")), tuple(parts), tuple(readings))


def select_report_sources(
    sources: tuple[_T, ...],
    choices: Mapping[str, str],
    *,
    describe: Callable[[_T], str] = _description,
    readings_of: Callable[[_T], tuple[tuple[str, float], ...]] | None = None,
) -> tuple[tuple[_T, ...], tuple[ReportRepeat, ...]]:
    """Keep the chosen source(s), or the latest complete acquisition by default.

    Partial acquisitions remain selectable on their own. A removed choice
    falls back to automatic; an ordinal would silently select a different
    measurement on deletion. Spectral repeat means have their own acceptance
    workflow and do not enter this selector.
    """
    families: dict[str, list[tuple[int, _Family]]] = defaultdict(list)
    for i, item in enumerate(sources):
        family = _family(item)
        if family is not None:
            families[family.key].append((i, family))
    walls = _diastolic_walls(sources, families)
    dropped: set[int] = set()
    repeats = []
    for key, entries in families.items():
        if len(entries) <= len({family.phase for _, family in entries}):
            continue  # no repeated parameter: leave a unique acquisition alone
        runs: list[tuple[int, ...]] = _acquisitions(entries, sources)
        latest = max(range(len(runs)), key=lambda i: (len(runs[i]), runs[i][-1]))
        row_ids = [row for _, family in entries for row in family.rows]
        members = runs
        if key == "la.simpson.a2c" and "la.simpson.a4c" not in families:
            row_ids.append("la.area")  # A2C supplies the area if there is no A4C
        if key == "lv.diameter_pair" and walls:
            members = [_with_walls(run, walls) for run in runs]
            row_ids.extend(wall for companions in walls.values() for _, wall in companions)
        candidates = tuple(_candidate(sources, run, parts, describe, readings_of) for run, parts in zip(runs, members))
        override = choices.get(key, "")
        chosen = next((i for i, c in enumerate(candidates) if c.id == override), latest)
        rows = tuple(dict.fromkeys(row_ids))
        repeats.append(
            ReportRepeat(
                key, rows, candidates, override if candidates[chosen].id == override else "", candidates[latest].id
            )
        )
        dropped.update(index for i, run in enumerate(members) if i != chosen for index in run)
    return tuple(item for i, item in enumerate(sources) if i not in dropped), tuple(repeats)
