"""Spectral Doppler widget built on PyQtGraph."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QRectF, Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from echo_personal_tool.domain.models import (
    DopplerIntervalMarker,
    DopplerMeasurementDTO,
    DopplerPeakMarker,
    DopplerTrace,
)

_TOOL_LABELS = {
    "none": "Tool: None",
    "peak": "Tool: Peak marker",
    "interval": "Tool: Interval marker",
    "trace": "Tool: VTI trace",
}


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

        self._trace_item = pg.PlotDataItem(pen=pg.mkPen("#1565c0", width=2))
        self._trace_item.setZValue(15)
        self._plot.addItem(self._trace_item)

        self._tool_mode = "none"
        self._active_partial_points: list[tuple[float, float]] = []
        self._active_interval_start: tuple[float, float] | None = None
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
        if mode_name not in _TOOL_LABELS:
            raise ValueError(f"Unsupported Doppler tool mode: {mode}")
        if mode_name != self._tool_mode:
            self._clear_partial_state()
        self._tool_mode = mode_name
        self._status_label.setText(self._format_tool_status(mode_name))

    def get_tool_mode(self) -> str:
        return self._tool_mode

    def cancel_active_tool(self) -> bool:
        had_active_state = self._tool_mode != "none" or bool(self._active_partial_points)
        self._tool_mode = "none"
        self._clear_partial_state()
        self._status_label.setText(self._format_tool_status(self._tool_mode))
        return had_active_state

    def get_measurement_dto(self) -> DopplerMeasurementDTO:
        return self._build_measurement_dto()

    def _build_measurement_dto(self) -> DopplerMeasurementDTO:
        return DopplerMeasurementDTO(
            peaks=tuple(self._peak_markers),
            intervals=tuple(self._interval_markers),
            traces=tuple(self._traces),
        )

    def _clear_partial_state(self) -> None:
        self._active_partial_points = []
        self._active_interval_start = None

    def _format_tool_status(self, mode: str) -> str:
        return _TOOL_LABELS[mode]

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
