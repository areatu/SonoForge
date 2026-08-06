"""Styled file dialogs for dark theme."""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QKeySequence
from PySide6.QtWidgets import QDialogButtonBox, QFileDialog, QWidget

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
    """Save file dialog with dark theme styling.

    Uses a non-native QFileDialog so the theme applies.  Native dialogs
    auto-append the selected filter's extension; this custom dialog does not,
    so we replicate that behaviour to avoid saving files without a usable
    extension (which breaks e.g. QPixmap.save() and cv2.VideoWriter()).
    """
    dialog = QFileDialog(parent, title, directory, filter)
    dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
    dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    _style_dialog(dialog)
    if dialog.exec() != QFileDialog.DialogCode.Accepted:
        return ("", "")
    files = dialog.selectedFiles()
    if not files:
        return ("", "")
    path = files[0]
    name_filter = dialog.selectedNameFilter()
    return (_append_extension(path, name_filter), name_filter)


def _append_extension(path: str, name_filter: str) -> str:
    """Append an extension from *name_filter* if *path* lacks a matching one."""
    path_obj = Path(path)
    match = re.search(r"\(([^()]+)\)", name_filter)
    filter_exts: list[str] = []
    if match:
        filter_exts = [p[1:] for p in match.group(1).split() if p.startswith("*")]
    if not filter_exts:
        return path
    suffix = path_obj.suffix.lower()
    if suffix:
        if suffix in filter_exts:
            return path
        # Filename has a suffix that is not part of the filter (e.g. a dot in
        # the middle of the name) — append the filter's first extension.
        return f"{path}{filter_exts[0]}"
    return f"{path}{filter_exts[0]}"


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


def theme_button_box_shortcuts(box: QDialogButtonBox) -> None:
    """Color accelerator-key letters (e.g. the **O** in **&OK**) with a
    theme-contrasting color — *text_dim* — so they stand out on both light
    and dark themes.

    Qt normally underlines the letter following ``&`` in button text.  When
    we switch to rich-text formatting to apply a custom color, the ``&``
    accelerator stops working, so the shortcut key is re-registered
    explicitly via :meth:`QPushButton.setShortcut`.
    """

    p = get_theme_palette()
    contrast_color = QColor(p["text_dim"])

    _shortcut_keys: dict[QDialogButtonBox.StandardButton, Qt.Key] = {
        QDialogButtonBox.StandardButton.Ok: Qt.Key.Key_O,
        QDialogButtonBox.StandardButton.Cancel: Qt.Key.Key_C,
        QDialogButtonBox.StandardButton.Save: Qt.Key.Key_S,
        QDialogButtonBox.StandardButton.Discard: Qt.Key.Key_D,
        QDialogButtonBox.StandardButton.Close: Qt.Key.Key_C,
        QDialogButtonBox.StandardButton.Help: Qt.Key.Key_H,
        QDialogButtonBox.StandardButton.Yes: Qt.Key.Key_Y,
        QDialogButtonBox.StandardButton.No: Qt.Key.Key_N,
        QDialogButtonBox.StandardButton.Abort: Qt.Key.Key_A,
        QDialogButtonBox.StandardButton.Retry: Qt.Key.Key_R,
        QDialogButtonBox.StandardButton.Ignore: Qt.Key.Key_I,
    }

    for std_button, key in _shortcut_keys.items():
        btn = box.button(std_button)
        if btn is None:
            continue
        raw_text = btn.text()
        if not raw_text or "&" not in raw_text:
            continue
        match = re.search(r"&(\w)", raw_text)
        if not match:
            continue
        shortcut_letter = match.group(1)
        rest = raw_text.replace("&", "", 1)
        rest = rest[len(shortcut_letter):]
        btn.setTextFormat(Qt.TextFormat.RichText)
        btn.setText(
            f'<span style="color:{contrast_color.name()};font-weight:bold;">'
            f'{shortcut_letter}</span>{rest}'
        )
        btn.setShortcut(QKeySequence("Alt+" + shortcut_letter.upper()))
