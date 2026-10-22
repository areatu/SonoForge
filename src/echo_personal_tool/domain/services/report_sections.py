"""Report sections and «not filled» recommendations (UI-4 PR-2, spec §4.6).

The left column of the report mode lists the sections of the study with their
state and the measurements the TP protocols still expect.  Recommendations are
the non-optional steps of all six protocols, deduplicated by projection key;
the category is the catalog section of the step's tool (or of the measurement
itself for tool-less steps such as RAP / LAI).

Pure and Qt-free: the presentation layer only renders the returned values.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final

from echo_personal_tool.domain.measurement_catalog import CATALOG, MEASUREMENTS, SECTIONS
from echo_personal_tool.domain.models.result_provenance import Freshness
from echo_personal_tool.domain.models.value_origin import KIND_MANUAL, METHOD_NOT_EVALUATED, ValueOrigin
from echo_personal_tool.domain.protocol_definitions import PROTOCOLS
from echo_personal_tool.domain.protocols import StudyProjection
from echo_personal_tool.domain.services.report_builder import GROUP_OTHER, ReportValue

#: Catalog section for a projection key that is produced by a tool.
_KEY_SECTION: Final[dict[str, str]] = {}
for _tool in CATALOG.values():
    for _key in _tool.result_keys:
        _KEY_SECTION.setdefault(_key, _tool.section)
del _tool, _key

#: Derived or input-only keys that no catalog tool produces but that still
#: belong to an anatomical section (the tool-less RAP / LAVi protocol steps).
_KEY_SECTION_OVERRIDES: Final[dict[str, str]] = {
    "la.lavi": "la",
    "ra.rap": "ra",
}
_KEY_SECTION.update(_KEY_SECTION_OVERRIDES)

_SECTION_ORDER: Final[tuple[str, ...]] = tuple(SECTIONS)


class SectionStatus(str, Enum):
    """State of one report section."""

    DONE = "done"
    PARTIAL = "partial"
    EMPTY = "empty"


@dataclass(frozen=True)
class ReportSectionItem:
    """One recommended measurement and whether the projection already has it."""

    key: str
    label: str
    protocol_id: str
    step_index: int
    filled: bool


@dataclass(frozen=True)
class ReportSection:
    """One section with its recommendation counter and items."""

    id: str
    title: str
    status: SectionStatus
    filled: int
    total: int
    items: tuple[ReportSectionItem, ...]


@dataclass(frozen=True)
class _Recommendation:
    key: str
    section: str
    protocol_id: str
    step_index: int


def _steps() -> tuple[_Recommendation, ...]:
    """Non-optional protocol steps, one entry per distinct projection key."""
    seen: set[str] = set()
    recommendations: list[_Recommendation] = []
    for protocol in PROTOCOLS:
        for index, step in enumerate(protocol.steps):
            if step.optional:
                continue
            tool = CATALOG.get(step.tool_id) if step.tool_id else None
            section = tool.section if tool is not None else ""
            for key in step.satisfied_keys:
                if key in seen:
                    continue
                seen.add(key)
                recommendations.append(
                    _Recommendation(
                        key=key,
                        section=section or _KEY_SECTION.get(key, "general"),
                        protocol_id=protocol.id,
                        step_index=index,
                    )
                )
    return tuple(recommendations)


#: Stable recommendation list, built once (the catalog and protocols are static).
RECOMMENDATIONS: Final[tuple[_Recommendation, ...]] = _steps()


def _label(key: str, language: str) -> str:
    spec = MEASUREMENTS.get(key)
    if spec is None:
        return key
    return spec.label(language).short


def _title(section: str, language: str) -> str:
    spec = SECTIONS.get(section)
    if spec is None:
        return section
    return spec.label(language).short


def build_report_sections(
    projection: StudyProjection | None,
    language: str = "ru",
) -> tuple[ReportSection, ...]:
    """Sections in catalog order with their recommendation status.

    A key counts as filled when the projection carries it — the same rule the
    protocol progress uses (S-11).  ``projection=None`` (no study yet) yields
    every section empty rather than hiding it.
    """
    grouped: dict[str, list[ReportSectionItem]] = {}
    for recommendation in RECOMMENDATIONS:
        grouped.setdefault(recommendation.section, []).append(
            ReportSectionItem(
                key=recommendation.key,
                label=_label(recommendation.key, language),
                protocol_id=recommendation.protocol_id,
                step_index=recommendation.step_index,
                filled=projection is not None and projection.get(recommendation.key) is not None,
            )
        )

    sections: list[ReportSection] = []
    for section_id in _SECTION_ORDER:
        items = grouped.get(section_id)
        if not items:
            continue
        filled = sum(item.filled for item in items)
        total = len(items)
        if filled == total:
            status = SectionStatus.DONE
        elif filled:
            status = SectionStatus.PARTIAL
        else:
            status = SectionStatus.EMPTY
        sections.append(
            ReportSection(
                id=section_id,
                title=_title(section_id, language),
                status=status,
                filled=filled,
                total=total,
                items=tuple(items),
            )
        )
    return tuple(sections)


#: Catalog section → report group of the printed sheet.  Sections that have no
#: anatomical group of their own (diastolic, mv_av, strain…) print in «Прочее»,
#: exactly where their values already land.
_SECTION_TO_GROUP: Final[dict[str, str]] = {
    "lv": "lv",
    "la": "la",
    "rv": "rv",
    "ra": "ra",
    "vessels": "vessels",
}


def not_evaluated_values(
    sections: tuple[ReportSection, ...],
    keys: frozenset[str] | set[str],
    *,
    value_text: str,
) -> tuple[ReportValue, ...]:
    """Rows the PDF prints for the explicit «не оценивалось» marks (PR-5).

    The mark is a statement of the physician, not a measurement: the row keeps
    the catalog label of the step and carries ``value_text`` — the localized
    «не оценивалось» of the caller, because this module is pure domain and does
    not translate anything itself.  Screen-only «измерить» markers never reach the document, so
    the printed sheet differs from the screen only by these honest marks
    (spec §4.6).
    """
    marked: list[ReportValue] = []
    wanted = set(keys)
    for section in sections:
        for item in section.items:
            if item.key not in wanted or item.filled:
                continue
            marked.append(
                ReportValue(
                    label=item.label,
                    value=value_text,
                    group=_SECTION_TO_GROUP.get(section.id, GROUP_OTHER),
                    origin=ValueOrigin(
                        kind=KIND_MANUAL,
                        method_id=METHOD_NOT_EVALUATED,
                        freshness=Freshness.FRESH.value,
                    ),
                )
            )
    return tuple(marked)
