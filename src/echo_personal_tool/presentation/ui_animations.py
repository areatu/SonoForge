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
