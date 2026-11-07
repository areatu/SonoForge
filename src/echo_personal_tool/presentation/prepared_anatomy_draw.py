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
        self._points: list[tuple[float, float]] = []
        self._preview = QGraphicsPathItem()
        self._preview.setZValue(70)
        self._preview.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        viewer._view.addItem(self._preview)

    def arm(self, structure: str) -> None:
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
        self.structure = None
        self._points.clear()
        self._preview.setPath(QPainterPath())
        self.viewer._graphics.viewport().unsetCursor()

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
        if self.structure is None or event.button() != Qt.MouseButton.LeftButton:
            return False
        if event.isStart():
            self._points.clear()
        point = self._point(event.scenePos())
        if point is not None and (not self._points or math.dist(point, self._points[-1]) >= 2):
            self._points.append(point)
            # Keep preview and exported sidecar bounded even for long drags.
            if len(self._points) > 512:
                self._points = self._points[::2]
        path = QPainterPath()
        if self._points:
            path.moveTo(*self._points[0])
            for x, y in self._points[1:]:
                path.lineTo(x, y)
        self._preview.setPath(path)
        if event.isFinish():
            points = self._points[:]
            structure = self.structure
            self.cancel()
            if len(points) >= 3:
                height, width = self.viewer.frame_shape
                normalized = tuple((x / (width - 1), y / (height - 1)) for x, y in points)
                self.completed(Shape(structure, normalized))
        event.accept()
        return True

    def dispose(self) -> None:
        self.cancel()
        self.viewer._view.removeItem(self._preview)
