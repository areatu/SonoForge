"""Tests for constructor_dialog.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from echo_personal_tool.constructor.constructor_dialog import (
    ConstructorDialog,
    show_constructor_dialog,
)

pytestmark = pytest.mark.gui

_THEME = {
    "bg_dark": "#111827",
    "bg_panel": "#1a2332",
    "bg_control": "#243044",
    "bg_button": "#2e4054",
    "bg_button_hover": "#3a5068",
    "bg_button_pressed": "#1e2a38",
    "accent": "#9ca3b0",
    "accent_bright": "#b0b8c0",
    "accent_tab": "#3b82f6",
    "text": "#f1f5f9",
    "text_dim": "#94a3b8",
    "border": "#334155",
}


@pytest.fixture
def yaml_file(tmp_path: Path) -> Path:
    import yaml

    path = tmp_path / "test.yaml"
    data = {"topics": []}
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True)
    return path


@pytest.fixture
def dialog(qtbot, yaml_file) -> ConstructorDialog:
    with patch(
        "echo_personal_tool.constructor.constructor_dialog.get_theme_palette",
        return_value=_THEME,
    ):
        with patch(
            "echo_personal_tool.constructor.constructor_widget.get_theme_palette",
            return_value=_THEME,
        ):
            with patch(
                "echo_personal_tool.constructor.constructor_dialog._YAML_PATH",
                yaml_file,
            ):
                d = ConstructorDialog()
    qtbot.addWidget(d)
    return d


class TestConstructorDialogInit:
    def test_creation(self, dialog) -> None:
        assert dialog.windowTitle() == "Конструктор справочника"

    def test_dirty_label_initial(self, dialog) -> None:
        assert dialog._dirty_label.text() == ""

    def test_is_frameless(self, dialog) -> None:
        assert dialog.windowFlags() & 0x00000800  # FramelessWindowHint


class TestOnDirtyChanged:
    def test_dirty_true(self, dialog) -> None:
        dialog._on_dirty_changed(True)
        assert dialog._dirty_label.text() == "*"

    def test_dirty_false(self, dialog) -> None:
        dialog._on_dirty_changed(False)
        assert dialog._dirty_label.text() == ""


class TestToggleMaximize:
    def test_toggle_maximize(self, dialog) -> None:
        assert dialog._is_maximized is False
        dialog._toggle_maximize()
        assert dialog._is_maximized is True
        dialog._toggle_maximize()
        assert dialog._is_maximized is False

    def test_toggle_maximize_restores_geometry(self, dialog) -> None:
        dialog._normal_geometry = MagicMock()
        dialog._toggle_maximize()
        assert dialog._is_maximized is True
        dialog._toggle_maximize()
        assert dialog._is_maximized is False


class TestMinimize:
    def test_minimize(self, dialog) -> None:
        dialog.showMinimized = MagicMock()
        dialog._minimize()
        dialog.showMinimized.assert_called_once()


class TestClose:
    def test_close(self, dialog) -> None:
        dialog.close = MagicMock()
        dialog._close()
        dialog.close.assert_called_once()


class TestMouseEvents:
    def test_mouse_release(self, dialog) -> None:
        event = MagicMock()
        dialog._drag_pos = MagicMock()
        dialog.mouseReleaseEvent(event)
        assert dialog._drag_pos is None

    def test_mouse_double_click(self, dialog) -> None:
        event = MagicMock()
        dialog._is_maximized = False
        dialog._toggle_maximize = MagicMock()
        dialog.mouseDoubleClickEvent(event)
        dialog._toggle_maximize.assert_called_once()

    def test_mouse_move_no_drag(self, dialog) -> None:
        event = MagicMock()
        dialog._drag_pos = None
        dialog.move = MagicMock()
        dialog.mouseMoveEvent(event)
        dialog.move.assert_not_called()


class TestKeyEvent:
    def test_enter_key_ignored(self, dialog) -> None:
        event = MagicMock()
        event.key.return_value = 0x01000005  # Qt.Key.Key_Return
        focused = MagicMock()
        focused.__class__ = MagicMock
        dialog.focusWidget = MagicMock(return_value=focused)
        dialog.keyPressEvent(event)

    def test_enter_key_in_line_edit(self, dialog) -> None:
        from PySide6.QtWidgets import QLineEdit

        event = MagicMock()
        event.key.return_value = 0x01000005  # Key_Return
        focused = MagicMock(spec=QLineEdit)
        dialog.focusWidget = MagicMock(return_value=focused)
        with patch("PySide6.QtWidgets.QDialog.keyPressEvent"):
            dialog.keyPressEvent(event)

    def test_non_enter_key_passes_through(self, dialog) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeyEvent

        event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier)
        dialog.keyPressEvent(event)


class TestConstructorWidgetInteraction:
    def test_mark_dirty_through_widget(self, dialog) -> None:
        dialog._constructor_widget._mark_dirty()
        assert dialog._dirty_label.text() == "*"

    def test_clear_dirty_through_widget(self, dialog) -> None:
        dialog._constructor_widget._mark_dirty()
        dialog._constructor_widget._clear_dirty()
        assert dialog._dirty_label.text() == ""


class TestShowConstructorDialog:
    @patch("echo_personal_tool.constructor.constructor_dialog.QMessageBox")
    def test_show_dialog_error(self, mock_msgbox) -> None:
        with patch(
            "echo_personal_tool.constructor.constructor_dialog.ConstructorDialog",
            side_effect=Exception("test error"),
        ):
            show_constructor_dialog(None)
            mock_msgbox.critical.assert_called_once()
