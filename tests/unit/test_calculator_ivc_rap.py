"""RAP (ДПП) calculator input derived from the M-mode IVC pair."""

from __future__ import annotations

from echo_personal_tool.application.calculator_inputs import resolve_study_inputs
from echo_personal_tool.domain.calculators.models import SOURCE_DERIVED, SOURCE_MANUAL
from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement


def _pair() -> tuple[LinearMeasurement, ...]:
    return (
        LinearMeasurement(label="IVC-EXP", pixel_length=48.0, millimeter_length=24.0),
        LinearMeasurement(label="IVC-INSP", pixel_length=24.0, millimeter_length=12.0),
    )


def test_rap_filled_from_ivc_pair() -> None:
    inputs = resolve_study_inputs(doppler=None, linear_measurements=_pair())
    rap = inputs["rap"]
    assert rap.value == 8.0
    assert rap.source == SOURCE_DERIVED


def test_manual_rap_overrides_the_estimate() -> None:
    inputs = resolve_study_inputs(doppler=None, linear_measurements=_pair(), manual={"rap": 3.0})
    rap = inputs["rap"]
    assert rap.value == 3.0
    assert rap.source == SOURCE_MANUAL
    assert rap.auto_value == 8.0
    assert rap.auto_source == SOURCE_DERIVED


def test_no_pair_leaves_rap_empty() -> None:
    inputs = resolve_study_inputs(doppler=None, linear_measurements=())
    assert inputs["rap"].value is None


def test_newest_caliper_of_each_label_wins() -> None:
    measurements = (
        LinearMeasurement(label="IVC-EXP", pixel_length=48.0, millimeter_length=24.0),
        LinearMeasurement(label="ivc-exp", pixel_length=0.0, millimeter_length=None),
        LinearMeasurement(label="IVC-INSP", pixel_length=32.0, millimeter_length=16.0),
        LinearMeasurement(label="IVC-INSP", pixel_length=24.0, millimeter_length=12.0),
    )
    inputs = resolve_study_inputs(doppler=None, linear_measurements=measurements)
    # 24/12 mm → 50 % collapse → 8 mmHg; the stale 16 mm reading gives 15 mmHg.
    assert inputs["rap"].value == 8.0


# ── The domain rule behind the input (ASE right-heart IVC / RA pressure) ──


def test_collapse_percent_is_the_respiratory_drop_of_the_diameter() -> None:
    from echo_personal_tool.domain.calculations.right_atrial_pressure import ivc_collapse_percent

    assert ivc_collapse_percent(24.0, 12.0) == 50.0
    assert ivc_collapse_percent(20.0, 5.0) == 75.0
    assert ivc_collapse_percent(20.0, 20.0) == 0.0


def test_collapse_percent_stays_empty_without_two_finite_positive_diameters() -> None:
    from echo_personal_tool.domain.calculations.right_atrial_pressure import ivc_collapse_percent

    assert ivc_collapse_percent(None, 12.0) is None
    assert ivc_collapse_percent(24.0, None) is None
    assert ivc_collapse_percent(0.0, 0.0) is None
    assert ivc_collapse_percent(24.0, -1.0) is None
    assert ivc_collapse_percent(float("nan"), 12.0) is None


def test_the_three_pressure_categories_follow_the_cut_offs() -> None:
    from echo_personal_tool.domain.calculations.right_atrial_pressure import rap_from_ivc

    assert rap_from_ivc(2.0, 60.0) == 3  # small vessel, collapses well
    assert rap_from_ivc(2.5, 20.0) == 15  # dilated, does not collapse
    assert rap_from_ivc(2.0, 40.0) == 8  # small but stiff
    assert rap_from_ivc(2.5, 60.0) == 8  # dilated but collapsing


def test_a_value_exactly_on_a_cut_off_is_intermediate() -> None:
    from echo_personal_tool.domain.calculations.right_atrial_pressure import rap_from_ivc

    assert rap_from_ivc(2.1, 50.0) == 8
    assert rap_from_ivc(2.1, 50.5) == 3
    assert rap_from_ivc(2.11, 49.9) == 15


def test_an_out_of_range_input_does_not_guess_a_category() -> None:
    from echo_personal_tool.domain.calculations.right_atrial_pressure import rap_from_ivc

    assert rap_from_ivc(None, 60.0) is None
    assert rap_from_ivc(2.0, None) is None
    assert rap_from_ivc(0.0, 60.0) is None
    assert rap_from_ivc(2.0, 140.0) is None
    assert rap_from_ivc(2.0, -5.0) is None


def test_the_mmode_pair_feeds_size_from_expiration_and_collapse_from_both() -> None:
    from echo_personal_tool.domain.calculations.right_atrial_pressure import rap_from_ivc_pair

    assert rap_from_ivc_pair(20.0, 8.0) == (60.0, 3)
    assert rap_from_ivc_pair(24.0, 20.0) == (16.666666666666664, 15)
    assert rap_from_ivc_pair(None, 12.0) == (None, None)
