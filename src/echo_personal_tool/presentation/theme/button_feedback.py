"""Animated hover / press feedback for *existing* buttons.

Qt stylesheets have no transitions: a ``:hover`` rule snaps from one colour to
another in a single frame, and a rule with the same colour as the resting state
(the settings «Готово» had exactly that) gives no feedback at all.  A custom
``QPushButton`` subclass cannot fix buttons that other modules already created,
and repainting a button from scratch would throw away its stylesheet.

So the feedback is a styled child widget painted *over* the button:

* the button keeps its QSS (and its icon, text, menu and accessibility name);
* the overlay is one rounded, accent-tinted layer.  A ``QGraphicsOpacityEffect``
  fades it in on hover (110 ms) and further on press (80 ms), so the wash is
  composited by Qt instead of relying on an ARGB child backing store (which is
  opaque-black on some Windows styles);
* the overlay is transparent to mouse events and never takes focus, so the
  click and the QSS ``:hover`` / ``:pressed`` rules still reach the button;
* ``reduce_motion`` disables the interpolation, not the feedback — the end
  state is applied immediately.

One instance per button, parented to the button, so closing a dialog cannot
leave an animation alive.  ``install()`` is idempotent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Property, QEvent, QObject, QPropertyAnimation, Qt, Signal
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

from echo_personal_tool.presentation.theme.controls import BUTTON_RADIUS

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterable

    from PySide6.QtWidgets import QAbstractButton

_HOVER_MS = 110
_PRESS_MS = 80
#: Effect opacity at full hover / at full press (0–1).
_HOVER_OPACITY = 0.30
_PRESS_OPACITY = 0.26


def _reduce_motion() -> bool:
    try:
        from echo_personal_tool.presentation.ui_animations import _reduce_motion_enabled

        return _reduce_motion_enabled()
    except Exception:  # noqa: BLE001 - a missing preference must not break a click
        return False


class _FeedbackOverlay(QWidget):
    """A rounded translucent wash over the parent button."""

    def __init__(self, button: QAbstractButton) -> None:
        super().__init__(button)
        from echo_personal_tool.presentation.dark_theme import get_theme_tokens
        from echo_personal_tool.presentation.theme.palettes import blend

        tokens = get_theme_tokens()
        self.setObjectName("buttonFeedbackOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setGeometry(button.rect())
        tint = blend(tokens["accent"], tokens["surface.2"], 0.14)
        edge = blend(tokens["accent"], tokens["surface.2"], 0.62)
        self.setStyleSheet(
            f"QWidget#buttonFeedbackOverlay {{ background: {tint}; "
            f"border: 1px solid {edge}; border-radius: {BUTTON_RADIUS}px; }}"
        )
        self._effect: QGraphicsOpacityEffect | None = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)
        self._hover = 0.0
        self._press = 0.0

    def hover_level(self) -> float:
        return self._hover

    def set_hover_level(self, value: float) -> None:
        self._hover = max(0.0, min(1.0, float(value)))
        self._sync()

    def press_level(self) -> float:
        return self._press

    def set_press_level(self, value: float) -> None:
        self._press = max(0.0, min(1.0, float(value)))
        self._sync()

    def _sync(self) -> None:
        effect = self._effect
        if effect is None:
            return
        try:
            effect.setOpacity(min(0.75, self._hover * _HOVER_OPACITY + self._press * _PRESS_OPACITY))
        except RuntimeError:
            self._effect = None

    def opacity(self) -> float:
        effect = self._effect
        if effect is None:
            return 0.0
        try:
            return effect.opacity()
        except RuntimeError:
            self._effect = None
            return 0.0

    def detach_effect(self) -> None:
        """Remove the QGraphicsOpacityEffect cleanly before dialog teardown."""
        self._effect = None
        self.hide()
        self.setGraphicsEffect(None)

    hoverLevel = Property(float, hover_level, set_hover_level)  # noqa: N815 - Qt property
    pressLevel = Property(float, press_level, set_press_level)  # noqa: N815 - Qt property


class ButtonFeedback(QObject):
    """Owns the hover/press animations of one button; use :meth:`install`."""

    #: Not a command — a hook for tests and for hosts that log interactions.
    hover_changed = Signal(bool)

    def __init__(self, button: QAbstractButton) -> None:
        super().__init__(button)
        self._button = button
        self._overlay = _FeedbackOverlay(button)
        self._overlay.raise_()
        self._hover_anim = QPropertyAnimation(self._overlay, b"hoverLevel", self)
        self._press_anim = QPropertyAnimation(self._overlay, b"pressLevel", self)
        button.installEventFilter(self)

    @classmethod
    def install(cls, button: QAbstractButton) -> ButtonFeedback:
        """Attach feedback once and return the instance."""
        existing = getattr(button, "_button_feedback", None)
        if isinstance(existing, cls):
            return existing
        instance = cls(button)
        button._button_feedback = instance
        return instance

    @classmethod
    def install_all(cls, widgets: Iterable[QAbstractButton]) -> None:
        for widget in widgets:
            if widget is not None:
                cls.install(widget)

    @property
    def overlay(self) -> _FeedbackOverlay:
        return self._overlay

    def detach_effect(self) -> None:
        """Stop animations and strip graphics effects before stylesheet swaps."""
        self._hover_anim.stop()
        self._press_anim.stop()
        self._overlay.detach_effect()

    # ── animation ──────────────────────────────────────────────────

    def _animate(self, animation: QPropertyAnimation, start: float, target: float, duration: int) -> None:
        animation.stop()
        if _reduce_motion():
            animation.setDuration(0)
            animation.setStartValue(target)
            animation.setEndValue(target)
        else:
            animation.setDuration(duration)
            animation.setStartValue(start)
            animation.setEndValue(target)
        animation.start()

    def _hover(self, target: float) -> None:
        self._animate(self._hover_anim, self._overlay.hover_level(), target, _HOVER_MS)
        self.hover_changed.emit(bool(target))

    def _press(self, target: float) -> None:
        self._animate(self._press_anim, self._overlay.press_level(), target, _PRESS_MS)

    # ── button events ──────────────────────────────────────────────

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # type: ignore[override]  # noqa: N802
        kind = event.type()
        if kind in (QEvent.Type.Resize, QEvent.Type.Show):
            self._overlay.setGeometry(self._button.rect())
            self._overlay.raise_()
        elif kind == QEvent.Type.Enter:
            self._hover(1.0)
        elif kind == QEvent.Type.Leave:
            self._hover(0.0)
            self._press(0.0)
        elif kind == QEvent.Type.MouseButtonPress and self._button.isEnabled():
            self._press(1.0)
        elif kind == QEvent.Type.MouseButtonRelease:
            self._press(0.0)
        elif kind == QEvent.Type.EnabledChange and not self._button.isEnabled():
            self._hover_anim.stop()
            self._press_anim.stop()
            self._overlay.set_hover_level(0.0)
            self._overlay.set_press_level(0.0)
        return super().eventFilter(obj, event)
