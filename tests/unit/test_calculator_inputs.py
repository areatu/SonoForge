"""Resolving calculator inputs from a study, with provenance (Э11)."""

from __future__ import annotations

import pytest

from echo_personal_tool.application.calculator_inputs import (
    CalculatorInputStore,
    HeartRateCandidate,
    lvot_diameter_cm,
    resolve_standalone_inputs,
    resolve_study_inputs,
    sanitize_manual_value,
)
from echo_personal_tool.domain.calculations.doppler_metrics import compute
from echo_personal_tool.domain.calculators.engine import evaluate
from echo_personal_tool.domain.calculators.models import (
    SOURCE_DERIVED,
    SOURCE_DICOM,
    SOURCE_ESTIMATE,
    SOURCE_MANUAL,
    SOURCE_MEASURED,
    SOURCE_MISSING,
    SOURCE_PATIENT,
)
from echo_personal_tool.domain.calculators.text import inputs_summary, source_text
from echo_personal_tool.domain.models.doppler import DopplerMeasurementDTO, DopplerPeakMarker, DopplerTrace
from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
from echo_personal_tool.infrastructure.i18n import set_language


def _trace(label: str, vti_cm: float, mid: str) -> DopplerTrace:
    """Triangle envelope 0→peak→0 over 300 ms with the requested VTI.

    VTI = ½ · peak · 0.3 s  →  peak = VTI / 0.15 (cm/s).
    """
    peak = vti_cm / 0.15
    return DopplerTrace(label=label, points=((0.0, 0.0), (150.0, peak), (300.0, 0.0)), measurement_id=mid)


def _dto(*, lvot_vtis=(20.0,), av_vtis=(100.0,), lvot_vmax=(100.0,), av_vmax=(450.0,)) -> DopplerMeasurementDTO:
    traces = [_trace("LVOT VTI", v, f"l{i}") for i, v in enumerate(lvot_vtis)]
    traces += [_trace("AV VTI", v, f"a{i}") for i, v in enumerate(av_vtis)]
    peaks = [DopplerPeakMarker("LVOT Vmax", 10.0 * i, v, f"lp{i}", "PW") for i, v in enumerate(lvot_vmax)]
    peaks += [DopplerPeakMarker("AV Vmax", 10.0 * i, -v, f"ap{i}", "CW") for i, v in enumerate(av_vmax)]
    return DopplerMeasurementDTO(peaks=tuple(peaks), intervals=(), traces=tuple(traces))


def _lvotd(mm: float, frame: int = 0) -> LinearMeasurement:
    return LinearMeasurement(label="LVOTd", pixel_length=40.0, millimeter_length=mm, frame_index=frame)


def test_lvot_diameter_is_mean_of_last_three_calipers_in_cm() -> None:
    measurements = [_lvotd(18.0, 0), _lvotd(20.0, 1), _lvotd(21.0, 2), _lvotd(22.0, 3)]
    value, count = lvot_diameter_cm(measurements)
    assert value == pytest.approx(2.1)
    assert count == 4
    set_language("ru")
    item = resolve_study_inputs(doppler=None, linear_measurements=measurements)["lvot_d"]
    assert source_text(item) == "измерение, среднее (n=3)"


def test_lvot_diameter_ignores_uncalibrated_doppler_and_other_labels() -> None:
    measurements = [
        LinearMeasurement(label="LVOTd", pixel_length=40.0, millimeter_length=None),
        LinearMeasurement(label="LVOTd", pixel_length=40.0, millimeter_length=20.0, doppler=True),
        LinearMeasurement(label="LVEDD", pixel_length=40.0, millimeter_length=50.0),
    ]
    assert lvot_diameter_cm(measurements) == (None, 0)


def test_study_inputs_come_from_measurements_with_repeats() -> None:
    doppler = compute(_dto(lvot_vtis=(18.0, 20.0, 22.0, 24.0)))
    inputs = resolve_study_inputs(
        doppler=doppler,
        linear_measurements=[_lvotd(20.0)],
        height_cm=175.0,
        weight_kg=75.0,
        height_source="dicom",
    )
    assert inputs["lvot_d"].value == pytest.approx(2.0)
    assert inputs["lvot_d"].source == SOURCE_MEASURED
    # Mean of the last three LVOT VTI traces (D-23), four in total.
    assert inputs["lvot_vti"].value == pytest.approx(22.0, abs=0.05)
    assert inputs["lvot_vti"].repeats == 3
    assert inputs["av_vti"].value == pytest.approx(100.0, abs=0.1)
    assert inputs["lvot_vmax"].value == pytest.approx(100.0)
    # Sign is a calibration artefact: below-baseline AV jet still reads 4.5 m/s.
    assert inputs["av_vmax"].value == pytest.approx(4.5)
    assert inputs["height"].source == SOURCE_PATIENT
    assert inputs["bsa"].source == SOURCE_DERIVED
    assert inputs["bsa"].detail == "Du Bois"
    assert inputs["hr"].source == SOURCE_MISSING


