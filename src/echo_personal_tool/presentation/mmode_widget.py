from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.domain.services.mmode_extractor import extract_mmode_column

_SWEEP_SPEEDS: dict[str, int] = {
    "50 mm/s": 256,
    "100 mm/s": 512,
    "200 mm/s": 1024,
}


class MModeWidget(QWidget):
    caliper_measurement_added = Signal(object)
    sweep_speed_changed = Signal(int)
    close_requested = Signal()

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
        self._close_btn.clicked.connect(self.close_requested.emit)
        toolbar.addWidget(self._close_btn)

        # Set default speed
        default_label = "100 mm/s"
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
        self._sweep_line.setValue(0)
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

    def set_depth_calibration_cm_per_pixel(self, cm_per_pixel: float) -> None:
        self._depth_mm_per_pixel = cm_per_pixel * 10.0
        self._plot.setLabel("left", "Depth", units="cm")
