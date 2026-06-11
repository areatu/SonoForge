"""2D image viewer using PyQtGraph."""

from __future__ import annotations

from dataclasses import dataclass

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
from echo_personal_tool.infrastructure.pixel_utils import bgr_to_rgb


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


@dataclass
class _ContourGraphics:
    contour: Contour
    line_item: pg.PlotDataItem
    node_items: list[_ContourNodeItem]


class _ContourNodeItem(pg.ScatterPlotItem):
    """Single draggable contour node."""

    def __init__(
        self,
        viewer_widget: ViewerWidget,
        contour_index: int,
        point_index: int,
        position: tuple[float, float],
        pen: pg.functions.mkPen,
    ) -> None:
        super().__init__(
            symbol="o",
            size=10,
            pen=pen,
            brush=pg.mkBrush(pen.color()),
        )
        self._viewer_widget = viewer_widget
        self._contour_index = contour_index
        self._point_index = point_index
        self.setZValue(30)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setData([position[0]], [position[1]])

    def set_indices(self, contour_index: int, point_index: int) -> None:
        self._contour_index = contour_index
        self._point_index = point_index

    def mouseDragEvent(self, ev) -> None:  # type: ignore[override]
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        ev.accept()
        view_box = self.getViewBox() or self._viewer_widget._view
        point = view_box.mapSceneToView(ev.scenePos())
        self._viewer_widget._update_contour_point(
            self._contour_index,
            self._point_index,
            float(point.x()),
            float(point.y()),
        )


