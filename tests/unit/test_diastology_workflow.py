"""Turnkey diastology workflow (plan А.10, issue #648).

Pure domain tests: the assembly from ``DopplerResults``, the criteria
verdicts, the grade arithmetic and the honest missing-inputs reporting.
"""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.calculations.diastology_grade import (
    GRADE_ABNORMAL,
    GRADE_INDETERMINATE,
    GRADE_INSUFFICIENT,
    GRADE_NORMAL,
)
from echo_personal_tool.domain.models.diastology import DiastologyField
from echo_personal_tool.domain.models.doppler import DopplerIntervalMarker, DopplerPeakMarker
from echo_personal_tool.domain.models.measurements import DopplerFlowResult, DopplerResults
from echo_personal_tool.domain.services.diastology_workflow import build_diastology_assessment


def _flow(site: str, *, vmax: float | None = None, repeats: int = 0) -> DopplerFlowResult:
    return DopplerFlowResult(site=site, vmax_cm_s=vmax, vmax_repeats=repeats)


def _results(**overrides: object) -> DopplerResults:
    """A DopplerResults with a typical normal-ish diastology dataset."""
    base: dict[str, object] = {
        "e_cm_s": 80.0,
        "a_cm_s": 60.0,
        "e_a_ratio": 80.0 / 60.0,
        "dt_ms": 200.0,
        "e_prime_sept_cm_s": 9.0,
        "e_prime_lat_cm_s": 12.0,
        "e_prime_avg_cm_s": 10.5,
        "e_over_e_prime": 80.0 / 10.5,
        "e_over_e_prime_sept": 80.0 / 9.0,
        "e_over_e_prime_lat": 80.0 / 12.0,
        "e_prime_over_a_prime": None,
        "tr_vmax_cm_s": 240.0,
        "ivrt_ms": 90.0,
        "peaks": (
            DopplerPeakMarker("E", 100.0, 80.0),
            DopplerPeakMarker("A", 130.0, 60.0),
            DopplerPeakMarker("e sept", 110.0, 9.0),
        ),
        "intervals": (DopplerIntervalMarker("IVRT", 400.0, 490.0),),
        "flow_results": (
            _flow("TR", vmax=240.0, repeats=2),
            _flow("PV", vmax=130.0, repeats=1),
        ),
    }
    base.update(overrides)
    return DopplerResults(**base)  # type: ignore[arg-type]


class TestFields:
    def test_fields_are_the_auto_filled_panel_in_display_order(self) -> None:
        assessment = build_diastology_assessment(_results(), lav_index_ml_m2=28.0)
        ids = [field.id for field in assessment.fields]
        assert ids[0] == "e" and ids[1] == "a" and ids[2] == "e_a"
        assert "tr_vmax" in ids and "pv_vmax" in ids and "ivrt" in ids and "lav_index" in ids

    def test_field_values_come_from_the_results(self) -> None:
        assessment = build_diastology_assessment(_results())
        assert assessment.field("e") == DiastologyField("e", 80.0, "cm/s", 1)
        assert assessment.field("e_a") is not None and assessment.field("e_a").value == pytest.approx(80.0 / 60.0)
        assert assessment.field("dt").value == pytest.approx(200.0)

    def test_repeat_counts_count_accepted_markers(self) -> None:
        results = _results(
            peaks=(
                DopplerPeakMarker("E", 100.0, 80.0),
                DopplerPeakMarker("E", 120.0, 78.0),
                DopplerPeakMarker("E", 140.0, 90.0, accepted=False),
                DopplerPeakMarker("e sept", 110.0, 9.0),
            )
        )
        assessment = build_diastology_assessment(results)
        assert assessment.field("e").n == 2  # one excluded beat stays out
        assert assessment.field("ivrt").n == 1

    def test_tr_and_pv_counts_come_from_the_flow_results(self) -> None:
        assessment = build_diastology_assessment(_results())
        assert assessment.field("tr_vmax").n == 2
        assert assessment.field("pv_vmax") is not None
        assert assessment.field("pv_vmax").value == pytest.approx(130.0)
        assert assessment.field("tr_pgmax") is not None

    def test_lav_index_is_a_passed_through_input(self) -> None:
        assessment = build_diastology_assessment(_results(), lav_index_ml_m2=41.5)
        assert assessment.field("lav_index").value == pytest.approx(41.5)
        assert assessment.field("lav_index").unit == "mL/m²"

    def test_absent_measurements_stay_none(self) -> None:
        assessment = build_diastology_assessment(DopplerResults())
        assert assessment.field("e") is not None and assessment.field("e").value is None
        assert assessment.field("tr_vmax").value is None
        assert assessment.field("ivrt").value is None


