"""Sections and tool rows of the measurement panel 2.0.

A row is deliberately not a ``QPushButton``: the panel shows a type glyph, a
label, a value and a keyboard badge on one line, and keeps the full name in
the tooltip.  The row stays keyboard reachable (Tab, Space/Enter) so the
whole panel can be driven without a mouse (A-13, TP-2 PR-2 extends this to
``/`` and the 1–9 favourites).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.domain.measurement_catalog import ToolSpec
from echo_personal_tool.presentation.dark_theme import get_theme_tokens
from echo_personal_tool.presentation.ui_metrics import control_height

#: Glyphs of the row states (§4.3).  The glyph is never the only signal: the
#: value text and the tooltip carry the same state.
STATE_NOT_STARTED = "○"
STATE_DONE = "✓"
STATE_ACTIVE = "◉"
STATE_STALE = "⟳"
STATE_WARNING = "⚠"
STATE_LOCKED = "🔒"


class ToolRow(QFrame):
    """One tool of a section: glyph, label, value, badge."""

    activated = Signal(str)

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
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setProperty("active", False)
        self.setProperty("available", True)

        label = tool.label(language)
        self._glyph = QLabel(STATE_NOT_STARTED)
        self._glyph.setObjectName("toolRowGlyph")
        self._title = QLabel(label.short)
        self._title.setObjectName("toolRowLabel")
        self._title.setWordWrap(True)
        self._value = QLabel("—")
        self._value.setObjectName("toolRowValue")
        self._value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._value.setMinimumWidth(42)
        self._badge = QLabel(favorite_key_badge(tool, favorite))
        self._badge.setObjectName("toolRowBadge")
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.setMinimumWidth(18)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 1, 4, 1)
        layout.setSpacing(4)
        layout.addWidget(self._glyph)
        layout.addWidget(self._title, 1)
        layout.addWidget(self._value)
        layout.addWidget(self._badge)

        self.setToolTip(self._tooltip(label))
        self._apply_style()
        self.setMinimumHeight(control_height(self, padding=6, minimum=22))

    # ── Appearance ─────────────────────────────────────────────────

    def _tooltip(self, label) -> str:
        parts = [label.full]
        if self.tool.requires:
            parts.append(", ".join(sorted(self.tool.requires)))
        return "\n".join(parts)

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

    def set_value(self, text: str) -> None:
        """Show a result (TP-2 PR-2 wires the status provider)."""
        self._value.setText(text or "—")
        self._has_value = bool(text)
        if not self._active:
            self._glyph.setText(STATE_DONE if self._has_value else STATE_NOT_STARTED)

    def set_status(self, glyph: str, tooltip: str = "") -> None:
        """Override the state glyph (stale, QC warning, locked …)."""
        self._glyph.setText(glyph)
        if tooltip:
            self.setToolTip(self.toolTip() + "\n" + tooltip)

    # ── Activation ─────────────────────────────────────────────────

    def _activate(self) -> None:
        if self._available:
            self.activated.emit(self.tool.id)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self._activate()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self._activate()
            event.accept()
            return
        super().keyPressEvent(event)


def favorite_key_badge(tool: ToolSpec, favorite: int | None) -> str:
    """Badge of a row: the favourite number wins over the catalog shortcut."""
    if favorite is not None:
        return str(favorite + 1)
    return tool.default_key or ""


class ToolSection(QWidget):
    """Expandable section; several sections can be open at once (§4.2)."""

    toggled = Signal(bool)

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

        self._header = QPushButton(self._header_text())
        self._header.setObjectName("toolPanelSectionHeader")
        self._header.setFlat(True)
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header.setCheckable(True)
        self._header.setChecked(self._expanded)
        self._header.clicked.connect(self._on_header_clicked)

        self._body = QWidget()
        body_layout = QVBoxLayout(self._body)
        body_layout.setContentsMargins(4, 0, 4, 2)
        body_layout.setSpacing(1)
        for row in rows:
            body_layout.addWidget(row)
        self._body.setVisible(self._expanded)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._header)
        layout.addWidget(self._body)
        self._apply_style()

    def _header_text(self) -> str:
        chevron = "▼" if self._expanded else "▶"
        return f"{chevron}  {self._title}"

    def _apply_style(self) -> None:
        tokens = get_theme_tokens()
        self.setStyleSheet(
            f"""
            #toolPanelSectionHeader {{
                text-align: left;
                padding: 5px 4px;
                border: none;
                border-bottom: 1px solid {tokens["line.1"]};
                color: {tokens["text.2"]};
                font-weight: 600;
            }}
            #toolPanelSectionHeader:hover {{
                background: {tokens["surface.3"]};
                color: {tokens["text.1"]};
            }}
            """
        )

    def _on_header_clicked(self) -> None:
        self.set_expanded(not self._expanded)

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
