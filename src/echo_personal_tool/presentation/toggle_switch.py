"""Pill toggle switch of the ui-redesign (mockup ``common.toggle()``).

A ``QCheckBox`` indicator cannot express the mockup's geometry — a 28 × 16
pill with a round knob that slides — in QSS, so the control is painted with
``QPainter`` from theme tokens like the other custom chrome of the panel.

Presentation only: the widget owns a boolean and emits ``toggled``; the caller
decides what the switch means (auto-advance, «Нормы», …).
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from echo_personal_tool.presentation.dark_theme import get_theme_tokens

#: Geometry of the mockup toggle: 28 × 16, knob radius = h/2 − 2.5.
TOGGLE_WIDTH = 28
TOGGLE_HEIGHT = 16
KNOB_INSET = 2.5


class ToggleSwitch(QWidget):
    """On/off pill switch drawn from theme tokens."""

    toggled = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("toggleSwitch")
        self._checked = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(self.tr("Switch"))

    def sizeHint(self):  # noqa: ANN201 - Qt signature
        return self.minimumSizeHint()

    def minimumSizeHint(self):  # noqa: ANN201 - Qt signature
        from PySide6.QtCore import QSize

        return QSize(TOGGLE_WIDTH, TOGGLE_HEIGHT)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool, *, emit: bool = False) -> None:
        checked = bool(checked)
        if checked == self._checked:
            return
        self._checked = checked
        self.update()
        self.setAccessibleState(checked)
        if emit:
            self.toggled.emit(checked)

    def set_checked(self, checked: bool) -> None:
        """Panel-friendly alias of :meth:`setChecked` (no signal)."""
        self.setChecked(checked, emit=False)

    def setAccessibleState(self, checked: bool) -> None:  # noqa: N802 - Qt name
        base = self.accessibleName() or self.tr("Switch")
        state = self.tr("on") if checked else self.tr("off")
        self.setAccessibleDescription(f"{base}: {state}")

    def toggle(self) -> None:
        self.setChecked(not self._checked, emit=True)

    # ── Interaction ────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:  # noqa: ANN001, N802 - Qt
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle()
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: ANN001, N802 - Qt
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Enter, Qt.Key.Key_Return):
            self.toggle()
            event.accept()
            return
        super().keyPressEvent(event)

    # ── Painting ───────────────────────────────────────────────

    def paintEvent(self, event) -> None:  # noqa: ANN001, N802 - Qt
        tokens = get_theme_tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = rect.height() / 2.0
        if self._checked:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(tokens["accent"]))
            painter.drawRoundedRect(rect, radius, radius)
        else:
            painter.setPen(QPen(QColor(tokens["line.2"]), 1.0))
            painter.setBrush(QColor(tokens["surface.3"]))
            painter.drawRoundedRect(rect, radius, radius)

        knob_radius = rect.height() / 2.0 - KNOB_INSET
        if self._checked:
            center = QPoint(int(rect.right() - knob_radius - KNOB_INSET), int(rect.center().y()))
        else:
            center = QPoint(int(rect.left() + knob_radius + KNOB_INSET), int(rect.center().y()))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(tokens["control.knob"]))
        painter.drawEllipse(center, knob_radius, knob_radius)

        if self.hasFocus():
            focus = QColor(tokens["focus.ring"])
            focus.setAlpha(160)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(focus, 1.5))
            painter.drawRoundedRect(rect.adjusted(-2, -2, 2, 2), radius + 2, radius + 2)
        painter.end()
