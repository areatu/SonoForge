"""Viewport zoom/pan owner extracted from :class:`ViewerWidget`.

``ViewerZoom`` owns the viewport mode (``fit`` / ``100%`` / ``200%`` /
``custom``), the continuous wheel factor and the armed click-to-zoom («лупа»)
state.  It receives the live frame, the graphics view and the ViewBox through a
narrow port; it never stores a ``ViewerState`` and emits no signals.

Frame-wheel navigation deliberately stays in ``ViewerWidget._handle_wheel``:
that is document navigation, not a viewport concern.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QPointF, Qt

from echo_personal_tool.application.localization import tr

#: Zoom bounds of a manual zoom (Ctrl+wheel or the loupe click).
ZOOM_MIN = 0.1
ZOOM_MAX = 20.0
#: Magnification of one loupe click (Shift+click divides by it).
ZOOM_CLICK_STEP = 1.6

_ZOOM_MODES = ("fit", "100%", "200%")


class ViewerZoom:
    """One owner for viewport mode/factor and the loupe state."""

    def __init__(
        self,
        *,
        graphics: pg.GraphicsLayoutWidget,
        view: pg.ViewBox,
        frame_provider: Callable[[], np.ndarray | None],
        set_hint: Callable[[str], None],
        refresh_cursor: Callable[[], None],
    ) -> None:
        self._graphics = graphics
        self._view = view
        self._frame_provider = frame_provider
        self._set_hint = set_hint
        self._refresh_cursor = refresh_cursor

        self._mode = "fit"
        self._factor = 1.0
        self._loupe_active = False
        self._loupe_hint = ""

    # ── state ────────────────────────────────────────────────────────

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def factor(self) -> float:
        """Factor of the manual zoom; 1.0 in the fit, 100% and 200% modes."""
        return self._factor

    @property
    def loupe_active(self) -> bool:
        return self._loupe_active

    @property
    def loupe_hint(self) -> str:
        return self._loupe_hint

    @property
    def preserve_range(self) -> bool:
        """True when a new frame must keep the user's current viewport."""
        return self._mode != "fit" or self._factor != 1.0

    # ── fit / 100% / 200% ───────────────────────────────────────────

    def apply_mode(self) -> None:
        """Apply the current mode to the ViewBox range."""
        frame = self._frame_provider()
        if frame is None:
            return
        frame = np.asarray(frame)
        h, w = frame.shape[:2]
        if self._mode == "fit":
            self._view.setRange(xRange=(0, w), yRange=(0, h), padding=0)
        elif self._mode == "100%":
            dpr = self._graphics.devicePixelRatioF()
            view_w = self._graphics.viewport().width() / dpr
            view_h = self._graphics.viewport().height() / dpr
            cx, cy = w / 2.0, h / 2.0
            half_w = view_w / 2.0
            half_h = view_h / 2.0
            self._view.setRange(
                xRange=(cx - half_w, cx + half_w),
                yRange=(cy - half_h, cy + half_h),
                padding=0,
            )
        elif self._mode == "200%":
            dpr = self._graphics.devicePixelRatioF()
            view_w = self._graphics.viewport().width() / dpr
            view_h = self._graphics.viewport().height() / dpr
            cx, cy = w / 2.0, h / 2.0
            half_w = view_w / 4.0
            half_h = view_h / 4.0
            self._view.setRange(
                xRange=(cx - half_w, cx + half_w),
                yRange=(cy - half_h, cy + half_h),
                padding=0,
            )

    def cycle_mode(self) -> None:
        """Cycle fit → 100% → 200% → fit; a custom zoom goes to 100%."""
        idx = _ZOOM_MODES.index(self._mode) if self._mode in _ZOOM_MODES else 0
        self._mode = _ZOOM_MODES[(idx + 1) % len(_ZOOM_MODES)]
        self._factor = 1.0
        self.apply_mode()

    def set_mode(self, mode: str) -> None:
        """Select one of the three named modes; unknown values are ignored."""
        if mode in _ZOOM_MODES:
            self._mode = mode
            self._factor = 1.0
            self.apply_mode()

    def step_mode(self, direction: int) -> None:
        """Keyboard zoom in/out: move one named mode without leaving the ends."""
        idx = _ZOOM_MODES.index(self._mode) if self._mode in _ZOOM_MODES else 0
        idx = max(0, min(idx + (1 if direction > 0 else -1), len(_ZOOM_MODES) - 1))
        self._mode = _ZOOM_MODES[idx]
        self._factor = 1.0
        self.apply_mode()

    # ── manual zoom ──────────────────────────────────────────────────

    def zoom_around(self, mx: float, my: float, factor: float) -> bool:
        """Show the frame at *factor*, keeping the scene point under (mx, my) fixed.

        ``mx``/``my`` are viewport coordinates (device-independent pixels).  One
        implementation for Ctrl+wheel and for the loupe click, so the two can
        never disagree about where the focus goes.
        """
        if self._frame_provider() is None:
            return False
        new_factor = max(ZOOM_MIN, min(ZOOM_MAX, float(factor)))
        if abs(new_factor - self._factor) < 1e-6:
            return False
        scene_pos = self._graphics.mapToScene(QPointF(mx, my).toPoint())
        data_x = scene_pos.x()
        data_y = scene_pos.y()
        self._factor = new_factor
        self._mode = "custom"  # any manual zoom is «custom», not fit/100/200
        view_w = self._graphics.viewport().width() / self._graphics.devicePixelRatioF()
        view_h = self._graphics.viewport().height() / self._graphics.devicePixelRatioF()
        half_w = (view_w / 2.0) / new_factor
        half_h = (view_h / 2.0) / new_factor
        ratio_x = mx / view_w if view_w > 0 else 0.5
        ratio_y = my / view_h if view_h > 0 else 0.5
        cx = data_x - half_w * (2 * ratio_x - 1)
        cy = data_y - half_h * (2 * ratio_y - 1)
        self._view.setRange(
            xRange=(cx - half_w, cx + half_w),
            yRange=(cy - half_h, cy + half_h),
            padding=0,
        )
        return True

    def handle_ctrl_wheel(self, ev: Any, delta_y: int) -> bool:
        """Ctrl+wheel: zoom around the pointer without touching the document."""
        if self._frame_provider() is None:
            return False

        zoom_step = 1.1
        new_factor = self._factor * zoom_step if delta_y > 0 else self._factor / zoom_step
        if hasattr(ev, "position"):
            mouse_pos = ev.position()
            mx, my = mouse_pos.x(), mouse_pos.y()
        elif hasattr(ev, "pos"):
            point = ev.pos()
            mx, my = point.x(), point.y()
        else:
            viewport = self._graphics.viewport()
            mx = viewport.width() / 2.0
            my = viewport.height() / 2.0
        if not self.zoom_around(mx, my, new_factor):
            return False
        ev.accept()
        return True

    # ── «лупа»: click-to-zoom tool of the tool row ───────────────────

    def set_loupe_active(self, active: bool) -> None:
        """Arm/disarm the magnifier tool (the row's «Лупа» button)."""
        self._loupe_active = bool(active)
        self._refresh_cursor()
        if self._loupe_active:
            self._loupe_hint = tr("viewer.zoom_loupe_hint")
            self._set_hint(self._loupe_hint)
        elif self._loupe_hint:
            self._set_hint("")
            self._loupe_hint = ""

    def loupe_click(self, event: Any) -> bool:
        """Apply one loupe click at the pointer position of *event*."""
        if self._frame_provider() is None:
            return False
        position = event.position()
        factor = (
            self._factor / ZOOM_CLICK_STEP
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier
            else self._factor * ZOOM_CLICK_STEP
        )
        if not self.zoom_around(position.x(), position.y(), factor):
            return False
        self.loupe_status()
        return True

    def loupe_status(self) -> None:
        """Say what the current magnification is, so the click is not a mystery."""
        if not self._loupe_active:
            return
        self._loupe_hint = tr("viewer.zoom_loupe_status", percent=int(round(self._factor * 100)))
        self._set_hint(self._loupe_hint)
