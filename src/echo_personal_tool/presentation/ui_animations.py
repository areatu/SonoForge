"""Pure Qt animation helpers for micro-UX feedback."""

from __future__ import annotations

import logging
import weakref
from contextlib import contextmanager
from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QEasingCurve,
    QObject,
    QPropertyAnimation,
)
from PySide6.QtWidgets import (
    QDialog,
    QGraphicsOpacityEffect,
    QPushButton,
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

    _instances: weakref.WeakValueDictionary[QWidget, HoverButtonMixin] = weakref.WeakValueDictionary()

    def __init__(self, widget: QWidget) -> None:
        super().__init__(widget)

    @classmethod
    def install(cls, widget: QWidget) -> HoverButtonMixin:
        """No-op: hover is handled by QSS."""
        if widget not in cls._instances:
            cls._instances[widget] = cls(widget)
        return cls._instances[widget]


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
    on_finished: callable | None = None,
) -> QPropertyAnimation:
    """Animate widget opacity from *from_val* to *to_val*."""
    effect = widget.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)

    anim = QPropertyAnimation(effect, b"opacity")
    anim.setDuration(duration_ms)
    anim.setStartValue(from_val)
    anim.setEndValue(to_val)
    anim.setEasingCurve(easing)
    if on_finished:
        anim.finished.connect(on_finished)
    anim.start()
    # Prevent GC — keep reference on widget
    widget.setProperty("_opacity_anim", anim)
    return anim


def show_dialog_animated(dialog: QDialog, duration_ms: int = 200) -> None:
    """Fade-in + scale 0.95→1.0 on dialog open."""
    # Skip animation if reduce_motion is enabled
    if _reduce_motion_enabled():
        dialog.show()
        return

    dialog.setWindowOpacity(0.0)
    dialog.show()

    fade = animate_widget_opacity(dialog, 0.0, 1.0, duration_ms)

    # Scale animation via geometry
    geo = dialog.geometry()
    w, h = geo.width(), geo.height()
    dx, dy = int(w * 0.025), int(h * 0.025)
    dialog.setGeometry(geo.x() + dx, geo.y() + dy, w - 2 * dx, h - 2 * dy)

    scale = QPropertyAnimation(dialog, b"geometry")
    scale.setDuration(duration_ms)
    scale.setStartValue(dialog.geometry())
    scale.setEndValue(geo)
    scale.setEasingCurve(QEasingCurve.Type.OutCubic)
    scale.start()
    dialog.setProperty("_scale_anim", scale)
    dialog.setProperty("_fade_anim", fade)


