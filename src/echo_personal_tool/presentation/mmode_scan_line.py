from __future__ import annotations

from typing import TYPE_CHECKING

import pyqtgraph as pg
from PySide6.QtCore import Qt

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget


class _MModeNodeItem(pg.ScatterPlotItem):
    """Single draggable M-mode scan line endpoint node."""

    def __init__(
        self,
        viewer_widget: QWidget | None,
        endpoint_index: int,
        position: tuple[float, float],
    ) -> None:
        super().__init__(symbol="o", size=10, pen=pg.mkPen("cyan"), brush=pg.mkBrush("cyan"))
        self._viewer_widget = viewer_widget
        self._endpoint_index = endpoint_index
        self.setZValue(30)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setAcceptHoverEvents(True)
        self.setData([position[0]], [position[1]])

    def hoverEvent(self, ev) -> None:  # type: ignore[override]
        if ev.isEnter():
            self.setSymbol("o")
            self.setSize(12)
            self.setPen(pg.mkPen("#ffb300", width=2))
            self.setBrush(pg.mkBrush("#ffb300"))
        elif ev.isExit():
            self.setSymbol("o")
            self.setSize(10)
            self.setPen(pg.mkPen("cyan"))
            self.setBrush(pg.mkBrush("cyan"))

    def mousePressEvent(self, ev) -> None:  # type: ignore[override]
        if ev.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(ev)
            return
        ev.accept()
        if self._viewer_widget is not None:
            self._viewer_widget._begin_mmode_node_drag(self._endpoint_index)

    def mouseDragEvent(self, ev) -> None:  # type: ignore[override]
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        ev.accept()
        if self._viewer_widget is not None and hasattr(ev, "scenePos"):
            view_box = self.getViewBox()
            if view_box is not None:
                pos = view_box.mapSceneToView(ev.scenePos())
                new_pos = (float(pos.x()), float(pos.y()))
                if (
                    self._viewer_widget._mmode_line_item is not None
                    and self._viewer_widget._mmode_line_item.vertical_lock
                ):
                    original = (
                        self._viewer_widget._mmode_line_item.line_start
                        if self._endpoint_index == 0
                        else self._viewer_widget._mmode_line_item.line_end
                    )
                    if original is not None:
                        new_pos = (original[0], new_pos[1])
                self._viewer_widget._mmode_node_dragging(self._endpoint_index, new_pos)

    def mouseReleaseEvent(self, ev) -> None:  # type: ignore[override]
        if ev.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(ev)
            return
        ev.accept()
        if self._viewer_widget is not None:
            self._viewer_widget._end_mmode_node_drag(self._endpoint_index)


