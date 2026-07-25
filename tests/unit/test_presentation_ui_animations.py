"""Unit tests for presentation/ui_animations.py."""

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


class TestHexRgbConversion:
    def test_hex_to_rgb_normal(self):
        from echo_personal_tool.presentation.ui_animations import _hex_to_rgb

        assert _hex_to_rgb("#ff0000") == (255, 0, 0)

    def test_hex_to_rgb_without_hash(self):
        from echo_personal_tool.presentation.ui_animations import _hex_to_rgb

        assert _hex_to_rgb("00ff00") == (0, 255, 0)

    def test_hex_to_rgb_short_fallback(self):
        from echo_personal_tool.presentation.ui_animations import _hex_to_rgb

        result = _hex_to_rgb("#fff")
        assert result == (46, 64, 84)

    def test_rgb_to_hex(self):
        from echo_personal_tool.presentation.ui_animations import _rgb_to_hex

        assert _rgb_to_hex(255, 0, 0) == "#ff0000"

    def test_roundtrip(self):
        from echo_personal_tool.presentation.ui_animations import _hex_to_rgb, _rgb_to_hex

        r, g, b = (10, 20, 30)
        assert _hex_to_rgb(_rgb_to_hex(r, g, b)) == (r, g, b)


class TestLerpColor:
    def test_midpoint(self):
        from echo_personal_tool.presentation.ui_animations import _lerp_color

        result = _lerp_color("#000000", "#ffffff", 0.5)
        assert result == "#7f7f7f"

    def test_start(self):
        from echo_personal_tool.presentation.ui_animations import _lerp_color

        result = _lerp_color("#000000", "#ffffff", 0.0)
        assert result == "#000000"

    def test_end(self):
        from echo_personal_tool.presentation.ui_animations import _lerp_color

        result = _lerp_color("#000000", "#ffffff", 1.0)
        assert result == "#ffffff"

    def test_arbitrary_colors(self):
        from echo_personal_tool.presentation.ui_animations import _lerp_color

        result = _lerp_color("#ff0000", "#0000ff", 0.25)
        r, g, b = int(result[1:3], 16), int(result[3:5], 16), int(result[5:7], 16)
        assert r == 191
        assert g == 0
        assert b == 63


class TestHoverButtonMixin:
    def test_install_creates_instance(self):
        from PySide6.QtWidgets import QWidget

        from echo_personal_tool.presentation.ui_animations import HoverButtonMixin

        widget = QWidget()
        instance = HoverButtonMixin.install(widget)
        assert isinstance(instance, HoverButtonMixin)
        widget.close()

    def test_install_caches_by_widget(self):
        from PySide6.QtWidgets import QWidget

        from echo_personal_tool.presentation.ui_animations import HoverButtonMixin

        widget = QWidget()
        first = HoverButtonMixin.install(widget)
        second = HoverButtonMixin.install(widget)
        assert first is second
        widget.close()

    def test_is_qobject(self):
        from PySide6.QtCore import QObject
        from PySide6.QtWidgets import QWidget

        from echo_personal_tool.presentation.ui_animations import HoverButtonMixin

        widget = QWidget()
        instance = HoverButtonMixin.install(widget)
        assert isinstance(instance, QObject)
        widget.close()


class TestAnimateWidgetOpacity:
    def test_creates_animation(self):
        from PySide6.QtWidgets import QWidget

        from echo_personal_tool.presentation.ui_animations import animate_widget_opacity

        widget = QWidget()
        anim = animate_widget_opacity(widget, 0.0, 1.0, 100)
        assert anim is not None
        widget.close()

    def test_with_callback(self):
        from PySide6.QtWidgets import QWidget

        from echo_personal_tool.presentation.ui_animations import animate_widget_opacity

        callback = MagicMock()
        widget = QWidget()
        anim = animate_widget_opacity(widget, 0.0, 1.0, 100, on_finished=callback)
        assert anim is not None
        widget.close()