class ViewerWidget(QWidget):
    """Display a frame with playback controls and window/level sliders."""

    play_pause_requested = Signal()
    frame_selected = Signal(int)
    contour_completed = Signal(object)
    contours_changed = Signal(object)
    linear_measurements_changed = Signal(object)

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
        self._contour_nodes: list[list[_ContourNodeItem]] = []
        self._caliper_labels = ("LVEDD", "LVESD", "IVSd", "LVPWd", "LVOT")
        self._caliper_label_index = 0
        self._contour_mode_active = False
        self._active_contour_points: list[tuple[float, float]] = []
        self._active_contour_item: pg.PlotDataItem | None = None
        self._active_contour_phase: str | None = None
        self._contour_pen_manual = pg.mkPen("#ff6f00", width=2)
        self._contour_pen_ai = pg.mkPen("#00bcd4", width=2)
        self._syncing_state = False
        self._is_color_frame = False

        self._timeline_slider = QSlider(Qt.Orientation.Horizontal)
        self._timeline_slider.setSingleStep(1)
        self._timeline_slider.valueChanged.connect(self._on_timeline_changed)

        self._play_button = QPushButton("Play")
        self._play_button.clicked.connect(self.play_pause_requested.emit)

        self._fps_label = QLabel("FPS: —")
        self._source_label = QLabel("Frame: —")
        self._ed_label = QLabel("ED: —")
        self._es_label = QLabel("ES: —")
        self._measurement_label = QLabel(f"{self._current_caliper_label()}: —")

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
        """Render a 2D grayscale (H, W) or color BGR (H, W, 3) array."""
        frame = np.asarray(pixels)
        self._is_color_frame = frame.ndim == 3 and frame.shape[2] >= 3
        if self._is_color_frame:
            display = bgr_to_rgb(frame)
            self._current_frame = frame
            self._image_item.setImage(display, autoLevels=True)
        else:
            if frame.ndim == 3:
                frame = frame[..., 0]
            self._current_frame = frame
            self._image_item.setImage(frame, autoLevels=False)
            self._update_levels()
        self._window_slider.setEnabled(not self._is_color_frame)
        self._level_slider.setEnabled(not self._is_color_frame)

    def clear(self) -> None:
        self._image_item.clear()
        self._clear_linear_caliper()
        self._clear_contours()

    def set_state(self, viewer_state: ViewerState) -> None:
        if self._syncing_state:
            return
        self._syncing_state = True
        previous_instance = self._current_state.instance if self._current_state else None
        if previous_instance != viewer_state.instance:
            self._clear_linear_caliper()
            self._clear_contours()
        self._current_state = viewer_state
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
            if tuple(self._contours) != viewer_state.contours:
                self.apply_contours(list(viewer_state.contours))
            self._update_linear_measurement()
        finally:
            self._syncing_state = False

    def toggle_linear_caliper(self) -> None:
        if self._linear_roi is not None:
            self._clear_linear_caliper()
            return
        if self._current_frame is None:
            return

        label = self._current_caliper_label()
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
        self._measurement_label.setText(f"{label}: —")
        self._update_linear_measurement()

    def cycle_caliper_label(self) -> None:
        self._caliper_label_index = (self._caliper_label_index + 1) % len(
            self._caliper_labels
        )
        if self._linear_roi is None:
            self._measurement_label.setText(f"{self._current_caliper_label()}: —")
        if self._linear_roi is not None:
            self._update_linear_measurement()

    def start_contour(self) -> None:
        if self._current_frame is None or self._active_contour_item is not None:
            return

        phase = self._resolve_contour_phase()
        self._contour_mode_active = True
        self._active_contour_phase = phase
        self._active_contour_points = []
        self._active_contour_item = pg.PlotDataItem(
            pen=self._contour_pen_manual,
            symbol="o",
            symbolSize=6,
            symbolBrush=self._contour_pen_manual.color(),
        )
        self._active_contour_item.setZValue(20)
        self._view.addItem(self._active_contour_item)

    def set_contour_from_domain(self, contour: Contour) -> None:
        self._upsert_contour_from_domain(contour, emit_change=not self._syncing_state)

    def apply_contours(self, contours: list[Contour]) -> None:
        self._clear_rendered_contours()
        for contour in contours:
            self._upsert_contour_from_domain(contour, emit_change=False)

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
        self._view.removeItem(self._active_contour_item)
        self._active_contour_item = None
        self._active_contour_points = []
        self._active_contour_phase = None
        self._contour_mode_active = False
        self.contour_completed.emit(contour)
        self.set_contour_from_domain(contour)
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
        self._measurement_label.setText(f"{self._current_caliper_label()}: —")
        if not self._syncing_state:
            self.linear_measurements_changed.emit([])

    def _clear_rendered_contours(self) -> None:
        for nodes in self._contour_nodes:
            for node in nodes:
                self._view.removeItem(node)
        for item in self._contour_items:
            self._view.removeItem(item)
        self._contour_items.clear()
        self._contour_nodes.clear()
        self._contours.clear()

    def _clear_contours(self) -> None:
        self._clear_rendered_contours()
        if self._active_contour_item is not None:
            self._view.removeItem(self._active_contour_item)
            self._active_contour_item = None
        self._active_contour_points = []
        self._active_contour_phase = None
        self._contour_mode_active = False
        if not self._syncing_state:
            self.contours_changed.emit([])

    def _upsert_contour_from_domain(self, contour: Contour, emit_change: bool) -> None:
        contour_index = self._find_contour_index(contour)
        if contour_index is None:
            contour_index = len(self._contours)
            self._contours.append(contour)
            self._insert_rendered_contour(contour, contour_index)
        else:
            self._contours.pop(contour_index)
            self._remove_rendered_contour(contour_index)
            self._contours.insert(contour_index, contour)
            self._insert_rendered_contour(contour, contour_index)
        if emit_change and not self._syncing_state:
            self.contours_changed.emit(self.contours())

    def _insert_rendered_contour(self, contour: Contour, contour_index: int) -> None:
        line_item, node_items = self._create_contour_render(contour, contour_index)
        self._contour_items.insert(contour_index, line_item)
        self._contour_nodes.insert(contour_index, node_items)
        self._reindex_contour_nodes()

    def _remove_rendered_contour(self, contour_index: int) -> None:
        line_item = self._contour_items.pop(contour_index)
        for node in self._contour_nodes.pop(contour_index):
            self._view.removeItem(node)
        self._view.removeItem(line_item)
        self._reindex_contour_nodes()

    def _create_contour_render(
        self,
        contour: Contour,
        contour_index: int,
    ) -> tuple[pg.PlotDataItem, list[_ContourNodeItem]]:
        pen = self._contour_pen_for(contour)
        line_item = pg.PlotDataItem(pen=pen)
        line_item.setZValue(20)
        x_values, y_values = self._contour_xy(contour, closed=True)
        line_item.setData(x_values, y_values)
        self._view.addItem(line_item)

        node_items: list[_ContourNodeItem] = []
        for point_index, point in enumerate(contour.points):
            node = _ContourNodeItem(self, contour_index, point_index, point, pen)
            self._view.addItem(node)
            node_items.append(node)
        return line_item, node_items

    def _reindex_contour_nodes(self) -> None:
        for contour_index, node_items in enumerate(self._contour_nodes):
            for point_index, node in enumerate(node_items):
                node.set_indices(contour_index, point_index)

    def _find_contour_index(self, contour: Contour) -> int | None:
        for index, existing in enumerate(self._contours):
            if existing.phase == contour.phase and existing.view == contour.view:
                return index
        return None

    def _contour_pen_for(self, contour: Contour) -> pg.QtGui.QPen:
        return self._contour_pen_ai if contour.source == "ai" else self._contour_pen_manual

    def _contour_xy(
        self,
        contour: Contour,
        *,
        closed: bool = False,
    ) -> tuple[list[float], list[float]]:
        points = list(contour.points)
        if closed and points:
            points = points + [points[0]]
        if not points:
            return [], []
        x_values = [point[0] for point in points]
        y_values = [point[1] for point in points]
        return x_values, y_values

    def _update_contour_point(
        self,
        contour_index: int,
        point_index: int,
        x: float,
        y: float,
    ) -> None:
        if contour_index < 0 or contour_index >= len(self._contours):
            return
        contour = self._contours[contour_index]
        if point_index < 0 or point_index >= len(contour.points):
            return

        contour.points[point_index] = (x, y)
        x_values, y_values = self._contour_xy(contour, closed=True)
        self._contour_items[contour_index].setData(x_values, y_values)
        self._contour_nodes[contour_index][point_index].setData([x], [y])
        if not self._syncing_state:
            self.contours_changed.emit(self.contours())

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
            self._measurement_label.setText(f"{self._current_caliper_label()}: —")
            self.linear_measurements_changed.emit([])
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
            label=self._current_caliper_label(),
            pixel_length=pixel_length,
            millimeter_length=millimeter_length,
        )
        self._measurement_label.setText(measurement.display_text())
        if not self._syncing_state:
            self.linear_measurements_changed.emit([measurement])

    def _on_timeline_changed(self, value: int) -> None:
        if self._syncing_state:
            return
        self.frame_selected.emit(value)

    def _update_levels(self) -> None:
        if self._current_frame is None or self._is_color_frame:
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

    def _current_caliper_label(self) -> str:
        return self._caliper_labels[self._caliper_label_index]
