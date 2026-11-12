from __future__ import annotations

import re

import pytest

from echo_personal_tool.domain.calculations.regurgitation_grade import (
    ar_grade_from_jet_area_ratio_percent,
    ar_grade_from_jet_width_ratio_percent,
    ar_grade_from_vc_mm,
    ar_integrated_grade,
    integrated_grade,
    mr_grade_from_vc_mm,
    mr_integrated_grade,
)
from echo_personal_tool.domain.calculators.reference_hints import reference_hint


def test_mr_integrated_grade_uses_consensus_when_vc_disagrees_with_pisa() -> None:
    # Severe VC (10 mm) but moderate EROA/RVol → grade 2 by the documented
    # lower-median rule; individual parameter grades remain shown separately.
    assert mr_integrated_grade(0.25, 50.0, 10.0) == 2.0


def test_ar_integrated_grade_allows_mild_area_ratio_to_outweigh_moderate_vc() -> None:
    # VC 4 mm = moderate; jet-area/LVOT ratio 4% = mild → lower-median grade 1.
    assert ar_integrated_grade(0.08, 20.0, 4.0, 4.0) == 1.0


def test_integrated_grade_ignores_unavailable_and_invalid_parameters() -> None:
    assert integrated_grade((None, 2, 8, 3)) == 2.0
    assert integrated_grade((None, 0, 4)) is None


@pytest.mark.parametrize(
    ("grade", "value", "expected"),
    [
        (mr_grade_from_vc_mm, 2.9, 1),
        (mr_grade_from_vc_mm, 3.0, 2),
        (mr_grade_from_vc_mm, 6.9, 2),
        (mr_grade_from_vc_mm, 7.0, 3),
        (ar_grade_from_vc_mm, 2.9, 1),
        (ar_grade_from_vc_mm, 3.0, 2),
        (ar_grade_from_vc_mm, 6.0, 3),
        (ar_grade_from_jet_area_ratio_percent, 4.9, 1),
        (ar_grade_from_jet_area_ratio_percent, 5.0, 2),
        (ar_grade_from_jet_area_ratio_percent, 60.0, 3),
        (ar_grade_from_jet_width_ratio_percent, 24.9, 1),
        (ar_grade_from_jet_width_ratio_percent, 25.0, 2),
        (ar_grade_from_jet_width_ratio_percent, 65.0, 3),
    ],
)
def test_parameter_grade_boundaries_match_the_reference_gradations(grade, value, expected) -> None:
    assert grade(value) == expected


def test_ar_width_ratio_alone_grades_the_jet_against_the_lvot() -> None:
    # Without PISA inputs the measured jet width / LVOT width still grades.
    assert ar_integrated_grade(None, None, None, None, 30.0) == 2.0
    assert ar_integrated_grade(None, None, None, None, 12.0) == 1.0
    assert ar_integrated_grade(None, None, None, None) is None


def test_negative_measurements_are_treated_as_unavailable() -> None:
    assert mr_grade_from_vc_mm(-1.0) is None
    assert ar_grade_from_jet_width_ratio_percent(-1.0) is None


def _first_number(text: str) -> float:
    return float(re.search(r"\d+(?:\.\d+)?", text).group())


@pytest.mark.parametrize(
    ("reference_id", "grader"),
    [
        ("mr_vc_primary", mr_grade_from_vc_mm),
        ("ar_vc", ar_grade_from_vc_mm),
        ("ar_jet_csa_lvot", ar_grade_from_jet_area_ratio_percent),
        ("ar_jet_width_lvot", ar_grade_from_jet_width_ratio_percent),
    ],
)
def test_graders_agree_with_the_bundled_reference_bands(reference_id: str, grader) -> None:
    """The colouring/grading thresholds must not drift from the reference table."""
    hint = reference_hint(reference_id, "en")
    assert hint is not None and len(hint.gradations) == 3, reference_id

    mild_high = _first_number(hint.gradations[0].range_text)
    assert grader(mild_high - 1e-9) == 1
    assert grader(mild_high) == 2

    severe_low = _first_number(hint.gradations[-1].range_text)
    assert grader(severe_low) == 3
