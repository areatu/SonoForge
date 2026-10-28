"""User bindings must change real handlers, not only the settings table."""

from __future__ import annotations

import json
from dataclasses import replace

import numpy as np
import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QAction, QKeyEvent, QKeySequence
from PySide6.QtWidgets import QWidget

from echo_personal_tool.application.profile_settings import active_profile_name
from echo_personal_tool.keyboard_shortcuts import (
    SHORTCUTS,
    bind_action_shortcut,
    configure_shortcuts,
    event_matches_shortcut,
    favorite_shortcut_index,
    install_qshortcuts,
    shortcut_label,
)
from echo_personal_tool.presentation.shortcut_settings import ShortcutSettingsWidget

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def _bindings(qapp):
    configure_shortcuts("")
    yield
    configure_shortcuts("")


def _widget(qtbot, encoded=""):
    widget = ShortcutSettingsWidget(encoded)
    qtbot.addWidget(widget)
    return widget


def test_all_active_keyboard_actions_are_editable_including_favorites(qtbot):
    widget = _widget(qtbot)
    expected = {
        spec.id
        for spec in SHORTCUTS
        if spec.kind == "keyboard" and (not spec.profiles or active_profile_name() in spec.profiles)
    }
    assert set(widget._editors) == expected
    assert {f"favorite_{index}" for index in range(1, 10)} <= expected
    assert "multiview_ctrl_click" not in widget._editors
    assert widget.overrides() == {}


def test_unsaved_edits_do_not_change_runtime_and_reset_restores_aliases(qtbot):
    widget = _widget(qtbot)
    editor = widget._editors["caliper"][0]
    editor.setKeySequence(QKeySequence("F9"))
    assert json.loads(widget.encoded_overrides())["caliper"] == ["F9"]
    assert shortcut_label("caliper") == "L"
    widget.reset_binding("caliper")
    assert "caliper" not in widget.overrides()
    for editor in widget._editors["finish_tool"]:
        editor.clear()
    assert widget.overrides()["finish_tool"] == ()
    widget.reset_binding("finish_tool")
    assert "finish_tool" not in widget.overrides()


def test_key_editor_records_a_real_keyboard_event(qtbot):
    widget = _widget(qtbot)
    widget.resize(760, 600)
    widget.show()
    editor = widget._editors["open_folder"][0]
    editor.setFocus()
    qtbot.keyClick(editor, Qt.Key.Key_F9)
    assert editor.keySequence() == QKeySequence("F9")
    assert widget.overrides()["open_folder"] == ("F9",)


def test_conflicts_across_main_and_viewer_contexts_are_visible(qtbot):
    widget = _widget(qtbot)
    widget._editors["caliper"][0].setKeySequence(QKeySequence("K"))
    assert widget.validation_error()
    assert widget._error.text() == widget.validation_error()
    widget._editors["calibration_toggle"][0].clear()
    assert widget.validation_error() == ""


def test_live_qshortcut_rebind_disable_and_restore_without_duplicate_callbacks(qtbot):
    window = QWidget()
    qtbot.addWidget(window)
    calls = []
    bindings = install_qshortcuts(window, "caliper", lambda: calls.append("caliper"))
    window.show()
    window.activateWindow()
    qtbot.waitExposed(window)
    qtbot.waitUntil(window.isActiveWindow)
    configure_shortcuts(json.dumps({"caliper": ["F9"]}))
    assert bindings[0].keys() == [QKeySequence("F9")]
    qtbot.keyClick(window, Qt.Key.Key_F9)
    qtbot.keyClick(window, Qt.Key.Key_L)
    assert calls == ["caliper"]
    configure_shortcuts(json.dumps({"caliper": []}))
    qtbot.keyClick(window, Qt.Key.Key_F9)
    qtbot.keyClick(window, Qt.Key.Key_L)
    assert calls == ["caliper"]
    configure_shortcuts("")
    qtbot.keyClick(window, Qt.Key.Key_L)
    assert calls == ["caliper", "caliper"]


def test_action_menus_follow_live_changes_and_allow_disabling(qtbot):
    window = QWidget()
    qtbot.addWidget(window)
    action = QAction("Save", window)
    bind_action_shortcut(action, "constructor_save")
    configure_shortcuts(json.dumps({"constructor_save": ["Alt+F9"]}))
    assert action.shortcuts() == [QKeySequence("Alt+F9")]
    configure_shortcuts(json.dumps({"constructor_save": []}))
    assert action.shortcuts() == []


def test_user_ctrl_binding_is_not_blocked_by_legacy_forbidden_modifier():
    # Ctrl+Y belongs to the new measurement-redo action; use an unclaimed chord
    # so this test covers the legacy-handler modifier exception, not collisions.
    configure_shortcuts(json.dumps({"magnifier_hold": ["Ctrl+J"]}))
    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_J, Qt.KeyboardModifier.ControlModifier)
    assert event_matches_shortcut(event, "magnifier_hold", exact_modifiers=False, forbidden_modifiers=("Ctrl",))
    extra = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_J, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
    )
    assert not event_matches_shortcut(extra, "magnifier_hold", exact_modifiers=False)
    assert shortcut_label("magnifier_hold") == "Ctrl+J"


