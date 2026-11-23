"""Stress-echo WMSI workflow — scoring, suggestions, comparison, pairing (plan А.11, issue #649).

The physician's visual ASE 1–5 scoring is the measurement; these tests pin
the honest plumbing around it: the WMSI is the mean over the *scored*
segments only, a suggestion carries its source and never reads as a
verdict, the comparison exists only when both stages scored, and ischaemia
means *new or worsening* wall motion — not a fixed rest abnormality.
"""

from __future__ import annotations

import json

import pytest

from echo_personal_tool.domain.models.stress_echo import (
    SCORE_AKINETIC,
    SCORE_ANEURYSMAL,
    SCORE_DYSKINETIC,
    SCORE_HYPOKINETIC,
    SCORE_NORMAL,
    SOURCE_MANUAL,
    SOURCE_STRAIN_SUGGESTION,
    STAGE_REST,
    STAGE_STRESS,
    StressEchoAssessment,
    StressEchoScoring,
)
from echo_personal_tool.domain.services.stress_workflow import (
    StressStudyRecord,
    build_stress_assessment,
    pair_stress_studies,
    suggest_scoring_from_strain,
    suggest_wall_motion_score,
)


class TestSuggestion:
    def test_the_threshold_rule_covers_the_ase_scale(self) -> None:
        assert suggest_wall_motion_score(-22.0) == SCORE_NORMAL
        assert suggest_wall_motion_score(-15.0) == SCORE_NORMAL
        assert suggest_wall_motion_score(-10.0) == SCORE_HYPOKINETIC
        assert suggest_wall_motion_score(-8.0) == SCORE_HYPOKINETIC
        assert suggest_wall_motion_score(-3.0) == SCORE_AKINETIC
        assert suggest_wall_motion_score(2.5) == SCORE_DYSKINETIC

    def test_aneurysmal_is_never_suggested_from_strain(self) -> None:
        """Dyskinesia vs aneurysm needs the eye — strain stays at score 4."""
        for value in (5.0, 50.0):
            assert suggest_wall_motion_score(value) == SCORE_DYSKINETIC
        assert SCORE_ANEURYSMAL not in {suggest_wall_motion_score(v) for v in range(-100, 51)}

    def test_suggestion_carries_its_source(self) -> None:
        scoring = suggest_scoring_from_strain({3: -20.0, 9: -4.0})
        assert scoring.scores == {3: SCORE_NORMAL, 9: SCORE_AKINETIC}
        assert scoring.source_of(3) == SOURCE_STRAIN_SUGGESTION
        assert scoring.source_of(9) == SOURCE_STRAIN_SUGGESTION

    def test_non_finite_and_low_quality_segments_stay_unscored(self) -> None:
        values = {3: float("nan"), 9: float("inf"), 15: -20.0, 6: -10.0}
        scoring = suggest_scoring_from_strain(values, segment_quality={15: 0.9, 6: 0.1}, min_quality=0.5)
        assert set(scoring.scores) == {15}
        assert scoring.scored_count() == 1

    def test_a_manual_verdict_never_carries_the_suggestion_source(self) -> None:
        scoring = suggest_scoring_from_strain({3: -20.0})
        overridden = scoring.with_score(3, SCORE_HYPOKINETIC, source=SOURCE_MANUAL)
        assert overridden.source_of(3) == SOURCE_MANUAL
        assert overridden.scores[3] == SCORE_HYPOKINETIC


class TestScoringAndWmsi:
    def test_wmsi_is_the_mean_over_scored_segments_only(self) -> None:
        scoring = StressEchoScoring(scores={1: 1, 2: 2, 3: 3, 4: 4, 5: 5})
        assert scoring.wmsi() == pytest.approx(3.0)
        assert scoring.scored_count() == 5

    def test_an_empty_stage_has_no_wmsi(self) -> None:
        assert StressEchoScoring().wmsi() is None

    def test_scores_outside_the_scale_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="ASE 1–5"):
            StressEchoScoring(scores={3: 6})
        with pytest.raises(ValueError, match="ASE 1–5"):
            StressEchoScoring(scores={3: 0})

    def test_with_score_keeps_the_rest_of_the_stage(self) -> None:
        scoring = StressEchoScoring(scores={3: 1, 9: 2})
        updated = scoring.with_score(15, 3)
        assert updated.scores == {3: 1, 9: 2, 15: 3}
        assert updated.source_of(15) == SOURCE_MANUAL


