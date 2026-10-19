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

RAIL_BUTTON_HORIZONTAL_PADDING = 4
RAIL_BUTTON_BORDER_WIDTH = 1
RAIL_BUTTON_HORIZONTAL_INSETS = 2 * (RAIL_BUTTON_HORIZONTAL_PADDING + RAIL_BUTTON_BORDER_WIDTH)


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
        self._panels.setStyleSheet(f"QPushButton {{ padding: 2px {RAIL_BUTTON_HORIZONTAL_PADDING}px; }}")
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
        control.setStyleSheet(f"QToolButton {{ padding: 2px {RAIL_BUTTON_HORIZONTAL_PADDING}px; }}")
        control.clicked.connect(lambda _checked=False, button_id=spec.id: self.action_requested.emit(button_id))
        return control

    # ── geometry and text ───────────────────────────────────────────

    def caption_font(self) -> QFont:
        """Paint captions one step below the UI font inside the 70 px rail.

        Long labels are right-elided at the button's available width; the complete
        text remains in the tooltip and accessible name rather than widening the
        rail into the viewer.
        """
        font = self.font()
        font.setPixelSize(max(9, font_pixel_size(self, 0.85)))
        return font

    def update_geometry(self) -> None:
        """Keep the 70 px rail compact; right-elide captions that do not fit."""
        font = self.caption_font()
        self.setFixedWidth(RAIL_WIDTH_MIN)
        edge = max(BUTTON_EDGE_MIN, control_height(self, padding=10))
        button_width = max(RAIL_WIDTH_MIN - 8, edge)
        text_width = max(0, button_width - RAIL_BUTTON_HORIZONTAL_INSETS)
        height = two_line_height(self, padding=14, minimum=48) if self._shows_any_caption() else edge
        for spec in self.specs():
            control = self.button(spec.id)
            if control is not None:
                control.setFont(font)
                control.setFixedSize(button_width, height)
                if self.shows_captions(spec):
                    text = caption(spec, self._language)
                    hint = key_hint(spec) if self._show_key_hints else ""
                    if hint:
                        text = f"{text} · {hint}"
                    control.setText(control.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, text_width))
        self._panels.setFont(font)
        self._panels.setFixedSize(button_width, height)
        self._elide_panels_label(self._panels.fontMetrics(), button_width)

    def _elide_panels_label(self, metrics: QFontMetrics, button_width: int | None = None) -> None:
        """Keep the rail toggle legible at large UI fonts too."""
        width = button_width if button_width is not None else max(RAIL_WIDTH_MIN - 8, BUTTON_EDGE_MIN)
        text = tr("toolbtn.panels")
        self._panels.setText(
            metrics.elidedText(text, Qt.TextElideMode.ElideRight, max(0, width - RAIL_BUTTON_HORIZONTAL_INSETS))
        )

    def _shows_any_caption(self) -> bool:
        return any(self.shows_captions(spec) for spec in self.specs())

    def refresh(self) -> None:
        super().refresh()
        self._panels.setText(tr("toolbtn.panels"))
        self._panels.setToolTip(tr("toolbtn.panels_tooltip"))
        self._panels.setAccessibleName(tr("toolbtn.panels_tooltip"))
        self._elide_panels_label(self._panels.fontMetrics())

    def captions_for_metrics(self) -> tuple[str, ...]:
        """Full captions and key hints; the fixed rail elides rather than widening."""
        texts = [caption(spec, self._language) for spec in self.specs()]
        texts += [key_hint(spec) for spec in self.specs()]
        texts.append(tr("toolbtn.panels"))
        return tuple(text for text in texts if text)
