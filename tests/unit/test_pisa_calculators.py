"""PISA for mitral and aortic regurgitation (Э11б): formulas, registry, inputs, report.

Worked example (hand-checkable, matches the textbook PISA example):
r 1.0 cm, Va 40 cm/s → flow 2π·1²·40 = 251.3 mL/s; MR Vmax 5 m/s → EROA
251.3 / 500 = 0.50 cm²; MR VTI 150 cm → RVol 75.4 mL; with LVOTd 2.0 cm and
LVOT VTI 20 cm (forward SV 62.8 mL) → MR RF 75.4 / (75.4 + 62.8) = 54.6 %.
"""

from __future__ import annotations

import math

import pytest

from echo_personal_tool.application.calculator_inputs import (
    caliper_mean_cm,
    evaluate_standalone,
    resolve_study_inputs,
)
from echo_personal_tool.domain.calculations.doppler_metrics import compute
from echo_personal_tool.domain.calculations.pisa import (
    eroa_cm2,
    pisa_flow_rate_ml_s,
    regurgitant_fraction_ar_percent,
    regurgitant_fraction_mr_percent,
    regurgitant_volume_ml,
)
from echo_personal_tool.domain.calculators import CALCULATORS, calculator_spec, evaluate, input_spec
from echo_personal_tool.domain.calculators.models import SOURCE_MANUAL, SOURCE_MEASURED, SOURCE_MISSING
from echo_personal_tool.domain.calculators.reference_hints import reference_hint
from echo_personal_tool.domain.calculators.text import source_text, warning_text
from echo_personal_tool.domain.models.doppler import DopplerMeasurementDTO, DopplerPeakMarker, DopplerTrace
from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
from echo_personal_tool.domain.services.report_builder import (
    GROUP_AORTIC_VALVE,
    GROUP_CALCULATIONS,
    GROUP_MITRAL_VALVE,
    build_report_groups,
    group_for_label,
)
from echo_personal_tool.infrastructure.i18n import set_language

_MR = {"pisa_r_mr": 1.0, "va_mr": 40.0, "mr_vmax": 5.0, "mr_vti": 150.0}
_AR = {"pisa_r_ar": 0.6, "va_ar": 40.0, "ar_vmax": 4.0, "ar_vti": 200.0}
_LVOT = {"lvot_d": 2.0, "lvot_vti": 20.0}


@pytest.fixture(autouse=True)
def _english():
    set_language("en")
    yield
    set_language("en")


# ── formulas ────────────────────────────────────────────────────────────────
def test_pisa_flow_eroa_rvol_etalon() -> None:
    flow = pisa_flow_rate_ml_s(1.0, 40.0)
    assert flow == pytest.approx(2 * math.pi * 40.0)
    assert flow == pytest.approx(251.33, abs=0.01)
    eroa = eroa_cm2(flow, 500.0)
    assert eroa == pytest.approx(0.503, abs=1e-3)
    assert regurgitant_volume_ml(eroa, 150.0) == pytest.approx(75.4, abs=0.05)


def test_general_formula_matches_the_bedside_shortcut_only_at_its_assumptions() -> None:
    """r²/2 holds for Va 40 cm/s and Vmax 5 m/s — the registry never uses the shortcut."""
    for radius in (0.6, 0.9, 1.2):
        assert eroa_cm2(pisa_flow_rate_ml_s(radius, 40.0), 500.0) == pytest.approx(radius**2 / 2, rel=0.01)
    # Different Va: the shortcut would be wrong by Va/40.
    assert eroa_cm2(pisa_flow_rate_ml_s(1.0, 30.0), 500.0) == pytest.approx(0.377, abs=1e-3)


def test_regurgitant_fractions() -> None:
    assert regurgitant_fraction_mr_percent(75.4, 62.8) == pytest.approx(54.6, abs=0.1)
    assert regurgitant_fraction_ar_percent(45.0, 90.0) == pytest.approx(50.0)
    # AR RF above 100 % is returned (inconsistent inputs are warned, not hidden).
    assert regurgitant_fraction_ar_percent(120.0, 60.0) == pytest.approx(200.0)


