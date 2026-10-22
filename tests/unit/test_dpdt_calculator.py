"""Э11: LV dP/dt from the MR jet and RV dP/dt from the TR jet.

Hand-checkable worked example:

* MR jet 1 → 3 m/s in 20 ms → 32 mmHg / 0.020 s = 1600 mmHg/s (LV).
* TR jet 1 → 2 m/s in 20 ms → 12 mmHg / 0.020 s = 600 mmHg/s (RV).
"""

from __future__ import annotations

import pytest

from echo_personal_tool.application.calculator_inputs import evaluate_standalone, resolve_study_inputs
from echo_personal_tool.domain.calculations.contractility import (
    LV_DPDT_DELTA_P_MMHG,
    RV_DPDT_DELTA_P_MMHG,
    dpdt_mmhg_s,
    lv_dpdt_mmhg_s,
    rv_dpdt_mmhg_s,
)
from echo_personal_tool.domain.calculations.doppler_metrics import compute
from echo_personal_tool.domain.calculators import calculator_spec, evaluate, input_spec
from echo_personal_tool.domain.calculators.models import SOURCE_MEASURED, SOURCE_MISSING
from echo_personal_tool.domain.calculators.reference_hints import reference_hint
from echo_personal_tool.domain.doppler_catalog import INTERVAL_LABELS, canonical_interval_label
from echo_personal_tool.domain.models.doppler import DopplerIntervalMarker, DopplerMeasurementDTO
from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
from echo_personal_tool.domain.services.report_builder import GROUP_CALCULATIONS, build_report_groups
from echo_personal_tool.infrastructure.i18n import set_language


@pytest.fixture(autouse=True)
def _english():
    set_language("en")
    yield
    set_language("en")


def test_pressure_rises_follow_simplified_bernoulli() -> None:
    assert LV_DPDT_DELTA_P_MMHG == pytest.approx(32.0)
    assert RV_DPDT_DELTA_P_MMHG == pytest.approx(12.0)


def test_formulas() -> None:
    assert lv_dpdt_mmhg_s(20.0) == pytest.approx(1600.0)
    assert rv_dpdt_mmhg_s(20.0) == pytest.approx(600.0)
    assert dpdt_mmhg_s(32.0, 40.0) == pytest.approx(800.0)
    for bad in (None, 0.0, -5.0, float("nan")):
        assert lv_dpdt_mmhg_s(bad) is None
        assert rv_dpdt_mmhg_s(bad) is None


def test_calculator_is_registered_with_formulas_and_references() -> None:
    spec = calculator_spec("dpdt")
    assert spec is not None
    outputs = {output.id: output for output in spec.outputs}
    assert outputs["lv_dpdt"].formula == "32 mmHg / Δt(MR 1→3 m/s)"
    assert outputs["rv_dpdt"].formula == "12 mmHg / Δt(TR 1→2 m/s)"
    assert outputs["lv_dpdt"].reference_ids == ("lv_dpdt",)
    assert outputs["rv_dpdt"].reference_ids == ("rv_dpdt",)
    for input_id in ("mr_dpdt_dt", "tr_dpdt_dt"):
        spec_in = input_spec(input_id)
        assert spec_in is not None and spec_in.unit == "ms" and not spec_in.manual_only


def test_worked_example_and_independent_sides() -> None:
    result = evaluate_standalone({"mr_dpdt_dt": 20.0, "tr_dpdt_dt": 20.0}).result("dpdt")
    formatted = {output.id: output.formatted() for output in result.outputs}
    assert formatted == {"lv_dpdt": "1600", "rv_dpdt": "600"}
    only_lv = evaluate_standalone({"mr_dpdt_dt": 40.0}).result("dpdt")
    assert only_lv.output("lv_dpdt").value == pytest.approx(800.0)
    assert not only_lv.output("rv_dpdt").computed


def test_interval_labels_and_aliases() -> None:
    assert {"MR dP/dt", "TR dP/dt"} <= set(INTERVAL_LABELS)
    assert canonical_interval_label("mr dp/dt") == "MR dP/dt"
    assert canonical_interval_label("LV dP/dt") == "MR dP/dt"
    assert canonical_interval_label("RV dP/dt") == "TR dP/dt"


def test_study_intervals_feed_the_calculator() -> None:
    dto = DopplerMeasurementDTO(
        peaks=(),
        traces=(),
        intervals=(
            DopplerIntervalMarker("MR dP/dt", 100.0, 125.0, "mr"),
            DopplerIntervalMarker("TR dP/dt", 300.0, 330.0, "tr"),
        ),
    )
    doppler = compute(dto)
    assert doppler.mr_dpdt_ms == pytest.approx(25.0)
    assert doppler.tr_dpdt_ms == pytest.approx(30.0)
    inputs = resolve_study_inputs(doppler=doppler)
    assert inputs["mr_dpdt_dt"].source == SOURCE_MEASURED
    assert inputs["tr_dpdt_dt"].source == SOURCE_MEASURED
    result = evaluate(inputs).result("dpdt")
    assert result.output("lv_dpdt").value == pytest.approx(1280.0)
    assert result.output("rv_dpdt").value == pytest.approx(400.0)


def test_missing_intervals_leave_outputs_empty() -> None:
    inputs = resolve_study_inputs(doppler=None)
    assert inputs["mr_dpdt_dt"].source == SOURCE_MISSING
    result = evaluate(inputs).result("dpdt")
    assert not result.output("lv_dpdt").computed
    assert not result.output("rv_dpdt").computed


@pytest.mark.parametrize("language", ["en", "ru"])
def test_reference_parameters(language: str) -> None:
    lv = reference_hint("lv_dpdt", language)
    rv = reference_hint("rv_dpdt", language)
    assert lv is not None and lv.gradations[0].range_text == "≥1200.0"
    assert rv is not None and rv.gradations[0].range_text == "≥400.0"
    assert "32" in lv.note
    assert "12" in rv.note


def test_report_lists_dpdt() -> None:
    calculations = evaluate(resolve_study_inputs(doppler=None, manual={"mr_dpdt_dt": 20.0, "tr_dpdt_dt": 20.0}))
    groups = {g.key: g for g in build_report_groups(MeasurementSnapshot(calculations=calculations))}
    rows = {v.label: (v.value, v.unit) for v in groups[GROUP_CALCULATIONS].values}
    assert rows["LV dP/dt"] == ("1600", "mmHg/s")
    assert rows["RV dP/dt"] == ("600", "mmHg/s")


@pytest.mark.gui
def test_menu_offers_dpdt_intervals() -> None:
    from echo_personal_tool.presentation.measures_menu import tool_menu_catalog

    intervals = {button.doppler_interval for _key, buttons in tool_menu_catalog() for button in buttons}
    assert {"MR dP/dt", "TR dP/dt"} <= intervals
