"""Calculator registry and engine (Э11): declarative consistency and evaluation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from echo_personal_tool.application.calculator_inputs import evaluate_standalone
from echo_personal_tool.domain.calculators import (
    CALCULATORS,
    INPUTS,
    InputValue,
    all_input_ids,
    calculator_spec,
    evaluate,
    input_spec,
    is_out_of_range,
)
from echo_personal_tool.domain.calculators.models import SOURCE_MANUAL, SOURCE_MEASURED
from echo_personal_tool.domain.calculators.reference_hints import format_range, reference_hint

_LOCALES = Path(__file__).resolve().parents[2] / "src" / "echo_personal_tool" / "infrastructure" / "locales"

_EXAMPLE = {
    "lvot_d": 2.0,
    "lvot_vti": 20.0,
    "av_vti": 100.0,
    "lvot_vmax": 100.0,
    "av_vmax": 4.5,
    "hr": 70.0,
    "height": 175.0,
    "weight": 75.0,
}


def _locale(lang: str) -> dict[str, str]:
    return json.loads((_LOCALES / f"{lang}.json").read_text(encoding="utf-8"))


def test_every_dependency_is_an_input_or_an_earlier_output() -> None:
    input_ids = {item.id for item in INPUTS}
    for calculator in CALCULATORS:
        earlier: set[str] = set()
        for output in calculator.outputs:
            for dependency in output.requires:
                assert dependency in input_ids or dependency in earlier, (calculator.id, output.id, dependency)
            earlier.add(output.id)


def test_every_registry_text_key_exists_in_both_locales() -> None:
    keys = {item.name_key for item in INPUTS}
    for calculator in CALCULATORS:
        keys.update({calculator.title_key, calculator.assumptions_key})
        keys.update(output.name_key for output in calculator.outputs)
    for lang in ("ru", "en"):
        missing = keys - set(_locale(lang))
        assert not missing, (lang, sorted(missing))


def test_every_calculator_cites_literature() -> None:
    for calculator in CALCULATORS:
        assert calculator.references
        assert all("J Am Soc Echocardiogr" in ref for ref in calculator.references)


def test_input_closure_follows_output_chain() -> None:
    spec = calculator_spec("stroke_volume")
    assert spec is not None
    assert spec.input_closure("ci") == ("lvot_d", "lvot_vti", "hr", "bsa")
    assert set(spec.input_ids) == {"lvot_d", "lvot_vti", "bsa", "hr"}


def test_all_input_ids_includes_bsa_sources_in_display_order() -> None:
    ids = all_input_ids()
    assert ids[0] == "lvot_d"
    assert {"height", "weight", "bsa"} <= set(ids)
    assert ids.index("height") < ids.index("bsa")


def test_full_example_evaluates_every_output() -> None:
    calculations = evaluate_standalone(_EXAMPLE)
    assert calculations.standalone
    sv = calculations.result("stroke_volume")
    ava = calculations.result("aortic_valve_area")
    assert sv is not None and ava is not None
    assert sv.output("sv").value == pytest.approx(62.83, abs=0.01)
    assert sv.output("co").value == pytest.approx(4.398, abs=1e-3)
    bsa = calculations.input("bsa").value
    assert bsa == pytest.approx(0.007184 * 175**0.725 * 75**0.425)
    assert sv.output("ci").value == pytest.approx(4.398 / bsa, abs=1e-3)
    assert ava.output("ava_vti").value == pytest.approx(0.628, abs=1e-3)
    # AV Vmax is entered in m/s (CW), LVOT Vmax in cm/s (PW): units are reconciled.
    assert ava.output("ava_vmax").value == pytest.approx(0.698, abs=1e-3)
    assert ava.output("dvi_vmax").value == pytest.approx(0.222, abs=1e-3)
    assert ava.output("avai").value == pytest.approx(0.628 / bsa, abs=1e-3)
    assert not sv.warnings and not ava.warnings


def test_missing_inputs_are_listed_and_outputs_stay_empty() -> None:
    calculations = evaluate_standalone({"lvot_d": 2.0, "lvot_vti": 20.0})
    sv = calculations.result("stroke_volume")
    assert sv.output("sv").computed
    co = sv.output("co")
    assert co.value is None
    assert co.missing == ("hr",)
    assert sv.output("ci").missing == ("hr", "bsa")
    ava = calculations.result("aortic_valve_area").output("ava_vti")
    assert ava.missing == ("av_vti",)
    assert ava.formatted() == "—"


def test_nothing_entered_computes_nothing() -> None:
    calculations = evaluate_standalone({})
    assert not calculations.has_values
    assert calculations.used_inputs() == ()


def test_out_of_range_input_warns_but_still_computes() -> None:
    calculations = evaluate_standalone({**_EXAMPLE, "lvot_d": 3.4})
    sv = calculations.result("stroke_volume")
    assert sv.output("sv").computed
    assert any(w.code == "out_of_range" and w.input_id == "lvot_d" for w in sv.warnings)
    assert is_out_of_range("lvot_d", 3.4)
    assert not is_out_of_range("lvot_d", 2.0)


def test_swapped_labels_warn_with_dvi_above_one() -> None:
    calculations = evaluate_standalone({**_EXAMPLE, "lvot_vti": 30.0, "av_vti": 20.0})
    codes = [w.code for w in calculations.result("aortic_valve_area").warnings]
    assert "dvi_above_one" in codes


def test_diverging_ava_methods_warn() -> None:
    calculations = evaluate_standalone({**_EXAMPLE, "av_vmax": 2.0})
    codes = [w.code for w in calculations.result("aortic_valve_area").warnings]
    assert "ava_methods_diverge" in codes


def test_used_inputs_only_lists_contributing_values() -> None:
    calculations = evaluate_standalone({"lvot_d": 2.0, "lvot_vti": 20.0, "hr": 70.0})
    used = {item.id for item in calculations.used_inputs()}
    assert used == {"lvot_d", "lvot_vti", "hr"}


def test_evaluate_marks_study_snapshots_as_not_standalone() -> None:
    inputs = {"lvot_d": InputValue("lvot_d", 2.0, source=SOURCE_MEASURED)}
    calculations = evaluate(inputs)
    assert not calculations.standalone
    assert calculations.input("lvot_d").source == SOURCE_MEASURED
    assert calculations.input("hr").value is None


def test_snapshots_compare_by_value() -> None:
    assert evaluate_standalone(_EXAMPLE) == evaluate_standalone(dict(_EXAMPLE))
    assert evaluate_standalone(_EXAMPLE) != evaluate_standalone({**_EXAMPLE, "hr": 71.0})


def test_overridden_flag_needs_an_auto_value() -> None:
    assert InputValue("hr", 70.0, source=SOURCE_MANUAL, auto_value=65.0).overridden
    assert not InputValue("hr", 70.0, source=SOURCE_MANUAL).overridden


def test_input_specs_have_sane_editor_bounds() -> None:
    for item in INPUTS:
        low, high = item.plausible
        editor_low, editor_high = item.editor_range
        assert editor_low < low < high < editor_high, item.id
        assert input_spec(item.id) is item


def test_reference_gradations_come_from_the_structured_reference() -> None:
    hint = reference_hint("as_ava", "en")
    assert hint is not None
    assert [g.name for g in hint.gradations] == ["Mild", "Moderate", "Severe"]
    assert hint.gradations[-1].range_text == "≤1.0"
    assert "cm²" in hint.text()
    ru = reference_hint("as_ava_indexed", "ru")
    assert ru is not None and ru.gradations[0].name.startswith("Л")
    assert reference_hint("does_not_exist", "en") is None
    assert reference_hint(None) is None


def test_format_range() -> None:
    assert format_range(1.0, 1.5) == "1.0–1.5"
    assert format_range(None, 0.25) == "≤0.25"
    assert format_range(0.85, None) == "≥0.85"
    assert format_range(None, None) == ""
