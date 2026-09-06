"""Shared sizing and scrolling rules for settings dialogs."""

from __future__ import annotations

from typing import TypeVar

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QFormLayout, QFrame, QLabel, QScrollArea, QWidget


def scrollable_settings(widget: QWidget) -> QScrollArea:
    """Keep a long form's minimum size out of the dialog's minimum size.

    The page scrolls, not the title bar or action buttons. Long form labels
    wrap on small displays and at larger UI font sizes.
    """
    for form in widget.findChildren(QFormLayout):
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form.setVerticalSpacing(8)
        for row in range(form.rowCount()):
            item = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
            if item is not None and isinstance(item.widget(), QLabel):
                label = item.widget()
                label.setWordWrap(True)
                label.setMinimumWidth(min(220, label.fontMetrics().horizontalAdvance(label.text())))
    for combo in widget.findChildren(QComboBox):
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(12)
    scroll = QScrollArea()
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll.setWidget(widget)
    return scroll


def fit_settings_dialog(dialog: QDialog, preferred: QSize = QSize(860, 560)) -> None:
    """Use a compact initial size, bounded by the parent's screen work area."""
    parent = dialog.parentWidget()
    screen = (parent.screen() if parent is not None else dialog.screen()) or QApplication.primaryScreen()
    if screen is None:
        dialog.resize(preferred)
        return
    available = screen.availableGeometry().adjusted(16, 16, -16, -16)
    dialog.resize(preferred.boundedTo(available.size()))
    center = parent.frameGeometry().center() if parent is not None else available.center()
    position = center - dialog.rect().center()
    position.setX(max(available.left(), min(position.x(), available.right() - dialog.width() + 1)))
    position.setY(max(available.top(), min(position.y(), available.bottom() - dialog.height() + 1)))
    dialog.move(position)


_TextWidget = TypeVar("_TextWidget", bound=QWidget)
_CHOICE_TRANSLATION_ROLE = Qt.ItemDataRole.UserRole + 17
_TEXT_SETTERS = ("setText", "setTitle", "setWindowTitle", "setToolTip", "setPlaceholderText", "setAccessibleName")


def settings_text(widget: _TextWidget, key: str, *, setter: str = "setText") -> _TextWidget:
    """Bind a static UI string to its key, never to its translated value.

    Only labels/metadata are registered. User-entered text, paths and server
    credentials must not be touched when the language changes.
    """
    from echo_personal_tool.infrastructure.i18n import tr

    if setter not in _TEXT_SETTERS:
        raise ValueError(f"Unsupported settings text setter: {setter}")
    widget.setProperty(f"_settings_{setter}_key", key)
    getattr(widget, setter)(tr(key))
    return widget


def add_settings_row(form: QFormLayout, key: str, field) -> None:
    from echo_personal_tool.infrastructure.i18n import tr

    form.addRow(tr(key), field)
    label = form.labelForField(field)
    if label is not None:
        settings_text(label, key)


def add_settings_choice(combo: QComboBox, key: str, value: object) -> None:
    from echo_personal_tool.infrastructure.i18n import tr

    combo.addItem(tr(key), value)
    combo.setItemData(combo.count() - 1, key, _CHOICE_TRANSLATION_ROLE)


def retranslate_settings(root: QWidget) -> None:
    """Refresh registered text in place without reconstructing the form."""
    from PySide6.QtCore import QSignalBlocker

    from echo_personal_tool.infrastructure.i18n import tr

    for widget in (root, *root.findChildren(QWidget)):
        for setter in _TEXT_SETTERS:
            key = widget.property(f"_settings_{setter}_key")
            if key:
                getattr(widget, setter)(tr(key))
        if isinstance(widget, QComboBox):
            with QSignalBlocker(widget):
                for index in range(widget.count()):
                    key = widget.itemData(index, _CHOICE_TRANSLATION_ROLE)
                    if key:
                        widget.setItemText(index, tr(key))
