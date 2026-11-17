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
