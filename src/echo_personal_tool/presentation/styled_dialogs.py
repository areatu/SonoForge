"""Styled file dialogs for dark theme."""

from __future__ import annotations

from PySide6.QtWidgets import QFileDialog, QWidget

from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.presentation.dark_theme import get_theme_palette


def styled_open_file(
    parent: QWidget | None = None,
    title: str = tr("styled_dialogs.open_file"),
    directory: str = "",
    filter: str = tr("styled_dialogs.all_files"),
) -> tuple[str, str]:
    """Open file dialog with dark theme styling."""
    dialog = QFileDialog(parent, title, directory, filter)
    dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    _style_dialog(dialog)
    if dialog.exec() == QFileDialog.DialogCode.Accepted:
        files = dialog.selectedFiles()
        return (files[0], dialog.selectedNameFilter()) if files else ("", "")
    return ("", "")


def styled_open_files(
    parent: QWidget | None = None,
    title: str = tr("styled_dialogs.open_files"),
    directory: str = "",
    filter: str = tr("styled_dialogs.all_files"),
) -> list[str]:
    """Open multiple files dialog with dark theme styling."""
    dialog = QFileDialog(parent, title, directory, filter)
    dialog.setFileMode(QFileDialog.FileMode.ExistingFiles)
    dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    _style_dialog(dialog)
    if dialog.exec() == QFileDialog.DialogCode.Accepted:
        return dialog.selectedFiles()
    return []


def styled_save_file(
    parent: QWidget | None = None,
    title: str = tr("styled_dialogs.save_file"),
    directory: str = "",
    filter: str = tr("styled_dialogs.all_files"),
) -> tuple[str, str]:
    """Save file dialog with dark theme styling."""
    dialog = QFileDialog(parent, title, directory, filter)
    dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
    dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    _style_dialog(dialog)
    if dialog.exec() == QFileDialog.DialogCode.Accepted:
        files = dialog.selectedFiles()
        return (files[0], dialog.selectedNameFilter()) if files else ("", "")
    return ("", "")


def styled_select_directory(
    parent: QWidget | None = None,
    title: str = tr("styled_dialogs.select_folder"),
    directory: str = "",
) -> str:
    """Select directory dialog with dark theme styling."""
    dialog = QFileDialog(parent, title, directory)
    dialog.setFileMode(QFileDialog.FileMode.Directory)
    dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    _style_dialog(dialog)
    if dialog.exec() == QFileDialog.DialogCode.Accepted:
        files = dialog.selectedFiles()
        return files[0] if files else ""
    return ""


def _style_dialog(dialog: QFileDialog) -> None:
    """Apply dark theme styling to file dialog."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QIcon, QPalette, QPixmap

    p = get_theme_palette()

    # Apply palette to all child widgets recursively
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(p["bg_panel"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(p["text"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(p["bg_panel"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(p["bg_control"]))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(p["bg_control"]))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(p["text"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(p["text"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(p["bg_control"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(p["text"]))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(p["accent_tab"]))
    palette.setColor(QPalette.ColorRole.Link, QColor(p["accent_tab"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(p["accent_tab"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("white"))
    dialog.setPalette(palette)

    # Recursively apply palette to all children
    def apply_palette(widget):
        widget.setPalette(palette)
        for child in widget.findChildren(QWidget):
            child.setPalette(palette)
            # For buttons with icons, recolor icon to text color
            if child.__class__.__name__ in ("QToolButton", "QPushButton"):
                old_icon = child.icon()
                if not old_icon.isNull():
                    pixmap = old_icon.pixmap(16, 16)
                    if not pixmap.isNull():
                        from PySide6.QtGui import QImage, QPainter

                        image = QImage(16, 16, QImage.Format.Format_ARGB32)
                        image.fill(Qt.GlobalColor.transparent)
                        painter = QPainter(image)
                        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
                        painter.drawPixmap(0, 0, pixmap)
                        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                        painter.fillRect(image.rect(), QColor(p["text"]))
                        painter.end()
                        child.setIcon(QIcon(QPixmap.fromImage(image)))

    apply_palette(dialog)

    dialog.setStyleSheet(f"""
        * {{
            color: {p["text"]};
        }}
        QFileDialog {{
            background: {p["bg_panel"]};
        }}
        QTreeView {{
            background: {p["bg_panel"]};
            border: 1px solid {p["border"]};
        }}
        QTreeView::item {{
            padding: 4px;
        }}
        QTreeView::item:selected {{
            background: {p["accent_tab"]};
            color: white;
        }}
        QTreeView::item:hover {{
            background: {p["bg_button_hover"]};
        }}
        QTreeView::section {{
            background: {p["bg_control"]};
            border: 1px solid {p["border"]};
            padding: 4px;
        }}
        QPushButton {{
            background: {p["bg_control"]};
            border: 1px solid {p["border"]};
            border-radius: 4px;
            padding: 6px 12px;
            min-width: 60px;
        }}
        QPushButton:hover {{
            background: {p["bg_button_hover"]};
        }}
        QPushButton:pressed {{
            background: {p["bg_button_pressed"]};
        }}
        QToolButton {{
            background: {p["bg_control"]};
            border: 1px solid {p["border"]};
            border-radius: 4px;
            padding: 4px;
            min-width: 24px;
            min-height: 24px;
        }}
        QToolButton:hover {{
            background: {p["bg_button_hover"]};
        }}
        QToolButton:pressed {{
            background: {p["bg_button_pressed"]};
        }}
        QLineEdit {{
            background: {p["bg_panel"]};
            border: 1px solid {p["border"]};
            border-radius: 4px;
            padding: 4px 8px;
        }}
        QComboBox {{
            background: {p["bg_control"]};
            border: 1px solid {p["border"]};
            border-radius: 4px;
            padding: 4px 8px;
        }}
        QComboBox::drop-down {{
            border: none;
        }}
        QComboBox QAbstractItemView {{
            background: {p["bg_control"]};
            selection-background-color: {p["accent_tab"]};
        }}
    """)
