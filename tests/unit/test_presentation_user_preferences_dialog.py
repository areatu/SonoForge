"""Unit tests for presentation/user_preferences_dialog.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def _setup_qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def _default_prefs():
    from echo_personal_tool.infrastructure.user_preferences import default_user_preferences

    return default_user_preferences()


class TestUserPreferencesDialogConstruction:
    @patch("echo_personal_tool.presentation.user_preferences_dialog.load_user_preferences")
    def test_creates_with_section_sidebar(self, mock_load):
        """The mock 07-settings-layout.png: a section list, one page each."""
        mock_load.return_value = _default_prefs()
        from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

        dlg = UserPreferencesDialog()
        # Every row of the sidebar has a page in the stack.
        assert dlg._section_list.count() >= 5
        assert dlg._stack.count() == dlg._section_list.count()
        assert dlg._section_list.currentRow() == 0
        assert dlg._stack.currentIndex() == 0
        # The sections the old tab widget carried are all still reachable.
        for key in (
            "settings_section_general",
            "settings_section_tools",
            "settings_section_measurements",
            "settings_section_server",
        ):
            assert key in dlg._pages

    @patch("echo_personal_tool.presentation.user_preferences_dialog.load_user_preferences")
    def test_initial_tab_tools(self, mock_load):
        mock_load.return_value = _default_prefs()
        from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

        dlg = UserPreferencesDialog(initial_tab="tools")
        assert dlg._pages["settings_section_tools"].isAncestorOf(dlg._tool_panel_settings)
        current = dlg._section_list.currentItem()
        assert current is not None
        assert current.data(0x0100) == "settings_section_tools"

    @patch("echo_personal_tool.presentation.user_preferences_dialog.load_user_preferences")
    def test_theme_combo_populated(self, mock_load):
        mock_load.return_value = _default_prefs()
        from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

        dlg = UserPreferencesDialog()
        # dark, light, VS Code dark, VS Code light, Graphite, system
        assert dlg._theme_combo.count() == 6
        assert dlg._theme_combo.findData("graphite") >= 0

    @patch("echo_personal_tool.presentation.user_preferences_dialog.load_user_preferences")
    def test_language_combo_populated(self, mock_load):
        mock_load.return_value = _default_prefs()
        from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

        dlg = UserPreferencesDialog()
        assert dlg._language_combo.count() == 2

    @patch("echo_personal_tool.presentation.user_preferences_dialog.load_user_preferences")
    def test_display_section_has_no_wl_preset(self, mock_load):
        mock_load.return_value = _default_prefs()
        from PySide6.QtWidgets import QLabel

        from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

        dlg = UserPreferencesDialog()
        assert not hasattr(dlg, "_wl_preset")
        labels = [label.text() for label in dlg.findChildren(QLabel)]
        assert "tool_panel.wl_preset" not in labels
        assert "W/L preset:" not in labels
        assert "Пресет W/L:" not in labels


class TestUserPreferencesDialogValues:
    @patch("echo_personal_tool.presentation.user_preferences_dialog.load_user_preferences")
    def test_ui_font_size_set(self, mock_load):
        prefs = _default_prefs()
        prefs.ui_font_size = 16
        mock_load.return_value = prefs
        from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

        dlg = UserPreferencesDialog()
        assert dlg._font_spin.value() == 16

    @patch("echo_personal_tool.presentation.user_preferences_dialog.load_user_preferences")
    def test_playback_speed_set(self, mock_load):
        prefs = _default_prefs()
        prefs.playback_speed_multiplier = 2.0
        mock_load.return_value = prefs
        from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

        dlg = UserPreferencesDialog()
        assert dlg._playback_spin.value() == 2.0

    @patch("echo_personal_tool.presentation.user_preferences_dialog.load_user_preferences")
    def test_crosshair_checkbox(self, mock_load):
        prefs = _default_prefs()
        prefs.show_crosshair = False
        mock_load.return_value = prefs
        from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

        dlg = UserPreferencesDialog()
        assert not dlg._show_crosshair.isChecked()

    @patch("echo_personal_tool.presentation.user_preferences_dialog.load_user_preferences")
    def test_doppler_cal_roi_checkbox_default_off(self, mock_load):
        mock_load.return_value = _default_prefs()
        from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

        dlg = UserPreferencesDialog()
        assert not dlg._show_doppler_cal_roi.isChecked()

    @patch("echo_personal_tool.presentation.user_preferences_dialog.load_user_preferences")
    def test_doppler_cal_roi_checkbox_checked(self, mock_load):
        prefs = _default_prefs()
        prefs.show_doppler_calibration_roi = True
        mock_load.return_value = prefs
        from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

        dlg = UserPreferencesDialog()
        assert dlg._show_doppler_cal_roi.isChecked()


class TestOnAccept:
    @patch("echo_personal_tool.presentation.user_preferences_dialog.save_server_settings")
    @patch("echo_personal_tool.presentation.user_preferences_dialog.save_user_preferences")
    @patch("echo_personal_tool.presentation.user_preferences_dialog.load_user_preferences")
    def test_accept_saves_preferences(self, mock_load, mock_save_pref, mock_save_srv):
        mock_load.return_value = _default_prefs()
        from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

        dlg = UserPreferencesDialog()
        with patch.object(dlg, "accept") as mock_accept:
            dlg._on_accept()
            mock_save_pref.assert_called_once()
            mock_save_srv.assert_called_once()
            mock_accept.assert_called_once()

    @patch("echo_personal_tool.presentation.user_preferences_dialog.save_server_settings")
    @patch("echo_personal_tool.presentation.user_preferences_dialog.save_user_preferences")
    @patch("echo_personal_tool.presentation.user_preferences_dialog.load_user_preferences")
    def test_on_apply_callback_invoked(self, mock_load, mock_save_pref, mock_save_srv):
        mock_load.return_value = _default_prefs()
        callback = MagicMock()
        from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

        dlg = UserPreferencesDialog(on_apply=callback)
        with patch.object(dlg, "accept"):
            dlg._on_accept()
            callback.assert_called_once()

    @patch("echo_personal_tool.presentation.user_preferences_dialog.save_server_settings")
    @patch("echo_personal_tool.presentation.user_preferences_dialog.save_user_preferences")
    @patch("echo_personal_tool.presentation.user_preferences_dialog.load_user_preferences")
    def test_on_apply_none_no_error(self, mock_load, mock_save_pref, mock_save_srv):
        mock_load.return_value = _default_prefs()
        from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

        dlg = UserPreferencesDialog(on_apply=None)
        with patch.object(dlg, "accept"):
            dlg._on_accept()  # Should not raise


class TestResetToDefaults:
    @patch("echo_personal_tool.presentation.user_preferences_dialog.save_user_preferences")
    @patch("echo_personal_tool.presentation.user_preferences_dialog.load_user_preferences")
    @patch(
        "echo_personal_tool.presentation.user_preferences_dialog.QMessageBox.question",
        return_value=0x00004000,  # Yes
    )
    def test_confirm_reset_applies_defaults(self, mock_question, mock_load, mock_save):
        mock_load.return_value = _default_prefs()
        from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

        dlg = UserPreferencesDialog()
        with patch.object(dlg, "accept") as mock_accept:
            dlg._reset_to_defaults()
            mock_save.assert_called_once()
            mock_accept.assert_called_once()

    @patch("echo_personal_tool.presentation.user_preferences_dialog.load_user_preferences")
    @patch(
        "echo_personal_tool.presentation.user_preferences_dialog.QMessageBox.question",
        return_value=0x00000400,  # No
    )
    def test_cancel_reset_does_nothing(self, mock_question, mock_load):
        mock_load.return_value = _default_prefs()
        from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

        dlg = UserPreferencesDialog()
        with patch("echo_personal_tool.presentation.user_preferences_dialog.save_user_preferences") as mock_save:
            dlg._reset_to_defaults()
            mock_save.assert_not_called()


class TestMouseDrag:
    @patch("echo_personal_tool.presentation.user_preferences_dialog.load_user_preferences")
    def test_mouse_press_sets_drag_pos(self, mock_load):
        mock_load.return_value = _default_prefs()
        from PySide6.QtCore import QEvent, QPoint, Qt
        from PySide6.QtGui import QMouseEvent

        from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

        dlg = UserPreferencesDialog()
        event = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPoint(10, 10),
            QPoint(10, 10),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        dlg.mousePressEvent(event)
        assert dlg._drag_pos is not None

    @patch("echo_personal_tool.presentation.user_preferences_dialog.load_user_preferences")
    def test_mouse_release_clears_drag_pos(self, mock_load):
        mock_load.return_value = _default_prefs()
        from PySide6.QtCore import QEvent, QPoint, Qt
        from PySide6.QtGui import QMouseEvent

        from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

        dlg = UserPreferencesDialog()
        dlg._drag_pos = QPoint(5, 5)
        event = QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            QPoint(10, 10),
            QPoint(10, 10),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        dlg.mouseReleaseEvent(event)
        assert dlg._drag_pos is None


class TestAreaToolModeCombo:
    @patch("echo_personal_tool.presentation.user_preferences_dialog.load_user_preferences")
    def test_combo_exists(self, mock_load):
        mock_load.return_value = _default_prefs()
        from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

        dlg = UserPreferencesDialog()
        assert hasattr(dlg, "_area_tool_mode_combo")

    @patch("echo_personal_tool.presentation.user_preferences_dialog.load_user_preferences")
    def test_combo_has_two_items(self, mock_load):
        mock_load.return_value = _default_prefs()
        from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

        dlg = UserPreferencesDialog()
        assert dlg._area_tool_mode_combo.count() == 2

    @patch("echo_personal_tool.presentation.user_preferences_dialog.load_user_preferences")
    def test_combo_defaults_to_click(self, mock_load):
        mock_load.return_value = _default_prefs()
        from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

        dlg = UserPreferencesDialog()
        assert dlg._area_tool_mode_combo.currentData() == "click"

    @patch("echo_personal_tool.presentation.user_preferences_dialog.load_user_preferences")
    def test_combo_selects_freehand_when_prefs_set(self, mock_load):
        prefs = _default_prefs()
        prefs.area_tool_mode = "freehand"
        mock_load.return_value = prefs
        from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

        dlg = UserPreferencesDialog()
        assert dlg._area_tool_mode_combo.currentData() == "freehand"

    @patch("echo_personal_tool.presentation.user_preferences_dialog.save_server_settings")
    @patch("echo_personal_tool.presentation.user_preferences_dialog.save_user_preferences")
    @patch("echo_personal_tool.presentation.user_preferences_dialog.load_user_preferences")
    def test_on_accept_saves_area_tool_mode(self, mock_load, mock_save_pref, mock_save_srv):
        mock_load.return_value = _default_prefs()
        from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

        dlg = UserPreferencesDialog()
        dlg._area_tool_mode_combo.setCurrentIndex(1)  # freehand
        with patch.object(dlg, "accept"):
            dlg._on_accept()
            saved_prefs = mock_save_pref.call_args[0][0]
            assert saved_prefs.area_tool_mode == "freehand"

    @patch("echo_personal_tool.presentation.user_preferences_dialog.save_server_settings")
    @patch("echo_personal_tool.presentation.user_preferences_dialog.save_user_preferences")
    @patch("echo_personal_tool.presentation.user_preferences_dialog.load_user_preferences")
    def test_on_accept_saves_doppler_cal_roi(self, mock_load, mock_save_pref, mock_save_srv):
        mock_load.return_value = _default_prefs()
        from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

        dlg = UserPreferencesDialog()
        dlg._show_doppler_cal_roi.setChecked(True)
        with patch.object(dlg, "accept"):
            dlg._on_accept()
            saved_prefs = mock_save_pref.call_args[0][0]
            assert saved_prefs.show_doppler_calibration_roi is True


class TestManagedCacheSettings:
    @patch("echo_personal_tool.presentation.user_preferences_dialog.load_user_preferences")
    def test_cache_controls_show_location_size_and_default_cleanup(self, mock_load, tmp_path):
        mock_load.return_value = _default_prefs()
        from echo_personal_tool.infrastructure.orthanc_cache import OrthancSessionCache
        from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

        cache = OrthancSessionCache(tmp_path)
        session = cache.create_session()
        (cache.session_path(session) / "sample.dcm").write_bytes(b"DICM")
        dlg = UserPreferencesDialog(orthanc_cache=cache)

        assert dlg._cache_location_label.text() == str(tmp_path)
        assert dlg._cache_size_label.text() == "4 B"
        assert dlg._cache_quota_label.text() == "20.0 GiB"
        assert dlg._cache_clear_on_exit.isChecked() is True

    @patch("echo_personal_tool.presentation.user_preferences_dialog.save_server_settings")
    @patch("echo_personal_tool.presentation.user_preferences_dialog.save_user_preferences")
    @patch("echo_personal_tool.presentation.user_preferences_dialog.load_user_preferences")
    def test_cache_cleanup_preference_is_saved(self, mock_load, mock_save, mock_save_server):
        mock_load.return_value = _default_prefs()
        from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

        dlg = UserPreferencesDialog()
        dlg._cache_clear_on_exit.setChecked(False)
        with patch.object(dlg, "accept"):
            dlg._on_accept()
        saved = mock_save.call_args[0][0]
        assert saved.orthanc_cache_clear_on_exit is False

    @patch("echo_personal_tool.presentation.user_preferences_dialog.QMessageBox.information")
    @patch("echo_personal_tool.presentation.user_preferences_dialog.load_user_preferences")
    def test_clear_cache_preserves_open_study_sessions(self, mock_load, mock_information, tmp_path):
        mock_load.return_value = _default_prefs()
        from PySide6.QtWidgets import QMessageBox

        from echo_personal_tool.infrastructure.orthanc_cache import OrthancSessionCache
        from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

        cache = OrthancSessionCache(tmp_path)
        active = cache.create_session()
        inactive = cache.create_session()
        (cache.session_path(active) / "active.dcm").write_bytes(b"active")
        (cache.session_path(inactive) / "inactive.dcm").write_bytes(b"inactive")
        dlg = UserPreferencesDialog(
            orthanc_cache=cache,
            protected_cache_sessions=lambda: {active},
        )

        with patch(
            "echo_personal_tool.presentation.user_preferences_dialog.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ) as mock_question:
            dlg._clear_cache()

        mock_question.assert_called_once()
        assert cache.session_path(active).is_dir()
        assert not cache.session_path(inactive).exists()
        assert dlg._cache_size_label.text() == "6 B"
        mock_information.assert_called_once()


class TestShowUserPreferencesDialog:
    @patch("echo_personal_tool.presentation.ui_animations.exec_animated", return_value=0)
    @patch("echo_personal_tool.presentation.user_preferences_dialog.load_user_preferences")
    def test_returns_false_when_rejected(self, mock_load, mock_exec):
        mock_load.return_value = _default_prefs()
        from echo_personal_tool.presentation.user_preferences_dialog import show_user_preferences_dialog

        result = show_user_preferences_dialog()
        assert result is False

    @patch("echo_personal_tool.presentation.ui_animations.exec_animated", return_value=1)
    @patch("echo_personal_tool.presentation.user_preferences_dialog.load_user_preferences")
    def test_returns_true_when_accepted(self, mock_load, mock_exec):
        mock_load.return_value = _default_prefs()
        from echo_personal_tool.presentation.user_preferences_dialog import show_user_preferences_dialog

        result = show_user_preferences_dialog()
        assert result is True


class TestMeasurementPersistenceCheckboxSync:
    """The manager may rewrite the stored autosave preference (delete-all);
    a pending checkbox edit must survive a plain open/close of the manager."""

    @patch("echo_personal_tool.presentation.user_preferences_dialog.load_user_preferences")
    def test_manager_without_preference_change_keeps_pending_checkbox(self, mock_load):
        prefs = _default_prefs()
        prefs.measurement_persistence_enabled = False
        mock_load.return_value = prefs
        from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

        dlg = UserPreferencesDialog(measurement_storage_action=lambda: False)
        dlg._persist_measurements.setChecked(True)  # pending user edit, not yet applied
        dlg._measurement_manage.click()
        assert dlg._persist_measurements.isChecked()

    @patch("echo_personal_tool.presentation.user_preferences_dialog.load_user_preferences")
    def test_manager_delete_all_resets_checkbox_from_disk(self, mock_load):
        prefs = _default_prefs()
        prefs.measurement_persistence_enabled = False  # delete-all already rewrote disk
        mock_load.return_value = prefs
        from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

        def delete_all_action():
            return True

        dlg = UserPreferencesDialog(measurement_storage_action=delete_all_action)
        dlg._persist_measurements.setChecked(True)
        dlg._measurement_manage.click()
        assert not dlg._persist_measurements.isChecked()


@pytest.mark.parametrize("initial", [True, False])
def test_tabs_checkbox_first_interface_row_and_saved(qtbot, initial):
    from PySide6.QtWidgets import QFormLayout

    from echo_personal_tool.infrastructure.user_preferences import load_user_preferences, save_user_preferences
    from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

    preferences = _default_prefs()
    preferences.tabs_enabled = initial
    save_user_preferences(preferences)
    applied = []
    dlg = UserPreferencesDialog(on_apply=applied.append)
    qtbot.addWidget(dlg)
    box = dlg._tabs_enabled
    assert box.isChecked() is initial
    assert dlg._pages["settings_section_general"].isAncestorOf(box)
    form = next(form for form in dlg.findChildren(QFormLayout) if form.indexOf(box) >= 0)
    assert form.getWidgetPosition(box)[0] == 0
    box.setChecked(not initial)
    with patch("echo_personal_tool.presentation.user_preferences_dialog.save_server_settings"):
        dlg._on_accept()
    assert load_user_preferences().tabs_enabled is (not initial)
    assert applied[0].tabs_enabled is (not initial)


@pytest.mark.parametrize("initial", [False, True])
def test_native_window_frame_checkbox_on_interface_tab_and_saved(qtbot, initial: bool):
    from echo_personal_tool.infrastructure.user_preferences import load_user_preferences, save_user_preferences
    from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

    preferences = _default_prefs()
    preferences.native_window_frame = initial
    save_user_preferences(preferences)
    applied = []
    dlg = UserPreferencesDialog(on_apply=applied.append)
    qtbot.addWidget(dlg)
    box = dlg._native_window_frame
    assert box.isChecked() is initial
    assert dlg._pages["settings_section_general"].isAncestorOf(box)
    box.setChecked(not initial)
    with patch("echo_personal_tool.presentation.user_preferences_dialog.save_server_settings"):
        dlg._on_accept()
    assert load_user_preferences().native_window_frame is (not initial)
    assert applied[0].native_window_frame is (not initial)


class TestToolSectionsInDialog:
    @patch("echo_personal_tool.presentation.user_preferences_dialog.save_server_settings")
    @patch("echo_personal_tool.presentation.user_preferences_dialog.save_user_preferences")
    @patch("echo_personal_tool.presentation.user_preferences_dialog.load_user_preferences")
    def test_add_button_creates_section_saved_in_layout(self, mock_load, mock_save_pref, mock_save_srv):
        import json

        mock_load.return_value = _default_prefs()
        from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

        dlg = UserPreferencesDialog()
        dlg._tool_panel_settings.duplicate_profile("Моя эхо")
        dlg._tool_panel_settings.add_custom_section("Мои")
        with patch.object(dlg, "accept"):
            dlg._on_accept()

        saved = mock_save_pref.call_args.args[0]
        # TP-5: the 2.0 editor writes version 3 only; the legacy key is kept.
        assert saved.tool_panel_layout_json == _default_prefs().tool_panel_layout_json
        data = json.loads(saved.tool_layout_v3_json)
        titles = [
            section["title"]
            for profile in data["profiles"]
            for context in profile["contexts"].values()
            for section in context["sections"]
            if section["key"].startswith("custom.")
        ]
        assert "Мои" in titles

    @patch("echo_personal_tool.presentation.user_preferences_dialog.save_server_settings")
    @patch("echo_personal_tool.presentation.user_preferences_dialog.save_user_preferences")
    @patch("echo_personal_tool.presentation.user_preferences_dialog.load_user_preferences")
    def test_version_three_layout_goes_to_its_own_key(self, mock_load, mock_save_pref, mock_save_srv):
        """TP-0 PR-2: version 3 is a new key; version 2 stays as it is."""
        import json

        mock_load.return_value = _default_prefs()
        from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

        dlg = UserPreferencesDialog()
        with patch.object(dlg, "accept"):
            dlg._on_accept()

        saved = mock_save_pref.call_args.args[0]
        assert saved.tool_panel_layout_json == _default_prefs().tool_panel_layout_json
        v3 = json.loads(saved.tool_layout_v3_json)
        assert v3["version"] == 3
        assert v3["profiles"][0]["id"] == "builtin.adult_echo"

    @patch("echo_personal_tool.presentation.user_preferences_dialog.save_server_settings")
    @patch("echo_personal_tool.presentation.user_preferences_dialog.save_user_preferences")
    @patch("echo_personal_tool.presentation.user_preferences_dialog.load_user_preferences")
    def test_label_picker_checkbox_saves_preference(self, mock_load, mock_save_pref, mock_save_srv):
        mock_load.return_value = _default_prefs()
        from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

        dlg = UserPreferencesDialog()
        assert dlg._label_picker_enabled.isChecked() is True
        dlg._label_picker_enabled.setChecked(False)
        with patch.object(dlg, "accept"):
            dlg._on_accept()

        saved = mock_save_pref.call_args.args[0]
        assert saved.label_picker_enabled is False


def test_the_section_reset_touches_only_the_shown_section(qtbot):
    """«Сбросить раздел» must undo the visible page and nothing else.

    The button used to be a no-op placeholder, which is worse than having no
    button at all: it promised an undo and delivered nothing. It now rebuilds
    the pages from «defaults for this section, the screen for the rest».
    """
    from dataclasses import replace

    from PySide6.QtWidgets import QMessageBox

    from echo_personal_tool.infrastructure.user_preferences import (
        default_user_preferences,
        load_user_preferences,
        save_user_preferences,
    )
    from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

    base = default_user_preferences()
    edited = replace(
        base,
        ui_font_size=base.ui_font_size + 4,
        caliper_line_width=base.caliper_line_width + 2.0,
        pdf_font_size=base.pdf_font_size + 3,
    )
    save_user_preferences(edited)
    dlg = UserPreferencesDialog()
    qtbot.addWidget(dlg)

    # The button asks before it throws the section away.
    with patch(
        "echo_personal_tool.presentation.user_preferences_dialog.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    ):
        # On General: the font size goes back to the default…
        dlg._section_list.setCurrentRow(0)
        qtbot.wait(10)
        dlg._reset_current_section()
    qtbot.wait(10)
    collected = dlg._collect_preferences(load_user_preferences())
    assert collected.ui_font_size == base.ui_font_size
    # …while the other sections keep the edits of this session.
    assert collected.caliper_line_width == edited.caliper_line_width
    assert collected.pdf_font_size == edited.pdf_font_size

    with patch(
        "echo_personal_tool.presentation.user_preferences_dialog.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    ):
        # On Report: only the report fields move.
        dlg._section_list.setCurrentRow(5)
        qtbot.wait(10)
        dlg._reset_current_section()
    qtbot.wait(10)
    collected = dlg._collect_preferences(load_user_preferences())
    assert collected.pdf_font_size == base.pdf_font_size
    assert collected.caliper_line_width == edited.caliper_line_width
    assert collected.ui_font_size == base.ui_font_size


def test_every_section_page_is_a_card_of_named_rows(qtbot):
    """The mock: one rounded card per section, every row a name over a hint.

    The pages used to be a flat list of right-aligned labels, which read as a
    spreadsheet rather than as settings. What this pins is the *shape* the mock
    asks for: a card per page, the label column left-aligned, and the control's
    own hint repeated under the name so a row explains itself.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QFormLayout, QFrame, QLabel

    from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

    dlg = UserPreferencesDialog()
    qtbot.addWidget(dlg)

    cards = dlg.findChildren(QFrame, "settingsCard")
    assert len(cards) == dlg._stack.count()

    forms = [form for card in cards for form in card.findChildren(QFormLayout)]
    assert forms, "no settings form on any card"
    for form in forms:
        assert form.labelAlignment() & Qt.AlignmentFlag.AlignLeft

    # A row whose control carries a hint shows it under the name; the name
    # itself stays first, unwrapped, so the row can still be scanned.
    hint = dlg._ui_scale.toolTip().strip()
    assert hint
    labels = [label.text() for label in dlg.findChildren(QLabel)]
    assert any(hint in text and text.startswith("<span") for text in labels)
