"""Visible client-area outlines, including frameless dialogs with edge-to-edge children."""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QApplication, QDialog, QWidget

from echo_personal_tool.presentation.theme.palettes import THEME_DARK, get_palette_tokens

#: ``line.dialog`` of the active theme, pushed by the theme whenever it is applied.
#: Until then the outline uses the dark theme's value, as ``get_theme_tokens()`` does
#: before anything was applied. The outline does not import the theme module: that
#: module imports this one, and a lazy import back closed a cycle (issue 328).
_outline_color: str | None = None


def set_outline_color(color: str) -> None:
    """Remember the dialog line colour of the theme that was just applied."""
    global _outline_color
    _outline_color = color


def outline_color() -> str:
    """The colour the outline is painted with."""
    if _outline_color is not None:
        return _outline_color
    return get_palette_tokens(THEME_DARK)["line.dialog"]


class _DialogOutline(QWidget):
    """Paint above child layouts; a QSS border alone can be covered by their backgrounds."""

    def __init__(self, dialog: QDialog) -> None:
        super().__init__(dialog)
        self.setObjectName("dialogOutline")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        dialog.installEventFilter(self)
        self.setGeometry(dialog.rect())
        self.show()
        self.raise_()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self.setGeometry(watched.rect())
            self.raise_()
        return False

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setPen(QColor(outline_color()))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))


def ensure_dialog_outline(dialog: QDialog) -> None:
    outline = dialog.findChild(_DialogOutline, "dialogOutline", Qt.FindChildOption.FindDirectChildrenOnly)
    if outline is None:
        _DialogOutline(dialog)
    else:
        outline.raise_()  # A rebuilt dialog may have added full-bleed children after its first show.


def install_dialog_outlines(app: QApplication) -> None:
    """Outline dialogs that already exist; never subscribe to QApplication.

    New dialogs opt in through their own construction path (``ensure_dialog_outline``
    or the shared styled-dialog helpers).  An application-wide Python event filter
    is unsafe next to QtWebEngine on PySide6 6.11.2: Shiboken may try to wrap an
    internal no-RTTI compositor object before the filter body can reject it.
    """
    for widget in app.topLevelWidgets():
        if isinstance(widget, QDialog):
            ensure_dialog_outline(widget)
