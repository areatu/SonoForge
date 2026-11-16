"""GUI tests for the report-mode sections column (UI-4 PR-2)."""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.protocols import ProjectionValue, StudyProjection

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def _setup_qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def _projection(*keys: str) -> StudyProjection:
    return StudyProjection(values={key: ProjectionValue(value=1.0) for key in keys})


def _panel():
    from echo_personal_tool.presentation.report_mode.sections import ReportSectionsPanel

    return ReportSectionsPanel()


def _buttons(panel, name: str):
    from PySide6.QtWidgets import QPushButton

    return [button for button in panel.findChildren(QPushButton) if button.objectName() == name]


def _flush() -> None:
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_lists_sections_with_status_glyphs_and_counter() -> None:
    from echo_personal_tool.domain.services.report_sections import build_report_sections
    from echo_personal_tool.infrastructure.i18n import tr

    panel = _panel()
    panel.set_projection(_projection("lv.ivsd"))
    assert [section.id for section in panel.sections] == ["lv", "la", "ra", "diastolic", "mv_av", "tv_pv"]
    assert panel.findChild(type(panel._title), "reportSectionsTitle").text() == tr("report.sections")
    assert panel.findChild(type(panel._counter), "reportSectionsCounter").text() == tr(
        "report.sections_counter", done=0, total=6
    )
    glyphs = panel.findChildren(type(panel._title), "reportSectionGlyph")
    assert [label.text() for label in glyphs] == ["◐", "○", "○", "○", "○", "○"]
    assert build_report_sections(_projection("lv.ivsd"))[0].filled == 1


def test_missing_row_emits_the_protocol_step() -> None:
    panel = _panel()
    panel.set_projection(None)
    emitted: list[tuple[str, int]] = []
    panel.measure_requested.connect(lambda protocol, step: emitted.append((protocol, step)))

    first = panel.sections[0].items[0]
    button = next(button for button in _buttons(panel, "reportMeasureLink") if button.property("key") == first.key)
    button.click()

    assert emitted == [(first.protocol_id, first.step_index)]


def test_not_evaluated_is_an_explicit_reversible_mark(monkeypatch) -> None:
    from echo_personal_tool.domain.services.report_sections import CHECK_NOT_OBTAINED, ChecklistDecision
    from echo_personal_tool.presentation.report_mode import sections as sections_module

    monkeypatch.setattr(
        sections_module.ChecklistDecisionDialog,
        "ask",
        classmethod(lambda cls, *args, **kwargs: ChecklistDecision(CHECK_NOT_OBTAINED, "плохая визуализация")),
    )
    panel = _panel()
    panel.set_projection(None)
    missing = panel.sections[0].items[0]
    button = next(button for button in _buttons(panel, "reportNotEvaluated") if button.property("key") == missing.key)
    button.click()
    _flush()

    assert panel.marked_not_evaluated() == {missing.key}
    labels = panel.findChildren(type(panel._title), "reportMissingLabel")
    assert any(label.text() == missing.label and label.property("marked") is True for label in labels)

    toggle = next(button for button in _buttons(panel, "reportNotEvaluated") if button.property("key") == missing.key)
    toggle.click()
    _flush()
    assert panel.marked_not_evaluated() == frozenset()


def test_filled_recommendations_are_not_listed_as_missing() -> None:
    from echo_personal_tool.domain.services.report_sections import RECOMMENDATIONS

    panel = _panel()
    panel.set_projection(_projection(*(item.key for item in RECOMMENDATIONS)))
    assert _buttons(panel, "reportMeasureLink") == []
    assert all(section.filled == section.total for section in panel.sections)


class TestHiddenValuesList:
    """Item 9 of the 2026-11-06 list: «Скрытые: N» with a reversible «вернуть»."""

    def test_nothing_is_shown_without_hidden_rows(self) -> None:
        from echo_personal_tool.infrastructure.i18n import tr

        panel = _panel()
        panel.set_projection(None)
        assert not panel.findChildren(type(panel._title), "reportSectionsSubheader") or all(
            label.text() != tr("report.hidden_values", count=0)
            for label in panel.findChildren(type(panel._title), "reportSectionsSubheader")
        )
        assert panel.hidden_values == ()

    def test_the_counter_and_the_restore_button_appear(self) -> None:
        from echo_personal_tool.infrastructure.i18n import tr

        panel = _panel()
        panel.set_projection(None)

        panel.set_hidden_values((("lv:КДР:0", "ЛЖ: КДР ЛЖ"), ("lv:КДР:1", "ЛЖ: КДР ЛЖ")))

        headers = [label.text() for label in panel.findChildren(type(panel._title), "reportSectionsSubheader")]
        assert tr("report.hidden_values", count=2) in headers
        labels = [label.text() for label in panel.findChildren(type(panel._title), "reportHiddenLabel")]
        assert labels == ["ЛЖ: КДР ЛЖ", "ЛЖ: КДР ЛЖ"]
        assert len(_buttons(panel, "reportRestoreValue")) == 2

    def test_restore_reports_the_key(self) -> None:
        panel = _panel()
        panel.set_projection(None)
        panel.set_hidden_values((("lv:КДР:0", "ЛЖ: КДР ЛЖ"),))
        seen: list[str] = []
        panel.restore_value_requested.connect(seen.append)

        _buttons(panel, "reportRestoreValue")[0].click()

        assert seen == ["lv:КДР:0"]

    def test_a_finished_sheet_cannot_restore(self) -> None:
        panel = _panel()
        panel.set_projection(None)
        panel.set_hidden_values((("lv:КДР:0", "ЛЖ: КДР ЛЖ"),))

        panel.set_frozen(True)
        _flush()

        assert len(_buttons(panel, "reportRestoreValue")) == 1
        assert not _buttons(panel, "reportRestoreValue")[0].isEnabled()


