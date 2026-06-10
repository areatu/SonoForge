"""Spectral Doppler widget built on PyQtGraph."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from echo_personal_tool.domain.models import (
    DopplerIntervalMarker,
    DopplerMeasurementDTO,
    DopplerPeakMarker,
    DopplerTrace,
)

_PEAK_LABELS = ("E", "A", "e_sept", "e_lat", "Vmax")
_INTERVAL_LABELS = ("DT", "IVRT", "AT")


class DopplerWidget(QWidget):
    """Display a spectral Doppler spectrogram and measurement overlays."""

    markers_changed = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._plot = pg.PlotWidget()
        self._plot.setMenuEnabled(False)
        self._plot.showGrid(x=True, y=True, alpha=0.15)
        self._plot.setLabel("bottom", "Time", units="ms")
        self._plot.setLabel("left", "Velocity", units="cm/s")
        self._plot.setRange(xRange=(0.0, 1000.0), yRange=(-100.0, 100.0), padding=0.0)
        self._plot.setLimits(xMin=0.0, xMax=1000.0, yMin=-100.0, yMax=100.0)
        self._plot.scene().sigMouseClicked.connect(self._on_plot_mouse_clicked)

        self._image_item = pg.ImageItem(axisOrder="row-major")
        self._image_item.setAutoDownsample(True)
        self._image_item.setZValue(0)
        self._plot.addItem(self._image_item)

        self._peak_scatter = pg.ScatterPlotItem(
            size=10,
            pen=pg.mkPen("#ff6f00", width=2),
            brush=pg.mkBrush("#ffb74d"),
            symbol="o",
        )
        self._peak_scatter.setZValue(20)
        self._plot.addItem(self._peak_scatter)

        self._interval_items: list[pg.PlotDataItem] = []

        self._trace_item = pg.PlotDataItem(
            pen=pg.mkPen("#1565c0", width=2, style=Qt.PenStyle.DashLine)
        )
        self._trace_item.setZValue(15)
        self._plot.addItem(self._trace_item)
        self._trace_items: list[pg.PlotDataItem] = []

        self._tool_mode = "none"
        self._active_partial_points: list[tuple[float, float]] = []
        self._active_interval_start: float | None = None
        self._peak_label_index = 0
        self._interval_label_index = 0
        self._peak_markers: list[DopplerPeakMarker] = []
        self._interval_markers: list[DopplerIntervalMarker] = []
        self._traces: list[DopplerTrace] = []

        self._status_label = QLabel()
        self._status_label.setObjectName("dopplerToolStatus")
        self._status_label.setText(self._format_tool_status(self._tool_mode))

        layout = QVBoxLayout(self)
        layout.addWidget(self._plot, stretch=1)
        layout.addWidget(self._status_label)

    def show_spectrogram(self, pixels: np.ndarray) -> None:
        """Display a grayscale spectrogram in the plot coordinate space."""

        image = np.asarray(pixels)
        if image.ndim == 3:
            image = image[..., 0]
        if image.ndim != 2:
            raise ValueError("Doppler spectrograms must be 2D grayscale arrays")

        # PoC mapping: anchor the image to a fixed 0-1000 ms / -100..100 cm/s window
        # so marker math can happen directly in plot coordinates.
        self._image_item.setImage(image, autoLevels=False)
        self._image_item.setRect(QRectF(0.0, -100.0, 1000.0, 200.0))
        self._update_image_levels(image)
        self._plot.setRange(xRange=(0.0, 1000.0), yRange=(-100.0, 100.0), padding=0.0)

    def set_tool_mode(self, mode: str) -> None:
        mode_name = mode.strip().lower()
        if mode_name not in {"none", "peak", "interval", "trace"}:
            raise ValueError(f"Unsupported Doppler tool mode: {mode}")
        if mode_name != self._tool_mode:
            self._clear_partial_state()
        self._tool_mode = mode_name
        self._status_label.setText(self._format_tool_status(mode_name))

    def get_tool_mode(self) -> str:
        return self._tool_mode

    def cancel_active_tool(self) -> bool:
        had_active_state = (
            self._tool_mode != "none"
            or bool(self._active_partial_points)
            or self._active_interval_start is not None
        )
        self._tool_mode = "none"
        self._clear_partial_state()
        self._status_label.setText(self._format_tool_status(self._tool_mode))
        return had_active_state

    def set_peak_label(self, label: str) -> None:
        """Set the next peak marker label."""

        self._peak_label_index = self._resolve_label_index(label, _PEAK_LABELS)
        self._status_label.setText(self._format_tool_status(self._tool_mode))

    def set_interval_label(self, label: str) -> None:
        """Set the next interval marker label."""

        self._interval_label_index = self._resolve_label_index(label, _INTERVAL_LABELS)
        self._status_label.setText(self._format_tool_status(self._tool_mode))

    def finish_trace(self) -> bool:
        """Complete the active VTI trace, if it has enough points."""

        if len(self._active_partial_points) < 2:
            return False

        points = tuple((float(x), float(y)) for x, y in self._active_partial_points)
        trace = DopplerTrace(label="VTI", points=points)
        self._traces.append(trace)

        completed_item = pg.PlotDataItem(pen=pg.mkPen("#1565c0", width=2))
        completed_item.setZValue(15)
        completed_item.setData([point[0] for point in points], [point[1] for point in points])
        self._plot.addItem(completed_item)
        self._trace_items.append(completed_item)

        self._active_partial_points = []
        self._trace_item.setData([], [])
        self.markers_changed.emit(self._build_measurement_dto())
        self._status_label.setText(self._format_tool_status(self._tool_mode))
        return True

    def get_measurement_dto(self) -> DopplerMeasurementDTO:
        return self._build_measurement_dto()

    def clear_measurements(self) -> None:
        """Clear all Doppler markers and plot overlays.

        Does not emit ``markers_changed`` (consistent with ``ViewerWidget.clear()``,
        which resets overlays without notifying the controller).
        """

        self._peak_markers.clear()
        self._interval_markers.clear()
        self._traces.clear()

        self._peak_scatter.setData([], [])

        for item in self._interval_items:
            self._plot.removeItem(item)
        self._interval_items.clear()

        for item in self._trace_items:
            self._plot.removeItem(item)
        self._trace_items.clear()

        self._clear_partial_state()

    def _build_measurement_dto(self) -> DopplerMeasurementDTO:
        return DopplerMeasurementDTO(
            peaks=tuple(self._peak_markers),
            intervals=tuple(self._interval_markers),
            traces=tuple(self._traces),
        )

    def _clear_partial_state(self) -> None:
        self._active_partial_points = []
        self._active_interval_start = None
        self._trace_item.setData([], [])

    def _format_tool_status(self, mode: str) -> str:
        if mode == "none":
            return "Tool: None"
        if mode == "peak":
            return f"Tool: Peak marker (M) | Click peak (label: {self._current_peak_label()})"
        if mode == "interval":
            prompt = f"Click interval start (label: {self._current_interval_label()})"
            if self._active_interval_start is not None:
                prompt = f"Click interval end (label: {self._current_interval_label()})"
            return f"Tool: Interval marker (T) | {prompt}"
        if mode == "trace":
            return "Tool: VTI trace (V) | Click points, double-click to finish"
        raise ValueError(f"Unsupported Doppler tool mode: {mode}")

    def _update_image_levels(self, image: np.ndarray) -> None:
        if image.size == 0:
            self._image_item.setLevels((0.0, 1.0))
            return

        data_min = float(np.nanmin(image))
        data_max = float(np.nanmax(image))
        if not np.isfinite(data_min) or not np.isfinite(data_max):
            self._image_item.setLevels((0.0, 1.0))
            return

        if data_max <= data_min:
            data_max = data_min + 1.0
        self._image_item.setLevels((data_min, data_max))

    def _resolve_label_index(self, label: str, labels: tuple[str, ...]) -> int:
        normalized = label.strip()
        if normalized not in labels:
            raise ValueError(f"Unsupported label: {label}")
        return labels.index(normalized)

    def _current_peak_label(self) -> str:
        return _PEAK_LABELS[self._peak_label_index]

    def _current_interval_label(self) -> str:
        return _INTERVAL_LABELS[self._interval_label_index]

    def _advance_peak_label(self) -> None:
        self._peak_label_index = (self._peak_label_index + 1) % len(_PEAK_LABELS)

    def _advance_interval_label(self) -> None:
        self._interval_label_index = (self._interval_label_index + 1) % len(_INTERVAL_LABELS)

    def _emit_markers_changed(self) -> None:
        self.markers_changed.emit(self._build_measurement_dto())

    def _refresh_peak_scatter(self) -> None:
        spots = [
            {
                "pos": (marker.time_ms, marker.velocity_cm_s),
                "data": marker.label,
            }
            for marker in self._peak_markers
        ]
        self._peak_scatter.setData(spots)

    def _add_interval_item(self, marker: DopplerIntervalMarker) -> None:
        interval_item = pg.PlotDataItem(
            [marker.start_time_ms, marker.end_time_ms],
            [0.0, 0.0],
            pen=pg.mkPen("#00897b", width=2),
        )
        interval_item.setZValue(18)
        self._plot.addItem(interval_item)
        self._interval_items.append(interval_item)

    def _add_peak_marker(self, time_ms: float, velocity_cm_s: float) -> None:
        marker = DopplerPeakMarker(
            label=self._current_peak_label(),
            time_ms=float(time_ms),
            velocity_cm_s=float(velocity_cm_s),
        )
        self._peak_markers.append(marker)
        self._refresh_peak_scatter()
        self._advance_peak_label()
        self._emit_markers_changed()

    def _add_interval_marker(self, end_time_ms: float) -> None:
        if self._active_interval_start is not None:
            start_time_ms = float(self._active_interval_start)
        else:
            start_time_ms = float(end_time_ms)
        marker = DopplerIntervalMarker(
            label=self._current_interval_label(),
            start_time_ms=float(start_time_ms),
            end_time_ms=float(end_time_ms),
        )
        self._interval_markers.append(marker)
        self._add_interval_item(marker)
        self._active_interval_start = None
        self._advance_interval_label()
        self._emit_markers_changed()

    def _add_trace_point(self, time_ms: float, velocity_cm_s: float) -> None:
        self._active_partial_points.append((float(time_ms), float(velocity_cm_s)))
        x_values = [point[0] for point in self._active_partial_points]
        y_values = [point[1] for point in self._active_partial_points]
        self._trace_item.setData(x_values, y_values)

    def _handle_plot_click(self, time_ms: float, velocity_cm_s: float) -> bool:
        if self._tool_mode == "none":
            return False

        if self._tool_mode == "peak":
            self._add_peak_marker(time_ms, velocity_cm_s)
            self._status_label.setText(self._format_tool_status(self._tool_mode))
            return True

        if self._tool_mode == "interval":
            if self._active_interval_start is None:
                self._active_interval_start = float(time_ms)
                self._status_label.setText(self._format_tool_status(self._tool_mode))
                return True
            self._add_interval_marker(time_ms)
            self._status_label.setText(self._format_tool_status(self._tool_mode))
            return True

        if self._tool_mode == "trace":
            self._add_trace_point(time_ms, velocity_cm_s)
            return True

        return False

    def _on_plot_mouse_clicked(self, ev) -> None:
        if ev.button() != Qt.MouseButton.LeftButton:
            return

        if self._tool_mode == "none":
            return

        ev.accept()
        if self._tool_mode == "trace" and ev.double():
            self.finish_trace()
            return

        point = self._plot.plotItem.vb.mapSceneToView(ev.scenePos())
        self._handle_plot_click(float(point.x()), float(point.y()))
