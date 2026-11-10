"""One-shot freehand teaching contour tool; independent of measurement tools."""

from __future__ import annotations

import math
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsPathItem

from echo_personal_tool.application.prepared_anatomy import Shape
from echo_personal_tool.presentation.prepared_anatomy_layer import DEFAULT_COLORS


class PreparedDrawTool:
    """Receives only speaker ViewBox drag gestures, never emits a Contour DTO."""

    def __init__(self, viewer, completed: Callable[[Shape], None]) -> None:
        self.viewer = viewer
        self.completed = completed
        self.structure: str | None = None
        self._disposed = False
        self._points: list[tuple[float, float]] = []
        #: Whether a stroke is in progress (set by the native Qt event path).
        self._stroke_active: bool = False
        self._preview = QGraphicsPathItem()
        self._preview.setZValue(70)
        self._preview.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        viewer._view.addItem(self._preview)

    def arm(self, structure: str) -> None:
        if self._disposed:
            return
        self.cancel()
        if structure not in DEFAULT_COLORS:
            return
        self.structure = structure
        pen = QPen(QColor(DEFAULT_COLORS[structure]))
        pen.setWidth(3)
        pen.setCosmetic(True)
        self._preview.setPen(pen)
        self.viewer._graphics.viewport().setCursor(Qt.CursorShape.CrossCursor)

    def cancel(self) -> None:
        if self._disposed:
            return
        self.structure = None
        self._stroke_active = False
        self._points.clear()
        self._preview.setPath(QPainterPath())
        self.viewer._graphics.viewport().unsetCursor()

    def _append_point(self, scene_pos) -> None:
        point = self._point(scene_pos)
        if point is not None and (not self._points or math.dist(point, self._points[-1]) >= 2):
            self._points.append(point)
            # Keep preview and exported sidecar bounded even for long drags.
            if len(self._points) > 512:
                self._points = self._points[::2]

    def _redraw_preview(self) -> None:
        path = QPainterPath()
        if self._points:
            path.moveTo(*self._points[0])
            for x, y in self._points[1:]:
                path.lineTo(x, y)
        self._preview.setPath(path)

    def _finish_stroke(self) -> None:
        self._stroke_active = False
        points = self._points[:]
        structure = self.structure
        self.cancel()
        if len(points) >= 3:
            height, width = self.viewer.frame_shape
            normalized = tuple((x / (width - 1), y / (height - 1)) for x, y in points)
            self.completed(Shape(structure, normalized))

    def handle_press(self, scene_pos) -> bool:
        """Begin a stroke from a native Qt mouse press (ViewBox path)."""
        if self._disposed or self.structure is None:
            return False
        self._points.clear()
        self._stroke_active = True
        self._append_point(scene_pos)
        self._redraw_preview()
        return True

    def handle_move(self, scene_pos) -> bool:
        """Feed a native Qt mouse move while a stroke is active."""
        if self._disposed or self.structure is None or not self._stroke_active:
            return False
        self._append_point(scene_pos)
        self._redraw_preview()
        return True

    def handle_release(self) -> bool:
        """Finish a stroke from a native Qt mouse release."""
        if self._disposed or self.structure is None or not self._stroke_active:
            return False
        self._finish_stroke()
        return True

    def _point(self, scene_pos) -> tuple[float, float] | None:
        size = self.viewer.frame_shape
        if size is None or size[0] < 2 or size[1] < 2:
            return None
        pos = self.viewer._view.mapSceneToView(scene_pos)
        x, y = float(pos.x()), float(pos.y())
        if not (0 <= x < size[1] and 0 <= y < size[0]):
            return None
        return x, y

    def drag(self, event) -> bool:
        if self._disposed or self.structure is None or event.button() != Qt.MouseButton.LeftButton:
            return False
        if event.isStart():
            self._points.clear()
            self._stroke_active = True
        self._append_point(event.scenePos())
        self._redraw_preview()
        if event.isFinish():
            self._finish_stroke()
        event.accept()
        return True

    def dispose(self) -> None:
        if self._disposed:
            return
        self.cancel()
        self._disposed = True
        self.viewer._view.removeItem(self._preview)
