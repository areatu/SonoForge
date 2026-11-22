"""Tests for diastology grading."""

from __future__ import annotations

from echo_personal_tool.domain.calculations.diastology_grade import (
    GRADE_ABNORMAL,
    GRADE_INSUFFICIENT,
    diastolic_criteria,
    grade_diastolic_code,
    grade_diastolic_function,
)


def test_grade_normal_low_e_over_e_prime() -> None:
    grade = grade_diastolic_function(
        e_over_e_prime=7.0,
        lav_index_ml_m2=28.0,
        tr_vmax_cm_s=200.0,
    )
    assert grade == "Normal"


def test_grade_abnormal_multiple_criteria() -> None:
    result = grade_diastolic_function(
        e_over_e_prime=15.0,
        lav_index_ml_m2=40.0,
        tr_vmax_cm_s=300.0,
    )
    assert result == "Abnormal"


def test_grade_indeterminate_half_criteria() -> None:
    result = grade_diastolic_function(
        e_over_e_prime=12.0,
        lav_index_ml_m2=40.0,
        tr_vmax_cm_s=300.0,
        e_prime_sept_cm_s=8.0,
    )
    assert result == "Indeterminate"


def test_grade_insufficient_data_few_criteria() -> None:
    result = grade_diastolic_function(
        e_over_e_prime=15.0,
        lav_index_ml_m2=40.0,
        tr_vmax_cm_s=None,
    )
    assert result is None


def test_grade_none_when_no_data() -> None:
    result = grade_diastolic_function(
        e_over_e_prime=None,
        lav_index_ml_m2=None,
        tr_vmax_cm_s=None,
    )
    assert result is None


class TestDiastolicCriteria:
    """The criteria table is the shared truth of the grade and the А.10 panel."""

    def test_rows_are_in_ase_display_order(self) -> None:
        rows = diastolic_criteria(
            e_over_e_prime=16.0,
            e_prime_sept_cm_s=6.0,
            lav_index_ml_m2=40.0,
            tr_vmax_cm_s=300.0,
        )
        assert [row.id for row in rows] == ["e_over_e_prime", "e_prime", "lav_index", "tr_vmax"]

    def test_absent_inputs_produce_no_row(self) -> None:
        assert diastolic_criteria() == ()
        rows = diastolic_criteria(e_over_e_prime=10.0)
        assert len(rows) == 1 and rows[0].id == "e_over_e_prime"

    def test_verdicts_compare_magnitudes(self) -> None:
        rows = diastolic_criteria(tr_vmax_cm_s=-312.0, e_prime_sept_cm_s=-6.5)
        assert rows[0].met is True
        assert rows[1].met is True

    def test_limits_are_language_neutral_thresholds(self) -> None:
        rows = diastolic_criteria(
            e_over_e_prime=16.0,
            e_prime_lat_cm_s=12.0,
            lav_index_ml_m2=40.0,
            tr_vmax_cm_s=300.0,
        )
        assert [row.limit for row in rows] == ["> 14", "< 10 cm/s", "> 34 mL/m²", "> 280 cm/s"]

    def test_septal_e_prime_preferred_over_lateral(self) -> None:
        rows = diastolic_criteria(e_prime_sept_cm_s=6.0, e_prime_lat_cm_s=16.0)
        assert len(rows) == 1
        assert rows[0].value == 6.0 and rows[0].limit == "< 7 cm/s"

    def test_grade_consumes_the_same_table(self) -> None:
        # The refactored grade keeps its pinned majority-rule behavior.
        assert grade_diastolic_code(e_over_e_prime=15.0, lav_index_ml_m2=40.0, tr_vmax_cm_s=300.0) == GRADE_ABNORMAL
        assert grade_diastolic_code(e_over_e_prime=15.0, tr_vmax_cm_s=300.0) == GRADE_INSUFFICIENT
