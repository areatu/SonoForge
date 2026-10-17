"""The image tool row in the window (UI-2 PR-3): choice, visibility, storage, one entry point."""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def _isolate_qsettings(isolated_qsettings):
    """Layout rebuilds persist to QSettings — keep them out of the real store."""
    return isolated_qsettings


from PySide6.QtWidgets import QMenu  # noqa: E402

from echo_personal_tool.application.app_controller import AppController  # noqa: E402
from echo_personal_tool.infrastructure.user_preferences import UserPreferences  # noqa: E402
from echo_personal_tool.presentation.layout.presets import LayoutConfigV2  # noqa: E402
from echo_personal_tool.presentation.main_window import LayoutConfig, MainWindow  # noqa: E402
from echo_personal_tool.presentation.measurement_action import MeasurementAction  # noqa: E402


def _window(qtbot, *, v2: str = "") -> MainWindow:
    prefs = UserPreferences(layout_state_v2_json=v2)
    window = MainWindow(controller=AppController(), user_preferences=prefs)
    qtbot.addWidget(window)
    window.resize(1280, 800)
    window.show()
    qtbot.waitExposed(window)
    return window


def _with_study(window: MainWindow) -> None:
    window._has_loaded_study = True
    window._rebuild_layout()


def test_row_is_off_by_default_and_the_document_says_auto(qtbot) -> None:
    window = _window(qtbot)
    saved = json.loads(window._user_preferences.layout_state_v2_json)
    assert saved["tool_buttons"] == "auto"
    assert not window._tool_row.isVisibleTo(window)


def test_row_shows_over_a_loaded_image_only(qtbot) -> None:
    window = _window(qtbot)
    window._set_tool_buttons("row")
    assert not window._tool_row.isVisibleTo(window)  # no study yet
    _with_study(window)
    assert window._tool_row.isVisibleTo(window)
    assert json.loads(window._user_preferences.layout_state_v2_json)["tool_buttons"] == "row"


def test_panel_choice_hides_the_row_and_keeps_the_panel(qtbot) -> None:
    window = _window(qtbot, v2=LayoutConfigV2(tool_buttons="row").to_json())
    _with_study(window)
    assert window._tool_row.isVisibleTo(window)
    window._set_tool_buttons("panel")
    assert not window._tool_row.isVisibleTo(window)
    assert json.loads(window._user_preferences.layout_state_v2_json)["tool_buttons"] == "panel"


def test_activity_bar_wins_over_the_row(qtbot) -> None:
    window = _window(qtbot, v2=LayoutConfigV2(tool_buttons="row").to_json())
    _with_study(window)
    window._on_layout_toggle("activity_bar", True)
    assert not window._tool_row.isVisibleTo(window)
    assert json.loads(window._user_preferences.layout_state_v2_json)["tool_buttons"] == "rail"


def test_row_choice_survives_a_restart(qtbot) -> None:
    window = _window(qtbot, v2=LayoutConfigV2(tool_buttons="row").to_json())
    restored = LayoutConfig.from_v2(LayoutConfigV2.from_json(window._user_preferences.layout_state_v2_json))
    assert restored.tool_buttons == "row"
    assert restored.to_v2().tool_buttons == "row"


def test_layout_menu_offers_the_two_radio_choices(qtbot) -> None:
    window = _window(qtbot, v2=LayoutConfigV2(tool_buttons="row").to_json())
    menu = window._build_layout_menu()
    buttons = menu.findChild(QMenu, "layoutToolButtonsMenu")
    assert buttons is not None
    checked = {action.data(): action.isChecked() for action in buttons.actions()}
    assert checked == {"tool_buttons:row": True, "tool_buttons:panel": False}


def test_row_click_emits_the_panel_contract(qtbot) -> None:
    window = _window(qtbot, v2=LayoutConfigV2(tool_buttons="row").to_json())
    _with_study(window)
    with qtbot.waitSignal(window._tool_row.action_requested, timeout=1000) as blocker:
        window._tool_row.button("doppler").click()
    assert blocker.args == [MeasurementAction.DOPPLER_TRACE, "A4C", "ED", ""]
