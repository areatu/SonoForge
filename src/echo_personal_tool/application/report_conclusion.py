"""Application orchestration for the report-conclusion autofill button.

The domain owns the clinical rules and text merge; this facade only assembles
the current study snapshot, patient context and UI language into the result
consumed by the report page. It performs no I/O and logs no patient text.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
from echo_personal_tool.domain.services.report_conclusion import (
    RULESET_VERSION,
    build_conclusion,
    merge_conclusion,
    render_conclusion,
    with_notice,
)


@dataclass(frozen=True)
class ConclusionAutofillResult:
    """Exact editor text and managed block produced by one button click."""

    text: str
    generated_block: str
    status_key: str
    changed: bool
    finding_count: int
    ruleset_version: str = RULESET_VERSION


def autofill_conclusion(
    snapshot: MeasurementSnapshot | None,
    *,
    sex: str = "",
    age_years: float | None = None,
    language: str = "en",
    existing: str = "",
    previous_generated: str = "",
) -> ConclusionAutofillResult:
    """Build a qualitative draft and merge it without deleting manual edits."""

    draft = build_conclusion(snapshot, sex=sex, age_years=age_years)
    block = render_conclusion(draft, language)
    merged = merge_conclusion(existing, block, previous_generated)
    if merged.preserved_edited_block:
        draft = with_notice(draft, "report.conclusion.notice.edited_block")
        block = render_conclusion(draft, language)
        merged = merge_conclusion(existing, block, previous_generated)
    return ConclusionAutofillResult(
        text=merged.text,
        generated_block=merged.generated_block,
        status_key=merged.status_key,
        changed=merged.changed,
        finding_count=len(draft.findings),
    )


_AGE_UNIT_YEARS = frozenset({"", "y", "yr", "yrs", "year", "years", "г", "год", "года", "лет"})
_AGE_UNIT_MONTHS = frozenset({"m", "mo", "mon", "month", "months", "мес", "месяц", "месяца", "месяцев"})
_AGE_UNIT_WEEKS = frozenset({"w", "wk", "week", "weeks", "нед", "неделя", "недели", "недель"})
_AGE_UNIT_DAYS = frozenset({"d", "day", "days", "д", "день", "дня", "дней"})
_DICOM_AGE = re.compile(r"^(\d{1,3})([DWMY])$", re.IGNORECASE)
_FREE_AGE = re.compile(r"^(\d{1,3}(?:[.,]\d+)?)\s*([^0-9].*)?$", re.IGNORECASE)


def age_years_from_text(raw: object) -> float | None:
    """Completed years from the report header, without guessing free text.

    DICOM ``nnnD/W/M/Y`` and explicit unit words are converted; a bare number
    is years.  Ambiguous text returns ``None`` so the adult-only gate cannot
    silently treat ``003M`` as three years or ``020D`` as twenty years.
    """
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
        return value if math.isfinite(value) and 0.0 <= value < 150.0 else None
    text = str(raw or "").strip()
    if not text:
        return None
    dicom = _DICOM_AGE.fullmatch(text)
    if dicom is not None:
        number = float(dicom.group(1))
        unit = dicom.group(2).upper()
        return {"Y": number, "M": number / 12.0, "W": number / 52.0, "D": number / 365.25}[unit]
    free = _FREE_AGE.fullmatch(text)
    if free is None:
        return None
    try:
        number = float(free.group(1).replace(",", "."))
    except ValueError:
        return None
    if not math.isfinite(number) or number < 0.0 or number >= 150.0:
        return None
    unit = (free.group(2) or "").strip().casefold().rstrip(".")
    if unit in _AGE_UNIT_YEARS:
        return number
    if unit in _AGE_UNIT_MONTHS:
        return number / 12.0
    if unit in _AGE_UNIT_WEEKS:
        return number / 52.0
    if unit in _AGE_UNIT_DAYS:
        return number / 365.25
    return None
