"""One-line chips for every button of the measure panel.

The panel used to paint its captions on two forced lines: a shortened name on
the first line and a number (the favourite key or the section's tool count) on
the second.  At 280–320 px the first line needed an `ElideMiddle` cut that
turned «LV-sequence» into «LV-S…ence», and the second line made the number look
like a measured value.  In edit mode a third row of controls squeezed the same
caption even further.

A chip is now:

* **one line** of text, elided on the right only, with the complete name in the
  tooltip and the accessible name;
* a compact **badge** at the right edge for the key/count, drawn as a child
  label so it cannot be mistaken for a value and cannot wrap the caption;
* one height, one radius and one border shared with the other buttons of the
  shell (see :mod:`presentation.theme.controls`).

The public helpers keep the old callers simple: ``set_chip_content()`` sets the
full strings, ``fit()`` re-elides for a cell width, ``label_text()`` /
``badge_text()`` expose the uncut strings for tests and accessibility.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtWidgets import QLabel, QPushButton, QSizePolicy, QWidget

from echo_personal_tool.presentation.theme.controls import (
    BADGE_RADIUS,
    CHIP_HEIGHT,
    CHIP_PAD_X,
    GAP_XS,
    button_qss,
)
from echo_personal_tool.presentation.ui_metrics import control_height

_BADGE_MIN_WIDTH = 18


class PanelChipButton(QPushButton):
    """A single-line panel button with a right-aligned badge."""

    def __init__(
        self,
        label: str,
        badge: str = "",
        *,
        object_name: str = "panelTileButton",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName(object_name)
        self._label = str(label or "")
        self._badge = str(badge or "")
        self._badge_label = QLabel(self._badge, self)
        self._badge_label.setObjectName("panelChipBadge")
        self._badge_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._badge_label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_height()
        self._apply_badge_style()
        self._fit()

    # ── content ────────────────────────────────────────────────────

    def set_chip_content(self, label: str, badge: str = "") -> None:
        self._label = label
        self._badge = badge
        self._badge_label.setText(badge)
        self._badge_label.setVisible(bool(badge))
        self._fit()

    def label_text(self) -> str:
        return self._label

    def badge_text(self) -> str:
        return self._badge

    def full_text(self) -> str:
        return f"{self._label} · {self._badge}" if self._badge else self._label

    def fit(self, available_width: int | None = None) -> None:
        """Elide the caption into the cell; the badge keeps its own room."""
        width = self.width() if available_width is None else max(0, int(available_width))
        self._fit(width)

    def sizeHint(self) -> QSize:  # noqa: N802
        hint = super().sizeHint()
        return QSize(hint.width(), self._chip_height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, self._chip_height())

    # ── geometry ───────────────────────────────────────────────────

    def _chip_height(self) -> int:
        return max(CHIP_HEIGHT, control_height(self, padding=12))

    def _apply_height(self) -> None:
        self.setFixedHeight(self._chip_height())

    def _badge_width(self) -> int:
        if not self._badge:
            return 0
        metrics = self._badge_label.fontMetrics()
        return max(_BADGE_MIN_WIDTH, metrics.horizontalAdvance(self._badge) + 10)

    def _apply_badge_style(self) -> None:
        from echo_personal_tool.presentation.dark_theme import get_theme_tokens

        tokens = get_theme_tokens()
        small = max(9, self.font().pixelSize() - 2)
        self._badge_label.setStyleSheet(
            f"QLabel#panelChipBadge {{ background: {tokens['surface.3']}; "
            f"color: {tokens['text.2']}; border-radius: {BADGE_RADIUS}px; "
            f"padding: 0 4px; font-size: {small}px; }}"
        )
        self.setStyleSheet(
            button_qss(
                f"QPushButton#{self.objectName()}",
                tokens,
                variant="chip",
                height=None,
                padding_x=CHIP_PAD_X,
                padding_y=4,
                font_size=max(11, self.font().pixelSize() - 1),
                text_align="left",
            )
        )

    def _fit(self, width: int | None = None) -> None:
        # The badge is positioned from the *real* geometry: a reflow passes a
        # cell width that can differ from the widget width, and a badge placed
        # at that width used to land outside the button and disappear.
        box = max(0, self.width())
        label_box = box if width is None else min(box, max(0, int(width)))
        badge_w = self._badge_width()
        badge_h = min(max(16, self.height() - 8), max(16, self._badge_label.fontMetrics().height() + 4))
        if badge_w:
            self._badge_label.setGeometry(
                max(0, box - badge_w - GAP_XS),
                max(0, (self.height() - badge_h) // 2),
                badge_w,
                badge_h,
            )
            self._badge_label.raise_()
        self._badge_label.setVisible(bool(self._badge))
        icon_w = self.iconSize().width() + 4 if not self.icon().isNull() else 0
        room = max(0, label_box - 2 * CHIP_PAD_X - badge_w - GAP_XS - icon_w - 2)
        elided = self.fontMetrics().elidedText(self._label, Qt.TextElideMode.ElideRight, room)
        if self.text() != elided:
            super().setText(elided)

    # ── events ─────────────────────────────────────────────────────

    def setText(self, text: str) -> None:  # type: ignore[override]  # noqa: N802
        """A plain setText from a caller re-fits the chip, never wraps it."""
        self._label = text
        self._fit()

    def resizeEvent(self, event) -> None:  # type: ignore[override]  # noqa: N802
        super().resizeEvent(event)
        self._fit()

    def event(self, event: QEvent) -> bool:
        handled = super().event(event)
        if event.type() in (QEvent.Type.Polish, QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._apply_height()
            self._fit()
        return handled
