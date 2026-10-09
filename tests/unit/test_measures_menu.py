"""Measures tab accordion menu layout."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.gui
from PySide6.QtWidgets import QApplication, QPushButton

from echo_personal_tool.presentation.measures_menu import MeasuresMenuWidget


def test_lv_auto_has_no_biplane_buttons(_qapp) -> None:
    menu = MeasuresMenuWidget()
    biplane = [child for child in menu.findChildren(QPushButton) if child.text().startswith("Simpson 2C")]
    assert len(biplane) == 2
    assert all(button.isEnabled() for button in biplane)


@pytest.fixture(scope="session", autouse=True)
def _qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_user_section_shows_its_title_and_saved_position() -> None:
    import copy

    from echo_personal_tool.infrastructure.user_preferences import default_user_preferences
    from echo_personal_tool.presentation.measures_menu import default_tool_layout, encode_tool_layout

    layout = copy.deepcopy(default_tool_layout())
    layout.insert(2, {"key": "custom:mine", "title": "Мои & я", "items": []})
    preferences = default_user_preferences()
    preferences.show_strain = True  # experimental section is hidden by default
    preferences.tool_panel_layout_json = encode_tool_layout(layout)

    menu = MeasuresMenuWidget()
    menu.set_preferences(preferences)

    assert [section._title_key for section in menu._sections] == [entry["key"] for entry in layout]
    user_section = menu._sections[2]
    assert user_section._header.text() == "Мои && я"  # "&" is escaped for Qt mnemonics
    assert user_section._custom_title == "Мои & я"


def test_builtin_section_title_comes_from_translations() -> None:
    from echo_personal_tool.infrastructure.i18n import tr

    menu = MeasuresMenuWidget()
    general = next(section for section in menu._sections if section._title_key == "menu.general")

    assert general._custom_title is None
    assert general._header.text() == tr("menu.general")
