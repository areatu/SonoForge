"""M-mode measurement tools: vertical (depth), horizontal (time), arbitrary, teichholz."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget

from echo_personal_tool.infrastructure.i18n import tr


@dataclass
class MModeMeasurement:
    kind: Literal["vertical", "horizontal", "arbitrary", "teichholz_ed", "teichholz_es"]
    start: tuple[float, float]  # (time_ms, depth_mm)
    end: tuple[float, float]
    value_mm: float | None = None
    value_ms: float | None = None
    label: str = ""


class MModeMeasurementItem:
    """Renders a single M-mode measurement with guide lines to axes."""

    _GUIDE_PEN = pg.mkPen("#9e9e9e", width=1, style=Qt.PenStyle.DashLine)
    _LINE_PEN = pg.mkPen("#ffb300", width=2)
    _NODE_BRUSH = pg.mkBrush("#ffb300")
    _NODE_PEN = pg.mkPen("#ffb300")
    _ES_HIGHLIGHT_PEN = pg.mkPen("#ff5722", width=3, style=Qt.PenStyle.DashLine)
    _ES_HIGHLIGHT_BRUSH = pg.mkBrush("#ff5722")

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
        self._es_highlight: pg.ScatterPlotItem | None = None

    def set_measurement(self, m: MModeMeasurement) -> None:
        self._measurement = m
        self._create_graphics()
        self._update_graphics()

    def remove(self) -> None:
        for item in (
            self._line_item,
            self._start_node,
            self._end_node,
            self._guide_h_start,
            self._guide_h_end,
            self._guide_v_start,
            self._guide_v_end,
            self._label,
            self._es_highlight,
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
        self._es_highlight = None

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

        self._label = pg.TextItem(
            color="#ffb300",
            fill=(0, 0, 0, 160),
            anchor=(0, 1),
        )
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
        if m.kind not in ("horizontal",):
            self._guide_h_start.setData([0, sx], [sy, sy])
            self._guide_h_end.setData([0, ex], [ey, ey])
        else:
            self._guide_h_start.setData([], [])
            self._guide_h_end.setData([], [])

        # Vertical guides (from point to X axis at y=0)
        if m.kind not in ("vertical",):
            self._guide_v_start.setData([sx, sx], [0, sy])
            self._guide_v_end.setData([ex, ex], [0, ey])
        else:
            self._guide_v_start.setData([], [])
            self._guide_v_end.setData([], [])

        # Label
        parts = []
        if m.label:
            parts.append(m.label)
        if m.value_mm is not None:
            parts.append(f"{m.value_mm:.1f} mm")
        if m.value_ms is not None:
            parts.append(f"{m.value_ms:.1f} ms")
            if m.value_ms > 0:
                hr = 60000.0 / m.value_ms
                parts.append(f"{tr('mmode.label_hr')} {hr:.0f}")
        text = "  ".join(parts)
        mid_x = (sx + ex) / 2
        mid_y = (sy + ey) / 2
        self._label.setText(text)
        self._label.setPos(mid_x, mid_y)

    def show_es_highlight(self) -> None:
        """Show a pulsating highlight on the end point for ESV measurement."""
        if self._measurement is None or self._view is None:
            return
        sx, sy = self._measurement.start
        ex, ey = self._measurement.end
        if self._es_highlight is None:
            self._es_highlight = pg.ScatterPlotItem(
                symbol="o",
                size=16,
                pen=self._ES_HIGHLIGHT_PEN,
                brush=self._ES_HIGHLIGHT_BRUSH,
            )
            self._es_highlight.setZValue(30)
            self._view.addItem(self._es_highlight)
        self._es_highlight.setData([ex], [ey])


class MModeMeasurementTool(QWidget):
    """Manages M-mode measurements on the MModeWidget plot."""

    measurement_added = Signal(object)
    teichholz_ed_complete = Signal(object)  # Emitted when 3 ED calipers are done
    teichholz_es_complete = Signal(object)  # Emitted when ESV caliper is done
    teichholz_es_highlight = Signal()  # Emitted to show ESV highlight

    # Labels for the 3 ED calipers in Teichholz workflow
    _TEICHHOLZ_ED_LABELS = [tr("mmode.teich_ed_labels.0"), tr("mmode.teich_ed_labels.1"), tr("mmode.teich_ed_labels.2")]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._active_mode: Literal["vertical", "horizontal", "arbitrary", "teichholz_ed", "teichholz_es"] | None = None
        self._first_click: tuple[float, float] | None = None
        self._depth_mm_per_pixel: float | None = None
        self._time_ms_per_pixel: float | None = None
        self._num_samples: int = 256
        self.measurements: list[MModeMeasurement] = []
        self._items: list[MModeMeasurementItem] = []
        self._view_box: pg.ViewBox | None = None
        self._preview_item: MModeMeasurementItem | None = None

        # Teichholz ED state
        self._teichholz_ed_index: int = 0
        self._teichholz_ed_measurements: list[MModeMeasurement] = []

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

    def start_teichholz_ed(self) -> None:
        """Start Teichholz ED workflow: 3 sequential vertical calipers."""
        self._active_mode = "teichholz_ed"
        self._first_click = None
        self._teichholz_ed_index = 0
        self._teichholz_ed_measurements.clear()

    def start_teichholz_es(self) -> None:
        """Start Teichholz ESV measurement."""
        self._active_mode = "teichholz_es"
        self._first_click = None

    def cancel(self) -> None:
        self._active_mode = None
        self._first_click = None
        self._teichholz_ed_index = 0
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
        if self._active_mode in ("vertical", "teichholz_ed", "teichholz_es"):
            end = (start[0], end[1])
        # Apply horizontal lock: second point uses first point's Y
        elif self._active_mode == "horizontal":
            end = (end[0], start[1])

        # Determine label
        label = ""
        if self._active_mode == "teichholz_ed":
            label = self._TEICHHOLZ_ED_LABELS[self._teichholz_ed_index]
        elif self._active_mode == "teichholz_es":
            label = tr("mmode.label_es")

        m = MModeMeasurement(kind=self._active_mode, start=start, end=end, label=label)

        # Coordinates are already in physical units (mm/ms)
        if self._active_mode in ("vertical", "arbitrary", "teichholz_ed", "teichholz_es"):
            m.value_mm = abs(end[1] - start[1])
        if self._active_mode in ("horizontal", "arbitrary"):
            m.value_ms = abs(end[0] - start[0])

        self.measurements.append(m)
        item = MModeMeasurementItem(self._view_box)
        item.set_measurement(m)
        self._items.append(item)
        self.measurement_added.emit(m)

        # Handle Teichholz ED workflow
        if self._active_mode == "teichholz_ed":
            self._teichholz_ed_measurements.append(m)
            self._teichholz_ed_index += 1

            if self._teichholz_ed_index >= 3:
                # All 3 ED calipers done — emit signal and switch to ESV mode
                self.teichholz_ed_complete.emit(self._teichholz_ed_measurements)
                self.teichholz_es_highlight.emit()
                self._active_mode = None
                self._teichholz_ed_index = 0
            else:
                # Chain: end point of this caliper = start point of next
                self._first_click = end
                self._show_preview(end[0], end[1])

        # Handle Teichholz ESV workflow
        elif self._active_mode == "teichholz_es":
            self.teichholz_es_complete.emit(m)
            self._active_mode = None

        return True

    def on_hover(self, x: float, y: float) -> bool:
        """Update preview guide lines during first-click hover."""
        if self._active_mode is None or self._first_click is None or self._view_box is None:
            return False
        self._update_preview_guides(x, y)
        return True

    def get_teichholz_ed_values(self) -> tuple[float, float, float] | None:
        """Return (IVSd, LVIDd, LVPWd) in mm if all 3 calipers are measured."""
        if len(self._teichholz_ed_measurements) < 3:
            return None
        return tuple(m.value_mm for m in self._teichholz_ed_measurements[:3])  # type: ignore[return-value]

    def _show_preview(self, x: float, y: float) -> None:
        """Show perpendicular crosshair guide lines at first click position."""
        if self._view_box is None:
            return
        self._remove_preview()
        self._preview_item = MModeMeasurementItem(self._view_box)
        m = MModeMeasurement(kind="arbitrary", start=(x, y), end=(x, y))
        self._preview_item.set_measurement(m)

    def _update_preview_guides(self, x: float, y: float) -> None:
        """Update preview to show crosshair at current mouse position."""
        if self._preview_item is None or self._first_click is None:
            return
        sx, sy = self._first_click
        # For vertical mode, fix X to first point
        if self._active_mode in ("vertical", "teichholz_ed", "teichholz_es"):
            x = sx
        # For horizontal mode, fix Y to first point
        elif self._active_mode == "horizontal":
            y = sy
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
        self._teichholz_ed_index = 0
        self._teichholz_ed_measurements.clear()
        self._remove_preview()
