"""The tool row above the snapshot (UI-2 PR-3, D-08).

Spec §4.1: a 42 px strip over the image, icons, and a caption only next to the
active tool; §4.2: the composition of the row and its right group («масштаб»).
The buttons come from :mod:`~echo_personal_tool.presentation.tool_buttons.buttons`,
so the row, the rail and the panel's tools block can never disagree about which
tools exist or in which order they sit.

§4.1 also promises that at 1024 px «часть кнопок ряда уходит в „Ещё“», so the row
measures itself on resize and folds what does not fit into a menu: the tools stay
reachable, nothing vanishes without a trace (D-08).
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QMenu, QToolButton, QWidget

from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.presentation.tool_buttons.base import (
    BUTTON_EDGE_MIN,
    ROW_HEIGHT_MIN,
    ToolButtonsBase,
)
from echo_personal_tool.presentation.tool_buttons.buttons import GROUP_VIEW, caption, unavailable_reason
from echo_personal_tool.presentation.ui_metrics import control_height

#: Width the «Ещё» button costs and the gap between the buttons of the row.
MORE_WIDTH = BUTTON_EDGE_MIN + 8
SPACING = 2


class ToolButtonRow(ToolButtonsBase):
    """The horizontal strip; one signal out, whatever the button is (D-09 TP)."""

    OBJECT_NAME = "toolButtonRow"
    VIEW = "row"

    def __init__(self, parent: QWidget | None = None) -> None:
        # The layout is built parentless: QWidget.__init__ has to run first, and
        # the base class assembles the buttons only when ``build()`` is called.
        self._layout = QHBoxLayout()
        self._widths: dict[str, int] = {}
        self._hidden: frozenset[str] = frozenset()
        super().__init__(parent)
        self.setLayout(self._layout)
        self._layout.setContentsMargins(4, 2, 4, 2)
        self._layout.setSpacing(SPACING)
        self._more = QToolButton(self)
        self._more.setObjectName("toolButtonMore")
        self._more.setText("…")
        self._more.setAutoRaise(True)
        self._more.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._more.setVisible(False)
        self._menu = QMenu(self._more)
        self._menu.aboutToShow.connect(self._fill_menu)
        self._more.setMenu(self._menu)
        self._more.setAccessibleName(tr("toolbtn.more"))
        self.build()

    def shows_captions(self, spec) -> bool:
        return True

    # ── assembly ────────────────────────────────────────────────────

    def arrange(self) -> None:
        """The measurement groups in catalog order, the view group on the right."""
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
        for index, spec in enumerate(self.specs()):
            if spec.group == GROUP_VIEW:
                continue
            control = self.button(spec.id)
            if control is None:
                continue
            if index and spec.separated:
                self._layout.addWidget(self._separator())
            self._layout.addWidget(control)
        self._layout.addStretch(1)
        self._layout.addWidget(self._more)
        for spec in self.specs():
            if spec.group == GROUP_VIEW:
                control = self.button(spec.id)
                if control is not None:
                    self._layout.addWidget(control)

    def _separator(self) -> QFrame:
        line = QFrame(self)
        line.setFrameShape(QFrame.Shape.VLine)
        line.setObjectName("toolButtonSeparator")
        return line

    # ── geometry ────────────────────────────────────────────────────

    def update_geometry(self) -> None:
        """42 px for the strip; the buttons fill it but never fall below 36 px.

        §4.1 pins the strip at 42 px while UA-05 asks for a 44 px target: inside a
        42 px row that is not reachable, so the row takes the strip and leaves the
        remainder of the target to the key (L, C, V, K) and the panel, which stay
        44 px.  The height is a floor, never a ceiling: a 24 px font grows it.
        """
        height = max(ROW_HEIGHT_MIN, control_height(self, padding=8) + 4)
        self.setFixedHeight(height)
        edge = max(BUTTON_EDGE_MIN - 8, height - 4)
        self._widths = {}
        for spec in self.specs():
            control = self.button(spec.id)
            if control is None:
                continue
            width = edge
            if self.shows_captions(spec):
                control.ensurePolished()
                icon_width = self.ICON_EDGE + 6 if not control.icon().isNull() else 0
                width = max(edge, control.fontMetrics().horizontalAdvance(control.text()) + icon_width + 28)
            control.setFixedSize(width, edge)
            self._widths[spec.id] = width + SPACING
        for spec in self.specs():
            control = self.button(spec.id)
            if control is not None:
                control.setIconSize(QSize(self.ICON_EDGE, self.ICON_EDGE))
        self._more.setIconSize(QSize(self.ICON_EDGE, self.ICON_EDGE))
        self._more.setFixedSize(MORE_WIDTH, edge)
        for index in range(self._layout.count()):
            item = self._layout.itemAt(index)
            widget = item.widget() if item is not None else None
            if isinstance(widget, QFrame):
                widget.setFixedHeight(edge - 4)
        self._fold()

    def needed_width(self) -> int:
        """What the row would need to paint every button at once (§4.1)."""
        return sum(self._widths.values()) + MORE_WIDTH + 8

    def hidden_ids(self) -> frozenset[str]:
        """The buttons currently folded into «Ещё» (what the 1024 px test reads)."""
        return self._hidden

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._fold()

    def _fold(self) -> None:
        """Keep what fits on the strip; the rest goes into the menu."""
        controls = [self.button(spec.id) for spec in self.specs()]
        if any(control is None for control in controls) or not controls:
            return
        available = self.width()
        if available <= 0:
            # Not laid out yet (the widget is still being assembled): the row
            # keeps every button, and the first real resize folds what is left.
            for control in controls:
                control.setVisible(True)
            self._more.setVisible(False)
            self._hidden = frozenset()
            return
        used = MORE_WIDTH
        keep = 0
        for spec in self.specs():
            control = self.button(spec.id)
            assert control is not None
            used += self._widths.get(spec.id, BUTTON_EDGE_MIN)
            if used > available:
                break
            keep += 1
        folded = frozenset(spec.id for index, spec in enumerate(self.specs()) if index >= keep)
        for spec in self.specs():
            control = self.button(spec.id)
            if control is not None:
                control.setVisible(spec.id not in folded)
        self._more.setVisible(bool(folded))
        self._hidden = folded

    def _fill_menu(self) -> None:
        """Menu entries for the folded buttons, in the row's own order (§4.1)."""
        self._menu.clear()
        for spec in self.specs():
            if spec.id not in self._hidden:
                continue
            action = self._menu.addAction(caption(spec, self._language))
            action.setEnabled(not unavailable_reason(spec, self.state(), self._language))
            action.triggered.connect(lambda _checked=False, button_id=spec.id: self.action_requested.emit(button_id))