class MModeScanLineItem:
    """Manages M-mode scan line graphics on the 2D viewer.

    Not a QWidget -- created by ViewerWidget and added to ContourViewBox via view.addItem().
    Follows the _CaliperNodeItem pattern: PlotDataItem for line, ScatterPlotItem for endpoints.
    """

    def __init__(self, viewer_widget: QWidget | None) -> None:
        self._viewer_widget = viewer_widget
        self.line_start: tuple[float, float] | None = None
        self.line_end: tuple[float, float] | None = None
        self._line_item: pg.PlotDataItem | None = None
        self._start_node: _MModeNodeItem | None = None
        self._end_node: _MModeNodeItem | None = None
        self._view: pg.ViewBox | None = None
        self.vertical_lock: bool = False
        self._guide_h: pg.PlotDataItem | None = None
        self._guide_v: pg.PlotDataItem | None = None

    @property
    def is_complete(self) -> bool:
        return self.line_start is not None and self.line_end is not None

    def set_start(self, pos: tuple[float, float]) -> None:
        self.line_start = pos
        self.line_end = None
        self._remove_graphics()

    def set_end(self, pos: tuple[float, float]) -> None:
        self.line_end = pos
        self._create_graphics()

    def get_endpoints(self) -> tuple[tuple[float, float], tuple[float, float]]:
        assert self.line_start is not None and self.line_end is not None
        return self.line_start, self.line_end

    def move_start_to(self, pos: tuple[float, float]) -> None:
        self.line_start = pos
        self._update_graphics()

    def move_end_to(self, pos: tuple[float, float]) -> None:
        self.line_end = pos
        self._update_graphics()

    def clear(self) -> None:
        self.line_start = None
        self.line_end = None
        self._remove_graphics()
        self._remove_guide_graphics()

    def update_preview(self, mouse_pos: tuple[float, float]) -> None:
        if self.line_start is not None:
            self.line_end = mouse_pos
            self._update_graphics()

    def update_preview_view(
        self, start_view: tuple[float, float], end_view: tuple[float, float], view: pg.ViewBox, frame_height: float
    ) -> None:
        """Show preview line from start_view to end_view in view coords."""
        self._remove_graphics()
        pen = pg.mkPen(color="cyan", style=Qt.PenStyle.DashLine, width=1.5)
        self._line_item = pg.PlotDataItem(pen=pen, antialias=True)
        self._line_item.setZValue(24)
        self._line_item.setData([start_view[0], end_view[0]], [start_view[1], end_view[1]])
        self._start_node = _MModeNodeItem(self._viewer_widget, 0, start_view)
        self.add_to_view(view)

    def add_to_view(self, view: pg.ViewBox) -> None:
        self._view = view
        if self._line_item is not None:
            view.addItem(self._line_item)
        if self._start_node is not None:
            view.addItem(self._start_node)
        if self._end_node is not None:
            view.addItem(self._end_node)

    def update_graphics_for_view(self, view: pg.ViewBox, frame_height: float) -> None:
        """Convert image coords to view coords (invertY) and update graphics."""
        if self.line_start is None or self.line_end is None:
            return
        view_start = (self.line_start[0], frame_height - self.line_start[1])
        view_end = (self.line_end[0], frame_height - self.line_end[1])
        self._remove_graphics()
        pen = pg.mkPen(color="cyan", style=Qt.PenStyle.DashLine, width=1.5)
        self._line_item = pg.PlotDataItem(pen=pen, antialias=True)
        self._line_item.setZValue(24)
        self._start_node = _MModeNodeItem(self._viewer_widget, 0, view_start)
        self._end_node = _MModeNodeItem(self._viewer_widget, 1, view_end)
        self._sync_line_data_view(view_start, view_end)
        self.add_to_view(view)
        if self.vertical_lock:
            self._create_guide_graphics()
            if self._guide_h is not None and self._guide_v is not None:
                self._update_guides(self.line_end, frame_height)

    def _sync_line_data_view(self, view_start: tuple[float, float], view_end: tuple[float, float]) -> None:
        if self._line_item is not None:
            self._line_item.setData(
                [view_start[0], view_end[0]],
                [view_start[1], view_end[1]],
            )

    def remove_from_view(self, view: pg.ViewBox) -> None:
        self._remove_graphics(view)

    def _create_graphics(self) -> None:
        self._remove_graphics()
        pen = pg.mkPen(color="cyan", style=Qt.PenStyle.DashLine, width=1.5)
        self._line_item = pg.PlotDataItem(pen=pen, antialias=True)
        self._line_item.setZValue(24)
        self._start_node = _MModeNodeItem(self._viewer_widget, 0, self.line_start)
        self._end_node = _MModeNodeItem(self._viewer_widget, 1, self.line_end)
        self._sync_line_data()
        if self.vertical_lock:
            self._create_guide_graphics()

    def _update_graphics(self) -> None:
        if self._line_item is not None and self.line_start is not None and self.line_end is not None:
            self._sync_line_data()
        if self._start_node is not None and self.line_start is not None:
            self._start_node.setData([self.line_start[0]], [self.line_start[1]])
        if self._end_node is not None and self.line_end is not None:
            self._end_node.setData([self.line_end[0]], [self.line_end[1]])
        if self.vertical_lock and self._view is not None and self.line_end is not None:
            h = (
                self._viewer_widget._current_frame.shape[0]
                if self._viewer_widget is not None and self._viewer_widget._current_frame is not None
                else 1.0
            )
            self._update_guides(self.line_end, h)

    def _sync_line_data(self) -> None:
        if self._line_item is not None and self.line_start is not None and self.line_end is not None:
            self._line_item.setData(
                [self.line_start[0], self.line_end[0]],
                [self.line_start[1], self.line_end[1]],
            )

    def _remove_graphics(self, view: pg.ViewBox | None = None) -> None:
        v = view or self._view
        for item in (self._line_item, self._start_node, self._end_node):
            if item is not None and v is not None:
                v.removeItem(item)
        self._line_item = None
        self._start_node = None
        self._end_node = None
        self._remove_guide_graphics()

    def _create_guide_graphics(self) -> None:
        """Create perpendicular guide lines for vertical lock mode."""
        pen = pg.mkPen("#9e9e9e", width=1, style=Qt.PenStyle.DashLine)
        self._guide_h = pg.PlotDataItem(pen=pen, antialias=True)
        self._guide_h.setZValue(23)
        self._guide_v = pg.PlotDataItem(pen=pen, antialias=True)
        self._guide_v.setZValue(23)

    def _remove_guide_graphics(self) -> None:
        """Remove guide lines."""
        v = self._view
        for item in (self._guide_h, self._guide_v):
            if item is not None and v is not None:
                v.removeItem(item)
        self._guide_h = None
        self._guide_v = None

    def _update_guides(self, pos: tuple[float, float], frame_height: float) -> None:
        """Update perpendicular guides at given position (image coords)."""
        if self._guide_h is None or self._guide_v is None or self._view is None:
            return
        view_y = frame_height - pos[1]
        self._guide_h.setData([0, self._view.width()], [view_y, view_y])
        self._guide_v.setData([pos[0], pos[0]], [0, frame_height])
        if self._guide_h not in self._view.addedItems:
            self._view.addItem(self._guide_h)
        if self._guide_v not in self._view.addedItems:
            self._view.addItem(self._guide_v)
