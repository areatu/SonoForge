"""Sections and tool rows of the measurement panel 2.0.

A row is deliberately not a ``QPushButton``: the panel shows a type glyph, a
label, a value and a keyboard badge on one line, and keeps the full name in
the tooltip.  The row stays keyboard reachable (Tab, Space/Enter) so the
whole panel can be driven without a mouse (A-13, TP-2 PR-2 extends this to
``/`` and the 1–9 favourites).

UI-5: the row is the host gesture of the S2 norm card — 400 ms of hovering or
the registry key on the focused row asks the panel for the card, Esc or
leaving the row closes it (§4.7).  The «Нормы» switch (UD-14, UQ-03) lights
the norm dot left of the value; the dot is the colour of the handbook
gradation and nothing else («на границе нормы» does not exist, UD-14).
"""

from __future__ import annotations

from PySide6.QtCore import QMimeData, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QDrag, QDragEnterEvent, QDragMoveEvent, QDropEvent, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.domain.measurement_catalog import ToolSpec
from echo_personal_tool.keyboard_shortcuts import event_matches_shortcut
from echo_personal_tool.presentation.dark_theme import get_theme_tokens
from echo_personal_tool.presentation.reference_card import HOVER_DELAY_MS
from echo_personal_tool.presentation.reference_grades import grade_colors
from echo_personal_tool.presentation.theme.token_restyle import TokenRestyleMixin
from echo_personal_tool.presentation.ui_metrics import control_height

#: Glyphs of the row states (§4.3).  The glyph is never the only signal: the
#: value text and the tooltip carry the same state.
STATE_NOT_STARTED = "○"
STATE_DONE = "✓"
STATE_ACTIVE = "◉"
STATE_STALE = "⟳"
STATE_WARNING = "⚠"
STATE_LOCKED = "🔒"

#: In-place edit mode (TP-5): rows carry their catalogue id while dragged.
TOOL_MIME = "application/x-sonoforge-tool"


class ToolRow(TokenRestyleMixin, QFrame):
    """One tool of a section: glyph, label, value, badge.

    UI-5: the row is the host of the S2 norm card.  The card opens after
    :data:`HOVER_DELAY_MS` of hovering or on the registry key of the focused
    row, and the row carries the norm dot of the «Нормы» switch (UD-14, UQ-03).
    The row only *reports* the gesture — the panel owns the card, and the card
    model comes from the domain.
    """

    activated = Signal(str)
    #: Emitted when the value appears or disappears (§4.2 section progress).
    value_changed = Signal()
    #: The hover delay passed or the registry key was pressed (UI-5, §4.7).
    reference_requested = Signal(str)
    #: The pointer left the row (or Esc): the host hides the S2 card.
    reference_hide_requested = Signal(str)
    #: The pointer entered the row: cancels a pending hide of the S2 card.
    pointer_entered = Signal(str)
    #: TP-5 in-place editing: ★ and 👁 of the row.
    edit_favorite_requested = Signal(str)
    edit_visibility_requested = Signal(str)

    def __init__(
        self,
        tool: ToolSpec,
        language: str,
        *,
        favorite: int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("toolRow")
        self.tool = tool
        self._language = language
        self._available = True
        self._active = False
        self._has_value = False
        self._measurement_value: float | None = None
        self._measurement_unit = ""
        self._measurement_key = ""
        self._norm_grade = ""
        self._norms_visible = False
        self._edit_mode = False
        self._is_favorite = False
        self._is_visible = True
        self._drag_origin: QPoint | None = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setProperty("active", False)
        self.setProperty("available", True)

        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(HOVER_DELAY_MS)
        self._hover_timer.timeout.connect(self._emit_reference_request)

        label = tool.label(language)
        self._glyph = QLabel(STATE_NOT_STARTED)
        self._glyph.setObjectName("toolRowGlyph")
        self._title = QLabel(label.short)
        self._title.setObjectName("toolRowLabel")
        self._title.setWordWrap(True)
        self._dot = QLabel(self)
        self._dot.setObjectName("toolRowNormDot")
        self._dot.setFixedSize(7, 7)
        self._dot.hide()
        self._value = QLabel("—")
        self._value.setObjectName("toolRowValue")
        self._value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._value.setMinimumWidth(42)
        self._badge = QLabel(favorite_key_badge(tool, favorite))
        self._badge.setObjectName("toolRowBadge")
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.setMinimumWidth(18)

        self._drag_handle = QLabel("⠿")
        self._drag_handle.setObjectName("toolRowDragHandle")
        self._drag_handle.setCursor(Qt.CursorShape.OpenHandCursor)
        self._drag_handle.setToolTip("")
        self._drag_handle.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._favorite_button = QPushButton("☆")
        self._favorite_button.setObjectName("toolRowFavorite")
        self._favorite_button.setFlat(True)
        self._favorite_button.setFixedWidth(20)
        self._favorite_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._favorite_button.clicked.connect(lambda: self.edit_favorite_requested.emit(self.tool.id))
        self._visibility_button = QPushButton("👁")
        self._visibility_button.setObjectName("toolRowVisibility")
        self._visibility_button.setFlat(True)
        self._visibility_button.setFixedWidth(20)
        self._visibility_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._visibility_button.clicked.connect(lambda: self.edit_visibility_requested.emit(self.tool.id))
        for control in (self._drag_handle, self._favorite_button, self._visibility_button):
            control.hide()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 1, 4, 1)
        layout.setSpacing(4)
        layout.addWidget(self._drag_handle)
        layout.addWidget(self._glyph)
        layout.addWidget(self._title, 1)
        layout.addWidget(self._dot)
        layout.addWidget(self._value)
        layout.addWidget(self._badge)
        layout.addWidget(self._favorite_button)
        layout.addWidget(self._visibility_button)

        self._tooltip_text = self._tooltip(label)
        self._tooltip_suppressed = False
        self.setToolTip(self._tooltip_text)
        # The full name also rides on the accessible name: the tooltip is
        # silenced while the reference card is up, and a screen reader must
        # still get the title of the row.
        self.setAccessibleName(label.full)
        self._apply_style()
        # The mockup paces its rows at 42 CSS px (the autocorrelation of the
        # right half of 01-panel-before-after.png finds the period at 42 with
        # r=0.68, and the text bands inside it repeat every 42 too), while the
        # container adds one: the row itself is 41.  It used to be 22 — a 23 px
        # pitch, half the air of the mockup.
        self.setMinimumHeight(control_height(self, padding=6, minimum=41))

    # ── Appearance ─────────────────────────────────────────────────

    def _tooltip(self, label) -> str:
        """The full name of the measurement — and nothing else.

        The list of requirements («spatial_calibration», «doppler_calibration»)
        used to hang below it as a second line.  That line is the internal name
        of a precondition, not a word a sonographer reads, and the row already
        shows its own state; worse, it popped up on top of the S2 reference card
        the same hover opens, hiding the norm it was meant to help read
        (ТЗ 2026-10-23, п. 3).  The requirements stay in the tool status
        (``application/tool_status.py``) where they gate the tool.
        """
        return label.full

    def set_reference_tooltip_suppressed(self, suppressed: bool) -> None:
        """Keep the row tooltip from covering the reference card of this row.

        The card appears after 400 ms of hover, the Qt tooltip after ~700 ms —
        so the tooltip would always land on top of the card.  While the card is
        up the tooltip of the row goes silent; the accessible name keeps the
        full title for screen readers.
        """
        if suppressed == self._tooltip_suppressed:
            return
        self._tooltip_suppressed = bool(suppressed)
        self.setToolTip("" if self._tooltip_suppressed else self._tooltip_text)

    def _apply_style(self) -> None:
        tokens = get_theme_tokens()
        color = tokens["text.1"] if self._available else tokens["text.disabled"]
        value_color = tokens["text.2"] if self._available else tokens["text.disabled"]
        self.setStyleSheet(
            f"""
            #toolRow {{
                border: 1px solid transparent;
                border-radius: 4px;
                background: transparent;
            }}
            #toolRow:hover {{
                background: {tokens["surface.3"]};
            }}
            #toolRow[active="true"] {{
                border-color: {tokens["accent"]};
                background: {tokens["surface.2"]};
            }}
            #toolRowGlyph {{
                color: {tokens["text.3"]};
                min-width: 12px;
            }}
            #toolRowLabel {{
                color: {color};
            }}
            #toolRowValue {{
                color: {value_color};
            }}
            #toolRowBadge {{
                color: {tokens["text.3"]};
            }}
            """
        )

    def set_available(self, available: bool) -> None:
        """Disable a tool the current clip cannot run (no time scale, no vessel)."""
        if available == self._available:
            return
        self._available = available
        self.setProperty("available", available)
        self.setCursor(Qt.CursorShape.PointingHandCursor if available else Qt.CursorShape.ArrowCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus if available else Qt.FocusPolicy.NoFocus)
        self._apply_style()

    def is_available(self) -> bool:
        return self._available

    # ── In-place editing (TP-5) ────────────────────────────────────

    def set_edit_mode(self, enabled: bool, *, favorite: bool = False, visible: bool = True) -> None:
        self._edit_mode = bool(enabled)
        self.setProperty("editMode", self._edit_mode)
        self._is_favorite = bool(favorite)
        self._is_visible = bool(visible)
        for control in (self._drag_handle, self._favorite_button, self._visibility_button):
            control.setVisible(self._edit_mode)
        if self._edit_mode:
            from echo_personal_tool.infrastructure.i18n import tr

            self._drag_handle.setToolTip(tr("panel.edit_drag"))
            self._favorite_button.setToolTip(tr("panel.edit_favorite"))
            self._visibility_button.setToolTip(tr("panel.edit_visible"))
            self._favorite_button.setText("★" if self._is_favorite else "☆")
            self._visibility_button.setText("👁" if self._is_visible else "🚫")
        self.update()

    def edit_mode(self) -> bool:
        return self._edit_mode

    def is_favorite(self) -> bool:
        return self._is_favorite

    def is_visible(self) -> bool:
        return self._is_visible

    def has_value(self) -> bool:
        """True when the section progress counts this row (§4.2 «2/9»)."""
        return self._has_value

    def set_active(self, active: bool) -> None:
        """Static next-step marker — TP-2 replaces the old 500 ms blinking."""
        if active == self._active:
            return
        self._active = active
        self.setProperty("active", active)
        self.style().unpolish(self)
        self.style().polish(self)
        self._glyph.setText(STATE_ACTIVE if active else (STATE_DONE if self._has_value else STATE_NOT_STARTED))

    def is_active(self) -> bool:
        return self._active

    def set_value(self, text: str, *, value: float | None = None, unit: str = "", key: str = "") -> None:
        """Show a result; the owning section advances its «N/M» progress.

        ``value`` / ``unit`` / ``key`` keep what the S2 card and the norm dot
        need: the measured number in the displayed unit and its projection key.
        """
        self._value.setText(text or "—")
        self._measurement_value = value
        self._measurement_unit = unit or ""
        if key:
            self._measurement_key = key
        changed = self._has_value != bool(text)
        self._has_value = bool(text)
        if not self._active:
            self._glyph.setText(STATE_DONE if self._has_value else STATE_NOT_STARTED)
        if changed:
            self.value_changed.emit()

    # ── Norm dot (UI-5, UD-14) ─────────────────────────────────────

    @property
    def measurement_value(self) -> float | None:
        return self._measurement_value

    @property
    def measurement_unit(self) -> str:
        return self._measurement_unit

    @property
    def measurement_key(self) -> str:
        return self._measurement_key

    @property
    def norm_grade(self) -> str:
        """Gradation name of the value («Норма» …); empty — outside the scale."""
        return self._norm_grade

    def set_norm_grade(self, grade_name: str) -> None:
        self._norm_grade = grade_name or ""
        self._update_norm_dot()

    def set_norms_visible(self, visible: bool) -> None:
        """The «Нормы» switch (UD-14: off by default, UQ-03: remembered)."""
        self._norms_visible = bool(visible)
        self._update_norm_dot()

    def _update_norm_dot(self) -> None:
        if not self._norms_visible or not self._norm_grade:
            self._dot.hide()
            return
        colors = grade_colors(self._norm_grade)
        if colors is None:
            self._dot.hide()
            return
        # The solid half of the pair: a dot has no room for a tinted fill.
        self._dot.setStyleSheet(f"background: {colors[1]}; border-radius: 3px;")
        self._dot.show()

    def set_status(self, glyph: str, tooltip: str = "") -> None:
        """Override the state glyph (stale, QC warning, locked …).

        A «req:<token>» reason is a key of the tool status, not a sentence: it
        gated the tool and stays there (``application/tool_status.py``), while
        the row shows it as the lock glyph only (ТЗ 2026-10-23, п. 3).
        """
        self._glyph.setText(glyph)
        if not tooltip or tooltip.startswith("req:"):
            return
        if tooltip in self._tooltip_text:
            return
        self._tooltip_text = f"{self._tooltip_text}\n{tooltip}"
        if not self._tooltip_suppressed:
            self.setToolTip(self._tooltip_text)

    # ── Activation ─────────────────────────────────────────────────

    def _activate(self) -> None:
        if self._available and not self._edit_mode:
            self.activated.emit(self.tool.id)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._edit_mode and event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.position().toPoint()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if (
            self._edit_mode
            and self._drag_origin is not None
            and event.buttons() & Qt.MouseButton.LeftButton
            and (event.position().toPoint() - self._drag_origin).manhattanLength() >= QApplication.startDragDistance()
        ):
            self._drag_origin = None
            mime = QMimeData()
            mime.setData(TOOL_MIME, self.tool.id.encode("utf-8"))
            drag = QDrag(self)
            drag.setMimeData(mime)
            drag.exec(Qt.DropAction.MoveAction)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._edit_mode:
            self._drag_origin = None
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self._activate()
        super().mouseReleaseEvent(event)

    # ── The S2 card gestures (UI-5, §4.7) ──────────────────────────

    def _emit_reference_request(self) -> None:
        self.reference_requested.emit(self.tool.id)

    def anchor_rect(self) -> QRect:
        """The row in global coordinates — the placement anchor of the card."""
        return QRect(self.mapToGlobal(QPoint(0, 0)), self.size())

    def enterEvent(self, event) -> None:  # noqa: N802
        self.pointer_entered.emit(self.tool.id)
        self._hover_timer.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover_timer.stop()
        self.reference_hide_requested.emit(self.tool.id)
        super().leaveEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event_matches_shortcut(event, "reference_card"):
            self._emit_reference_request()
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self._activate()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape:
            # Stage 0 of Esc (TP §6.2): close the S2 card first — only then
            # the event falls through to cancel_tool and the protocol stops.
            card = self._reference_card()
            if card is not None and card.isVisible():
                self._hover_timer.stop()
                card.hide()
                event.accept()
            return
        super().keyPressEvent(event)

    def _reference_card(self):
        """The S2 card the panel hosts for the rows, or ``None``."""
        from echo_personal_tool.presentation.reference_card import ReferenceCard

        parent = self.parentWidget()
        while parent is not None:
            card = parent.findChild(ReferenceCard, "referenceCard")
            if card is not None:
                return card
            parent = parent.parentWidget()
        return None


def favorite_key_badge(tool: ToolSpec, favorite: int | None) -> str:
    """Badge of a row: the favourite number wins over the catalog shortcut."""
    if favorite is not None:
        return str(favorite + 1)
    return tool.default_key or ""


class ToolSection(TokenRestyleMixin, QWidget):
    """Expandable section; several sections can be open at once (§4.2)."""

    toggled = Signal(bool)
    #: TP-5: a tool was dropped into this section at ``index``.
    tool_dropped = Signal(str, int)

    def __init__(
        self,
        key: str,
        title: str,
        rows: list[ToolRow],
        *,
        expanded: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("toolPanelSection")
        self.key = key
        self._title = title
        self._expanded = bool(expanded)
        self._rows = rows
        self._edit_mode = False

        self._header = QPushButton(self._header_text())
        self._header.setObjectName("toolPanelSectionHeader")
        self._header.setFlat(True)
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header.setCheckable(True)
        self._header.setChecked(self._expanded)
        self._header.clicked.connect(self._on_header_clicked)

        #: Progress «2/9» — measured tools of the section; the label is not a
        #: click target, the whole row header toggles (§4.2).
        self._progress = QLabel(self._progress_text())
        self._progress.setObjectName("toolPanelSectionProgress")
        self._progress.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._progress.setStyleSheet(f"color: {get_theme_tokens()['text.3']};")
        header_row = QWidget()
        header_row.setObjectName("toolPanelSectionHeaderRow")
        header_layout = QHBoxLayout(header_row)
        header_layout.setContentsMargins(0, 0, 4, 0)
        header_layout.setSpacing(4)
        header_layout.addWidget(self._header, 1)
        header_layout.addWidget(self._progress)

        self._body = QWidget()
        body_layout = QVBoxLayout(self._body)
        body_layout.setContentsMargins(4, 0, 4, 2)
        body_layout.setSpacing(1)
        for row in rows:
            body_layout.addWidget(row)
            row.value_changed.connect(self._update_progress)
        self._body.setVisible(self._expanded)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(header_row)
        layout.addWidget(self._body)
        self._apply_style()

    def _header_text(self) -> str:
        chevron = "▼" if self._expanded else "▶"
        return f"{chevron}  {self._title}"

    def _progress_text(self) -> str:
        done = sum(1 for row in self._rows if row.has_value())
        return f"{done}/{len(self._rows)}"

    def _apply_style(self) -> None:
        tokens = get_theme_tokens()
        self.setStyleSheet(
            f"""
            #toolPanelSectionHeader {{
                text-align: left;
                padding: 5px 4px;
                border: none;
                color: {tokens["text.2"]};
                font-weight: 600;
            }}
            #toolPanelSectionHeaderRow {{
                border-bottom: 1px solid {tokens["line.1"]};
            }}
            #toolPanelSectionHeader:hover {{
                background: {tokens["surface.3"]};
                color: {tokens["text.1"]};
            }}
            """
        )

    def _on_header_clicked(self) -> None:
        self.set_expanded(not self._expanded)

    def _update_progress(self) -> None:
        self._progress.setText(self._progress_text())

    def set_edit_mode(self, enabled: bool) -> None:
        self._edit_mode = bool(enabled)
        self.setAcceptDrops(self._edit_mode)

    def edit_mode(self) -> bool:
        return self._edit_mode

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if self._edit_mode and event.mimeData().hasFormat(TOOL_MIME):
            event.acceptProposedAction()
            if not self._expanded:
                self.set_expanded(True)
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802
        if self._edit_mode and event.mimeData().hasFormat(TOOL_MIME):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        if not self._edit_mode or not event.mimeData().hasFormat(TOOL_MIME):
            super().dropEvent(event)
            return
        tool_id = bytes(event.mimeData().data(TOOL_MIME)).decode("utf-8")
        position = self._body.mapFrom(self, event.position().toPoint())
        index = len(self._rows)
        for row_index, row in enumerate(self._rows):
            if position.y() < row.geometry().center().y():
                index = row_index
                break
        self.tool_dropped.emit(tool_id, index)
        event.acceptProposedAction()

    def progress(self) -> tuple[int, int]:
        """Measured tools of the section and its total («2 из 9»)."""
        return (sum(1 for row in self._rows if row.has_value()), len(self._rows))

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = bool(expanded)
        self._header.setChecked(self._expanded)
        self._header.setText(self._header_text())
        self._body.setVisible(self._expanded)
        self.toggled.emit(self._expanded)

    def is_expanded(self) -> bool:
        return self._expanded

    def rows(self) -> tuple[ToolRow, ...]:
        return tuple(self._rows)

    def row(self, tool_id: str) -> ToolRow | None:
        for row in self._rows:
            if row.tool.id == tool_id:
                return row
        return None
