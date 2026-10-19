"""The tool rail left of the snapshot (UI-2 PR-3, «Замена» of the activity bar).

Spec §4.1: a 70 px column, icon 48 × 48 with the caption under it; §4.2: the
same tools as the row, the key letter shown, an unavailable tool dimmed with its
reason, and «внизу — показать / скрыть боковые панели».

The rail replaces the interim activity bar: the bar's action buttons were a copy
of six measurements with their own captions, so they went out of date whenever the
catalog changed.  Here the captions, the keys and the availability are read out
of the tool catalog and the shortcut registry instead (D-09 TP).
"""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget

from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.presentation.tool_buttons.base import (
    BUTTON_EDGE_MIN,
    RAIL_WIDTH_MIN,
    ToolButton,
    ToolButtonsBase,
)
from echo_personal_tool.presentation.tool_buttons.buttons import caption, key_hint
from echo_personal_tool.presentation.ui_metrics import control_height, font_pixel_size, two_line_height


class RailButton(ToolButton):
    """A rail button: the key letter painted in the corner (§4.2)."""

    def __init__(self, spec, parent: QWidget | None = None) -> None:  # noqa: ANN001
        super().__init__(spec, parent)
        self.setProperty("view", "rail")

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        key = key_hint(self.spec)
        if not key or not self.isVisible():
            return
        from echo_personal_tool.presentation.dark_theme import get_theme_tokens

        tokens = get_theme_tokens()
        from PySide6.QtGui import QColor, QFontMetrics

        from echo_personal_tool.presentation.dark_theme import get_theme_tokens

        painter = QPainter(self)
        font = self.font()
        font.setPixelSize(max(8, font_pixel_size(self, 0.8)))
        painter.setFont(font)
        metrics = QFontMetrics(font)
        box = metrics.horizontalAdvance(key) + 8
        area = QRect(self.width() - box - 3, 3, box, metrics.height() + 4)
        # UA-17: the badge colour is a token, never a literal.
        painter.setPen(QColor(get_theme_tokens()["text.2"]))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(area)
        painter.drawText(area, Qt.AlignmentFlag.AlignCenter, key)
        painter.end()


class ToolButtonRail(ToolButtonsBase):
    """The vertical strip of tool buttons, 70 px wide."""

    OBJECT_NAME = "toolButtonRail"
    VIEW = "rail"
    VERTICAL_CAPTIONS = True
    BORDER_PROPERTY = "border-right"

    #: The bottom button of the rail: show / hide the side panels (§4.2).
    side_panels_toggled = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        self._layout = QVBoxLayout()
        super().__init__(parent)
        self.setLayout(self._layout)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(2)
        self._panels = QPushButton(self)
        self._panels.setObjectName("toolRailPanels")
        self._panels.setCheckable(False)
        self._panels.setAutoDefault(False)
        self._panels.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._panels.clicked.connect(self.side_panels_toggled.emit)
        self._layout.addStretch(1)
        self._layout.addWidget(self._panels)
        self.build()

    # ── assembly ────────────────────────────────────────────────────

    def arrange(self) -> None:
        """Every tool of the table, in its order, then the panel toggle."""
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None and widget is not self._panels:
                widget.setParent(None)
        for spec in self.specs():
            control = self.button(spec.id)
            if control is not None:
                self._layout.addWidget(control)
        self._layout.addStretch(1)
        self._layout.addWidget(self._panels)

    def make_button(self, spec) -> RailButton:  # noqa: ANN001
        control = RailButton(spec, self)
        control.clicked.connect(lambda _checked=False, button_id=spec.id: self.action_requested.emit(button_id))
        return control

    # ── geometry and text ───────────────────────────────────────────

    def caption_font(self) -> QFont:
        """The rail paints its captions a step below the UI font (§4.1: 70 px).

        A 70 px column cannot hold «Калибровка» at 13 px, and UA-16 forbids
        clipping it, so the caption is the part that gives: one step down in size,
        full text in the tooltip as always.
        """
        font = self.font()
        font.setPixelSize(max(9, font_pixel_size(self, 0.85)))
        return font

    def update_geometry(self) -> None:
        """70 px as the floor, widened by the captions the rail really paints."""
        font = self.caption_font()
        metrics = QFontMetrics(font)
        width = RAIL_WIDTH_MIN
        for text in self.captions_for_metrics():
            width = max(width, int(metrics.horizontalAdvance(text)) + 16)
        self.setFixedWidth(width)
        edge = max(BUTTON_EDGE_MIN, control_height(self, padding=10))
        height = two_line_height(self, padding=14, minimum=48) if self._shows_any_caption() else edge
        for spec in self.specs():
            control = self.button(spec.id)
            if control is not None:
                control.setFont(font)
                control.setFixedSize(max(self.width() - 8, edge), height)
        self._panels.setFont(font)
        self._panels.setFixedSize(max(self.width() - 8, edge), height)

    def _shows_any_caption(self) -> bool:
        return any(self.shows_captions(spec) for spec in self.specs())

    def refresh(self) -> None:
        super().refresh()
        self._panels.setText(tr("toolbtn.panels"))
        self._panels.setToolTip(tr("toolbtn.panels_tooltip"))
        self._panels.setAccessibleName(tr("toolbtn.panels_tooltip"))

    def captions_for_metrics(self) -> tuple[str, ...]:
        """Captions plus the key letters: the rail paints both (§4.2)."""
        texts = [caption(spec, self._language) for spec in self.specs()]
        texts += [key_hint(spec) for spec in self.specs()]
        texts.append(tr("toolbtn.panels"))
        return tuple(text for text in texts if text)
