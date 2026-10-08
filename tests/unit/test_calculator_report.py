"""Calculator results in the study report: group «Расчёты», footnotes, PDF (Э11)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from echo_personal_tool.application.calculator_inputs import evaluate_standalone, resolve_standalone_inputs
from echo_personal_tool.domain.calculators import evaluate
from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
from echo_personal_tool.domain.services.measurement_report_formatter import format_measurement_report
from echo_personal_tool.domain.services.report_builder import (
    GROUP_CALCULATIONS,
    GROUP_ORDER,
    build_report_document,
    build_report_groups,
)
from echo_personal_tool.infrastructure.i18n import set_language, tr

_EXAMPLE = {"lvot_d": 2.0, "lvot_vti": 20.0, "av_vti": 100.0, "hr": 70.0, "bsa": 1.9}


def _study_calculations(values=None):
    """A study (non-standalone) snapshot built from the same manual values."""
    return evaluate(resolve_standalone_inputs(_EXAMPLE if values is None else values))


@pytest.fixture(autouse=True)
def _english():
    set_language("en")
    yield
    set_language("en")


def _calc_group(snapshot):
    groups = {group.key: group for group in build_report_groups(snapshot)}
    return groups.get(GROUP_CALCULATIONS)


def test_calculations_group_sits_before_other() -> None:
    assert GROUP_ORDER.index(GROUP_CALCULATIONS) == GROUP_ORDER.index("other") - 1


def test_computed_outputs_enter_the_group_once() -> None:
    group = _calc_group(MeasurementSnapshot(calculations=_study_calculations()))
    assert group is not None
    assert group.title == tr("report.group.calculations")
    rows = {value.label: (value.value, value.unit) for value in group.values}
    assert rows["SV"] == ("62.8", "mL")
    assert rows["CO"] == ("4.40", "L/min")
    assert rows["AVA (VTI)"] == ("0.63", "cm²")
    assert rows["DVI (VTI)"] == ("0.20", "")
    # LVOT area is shared by both calculators but printed once.
    assert [value.label for value in group.values].count("LVOT area") == 1
    # Outputs whose inputs are missing are simply absent (no typical values).
    assert "AVA (Vmax)" not in rows
    # No automatic grading: the norm column stays empty.
    assert all(value.norm == "" and not value.pathological for value in group.values)


def test_group_notes_carry_inputs_assumptions_and_ruo() -> None:
    group = _calc_group(MeasurementSnapshot(calculations=_study_calculations()))
    notes = group.notes
    assert notes[0].startswith("Inputs: ")
    assert "LVOTd 2.00 cm" in notes[0]
    assert any("circular" in note.lower() for note in notes)
    assert notes[-1] == tr("calc.ruo")


def test_warnings_are_printed_as_notes() -> None:
    calculations = _study_calculations({**_EXAMPLE, "lvot_vti": 30.0, "av_vti": 20.0})
    notes = _calc_group(MeasurementSnapshot(calculations=calculations)).notes
    assert any("DVI" in note and "> 1" in note for note in notes)


def test_standalone_results_never_reach_the_report() -> None:
    snapshot = MeasurementSnapshot(calculations=evaluate_standalone(_EXAMPLE))
    assert _calc_group(snapshot) is None
    assert tr("report.group.calculations") not in format_measurement_report(snapshot)


def test_empty_calculations_add_no_group() -> None:
    assert _calc_group(MeasurementSnapshot(calculations=_study_calculations({}))) is None
    assert _calc_group(MeasurementSnapshot()) is None


def test_text_report_has_a_calculations_section() -> None:
    text = format_measurement_report(MeasurementSnapshot(calculations=_study_calculations()))
    assert tr("report.group.calculations") in text
    assert "SV: 62.8 mL" in text
    assert tr("calc.ruo") in text


def test_russian_report_labels() -> None:
    set_language("ru")
    group = _calc_group(MeasurementSnapshot(calculations=_study_calculations()))
    assert group.title == "Расчёты"
    assert "вручную" in group.notes[0]


def test_pdf_export_includes_notes(tmp_path: Path) -> None:
    from echo_personal_tool.infrastructure.measurement_report_pdf import export_report_document_pdf

    document = build_report_document(MeasurementSnapshot(calculations=_study_calculations()))
    output = export_report_document_pdf(document, tmp_path / "calc.pdf")
    assert output.read_bytes()[:5] == b"%PDF-"


@pytest.mark.gui
def test_report_dialog_shows_notes_under_the_group() -> None:
    from PySide6.QtWidgets import QApplication

    from echo_personal_tool.presentation.report_dialog import ReportDialog

    _ = QApplication.instance() or QApplication([])
    snapshot = replace(MeasurementSnapshot(), calculations=_study_calculations())
    dialog = ReportDialog(snapshot)
    tree = dialog._tree
    titles = {tree.topLevelItem(i).text(0): tree.topLevelItem(i) for i in range(tree.topLevelItemCount())}
    top = titles[tr("report.group.calculations")]
    children = [top.child(j).text(0) for j in range(top.childCount())]
    assert "SV" in children
    assert children[-1] == tr("calc.ruo")
