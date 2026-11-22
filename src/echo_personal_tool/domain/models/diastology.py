"""Diastology assessment models (plan А.10, issue #648).

Data + display text only; the assembly lives in
``domain.services.diastology_workflow``. The criteria rows come straight from
``domain.calculations.diastology_grade.diastolic_criteria`` — one source of
truth for the thresholds, the grade and this display.

Honest indeterminate (the issue's acceptance item): the simplified ASE
algorithm needs ≥ 3 of its 4 criteria, so an assessment with fewer carries
``GRADE_INSUFFICIENT`` and names exactly which inputs are missing; a 50/50
split of the four criteria is ``GRADE_INDETERMINATE`` with the split counts.
Nothing here invents a grade from a typical value.
"""

from __future__ import annotations

from dataclasses import dataclass

from echo_personal_tool.domain.calculations.diastology_grade import (
    GRADE_ABNORMAL,
    GRADE_INDETERMINATE,
    GRADE_INSUFFICIENT,
    GRADE_NORMAL,
    DiastolicCriterion,
    grade_diastolic_label,
)

#: Display labels of the ASE criteria (abbreviations stay Latin by decision
#: Q-03, like DT/IVRT/VTI in the measurement catalog).
_CRITERION_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "e_over_e_prime": "E/e′",
        "e_prime": "e′",
        "lav_index": "LAVi",
        "tr_vmax": "TR Vmax",
    },
    "ru": {
        "e_over_e_prime": "E/e′",
        "e_prime": "e′",
        "lav_index": "LAVi",
        "tr_vmax": "TR Vmax",
    },
}

_MET_TEXT: dict[str, dict[bool, str]] = {
    "en": {True: "elevated", False: "not elevated"},
    "ru": {True: "повышен", False: "не повышен"},
}

_VERDICT_NOTE: dict[str, dict[int, str]] = {
    "en": {
        GRADE_NORMAL: "Normal — {k} of {n} criteria favor elevated filling pressures",
        GRADE_INDETERMINATE: "Indeterminate — criteria split ({k} of {n})",
        GRADE_ABNORMAL: "Abnormal — {k} of {n} criteria favor elevated filling pressures",
        GRADE_INSUFFICIENT: "Insufficient data — missing: {missing}",
    },
    "ru": {
        GRADE_NORMAL: "Норма — за повышение давления наполнения {k} из {n} критериев",
        GRADE_INDETERMINATE: "Неопределено — критерии разделились ({k} из {n})",
        GRADE_ABNORMAL: "Нарушение ДФ — за повышение давления наполнения {k} из {n} критериев",
        GRADE_INSUFFICIENT: "Недостаточно данных — нет: {missing}",
    },
}


def criterion_label_text(criterion_id: str, *, language: str = "en") -> str:
    """Localized display label of one ASE criterion id."""
    return _CRITERION_LABELS.get(language, _CRITERION_LABELS["en"]).get(criterion_id, criterion_id)


def criterion_verdict_word(row: DiastolicCriterion, *, language: str = "en") -> str:
    """Localized verdict word for one criterion row («повышен» / «не повышен»)."""
    return _MET_TEXT.get(language, _MET_TEXT["en"]).get(row.met, "—")


@dataclass(frozen=True)
class DiastologyField:
    """One auto-filled panel field: value, unit, and how many measurements."""

    id: str
    value: float | None
    unit: str
    #: Measurements behind the value (D-23 repeats); 0 when unknown.
    n: int = 0


@dataclass(frozen=True)
class DiastologyAssessment:
    """The turnkey diastology panel: fields, criteria, grade, gaps.

    ``fields`` is the display-ordered auto-filled panel (E, A, E/A, …); an
    absent measurement simply has ``value=None`` — no typical value is ever
    substituted. ``missing_inputs`` lists the ASE criterion ids absent from
    this assessment, in ASE order.
    """

    fields: tuple[DiastologyField, ...]
    criteria: tuple[DiastolicCriterion, ...]
    #: A ``GRADE_*`` code or ``None`` (no data at all).
    grade_code: int | None
    missing_inputs: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def field(self, field_id: str) -> DiastologyField | None:
        """One field by id, ``None`` when the assessment has none."""
        return next((item for item in self.fields if item.id == field_id), None)

    def grade_label(self, *, language: str = "en") -> str:
        """Localized grade (covers the insufficient-data state, unlike the
        report's historical grade string which is ``None`` there)."""
        return grade_diastolic_label(self.grade_code, language=language)

    def verdict_note(self, *, language: str = "en") -> str:
        """One-line conclusion: the grade with its criteria arithmetic."""
        code = self.grade_code
        if code is None:
            return ""
        if code == GRADE_INSUFFICIENT:
            missing = ", ".join(criterion_label_text(item, language=language) for item in self.missing_inputs)
            return _VERDICT_NOTE[language].get(code, _VERDICT_NOTE["en"][code]).format(missing=missing)
        positive = sum(1 for row in self.criteria if row.met)
        total = len(self.criteria)
        return _VERDICT_NOTE.get(language, _VERDICT_NOTE["en"]).get(code, "").format(k=positive, n=total)

    def criterion_label(self, criterion_id: str, *, language: str = "en") -> str:
        """Localized display label of one ASE criterion."""
        return criterion_label_text(criterion_id, language=language)

    def criterion_verdict(self, row: DiastolicCriterion, *, language: str = "en") -> str:
        """Localized verdict word for one criterion row."""
        return criterion_verdict_word(row, language=language)
