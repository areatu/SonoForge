"""Helper functions for styled dialogs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QFileDialog, QWidget

from echo_personal_tool.presentation.echopac_theme import get_theme_palette


def styled_open_file(
    parent: QWidget | None = None,
    title: str = "Открыть файл",
    directory: str = "",
    filter: str = "Все файлы (*)",
) -> tuple[str, str]:
    """Open file dialog with dark theme styling."""
    dialog = QFileDialog(parent, title, directory, filter)
    _style_dialog(dialog)
    if dialog.exec() == QFileDialog.DialogCode.Accepted:
        files = dialog.selectedFiles()
        return (files[0], dialog.selectedNameFilter()) if files else ("", "")
    return ("", "")


def styled_open_files(
    parent: QWidget | None = None,
    title: str = "Открыть файлы",
    directory: str = "",
    filter: str = "Все файлы (*)",
) -> list[str]:
    """Open multiple files dialog with dark theme styling."""
    dialog = QFileDialog(parent, title, directory, filter)
    dialog.setFileMode(QFileDialog.FileMode.ExistingFiles)
    _style_dialog(dialog)
    if dialog.exec() == QFileDialog.DialogCode.Accepted:
        return dialog.selectedFiles()
    return []


def styled_save_file(
    parent: QWidget | None = None,
    title: str = "Сохранить файл",
    directory: str = "",
    filter: str = "Все файлы (*)",
) -> tuple[str, str]:
    """Save file dialog with dark theme styling."""
    dialog = QFileDialog(parent, title, directory, filter)
    dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
    _style_dialog(dialog)
    if dialog.exec() == QFileDialog.DialogCode.Accepted:
        files = dialog.selectedFiles()
        return (files[0], dialog.selectedNameFilter()) if files else ("", "")
    return ("", "")


def styled_select_directory(
    parent: QWidget | None = None,
    title: str = "Выберите папку",
    directory: str = "",
) -> str:
    """Select directory dialog with dark theme styling."""
    dialog = QFileDialog(parent, title, directory)
    dialog.setFileMode(QFileDialog.FileMode.Directory)
    _style_dialog(dialog)
    if dialog.exec() == QFileDialog.DialogCode.Accepted:
        files = dialog.selectedFiles()
        return files[0] if files else ""
    return ""


def _style_dialog(dialog: QFileDialog) -> None:
    """Apply dark theme styling to file dialog."""
    p = get_theme_palette()
    dialog.setStyleSheet(f"""
        QFileDialog {{
            background: {p['bg_panel']};
            color: {p['text']};
        }}
        QTreeView {{
            background: {p['bg_panel']};
            color: {p['text']};
            border: 1px solid {p['border']};
        }}
        QTreeView::item {{
            padding: 4px;
        }}
        QTreeView::item:selected {{
            background: {p['accent_tab']};
            color: white;
        }}
        QTreeView::item:hover {{
            background: {p['bg_button_hover']};
        }}
        QTreeView::section {{
            background: {p['bg_control']};
            color: {p['text']};
            border: 1px solid {p['border']};
            padding: 4px;
        }}
        QPushButton {{
            background: {p['bg_control']};
            color: {p['text']};
            border: 1px solid {p['border']};
            border-radius: 4px;
            padding: 6px 12px;
            min-width: 60px;
        }}
        QPushButton:hover {{
            background: {p['bg_button_hover']};
        }}
        QPushButton:pressed {{
            background: {p['bg_button_pressed']};
        }}
        QLineEdit {{
            background: {p['bg_panel']};
            color: {p['text']};
            border: 1px solid {p['border']};
            border-radius: 4px;
            padding: 4px 8px;
        }}
        QLabel {{
            color: {p['text']};
        }}
        QComboBox {{
            background: {p['bg_control']};
            color: {p['text']};
            border: 1px solid {p['border']};
            border-radius: 4px;
            padding: 4px 8px;
        }}
        QComboBox::drop-down {{
            border: none;
        }}
        QComboBox QAbstractItemView {{
            background: {p['bg_control']};
            color: {p['text']};
            selection-background-color: {p['accent_tab']};
        }}
    """)
