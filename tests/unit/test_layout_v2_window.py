"""MainWindow on layout v2: storage keys, migration on start, exclusive presets, slot assembly.

UI-2 PR-1, spec §8.1. The version-1 key is read for migration and never overwritten.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def _isolate_qsettings(isolated_qsettings):
    """Layout rebuilds persist to QSettings — keep them out of the real store."""
    return isolated_qsettings


from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

from echo_personal_tool.application.app_controller import AppController  # noqa: E402
from echo_personal_tool.infrastructure.user_preferences import UserPreferences  # noqa: E402
from echo_personal_tool.presentation.layout.presets import (  # noqa: E402
    PRESET_CLASSIC,
    PRESET_FILMSTRIP,
    PRESET_MIRRORED,
    LayoutConfigV2,
    slot_plan,
)
from echo_personal_tool.presentation.main_window import LayoutConfig, MainWindow  # noqa: E402


def _window(qtbot, *, v1: str = "", v2: str = "") -> MainWindow:
    prefs = UserPreferences(layout_state_json=v1, layout_state_v2_json=v2)
    window = MainWindow(controller=AppController(), user_preferences=prefs)
    qtbot.addWidget(window)
    window.resize(1280, 800)
    window.show()
    qtbot.waitExposed(window)
    return window


def test_fresh_install_saves_the_classic_document(qtbot) -> None:
    window = _window(qtbot)
    saved = json.loads(window._user_preferences.layout_state_v2_json)
    assert saved["version"] == 2
    assert saved["preset"] == PRESET_CLASSIC
    assert saved["tool_buttons"] == "auto"


def test_saving_never_touches_the_version_one_key(qtbot) -> None:
    v1 = json.dumps({"swap_places": True})
    window = _window(qtbot, v1=v1)
    window._on_layout_toggle("activity_bar", True)
    assert window._user_preferences.layout_state_json == v1
    saved = json.loads(window._user_preferences.layout_state_v2_json)
    assert saved["preset"] == PRESET_MIRRORED
    assert saved["tool_buttons"] == "rail"


def test_a_version_one_key_is_migrated_on_start(qtbot) -> None:
    window = _window(qtbot, v1=json.dumps({"gallery_horizontal": True, "swap_places": True}))
    assert window._layout_config.gallery_horizontal is True
    assert window._layout_config.swap_places is False  # the filmstrip wins (spec §8.1)


def test_a_version_two_document_wins_over_the_version_one_key(qtbot) -> None:
    v1 = json.dumps({"gallery_horizontal": True})
    v2 = LayoutConfigV2(preset=PRESET_MIRRORED).to_json()
    window = _window(qtbot, v1=v1, v2=v2)
    assert window._layout_config.swap_places is True
    assert window._layout_config.gallery_horizontal is False


def test_the_snapshot_round_trips_through_the_document(qtbot) -> None:
    window = _window(qtbot)
    window._on_layout_toggle("gallery_horizontal", True)
    saved = window._user_preferences.layout_state_v2_json
    restored = LayoutConfig.from_v2(LayoutConfigV2.from_json(saved))
    assert restored.gallery_horizontal is True
    assert restored.multiview is False
    assert restored == replace(window._layout_config, multiview=False)


def test_turning_one_preset_on_turns_the_other_off(qtbot) -> None:
    window = _window(qtbot)
    window._on_layout_toggle("swap_places", True)
    assert window._layout_config.swap_places is True
    window._on_layout_toggle("gallery_horizontal", True)
    assert window._layout_config.gallery_horizontal is True
    assert window._layout_config.swap_places is False


def test_open_logo_menu_shows_the_exclusive_check(qtbot) -> None:
    window = _window(qtbot)
    menu = window._title_bar.app_button.menu()
    assert menu is not None
    layout_menu = menu.findChild(QMenu, "appMenuLayout")
    assert layout_menu is not None
    checks = {action.data(): action for action in layout_menu.actions()}
    checks["swap_places"].setChecked(True)  # what the user sees before a change
    window._on_layout_toggle("gallery_horizontal", True)
    assert checks["gallery_horizontal"].isChecked() is True
    assert checks["swap_places"].isChecked() is False


@pytest.mark.parametrize(
    ("preset", "rail"),
    [(preset, rail) for preset in (PRESET_CLASSIC, PRESET_MIRRORED, PRESET_FILMSTRIP) for rail in (False, True)],
)
def test_side_slots_are_filled_from_the_table(qtbot, preset: str, rail: bool) -> None:
    document = LayoutConfigV2(preset=preset, tool_buttons="rail" if rail else "auto")
    window = _window(qtbot, v2=document.to_json())
    plan = slot_plan(document, multiview=False)
    QApplication.processEvents()

    left = window._content_layout.itemAt(0).widget() if window._content_layout.count() else None
    right_index = window._content_layout.count() - 1
    right = window._content_layout.itemAt(right_index).widget() if right_index >= 0 else None

    expected_left = {"gallery": window._gallery, "tool_panel": window._tool_panel, "rail": window._activity_bar}
    expected_right = {"gallery": window._gallery, "tool_panel": window._tool_panel, "rail": window._activity_bar}
    if plan.left is None:
        assert left is not window._gallery and left is not window._tool_panel
    else:
        assert left is expected_left[plan.left]
    if plan.right is None:
        assert right is not window._gallery and right is not window._tool_panel
    else:
        assert right is expected_right[plan.right]
    if plan.bottom is not None:
        assert window._gallery.isVisibleTo(window)
