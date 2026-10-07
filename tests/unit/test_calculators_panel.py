"""Calculators panel (Э11): study mode with overrides, standalone mode (D-25)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.gui

from PySide6.QtWidgets import QApplication, QGroupBox, QLabel, QLineEdit, QToolButton, QWidget

from echo_personal_tool.application.calculator_inputs import resolve_standalone_inputs, resolve_study_inputs
from echo_personal_tool.domain.calculators import evaluate
from echo_personal_tool.domain.calculators.models import SOURCE_MEASURED
from echo_personal_tool.infrastructure.i18n import set_language, tr
from echo_personal_tool.presentation.calculators_panel import (
    MODE_STANDALONE,
    MODE_STUDY,
    CalculatorsPanel,
    parse_number,
)


@pytest.fixture(autouse=True)
def _app():
    app = QApplication.instance() or QApplication([])
    set_language("en")
    yield app
    set_language("en")


def _edit(panel: CalculatorsPanel, input_id: str) -> QLineEdit:
    widget = panel.findChild(QLineEdit, f"calcInput_{input_id}")
    assert widget is not None
    return widget


def _output(panel: CalculatorsPanel, calc: str, output: str) -> str:
    label = panel.findChild(QLabel, f"calcOutput_{calc}_{output}")
    assert label is not None
    return label.text()


def _type(panel: CalculatorsPanel, input_id: str, text: str) -> None:
    edit = _edit(panel, input_id)
    edit.setText(text)
    edit.editingFinished.emit()


def _study(manual=None):
    inputs = resolve_study_inputs(doppler=None, manual={"lvot_vti": 20.0, "av_vti": 100.0, **(manual or {})})
    inputs["lvot_d"] = type(inputs["lvot_d"])("lvot_d", 2.0, source=SOURCE_MEASURED)
    return evaluate(inputs)


def test_parse_number_accepts_comma_and_blank() -> None:
    assert parse_number("2,1") == 2.1
    assert parse_number(" 2.10 ") == 2.1
    assert parse_number("") is None
    with pytest.raises(ValueError):
        parse_number("abc")


def test_panel_has_one_card_per_calculator_and_ruo() -> None:
    panel = CalculatorsPanel()
    assert panel.objectName() == "calculatorsPanel"
    assert panel.findChild(QGroupBox, "calcCard_stroke_volume") is not None
    assert panel.findChild(QGroupBox, "calcCard_aortic_valve_area") is not None
    assert panel.findChild(QLabel, "calcRuo").text() == tr("calc.ruo")
    assert panel.mode == MODE_STUDY


def test_without_study_inputs_are_disabled() -> None:
    panel = CalculatorsPanel()
    panel.set_study_calculations(None, has_study=False)
    assert not _edit(panel, "lvot_d").isEnabled()
    assert panel.findChild(QLabel, "calcModeHint").text() == tr("calc.hint.no_study")
    assert _output(panel, "stroke_volume", "sv") == "—"


def test_study_values_show_with_provenance_and_missing_list() -> None:
    panel = CalculatorsPanel()
    panel.set_study_calculations(_study(), has_study=True)
    assert _edit(panel, "lvot_d").isEnabled()
    assert _edit(panel, "lvot_d").text() == "2.00"
    assert panel.findChild(QLabel, "calcSource_lvot_d").text() == tr("calc.source.measured")
    assert _output(panel, "stroke_volume", "sv") == "62.8"
    assert _output(panel, "aortic_valve_area", "ava_vti") == "0.63"
    assert _output(panel, "stroke_volume", "co") == "—"
    missing = panel.findChild(QLabel, "calcMissing_stroke_volume").text()
    assert "HR" in missing and "BSA" in missing


def test_reference_gradation_hint_is_shown() -> None:
    panel = CalculatorsPanel()
    hints = panel.findChild(QLabel, "calcHints_aortic_valve_area").text()
    assert "Severe" in hints and "≤1.0" in hints


def test_study_edit_emits_override_and_reset_clears_it() -> None:
    panel = CalculatorsPanel()
    panel.set_study_calculations(_study(), has_study=True)
    emitted: list[tuple[str, object]] = []
    panel.study_input_changed.connect(lambda key, value: emitted.append((key, value)))
    _type(panel, "hr", "72")
    assert emitted == [("hr", 72.0)]
    # The controller answers with a recomputed snapshot that marks the override.
    panel.set_study_calculations(_study({"hr": 72.0}), has_study=True)
    assert _output(panel, "stroke_volume", "co") == "4.52"
    panel.findChild(QToolButton, "calcReset_hr").click()
    assert emitted[-1] == ("hr", None)


def test_overridden_measurement_shows_the_measured_value() -> None:
    inputs = resolve_study_inputs(doppler=None, manual={"lvot_d": 2.2})
    inputs["lvot_d"] = type(inputs["lvot_d"])(
        "lvot_d", 2.2, source="manual", auto_value=2.0, auto_source=SOURCE_MEASURED
    )
    panel = CalculatorsPanel()
    panel.set_study_calculations(evaluate(inputs), has_study=True)
    source = panel.findChild(QLabel, "calcSource_lvot_d").text()
    assert "2.00 cm" in source
    assert not panel.findChild(QToolButton, "calcReset_lvot_d").isHidden()


def test_invalid_text_is_reverted_with_tooltip() -> None:
    panel = CalculatorsPanel()
    panel.set_study_calculations(_study(), has_study=True)
    emitted: list[tuple[str, object]] = []
    panel.study_input_changed.connect(lambda key, value: emitted.append((key, value)))
    _type(panel, "lvot_d", "abc")
    assert _edit(panel, "lvot_d").text() == "2.00"
    assert _edit(panel, "lvot_d").toolTip() == tr("calc.invalid_number")
    _type(panel, "lvot_d", "60")
    assert _edit(panel, "lvot_d").text() == "2.00"
    assert "6" in _edit(panel, "lvot_d").toolTip()
    assert emitted == []


def test_standalone_mode_computes_locally_and_never_emits() -> None:
    panel = CalculatorsPanel()
    panel.set_study_calculations(_study(), has_study=True)
    emitted: list[tuple[str, object]] = []
    panel.study_input_changed.connect(lambda key, value: emitted.append((key, value)))
    panel.set_mode(MODE_STANDALONE)
    assert panel.mode == MODE_STANDALONE
    assert _edit(panel, "lvot_d").text() == ""
    assert not panel.findChild(QWidget, "calcClearButton").isHidden()
    for key, text in (("lvot_d", "2,0"), ("lvot_vti", "20"), ("hr", "70")):
        _type(panel, key, text)
    assert emitted == []
    assert _output(panel, "stroke_volume", "sv") == "62.8"
    assert _output(panel, "stroke_volume", "co") == "4.40"
    assert panel.standalone_values() == {"lvot_d": 2.0, "lvot_vti": 20.0, "hr": 70.0}
    assert panel.current_calculations().standalone

    # Back to the study: its values return untouched.
    panel.set_mode(MODE_STUDY)
    assert _edit(panel, "lvot_d").text() == "2.00"
    assert _output(panel, "stroke_volume", "co") == "—"

    panel.set_mode(MODE_STANDALONE)
    panel.clear_standalone()
    assert _output(panel, "stroke_volume", "sv") == "—"


def test_standalone_works_without_a_study() -> None:
    panel = CalculatorsPanel()
    panel.set_study_calculations(None, has_study=False)
    panel.set_mode(MODE_STANDALONE)
    assert _edit(panel, "lvot_d").isEnabled()
    _type(panel, "height", "175")
    _type(panel, "weight", "75")
    assert _edit(panel, "bsa").text() == "1.90"


def test_out_of_range_value_gets_a_warning() -> None:
    panel = CalculatorsPanel()
    panel.set_mode(MODE_STANDALONE)
    for key, text in (("lvot_d", "3.4"), ("lvot_vti", "20")):
        _type(panel, key, text)
    assert "border" in _edit(panel, "lvot_d").styleSheet()
    assert "LVOTd" in panel.findChild(QLabel, "calcWarnings_stroke_volume").text()


def test_copy_text_has_formulas_inputs_and_ruo() -> None:
    panel = CalculatorsPanel()
    panel.set_study_calculations(evaluate(resolve_standalone_inputs({"lvot_d": 2.0, "lvot_vti": 20.0})), has_study=True)
    text = panel.results_text()
    assert "SV: 62.8 mL  [" in text
    assert "LVOTd 2.00 cm" in text
    assert text.endswith(tr("calc.ruo"))
    panel.copy_results()
    assert QApplication.clipboard().text() == text


def test_empty_panel_copies_nothing() -> None:
    panel = CalculatorsPanel()
    assert panel.results_text() == ""
    assert not panel.findChild(QWidget, "calcCopyButton").isEnabled()


def test_language_switch_retranslates() -> None:
    panel = CalculatorsPanel()
    set_language("ru")
    panel.reload_text()
    card = panel.findChild(QGroupBox, "calcCard_stroke_volume")
    assert card.title() == tr("calc.title.stroke_volume")
    assert panel.findChild(QLabel, "calcRuo").text().startswith("Расчёты")


def test_inputs_are_grouped_by_section() -> None:
    panel = CalculatorsPanel()
    for section, key in (
        ("continuity", "calc.section.continuity"),
        ("mr", "calc.section.mr"),
        ("ar", "calc.section.ar"),
        ("patient", "calc.section.patient"),
    ):
        heading = panel.findChild(QLabel, f"calcSection_{section}")
        assert heading is not None and heading.text() == tr(key)


def test_pisa_card_in_standalone_mode() -> None:
    panel = CalculatorsPanel()
    panel.set_mode(MODE_STANDALONE)
    assert panel.findChild(QGroupBox, "calcCard_pisa_mr") is not None
    for key, text in (("pisa_r_mr", "1,0"), ("va_mr", "40"), ("mr_vmax", "5"), ("mr_vti", "150")):
        _type(panel, key, text)
    assert _output(panel, "pisa_mr", "eroa_mr") == "0.50"
    assert _output(panel, "pisa_mr", "rvol_mr") == "75"
    assert _output(panel, "pisa_mr", "rf_mr") == "—"
    assert "LVOTd" in panel.findChild(QLabel, "calcMissing_pisa_mr").text()
    hints = panel.findChild(QLabel, "calcHints_pisa_mr").text()
    assert "Primary Mitral Regurgitation" in hints and "Secondary Mitral Regurgitation" in hints


def test_aliasing_velocity_asks_for_manual_entry_in_study_mode() -> None:
    panel = CalculatorsPanel()
    panel.set_study_calculations(_study(), has_study=True)
    assert panel.findChild(QLabel, "calcSource_va_mr").text() == tr("calc.source.manual_only.va_mr")