class TestCriteria:
    def test_criteria_rows_are_ase_ordered(self) -> None:
        assessment = build_diastology_assessment(_results(), lav_index_ml_m2=28.0)
        assert [row.id for row in assessment.criteria] == [
            "e_over_e_prime",
            "e_prime",
            "lav_index",
            "tr_vmax",
        ]

    def test_verdicts_use_magnitudes(self) -> None:
        results = _results(tr_vmax_cm_s=-312.0)
        assessment = build_diastology_assessment(results)
        tr_row = next(row for row in assessment.criteria if row.id == "tr_vmax")
        assert tr_row.met is True  # a below-baseline jet still meets > 280

    def test_septal_e_prime_wins_over_lateral(self) -> None:
        assessment = build_diastology_assessment(_results(e_prime_sept_cm_s=6.0, e_prime_lat_cm_s=16.0))
        e_prime_row = next(row for row in assessment.criteria if row.id == "e_prime")
        assert e_prime_row.value == pytest.approx(6.0)
        assert e_prime_row.met is True
        assert e_prime_row.limit == "< 7 cm/s"

    def test_missing_inputs_listed_in_ase_order(self) -> None:
        assessment = build_diastology_assessment(_results(e_over_e_prime=None, tr_vmax_cm_s=None), lav_index_ml_m2=28.0)
        assert assessment.missing_inputs == ("e_over_e_prime", "tr_vmax")

    def test_no_inputs_at_all_lists_everything(self) -> None:
        assessment = build_diastology_assessment(DopplerResults())
        assert assessment.missing_inputs == ("e_over_e_prime", "e_prime", "lav_index", "tr_vmax")
        assert assessment.grade_code is None


class TestGrade:
    def test_normal_when_minority_of_criteria_met(self) -> None:
        # 1 of 4 met (E/e′ 7.6 no, e′ 9 no, LAVi 28 no, TR 240 no → 0 of 4)
        assessment = build_diastology_assessment(_results(), lav_index_ml_m2=28.0)
        assert assessment.grade_code == GRADE_NORMAL
        assert assessment.verdict_note(language="en").startswith("Normal — 0 of 4")

    def test_abnormal_when_majority_met(self) -> None:
        results = _results(
            e_over_e_prime=16.0,
            e_prime_sept_cm_s=6.0,
            tr_vmax_cm_s=300.0,
        )
        assessment = build_diastology_assessment(results, lav_index_ml_m2=40.0)
        assert assessment.grade_code == GRADE_ABNORMAL
        assert assessment.verdict_note(language="ru").startswith("Нарушение ДФ")

    def test_indeterminate_on_exact_split(self) -> None:
        results = _results(e_over_e_prime=16.0, tr_vmax_cm_s=300.0)
        assessment = build_diastology_assessment(results, lav_index_ml_m2=28.0)
        # 2 of 4 met (E/e′ yes, TR yes, e′ no, LAVi no)
        assert assessment.grade_code == GRADE_INDETERMINATE
        assert "2 из 4" in assessment.verdict_note(language="ru")
        assert "split (2 of 4)" in assessment.verdict_note(language="en")

    def test_insufficient_with_missing_list(self) -> None:
        assessment = build_diastology_assessment(_results(e_over_e_prime=None, tr_vmax_cm_s=None), lav_index_ml_m2=28.0)
        # e′ no + LAVi no → only 2 criteria available
        assert assessment.grade_code == GRADE_INSUFFICIENT
        note = assessment.verdict_note(language="ru")
        assert note.startswith("Недостаточно данных")
        assert "E/e′" in note and "TR Vmax" in note

    def test_grade_label_covers_insufficient(self) -> None:
        assessment = build_diastology_assessment(DopplerResults(e_over_e_prime=10.0, tr_vmax_cm_s=240.0))
        assert assessment.grade_code == GRADE_INSUFFICIENT
        assert assessment.grade_label(language="en") == "Insufficient data"
        assert assessment.grade_label(language="ru") == "Недостаточно данных"

    def test_none_doppler_is_an_empty_assessment(self) -> None:
        assessment = build_diastology_assessment(None)
        assert assessment.fields == ()
        assert assessment.criteria == ()
        assert assessment.grade_code is None
        assert assessment.missing_inputs == ("e_over_e_prime", "e_prime", "lav_index", "tr_vmax")
        assert assessment.verdict_note(language="en") == ""
        assert assessment.grade_label(language="en") == ""
