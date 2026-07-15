from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from echo_personal_tool.domain.services.mmode_extractor import extract_mmode_column


class MModeWidget(QWidget):
    caliper_measurement_added = Signal(object)

    def __init__(self, buffer_width: int = 512, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._buffer_width = buffer_width
        self._num_samples = 256
        self._sweep_x = 0
        self._scan_start: tuple[float, float] | None = None
        self._scan_end: tuple[float, float] | None = None
        self._time_ms_per_pixel: float | None = None
        self._depth_mm_per_pixel: float | None = None

        self._image_buffer = np.zeros(
            (self._num_samples, self._buffer_width), dtype=np.uint8
        )

        self._plot = pg.PlotWidget()
        self._plot.setLabel("bottom", "Time", units="px")
        self._plot.setLabel("left", "Depth", units="px")
        self._plot.showGrid(x=True, y=True, alpha=0.3)
        self._plot.setMinimumHeight(150)

        self._view_box = self._plot.getPlotItem().getViewBox()
        self._image_item = pg.ImageItem(axisOrder="row-major")
        self._view_box.addItem(self._image_item)
        self._image_item.setImage(self._image_buffer, autoLevels=True)

        self._sweep_line = pg.InfiniteLine(
            angle=90, pen=pg.mkPen("red", width=1, style=Qt.PenStyle.DashLine), movable=False
        )
        self._view_box.addItem(self._sweep_line)
        self._sweep_line.setValue(0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._plot)

    def set_scan_line(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        num_samples: int = 256,
    ) -> None:
        self._scan_start = start
        self._scan_end = end
        if num_samples != self._num_samples:
            self._num_samples = num_samples
            self._image_buffer = np.zeros(
                (self._num_samples, self._buffer_width), dtype=np.uint8
            )
            self._sweep_x = 0
            self._image_item.setImage(self._image_buffer, autoLevels=True)
            self._sweep_line.setValue(0)

    def on_new_column(self, column: np.ndarray) -> None:
        n = min(column.shape[0], self._num_samples)
        self._image_buffer[:n, self._sweep_x] = column[:n]
        self._sweep_x = (self._sweep_x + 1) % self._buffer_width
        self._image_item.setImage(self._image_buffer, autoLevels=True)
        self._sweep_line.setValue(self._sweep_x)

    def clear_buffer(self) -> None:
        self._image_buffer[:] = 0
        self._sweep_x = 0
        self._image_item.setImage(self._image_buffer, autoLevels=True)
        self._sweep_line.setValue(0)

    def recalculate_from_frames(
        self,
        frames: list[np.ndarray],
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> None:
        self.clear_buffer()
        self._scan_start = start
        self._scan_end = end
        for frame in frames:
            col = extract_mmode_column(frame, start, end, self._num_samples)
            self.on_new_column(col)

    def set_time_calibration_ms_per_pixel(self, ms_per_pixel: float) -> None:
        self._time_ms_per_pixel = ms_per_pixel
        self._plot.setLabel("bottom", "Time", units="ms")

    def set_depth_calibration_mm_per_pixel(self, mm_per_pixel: float) -> None:
        self._depth_mm_per_pixel = mm_per_pixel
        self._plot.setLabel("left", "Depth", units="mm")
