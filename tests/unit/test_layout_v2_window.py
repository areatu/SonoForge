"""MainWindow on layout v2: presets, the tool-buttons row, storage and the 300 ms gate.

UI-2 PR-2, spec §4.2, §8.1, G-2. The five version-1 checkboxes are gone: the
logo menu offers three preset radios, a «Tool buttons» submenu and «Настроить…».
The version-1 key is read for migration and never overwritten.
"""

from __future__ import annotations

import json
from dataclasses import replace
from time import perf_counter

import pytest

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def _isolate_qsettings(isolated_qsettings):
    """Layout rebuilds persist to QSettings — keep them out of the real store."""
    return isolated_qsettings


@pytest.fixture(autouse=True)
def _stub_load_failure_dialog(monkeypatch) -> None:
    """Synthetic publishes autoload a clip whose files do not exist; the async
    load failure would open a modal QMessageBox and block headless runs."""
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)


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
from echo_personal_tool.presentation.main_window import MainWindow  # noqa: E402


def _window(qtbot, *, v1: str = "", v2: str = "") -> MainWindow:
    prefs = UserPreferences(layout_state_json=v1, layout_state_v2_json=v2)
    window = MainWindow(controller=AppController(), user_preferences=prefs)
    qtbot.addWidget(window)
    window.resize(1280, 800)
    window.show()
    qtbot.waitExposed(window)
    return window


def _layout_menu(window: MainWindow) -> QMenu:
    menu = window._title_bar.app_button.menu()
    assert menu is not None
    layout_menu = menu.findChild(QMenu, "appMenuLayout")
    assert layout_menu is not None
    return layout_menu


def _preset_actions(window: MainWindow) -> list:
    return [
        action
        for action in _layout_menu(window).actions()
        if isinstance(action.data(), tuple) and action.data()[0] == "preset"
    ]


def _tool_button_actions(window: MainWindow) -> list:
    tools_menu = _layout_menu(window).findChild(QMenu, "layoutToolButtonsMenu")
    assert tools_menu is not None
    return [
        action
        for action in tools_menu.actions()
        if isinstance(action.data(), tuple) and action.data()[0] == "tool_buttons"
    ]


def _publish_one_study(window: MainWindow) -> None:
    from datetime import datetime

    from echo_personal_tool.domain.models.metadata import InstanceMetadata, SeriesMetadata, StudyMetadata

    instance = InstanceMetadata(
        sop_instance_uid="1.2.3.preset",
        series_uid="1.2.3.preset.series",
        modality="US",
        number_of_frames=4,
        pixel_spacing=(0.5, 0.5),
        frame_time_ms=33.3,
        series_description="A4C",
        path=None,
    )
    series = SeriesMetadata(
        series_uid="1.2.3.preset.series",
        study_uid="1.2.3.preset",
        modality="US",
        description="A4C",
        instances=(instance,),
    )
    study = StudyMetadata(study_uid="1.2.3.preset", study_datetime=datetime(2026, 10, 1), series=(series,))
    window._controller.studies_loaded.emit([study])
    QApplication.processEvents()


def test_fresh_install_saves_the_classic_document(qtbot) -> None:
    window = _window(qtbot)
    saved = json.loads(window._user_preferences.layout_state_v2_json)
    assert saved["version"] == 2
    assert saved["preset"] == PRESET_CLASSIC
    assert saved["tool_buttons"] == "auto"


def test_saving_never_touches_the_version_one_key(qtbot) -> None:
    v1 = json.dumps({"swap_places": True})
    window = _window(qtbot, v1=v1)
    window._on_layout_preset_selected(PRESET_MIRRORED)
    window._on_layout_tool_buttons_selected("rail")
    assert window._user_preferences.layout_state_json == v1
    saved = json.loads(window._user_preferences.layout_state_v2_json)
    assert saved["preset"] == PRESET_MIRRORED
    assert saved["tool_buttons"] == "rail"


def test_a_version_one_key_is_migrated_on_start(qtbot) -> None:
    window = _window(qtbot, v1=json.dumps({"gallery_horizontal": True, "swap_places": True}))
    assert window._layout_document.preset == PRESET_FILMSTRIP  # the filmstrip wins (spec §8.1)
    assert window._layout_document.tool_buttons == "auto"


def test_a_version_two_document_wins_over_the_version_one_key(qtbot) -> None:
    v1 = json.dumps({"gallery_horizontal": True})
    v2 = LayoutConfigV2(preset=PRESET_MIRRORED).to_json()
    window = _window(qtbot, v1=v1, v2=v2)
    assert window._layout_document.preset == PRESET_MIRRORED


def test_the_document_round_trips_through_save(qtbot) -> None:
    window = _window(qtbot)
    window._on_layout_preset_selected(PRESET_FILMSTRIP)
    saved = window._user_preferences.layout_state_v2_json
    assert LayoutConfigV2.from_json(saved) == window._layout_document
    assert window._layout_document.preset == PRESET_FILMSTRIP


def test_preset_menu_offers_three_exclusive_radios(qtbot) -> None:
    window = _window(qtbot)
    presets = _preset_actions(window)
    assert [action.data()[1] for action in presets] == [PRESET_CLASSIC, PRESET_MIRRORED, PRESET_FILMSTRIP]
    assert all(action.isCheckable() for action in presets)
    assert [action.isChecked() for action in presets] == [True, False, False]

    presets[1].trigger()
    assert window._layout_document.preset == PRESET_MIRRORED
    assert [action.isChecked() for action in presets] == [False, True, False]


