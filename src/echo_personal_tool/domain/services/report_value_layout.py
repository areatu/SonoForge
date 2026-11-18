"""User-level report layout. Keys describe parameters, never a study or frame."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

# The routine sheet omits these rows. They remain available in the row editor,
# even if this leaves their entire group empty on the printed sheet.
DEFAULT_REPORT_VALUE_EXCLUDED = (
    "lv:lv.length_a4c:0",
    "lv:lv.length_a2c:0",
    "lv:lv.sv_teich:0",
    "calculations:calc.sv_teich:0",
    "av:lvot.vmax:0",
)


def merge_report_order(saved: Iterable[str], reordered: tuple[str, ...]) -> tuple[str, ...]:
    """Replace only the edited rows' slots; retain preferences for absent rows."""
    edited = set(reordered)
    remaining = iter(reordered)
    result = [next(remaining) if key in edited else key for key in dict.fromkeys(saved)]
    return (*result, *remaining)


@dataclass(frozen=True)
class ReportRowSpec:
    """One row a report may print (2026-11-18 list, item 3 — «Все измерения»).

    ``key`` is exactly the ``group:parameter:ordinal`` key the builder stamps
    on the row, so a preference written against the spec addresses the row when
    a future study finally measures it.
    """

    key: str
    group: str
    label: str


# Rows whose group the builder pins in code rather than deriving from the
# label (the report's own tables).  An id absent here routes through
# ``group_for_label`` exactly like the row would.
_SPEC_GROUPS: dict[str, str] = {
    "lv.ivrt": "mv",
    "mv.at": "av",
    "doppler.et": "av",
    "mv.e": "mv",
    "mv.a": "mv",
    "mv.ea": "mv",
    "mv.dt": "mv",
    "tdi.e_sept": "mv",
    "tdi.e_lat": "mv",
    "tdi.e_avg": "mv",
    "tdi.e_e_sept": "mv",
    "tdi.e_e_lat": "mv",
    "tdi.e_a_prime": "mv",
    "tdi.s_prime_sept": "mv",
    "tdi.s_prime_lat": "mv",
    "rv.s_prime": "rv",
    "tr.dpdt": "rv",
    "mr.dpdt": "lv",
    "hr": "other",
    "patient.bsa": "other",
    "patient.bsa_source": "other",
    "lv.sv_teich": "lv",
}

# Second-chance routing for families whose names speak for themselves; used
# only when the explicit map and the label keywords both say nothing.
_SPEC_PREFIX_GROUPS: tuple[tuple[str, str], ...] = (
    ("lv.", "lv"),
    ("la.", "la"),
    ("ra.", "ra"),
    ("rv.", "rv"),
    ("mv.", "mv"),
    ("tdi.", "mv"),
    ("av.", "av"),
    ("ar.", "av"),
    ("ao.", "av"),
    ("lvot.", "av"),
    ("tr.", "tv"),
    ("tv.", "tv"),
    ("pv.", "rv"),
    ("pr.", "rv"),
    ("rvot.", "rv"),
    ("ivc.", "ra"),
    ("pa.", "vessels"),
    ("vessel.", "vessels"),
    ("abd_aorta.", "abdomen"),
    ("bile_duct.", "abdomen"),
    ("bladder.", "abdomen"),
    ("gallbladder.", "abdomen"),
    ("liver.", "abdomen"),
    ("pancreas.", "abdomen"),
    ("portal_vein.", "abdomen"),
    ("organ.", "planimetry"),
    ("cca.", "precerebral"),
    ("kidney.", "kidney"),
    ("thyroid.", "thyroid"),
    ("planimeter.", "planimetry"),
    ("calc.", "calculations"),
    ("caliper.", "other"),
    ("doppler.", "other"),
    ("indexed.", "other"),
)


def all_report_rows() -> tuple[ReportRowSpec, ...]:
    """Every standard row the report builder may print (item 3, 2026-11-18).

    The «Все измерения» mode of «Показатели отчёта» lists these rows whether or
    not the current study measured them, so a layout preference can be written
    for the reports of the future.  Row keys mirror the builder exactly:
    caliper rows are keyed ``linear.<catalog id>``, catalog rows by their id,
    and the derived rows (indexed aorta, Teichholz stroke volume, BSA source,
    calculator outputs) by the parameter the builder gives them.  Rows keyed
    from free text (planimeter contours, named vessels) are per-study and stay
    out of the catalogue.
    """
    from echo_personal_tool.domain.calculators.registry import CALCULATORS
    from echo_personal_tool.domain.measurement_catalog import CALIPER_TO_MEASUREMENT, MEASUREMENTS
    from echo_personal_tool.domain.services.nomenclature import caliper_label, catalog_label
    from echo_personal_tool.domain.services.report_builder import group_for_label

    rows: list[ReportRowSpec] = []
    seen: set[str] = set()

    def add(group: str, parameter: str, label: str) -> None:
        key = f"{group}:{parameter}:0"
        if key not in seen:
            seen.add(key)
            rows.append(ReportRowSpec(key, group, label))

    caliper_ids = set(CALIPER_TO_MEASUREMENT.values())
    for measurement_id in sorted(MEASUREMENTS):
        if measurement_id in caliper_ids:
            # The report shows the caliper's own label and keys the row
            # ``linear.<id>``; route the group exactly as the builder does.
            raw = next(raw for raw, known in CALIPER_TO_MEASUREMENT.items() if known == measurement_id)
            label = caliper_label(raw)
            add(group_for_label(label), f"linear.{measurement_id}", label)
        else:
            label = catalog_label(measurement_id)
            group = _SPEC_GROUPS.get(measurement_id)
            if group is None:
                group = next((g for prefix, g in _SPEC_PREFIX_GROUPS if measurement_id.startswith(prefix)), "")
            add(group or group_for_label(label), measurement_id, label)
    # Derived rows beyond the measurement catalogue.
    add("lv", "lv.sv_teich", _sv_teich_label())
    add("other", "patient.bsa_source", _bsa_source_label())
    for parameter, label in _aorta_index_rows():
        add("av", parameter, label)
    for calculator in CALCULATORS:
        for output in calculator.outputs:
            add("calculations", f"calc.{output.id}", _tr_key(output.name_key))
    return tuple(rows)


def _tr_key(key: str) -> str:
    from echo_personal_tool.domain.translation import tr

    return tr(key)


def _sv_teich_label() -> str:
    from echo_personal_tool.domain.translation import tr

    return tr("result.lv_sv_teich")


def _bsa_source_label() -> str:
    from echo_personal_tool.domain.translation import tr

    return tr("domain.report.bsa_source")


def _aorta_index_rows() -> tuple[tuple[str, str], ...]:
    from echo_personal_tool.domain.measurement_catalog import CALIPER_TO_MEASUREMENT
    from echo_personal_tool.domain.services.nomenclature import caliper_label
    from echo_personal_tool.domain.translation import tr

    rows = []
    for raw in ("Annulus", "Ao Sinus", "Ao Junction", "Prox Ao"):
        known = CALIPER_TO_MEASUREMENT.get(raw)
        if known is None:
            continue
        rows.append((f"linear.{known}.i", tr("domain.report.indexed_linear", label=caliper_label(raw))))
    return tuple(rows)
