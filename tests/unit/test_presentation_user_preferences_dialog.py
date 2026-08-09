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
    def test_creates_with_tabs(self, mock_load):
        mock_load.return_value = _default_prefs()
        from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

        dlg = UserPreferencesDialog()
        assert dlg._tabs is not None
        assert (
            dlg._tabs.count() >= 5
        )  # interface(+display block), measurement, other(+gold/dicom/refs blocks), experimental, server

    @patch("echo_personal_tool.presentation.user_preferences_dialog.load_user_preferences")
    def test_theme_combo_populated(self, mock_load):
        mock_load.return_value = _default_prefs()
        from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

        dlg = UserPreferencesDialog()
        assert dlg._theme_combo.count() == 5

    @patch("echo_personal_tool.presentation.user_preferences_dialog.load_user_preferences")
    def test_language_combo_populated(self, mock_load):
        mock_load.return_value = _default_prefs()
        from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

        dlg = UserPreferencesDialog()
        assert dlg._language_combo.count() == 2


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
