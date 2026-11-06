"""The report-form editor (item 12 of the 2026-11-06 list).

The editor is the physician's view of a template: which header fields print,
in what order, how many columns, and whether the notes, the conclusion and the
signature are on the sheet.  It edits the small versioned dataclass — not a
layout language — and an unreadable imported file changes nothing.
"""

from __future__ import annotations

from dataclasses import replace

from echo_personal_tool.domain.services.report_template import (
    COLUMNS_TWO,
    FIELD_AGE,
    FIELD_NAME,
    FIELD_PHYSICIAN,
    HEADER_FIELDS,
    ReportTemplate,
    default_template,
)


def _editor(qtbot, template=None):
    from echo_personal_tool.presentation.report_template_editor import ReportTemplateEditor

    editor = ReportTemplateEditor(template)
    qtbot.addWidget(editor)
    editor.resize(520, 640)
    editor.show()
    return editor


def _printed_rows(editor) -> list[str]:
    from PySide6.QtCore import Qt

    return [
        str(editor._fields.item(row).data(Qt.ItemDataRole.UserRole))
        for row in range(editor._fields.count())
        if bool(editor._fields.item(row).data(Qt.ItemDataRole.UserRole + 1))
    ]


def test_the_editor_shows_every_field_printed_first(qtbot) -> None:
    editor = _editor(qtbot)
    assert _printed_rows(editor) == list(HEADER_FIELDS)
    assert editor._fields.count() == len(HEADER_FIELDS)


def test_an_unprinted_field_is_shown_but_marked(qtbot) -> None:
    editor = _editor(qtbot, ReportTemplate(header_fields=(FIELD_NAME,)))
    labels = [editor._fields.item(row).text() for row in range(editor._fields.count())]
    assert any("Петрова" in label or "Physician" in label or "(" in label for label in labels)
    assert len(labels) == len(HEADER_FIELDS)


def test_moving_a_field_changes_the_order_on_the_sheet(qtbot) -> None:
    editor = _editor(qtbot)
    editor._fields.setCurrentRow(0)
    editor._move(1)
    assert editor.template().header_fields[:2] == (HEADER_FIELDS[1], HEADER_FIELDS[0])
    assert _printed_rows(editor)[:2] == [HEADER_FIELDS[1], HEADER_FIELDS[0]]


def test_the_first_field_cannot_move_up_and_the_last_cannot_move_down(qtbot) -> None:
    editor = _editor(qtbot)
    editor._fields.setCurrentRow(0)
    assert editor._up.isEnabled() is False
    editor._fields.setCurrentRow(editor._fields.count() - 1)
    assert editor._down.isEnabled() is False


def test_hiding_a_field_removes_it_and_showing_it_returns_it(qtbot) -> None:
    editor = _editor(qtbot)
    editor._fields.setCurrentRow(0)
    editor._toggle_selected()
    assert FIELD_NAME not in editor.template().header_fields
    row = next(
        index
        for index in range(editor._fields.count())
        if editor._fields.item(index).data(__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.ItemDataRole.UserRole)
        == FIELD_NAME
    )
    editor._fields.setCurrentRow(row)
    editor._toggle_selected()
    assert FIELD_NAME in editor.template().header_fields


def test_every_edit_reports_the_change(qtbot) -> None:
    editor = _editor(qtbot)
    seen = []
    editor.changed.connect(lambda: seen.append(True))
    editor._fields.setCurrentRow(0)
    editor._move(1)
    editor._toggle_selected()
    editor._columns.setCurrentIndex(1)
    editor._notes.setChecked(False)
    editor._conclusion.setChecked(False)
    editor._signature.setChecked(False)
    assert len(seen) >= 5


def test_loading_a_template_does_not_report_a_change(qtbot) -> None:
    editor = _editor(qtbot)
    seen = []
    editor.changed.connect(lambda: seen.append(True))
    editor.set_template(ReportTemplate(header_fields=(FIELD_PHYSICIAN,), show_notes=False))
    assert seen == []
    assert editor.template().header_fields == (FIELD_PHYSICIAN,)
    assert editor._notes.isChecked() is False


def test_the_columns_and_the_switches_reach_the_template(qtbot) -> None:
    editor = _editor(qtbot)
    editor._columns.setCurrentIndex(1)
    assert editor.template().normalized_columns == COLUMNS_TWO
    editor._signature.setChecked(False)
    assert editor.template().show_signature is False


def test_dragging_a_row_updates_the_order(qtbot) -> None:
    from PySide6.QtCore import Qt

    editor = _editor(qtbot)
    first = editor._fields.takeItem(0)
    editor._fields.insertItem(1, first)  # take/insert emits rowsRemoved — read the order back
    editor.commit_drag()
    assert editor.template().header_fields[:2] == (HEADER_FIELDS[1], HEADER_FIELDS[0])
    assert editor._fields.item(0).data(Qt.ItemDataRole.UserRole) in HEADER_FIELDS


def test_the_form_round_trips_through_a_file(qtbot, tmp_path, monkeypatch) -> None:
    editor = _editor(qtbot)
    template = ReportTemplate(header_fields=(FIELD_AGE, FIELD_NAME), columns=COLUMNS_TWO, name="Районная")
    editor.set_template(template)
    target = tmp_path / "form.json"
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), "JSON (*.json)"))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    editor._export_to_file()
    assert target.exists()

    other = _editor(qtbot)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(target), "JSON (*.json)"))
    other._import_from_file()
    assert other.template() == template


def test_an_unreadable_file_changes_nothing(qtbot, tmp_path, monkeypatch) -> None:
    editor = _editor(qtbot)
    before = editor.template()
    broken = tmp_path / "broken.json"
    broken.write_text("{{{ not json", encoding="utf-8")
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    warned = []
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(broken), "JSON (*.json)"))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a))
    editor._import_from_file()
    assert editor.template() == before
    assert warned


def test_a_write_failure_is_reported_not_raised(qtbot, monkeypatch) -> None:
    editor = _editor(qtbot)
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    warned = []
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: ("/proc/definitely/not/writable.json", ""))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a))
    editor._export_to_file()
    assert warned


def test_the_cancel_is_silent(qtbot, monkeypatch) -> None:
    editor = _editor(qtbot)
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: ("", ""))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: ("", ""))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    editor._export_to_file()
    editor._import_from_file()
    assert editor.template() == default_template()


def test_a_switched_off_switch_survives_the_round_trip(qtbot) -> None:
    editor = _editor(qtbot)
    editor.set_template(replace(default_template(), show_conclusion=False, show_notes=False))
    assert editor._conclusion.isChecked() is False
    assert editor.template().show_conclusion is False
