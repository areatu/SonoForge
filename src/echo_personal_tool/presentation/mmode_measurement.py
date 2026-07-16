"""M-mode measurement tools: vertical (depth), horizontal (time), arbitrary."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget


@dataclass
class MModeMeasurement:
    kind: Literal["vertical", "horizontal", "arbitrary"]
    start: tuple[float, float]  # (time_ms, depth_mm)
    end: tuple[float, float]
    value_mm: float | None = None
    value_ms: float | None = None


class MModeMeasurementItem:
    """Renders a single M-mode measurement with guide lines to axes."""

    _GUIDE_PEN = pg.mkPen("#9e9e9e", width=1, style=Qt.PenStyle.DashLine)
    _LINE_PEN = pg.mkPen("#ffb300", width=2)
    _NODE_BRUSH = pg.mkBrush("#ffb300")
    _NODE_PEN = pg.mkPen("#ffb300")

    def __init__(self, view_box: pg.ViewBox) -> None:
        self._view = view_box
        self._line_item: pg.PlotDataItem | None = None
        self._start_node: pg.ScatterPlotItem | None = None
        self._end_node: pg.ScatterPlotItem | None = None
        self._guide_h_start: pg.PlotDataItem | None = None
        self._guide_h_end: pg.PlotDataItem | None = None
        self._guide_v_start: pg.PlotDataItem | None = None
        self._guide_v_end: pg.PlotDataItem | None = None
        self._label: pg.TextItem | None = None
        self._measurement: MModeMeasurement | None = None

    def set_measurement(self, m: MModeMeasurement) -> None:
        self._measurement = m
        self._create_graphics()
        self._update_graphics()

    def remove(self) -> None:
        for item in (
            self._line_item, self._start_node, self._end_node,
            self._guide_h_start, self._guide_h_end,
            self._guide_v_start, self._guide_v_end,
            self._label,
        ):
            if item is not None:
                self._view.removeItem(item)
        self._line_item = None
        self._start_node = None
        self._end_node = None
        self._guide_h_start = None
        self._guide_h_end = None
        self._guide_v_start = None
        self._guide_v_end = None
        self._label = None

    def _create_graphics(self) -> None:
        if self._line_item is not None:
            return
        self._line_item = pg.PlotDataItem(pen=self._LINE_PEN, antialias=True)
        self._line_item.setZValue(25)
        self._view.addItem(self._line_item)

        self._start_node = pg.ScatterPlotItem(symbol="o", size=8, pen=self._NODE_PEN, brush=self._NODE_BRUSH)
        self._start_node.setZValue(26)
        self._view.addItem(self._start_node)

        self._end_node = pg.ScatterPlotItem(symbol="o", size=8, pen=self._NODE_PEN, brush=self._NODE_BRUSH)
        self._end_node.setZValue(26)
        self._view.addItem(self._end_node)

        pen = self._GUIDE_PEN
        for attr in ("_guide_h_start", "_guide_h_end", "_guide_v_start", "_guide_v_end"):
            item = pg.PlotDataItem(pen=pen, antialias=True)
            item.setZValue(24)
            item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            item.setAcceptHoverEvents(False)
            self._view.addItem(item)
            setattr(self, attr, item)

        self._label = pg.TextItem(color="#ffb300", anchor=(0, 1))
        self._label.setZValue(27)
        self._view.addItem(self._label)

    def _update_graphics(self) -> None:
        m = self._measurement
        if m is None or self._line_item is None:
            return
        sx, sy = m.start
        ex, ey = m.end
        self._line_item.setData([sx, ex], [sy, ey])
        self._start_node.setData([sx], [sy])
        self._end_node.setData([ex], [ey])

        # Horizontal guides (from point to Y axis at x=0)
        if m.kind != "horizontal":
            self._guide_h_start.setData([0, sx], [sy, sy])
            self._guide_h_end.setData([0, ex], [ey, ey])
        else:
            self._guide_h_start.setData([], [])
            self._guide_h_end.setData([], [])

        # Vertical guides (from point to X axis at y=0)
        if m.kind != "vertical":
            self._guide_v_start.setData([sx, sx], [0, sy])
            self._guide_v_end.setData([ex, ex], [0, ey])
        else:
            self._guide_v_start.setData([], [])
            self._guide_v_end.setData([], [])

        # Label
        parts = []
        if m.value_mm is not None:
            parts.append(f"{m.value_mm:.1f} mm")
        if m.value_ms is not None:
            parts.append(f"{m.value_ms:.1f} ms")
        text = "  ".join(parts)
        mid_x = (sx + ex) / 2
        mid_y = (sy + ey) / 2
        self._label.setText(text)
        self._label.setPos(mid_x, mid_y)


class MModeMeasurementTool(QWidget):
    """Manages M-mode measurements on the MModeWidget plot."""

    measurement_added = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._active_mode: Literal["vertical", "horizontal", "arbitrary"] | None = None
        self._first_click: tuple[float, float] | None = None
        self._depth_mm_per_pixel: float | None = None
        self._time_ms_per_pixel: float | None = None
        self._num_samples: int = 256
        self.measurements: list[MModeMeasurement] = []
        self._items: list[MModeMeasurementItem] = []
        self._view_box: pg.ViewBox | None = None
        self._preview_item: MModeMeasurementItem | None = None

    def set_view_box(self, view_box: pg.ViewBox) -> None:
        self._view_box = view_box

    def set_calibration(self, depth_mm_per_pixel: float, time_ms_per_pixel: float, num_samples: int) -> None:
        self._depth_mm_per_pixel = depth_mm_per_pixel
        self._time_ms_per_pixel = time_ms_per_pixel
        self._num_samples = num_samples

    def start_vertical(self) -> None:
        self._active_mode = "vertical"
        self._first_click = None

    def start_horizontal(self) -> None:
        self._active_mode = "horizontal"
        self._first_click = None

    def start_arbitrary(self) -> None:
        self._active_mode = "arbitrary"
        self._first_click = None

    def cancel(self) -> None:
        self._active_mode = None
        self._first_click = None
        self._remove_preview()

    def on_click(self, x: float, y: float) -> bool:
        if self._active_mode is None or self._view_box is None:
            return False
        if self._first_click is None:
            self._first_click = (x, y)
            # Show preview guide lines from first click
            self._show_preview(x, y)
            return True
        # Second click — create measurement
        start = self._first_click
        end = (x, y)
        self._first_click = None
        self._remove_preview()

        # Apply vertical lock: second point uses first point's X
        if self._active_mode == "vertical":
            end = (start[0], end[1])

        m = MModeMeasurement(kind=self._active_mode, start=start, end=end)

        # Coordinates are already in physical units (mm/ms) because
        # ImageItem.setRect() maps the ViewBox to physical dimensions.
        if self._active_mode in ("vertical", "arbitrary"):
            m.value_mm = abs(end[1] - start[1])
        if self._active_mode in ("horizontal", "arbitrary"):
            m.value_ms = abs(end[0] - start[0])

        self.measurements.append(m)
        item = MModeMeasurementItem(self._view_box)
        item.set_measurement(m)
        self._items.append(item)
        self.measurement_added.emit(m)
        return True

    def on_hover(self, x: float, y: float) -> bool:
        """Update preview guide lines during first-click hover."""
        if self._active_mode is None or self._first_click is None or self._view_box is None:
            return False
        self._update_preview_guides(x, y)
        return True

    def _show_preview(self, x: float, y: float) -> None:
        """Show perpendicular crosshair guide lines at first click position."""
        if self._view_box is None:
            return
        self._remove_preview()
        pen = pg.mkPen("#9e9e9e", width=1, style=Qt.PenStyle.DashLine)
        self._preview_item = MModeMeasurementItem(self._view_box)
        # Create a dummy vertical measurement for guide rendering
        m = MModeMeasurement(kind="arbitrary", start=(x, y), end=(x, y))
        self._preview_item.set_measurement(m)

    def _update_preview_guides(self, x: float, y: float) -> None:
        """Update preview to show crosshair at current mouse position."""
        if self._preview_item is None or self._first_click is None:
            return
        sx, sy = self._first_click
        # For vertical mode, fix X to first point
        if self._active_mode == "vertical":
            x = sx
        m = MModeMeasurement(kind="arbitrary", start=(sx, sy), end=(x, y))
        self._preview_item.set_measurement(m)

    def _remove_preview(self) -> None:
        if self._preview_item is not None:
            self._preview_item.remove()
            self._preview_item = None

    def clear(self) -> None:
        for item in self._items:
            item.remove()
        self._items.clear()
        self.measurements.clear()
        self._active_mode = None
        self._first_click = None
        self._remove_preview()