def test_tool_buttons_submenu_changes_the_rail_assembly(qtbot) -> None:
    window = _window(qtbot)
    modes = _tool_button_actions(window)
    assert [action.data()[1] for action in modes] == ["auto", "row", "rail", "panel"]
    assert [action.isChecked() for action in modes] == [True, False, False, False]
    by_mode = {action.data()[1]: action for action in modes}

    by_mode["rail"].trigger()
    assert window._layout_document.tool_buttons == "rail"
    assert window._activity_bar is not None
    assert window._content_layout.indexOf(window._activity_bar) >= 0

    by_mode["auto"].trigger()
    assert window._layout_document.tool_buttons == "auto"
    assert window._content_layout.indexOf(window._activity_bar) < 0
    assert window._tool_panel.isVisibleTo(window)


def test_row_and_panel_buttons_assemble_as_auto_until_pr3(qtbot) -> None:
    """Interim contract: ``row``/``panel`` are stored but render as ``auto``.

    UI-2 PR-3 builds the row over the image and the tools block of the panel;
    until then the assembly only knows the rail. This test is rewritten there.
    """
    window = _window(qtbot)
    by_mode = {action.data()[1]: action for action in _tool_button_actions(window)}
    expected = slot_plan(LayoutConfigV2(preset=PRESET_CLASSIC), multiview=False)
    for mode in ("row", "panel"):
        by_mode[mode].trigger()
        assert window._layout_document.tool_buttons == mode
        plan = slot_plan(window._layout_document, multiview=False)
        assert (plan.left, plan.center, plan.right, plan.bottom) == (
            expected.left,
            expected.center,
            expected.right,
            expected.bottom,
        )
        assert window._tool_panel.isVisibleTo(window)
        assert window._activity_bar is None or window._content_layout.indexOf(window._activity_bar) < 0


def test_open_logo_menu_syncs_preset_selection(qtbot) -> None:
    window = _window(qtbot)
    presets = {action.data()[1]: action for action in _preset_actions(window)}
    presets[PRESET_CLASSIC].setChecked(True)  # what the user sees before a change
    window._on_layout_preset_selected(PRESET_FILMSTRIP)
    assert presets[PRESET_FILMSTRIP].isChecked() is True
    assert presets[PRESET_CLASSIC].isChecked() is False


def test_configure_opens_the_settings_dialog(qtbot) -> None:
    from unittest.mock import patch

    window = _window(qtbot)
    configure = next(
        action
        for action in _layout_menu(window).actions()
        if isinstance(action.data(), tuple) and action.data()[0] == "configure"
    )
    with patch.object(window, "_show_user_preferences") as shown:
        configure.trigger()
    shown.assert_called_once_with()


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


def test_preset_switch_fits_the_300ms_budget(qtbot) -> None:
    """G-2: switching a preset rebuilds the window in under 300 ms, no restart."""
    window = _window(qtbot)
    rotation = [PRESET_MIRRORED, PRESET_FILMSTRIP, PRESET_CLASSIC]
    for preset in rotation:  # warm-up: build the rail and the bottom strip once
        window._on_layout_preset_selected(preset)
    QApplication.processEvents()
    for preset in rotation:
        started = perf_counter()
        window._on_layout_preset_selected(preset)
        QApplication.processEvents()
        elapsed_ms = (perf_counter() - started) * 1000.0
        assert elapsed_ms < 300, f"{preset}: {elapsed_ms:.1f} ms"
    assert window._layout_document.preset == PRESET_CLASSIC


def test_preset_switch_keeps_clip_and_measurements(qtbot) -> None:
    """G-2 (mechanism): widgets are reparented, never recreated; state stays.

    The gallery keeps its items and selection, the viewer and the tool panel
    keep their identity, and the controller snapshot (contours here) is
    untouched: the layout owns slots, not data. Clip/frame preservation with
    real media is the UA-04 manual acceptance.
    """
    from echo_personal_tool.domain.models import Contour

    window = _window(qtbot)
    _publish_one_study(window)
    contours = (Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 20)]),)
    window._controller.state_manager.set_contours(contours)
    gallery, viewer, tool_panel = window._gallery, window._viewer, window._tool_panel
    item_count, current_row = gallery.count(), gallery.currentRow()

    for preset in (PRESET_MIRRORED, PRESET_FILMSTRIP, PRESET_CLASSIC):
        window._on_layout_preset_selected(preset)
    QApplication.processEvents()

    assert window._gallery is gallery
    assert window._viewer is viewer
    assert window._tool_panel is tool_panel
    assert gallery.count() == item_count
    assert gallery.currentRow() == current_row
    assert window._controller.state_manager.snapshot.contours == contours
    assert window._has_loaded_study is True


def test_settings_apply_rebuilds_on_document_change(qtbot) -> None:
    window = _window(qtbot)
    assert window._layout_document.preset == PRESET_CLASSIC
    preferences = replace(
        window._user_preferences,
        layout_state_v2_json=LayoutConfigV2(preset=PRESET_FILMSTRIP).to_json(),
    )
    window._apply_user_preferences(preferences)
    QApplication.processEvents()
    assert window._layout_document.preset == PRESET_FILMSTRIP
    assert window._bottom_container is not None
    # An unchanged document is a no-op, not a rebuild.
    window._apply_user_preferences(preferences)
    assert window._layout_document.preset == PRESET_FILMSTRIP
