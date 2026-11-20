"""DebugOverlayController — the diagnostics overlay slice of ``ViewerWidget``.

Composition-pilot follow-up: the debug overlay (the F-key monospace label
plus the auto-segment ROI rectangle drawn on the ViewBox) was the last overlay
still driven directly by ``ViewerWidget`` state.  The controller owns that
state; the viewer facade only forwards calls:

  keyPressEvent ("debug_overlay" shortcut) → controller.toggle()
  frame refresh (``_refresh_frame_overlays``) → controller.update()
  tests via ``ViewerContract``              → forwarded members (see viewer_contract)

Lifecycle (§7.3): owner-scoped QObject (parent = ViewerWidget) with an
idempotent ``dispose()`` that hides the label and removes the ROI item, so the
50/500-cycle harness sees zero live closed-owner objects.  The label stays a
plain child of the viewer for Qt lifetime reasons.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QLabel, QWidget

from echo_personal_tool.application.diagnostics import log_boundary_failure
from echo_personal_tool.presentation import dark_theme
from echo_personal_tool.presentation.display_formats import format_dpr, format_scale_factor

logger = logging.getLogger(__name__)

RoiRect = tuple[float, float, float, float]


def _overlay_style() -> str:
    """Debug overlay stylesheet built from theme tokens (no raw colour literals)."""
    return (
        "background-color: rgba(0, 0, 0, 180); "
        f"color: {dark_theme.get_theme_tokens()['state.ok']}; "
        "font-family: monospace; font-size: 11px; padding: 4px;"
    )


class DebugOverlayController(QObject):
    """Visibility, text and ROI rectangle of the viewer debug overlay."""

    def __init__(
        self,
        *,
        parent: QWidget | None = None,
        view: Any = None,
        frame_provider: Callable[[], np.ndarray | None],
        state_provider: Callable[[], Any],
        graphics_provider: Callable[[], Any],
        roi_provider: Callable[[], RoiRect | None],
        label_factory: Callable[[], QLabel] | None = None,
    ) -> None:
        super().__init__(parent)
        self._view = view
        self._frame_provider = frame_provider
        self._state_provider = state_provider
        self._graphics_provider = graphics_provider
        self._roi_provider = roi_provider
        self._visible = False
        self._roi_item: Any | None = None
        if label_factory is not None:
            self._label = label_factory()
        else:
            self._label = QLabel(parent)
        self._label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._label.setStyleSheet(_overlay_style())
        self._label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._label.hide()

    # -- contract seams (viewer_contract forwards these names) ---------------

    @property
    def label(self) -> QLabel:
        return self._label

    @property
    def visible(self) -> bool:
        return self._visible

    @visible.setter
    def visible(self, value: bool) -> None:
        self._visible = bool(value)

    @property
    def roi_item(self) -> Any | None:
        return self._roi_item

    @roi_item.setter
    def roi_item(self, value: Any | None) -> None:
        self._roi_item = value

    # -- public facade ---------------------------------------------------------

    def is_visible(self) -> bool:
        return self._visible

    def text(self) -> str:
        """Text of the debug overlay while it is on; an empty string while it is off."""
        return self._label.text() if self._visible else ""

    def toggle(self) -> bool:
        """Flip visibility; returns the new state."""
        self._visible = not self._visible
        if self._visible:
            self.update()
            self._label.show()
        else:
            self._label.hide()
            self.draw_roi_rect(None)
            self._roi_item = None
        return self._visible

    def update(self) -> None:
        """Rebuild the diagnostics text and reposition the label."""
        if not self._visible:
            return
        lines: list[str] = []
        frame = self._frame_provider()
        if frame is not None:
            h, w = frame.shape[:2]
            lines.append(f"Native: {w}x{h}")
        graphics = self._graphics_provider()
        geo = graphics.geometry()
        vw, vh = geo.width(), geo.height()
        lines.append(f"Viewport: {vw}x{vh}")
        if frame is not None:
            h, w = frame.shape[:2]
            if w > 0 and h > 0:
                scale = max(vw / w, vh / h)
                lines.append(f"Scale: {format_scale_factor(scale)}x")
        dpr = graphics.devicePixelRatioF()
        lines.append(f"DPR: {format_dpr(dpr)}")
        state = self._state_provider()
        if state is not None and state.instance is not None:
            inst = state.instance
            lines.append(f"Format: {inst.media_format}")
            lines.append(f"Frames: {inst.number_of_frames}")
        # ROI info
        roi = self.resolve_roi()
        if roi is not None:
            x0, y0, x1, y1 = roi
            lines.append(f"ROI: {int(x0)},{int(y0)}-{int(x1)},{int(y1)}")
        self._label.setText("\n".join(lines))
        self._label.adjustSize()
        geo_viewer = graphics.geometry()
        self._label.move(
            geo_viewer.x() + 4,
            geo_viewer.y() + 4,
        )
        self._label.raise_()
        # Draw ROI rectangle on ViewBox
        self.draw_roi_rect(roi)

    def resolve_roi(self) -> RoiRect | None:
        """Last auto-segment ROI from the wired provider, if any."""
        return self._roi_provider()

    def draw_roi_rect(self, roi: RoiRect | None) -> None:
        """Draw the ROI rectangle on the ViewBox while the overlay is visible."""
        if self._roi_item is not None:
            try:
                self._view.removeItem(self._roi_item)
            except RuntimeError as exc:
                log_boundary_failure(logger, "ui.cleanup", exc, code="cleanup", level=logging.DEBUG)
            self._roi_item = None

        if roi is None or not self._visible:
            return

        x0, y0, x1, y1 = roi
        pen = pg.mkPen(dark_theme.get_theme_tokens()["state.err"], width=1, style=Qt.PenStyle.DashLine)
        rect_item = pg.PlotDataItem(
            pen=pen,
            connect="all",
        )
        rect_item.setZValue(25)
        # Draw rectangle as closed polygon
        rect_item.setData(
            [x0, x1, x1, x0, x0],
            [y0, y0, y1, y1, y0],
        )
        self._view.addItem(rect_item)
        self._roi_item = rect_item

    # -- lifecycle -------------------------------------------------------------

    def dispose(self) -> None:
        """Idempotent — called on viewer teardown and by the lifecycle harness."""
        self._visible = False
        try:
            self._label.hide()
        except RuntimeError as exc:
            log_boundary_failure(logger, "ui.cleanup", exc, code="cleanup", level=logging.DEBUG)
        if self._roi_item is not None:
            try:
                self._view.removeItem(self._roi_item)
            except RuntimeError as exc:
                log_boundary_failure(logger, "ui.cleanup", exc, code="cleanup", level=logging.DEBUG)
            self._roi_item = None
