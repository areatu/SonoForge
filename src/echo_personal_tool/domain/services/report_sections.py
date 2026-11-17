"""Report sections and «not filled» recommendations (UI-4 PR-2, spec §4.6).

The left column of the report mode is the pre-export completeness checklist of
the study.  It lists the sections with their state and the measurements the
study type still expects: for a cardiac study these are the non-optional steps
of all six TP protocols, for an organ study the measurements of its study
profile.  Recommendations are deduplicated by projection key and carry the
required view/frame hint, so the row can say both *what* is missing and *where*
it is measured.

Missing, stale and unreviewed values are separate states: a stale value is
present but its provenance no longer matches the open study, and an unreviewed
contour is work the physician has not confirmed.  A missing item may carry an
explicit ``not_applicable`` / ``not_obtained`` decision with a mandatory reason;
that decision removes it from *missing* without pretending a value exists, and
the printed sheet shows the decision instead of silently omitting the row.

Pure and Qt-free: the presentation layer only renders the returned values.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Final

from echo_personal_tool.domain.measurement_catalog import (
    CALIPER_TO_MEASUREMENT,
    CATALOG,
    FLAG_CARDIAC,
    MEASUREMENTS,
    SECTIONS,
)
from echo_personal_tool.domain.models.result_provenance import Freshness
from echo_personal_tool.domain.models.value_origin import KIND_MANUAL, METHOD_NOT_EVALUATED, ValueOrigin
from echo_personal_tool.domain.protocol_definitions import PROTOCOLS
from echo_personal_tool.domain.protocols import StudyProjection
from echo_personal_tool.domain.services.report_builder import GROUP_OTHER, ReportValue
from echo_personal_tool.domain.services.study_projection import MAPPED_KEYS
from echo_personal_tool.domain.study_profiles import study_profile
from echo_personal_tool.domain.translation import tr

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
    #: The value exists but its provenance no longer matches the open study.
    stale: bool = False
    #: Explicit physician decision (``""`` when the item is still missing).
    decision: str = ""
    reason: str = ""
    #: Required view/frame hint of the protocol step (``""`` when not specified).
    view: str = ""
    frame_hint: str = ""
    tool_id: str = ""


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
    view: str = ""
    frame_hint: str = ""
    tool_id: str = ""


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
                        view=step.view,
                        frame_hint=step.frame_hint or "",
                        tool_id=step.tool_id,
                    )
                )
    return tuple(recommendations)


#: Stable recommendation list, built once (the catalog and protocols are static).
RECOMMENDATIONS: Final[tuple[_Recommendation, ...]] = _steps()

#: Explicit physician decisions for a missing checklist item.
CHECK_NOT_APPLICABLE = "not_applicable"
CHECK_NOT_OBTAINED = "not_obtained"
CHECK_DECISION_KINDS: Final[tuple[str, ...]] = (CHECK_NOT_APPLICABLE, CHECK_NOT_OBTAINED)


@dataclass(frozen=True)
class ChecklistDecision:
    """Why a missing measurement is not expected in this study."""

    kind: str = CHECK_NOT_OBTAINED
    reason: str = ""

    @property
    def label_key(self) -> str:
        return (
            "report.checklist.not_applicable" if self.kind == CHECK_NOT_APPLICABLE else "report.checklist.not_obtained"
        )


@dataclass(frozen=True)
class ChecklistSummary:
    """Counts of the three incomplete states and the physician decisions."""

    missing: int = 0
    stale: int = 0
    unreviewed: int = 0
    not_applicable: int = 0
    not_obtained: int = 0

    @property
    def complete(self) -> bool:
        """No missing or stale value and no contour waiting for review."""
        return self.missing == 0 and self.stale == 0 and self.unreviewed == 0

    @property
    def decided(self) -> int:
        return self.not_applicable + self.not_obtained


#: Projection keys the snapshot builder can actually fill.  A study profile
#: recommendation outside this set would be permanently "missing" even after a
#: measurement, so such a catalog tool is not used as a checklist item.  The
#: non-cardiac checklist only uses organ/IMT caliper keys: the cardiac keys of
#: ``MAPPED_KEYS`` belong to the echo protocols even when a generic M-mode tool
#: happens to sit in a shared section.
_ORGAN_SNAPSHOT_KEYS: Final[frozenset[str]] = frozenset(CALIPER_TO_MEASUREMENT.values()) - frozenset(MAPPED_KEYS)


def _tool_recommendations(profile_id: str) -> tuple[_Recommendation, ...]:
    """Checklist of a non-cardiac study from the measurements of its profile."""
    profile = study_profile(profile_id)
    tools = (
        [CATALOG[tool_id] for tool_id in profile.tools if tool_id in CATALOG]
        if profile.tools is not None
        else [tool for tool in CATALOG.values() if profile.allows(tool.section)]
    )
    seen: set[str] = set()
    recommendations: list[_Recommendation] = []
    for tool in tools:
        if tool.id.startswith("tool."):
            continue
        # An echocardiography instrument stays out of an organ checklist exactly
        # as ``tool_panel_view`` hides its button: a shared section («М-режим»)
        # must not demand e.g. the IVC diameters of a precerebral study.
        if FLAG_CARDIAC in tool.flags:
            continue
        for key in tool.result_keys:
            if key in seen or key not in _ORGAN_SNAPSHOT_KEYS:
                continue
            seen.add(key)
            recommendations.append(
                _Recommendation(
                    key=key,
                    section=tool.section,
                    protocol_id="",
                    step_index=0,
                    tool_id=tool.id,
                )
            )
    return tuple(recommendations)


def recommendations_for_profile(profile_id: str = "") -> tuple[_Recommendation, ...]:
    """Checklist recommendations relevant to one study profile.

    The cardiac profile uses the six TP protocols, exactly as before.  Organ
    studies use the measurements their profile already shows; a tool whose
    result key the snapshot cannot fill is skipped rather than reported as
    missing forever.
    """
    profile = study_profile(profile_id)
    if profile.cardiac:
        return tuple(item for item in RECOMMENDATIONS if profile.allows(item.section))
    return _tool_recommendations(profile.id)


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
    *,
    profile_id: str = "",
    decisions: Mapping[str, ChecklistDecision] | None = None,
) -> tuple[ReportSection, ...]:
    """Sections in catalog order with their checklist status.

    A key counts as filled when the projection carries a *fresh* value — the
    same rule the protocol progress uses (S-11).  A stale value stays visible
    in its section but is not filled.  A missing key with a decision is no
    longer missing, yet it is not a measured value either.  ``projection=None``
    (no study yet) yields every section empty rather than hiding it.
    """
    decisions = decisions or {}
    grouped: dict[str, list[ReportSectionItem]] = {}
    for recommendation in recommendations_for_profile(profile_id):
        value = projection.get(recommendation.key) if projection is not None else None
        stale = bool(value is not None and value.stale)
        decision = decisions.get(recommendation.key) if value is None else None
        grouped.setdefault(recommendation.section, []).append(
            ReportSectionItem(
                key=recommendation.key,
                label=_label(recommendation.key, language),
                protocol_id=recommendation.protocol_id,
                step_index=recommendation.step_index,
                filled=value is not None and not stale,
                stale=stale,
                decision=decision.kind if decision is not None else "",
                reason=decision.reason if decision is not None else "",
                view=recommendation.view,
                frame_hint=recommendation.frame_hint,
                tool_id=recommendation.tool_id,
            )
        )

    sections: list[ReportSection] = []
    for section_id in _SECTION_ORDER:
        items = grouped.get(section_id)
        if not items:
            continue
        filled = sum(item.filled for item in items)
        stale_count = sum(item.stale for item in items)
        resolved = filled + sum(bool(item.decision) for item in items)
        total = len(items)
        if resolved == total and not stale_count:
            status = SectionStatus.DONE
        elif resolved or stale_count:
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


def checklist_summary(sections: tuple[ReportSection, ...], *, unreviewed: int = 0) -> ChecklistSummary:
    """Counts of missing, stale, unreviewed and explicitly decided items."""
    items = [item for section in sections for item in section.items]
    return ChecklistSummary(
        missing=sum(not item.filled and not item.stale and not item.decision for item in items),
        stale=sum(item.stale for item in items),
        unreviewed=max(int(unreviewed), 0),
        not_applicable=sum(item.decision == CHECK_NOT_APPLICABLE for item in items),
        not_obtained=sum(item.decision == CHECK_NOT_OBTAINED for item in items),
    )


def checklist_notices(summary: ChecklistSummary) -> tuple[str, ...]:
    """Printable warning that the exported sheet is not a complete protocol."""
    if summary.missing == 0 and summary.stale == 0:
        return ()
    return (tr("report.notice.checklist_incomplete", missing=summary.missing, stale=summary.stale),)


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
    decisions: Mapping[str, ChecklistDecision] | None = None,
) -> tuple[ReportValue, ...]:
    """Rows the PDF prints for explicit «not evaluated» decisions (PR-5).

    The mark is a statement of the physician, not a measurement: the row keeps
    the catalog label of the step and carries ``value_text`` — the localized
    fallback of the caller — or the specific «неприменимо» / «не получено»
    wording with the recorded reason.  Screen-only «измерить» markers never
    reach the document, so the printed sheet differs from the screen only by
    these honest marks (spec §4.6).

    ``keys`` keeps the historical API: without a matching decision the row
    prints the caller's generic ``value_text``; the reason lives in the
    decision, not in the label.
    """
    marked: list[ReportValue] = []
    wanted = set(keys)
    decisions = decisions or {}
    for section in sections:
        for item in section.items:
            if item.key not in wanted or item.filled or item.stale:
                continue
            decision = decisions.get(item.key)
            text = value_text
            if decision is not None:
                text = tr(decision.label_key)
                if decision.reason:
                    text = f"{text} — {decision.reason}"
            marked.append(
                ReportValue(
                    label=item.label,
                    value=text,
                    group=_SECTION_TO_GROUP.get(section.id, GROUP_OTHER),
                    origin=ValueOrigin(
                        kind=KIND_MANUAL,
                        method_id=METHOD_NOT_EVALUATED,
                        freshness=Freshness.FRESH.value,
                    ),
                )
            )
    return tuple(marked)