def test_checklist_summary_separates_missing_stale_and_unreviewed() -> None:
    from echo_personal_tool.infrastructure.i18n import tr

    panel = _panel()
    panel.set_projection(StudyProjection(values={"lv.ivsd": ProjectionValue(value=1.0, stale=True)}), unreviewed=2)
    summary = panel.checklist_summary()

    assert (summary.missing, summary.stale, summary.unreviewed) == (21, 1, 2)
    summary_label = panel.findChild(type(panel._title), "reportChecklistSummary")
    assert summary_label.text() == tr("report.checklist.summary", missing=21, stale=1, unreviewed=2)
    assert summary_label.isVisibleTo(panel)
    headers = [label.text() for label in panel.findChildren(type(panel._title), "reportSectionsSubheader")]
    assert tr("report.checklist.stale") in headers
    assert tr("report.checklist.unreviewed") in headers


def test_stale_value_is_listed_apart_and_is_not_counted_as_filled() -> None:
    panel = _panel()
    panel.set_projection(StudyProjection(values={"lv.ivsd": ProjectionValue(value=1.0, stale=True)}))
    lv = panel.sections[0]

    assert lv.items[0].stale is True
    assert lv.items[0].filled is False
    assert lv.filled == 0
    assert any(button.property("key") == "lv.ivsd" for button in _buttons(panel, "reportMeasureLink"))


def test_organ_profile_rows_go_to_their_measurement_tool() -> None:
    panel = _panel()
    panel.set_profile("builtin.vascular")
    panel.set_projection(None)
    emitted: list[str] = []
    panel.tool_requested.connect(emitted.append)

    assert [section.id for section in panel.sections] == ["precerebral"]
    first = panel.sections[0].items[0]
    button = next(button for button in _buttons(panel, "reportMeasureLink") if button.property("key") == first.key)
    button.click()

    assert emitted == [first.tool_id]


def test_a_decision_needs_a_known_kind_and_a_reason() -> None:
    panel = _panel()
    panel.set_projection(None)
    key = panel.sections[0].items[0].key

    with pytest.raises(ValueError):
        panel.set_decision(key, "unknown", "причина")
    with pytest.raises(ValueError):
        panel.set_decision(key, "not_applicable", "   ")
    assert panel.decisions() == {}


def test_a_decision_moves_the_item_out_of_missing_and_keeps_its_reason() -> None:
    from echo_personal_tool.domain.services.report_sections import CHECK_NOT_APPLICABLE

    panel = _panel()
    panel.set_projection(None)
    item = panel.sections[0].items[0]
    missing_before = panel.checklist_summary().missing

    panel.set_decision(item.key, CHECK_NOT_APPLICABLE, "не входит в протокол исследования")
    _flush()
    summary = panel.checklist_summary()

    assert summary.not_applicable == 1
    assert summary.missing == missing_before - 1
    assert panel.decisions()[item.key].reason == "не входит в протокол исследования"
    labels = [label.text() for label in panel.findChildren(type(panel._title), "reportMissingLabel")]
    assert labels.count(item.label) == 1  # one decided row, not one missing row plus one decided row
    decisions = [label.text() for label in panel.findChildren(type(panel._title), "reportChecklistDecision")]
    assert any("не входит в протокол исследования" in text for text in decisions)

    panel.clear_decision(item.key)
    assert panel.checklist_summary().missing == missing_before


def test_the_decision_dialog_requires_a_reason(qapp) -> None:
    from PySide6.QtWidgets import QComboBox, QDialogButtonBox, QLineEdit

    from echo_personal_tool.domain.services.report_sections import CHECK_NOT_APPLICABLE
    from echo_personal_tool.presentation.report_mode.checklist_decision import ChecklistDecisionDialog

    dialog = ChecklistDecisionDialog(label="МЖП")
    reason = dialog.findChild(QLineEdit, "checklistDecisionReason")
    kind = dialog.findChild(QComboBox, "checklistDecisionKind")
    buttons = dialog.findChild(QDialogButtonBox)
    ok = buttons.button(QDialogButtonBox.StandardButton.Ok)

    assert ok.isEnabled() is False

    reason.setText("не входит в протокол")
    kind.setCurrentIndex(kind.findData(CHECK_NOT_APPLICABLE))

    assert ok.isEnabled() is True
    assert dialog.decision().kind == CHECK_NOT_APPLICABLE
    assert dialog.decision().reason == "не входит в протокол"

    reason.setText("   ")
    assert ok.isEnabled() is False


def test_the_decision_dialog_reopens_on_the_current_decision(qapp) -> None:
    from PySide6.QtWidgets import QComboBox, QDialogButtonBox, QLineEdit

    from echo_personal_tool.domain.services.report_sections import CHECK_NOT_OBTAINED, ChecklistDecision
    from echo_personal_tool.presentation.report_mode.checklist_decision import ChecklistDecisionDialog

    dialog = ChecklistDecisionDialog(label="МЖП", current=ChecklistDecision(CHECK_NOT_OBTAINED, "плохая визуализация"))

    assert dialog.findChild(QComboBox, "checklistDecisionKind").currentData() == CHECK_NOT_OBTAINED
    assert dialog.findChild(QLineEdit, "checklistDecisionReason").text() == "плохая визуализация"
    ok = dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok)
    assert ok.isEnabled() is True
