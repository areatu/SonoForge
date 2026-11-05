"""The patient line remains usable when high-DPI displays narrow the window."""

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from echo_personal_tool.application.localization import get_language, set_language
from echo_personal_tool.presentation.dark_theme import build_clinical_stylesheet
from echo_personal_tool.presentation.system_bar import SystemBar
from echo_personal_tool.resources.bundled_fonts import ui_font


@pytest.fixture
def restore_ui_state(qtbot):
    app = QApplication.instance()
    original_language = get_language()
    original_sheet = app.styleSheet()
    original_font = QFont(app.font())
    yield
    set_language(original_language)
    app.setStyleSheet(original_sheet)
    app.setFont(original_font)


@pytest.mark.gui
def test_narrow_actions_remain_visible_and_restore_translated_captions(qtbot, restore_ui_state):
    # The shared GUI suite can leave any earlier theme active. Pin the 12 px
    # theme that exposed the narrow-row regression instead of inheriting it.
    app = QApplication.instance()
    app.setFont(ui_font(pixel_size=12))
    app.setStyleSheet(build_clinical_stylesheet(12, theme="dark"))
    set_language("en")
    bar = SystemBar()
    qtbot.addWidget(bar)
    bar.reload_text()
    bar.resize(911, 42)
    bar.show()
    qtbot.waitUntil(lambda: bar.width() == 911)
    qtbot.waitUntil(lambda: bar._actions_compact)
    buttons = [button for group in bar._action_groups for button in group if button.isVisibleTo(bar)]
    assert buttons
    for button in buttons:
        x = button.mapTo(bar, QPoint(0, 0)).x()
        assert 0 <= x and x + button.width() <= bar.width()
        assert button.accessibleName()
        assert button.toolTip()
    assert bar._btn_open.text() == ""
    assert bar._btn_pacs.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
    for switch in (bar._mode_switch, bar._view_switch):
        x = switch.mapTo(bar, QPoint(0, 0)).x()
        assert 0 <= x and x + switch.width() <= bar.width()
    opened = []
    bar.open_folder_requested.connect(lambda: opened.append(True))
    qtbot.mouseClick(bar._btn_open, Qt.MouseButton.LeftButton)
    assert opened == [True]

    set_language("ru")
    bar.reload_text()
    assert bar._btn_open.text() == ""
    assert bar._btn_open.accessibleName()
    bar.resize(1800, 42)
    qtbot.waitUntil(lambda: not bar._actions_compact)
    assert bar._btn_open.text()
    assert bar._btn_open.accessibleName() == bar._btn_open.text()
    assert bar._btn_pacs.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextBesideIcon
