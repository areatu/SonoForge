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
from PySide6.QtGui import QDrag, QDragEnterEvent, QDragMoveEvent, QDropEvent, QKeyEvent, QMouseEvent, QWheelEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.domain.measurement_catalog import ToolSpec
from echo_personal_tool.keyboard_shortcuts import event_matches_shortcut, shortcut_label
from echo_personal_tool.presentation.reference_card import HOVER_DELAY_MS
from echo_personal_tool.presentation.reference_grades import grade_colors
from echo_personal_tool.presentation.theme.controls import (
    GAP_XS,
    LIST_ROW_HEIGHT,
    SECTION_HEADER_HEIGHT,
    SPACE_LG,
    SPACE_MD,
    SPACE_SM,
    SPACE_XS,
    button_qss,
    list_row_qss,
)
from echo_personal_tool.presentation.theme.token_restyle import TokenRestyleMixin
from echo_personal_tool.presentation.tooltip_text import wrapped_tooltip
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


def tool_row_qss(tokens, scale) -> str:
    """One stylesheet for every tool row, with state expressed as properties."""
    return (
        list_row_qss("#toolRow", tokens)
        + f"""
        #toolRowGlyph {{
            color: {tokens["text.3"]};
            min-width: 12px;
            max-width: 12px;
            font-size: {scale["meta"]}px;
        }}
        #toolRowLabel {{
            color: {tokens["text.1"]};
            font-size: {scale["body"]}px;
        }}
        #toolRowValue {{
            color: {tokens["text.2"]};
            font-size: {scale["small"]}px;
        }}
        #toolRow[available="false"] #toolRowLabel,
        #toolRow[available="false"] #toolRowValue {{
            color: {tokens["text.disabled"]};
        }}
        #toolRow[active="true"] #toolRowLabel {{
            color: {tokens["accent.text"]};
        }}
        #toolRowBadge {{
            color: {tokens["text.3"]};
            background: transparent;
            padding: 0;
            font-size: {scale["meta"]}px;
        }}
        #toolRowNormDot {{
            background: {tokens["surface.3"]};
        }}
        """
        + button_qss(
            ("QPushButton#toolRowFavorite", "QPushButton#toolRowVisibility"),
            tokens,
            variant="ghost",
            height=None,
            padding_x=2,
            padding_y=0,
        )
    )


def tool_section_qss(tokens, scale) -> str:
    """Shared section chrome; individual sections only adjust their metrics."""
    return f"""
        #toolPanelSectionHeader {{
            text-align: left;
            padding: 5px 4px;
            border: none;
            color: {tokens["text.2"]};
            font-weight: 600;
            font-size: {scale["small"]}px;
        }}
        #toolPanelSectionHeader:hover {{
            background: {tokens["surface.3"]};
            color: {tokens["text.1"]};
        }}
        #toolPanelSectionTitle {{
            text-align: left;
            padding: 0;
            border: none;
            background: transparent;
            color: {tokens["text.1"]};
            font-weight: 600;
            font-size: {scale["body"]}px;
        }}
        #toolPanelSectionTitle:hover {{
            background: transparent;
            color: {tokens["text.1"]};
        }}
        #toolPanelSectionHeaderRow {{
            border-bottom: none;
        }}
        #toolPanelSectionProgress {{
            color: {tokens["text.3"]};
        }}
    """


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
        self._title_text = label.short
        self._title = QLabel(label.short)
        self._title.setObjectName("toolRowLabel")
        # One line, elided on the right: a wrapped caption on a 100 px cell was
        # the main complaint of the 2026-10-27 acceptance list.  The complete
        # name lives in the tooltip and the accessible name.
        self._title.setWordWrap(False)
        self._title.setMinimumWidth(0)
        self._title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._dot = QLabel(self)
        self._dot.setObjectName("toolRowNormDot")
        self._dot.setFixedSize(7, 7)
        self._dot.hide()
        self._value = QLabel("—")
        self._value.setObjectName("toolRowValue")
        self._value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._value.setMinimumWidth(40)
        self._badge = QLabel(favorite_key_badge(tool, favorite))
        self._badge.setObjectName("toolRowBadge")
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.setMinimumWidth(14)
        self._badge.setMaximumWidth(24)

        self._drag_handle = QLabel("⠿")
        self._drag_handle.setObjectName("toolRowDragHandle")
        self._drag_handle.setCursor(Qt.CursorShape.OpenHandCursor)
        self._drag_handle.setToolTip("")
        self._drag_handle.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._favorite_button = QPushButton("☆")
        self._favorite_button.setObjectName("toolRowFavorite")
        self._favorite_button.setFlat(True)
        self._favorite_button.setFixedWidth(24)
        self._favorite_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._favorite_button.clicked.connect(lambda: self.edit_favorite_requested.emit(self.tool.id))
        self._visibility_button = QPushButton("👁")
        self._visibility_button.setObjectName("toolRowVisibility")
        self._visibility_button.setFlat(True)
        self._visibility_button.setFixedWidth(24)
        self._visibility_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._visibility_button.clicked.connect(lambda: self.edit_visibility_requested.emit(self.tool.id))
        for control in (self._drag_handle, self._favorite_button, self._visibility_button):
            control.hide()

        # One line of text, like a row of a clinical worksheet: glyph, name,
        # value, badge.  The row used to keep a second line under the caption
        # even when it was empty (the «непонятная вторая строка» of the
        # 2026-10-27 list): the value edits were stacked below the name, so
        # every tool looked like a two-storey button.  A missing value is now
        # a dash at the right edge of the same line — the row keeps its shape
        # whether the measurement exists or not.
        layout = QHBoxLayout(self)
        # The row's text starts on the panel's gutter; the hover fill and the
        # rule may bleed to the panel's edge, which is what makes a list read as
        # a list instead of a stack of boxes.
        layout.setContentsMargins(SPACE_LG, GAP_XS, SPACE_LG, GAP_XS)
        layout.setSpacing(SPACE_SM)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self._glyph)
        layout.addWidget(self._dot)
        layout.addWidget(self._title, 1)
        layout.addWidget(self._badge)
        layout.addWidget(self._value)
        layout.addWidget(self._drag_handle)
        layout.addWidget(self._favorite_button)
        layout.addWidget(self._visibility_button)

        # Visibility is decided *after* the layout took the widgets over: a
        # setVisible(True) on a parentless label would create a top-level
        # window for one event loop tick (the flash of N-07).
        self._badge.setVisible(bool(self._badge.text()))
        self._value.setVisible(not self._edit_mode if hasattr(self, "_edit_mode") else True)

        self._tooltip_text = self._tooltip(label)
        self._base_tooltip_text = self._tooltip_text
        self._tooltip_suppressed = False
        self.setToolTip(wrapped_tooltip(self._tooltip_text))
        # The full name also rides on the accessible name: the tooltip is
        # silenced while the reference card is up, and a screen reader must
        # still get the title of the row.
        self.setAccessibleName(label.full)
        self._apply_style()

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
        # The row QSS is shared by the panel (see tool_row_qss).  Re-parsing a
        # private sheet for every row made each context swap restyle the whole
        # subtree several times; availability is a QSS property instead.
        # A single-line elided QLabel must still keep one line of height: a
        # squeezed cell used to flatten it to 8 px at large fonts.
        self._title.setMinimumHeight(max(14, self._title.fontMetrics().height() + 2))
        self._fit_title()
        # One pitch for the whole list: the row, the section caption and the
        # chips share it, so a list cannot end up with 41 px rows under a 30 px
        # header (2026-10-25) or a 4 px gap where the design has 8.
        self.setMinimumHeight(max(LIST_ROW_HEIGHT, control_height(self, padding=10, minimum=26)))

    def resizeEvent(self, event) -> None:  # type: ignore[override]  # noqa: N802
        super().resizeEvent(event)
        self._fit_title()

    def _fit_title(self) -> None:
        """Elide the caption into the column, never wrap or clip it mid-word."""
        if not hasattr(self, "_title_text"):
            return
        width = max(0, self._title.width())
        elided = self._title.fontMetrics().elidedText(self._title_text, Qt.TextElideMode.ElideRight, width)
        if self._title.text() != elided:
            self._title.setText(elided)

    def set_available(self, available: bool) -> None:
        """Disable a tool the current clip cannot run (no time scale, no vessel)."""
        if available == self._available:
            return
        self._available = available
        self.setProperty("available", available)
        self.setCursor(Qt.CursorShape.PointingHandCursor if available else Qt.CursorShape.ArrowCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus if available else Qt.FocusPolicy.NoFocus)
        # The shared panel sheet selects on this property; refresh the state
        # without assigning a new stylesheet to the whole row subtree.
        self.style().unpolish(self)
        self.style().polish(self)
        self._apply_style()

    def is_available(self) -> bool:
        return self._available

    # ── In-place editing (TP-5) ────────────────────────────────────

    def set_edit_mode(self, enabled: bool, *, favorite: bool = False, visible: bool = True) -> None:
        self._edit_mode = bool(enabled)
        self.setProperty("editMode", self._edit_mode)
        self._is_favorite = bool(favorite)
        self._is_visible = bool(visible)
        # The customize controls replace the value and the key badge of the
        # same line: the row is one line in both modes, so the caption never
        # loses width to a second storey (2026-10-27 list, item 3).
        for control in (self._drag_handle, self._favorite_button, self._visibility_button):
            control.setVisible(self._edit_mode)
        self._value.setVisible(not self._edit_mode)
        self._badge.setVisible(not self._edit_mode and bool(self._badge.text()))
        self._fit_title()
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
            self.setToolTip(wrapped_tooltip(self._tooltip_text))

    def prepare_for_reuse(self) -> None:
        """Detach from a retired section without losing the catalogue identity.

        Context changes reuse rows instead of deleting hundreds of widgets in
        the middle of input delivery.  Stop hover work before reparenting: a
        queued reference-card request must not point at a retired section.
        """
        self._hover_timer.stop()
        self._drag_origin = None
        self.set_active(False)
        self.set_value("", key="")
        self._measurement_key = ""
        self.set_norm_grade("")
        self._tooltip_text = self._base_tooltip_text
        self._tooltip_suppressed = False
        self.setToolTip(wrapped_tooltip(self._tooltip_text))
        self.hide()

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        # The gesture belongs to the surrounding page.  Do not open a norm card
        # for each row that happens to pass under a stationary pointer.
        self._hover_timer.stop()
        self.reference_hide_requested.emit(self.tool.id)
        event.ignore()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._hover_timer.stop()
        super().hideEvent(event)

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
        return shortcut_label(f"favorite_{favorite + 1}")
    return shortcut_label("caliper") if tool.id == "tool.caliper" else (tool.default_key or "")


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
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.key = key
        self._title = title
        self._expanded = bool(expanded)
        self._rows = rows
        self._edit_mode = False
        self._columns = 1
        self._caption_mode = False

        self._header = QPushButton(self._header_text(), self)
        self._header.setObjectName("toolPanelSectionHeader")
        self._header.setFlat(True)
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header.setCheckable(True)
        self._header.setChecked(self._expanded)
        self._header.clicked.connect(self._on_header_clicked)

        #: Progress «2/9» — measured tools of the section; the label is not a
        #: click target, the whole row header toggles (§4.2).
        self._progress = QLabel(self._progress_text(), self)
        self._progress.setObjectName("toolPanelSectionProgress")
        self._progress.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header_row = QWidget(self)
        header_row.setObjectName("toolPanelSectionHeaderRow")
        self._header_row = header_row
        header_layout = QHBoxLayout(header_row)
        header_layout.setContentsMargins(SPACE_MD, 0, SPACE_MD, 0)
        header_layout.setSpacing(SPACE_SM)
        header_layout.addWidget(self._header, 1)
        header_layout.addWidget(self._progress)

        # Never show an unparented body: setVisible(True) below used to create
        # a short-lived native white window on Windows at every context swap.
        self._body = QWidget(self)
        body_layout = QGridLayout(self._body)
        body_layout.setContentsMargins(0, SPACE_XS, 0, 0)
        body_layout.setSpacing(0)
        # Column 0 owns the whole width: the row is a list entry, and two empty
        # stretched columns would shrink every name to three characters.
        for column in range(3):
            body_layout.setColumnStretch(column, 1 if column == 0 else 0)
        for index, row in enumerate(rows):
            body_layout.addWidget(row, index, 0)
            row.value_changed.connect(self._update_progress)
        self._body.setVisible(self._expanded)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(header_row)
        layout.addWidget(self._body)
        self._apply_style()

    def columns(self) -> int:
        """Number of tool cells per row (adaptive, never wraps a caption)."""
        return self._columns

    def set_columns(self, columns: int) -> None:
        """Reflow the rows; the list form keeps a single column.

        The section is a worksheet list (a rule per row, the value on the right
        edge), not a grid of tiles: two columns of a list would split the
        names and their values into two unrelated columns.  ``columns`` stays
        in the API because the panel and its tests ask a section how wide its
        grid is; more than one column is simply not drawn.
        """
        columns = 1 if self._caption_mode else max(1, min(3, int(columns)))
        if columns == self._columns:
            return
        self._columns = columns
        layout = self._body.layout()
        # Qt does not *move* a widget that is already in a grid: remove every
        # row first, then place it in the new cell.
        for row in self._rows:
            layout.removeWidget(row)
        for column in range(3):
            layout.setColumnStretch(column, 1 if column < columns else 0)
        for index, row in enumerate(self._rows):
            layout.addWidget(row, index // columns, index % columns)
        # Removing and re-adding in one pass leaves the cached cell geometries
        # valid in Qt's eyes: an explicit invalidation is needed or the rows
        # keep the old three-column positions until the next resize.
        layout.invalidate()
        layout.activate()
        self._body.updateGeometry()
        self.updateGeometry()

    def _header_text(self) -> str:
        if self._caption_mode:
            return self._title
        chevron = "▼" if self._expanded else "▶"
        return f"{chevron}  {self._title}"

    def set_caption_mode(self, enabled: bool = True) -> None:
        """Draw the section as a caption over a list instead of a fold-out.

        The panel uses the anatomy chips as tabs and shows exactly one group:
        a chevron that folds nothing would be a lie, and a bare list under the
        chips read as their continuation (2026-10-27 list, item 2: «слишком
        маленькое расстояние, нет общего дизайна»).  In this mode the section
        shows the name of the open group and its progress as a small caption —
        the same 26 px caption over every block of the panel — and the rows
        become a one-column list.
        """
        self._caption_mode = bool(enabled)
        self._header.setCheckable(not self._caption_mode)
        self._header.setCursor(
            Qt.CursorShape.PointingHandCursor if not self._caption_mode else Qt.CursorShape.ArrowCursor
        )
        self._header.setText(self._header_text())
        self._header.setObjectName("toolPanelSectionTitle" if self._caption_mode else "toolPanelSectionHeader")
        self._columns = 1 if self._caption_mode else self._columns
        self._apply_style()

    def _progress_text(self) -> str:
        done = sum(1 for row in self._rows if row.has_value())
        return f"{done}/{len(self._rows)}"

    def _apply_style(self) -> None:
        # Shared, panel-level QSS: section shells no longer each own a sheet.
        # Match the row pitch with the same font-derived formula.
        if self._caption_mode:
            self._header.setMinimumHeight(
                max(SECTION_HEADER_HEIGHT, control_height(self._header, padding=8, minimum=22))
            )
        else:
            self._header.setMinimumHeight(control_height(self._header, padding=10, minimum=30))

    def _on_header_clicked(self) -> None:
        if self._caption_mode:
            return
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
            rect = row.geometry()
            if position.y() < rect.top() or (position.y() <= rect.bottom() and position.x() < rect.center().x()):
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
