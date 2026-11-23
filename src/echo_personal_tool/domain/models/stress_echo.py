"""Stress-echo records — WMSI scoring per stage and the rest/stress comparison (plan А.11, issue #649).

Wall Motion Score Index (WMSI) is the physician's visual scoring of the LV
wall motion, segment by segment, on the ASE 1–5 scale; the index is the mean
over the *scored* segments (the clinical convention — an unvisualised segment
is not a ``1``). This module carries the records between the scoring UI, the
measurement session and the report; the domain logic that builds, suggests
and compares them lives in :mod:`echo_personal_tool.domain.services.stress_workflow`.

Honesty rules, the same as everywhere in this pipeline:

* a score is either the physician's manual verdict or a strain-derived
  suggestion — the source travels with the score, and a suggestion is never
  silently presented as a measurement;
* a stage with no scored segments has no WMSI — ``None``, never ``1.0``;
* the comparison (ΔWMSI, new/worsening segments) exists only when both stages
  have scored segments — half a comparison is not a conclusion.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: ASE wall-motion scale. A ``dict`` keeps the wire shape compact; the keys
#: are segment ids of the app's AHA-18 model, the values are 1..5.
SCORE_NORMAL = 1
SCORE_HYPOKINETIC = 2
SCORE_AKINETIC = 3
SCORE_DYSKINETIC = 4
SCORE_ANEURYSMAL = 5

VALID_SCORES: tuple[int, ...] = (
    SCORE_NORMAL,
    SCORE_HYPOKINETIC,
    SCORE_AKINETIC,
    SCORE_DYSKINETIC,
    SCORE_ANEURYSMAL,
)

#: Where a score came from — a suggestion must never read as a measurement.
SOURCE_MANUAL = "manual"
SOURCE_STRAIN_SUGGESTION = "strain_suggestion"

#: The two protocol stages (v1; dobutamine dose stages stay a follow-up).
STAGE_REST = "rest"
STAGE_STRESS = "stress"


def _clean_scores(
    scores: dict[int, int], sources: dict[int, str] | None = None
) -> tuple[dict[int, int], dict[int, str]]:
    """Validate + copy the scoring dicts (defensive: UI passes live objects)."""
    clean: dict[int, int] = {}
    for segment, score in dict(scores).items():
        value = int(score)
        if value not in VALID_SCORES:
            raise ValueError(f"wall-motion score {value} is not on the ASE 1–5 scale")
        clean[int(segment)] = value
    clean_sources = {int(seg): str(src) for seg, src in (sources or {}).items() if int(seg) in clean}
    return clean, clean_sources


@dataclass(frozen=True)
class StressEchoScoring:
    """One stage's wall-motion scores with their provenance."""

    scores: dict[int, int] = field(default_factory=dict)
    sources: dict[int, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        scores, sources = _clean_scores(self.scores, self.sources)
        object.__setattr__(self, "scores", scores)
        object.__setattr__(self, "sources", sources)

    def with_score(self, segment: int, score: int, *, source: str = SOURCE_MANUAL) -> StressEchoScoring:
        """A copy with one segment scored (validated); the rest stays intact."""
        scores = dict(self.scores)
        sources = dict(self.sources)
        scores[int(segment)] = int(score)
        sources[int(segment)] = source
        return StressEchoScoring(scores=scores, sources=sources)

    def scored_count(self) -> int:
        return len(self.scores)

    def wmsi(self) -> float | None:
        """Mean score over the scored segments — ``None`` when none scored.

        An unvisualised segment is *not* a normal segment: the clinical WMSI
        divides by the number of segments the physician actually scored.
        """
        if not self.scores:
            return None
        return float(sum(self.scores.values()) / len(self.scores))

    def source_of(self, segment: int) -> str | None:
        return self.sources.get(int(segment))


@dataclass(frozen=True)
class StressEchoAssessment:
    """Rest + stress wall-motion scoring with the comparison the report shows.

    Both stages live in one record so the rest/stress comparison cannot
    diverge between the window's live labels and the protocol section. An
    empty assessment (no scored segment at all) is never built — the workflow
    returns ``None`` and the report simply has no stress section.
    """

    rest: StressEchoScoring = field(default_factory=StressEchoScoring)
    stress: StressEchoScoring = field(default_factory=StressEchoScoring)

    def with_stage(self, stage: str, scoring: StressEchoScoring) -> StressEchoAssessment:
        """A copy with one stage's scoring replaced (the newest edit wins)."""
        if stage == STAGE_REST:
            return StressEchoAssessment(rest=scoring, stress=self.stress)
        if stage == STAGE_STRESS:
            return StressEchoAssessment(rest=self.rest, stress=scoring)
        raise ValueError(f"unknown stress stage: {stage!r}")

    def stage(self, stage: str) -> StressEchoScoring:
        if stage == STAGE_REST:
            return self.rest
        if stage == STAGE_STRESS:
            return self.stress
        raise ValueError(f"unknown stress stage: {stage!r}")

    def is_empty(self) -> bool:
        return not self.rest.scores and not self.stress.scores

    def wmsi_rest(self) -> float | None:
        return self.rest.wmsi()

    def wmsi_stress(self) -> float | None:
        return self.stress.wmsi()

    def wmsi_delta(self) -> float | None:
        """``WMSI_stress − WMSI_rest`` — positive when stress worsened."""
        rest, stress = self.wmsi_rest(), self.wmsi_stress()
        if rest is None or stress is None:
            return None
        return float(stress - rest)

    def worsened_segments(self) -> tuple[int, ...]:
        """Segments scored worse at stress than at rest (score increased)."""
        return tuple(
            sorted(
                seg
                for seg, score in self.stress.scores.items()
                if seg in self.rest.scores and score > self.rest.scores[seg]
            )
        )

    def new_abnormal_segments(self) -> tuple[int, ...]:
        """Segments that were normal at rest and abnormal (≥ hypokinetic) at stress."""
        return tuple(
            sorted(
                seg
                for seg, score in self.stress.scores.items()
                if self.rest.scores.get(seg) == SCORE_NORMAL and score >= SCORE_HYPOKINETIC
            )
        )

    def verdict_code(self) -> str:
        """The honest conclusion code; ``"no_comparison"`` when a stage is empty.

        Ischaemia = new or worsening wall-motion abnormality at stress (or a
        stress WMSI above normal while rest was normal). A rest abnormality
        that stress does not worsen is a *fixed* abnormality, not ischaemia.
        """
        if self.rest.scores == {} or self.stress.scores == {}:
            return "no_comparison"
        if self.worsened_segments() or self.new_abnormal_segments():
            return "ischaemia"
        rest, stress = self.wmsi_rest() or 1.0, self.wmsi_stress() or 1.0
        if rest <= 1.0 + 1e-9 and stress > 1.0 + 1e-9:
            return "ischaemia"
        if rest > 1.0 + 1e-9:
            return "abnormal_rest"
        return "normal"

    def to_dict(self) -> dict:
        """JSON-serialisable record (scores as strings keys — JSON dicts)."""
        return {
            "schema_version": 1,
            "rest": {"scores": {str(k): v for k, v in sorted(self.rest.scores.items())}},
            "stress": {"scores": {str(k): v for k, v in sorted(self.stress.scores.items())}},
            "wmsi_rest": self.wmsi_rest(),
            "wmsi_stress": self.wmsi_stress(),
            "wmsi_delta": self.wmsi_delta(),
            "worsened_segments": list(self.worsened_segments()),
            "verdict": self.verdict_code(),
        }
