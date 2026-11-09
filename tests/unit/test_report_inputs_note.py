"""The «Входные данные» footnote and the switch that removes it (item 8).

The owner asked whether the «Входные данные: …» line under the calculations
group should exist at all.  The decision is a switch, not a deletion: the
provenance of a value is useful for review and teaching, while in routine work
it repeats what the field headers already say.  The switch is off by default —
routine reports are quieter.

Since 2026-11-09 the switch silences the *whole* machine-generated footnote
block (the inputs line, the per-calculator assumptions, the plausibility
warnings and the RUO statement, plus the provenance and strain-method notes of
the other groups): the owner found the auto-text redundant under the tables,
"fully remove" being the requirement.  The value cells are unaffected.
"""

from __future__ import annotations

import pytest

from echo_personal_tool.application.calculator_inputs import resolve_standalone_inputs
from echo_personal_tool.domain.calculators import evaluate
from echo_personal_tool.domain.calculators.text import report_notes
from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
from echo_personal_tool.domain.services.report_builder import (
    GROUP_CALCULATIONS,
    PatientInfo,
    build_report_document,
    build_report_groups,
)
from echo_personal_tool.infrastructure.i18n import set_language, tr

_EXAMPLE = {"lvot_d": 2.0, "lvot_vti": 20.0, "av_vti": 100.0, "hr": 70.0, "bsa": 1.9}
_CALC = evaluate(resolve_standalone_inputs(_EXAMPLE))


@pytest.fixture(autouse=True)
def _english() -> None:
    set_language("en")
    yield
    set_language("en")


def _inputs_line() -> str:
    return tr("calc.report.inputs", inputs="")


def _notes(include_inputs: bool) -> tuple[str, ...]:
    return report_notes(_CALC, include_inputs=include_inputs)


def _group_notes(document) -> tuple[str, ...]:
    return next(group.notes for group in document.groups if group.key == GROUP_CALCULATIONS)


def test_the_inputs_line_is_kept_for_explicit_callers() -> None:
    """The default stays on so the calculators panel and older callers keep it."""
    notes = _notes(True)
    assert notes[0].startswith(_inputs_line().split(":")[0])
    assert "LVOTd 2.00 cm" in notes[0]


def test_the_inputs_line_is_absent_when_switched_off() -> None:
    prefix = _inputs_line().split(":")[0]
    assert not any(note.startswith(prefix) for note in _notes(False))


def test_the_switch_silences_the_whole_auto_text_block() -> None:
    """Since 2026-11-09 the toggle removes the whole footnote block."""
    on, off = _notes(True), _notes(False)
    assert tr("calc.ruo") in on
    assert off == ()


def test_the_group_builder_threads_the_flag() -> None:
    snapshot = MeasurementSnapshot(calculations=_CALC)
    on = {group.key: group for group in build_report_groups(snapshot, sex="M", include_inputs=True)}
    off = {group.key: group for group in build_report_groups(snapshot, sex="M", include_inputs=False)}
    assert on[GROUP_CALCULATIONS].notes
    assert off[GROUP_CALCULATIONS].notes == ()


def test_the_document_builder_threads_the_flag() -> None:
    snapshot = MeasurementSnapshot(calculations=_CALC)
    on = build_report_document(snapshot, PatientInfo(sex="M"), sex="M", include_inputs=True)
    off = build_report_document(snapshot, PatientInfo(sex="M"), sex="M", include_inputs=False)
    assert _group_notes(on)
    assert _group_notes(off) == ()
    assert any("LVOTd" in note for note in _group_notes(on))


def test_the_csv_and_json_are_not_affected(tmp_path) -> None:
    """JSON keeps the notes of the group; CSV never printed them, and still does not."""
    from echo_personal_tool.application.report_export import render_report_csv, render_report_json

    snapshot = MeasurementSnapshot(calculations=_CALC)
    on = build_report_document(snapshot, PatientInfo(sex="M"), sex="M", include_inputs=True)
    off = build_report_document(snapshot, PatientInfo(sex="M"), sex="M", include_inputs=False)
    assert "LVOTd" in render_report_json(on, tmp_path / "on.json").read_text(encoding="utf-8")
    assert "LVOTd" not in render_report_json(off, tmp_path / "off.json").read_text(encoding="utf-8")
    csv_on = render_report_csv(on, tmp_path / "on.csv").read_text(encoding="utf-8")
    csv_off = render_report_csv(off, tmp_path / "off.csv").read_text(encoding="utf-8")
    assert csv_on == csv_off


def test_the_pdf_drops_the_line_when_the_switch_is_off(tmp_path) -> None:
    import fitz

    from echo_personal_tool.application.report_export import export_report_document_pdf

    snapshot = MeasurementSnapshot(calculations=_CALC)

    def text(include_inputs: bool) -> str:
        document = build_report_document(snapshot, PatientInfo(sex="M"), sex="M", include_inputs=include_inputs)
        path = export_report_document_pdf(document, tmp_path / f"report-{include_inputs}.pdf")
        with fitz.open(path) as pdf:
            return "\n".join(page.get_text() for page in pdf)

    marker = "Inputs:"
    assert marker in text(True)
    assert marker not in text(False)
    # The whole auto-text block is gone, not only the inputs line.
    assert "research use only" not in text(False).casefold()


def test_the_preference_is_off_by_default_and_round_trips() -> None:
    from dataclasses import replace

    from echo_personal_tool.infrastructure.user_preferences import (
        UserPreferences,
        load_user_preferences,
        save_user_preferences,
    )

    assert UserPreferences().report_show_inputs is False
    save_user_preferences(replace(UserPreferences(), report_show_inputs=True))
    assert load_user_preferences().report_show_inputs is True
    save_user_preferences(UserPreferences(report_show_inputs=False))
    assert load_user_preferences().report_show_inputs is False
