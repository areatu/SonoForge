"""Severity gradations for calculator outputs, read from the structured reference.

Thresholds are deliberately *not* hard-coded in the calculators: the reference
handbook is user-editable (reference constructor), and the calculator card
shows exactly the gradations the reference window shows.  No automatic grade
is assigned — guideline boundaries are half-open in different directions
(severe AS: AVA < 1.0 cm² but Vmax ≥ 4 m/s), and the reference stores closed
ranges, so the card lists the gradations and the physician reads them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GradationHint:
    name: str
    range_text: str


@dataclass(frozen=True)
class ReferenceHint:
    parameter: str
    unit: str
    gradations: tuple[GradationHint, ...]
    source: str = ""
    #: Pathology the thresholds belong to (``Primary Mitral Regurgitation``):
    #: tells apart several hints for the same output.
    context: str = ""
    #: Free-text caveat of the reference parameter (shown under the line).
    note: str = ""

    def text(self) -> str:
        parts = " · ".join(f"{item.name} {item.range_text}" for item in self.gradations)
        unit = f" {self.unit}" if self.unit else ""
        prefix = f"{self.context} — " if self.context else ""
        return f"{prefix}{self.parameter}: {parts}{unit}"


def _number(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text if "." in text else f"{value:.1f}"


def format_range(low: float | None, high: float | None) -> str:
    if low is not None and high is not None:
        return f"{_number(low)}–{_number(high)}"
    if high is not None:
        return f"≤{_number(high)}"
    if low is not None:
        return f"≥{_number(low)}"
    return ""


@lru_cache(maxsize=4)
def _store(language: str):
    from echo_personal_tool.domain.services.reference_data_store import ReferenceDataStore

    try:
        return ReferenceDataStore(language=language).load()
    except Exception:  # noqa: BLE001 - a broken reference must not break the calculators
        logger.exception("reference data unavailable; calculator gradations hidden")
        return None


def reference_hint(reference_id: str | None, language: str = "en") -> ReferenceHint | None:
    """Gradations of one reference parameter, or ``None`` when absent."""
    if not reference_id:
        return None
    store = _store("ru" if language == "ru" else "en")
    if store is None:
        return None
    for _topic, pathology, _gradation, param in store.search(reference_id):
        if param.id != reference_id:
            continue
        gradations: list[GradationHint] = []
        for gradation in param.gradations:
            norm = gradation.range_male or gradation.range_female
            if norm is None:
                continue
            text = format_range(norm.low, norm.high)
            if text:
                gradations.append(GradationHint(gradation.name, text))
        if not gradations:
            return None
        context = getattr(pathology, "name", "") or ""
        note = getattr(param, "note", None) or ""
        return ReferenceHint(param.name, param.unit, tuple(gradations), param.source or "", context, note)
    return None


def clear_cache() -> None:
    """Forget the parsed reference (after the reference constructor saved)."""
    _store.cache_clear()