def test_vmax_from_trace_is_flagged() -> None:
    doppler = compute(_dto(lvot_vmax=(), av_vmax=()))
    inputs = resolve_study_inputs(doppler=doppler)
    assert inputs["lvot_vmax"].detail == "trace"
    set_language("en")
    assert "trace" in source_text(inputs["lvot_vmax"])


def test_manual_value_overrides_and_remembers_the_measurement() -> None:
    doppler = compute(_dto())
    inputs = resolve_study_inputs(doppler=doppler, manual={"lvot_vti": 25.0})
    item = inputs["lvot_vti"]
    assert item.value == 25.0
    assert item.source == SOURCE_MANUAL
    assert item.auto_value == pytest.approx(20.0, abs=0.05)
    assert item.overridden


def test_manual_value_fills_a_missing_input_without_override_flag() -> None:
    inputs = resolve_study_inputs(doppler=None, manual={"hr": 72.0})
    assert inputs["hr"].source == SOURCE_MANUAL
    assert not inputs["hr"].overridden


def test_manual_bsa_wins_over_height_and_weight() -> None:
    inputs = resolve_study_inputs(doppler=None, height_cm=175.0, weight_kg=75.0, manual={"bsa": 2.0})
    assert inputs["bsa"].value == 2.0
    assert inputs["bsa"].overridden


def test_manual_height_recomputes_bsa() -> None:
    inputs = resolve_study_inputs(doppler=None, height_cm=175.0, weight_kg=75.0, manual={"height": 160.0})
    assert inputs["bsa"].value == pytest.approx(0.007184 * 160**0.725 * 75**0.425)


def test_heart_rate_candidate_keeps_its_source() -> None:
    dicom = resolve_study_inputs(doppler=None, heart_rate=HeartRateCandidate(64.0, SOURCE_DICOM, "HeartRate"))
    assert dicom["hr"].value == 64.0 and dicom["hr"].source == SOURCE_DICOM
    estimate = resolve_study_inputs(doppler=None, heart_rate=HeartRateCandidate(80.0, SOURCE_ESTIMATE, "optical_flow"))
    assert estimate["hr"].source == SOURCE_ESTIMATE


def test_study_evaluation_end_to_end_with_provenance_summary() -> None:
    set_language("en")
    doppler = compute(_dto())
    inputs = resolve_study_inputs(
        doppler=doppler,
        linear_measurements=[_lvotd(20.0)],
        heart_rate=HeartRateCandidate(70.0, SOURCE_DICOM, "HeartRate"),
        manual={"bsa": 1.9},
    )
    calculations = evaluate(inputs)
    assert calculations.result("stroke_volume").output("co").value == pytest.approx(4.398, abs=0.01)
    assert calculations.result("aortic_valve_area").output("ava_vti").value == pytest.approx(0.628, abs=0.005)
    summary = inputs_summary(calculations)
    assert "LVOTd 2.00 cm (measured)" in summary
    assert "HR 70 bpm (DICOM HeartRate of the LVOT VTI clip)" in summary
    assert "BSA 1.90 m² (manual)" in summary


def test_standalone_inputs_are_manual_only() -> None:
    inputs = resolve_standalone_inputs({"lvot_d": 2.0, "height": 170.0, "weight": 70.0})
    assert inputs["lvot_d"].source == SOURCE_MANUAL
    assert inputs["lvot_vti"].source == SOURCE_MISSING
    assert inputs["bsa"].source == SOURCE_DERIVED


def test_store_sets_clears_and_validates() -> None:
    store = CalculatorInputStore()
    assert store.set_manual("study", "hr", 70.0)
    assert not store.set_manual("study", "hr", 70.0)
    assert store.manual("study") == {"hr": 70.0}
    assert store.manual("other") == {}
    assert store.set_manual("study", "hr", None)
    assert not store.set_manual("study", "hr", None)
    with pytest.raises(ValueError):
        store.set_manual("study", "lvot_d", 200.0)
    with pytest.raises(KeyError):
        store.set_manual("study", "nope", 1.0)
    store.set_manual("study", "hr", 70.0)
    store.set_hr_estimate("study", 66.0, "optical_flow")
    assert store.hr_estimate("study").bpm == 66.0
    store.set_hr_estimate("study", 0.0, "optical_flow")  # ignored
    assert store.hr_estimate("study").bpm == 66.0
    store.clear_study("study")
    assert store.manual("study") == {}
    assert store.hr_estimate("study") is None


def test_sanitize_manual_value() -> None:
    assert sanitize_manual_value("hr", None) is None
    assert sanitize_manual_value("hr", 70) == 70.0
    with pytest.raises(ValueError):
        sanitize_manual_value("hr", 0.0)
