"""The layout group of the settings: preset tiles, tool buttons, v2 flags (UI-2 PR-2).

Spec §4.9. The widget edits a ``LayoutConfigV2`` document; the dialog writes it
to ``layout_state_v2_json`` on accept and never touches the version-1 key.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytestmark = pytest.mark.gui

from PySide6.QtCore import Qt  # noqa: E402

from echo_personal_tool.presentation.layout.layout_settings import LayoutSettingsWidget  # noqa: E402
from echo_personal_tool.presentation.layout.presets import (  # noqa: E402
    PRESET_CLASSIC,
    PRESET_FILMSTRIP,
    PRESET_MIRRORED,
    LayoutConfigV2,
)


def _section(qtbot, document: LayoutConfigV2 | None = None) -> LayoutSettingsWidget:
    section = LayoutSettingsWidget(document or LayoutConfigV2())
    qtbot.addWidget(section)
    return section


def test_preset_radios_reflect_the_document(qtbot) -> None:
    section = _section(qtbot, LayoutConfigV2(preset=PRESET_MIRRORED))
    by_preset = {tile.preset: tile for tile in section._tiles.values()}
    assert set(by_preset) == {PRESET_CLASSIC, PRESET_MIRRORED, PRESET_FILMSTRIP}
    assert [by_preset[name].radio.isChecked() for name in (PRESET_CLASSIC, PRESET_MIRRORED, PRESET_FILMSTRIP)] == [
        False,
        True,
        False,
    ]
    assert section.document().preset == PRESET_MIRRORED


def test_preset_radio_click_changes_the_document(qtbot) -> None:
    section = _section(qtbot)
    section.show()
    qtbot.waitExposed(section)
    section._tiles[PRESET_FILMSTRIP].radio.click()
    assert section.document().preset == PRESET_FILMSTRIP
    assert section._tiles[PRESET_CLASSIC].radio.isChecked() is False


def test_scheme_click_selects_the_preset(qtbot) -> None:
    section = _section(qtbot)
    section.show()
    qtbot.waitExposed(section)
    tile = section._tiles[PRESET_MIRRORED]
    qtbot.mouseClick(tile.scheme, Qt.MouseButton.LeftButton)
    assert tile.radio.isChecked() is True
    assert section.document().preset == PRESET_MIRRORED


def test_tool_buttons_combo_round_trips_all_modes(qtbot) -> None:
    section = _section(qtbot)
    for mode in LayoutSettingsWidget.TOOL_BUTTON_MODES:
        section._tool_buttons.setCurrentIndex(section._tool_buttons.findData(mode))
        assert section.document().tool_buttons == mode


def test_tool_buttons_combo_shows_the_stored_mode(qtbot) -> None:
    section = _section(qtbot, LayoutConfigV2(tool_buttons="rail"))
    assert section._tool_buttons.currentData() == "rail"
    assert section.document().tool_buttons == "rail"


def test_tool_labels_combo_round_trips(qtbot) -> None:
    section = _section(qtbot)
    for mode in LayoutSettingsWidget.TOOL_LABEL_MODES:
        section._tool_labels.setCurrentIndex(section._tool_labels.findData(mode))
        assert section.document().tool_labels == mode


def test_status_bar_and_focus_checkboxes_round_trip(qtbot) -> None:
    section = _section(qtbot)
    section._status_bar.setChecked(False)
    section._single_file_focus.setChecked(False)
    document = section.document()
    assert document.status_bar_visible is False
    assert document.single_file_focus is False
    section._status_bar.setChecked(True)
    section._single_file_focus.setChecked(True)
    document = section.document()
    assert document.status_bar_visible is True
    assert document.single_file_focus is True


def test_set_document_updates_every_control(qtbot) -> None:
    section = _section(qtbot)
    section.set_document(
        LayoutConfigV2(
            preset=PRESET_FILMSTRIP,
            tool_buttons="panel",
            tool_labels="icons",
            status_bar_visible=False,
            single_file_focus=False,
        )
    )
    assert section._tiles[PRESET_FILMSTRIP].radio.isChecked() is True
    assert section._tool_buttons.currentData() == "panel"
    assert section._tool_labels.currentData() == "icons"
    assert section._status_bar.isChecked() is False
    assert section._single_file_focus.isChecked() is False
    assert section.document() == LayoutConfigV2(
        preset=PRESET_FILMSTRIP,
        tool_buttons="panel",
        tool_labels="icons",
        status_bar_visible=False,
        single_file_focus=False,
    )


def test_dialog_saves_the_layout_document_and_leaves_v1_untouched(qtbot) -> None:
    import json

    from echo_personal_tool.infrastructure.user_preferences import (
        default_user_preferences,
        load_user_preferences,
        save_user_preferences,
    )
    from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

    v1 = json.dumps({"swap_places": True})
    preferences = default_user_preferences()
    preferences.layout_state_json = v1
    preferences.layout_state_v2_json = LayoutConfigV2().to_json()
    save_user_preferences(preferences)
    applied = []
    dialog = UserPreferencesDialog(on_apply=applied.append)
    qtbot.addWidget(dialog)
    assert dialog._layout_section.document().preset == PRESET_CLASSIC

    dialog._layout_section._tiles[PRESET_MIRRORED].radio.setChecked(True)
    dialog._layout_section._tool_buttons.setCurrentIndex(dialog._layout_section._tool_buttons.findData("rail"))
    with patch("echo_personal_tool.presentation.user_preferences_dialog.save_server_settings"):
        dialog._on_accept()

    saved = load_user_preferences()
    assert saved.layout_state_json == v1
    assert LayoutConfigV2.from_json(saved.layout_state_v2_json) == LayoutConfigV2(
        preset=PRESET_MIRRORED, tool_buttons="rail"
    )
    assert applied[0].layout_state_v2_json == saved.layout_state_v2_json


def test_dialog_shows_the_migrated_v1_document(qtbot) -> None:
    import json

    from echo_personal_tool.infrastructure.user_preferences import default_user_preferences, save_user_preferences
    from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

    preferences = default_user_preferences()
    preferences.layout_state_json = json.dumps({"gallery_horizontal": True})
    preferences.layout_state_v2_json = ""
    save_user_preferences(preferences)
    dialog = UserPreferencesDialog()
    qtbot.addWidget(dialog)
    assert dialog._layout_section.document().preset == PRESET_FILMSTRIP