class TestComparison:
    def _assessment(self, rest: dict[int, int], stress: dict[int, int]) -> StressEchoAssessment:
        return StressEchoAssessment(rest=StressEchoScoring(scores=rest), stress=StressEchoScoring(scores=stress))

    def test_delta_and_worsened_segments(self) -> None:
        assessment = self._assessment({3: 1, 9: 1, 15: 2}, {3: 1, 9: 3, 15: 2})
        assert assessment.wmsi_delta() == pytest.approx((1 + 3 + 2) / 3 - (1 + 1 + 2) / 3)
        assert assessment.worsened_segments() == (9,)
        assert assessment.new_abnormal_segments() == (9,)

    def test_new_abnormality_requires_a_normal_rest(self) -> None:
        assessment = self._assessment({3: 2}, {3: 3})
        assert assessment.worsened_segments() == (3,)
        assert assessment.new_abnormal_segments() == ()  # already abnormal at rest

    def test_ischaemia_verdict_needs_new_or_worsening_motion(self) -> None:
        assert self._assessment({3: 1, 9: 1}, {3: 2, 9: 1}).verdict_code() == "ischaemia"
        assert self._assessment({3: 1, 9: 1}, {3: 1, 9: 1}).verdict_code() == "normal"
        assert self._assessment({3: 2, 9: 2}, {3: 2, 9: 2}).verdict_code() == "abnormal_rest"

    def test_a_high_stress_wmsi_with_a_normal_rest_is_ischaemia(self) -> None:
        # Segments scored only at stress cannot drive "worsened" (no rest
        # score to compare) — but a stress WMSI above normal against a normal
        # rest WMSI is ischaemia through the aggregate branch.
        assessment = self._assessment({3: 1, 9: 1}, {15: 3, 6: 3})
        assert assessment.worsened_segments() == ()
        assert assessment.new_abnormal_segments() == ()
        assert assessment.verdict_code() == "ischaemia"

    def test_half_a_comparison_is_no_comparison(self) -> None:
        assert self._assessment({3: 1}, {}).verdict_code() == "no_comparison"
        assert self._assessment({}, {3: 1}).verdict_code() == "no_comparison"

    def test_stage_access_and_replacement(self) -> None:
        assessment = self._assessment({3: 1}, {3: 2})
        assert assessment.stage(STAGE_REST).scores == {3: 1}
        updated = assessment.with_stage(STAGE_STRESS, StressEchoScoring(scores={3: 4}))
        assert updated.stress.scores == {3: 4}
        assert updated.rest.scores == {3: 1}
        with pytest.raises(ValueError, match="unknown stress stage"):
            assessment.with_stage("recovery", StressEchoScoring())


class TestAssessmentBuildAndExport:
    def test_an_empty_assessment_is_not_built(self) -> None:
        assert build_stress_assessment(None, None) is None
        assert build_stress_assessment(StressEchoScoring(), StressEchoScoring()) is None

    def test_a_single_scored_stage_builds_a_honest_record(self) -> None:
        assessment = build_stress_assessment(StressEchoScoring(scores={3: 2}), None)
        assert assessment is not None
        assert assessment.wmsi_rest() == pytest.approx(2.0)
        assert assessment.wmsi_stress() is None
        assert assessment.wmsi_delta() is None
        assert assessment.verdict_code() == "no_comparison"

    def test_the_record_is_json_serialisable(self) -> None:
        assessment = build_stress_assessment(
            StressEchoScoring(scores={3: 1, 9: 1}), StressEchoScoring(scores={3: 3, 9: 1})
        )
        data = assessment.to_dict()
        assert data["verdict"] == "ischaemia"
        assert data["worsened_segments"] == [3]
        json.dumps(data)


class TestPairing:
    def test_pairs_by_patient_with_the_nearest_rest_date(self) -> None:
        records = [
            StressStudyRecord("rest-1", "P1", "2026-01-10"),
            StressStudyRecord("rest-2", "P1", "2026-02-01"),
            StressStudyRecord("stress-1", "P1", "2026-02-03", protocol_name="Добутамин", is_stress=True),
            StressStudyRecord("stress-2", "P2", "2026-03-01", is_stress=True),
            StressStudyRecord("rest-3", "P2", "2026-03-02"),
        ]
        pairs = pair_stress_studies(records)
        # P1: stress 2026-02-03 pairs with rest-2 (4 days), not rest-1 (24).
        assert ("rest-2", "stress-1") in pairs
        # P2: the only rest study pairs.
        assert ("rest-3", "stress-2") in pairs

    def test_a_study_pairs_at_most_once(self) -> None:
        records = [
            StressStudyRecord("rest-1", "P1", "2026-01-10"),
            StressStudyRecord("stress-1", "P1", "2026-01-11", is_stress=True),
            StressStudyRecord("stress-2", "P1", "2026-01-12", is_stress=True),
        ]
        pairs = pair_stress_studies(records)
        assert len(pairs) == 1

    def test_a_stress_study_without_rest_stays_unpaired(self) -> None:
        records = [StressStudyRecord("stress-1", "P1", is_stress=True)]
        assert pair_stress_studies(records) == ()

    def test_protocol_names_drive_the_stress_side(self) -> None:
        from echo_personal_tool.domain.services.stress_workflow import stress_studies_from_protocol_names

        records = stress_studies_from_protocol_names(
            [
                ("rest-1", "P1", "2026-01-10", "ЭхоКГ покой"),
                ("stress-1", "P1", "2026-01-11", "Добутаминовая проба"),
                ("stress-2", "P1", "2026-01-12", "dobutamine stress"),
            ]
        )
        assert [r.is_stress for r in records] == [False, True, True]
        pairs = pair_stress_studies(records)
        assert ("rest-1", "stress-1") in pairs
        # The second stress study has no free rest counterpart.
        assert len(pairs) == 1
