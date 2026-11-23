"""Stress-echo workflow — WMSI aggregation, strain suggestions and rest/stress pairing (plan А.11, issue #649).

The physician scores wall motion visually on the ASE 1–5 scale; this service
gives that scoring its honest plumbing:

* **suggestion** — a starting point derived from the measured per-segment
  peak strain (:func:`suggest_wall_motion_score`); every suggested score
  carries the ``strain_suggestion`` source, so the UI marks it and a manual
  verdict always wins. The thresholds are the app's documented convention
  (module constants), not a clinical standard — the physician overrides.
* **aggregation** — WMSI = mean over the *scored* segments (unvisualised
  segments are not normal by default); a stage with no scores has no WMSI.
* **comparison** — ΔWMSI, new/worsening segments, and the verdict code
  (ischaemia = new or worsening abnormality at stress; a rest abnormality
  stress does not worsen is fixed, not ischaemic).
* **pairing** — rest/stress study matching per patient (nearest date, one
  pair per study), reusing :func:`study_enrichment.is_stress_study` for the
  stress-side detection the loader already computes.

The contrast-perfusion step of the issue is deliberately out of scope here —
a qualitative scoring column needs its own honest design and is a follow-up.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from echo_personal_tool.domain.models.stress_echo import (
    SCORE_AKINETIC,
    SCORE_DYSKINETIC,
    SCORE_HYPOKINETIC,
    SCORE_NORMAL,
    SOURCE_STRAIN_SUGGESTION,
    STAGE_REST,
    STAGE_STRESS,
    StressEchoAssessment,
    StressEchoScoring,
)
from echo_personal_tool.domain.services.study_enrichment import is_stress_study

#: Suggestion thresholds on the peak systolic longitudinal strain of one
#: segment (percent, the app's LV sign convention: more negative = stronger
#: contraction). Documented app convention — the physician overrides.
#: ≤ -15 % normal/hyperkinetic; -15…-8 hypokinetic; -8…0 akinetic; ≥ 0
#: dyskinetic (systolic lengthening). Aneurysmal (5) is visual-only: strain
#: alone cannot distinguish it from dyskinesia.
SUGGEST_NORMAL_MAX = -15.0
SUGGEST_HYPOKINETIC_MAX = -8.0


def suggest_wall_motion_score(peak_strain_pct: float) -> int:
    """Wall-motion score suggested by one segment's peak systolic strain."""
    value = float(peak_strain_pct)
    if value <= SUGGEST_NORMAL_MAX:
        return SCORE_NORMAL
    if value <= SUGGEST_HYPOKINETIC_MAX:
        return SCORE_HYPOKINETIC
    if value < 0.0:
        return SCORE_AKINETIC
    return SCORE_DYSKINETIC


def suggest_scoring_from_strain(
    segment_values: Mapping[int, float],
    *,
    segment_quality: Mapping[int, float] | None = None,
    min_quality: float = 0.0,
) -> StressEchoScoring:
    """A starting scoring from the strain values that passed the quality bar.

    Segments without a finite value (and segments below ``min_quality`` when
    a quality map is given) are left unscored — a suggestion may cover part
    of the wall, the physician fills the rest by eye.
    """
    scores: dict[int, int] = {}
    for segment, value in segment_values.items():
        if value is None or value != value or value in (float("inf"), float("-inf")):
            continue
        if segment_quality is not None and float(segment_quality.get(int(segment), 0.0)) < min_quality:
            continue
        scores[int(segment)] = suggest_wall_motion_score(float(value))
    return StressEchoScoring(scores=scores, sources={seg: SOURCE_STRAIN_SUGGESTION for seg in scores})


@dataclass(frozen=True)
class StressStudyRecord:
    """One study as the pairing helper sees it (loader/enrichment supplies)."""

    study_uid: str
    patient_id: str
    #: ISO date string or ``""`` (unknown dates pair by list order).
    study_date: str = ""
    protocol_name: str = ""
    #: ``True`` when the study is the stress side — the caller normally feeds
    #: :func:`study_enrichment.is_stress_study` here.
    is_stress: bool = False


def pair_stress_studies(
    records: Sequence[StressStudyRecord],
) -> tuple[tuple[str, str], ...]:
    """Rest/stress pairs of one patient's studies, ``(rest_uid, stress_uid)``.

    Per patient: every stress study pairs with the nearest-dated rest study
    that is not already paired (unknown dates fall back to list order —
    the first free rest study). A study takes part in at most one pair; a
    stress study without a free rest counterpart stays unpaired (the caller
    sees it as an absent pair, not a fabricated one).
    """
    by_patient: dict[str, list[StressStudyRecord]] = {}
    for record in records:
        if not record.study_uid:
            continue
        by_patient.setdefault(record.patient_id, []).append(record)

    pairs: list[tuple[str, str]] = []
    for patient_records in by_patient.values():
        stress_studies = [r for r in patient_records if r.is_stress]
        rest_studies = [r for r in patient_records if not r.is_stress]
        if not stress_studies or not rest_studies:
            continue
        taken: set[str] = set()
        for stress_record in stress_studies:
            free = [r for r in rest_studies if r.study_uid not in taken]
            if not free:
                break
            stress_day = _date_day(stress_record.study_date)
            if stress_day is not None:
                rest = min(
                    free,
                    key=lambda r: (
                        abs((_date_day(r.study_date) or stress_day) - stress_day),
                        r.study_uid,
                    ),
                )
            else:
                rest = min(free, key=lambda r: r.study_uid)
            taken.add(rest.study_uid)
            pairs.append((rest.study_uid, stress_record.study_uid))
    return tuple(pairs)


def _date_day(iso_date: str) -> int | None:
    """Compact day number for an ISO date; ``None`` when absent/malformed."""
    try:
        year, month, day = iso_date.split("-")
        return int(year) * 10000 + int(month) * 100 + int(day)
    except (ValueError, AttributeError):
        return None


def build_stress_assessment(
    rest: StressEchoScoring | None,
    stress: StressEchoScoring | None,
) -> StressEchoAssessment | None:
    """The session/report record, or ``None`` when nothing was scored.

    Both stages live in one record even when only one has scores — the
    comparison columns then read ``None``/``no_comparison`` honestly instead
    of the record pretending the missing stage was normal.
    """
    rest_scoring = rest if rest is not None else StressEchoScoring()
    stress_scoring = stress if stress is not None else StressEchoScoring()
    assessment = StressEchoAssessment(rest=rest_scoring, stress=stress_scoring)
    if assessment.is_empty():
        return None
    return assessment


def stage_order() -> tuple[str, ...]:
    """The display order of the stages (rest first — the protocol's anchor)."""
    return (STAGE_REST, STAGE_STRESS)


def stress_studies_from_protocol_names(
    records: Iterable[tuple[str, str, str, str]],
) -> tuple[StressStudyRecord, ...]:
    """Convenience: ``(uid, patient, date, protocol)`` tuples → records.

    The stress side is detected with the loader's own rule
    (:func:`is_stress_study`) so the pairing cannot disagree with the dialog.
    """
    return tuple(
        StressStudyRecord(
            study_uid=uid,
            patient_id=patient,
            study_date=date,
            protocol_name=protocol,
            is_stress=is_stress_study(protocol),
        )
        for uid, patient, date, protocol in records
    )
