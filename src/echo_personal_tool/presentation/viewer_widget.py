"""2D image viewer using PyQtGraph."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.domain.models.viewer_state import ViewerState


class ViewerWidget(QWidget):
    """Display a frame with playback controls and window/level sliders."""

    play_pause_requested = Signal()
    frame_selected = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._graphics = pg.GraphicsLayoutWidget()
        self._view = self._graphics.addViewBox(lockAspect=True, invertY=True)
        self._image_item = pg.ImageItem(axisOrder="row-major")
        self._image_item.setAutoDownsample(True)
        self._view.addItem(self._image_item)
        self._current_frame: np.ndarray | None = None
        self._syncing_state = False

        self._timeline_slider = QSlider(Qt.Orientation.Horizontal)
        self._timeline_slider.setSingleStep(1)
        self._timeline_slider.valueChanged.connect(self._on_timeline_changed)

        self._play_button = QPushButton("Play")
        self._play_button.clicked.connect(self.play_pause_requested.emit)

        self._fps_label = QLabel("FPS: —")
        self._source_label = QLabel("Frame: —")
        self._ed_label = QLabel("ED: —")
        self._es_label = QLabel("ES: —")

        self._window_slider = QSlider(Qt.Orientation.Horizontal)
        self._window_slider.setRange(1, 400)
        self._window_slider.setValue(100)
        self._window_slider.valueChanged.connect(self._update_levels)

        self._level_slider = QSlider(Qt.Orientation.Horizontal)
        self._level_slider.setRange(0, 100)
        self._level_slider.setValue(50)
        self._level_slider.valueChanged.connect(self._update_levels)

        controls = QVBoxLayout()
        timeline_row = QHBoxLayout()
        timeline_row.addWidget(self._play_button)
        timeline_row.addWidget(self._timeline_slider, stretch=1)
        timeline_row.addWidget(self._source_label)
        timeline_row.addWidget(self._fps_label)
        controls.addLayout(timeline_row)

        wl_row = QHBoxLayout()
        wl_row.addWidget(QLabel("Window"))
        wl_row.addWidget(self._window_slider, stretch=1)
        wl_row.addWidget(QLabel("Level"))
        wl_row.addWidget(self._level_slider, stretch=1)
        wl_row.addWidget(self._ed_label)
        wl_row.addWidget(self._es_label)
        controls.addLayout(wl_row)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._graphics)
        layout.addLayout(controls)

    def show_frame(self, pixels: np.ndarray) -> None:
        """Render a 2D numpy array (H, W) or (H, W, C)."""
        frame = np.asarray(pixels)
        if frame.ndim == 3:
            frame = frame[..., 0]
        self._current_frame = frame
        self._image_item.setImage(frame, autoLevels=False)
        self._update_levels()

    def clear(self) -> None:
        self._image_item.clear()

    def set_state(self, viewer_state: ViewerState) -> None:
        self._syncing_state = True
        try:
            maximum = max(0, viewer_state.total_frames - 1)
            self._timeline_slider.setEnabled(viewer_state.total_frames > 1)
            self._timeline_slider.setRange(0, maximum)
            self._timeline_slider.setValue(
                min(viewer_state.current_frame_index, maximum)
            )
            self._play_button.setText("Pause" if viewer_state.is_playing else "Play")
            self._fps_label.setText(
                f"FPS: {viewer_state.fps:.1f}" if viewer_state.fps > 0 else "FPS: —"
            )
            if viewer_state.total_frames > 0:
                current = min(
                    viewer_state.current_frame_index + 1, viewer_state.total_frames
                )
                self._source_label.setText(f"Frame: {current}/{viewer_state.total_frames}")
            else:
                self._source_label.setText("Frame: —")
            self._ed_label.setText(
                f"ED: {viewer_state.ed_frame_index}"
                if viewer_state.ed_frame_index is not None
                else "ED: —"
            )
            self._es_label.setText(
                f"ES: {viewer_state.es_frame_index}"
                if viewer_state.es_frame_index is not None
                else "ES: —"
            )
        finally:
            self._syncing_state = False

    def _on_timeline_changed(self, value: int) -> None:
        if self._syncing_state:
            return
        self.frame_selected.emit(value)

    def _update_levels(self) -> None:
        if self._current_frame is None:
            return
        frame = np.asarray(self._current_frame, dtype=float)
        if frame.size == 0:
            return
        data_min = float(np.nanmin(frame))
        data_max = float(np.nanmax(frame))
        if not np.isfinite(data_min) or not np.isfinite(data_max):
            return
        span = max(data_max - data_min, 1.0)
        window_scale = self._window_slider.value() / 100.0
        center_offset = (self._level_slider.value() - 50) / 50.0
        window = span * max(window_scale, 0.01)
        center = data_min + span * (0.5 + 0.5 * center_offset)
        low = center - window / 2.0
        high = center + window / 2.0
        self._image_item.setLevels((low, high))