@pytest.mark.parametrize("bad", [None, 0.0, -0.5, float("nan")])
def test_missing_inputs_give_none(bad) -> None:
    assert pisa_flow_rate_ml_s(bad, 40.0) is None
    assert pisa_flow_rate_ml_s(1.0, bad) is None
    assert eroa_cm2(250.0, bad) is None
    assert regurgitant_volume_ml(0.5, bad) is None
    assert regurgitant_fraction_mr_percent(bad, 60.0) is None
    assert regurgitant_fraction_ar_percent(45.0, bad) is None


# ── registry and engine ─────────────────────────────────────────────────────
def test_pisa_calculators_are_registered_after_continuity() -> None:
    assert [spec.id for spec in CALCULATORS][:4] == ["stroke_volume", "aortic_valve_area", "pisa_mr", "pisa_ar"]
    mr = calculator_spec("pisa_mr")
    assert [o.id for o in mr.outputs] == ["pisa_flow_mr", "eroa_mr", "rvol_mr", "rf_mr"]
    assert mr.input_closure("rf_mr") == ("pisa_r_mr", "va_mr", "mr_vmax", "mr_vti", "lvot_d", "lvot_vti")
    assert input_spec("va_mr").manual_only and input_spec("va_ar").manual_only
    assert not input_spec("pisa_r_mr").manual_only


@pytest.mark.parametrize("language", ["en", "ru"])
def test_every_reference_id_resolves_to_gradations(language: str) -> None:
    for spec in CALCULATORS:
        for output in spec.outputs:
            for reference_id in output.reference_ids:
                hint = reference_hint(reference_id, language)
                assert hint is not None, (language, reference_id)
                assert hint.gradations, (language, reference_id)
                assert hint.context


def test_mr_rvol_reference_has_moderate_and_severe_ranges() -> None:
    hint = reference_hint("mr_rvol_primary", "en")
    assert [(g.name, g.range_text) for g in hint.gradations] == [
        ("Mild", "≤30.0"),
        ("Moderate", "30.0–59.0"),
        ("Severe", "≥60.0"),
    ]


def test_mr_shows_primary_and_secondary_thresholds() -> None:
    eroa = calculator_spec("pisa_mr").output("eroa_mr")
    assert eroa.reference_ids == ("mr_eroa_primary", "mr_eroa_secondary")
    texts = [reference_hint(rid, "en").text() for rid in eroa.reference_ids]
    assert texts[0].startswith("Primary Mitral Regurgitation — EROA")
    assert texts[1].startswith("Secondary Mitral Regurgitation — EROA")


def test_full_mr_and_ar_example() -> None:
    calculations = evaluate_standalone({**_LVOT, **_MR, **_AR})
    mr = calculations.result("pisa_mr")
    assert mr.output("pisa_flow_mr").formatted() == "251"
    assert mr.output("eroa_mr").formatted() == "0.50"
    assert mr.output("rvol_mr").formatted() == "75"
    assert mr.output("rf_mr").value == pytest.approx(54.6, abs=0.1)
    ar = calculations.result("pisa_ar")
    assert ar.output("eroa_ar").value == pytest.approx(2 * math.pi * 0.36 * 40 / 400, abs=1e-4)
    assert ar.output("rvol_ar").value == pytest.approx(45.2, abs=0.1)
    assert ar.output("rf_ar").value == pytest.approx(45.24 / 62.83 * 100, abs=0.1)
    assert not mr.warnings and not ar.warnings


def test_without_aliasing_velocity_nothing_is_assumed() -> None:
    calculations = evaluate_standalone({**_LVOT, "pisa_r_mr": 1.0, "mr_vmax": 5.0, "mr_vti": 150.0})
    mr = calculations.result("pisa_mr")
    assert not mr.has_values
    assert mr.output("eroa_mr").missing == ("va_mr",)


def test_rf_needs_the_lvot_stroke_volume_but_rvol_does_not() -> None:
    mr = evaluate_standalone(_MR).result("pisa_mr")
    assert mr.output("rvol_mr").computed
    assert mr.output("rf_mr").missing == ("lvot_d", "lvot_vti")


def test_ar_fraction_above_100_percent_warns() -> None:
    calculations = evaluate_standalone({**_LVOT, **_AR, "pisa_r_ar": 1.2})
    ar = calculations.result("pisa_ar")
    assert ar.output("rf_ar").value > 100
    warning = next(w for w in ar.warnings if w.code == "rf_above_100")
    assert "> 100 %" in warning_text(warning)


