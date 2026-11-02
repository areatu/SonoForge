"""Accessibility of the report export block (S3-04, #313).

The block is the last thing a surgeon touches before a report leaves the
application, so every action must be nameable by a screen reader (a terse «PDF…»
reads as punctuation) and reachable in reading order from the keyboard. These
cases are the automated half of the manual checklist in
``docs/reviews/2026-11-01-s3-04-pdf-worker-budget-a11y-ru.md``.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.gui

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPushButton

from echo_personal_tool.application.localization import set_language


@pytest.fixture(autouse=True)
def _qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _russian():
    set_language("ru")
    yield
    set_language("ru")


def _panel(qtbot):
    from echo_personal_tool.presentation.report_mode.export import ReportExportPanel

    panel = ReportExportPanel()
    qtbot.addWidget(panel)
    panel.show()
    qtbot.waitExposed(panel)
    return panel


class TestAccessibleNames:
    def test_every_action_has_a_name(self, qtbot) -> None:
        panel = _panel(qtbot)

        for button in (panel.pdf_button, panel.print_button, panel.finish_button):
            assert isinstance(button, QPushButton)
            assert button.accessibleName().strip(), button.objectName()

    def test_names_say_more_than_the_visible_caption(self, qtbot) -> None:
        panel = _panel(qtbot)

        assert panel.pdf_button.accessibleName() != panel.pdf_button.text()
        assert panel.print_button.accessibleName() != panel.print_button.text()
        assert "PDF" in panel.pdf_button.accessibleName()

    def test_names_are_distinct(self, qtbot) -> None:
        panel = _panel(qtbot)
        names = {
            panel.pdf_button.accessibleName(),
            panel.print_button.accessibleName(),
            panel.finish_button.accessibleName(),
        }

        assert len(names) == 3

    def test_the_status_line_is_nameable(self, qtbot) -> None:
        from PySide6.QtWidgets import QLabel

        panel = _panel(qtbot)
        status = panel.findChild(QLabel, "reportExportStatus")

        assert status is not None
        assert status.accessibleName().strip()

    def test_the_finished_state_renames_the_action(self, qtbot) -> None:
        panel = _panel(qtbot)
        draft_name = None

        panel.set_finished(True)
        draft_name = panel.finish_button.accessibleName()
        panel.set_finished(False)

        assert draft_name
        assert draft_name != panel.finish_button.accessibleName()

    def test_a_language_switch_retranslates_the_names(self, qtbot) -> None:
        panel = _panel(qtbot)
        russian = panel.pdf_button.accessibleName()

        set_language("en")
        panel.reload_text()
        english = panel.pdf_button.accessibleName()

        assert russian and english
        assert russian != english


class TestKeyboardOrder:
    def test_the_buttons_are_in_the_tab_chain_in_reading_order(self, qtbot) -> None:
        panel = _panel(qtbot)

        assert panel.pdf_button.nextInFocusChain() is panel.print_button
        assert panel.print_button.nextInFocusChain() is panel.finish_button

    def test_every_action_accepts_focus(self, qtbot) -> None:
        panel = _panel(qtbot)

        for button in (panel.pdf_button, panel.print_button, panel.finish_button):
            assert button.focusPolicy() != Qt.FocusPolicy.NoFocus, button.objectName()

    def test_space_activates_the_focused_action(self, qtbot) -> None:
        panel = _panel(qtbot)
        seen: list[str] = []
        panel.export_requested.connect(lambda: seen.append("pdf"))

        panel.pdf_button.setFocus()
        qtbot.keyClick(panel.pdf_button, Qt.Key.Key_Space)

        assert seen == ["pdf"]