@pytest.mark.parametrize(
    "key,qt_key", [("Ctrl++", Qt.Key.Key_Plus), ("Ctrl+;", Qt.Key.Key_Semicolon), ("Ctrl+PgUp", Qt.Key.Key_PageUp)]
)
def test_custom_punctuation_and_special_keys_match_real_events(key, qt_key):
    configure_shortcuts(json.dumps({"magnifier_hold": [key]}))
    event = QKeyEvent(QEvent.Type.KeyPress, qt_key, Qt.KeyboardModifier.ControlModifier)
    assert event_matches_shortcut(event, "magnifier_hold")


def test_remapped_favorite_has_no_remaining_digit_alias(qtbot):
    from echo_personal_tool.infrastructure.user_preferences import UserPreferences
    from echo_personal_tool.presentation.tool_panel_v2.panel import ToolPanelV2

    configure_shortcuts(json.dumps({"favorite_1": ["Alt+1"]}))
    panel = ToolPanelV2(UserPreferences())
    qtbot.addWidget(panel)
    # The favourite key is a badge now, not a second text line under the name.
    assert panel._favorite_buttons[0].badge_text().endswith("Alt+1")
    assert favorite_shortcut_index(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_1, Qt.KeyboardModifier.AltModifier)) == 0
    assert (
        favorite_shortcut_index(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_1, Qt.KeyboardModifier.NoModifier)) is None
    )


def test_new_binding_updates_an_existing_main_window(qtbot, make_main_window, synthetic_dicom_path):
    from echo_personal_tool.application.app_controller import AppController
    from echo_personal_tool.domain.models import InstanceMetadata

    controller = AppController()
    instance = InstanceMetadata("1.2.3.4", "1.2.3", "US", 1, (0.5, 0.5), 33.3, "A4C", path=synthetic_dicom_path)
    controller.state_manager.set_instance(instance, total_frames=1, frame_time_ms=33.3)
    window = make_main_window(controller=controller)
    window.show()
    qtbot.waitExposed(window)
    window._viewer.show_frame(np.zeros((64, 64), dtype=np.uint8))
    window._apply_user_preferences(
        replace(window._user_preferences, shortcut_overrides_json=json.dumps({"caliper": ["F9"]}))
    )
    qtbot.keyClick(window, Qt.Key.Key_F9)
    assert window._viewer.is_linear_caliper_active
    qtbot.keyClick(window, Qt.Key.Key_Escape)
    assert not window._viewer.is_linear_caliper_active
    qtbot.keyClick(window, Qt.Key.Key_L)
    assert not window._viewer.is_linear_caliper_active


def test_profile_inactive_bindings_are_preserved_when_editing(qtbot):
    widget = _widget(qtbot, json.dumps({"presenter_toggle": ["F8"]}))
    assert widget.overrides()["presenter_toggle"] == ("F8",)


def test_numpad_specific_binding_does_not_match_the_regular_number_row():
    configure_shortcuts('{"favorite_1": ["Num+2"]}')
    numpad = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_2, Qt.KeyboardModifier.KeypadModifier)
    regular = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_2, Qt.KeyboardModifier.NoModifier)
    assert favorite_shortcut_index(numpad) == 0
    assert favorite_shortcut_index(regular) == 1


def test_later_favorite_can_claim_the_numpad_without_losing_to_regular_digits():
    configure_shortcuts('{"favorite_9": ["Num+2"]}')
    numpad = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_2, Qt.KeyboardModifier.KeypadModifier)
    regular = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_2, Qt.KeyboardModifier.NoModifier)
    assert favorite_shortcut_index(numpad) == 8
    assert favorite_shortcut_index(regular) == 1


def test_custom_combination_takes_priority_over_permissive_legacy_handlers():
    configure_shortcuts('{"caliper": ["Ctrl+Space"]}')
    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.ControlModifier)
    assert not event_matches_shortcut(event, "play_pause", exact_modifiers=False)
    assert event_matches_shortcut(event, "caliper")


def test_other_window_and_inactive_profile_bindings_do_not_shadow_main_keys():
    configure_shortcuts('{"constructor_save": ["Ctrl+Space"], "presenter_toggle": ["Ctrl+Space"]}')
    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.ControlModifier)
    assert event_matches_shortcut(event, "play_pause", exact_modifiers=False)


def test_disabled_bindings_leave_no_empty_shortcut_hint():
    from echo_personal_tool.keyboard_shortcuts import append_shortcut_hint, shortcut_note

    configure_shortcuts('{"caliper": []}')
    assert shortcut_note("caliper") == ""
    assert append_shortcut_hint("Caliper", "caliper") == "Caliper"
