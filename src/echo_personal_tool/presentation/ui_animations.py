"""Pure Qt animation helpers for micro-UX feedback."""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import contextmanager
from typing import TYPE_CHECKING

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QEvent,
    QObject,
    QPropertyAnimation,
)
from PySide6.QtWidgets import (
    QDialog,
    QGraphicsOpacityEffect,
    QPushButton,
    QStatusBar,
    QStyle,
    QStyleOptionButton,
    QStylePainter,
    QWidget,
)

if TYPE_CHECKING:
    from collections.abc import Generator

logger = logging.getLogger(__name__)

_MAX_ANIMATIONS_PER_WIDGET = 1
_HOVER_LERP_MS = 100
_HOVER_TICK_MS = 16  # ~60fps


def _reduce_motion_enabled() -> bool:
    """Check if user prefers reduced motion (accessibility)."""
    try:
        from echo_personal_tool.infrastructure.user_preferences import load_user_preferences

        return load_user_preferences().reduce_motion
    except Exception:
        return False


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) < 6:
        return (46, 64, 84)  # fallback to bg_button
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def _lerp_color(c1: str, c2: str, t: float) -> str:
    r1, g1, b1 = _hex_to_rgb(c1)
    r2, g2, b2 = _hex_to_rgb(c2)
    r = int(r1 + (r2 - r1) * t)
    g = int(g1 + (g2 - g1) * t)
    b = int(b1 + (b2 - b1) * t)
    return _rgb_to_hex(r, g, b)


class HoverButtonMixin(QObject):
    """NO-OP placeholder. Hover is handled by QSS :hover/:pressed states.

    Kept for API compatibility — install() is harmless.
    """

    def __init__(self, widget: QWidget) -> None:
        super().__init__(widget)

    @classmethod
    def install(cls, widget: QWidget) -> HoverButtonMixin:
        """No-op: hover is handled by QSS."""
        # A global dictionary with widget keys keeps closed dialogs alive:
        # the widget owns the QObject mixin, even if dictionary values are weak.
        instance = getattr(widget, "_hover_button_mixin", None)
        if instance is None:
            instance = cls(widget)
            widget._hover_button_mixin = instance
        return instance


def _init_time_source():
    try:
        from PySide6.QtCore import QDateTime

        return lambda: QDateTime.currentMSecsSinceEpoch()
    except Exception:
        import time

        return lambda: int(time.time() * 1000)


_current_time_ms = _init_time_source()


def animate_widget_opacity(
    widget: QWidget,
    from_val: float,
    to_val: float,
    duration_ms: int = 200,
    easing: QEasingCurve.Type = QEasingCurve.Type.OutCubic,
    on_finished: Callable[[], None] | None = None,
) -> QPropertyAnimation:
    """Fade ordinary widgets without stacking effects or concurrent animations.

    Do not use this on live image/plot widgets. A full-opacity effect is
    removed after the transition so it does not keep an offscreen cache.
    """
    old_animation = widget.property("_opacity_anim")
    if isinstance(old_animation, QPropertyAnimation):
        old_animation.stop()
        old_animation.deleteLater()
    effect = widget.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
    effect.setOpacity(from_val)
    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(0 if _reduce_motion_enabled() else max(0, duration_ms))
    anim.setStartValue(from_val)
    anim.setEndValue(to_val)
    anim.setEasingCurve(easing)
    widget.setProperty("_opacity_anim", anim)

    def finish() -> None:
        if widget.property("_opacity_anim") is not anim:
            return
        if to_val == 1.0 and widget.graphicsEffect() is effect:
            widget.setGraphicsEffect(None)
        if on_finished is not None:
            on_finished()

    anim.finished.connect(finish)
    anim.start()
    return anim


def show_dialog_animated(dialog: QDialog, duration_ms: int = 200) -> None:
    """Fade the window itself, never resize its form or leave it transparent."""
    previous = dialog.property("_fade_anim")
    if isinstance(previous, QPropertyAnimation):
        previous.stop()
        previous.deleteLater()
        dialog.setProperty("_fade_anim", None)
    if _reduce_motion_enabled() or duration_ms <= 0:
        dialog.setWindowOpacity(1.0)
        dialog.show()
        return

    dialog.setWindowOpacity(0.0)
    dialog.show()
    fade = QPropertyAnimation(dialog, b"windowOpacity", dialog)
    fade.setDuration(duration_ms)
    fade.setStartValue(0.0)
    fade.setEndValue(1.0)
    fade.setEasingCurve(QEasingCurve.Type.OutCubic)
    dialog.setProperty("_fade_anim", fade)
    fade.start()


def hide_dialog_animated(
    dialog: QDialog,
    on_done: Callable[[], None] | None = None,
    duration_ms: int = 120,
) -> None:
    """Call on_done directly. Animation is disabled for stability."""
    if on_done:
        on_done()