def test_unusual_jet_velocity_warns() -> None:
    calculations = evaluate_standalone({**_MR, "mr_vmax": 2.0})
    codes = [(w.code, w.input_id) for w in calculations.result("pisa_mr").warnings]
    assert ("out_of_range", "mr_vmax") in codes


# ── study inputs ────────────────────────────────────────────────────────────
def _trace(label: str, vti_cm: float, mid: str, sign: float = 1.0) -> DopplerTrace:
    peak = sign * vti_cm / 0.15
    return DopplerTrace(label=label, points=((0.0, 0.0), (150.0, peak), (300.0, 0.0)), measurement_id=mid)


def _pisa(label: str, mm: float) -> LinearMeasurement:
    return LinearMeasurement(label=label, pixel_length=30.0, millimeter_length=mm)


def test_caliper_mean_for_pisa_radius() -> None:
    radius, count = caliper_mean_cm(
        [_pisa("PISA MR", 9.0), _pisa("PISA MR", 10.0), _pisa("PISA MR", 11.0), _pisa("PISA AR", 6.0)],
        frozenset({"pisa mr"}),
    )
    assert radius == pytest.approx(1.0)
    assert count == 3


def test_study_inputs_for_pisa_from_calipers_and_cw_doppler() -> None:
    dto = DopplerMeasurementDTO(
        peaks=(
            DopplerPeakMarker("MR Vmax", 100.0, -500.0, "m1", "CW"),
            DopplerPeakMarker("AR Vmax", 100.0, 400.0, "a1", "CW"),
        ),
        intervals=(),
        traces=(_trace("MR VTI", 150.0, "mt", sign=-1.0), _trace("AR VTI", 200.0, "at")),
    )
    inputs = resolve_study_inputs(
        doppler=compute(dto),
        linear_measurements=[_pisa("PISA MR", 10.0), _pisa("PISA AR", 6.0)],
        manual={"va_mr": 40.0},
    )
    assert inputs["pisa_r_mr"].value == pytest.approx(1.0)
    assert inputs["pisa_r_mr"].source == SOURCE_MEASURED
    assert inputs["pisa_r_ar"].value == pytest.approx(0.6)
    # Below-baseline MR jet: magnitude in m/s.
    assert inputs["mr_vmax"].value == pytest.approx(5.0)
    assert inputs["mr_vti"].value == pytest.approx(150.0, abs=0.1)
    assert inputs["ar_vmax"].value == pytest.approx(4.0)
    assert inputs["ar_vti"].value == pytest.approx(200.0, abs=0.1)
    assert inputs["va_mr"].source == SOURCE_MANUAL
    assert inputs["va_ar"].source == SOURCE_MISSING
    assert source_text(inputs["va_ar"]) == "type it in: aliasing velocity from the scanner colour scale"
    calculations = evaluate(inputs)
    assert calculations.result("pisa_mr").output("rvol_mr").value == pytest.approx(75.4, abs=0.2)
    assert not calculations.result("pisa_ar").has_values


# ── report and menu ─────────────────────────────────────────────────────────
def test_pisa_calipers_land_in_their_valve_group() -> None:
    assert group_for_label("PISA MR") == GROUP_MITRAL_VALVE
    assert group_for_label("PISA AR") == GROUP_AORTIC_VALVE


def test_report_lists_pisa_outputs_and_assumptions() -> None:
    calculations = evaluate(resolve_study_inputs(doppler=None, manual={**_LVOT, **_MR}))
    groups = {g.key: g for g in build_report_groups(MeasurementSnapshot(calculations=calculations))}
    group = groups[GROUP_CALCULATIONS]
    rows = {v.label: (v.value, v.unit) for v in group.values}
    assert rows["MR EROA"] == ("0.50", "cm²")
    assert rows["MR RVol"] == ("75", "mL")
    assert rows["MR RF"] == ("55", "%")
    assert "AR EROA" not in rows
    assert any(note.startswith("Mitral regurgitation (PISA):") for note in group.notes)
    assert not any(note.startswith("Aortic regurgitation (PISA):") for note in group.notes)


@pytest.mark.gui
def test_menu_offers_pisa_radius_calipers() -> None:
    from echo_personal_tool.presentation.measures_menu import tool_menu_catalog

    calipers = {button.caliper_label for _key, buttons in tool_menu_catalog() for button in buttons}
    assert {"PISA MR", "PISA AR"} <= calipers
