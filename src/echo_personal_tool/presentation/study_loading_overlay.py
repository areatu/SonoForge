"""Viewer-local loading veil: no page switch or disabled/repainted chrome."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QShortcut
from PySide6.QtWidgets import QLabel, QWidget


class StudyLoadingOverlay(QLabel):
    """Mark the retained image as busy and prevent edits against the old study.

    Input is filtered on the widgets of this window only.  The previous
    QApplication-wide filter also received QtWebEngine compositor events; on
    PySide6 6.11.2 Shiboken could crash while wrapping those internal no-RTTI
    receivers, before Python had a chance to ignore the event.  Other windows
    and modal error dialogs remain usable.
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
        self._input_targets: list[QWidget] = []
        self._shortcuts: list[tuple[QShortcut, bool]] = []
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
            self._install_input_filters()

    def stop(self) -> None:
        self.hide()
        self._remove_input_filter()

    def _install_input_filters(self) -> None:
        window = self.window()
        if window is None:
            return
        targets: list[QWidget] = []

        def visit(widget: QWidget) -> None:
            if widget is self:
                return
            # Never observe QtWebEngine's internal render-widget delegates.
            if "WebEngine" in widget.metaObject().className():
                return
            targets.append(widget)
            for child in widget.children():
                if isinstance(child, QWidget):
                    visit(child)

        visit(window)
        for target in targets:
            target.installEventFilter(self)
        self._input_targets = targets
        self._shortcuts = [(shortcut, shortcut.isEnabled()) for shortcut in window.findChildren(QShortcut)]
        for shortcut, _enabled in self._shortcuts:
            shortcut.setEnabled(False)
        self._filter_installed = True

    def _remove_input_filter(self) -> None:
        if not self._filter_installed:
            return
        for target in self._input_targets:
            try:
                target.removeEventFilter(self)
            except RuntimeError:
                pass
        self._input_targets = []
        for shortcut, enabled in self._shortcuts:
            try:
                shortcut.setEnabled(enabled)
            except RuntimeError:
                pass
        self._shortcuts = []
        self._filter_installed = False

    def hideEvent(self, event) -> None:
        self._remove_input_filter()
        super().hideEvent(event)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self.setGeometry(self.parentWidget().rect())
        if watched is self.window():
            if event.type() in (QEvent.Type.Hide, QEvent.Type.Close):
                self._remove_input_filter()
            elif event.type() == QEvent.Type.Show and self.isVisible() and not self._filter_installed:
                self._install_input_filters()
        if self._filter_installed and event.type() in self._INPUT_EVENTS:
            owner = watched
            while owner is not None and not isinstance(owner, QWidget):
                owner = owner.parent()
            if owner is not None and owner.window() is self.window():
                event.accept()
                return True
        return super().eventFilter(watched, event)
