"""Item 5 of the 2026-11-06 list: heart-rate tools are experimental.

The owner asked for «ЧСС», «Авто-ЧСС», «ЧСС по допплеру», «Время / ЧСС» and
«D/S маркеры» to be hidden until the «Показать инструменты ЧСС» checkbox of the
settings is on.  One preference governs the whole branch — the catalog gates the
tools of the panel, :func:`visible_buttons` gates the strip, the window gates the
button of the patient line — and the hotkeys keep working while the buttons are
hidden (the owner asked to hide a button, not to remove the function).
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from echo_personal_tool.domain.measurement_catalog import CATALOG
from echo_personal_tool.domain.tool_layout_v3 import default_layout
from echo_personal_tool.domain.tool_panel_view import panel_view
from echo_personal_tool.infrastructure.user_preferences import UserPreferences
from echo_personal_tool.presentation.tool_buttons import buttons as tool_buttons

#: Every tool or button the checkbox governs.
_GATED_TOOL_IDS = ("hr.auto", "hr.doppler", "mmode.time_hr")
_GATED_BUTTON_IDS = ("ds_markers",)


def _panel_ids(context: str, preferences: UserPreferences) -> set[str]:
    view = panel_view(default_layout(), context, language="ru", preferences=preferences)
    return {tool.id for section in view.sections for tool in section.items}


def test_the_catalog_tools_carry_the_preference_flag() -> None:
    for tool_id in _GATED_TOOL_IDS:
        tool = CATALOG[tool_id]
        assert "pref:show_heart_rate_tools" in tool.flags, tool_id
        assert "experimental" in tool.flags, tool_id


def test_the_strain_and_ai_flags_keep_their_own_preferences() -> None:
    """The new flag must not become a second, weaker gate on unrelated tools."""
    assert "pref:show_heart_rate_tools" not in CATALOG["tool.caliper"].flags
    assert "pref:show_heart_rate_tools" not in CATALOG["tool.area"].flags


@pytest.mark.parametrize("context", ["2d", "doppler", "m"])
def test_the_panel_hides_the_tools_until_the_checkbox_is_on(context: str) -> None:
    off = UserPreferences()
    assert not set(_GATED_TOOL_IDS) & _panel_ids(context, off)

    on = replace(off, show_heart_rate_tools=True)
    shown = _panel_ids(context, on) & set(_GATED_TOOL_IDS)
    assert shown, "the branch must come back with the checkbox"
    # Exactly the tools that belong to this context come back: the Doppler HR
    # needs a spectrum, the M-mode interval needs a trace.
    if context == "2d":
        assert "hr.auto" in shown
        assert "hr.doppler" not in shown
        assert "mmode.time_hr" not in shown
    elif context == "doppler":
        assert "hr.doppler" in shown
    else:
        assert "mmode.time_hr" in shown


def test_the_strip_drops_the_ds_button_until_the_checkbox_is_on() -> None:
    state = tool_buttons.ToolButtonState()
    off = UserPreferences()
    ids = [spec.id for spec in tool_buttons.visible_buttons(state, off)]
    assert not set(_GATED_BUTTON_IDS) & set(ids)

    on = replace(off, show_heart_rate_tools=True)
    ids_on = [spec.id for spec in tool_buttons.visible_buttons(state, on)]
    assert set(_GATED_BUTTON_IDS) <= set(ids_on)


def test_the_table_keeps_the_button_so_the_hotkey_still_resolves() -> None:
    """Hidden from the strip is not removed from the table (the shortcut stays)."""
    spec = tool_buttons.tool_button_spec("ds_markers")
    assert spec is not None
    assert spec.flags == frozenset({"experimental", "pref:show_heart_rate_tools"})


def test_visible_buttons_without_preferences_is_the_whole_table() -> None:
    """Old callers that pass only the state keep the pre-item-5 behaviour."""
    specs = tool_buttons.visible_buttons(tool_buttons.ToolButtonState())
    assert specs == tool_buttons.TOOL_BUTTONS


def test_the_preference_round_trips_through_the_store() -> None:
    from echo_personal_tool.infrastructure.user_preferences import (
        load_user_preferences,
        save_user_preferences,
    )

    assert UserPreferences().show_heart_rate_tools is False
    assert UserPreferences(show_heart_rate_tools=True).show_heart_rate_tools is True

    preferences = UserPreferences(show_heart_rate_tools=True)
    save_user_preferences(preferences)
    assert load_user_preferences().show_heart_rate_tools is True

    save_user_preferences(replace(preferences, show_heart_rate_tools=False))
    assert load_user_preferences().show_heart_rate_tools is False


@pytest.mark.gui
def test_the_patient_line_hides_its_heart_rate_button(qtbot) -> None:
    """The «ЧСС» button of the header follows the same checkbox."""
    from echo_personal_tool.application.app_controller import AppController
    from echo_personal_tool.presentation.main_window import MainWindow

    preferences = UserPreferences(tool_panel_v2=True)
    window = MainWindow(controller=AppController(), user_preferences=preferences)
    qtbot.addWidget(window)

    button = window._system_bar._btn_heart_rate
    assert button.isHidden() is True

    window._apply_user_preferences(replace(preferences, show_heart_rate_tools=True))
    assert button.isHidden() is False

    window._apply_user_preferences(replace(preferences, show_heart_rate_tools=False))
    assert button.isHidden() is True