@contextmanager
def loading_button(btn: QPushButton, text: str = "...") -> Generator[None, None, None]:
    """Context manager that disables button and shows *text* while async work runs.

    NOTE: For async workers, the caller must manage button state manually
    via signals — this CM only covers synchronous blocks.
    """
    old_text = btn.text()
    old_enabled = btn.isEnabled()
    btn.setText(text)
    btn.setEnabled(False)
    try:
        yield
    finally:
        btn.setText(old_text)
        btn.setEnabled(old_enabled)


def exec_animated(dialog: QDialog, duration_ms: int = 200) -> int:
    """Show dialog and return exec result. Animation is disabled for stability."""
    return dialog.exec()


def set_button_loading(btn: QPushButton, loading: bool, text: str = "...") -> None:
    """Manually set/clear loading state on a button (for async workflows)."""
    if loading:
        # Repeated progress/start signals must not overwrite the original
        # text with "Loading…", nor the original enabled state with False.
        if not btn.property("_is_loading"):
            btn.setProperty("_saved_text", btn.text())
            btn.setProperty("_saved_enabled", btn.isEnabled())
            btn.setProperty("_is_loading", True)
        btn.setText(text)
        btn.setEnabled(False)
    elif btn.property("_is_loading"):
        btn.setText(btn.property("_saved_text"))
        btn.setEnabled(bool(btn.property("_saved_enabled")))
        btn.setProperty("_is_loading", False)
        btn.setProperty("_saved_text", None)
        btn.setProperty("_saved_enabled", None)


class AnimatedButton(QPushButton):
    """Subtle press feedback painted in place, with no layout/geometry changes."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._press_progress = 0.0
        self._press_anim = QPropertyAnimation(self, b"pressProgress", self)
        self._press_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        # Signals cover both mouse and keyboard activation.
        self.pressed.connect(lambda: self._animate_press(1.0))
        self.released.connect(lambda: self._animate_press(0.0))

    def _get_press_progress(self) -> float:
        return self._press_progress

    def _set_press_progress(self, progress: float) -> None:
        self._press_progress = progress
        self.update()

    pressProgress = Property(float, _get_press_progress, _set_press_progress)

    def _animate_press(self, target: float) -> None:
        self._press_anim.stop()
        if _reduce_motion_enabled():
            self._set_press_progress(0.0)
            return
        self._press_anim.setDuration(80 if target else 120)
        self._press_anim.setStartValue(self._press_progress)
        self._press_anim.setEndValue(target)
        self._press_anim.start()

    def paintEvent(self, event) -> None:
        option = QStyleOptionButton()
        self.initStyleOption(option)
        painter = QStylePainter(self)
        painter.translate(self.width() / 2, self.height() / 2)
        scale = 1.0 - 0.03 * self._press_progress
        painter.scale(scale, scale)
        painter.translate(-self.width() / 2, -self.height() / 2)
        painter.drawControl(QStyle.ControlElement.CE_PushButton, option)

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.Type.EnabledChange and not self.isEnabled() and hasattr(self, "_press_anim"):
            self._press_anim.stop()
            self._set_press_progress(0.0)
        super().changeEvent(event)


class _HeightSlideMixin:
    """One cancellable height animation with size constraints restored at rest."""

    def _init_slide(self) -> None:
        self._slide_anim = None
        self._slide_bounds = None

    def showSlideUp(self, duration_ms: int = 200) -> None:
        self._slide_to(True, duration_ms)

    def hideSlideDown(self, duration_ms: int = 150) -> None:
        self._slide_to(False, duration_ms)

    def _slide_to(self, visible: bool, duration_ms: int) -> None:
        if self._slide_anim is not None:
            self._slide_anim.stop()
            self._slide_anim.deleteLater()
            self._slide_anim = None
        if self._slide_bounds is None:
            self._slide_bounds = (self.minimumHeight(), self.maximumHeight())
        low, high = self._slide_bounds
        if _reduce_motion_enabled() or duration_ms <= 0:
            self.setMinimumHeight(low)
            self.setMaximumHeight(high)
            self._slide_bounds = None
            self.setVisible(visible)
            return

        start = self.height() if not self.isHidden() else 0
        hint = self.sizeHint().height()
        target = min(high, max(low, hint if hint >= 0 else self.height()))
        self.setMinimumHeight(0)
        self.setMaximumHeight(start)
        self.show()
        animation = QPropertyAnimation(self, b"maximumHeight", self)
        self._slide_anim = animation
        animation.setDuration(duration_ms)
        animation.setStartValue(start)
        animation.setEndValue(target if visible else 0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        def finish() -> None:
            if self._slide_anim is not animation:
                return
            self._slide_anim = None
            self.setVisible(visible)
            self.setMinimumHeight(low)
            self.setMaximumHeight(high)
            self._slide_bounds = None
            animation.deleteLater()

        animation.finished.connect(finish)
        animation.start()


class SlideUpWidget(_HeightSlideMixin, QWidget):
    """QWidget with interruptible slide transitions."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_slide()


class AnimatedStatusBar(_HeightSlideMixin, QStatusBar):
    """QStatusBar with the same reduced-motion and cancellation semantics."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_slide()
