"""Tab strip below the system bar (Э9, PR-B) and the placeholder of an empty tab.

The strip only renders: the window owns the tab state (``TabSessionManager``)
and reacts to the signals. The placeholder is a stub until the start page
(PR-D) replaces it.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QTabBar, QToolButton, QVBoxLayout, QWidget

from echo_personal_tool.presentation.ui_metrics import control_height


def _close_icon() -> QIcon:
    """PR2: close glyph recolored to the theme text color.

    The native Fusion PE_IndicatorTabClose paints the selected tab's glyph
    orange-red; the repo never overrode it, so it surfaced with the tab strip.
    """
    from pathlib import Path

    from PySide6.QtGui import QPixmap

    from echo_personal_tool.presentation.dark_theme import get_theme_palette

    svg_path = Path(__file__).resolve().parents[1] / "resources" / "icons" / "close.svg"
    if svg_path.is_file():
        svg_text = svg_path.read_text(encoding="utf-8")
        color = get_theme_palette().get("text", "#f1f5f9")
        svg_text = svg_text.replace("currentColor", color)
        pixmap = QPixmap()
        pixmap.loadFromData(svg_text.encode("utf-8"))
        if not pixmap.isNull():
            return QIcon(pixmap)
    return QIcon()


class TabStrip(QWidget):
    """Horizontal list of open tabs, sized like a system-bar control."""

    tab_selected = Signal(str)  # tab_id
    tab_close_requested = Signal(str)  # tab_id

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("tabStrip")
        self._bar = QTabBar(self)
        self._bar.setObjectName("tabStripBar")
        self._bar.setTabsClosable(True)
        self._bar.setMovable(False)
        self._bar.setExpanding(False)
        self._bar.setDrawBase(False)
        self._bar.setUsesScrollButtons(True)
        self._bar.setElideMode(Qt.TextElideMode.ElideRight)
        self._bar.currentChanged.connect(self._on_current_changed)
        self._bar.tabCloseRequested.connect(self._on_close_requested)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._bar, stretch=1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    # ----- state -----------------------------------------------------------

    def set_tabs(self, items: Sequence[tuple[str, str]], active_tab_id: str | None) -> None:
        """Update in place when ids/order match, preserving close buttons and geometry."""
        with QSignalBlocker(self._bar):
            if self.tab_ids() != [tab_id for tab_id, _ in items]:
                while self._bar.count():
                    self._bar.removeTab(0)
                for tab_id, caption in items:
                    index = self._bar.addTab(caption)
                    self._bar.setTabData(index, tab_id)
            for index, (tab_id, caption) in enumerate(items):
                if self._bar.tabText(index) != caption:
                    self._bar.setTabText(index, caption)
                if self._bar.tabToolTip(index) != caption:
                    self._bar.setTabToolTip(index, caption)
                if tab_id == active_tab_id and self._bar.currentIndex() != index:
                    self._bar.setCurrentIndex(index)
            self._refresh_close_buttons()

    def tab_count(self) -> int:
        return self._bar.count()

    def tab_ids(self) -> list[str]:
        return [self._bar.tabData(i) for i in range(self._bar.count())]

    def current_tab_id(self) -> str | None:
        index = self._bar.currentIndex()
        return self._bar.tabData(index) if index >= 0 else None

    def caption(self, tab_id: str) -> str:
        for index in range(self._bar.count()):
            if self._bar.tabData(index) == tab_id:
                return self._bar.tabText(index)
        raise KeyError(tab_id)

    def update_control_height(self, reference: QWidget) -> None:
        """Re-measure after the system-bar font/theme has been applied."""
        reference.ensurePolished()
        height = control_height(reference)
        # The global QTabBar rule has 8px vertical padding. Merely shrinking
        # the widget clips both text and close buttons; size the tabs as well.
        # The theme contributes a 1px top border and no bottom border.
        self._bar.setStyleSheet(
            f"QTabBar#tabStripBar::tab {{ height: {height - 1}px; padding: 0px 12px; }}"
            "QTabBar#tabStripBar QToolButton { min-height: 0px; padding: 0px; }"
        )
        self._bar.setFixedHeight(height)
        self.setFixedHeight(height)
        # Theme change path (called from MainWindow._on_preferences_changed):
        # recolor themed close glyphs along with the metrics.
        self._refresh_close_buttons()

    def _refresh_close_buttons(self) -> None:
        """Replace native close glyphs with theme-colored ones."""
        for index in range(self._bar.count()):
            old = self._bar.tabButton(index, QTabBar.ButtonPosition.RightSide)
            if isinstance(old, QToolButton) and old.property("themedClose"):
                old.setIcon(_close_icon())
                continue
            btn = QToolButton(self._bar)
            btn.setProperty("themedClose", True)
            btn.setIcon(_close_icon())
            btn.setAutoRaise(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(self._on_close_button_clicked)
            self._bar.setTabButton(index, QTabBar.ButtonPosition.RightSide, btn)

    def _on_close_button_clicked(self) -> None:
        sender = self.sender()
        for index in range(self._bar.count()):
            if self._bar.tabButton(index, QTabBar.ButtonPosition.RightSide) is sender:
                self._on_close_requested(index)
                return

    # ----- internal --------------------------------------------------------

    def _on_current_changed(self, index: int) -> None:
        if index < 0:
            return
        tab_id = self._bar.tabData(index)
        if tab_id:
            # Deferred: the window may rebuild the bar, which must not happen
            # inside the bar's own currentChanged handler.
            QTimer.singleShot(0, lambda: self.tab_selected.emit(tab_id))

    def _on_close_requested(self, index: int) -> None:
        tab_id = self._bar.tabData(index)
        if tab_id:
            QTimer.singleShot(0, lambda: self.tab_close_requested.emit(tab_id))


class EmptyTabPlaceholder(QWidget):
    """Shown in the viewer area while the active tab has no studies loaded."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("emptyTabPlaceholder")
        self._title = QLabel(self)
        self._title.setObjectName("emptyTabTitle")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setWordWrap(True)
        self._hint = QLabel(self)
        self._hint.setObjectName("emptyTabHint")
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addStretch(1)
        layout.addWidget(self._title)
        layout.addWidget(self._hint)
        layout.addStretch(1)

    def show_message(self, title: str, hint: str) -> None:
        self._title.setText(title)
        self._hint.setText(hint)
