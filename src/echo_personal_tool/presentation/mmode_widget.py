from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from echo_personal_tool.domain.services.mmode_extractor import extract_mmode_column
from echo_personal_tool.domain.services.mmode_smoothing import (
    log_compress,
    spatial_smooth,
    temporal_smooth,
)

_SWEEP_SPEEDS: dict[str, int] = {
    "25 mm/s": 128,
    "50 mm/s": 256,
    "100 mm/s": 512,
}


class MModeWidget(QWidget):
    caliper_measurement_added = Signal(object)
    sweep_speed_changed = Signal(int)
    deactivate_requested = Signal()

    def __init__(self, buffer_width: int = 512, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._buffer_width = buffer_width
        self._num_samples = 256
        self._sweep_x = 0
        self._scan_start: tuple[float, float] | None = None
        self._scan_end: tuple[float, float] | None = None
        self._time_ms_per_pixel: float | None = None
        self._depth_mm_per_pixel: float | None = None
        self._previous_column: np.ndarray | None = None

        self._image_buffer = np.zeros(
            (self._num_samples, self._buffer_width), dtype=np.uint8
        )

        self._plot = pg.PlotWidget()
        self._plot.setLabel("bottom", "Time", units="px")
        self._plot.setLabel("left", "Depth", units="px")
        self._plot.showGrid(x=True, y=True, alpha=0.3)
        self._plot.setMinimumHeight(150)

        self._view_box = self._plot.getPlotItem().getViewBox()
        self._view_box.setMouseEnabled(x=False, y=False)
        self._view_box.setMenuEnabled(False)
        self._image_item = pg.ImageItem(axisOrder="row-major")
        self._view_box.addItem(self._image_item)
        self._image_item.setImage(self._image_buffer, autoLevels=True)

        self._sweep_line = pg.InfiniteLine(
            angle=90, pen=pg.mkPen("red", width=1, style=Qt.PenStyle.DashLine), movable=False
        )
        self._view_box.addItem(self._sweep_line)
        self._sweep_line.setValue(0)

        # Speed selector toolbar
        self._speed_buttons: dict[str, QPushButton] = {}
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(4, 0, 4, 0)
        toolbar.setSpacing(2)
        for label in _SWEEP_SPEEDS:
            btn = QPushButton(label)
            btn.setFixedHeight(22)
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, l=label: self.set_sweep_speed(l))
            self._speed_buttons[label] = btn
            toolbar.addWidget(btn)
        toolbar.addStretch(1)

        self._close_btn = QPushButton("×")
        self._close_btn.setFixedWidth(24)
        self._close_btn.setFixedHeight(22)
        self._close_btn.clicked.connect(self.deactivate_requested.emit)
        toolbar.addWidget(self._close_btn)

        # Set default speed
        default_label = "50 mm/s"
        self._speed_buttons[default_label].setChecked(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(toolbar)
        layout.addWidget(self._plot)

    def set_sweep_speed(self, label: str) -> None:
        new_width = _SWEEP_SPEEDS.get(label)
        if new_width is None or new_width == self._buffer_width:
            return
        for l, btn in self._speed_buttons.items():
            btn.setChecked(l == label)
        self._buffer_width = new_width
        self._image_buffer = np.zeros(
            (self._num_samples, self._buffer_width), dtype=np.uint8
        )
        self._sweep_x = 0
        self._image_item.setImage(self._image_buffer, autoLevels=True)
        self._apply_image_rect()
        self.sweep_speed_changed.emit(new_width)

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
        col = column[:n]
        # Smart smoothing pipeline: log → spatial → temporal
        col = log_compress(col)
        col = spatial_smooth(col, sigma=1.5)
        col = temporal_smooth(col, self._previous_column, alpha=0.3)
        self._previous_column = col.copy()
        self._image_buffer[:n, self._sweep_x] = col.astype(np.uint8)
        self._sweep_x = (self._sweep_x + 1) % self._buffer_width
        self._image_item.setImage(self._image_buffer, autoLevels=True)
        # Sweep line position in physical X units
        if self._time_ms_per_pixel is not None and self._time_ms_per_pixel > 0:
            self._sweep_line.setValue(self._sweep_x * self._time_ms_per_pixel)
        else:
            self._sweep_line.setValue(self._sweep_x)

    def clear_buffer(self) -> None:
        self._image_buffer[:] = 0
        self._sweep_x = 0
        self._previous_column = None
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
        self._apply_image_rect()

    def set_depth_calibration_mm_per_pixel(self, mm_per_pixel: float) -> None:
        self._depth_mm_per_pixel = mm_per_pixel
        self._apply_image_rect()

    def set_depth_calibration_cm_per_pixel(self, cm_per_pixel: float) -> None:
        self._depth_mm_per_pixel = cm_per_pixel * 10.0
        self._apply_image_rect()

    def set_depth_range_mm(self, total_depth_mm: float) -> None:
        self._depth_mm_per_pixel = total_depth_mm / max(self._num_samples, 1)
        self._apply_image_rect()

    def _apply_image_rect(self) -> None:
        """Scale ImageItem so axes show real physical units (mm / ms)."""
        width_px = self._buffer_width
        height_px = self._num_samples
        # X: time axis
        if self._time_ms_per_pixel is not None and self._time_ms_per_pixel > 0:
            x_size = width_px * self._time_ms_per_pixel
            self._plot.setLabel("bottom", "Time", units="ms")
        else:
            x_size = float(width_px)
            self._plot.setLabel("bottom", "Time", units="px")
        # Y: depth axis
        if self._depth_mm_per_pixel is not None and self._depth_mm_per_pixel > 0:
            y_size = height_px * self._depth_mm_per_pixel
            self._plot.setLabel("left", "Depth", units="mm")
        else:
            y_size = float(height_px)
            self._plot.setLabel("left", "Depth", units="px")
        self._image_item.setRect(0, 0, x_size, y_size)
        self._sweep_line.setPos(0)
        self._view_box.setYRange(0, y_size)
        self._view_box.setXRange(0, x_size)
