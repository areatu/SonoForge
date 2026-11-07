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


def test_not_evaluated_is_an_explicit_reversible_mark() -> None:
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
