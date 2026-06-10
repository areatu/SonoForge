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

from echo_personal_tool.domain.models import Contour
from echo_personal_tool.domain.models.linear_measurement import (
    LinearMeasurement,
    pixel_to_mm_length,
)
from echo_personal_tool.domain.models.viewer_state import ViewerState


class ContourViewBox(pg.ViewBox):
    """ViewBox that forwards contour clicks to the widget."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._viewer_widget: ViewerWidget | None = None

    def set_viewer_widget(self, viewer_widget: ViewerWidget) -> None:
        self._viewer_widget = viewer_widget

    def mouseClickEvent(self, ev) -> None:  # type: ignore[override]
        if self._viewer_widget is not None and self._viewer_widget._handle_contour_mouse_click(ev):
            return
        super().mouseClickEvent(ev)


class ViewerWidget(QWidget):
    """Display a frame with playback controls and window/level sliders."""

    play_pause_requested = Signal()
    frame_selected = Signal(int)
    contour_completed = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._graphics = pg.GraphicsLayoutWidget()
        self._view = ContourViewBox(lockAspect=True, invertY=True)
        self._graphics.ci.addItem(self._view)
        self._view.set_viewer_widget(self)
        self._image_item = pg.ImageItem(axisOrder="row-major")
        self._image_item.setAutoDownsample(True)
        self._view.addItem(self._image_item)
        self._current_frame: np.ndarray | None = None
        self._current_state: ViewerState | None = None
        self._linear_roi: pg.LineROI | None = None
        self._contours: list[Contour] = []
        self._contour_items: list[pg.PlotDataItem] = []
        self._contour_mode_active = False
        self._active_contour_points: list[tuple[float, float]] = []
        self._active_contour_item: pg.PlotDataItem | None = None
        self._active_contour_phase: str | None = None
        self._contour_pen = pg.mkPen("#ff6f00", width=2)
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
        self._measurement_label = QLabel("Length: —")

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
        wl_row.addWidget(self._measurement_label)
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
        self._clear_linear_caliper()
        self._clear_contours()

    def set_state(self, viewer_state: ViewerState) -> None:
        previous_instance = self._current_state.instance if self._current_state else None
        if previous_instance != viewer_state.instance:
            self._clear_linear_caliper()
            self._clear_contours()
        self._current_state = viewer_state
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
            ed_index = viewer_state.ed_frame_index
            es_index = viewer_state.es_frame_index
            self._ed_label.setText(
                f"ED: {ed_index + 1}" if ed_index is not None else "ED: —"
            )
            self._es_label.setText(
                f"ES: {es_index + 1}" if es_index is not None else "ES: —"
            )
            self._ed_label.setStyleSheet(
                "color: #2e7d32; font-weight: bold;" if ed_index is not None else ""
            )
            self._es_label.setStyleSheet(
                "color: #c62828; font-weight: bold;" if es_index is not None else ""
            )
            self._update_timeline_indicator(viewer_state)
            self._update_linear_measurement()
        finally:
            self._syncing_state = False

    def toggle_linear_caliper(self) -> None:
        if self._linear_roi is not None:
            self._clear_linear_caliper()
            return
        if self._current_frame is None:
            return

        height, width = self._current_frame.shape[:2]
        line_length = max(float(min(width, height)) * 0.35, 20.0)
        line_width = max(float(min(width, height)) * 0.02, 4.0)
        start_x = max((width - line_length) / 2.0, 0.0)
        start_y = float(height) / 2.0
        roi = pg.LineROI(
            (start_x, start_y),
            (min(start_x + line_length, float(width - 1)), start_y),
            line_width,
            pen=pg.mkPen("#ffb300", width=2),
        )
        roi.sigRegionChanged.connect(self._update_linear_measurement)
        roi.sigRegionChangeFinished.connect(self._update_linear_measurement)
        self._view.addItem(roi)
        self._linear_roi = roi
        self._update_linear_measurement()

    def start_contour(self) -> None:
        if self._current_frame is None or self._active_contour_item is not None:
            return

        phase = self._resolve_contour_phase()
        self._contour_mode_active = True
        self._active_contour_phase = phase
        self._active_contour_points = []
        self._active_contour_item = pg.PlotDataItem(
            pen=self._contour_pen,
            symbol="o",
            symbolSize=6,
            symbolBrush=self._contour_pen.color(),
        )
        self._active_contour_item.setZValue(20)
        self._view.addItem(self._active_contour_item)

    def handle_contour_click(self, point: tuple[float, float]) -> bool:
        if not self._contour_mode_active or self._active_contour_item is None:
            return False

        self._active_contour_points.append((float(point[0]), float(point[1])))
        self._update_active_contour_item()
        return True

    def finish_contour(self) -> bool:
        if not self._contour_mode_active or self._active_contour_item is None:
            return False
        if len(self._active_contour_points) < 3:
            return False

        points = list(self._active_contour_points)
        self._update_active_contour_item(closed=True)
        contour = Contour(
            phase=self._active_contour_phase or "ED",
            points=points,
        )
        self._contours.append(contour)
        self._contour_items.append(self._active_contour_item)
        self.contour_completed.emit(contour)
        self._active_contour_item = None
        self._active_contour_points = []
        self._active_contour_phase = None
        self._contour_mode_active = False
        return True

    def cancel_active_tool(self) -> None:
        if self._active_contour_item is not None:
            self._view.removeItem(self._active_contour_item)
            self._active_contour_item = None
            self._active_contour_points = []
            self._active_contour_phase = None
            self._contour_mode_active = False
            return
        self._clear_linear_caliper()

    @property
    def contours(self) -> list[Contour]:
        return list(self._contours)

    @property
    def is_contour_mode_active(self) -> bool:
        return self._contour_mode_active

    def _update_timeline_indicator(self, viewer_state: ViewerState) -> None:
        ed_index = viewer_state.ed_frame_index
        es_index = viewer_state.es_frame_index
        markers: list[str] = []
        if ed_index is not None:
            markers.append(f"ED @ {ed_index + 1}")
        if es_index is not None:
            markers.append(f"ES @ {es_index + 1}")
        self._timeline_slider.setToolTip(
            "Phase markers: " + ", ".join(markers) if markers else ""
        )
        current = viewer_state.current_frame_index
        if current == ed_index:
            self._timeline_slider.setStyleSheet(
                "QSlider::handle:horizontal { background: #2e7d32; }"
            )
        elif current == es_index:
            self._timeline_slider.setStyleSheet(
                "QSlider::handle:horizontal { background: #c62828; }"
            )
        else:
            self._timeline_slider.setStyleSheet("")

    def _clear_linear_caliper(self) -> None:
        if self._linear_roi is not None:
            self._view.removeItem(self._linear_roi)
            self._linear_roi = None
        self._measurement_label.setText("Length: —")

    def _clear_contours(self) -> None:
        if self._active_contour_item is not None:
            self._view.removeItem(self._active_contour_item)
            self._active_contour_item = None
        for item in self._contour_items:
            self._view.removeItem(item)
        self._contour_items.clear()
        self._contours.clear()
        self._active_contour_points = []
        self._active_contour_phase = None
        self._contour_mode_active = False

    def _resolve_contour_phase(self) -> str:
        if self._current_state is None:
            return "ED"

        state = self._current_state
        current = state.current_frame_index
        ed = state.ed_frame_index
        es = state.es_frame_index
        if ed is not None and current == ed:
            return "ED"
        if es is not None and current == es:
            return "ES"
        if ed is not None and es is None:
            return "ED"
        if es is not None and ed is None:
            return "ES"
        return "ED"

    def _handle_contour_mouse_click(self, ev) -> bool:
        if not self._contour_mode_active:
            return False
        if ev.button() != Qt.MouseButton.LeftButton:
            return False

        ev.accept()
        if ev.double():
            self.finish_contour()
            return True

        point = self._view.mapSceneToView(ev.scenePos())
        self.handle_contour_click((float(point.x()), float(point.y())))
        return True

    def _update_active_contour_item(self, closed: bool = False) -> None:
        if self._active_contour_item is None:
            return
        points = list(self._active_contour_points)
        if closed and points:
            points.append(points[0])
        if points:
            x_values = [point[0] for point in points]
            y_values = [point[1] for point in points]
            self._active_contour_item.setData(x_values, y_values)
        else:
            self._active_contour_item.setData([], [])

    def _update_linear_measurement(self, *_args) -> None:
        if self._linear_roi is None:
            self._measurement_label.setText("Length: —")
            return

        pixel_length = float(self._linear_roi.size().x())
        angle_degrees = float(self._linear_roi.angle())
        pixel_spacing = None
        if self._current_state and self._current_state.instance:
            pixel_spacing = self._current_state.instance.pixel_spacing
        millimeter_length = (
            pixel_to_mm_length(pixel_length, angle_degrees, pixel_spacing)
            if pixel_spacing is not None
            else None
        )
        measurement = LinearMeasurement(
            label="Length",
            pixel_length=pixel_length,
            millimeter_length=millimeter_length,
        )
        self._measurement_label.setText(measurement.display_text())

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
