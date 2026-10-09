"""Viewer-local loading veil: no page switch or disabled/repainted chrome."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QApplication, QLabel, QWidget


class StudyLoadingOverlay(QLabel):
    """Mark the retained image as busy and prevent edits against the old study.

    Input is filtered instead of disabling the window (which would restyle all
    chrome). Only this window is blocked; other windows and modal error dialogs
    remain usable. Paint, timers, worker signals and close events still run.
    """

    _INPUT_EVENTS = frozenset(
        {
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.MouseButtonDblClick,
            QEvent.Type.MouseMove,
            QEvent.Type.Wheel,
            QEvent.Type.KeyPress,
            QEvent.Type.KeyRelease,
            QEvent.Type.Shortcut,
            QEvent.Type.ShortcutOverride,
            QEvent.Type.ContextMenu,
            QEvent.Type.TouchBegin,
            QEvent.Type.TouchUpdate,
            QEvent.Type.TouchEnd,
            QEvent.Type.TabletPress,
            QEvent.Type.TabletMove,
            QEvent.Type.TabletRelease,
        }
    )

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("studyLoadingOverlay")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.setCursor(Qt.CursorShape.BusyCursor)
        self.setStyleSheet(
            "QLabel#studyLoadingOverlay { background: rgba(16, 33, 53, 180); color: #f1f5f9; padding: 16px; }"
        )
        self._filter_installed = False
        parent.installEventFilter(self)
        self.hide()

    def start(self, text: str) -> None:
        self.setText(text)
        self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self.show()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._filter_installed:
            QApplication.instance().installEventFilter(self)
            self._filter_installed = True

    def stop(self) -> None:
        self.hide()
        self._remove_input_filter()

    def _remove_input_filter(self) -> None:
        if self._filter_installed:
            QApplication.instance().removeEventFilter(self)
            self._filter_installed = False

    def hideEvent(self, event) -> None:
        self._remove_input_filter()
        super().hideEvent(event)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self.setGeometry(self.parentWidget().rect())
        if self._filter_installed and event.type() in self._INPUT_EVENTS:
            # QShortcut is a QObject, so walk up to its owning QWidget.
            owner = watched
            while owner is not None and not isinstance(owner, QWidget):
                owner = owner.parent()
            if owner is not None and owner.window() is self.window():
                event.accept()
                return True
        return super().eventFilter(watched, event)
