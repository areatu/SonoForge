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


def test_grade_elevated_e_over_e_prime() -> None:
    result = grade_diastolic_function(
        e_over_e_prime=15.0,
        lav_index_ml_m2=40.0,
        tr_vmax_cm_s=None,
    )
    assert result is not None
    assert "Grade" in result
