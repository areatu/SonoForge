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


def test_general_doppler_heart_rate_routes_time_interval_and_requires_time(qtbot) -> None:
    from echo_personal_tool.infrastructure.i18n import tr
    from echo_personal_tool.presentation.measurement_action import MeasurementAction

    menu = MeasuresMenuWidget()
    qtbot.addWidget(menu)
    general = next(section for section in menu._sections if section._title_key == "menu.general")
    button = next(child for child in general.findChildren(QPushButton) if child.text() == tr("menu.doppler_heart_rate"))

    menu.set_doppler_tool_availability(time_ok=False)
    assert not button.isEnabled()
    menu.set_doppler_tool_availability(time_ok=True, vessel_ok=False)
    assert button.isEnabled()
    with qtbot.waitSignal(menu.action_requested) as signal:
        button.click()
    assert signal.args == [MeasurementAction.DOPPLER_INTERVAL, "A4C", "ED", "RR"]
    # The existing cine auto-HR tool is a separate action.
    assert any(spec.action == MeasurementAction.HEART_RATE for _, spec in menu._tool_buttons)