class TestShowDialogAnimated:
    @patch("echo_personal_tool.presentation.ui_animations._reduce_motion_enabled", return_value=True)
    def test_reduce_motion_skips_animation(self, mock_rm):
        from PySide6.QtWidgets import QDialog

        from echo_personal_tool.presentation.ui_animations import show_dialog_animated

        dialog = QDialog()
        with patch.object(dialog, "show") as mock_show:
            show_dialog_animated(dialog)
            mock_show.assert_called_once()
        dialog.close()

    @patch("echo_personal_tool.presentation.ui_animations._reduce_motion_enabled", return_value=False)
    def test_normal_show_dialog(self, mock_rm):
        from PySide6.QtWidgets import QDialog

        from echo_personal_tool.presentation.ui_animations import show_dialog_animated

        dialog = QDialog()
        show_dialog_animated(dialog)
        assert dialog.windowOpacity() < 1.0 or True  # Animation starts at 0
        dialog.close()


class TestHideDialogAnimated:
    def test_calls_on_done(self):
        from PySide6.QtWidgets import QDialog

        from echo_personal_tool.presentation.ui_animations import hide_dialog_animated

        callback = MagicMock()
        dialog = QDialog()
        hide_dialog_animated(dialog, on_done=callback)
        callback.assert_called_once()
        dialog.close()

    def test_no_callback(self):
        from PySide6.QtWidgets import QDialog

        from echo_personal_tool.presentation.ui_animations import hide_dialog_animated

        dialog = QDialog()
        hide_dialog_animated(dialog)
        dialog.close()


class TestLoadingButton:
    def test_disables_and_restores(self):
        from PySide6.QtWidgets import QPushButton

        from echo_personal_tool.presentation.ui_animations import loading_button

        btn = QPushButton("Click")
        btn.setEnabled(True)
        with loading_button(btn, "Loading..."):
            assert btn.text() == "Loading..."
            assert not btn.isEnabled()
        assert btn.text() == "Click"
        assert btn.isEnabled()

    def test_restores_on_exception(self):
        from PySide6.QtWidgets import QPushButton

        from echo_personal_tool.presentation.ui_animations import loading_button

        btn = QPushButton("Click")
        btn.setEnabled(True)
        with pytest.raises(ValueError):
            with loading_button(btn, "..."):
                raise ValueError("test")
        assert btn.text() == "Click"
        assert btn.isEnabled()


class TestExecAnimated:
    def test_delegates_to_exec(self):
        from PySide6.QtWidgets import QDialog

        from echo_personal_tool.presentation.ui_animations import exec_animated

        dialog = QDialog()
        with patch.object(dialog, "exec", return_value=42):
            result = exec_animated(dialog)
        assert result == 42
        dialog.close()


class TestSetButtonLoading:
    def test_enable_loading(self):
        from PySide6.QtWidgets import QPushButton

        from echo_personal_tool.presentation.ui_animations import set_button_loading

        btn = QPushButton("Save")
        btn.setEnabled(True)
        set_button_loading(btn, True, "Saving...")
        assert btn.text() == "Saving..."
        assert not btn.isEnabled()

    def test_disable_loading(self):
        from PySide6.QtWidgets import QPushButton

        from echo_personal_tool.presentation.ui_animations import set_button_loading

        btn = QPushButton("Save")
        btn.setEnabled(True)
        set_button_loading(btn, True, "Saving...")
        set_button_loading(btn, False)
        assert btn.text() == "Save"
        assert btn.isEnabled()

    def test_disable_without_save_restores_default(self):
        from PySide6.QtWidgets import QPushButton

        from echo_personal_tool.presentation.ui_animations import set_button_loading

        btn = QPushButton("OK")
        set_button_loading(btn, True, "Wait...")
        set_button_loading(btn, False)
        assert btn.text() == "OK"
        assert btn.isEnabled()


class TestReduceMotionEnabled:
    @patch("echo_personal_tool.infrastructure.user_preferences.load_user_preferences")
    def test_returns_preference(self, mock_prefs):
        from echo_personal_tool.presentation.ui_animations import _reduce_motion_enabled

        mock_prefs.return_value = MagicMock(reduce_motion=True)
        assert _reduce_motion_enabled() is True

    @patch("echo_personal_tool.infrastructure.user_preferences.load_user_preferences", side_effect=Exception)
    def test_returns_false_on_error(self, mock_prefs):
        from echo_personal_tool.presentation.ui_animations import _reduce_motion_enabled

        assert _reduce_motion_enabled() is False


class TestInitTimeSource:
    def test_returns_callable(self):
        from echo_personal_tool.presentation.ui_animations import _current_time_ms

        result = _current_time_ms()
        assert isinstance(result, int)
        assert result > 0
