"""Tests for diastology grading."""

from __future__ import annotations

from echo_personal_tool.domain.calculations.diastology_grade import grade_diastolic_function


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
    assert result == "Insufficient data"


def test_grade_none_when_no_data() -> None:
    result = grade_diastolic_function(
        e_over_e_prime=None,
        lav_index_ml_m2=None,
        tr_vmax_cm_s=None,
    )
    assert result is None