def hide_dialog_animated(
    dialog: QDialog,
    on_done: callable | None = None,
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
        btn.setProperty("_saved_text", btn.text())
        btn.setProperty("_saved_enabled", btn.isEnabled())
        btn.setText(text)
        btn.setEnabled(False)
    else:
        saved_text = btn.property("_saved_text")
        saved_enabled = btn.property("_saved_enabled")
        btn.setText(saved_text if saved_text is not None else btn.text())
        btn.setEnabled(saved_enabled if saved_enabled is not None else True)


class AnimatedButton(QPushButton):
    """QPushButton with scale animation on press/release."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._scale_effect = None
        self._setup_animation()

    def _setup_animation(self) -> None:
        """Set up the scale animation."""
        from PySide6.QtWidgets import QGraphicsScaleEffect

        self._scale_effect = QGraphicsScaleEffect(self)
        self.setGraphicsEffect(self._scale_effect)

    def mousePressEvent(self, event) -> None:
        """Animate scale down on press."""
        if not _reduce_motion_enabled():
            self._animate_scale(0.95, 80)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        """Animate scale up on release."""
        if not _reduce_motion_enabled():
            self._animate_scale(1.0, 120)
        super().mouseReleaseEvent(event)

    def _animate_scale(self, target: float, duration: int) -> None:
        """Animate scale to target value."""
        from PySide6.QtCore import QPropertyAnimation

        if self._scale_effect is None:
            return

        anim = QPropertyAnimation(self._scale_effect, b"scale")
        anim.setDuration(duration)
        anim.setStartValue(self._scale_effect.scale())
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()
        self.setProperty("_scale_anim", anim)


class SlideUpWidget(QWidget):
    """QWidget that slides up when shown."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._slide_anim = None
        self._original_height = 0

    def showSlideUp(self, duration_ms: int = 200) -> None:
        """Show widget with slide-up animation."""
        if _reduce_motion_enabled():
            self.show()
            return

        self._original_height = self.sizeHint().height()
        self.setMaximumHeight(0)
        self.show()

        self._slide_anim = QPropertyAnimation(self, b"maximumHeight")
        self._slide_anim.setDuration(duration_ms)
        self._slide_anim.setStartValue(0)
        self._slide_anim.setEndValue(self._original_height)
        self._slide_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._slide_anim.start()

    def hideSlideDown(self, duration_ms: int = 150) -> None:
        """Hide widget with slide-down animation."""
        if _reduce_motion_enabled():
            self.hide()
            return

        self._slide_anim = QPropertyAnimation(self, b"maximumHeight")
        self._slide_anim.setDuration(duration_ms)
        self._slide_anim.setStartValue(self.height())
        self._slide_anim.setEndValue(0)
        self._slide_anim.setEasingCurve(QEasingCurve.Type.InCubic)
        self._slide_anim.finished.connect(self.hide)
        self._slide_anim.start()


class AnimatedStatusBar(QStatusBar):
    """QStatusBar with slide-up animation on show."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._slide_anim = None
        self._original_height = 0

    def showSlideUp(self, duration_ms: int = 200) -> None:
        """Show status bar with slide-up animation."""
        if _reduce_motion_enabled():
            self.show()
            return

        self._original_height = self.sizeHint().height()
        self.setMaximumHeight(0)
        self.show()

        self._slide_anim = QPropertyAnimation(self, b"maximumHeight")
        self._slide_anim.setDuration(duration_ms)
        self._slide_anim.setStartValue(0)
        self._slide_anim.setEndValue(self._original_height)
        self._slide_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._slide_anim.start()

    def hideSlideDown(self, duration_ms: int = 150) -> None:
        """Hide status bar with slide-down animation."""
        if _reduce_motion_enabled():
            self.hide()
            return

        self._slide_anim = QPropertyAnimation(self, b"maximumHeight")
        self._slide_anim.setDuration(duration_ms)
        self._slide_anim.setStartValue(self.height())
        self._slide_anim.setEndValue(0)
        self._slide_anim.setEasingCurve(QEasingCurve.Type.InCubic)
        self._slide_anim.finished.connect(self.hide)
        self._slide_anim.start()


class SkeletonPulse(QWidget):
    """Pulsing placeholder widget for loading states."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pulse_anim = None
        self._opacity_effect = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the skeleton UI."""
        from PySide6.QtGui import QColor, QPalette
        from PySide6.QtWidgets import QGraphicsOpacityEffect

        self.setMinimumHeight(40)
        self.setMaximumHeight(40)

        # Set palette for background color
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#2a4a6b"))
        self.setPalette(palette)
        self.setAutoFillBackground(True)

        # Opacity effect for pulsing
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(0.6)
        self.setGraphicsEffect(self._opacity_effect)

    def startPulse(self, duration_ms: int = 800) -> None:
        """Start pulsing animation."""
        if _reduce_motion_enabled():
            return

        if self._pulse_anim is not None:
            self._pulse_anim.stop()

        self._pulse_anim = QPropertyAnimation(self._opacity_effect, b"opacity")
        self._pulse_anim.setDuration(duration_ms)
        self._pulse_anim.setStartValue(0.4)
        self._pulse_anim.setEndValue(0.8)
        self._pulse_anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._pulse_anim.setLoopCount(-1)  # Infinite loop
        self._pulse_anim.start()

    def stopPulse(self) -> None:
        """Stop pulsing animation."""
        if self._pulse_anim is not None:
            self._pulse_anim.stop()
            self._pulse_anim = None

    def paintEvent(self, event) -> None:
        """Custom paint for rounded rectangle."""
        from PySide6.QtGui import QBrush, QColor, QPainter, QPen

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw rounded rectangle
        pen = QPen(QColor("#3d5a7a"), 1)
        brush = QBrush(QColor("#1e3a5f"))
        painter.setPen(pen)
        painter.setBrush(brush)
        painter.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), 4, 4)

        painter.end()
