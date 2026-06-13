"""2D image viewer using PyQtGraph."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QEvent, QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.domain.calculations.lvef_simpson import format_contour_overlay
from echo_personal_tool.domain.models import Contour
from echo_personal_tool.domain.models.linear_measurement import (
    LinearMeasurement,
    pixel_to_mm_length,
)
from echo_personal_tool.domain.models.viewer_state import ViewerState
from echo_personal_tool.domain.services.contour_geometry import (
    DEFAULT_NODE_COUNT,
    MIN_DELTA_NORM,
    WEIGHT_ACTIVE_THRESHOLD,
    apply_gaussian_displacement,
    gaussian_weights,
    resample_open_arc,
    sample_spline,
    sigma_from_view_range,
)
from echo_personal_tool.domain.services.mbs_lite_service import (
    fit_contour_from_landmarks,
    refine_open_arc_contour,
)
from echo_personal_tool.domain.services.pixel_spacing_resolver import (
    pixel_length_along_angle,
    spacing_from_known_distance,
)
from echo_personal_tool.infrastructure.pixel_utils import (
    bgr_to_rgb,
    compute_display_levels,
    dr_percentiles_from_slider,
)


class ContourViewBox(pg.ViewBox):
    """ViewBox: clicks for tools; wheel steps frames; no pan/zoom drag."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._viewer_widget: ViewerWidget | None = None
        self.setMenuEnabled(False)
        self.setMouseEnabled(x=False, y=False)

    def set_viewer_widget(self, viewer_widget: ViewerWidget) -> None:
        self._viewer_widget = viewer_widget

    def mouseClickEvent(self, ev) -> None:  # type: ignore[override]
        if ev.button() == Qt.MouseButton.RightButton:
            ev.accept()
            return
        if self._viewer_widget is not None and self._viewer_widget._handle_contour_mouse_click(ev):
            return
        ev.accept()

    def mouseDragEvent(self, ev) -> None:  # type: ignore[override]
        if ev.button() == Qt.MouseButton.RightButton:
            ev.accept()
            return
        ev.ignore()

    def wheelEvent(self, ev, axis=None) -> None:  # type: ignore[override]
        if self._viewer_widget is not None and self._viewer_widget._handle_wheel(ev):
            return
        ev.ignore()


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
        self._base_pen = pen
        self.setZValue(30)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setData([position[0]], [position[1]])

    def set_indices(self, contour_index: int, point_index: int) -> None:
        self._contour_index = contour_index
        self._point_index = point_index

    def set_rbf_highlight(self, *, active: bool) -> None:
        if active:
            highlight = pg.mkPen("#4caf50", width=2)
            self.setPen(highlight)
            self.setBrush(pg.mkBrush("#4caf50"))
            self.setSize(12)
        else:
            self.setPen(self._base_pen)
            self.setBrush(pg.mkBrush(self._base_pen.color()))
            self.setSize(10)

    def mouseDragEvent(self, ev) -> None:  # type: ignore[override]
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        ev.accept()
        view_box = self.getViewBox() or self._viewer_widget._view
        point = view_box.mapSceneToView(ev.scenePos())
        x = float(point.x())
        y = float(point.y())
        if ev.isFinish():
            self._viewer_widget._finalize_contour_point_drag(
                self._contour_index,
                self._point_index,
                x,
                y,
            )
            return
        self._viewer_widget._drag_contour_point(
            self._contour_index,
            self._point_index,
            x,
            y,
        )


class ViewerWidget(QWidget):
    """Display a frame with playback controls and window/level sliders."""

    play_pause_requested = Signal()
    frame_selected = Signal(int)
    contour_completed = Signal(object)
    contours_changed = Signal(object)
    linear_measurements_changed = Signal(object)
    calibration_completed = Signal(object)

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
        self._calibration_roi: pg.LineROI | None = None
        self._stored_contours: list[Contour] = []
        self._contours: list[Contour] = []
        self._contour_items: list[pg.PlotDataItem] = []
        self._contour_nodes: list[list[_ContourNodeItem]] = []
        self._caliper_labels = [
            "LVEDD",
            "LVESD",
            "IVSd",
            "LVPWd",
            "LVOT",
            "LA",
            "LAL",
            "RV basal",
            "TAPSE",
        ]
        self._caliper_label_index = 0
        self._contour_mode_active = False
        self._contour_mode_kind: Literal["manual", "model", "closed"] | None = None
        self._active_contour_chamber: str = "LV"
        self._contour_stage: Literal[
            "ma_septal", "ma_lateral", "arc", "apex", "polygon"
        ] | None = None
        self._active_mitral_septal: tuple[float, float] | None = None
        self._active_mitral_annulus: tuple[tuple[float, float], tuple[float, float]] | None = (
            None
        )
        self._active_arc_points: list[tuple[float, float]] = []
        self._active_contour_item: pg.PlotDataItem | None = None
        self._active_ma_chord_item: pg.PlotDataItem | None = None
        self._active_contour_phase: str | None = None
        self._contour_pen_manual = pg.mkPen("#ff6f00", width=2)
        self._contour_pen_ai = pg.mkPen("#00bcd4", width=2)
        self._contour_pen_model = pg.mkPen("#4caf50", width=2)
        self._contour_pen_ma = pg.mkPen("#ff6f00", width=1, style=Qt.PenStyle.DashLine)
        self._contour_ma_items: list[pg.PlotDataItem | None] = []
        self._active_contour_view = "A4C"
        self._frame_overlay_lines: list[str] = []
        self._pending_viewer_state: ViewerState | None = None
        self._stored_linear_measurements: dict[str, LinearMeasurement] = {}
        self._caliper_sequence: list[str] = []
        self._syncing_state = False
        self._is_color_frame = False
        self._drag_session: tuple[int, float, float] | None = None

        self._overlay_label = QLabel(self)
        self._overlay_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._overlay_label.setStyleSheet(
            "background-color: rgba(0, 0, 0, 180);"
            " color: #f5f5f5;"
            " padding: 8px;"
            " font-size: 12px;"
            " border: 1px solid #4caf50;"
        )
        self._overlay_label.hide()

        self._timeline_slider = QSlider(Qt.Orientation.Horizontal)
        self._timeline_slider.setSingleStep(1)
        self._timeline_slider.valueChanged.connect(self._on_timeline_changed)

        self._play_button = QPushButton("Play")
        self._play_button.clicked.connect(self.play_pause_requested.emit)

        self._fps_label = QLabel("FPS: —")
        self._source_label = QLabel("Frame: —")
        self._measurement_label = QLabel(f"{self._current_caliper_label()}: —")

        self._window_slider = QSlider(Qt.Orientation.Horizontal)
        self._window_slider.setRange(1, 400)
        self._window_slider.setValue(100)
        self._window_slider.valueChanged.connect(self._update_levels)

        self._level_slider = QSlider(Qt.Orientation.Horizontal)
        self._level_slider.setRange(0, 100)
        self._level_slider.setValue(50)
        self._level_slider.valueChanged.connect(self._update_levels)

        self._dr_slider = QSlider(Qt.Orientation.Horizontal)
        self._dr_slider.setRange(0, 100)
        self._dr_slider.setValue(50)
        self._dr_slider.setToolTip(
            "Dynamic range: center = full range; left = clip dark (typical for US)"
        )
        self._dr_slider.valueChanged.connect(self._update_levels)

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
        wl_row.addWidget(QLabel("DR"))
        wl_row.addWidget(self._dr_slider, stretch=1)
        wl_row.addWidget(self._measurement_label)
        controls.addLayout(wl_row)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._graphics)
        layout.addLayout(controls)
        self._graphics.installEventFilter(self)
        self._graphics.setFocusPolicy(Qt.FocusPolicy.WheelFocus)

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        if event.type() == QEvent.Type.Wheel and watched is self._graphics:
            if self._handle_wheel(event):
                return True
        return super().eventFilter(watched, event)

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        if self._handle_wheel(event):
            event.accept()
        else:
            super().wheelEvent(event)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        geo = self._graphics.geometry()
        self._overlay_label.move(geo.x() + 8, geo.y() + 8)

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
            with QSignalBlocker(self._dr_slider):
                self._dr_slider.setValue(50)
            self._update_levels()
        self._window_slider.setEnabled(not self._is_color_frame)
        self._level_slider.setEnabled(not self._is_color_frame)
        self._dr_slider.setEnabled(not self._is_color_frame)
        if self._current_frame is not None:
            height, width = self._current_frame.shape[:2]
            self._view.setRange(xRange=(0, width), yRange=(0, height), padding=0)

    def clear(self) -> None:
        self._image_item.clear()
        self._clear_linear_caliper()
        self._clear_calibration_caliper()
        self._clear_contours()

    def set_state(self, viewer_state: ViewerState) -> None:
        if self._syncing_state:
            self._pending_viewer_state = viewer_state
            return
        self._syncing_state = True
        previous_instance = self._current_state.instance if self._current_state else None
        previous_frame = (
            self._current_state.current_frame_index if self._current_state else None
        )
        frame_changed = previous_frame != viewer_state.current_frame_index
        if previous_instance != viewer_state.instance:
            self._clear_linear_caliper()
            self._clear_calibration_caliper()
            self._clear_contours()
            self._stored_linear_measurements = {}
        elif frame_changed:
            self._clear_active_contour_drawing()
        if frame_changed:
            self._clear_frame_overlay()
        self._stored_linear_measurements = {
            measurement.label: measurement
            for measurement in viewer_state.linear_measurements
        }
        self._current_state = viewer_state
        try:
            maximum = max(0, viewer_state.total_frames - 1)
            self._timeline_slider.setRange(0, maximum)
            controls_enabled = (
                viewer_state.total_frames > 1 and not viewer_state.decode_in_progress
            )
            self._timeline_slider.setEnabled(controls_enabled)
            self._play_button.setEnabled(controls_enabled)
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
            self._update_timeline_indicator(viewer_state)
            contours_updated = tuple(self._stored_contours) != viewer_state.contours
            if contours_updated:
                self._stored_contours = list(viewer_state.contours)
            if frame_changed or contours_updated:
                self._render_contours_for_current_frame()
            self._update_linear_measurement_preview()
            if frame_changed or contours_updated:
                self._refresh_lv_frame_overlay()
        finally:
            self._syncing_state = False
            pending = self._pending_viewer_state
            self._pending_viewer_state = None
            if pending is not None:
                self.set_state(pending)

    def toggle_linear_caliper(self) -> None:
        if self._linear_roi is not None:
            self._clear_linear_caliper()
            return
        self._clear_calibration_caliper()
        self.start_linear_caliper_for(self._current_caliper_label())

    def toggle_calibration_caliper(self) -> None:
        if self._calibration_roi is not None:
            self._clear_calibration_caliper()
            return
        self._clear_linear_caliper()
        if self._current_frame is None:
            return

        height, width = self._current_frame.shape[:2]
        line_width = max(float(min(width, height)) * 0.02, 4.0)
        start_x = max(float(width) * 0.08, 5.0)
        start_y = float(height) * 0.25
        end_y = float(height) * 0.75
        roi = pg.LineROI(
            (start_x, start_y),
            (start_x, min(end_y, float(height - 1))),
            line_width,
            pen=pg.mkPen("#29b6f6", width=2),
        )
        self._view.addItem(roi)
        self._calibration_roi = roi
        self._measurement_label.setText("Калибровка: задайте линию → Enter")

    def finish_calibration(self) -> bool:
        if self._calibration_roi is None:
            return False

        pixel_length = float(self._calibration_roi.size().x())
        angle_degrees = float(self._calibration_roi.angle())
        length_px = pixel_length_along_angle(pixel_length, angle_degrees)
        known_mm, accepted = QInputDialog.getDouble(
            self,
            "Калибровка по шкале глубины",
            "Известное расстояние (мм), например 50 для отметок 0–5 см:",
            50.0,
            0.1,
            10000.0,
            1,
        )
        if not accepted:
            return True
        spacing = spacing_from_known_distance(length_px, known_mm)
        self._clear_calibration_caliper()
        if not self._syncing_state:
            self.calibration_completed.emit(spacing)
        return True

    @property
    def is_calibration_active(self) -> bool:
        return self._calibration_roi is not None

    def start_linear_caliper_for(self, label: str) -> bool:
        self._caliper_sequence = []
        return self._begin_linear_caliper(label)

    def start_linear_caliper_sequence(self, labels: tuple[str, ...]) -> bool:
        if not labels:
            return False
        self._caliper_sequence = list(labels[1:])
        return self._begin_linear_caliper(labels[0])

    def _begin_linear_caliper(self, label: str) -> bool:
        if self._linear_roi is not None:
            self._view.removeItem(self._linear_roi)
            self._linear_roi = None
        self._clear_calibration_caliper()
        if self._current_frame is None:
            return False
        self._set_caliper_label(label)
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
        roi.sigRegionChanged.connect(self._update_linear_measurement_preview)
        roi.sigRegionChangeFinished.connect(self._commit_linear_measurement)
        self._view.addItem(roi)
        self._linear_roi = roi
        self._measurement_label.setText(f"{label}: —")
        self._update_linear_measurement_preview()
        return True

    def cycle_caliper_label(self) -> None:
        self._caliper_label_index = (self._caliper_label_index + 1) % len(
            self._caliper_labels
        )
        if self._linear_roi is None:
            self._measurement_label.setText(f"{self._current_caliper_label()}: —")
        if self._linear_roi is not None:
            self._update_linear_measurement_preview()

    def start_contour(
        self,
        *,
        phase: str | None = None,
        view: str = "A4C",
    ) -> bool:
        return self._start_contour_drawing(
            mode_kind="manual",
            pen=self._contour_pen_manual,
            phase=phase,
            view=view,
        )

    def start_model_contour(
        self,
        *,
        phase: str | None = None,
        view: str = "A4C",
    ) -> bool:
        return self._start_contour_drawing(
            mode_kind="model",
            pen=self._contour_pen_model,
            phase=phase,
            view=view,
        )

    def start_closed_contour(
        self,
        *,
        chamber: str = "LA",
        phase: str | None = None,
        view: str = "A4C",
    ) -> bool:
        return self._start_contour_drawing(
            mode_kind="closed",
            pen=self._contour_pen_manual,
            phase=phase,
            view=view,
            chamber=chamber,
        )

    def _start_contour_drawing(
        self,
        *,
        mode_kind: Literal["manual", "model", "closed"],
        pen: pg.QtGui.QPen,
        phase: str | None = None,
        view: str = "A4C",
        chamber: str = "LV",
    ) -> bool:
        if self._current_frame is None:
            return False
        if self._active_contour_item is not None:
            return False

        self.cancel_active_tool()
        self._active_contour_view = view
        self._active_contour_phase = phase or self._resolve_contour_phase()
        self._active_contour_chamber = chamber
        self._contour_mode_active = True
        self._contour_mode_kind = mode_kind
        self._contour_stage = "polygon" if mode_kind == "closed" else "ma_septal"
        self._active_mitral_septal = None
        self._active_mitral_annulus = None
        self._active_arc_points = []
        self._active_contour_item = pg.PlotDataItem(
            pen=pen,
            symbol="o",
            symbolSize=6,
            symbolBrush=pen.color(),
        )
        self._active_contour_item.setZValue(20)
        self._view.addItem(self._active_contour_item)
        return True

    def set_contour_from_domain(self, contour: Contour) -> None:
        self._upsert_stored_contour(contour)
        self._render_contours_for_current_frame()
        self._refresh_lv_frame_overlay()
        if not self._syncing_state:
            self.contours_changed.emit(self.contours())

    def apply_contours(self, contours: list[Contour]) -> None:
        self._stored_contours = list(contours)
        self._render_contours_for_current_frame()

    def handle_contour_click(self, point: tuple[float, float]) -> bool:
        if not self._contour_mode_active or self._active_contour_item is None:
            return False

        click = (float(point[0]), float(point[1]))
        if self._contour_stage == "ma_septal":
            self._active_mitral_septal = click
            self._contour_stage = "ma_lateral"
        elif self._contour_stage == "ma_lateral":
            if self._active_mitral_septal is None:
                return False
            self._active_mitral_annulus = (self._active_mitral_septal, click)
            self._show_active_ma_chord()
            self._contour_stage = "apex"
        elif self._contour_stage == "apex":
            if self._contour_mode_kind == "model":
                return self._finish_model_contour(apex=click)
            return self._finish_manual_contour(apex=click)
        elif self._contour_stage == "arc":
            self._active_arc_points.append(click)
        elif self._contour_stage == "polygon":
            self._active_arc_points.append(click)
        self._update_active_contour_item()
        return True

    def _finish_model_contour(self, *, apex: tuple[float, float]) -> bool:
        if self._active_mitral_annulus is None:
            return False
        septal, lateral = self._active_mitral_annulus
        try:
            contour = fit_contour_from_landmarks(
                septal=septal,
                lateral=lateral,
                apex=apex,
                phase=self._active_contour_phase or "ED",
                view=self._active_contour_view,
            )
            contour.frame_index = self._contour_frame_index()
        except ValueError:
            return False
        self._clear_active_contour_drawing()
        self.set_contour_from_domain(contour)
        self.contour_completed.emit(contour)
        return True

    def refine_active_open_contour(self) -> bool:
        """Active contour refine on manual or model LV open arc for the current frame."""
        if self._current_frame is None:
            return False
        frame_index = self._contour_frame_index()
        for contour_index, contour in enumerate(self._contours):
            if (
                contour.chamber.upper() != "LV"
                or contour.source not in {"manual", "model"}
                or not contour.is_open_arc
                or contour.mitral_annulus is None
                or contour.frame_index != frame_index
            ):
                continue
            refined = refine_open_arc_contour(self._current_frame, contour)
            num_nodes = refined.num_nodes or DEFAULT_NODE_COUNT
            refined.points = resample_open_arc(refined.points, num_nodes=num_nodes)
            if refined.mitral_annulus is not None:
                refined.mitral_annulus = (refined.points[0], refined.points[-1])
            self._contours[contour_index] = refined
            self._upsert_stored_contour(refined)
            self._render_contours_for_current_frame()
            self._refresh_lv_frame_overlay()
            if not self._syncing_state:
                self.contours_changed.emit(self.contours())
            return True
        return False

    def refine_active_model_contour(self) -> bool:
        """Backward-compatible alias for refine_active_open_contour."""
        return self.refine_active_open_contour()

    def _finish_manual_contour(self, *, apex: tuple[float, float]) -> bool:
        if self._active_mitral_annulus is None:
            return False

        septal, lateral = self._active_mitral_annulus
        raw_arc = [septal, apex, lateral]
        resampled = resample_open_arc(raw_arc, num_nodes=DEFAULT_NODE_COUNT)
        contour = Contour(
            phase=self._active_contour_phase or "ED",
            view=self._active_contour_view,
            mitral_annulus=self._active_mitral_annulus,
            points=resampled,
            num_nodes=DEFAULT_NODE_COUNT,
            frame_index=self._contour_frame_index(),
        )
        self._clear_active_contour_drawing()
        self.set_contour_from_domain(contour)
        self.contour_completed.emit(contour)
        return True

    def finish_contour(self) -> bool:
        if not self._contour_mode_active or self._active_contour_item is None:
            return False
        if self._contour_stage == "polygon":
            return self._finish_closed_contour()
        if (
            self._contour_stage != "arc"
            or self._active_mitral_annulus is None
            or len(self._active_arc_points) < 1
        ):
            return False

        septal, lateral = self._active_mitral_annulus
        raw_arc = [septal, *self._active_arc_points, lateral]
        resampled = resample_open_arc(raw_arc, num_nodes=DEFAULT_NODE_COUNT)
        contour = Contour(
            phase=self._active_contour_phase or "ED",
            view=self._active_contour_view,
            mitral_annulus=self._active_mitral_annulus,
            points=resampled,
            num_nodes=DEFAULT_NODE_COUNT,
            frame_index=self._contour_frame_index(),
        )
        self._clear_active_contour_drawing()
        self.set_contour_from_domain(contour)
        self.contour_completed.emit(contour)
        return True

    def _finish_closed_contour(self) -> bool:
        if len(self._active_arc_points) < 3:
            return False

        contour = Contour(
            phase=self._active_contour_phase or "ES",
            view=self._active_contour_view,
            chamber=self._active_contour_chamber,
            points=list(self._active_arc_points),
            frame_index=self._contour_frame_index(),
        )
        self._clear_active_contour_drawing()
        self.append_frame_overlay(
            f"{contour.view} {contour.chamber} {contour.phase} area contour"
        )
        self.set_contour_from_domain(contour)
        self.contour_completed.emit(contour)
        return True

    def cancel_active_tool(self) -> None:
        if self._active_contour_item is not None:
            self._clear_active_contour_drawing()
            return
        if self._calibration_roi is not None:
            self._clear_calibration_caliper()
            return
        self._clear_linear_caliper()

    def contours(self) -> list[Contour]:
        return list(self._stored_contours)

    def delete_contour_for_current_phase(self, view: str = "A4C") -> bool:
        """Remove contour for the current frame, resolved phase, and view."""
        if self._current_state is None:
            return False
        phase = self._resolve_contour_phase()
        frame_index = self._current_state.current_frame_index
        before = len(self._stored_contours)
        self._stored_contours = [
            contour
            for contour in self._stored_contours
            if not (
                contour.phase.casefold() == phase.casefold()
                and contour.view.casefold() == view.casefold()
                and contour.chamber.casefold() == "LV"
                and contour.frame_index == frame_index
            )
        ]
        if len(self._stored_contours) == before:
            return False
        self._render_contours_for_current_frame()
        if not self._syncing_state:
            self.contours_changed.emit(self.contours())
        return True

    @property
    def is_contour_mode_active(self) -> bool:
        return self._contour_mode_active

    def _handle_wheel(self, ev) -> bool:
        if self._current_state is None or self._current_state.total_frames <= 1:
            return False
        if self._current_state.decode_in_progress:
            return False
        if hasattr(ev, "angleDelta"):
            delta_y = ev.angleDelta().y()
        elif hasattr(ev, "delta"):
            delta_y = ev.delta()
        else:
            return False
        if delta_y == 0:
            return False
        step = -1 if delta_y > 0 else 1
        current = self._current_state.current_frame_index
        total = self._current_state.total_frames
        new_index = (current + step) % total
        if new_index == current:
            return False
        ev.accept()
        self.frame_selected.emit(new_index)
        return True

    def _update_timeline_indicator(self, viewer_state: ViewerState) -> None:
        self._timeline_slider.setToolTip("")
        self._timeline_slider.setStyleSheet("")

    def append_frame_overlay(self, line: str) -> None:
        self._frame_overlay_lines.append(line)
        self._refresh_frame_overlay()

    def clear_frame_overlay(self) -> None:
        self._frame_overlay_lines.clear()
        self._refresh_frame_overlay()

    def _clear_frame_overlay(self) -> None:
        self.clear_frame_overlay()

    def _refresh_frame_overlay(self) -> None:
        if self._frame_overlay_lines:
            self._overlay_label.setText("\n".join(self._frame_overlay_lines))
            self._overlay_label.adjustSize()
            self._overlay_label.show()
            self._overlay_label.raise_()
        else:
            self._overlay_label.hide()

    def _clear_linear_caliper(self) -> None:
        if self._linear_roi is not None:
            self._view.removeItem(self._linear_roi)
            self._linear_roi = None
        self._caliper_sequence = []
        self._measurement_label.setText(f"{self._current_caliper_label()}: —")
        if not self._syncing_state:
            self._emit_stored_linear_measurements()

    def _clear_calibration_caliper(self) -> None:
        if self._calibration_roi is not None:
            self._view.removeItem(self._calibration_roi)
            self._calibration_roi = None
        if self._linear_roi is None:
            self._measurement_label.setText(f"{self._current_caliper_label()}: —")

    def _clear_rendered_contours(self) -> None:
        for nodes in self._contour_nodes:
            for node in nodes:
                self._view.removeItem(node)
        for item in self._contour_items:
            self._view.removeItem(item)
        for ma_item in self._contour_ma_items:
            if ma_item is not None:
                self._view.removeItem(ma_item)
        self._contour_items.clear()
        self._contour_nodes.clear()
        self._contour_ma_items.clear()
        self._contours.clear()

    def _clear_contours(self) -> None:
        self._stored_contours.clear()
        self._clear_rendered_contours()
        self._clear_active_contour_drawing()
        if not self._syncing_state:
            self.contours_changed.emit([])

    def _render_contours_for_current_frame(self) -> None:
        if self._current_state is None:
            visible = list(self._stored_contours)
        else:
            frame_index = self._current_state.current_frame_index
            visible = [
                contour
                for contour in self._stored_contours
                if contour.frame_index == frame_index
            ]
        self._clear_rendered_contours()
        for contour in visible:
            self._append_rendered_contour(contour)

    def _upsert_stored_contour(self, contour: Contour) -> None:
        contour_index = self._find_stored_contour_index(contour)
        if contour_index is None:
            self._stored_contours.append(contour)
        else:
            self._stored_contours[contour_index] = contour

    def _append_rendered_contour(self, contour: Contour) -> None:
        contour_index = len(self._contours)
        self._contours.append(contour)
        line_item, ma_item, node_items = self._create_contour_render(contour, contour_index)
        self._contour_items.append(line_item)
        self._contour_ma_items.append(ma_item)
        self._contour_nodes.append(node_items)
        self._reindex_contour_nodes()

    def _find_stored_contour_index(self, contour: Contour) -> int | None:
        for index, existing in enumerate(self._stored_contours):
            if (
                existing.phase.casefold() == contour.phase.casefold()
                and existing.view.casefold() == contour.view.casefold()
                and existing.chamber.casefold() == contour.chamber.casefold()
                and existing.frame_index == contour.frame_index
            ):
                return index
        return None

    def _contour_frame_index(self) -> int | None:
        if self._current_state is None:
            return None
        return self._current_state.current_frame_index

    def _clear_active_contour_drawing(self) -> None:
        if self._active_contour_item is not None:
            self._view.removeItem(self._active_contour_item)
            self._active_contour_item = None
        if self._active_ma_chord_item is not None:
            self._view.removeItem(self._active_ma_chord_item)
            self._active_ma_chord_item = None
        self._active_mitral_septal = None
        self._active_mitral_annulus = None
        self._active_arc_points = []
        self._active_contour_phase = None
        self._contour_stage = None
        self._contour_mode_kind = None
        self._contour_mode_active = False

    def _remove_rendered_contour(self, contour_index: int) -> None:
        if self._drag_session is not None and self._drag_session[0] == contour_index:
            self._clear_drag_session()
        elif self._drag_session is not None and self._drag_session[0] > contour_index:
            idx, lx, ly = self._drag_session
            self._drag_session = (idx - 1, lx, ly)
        line_item = self._contour_items.pop(contour_index)
        ma_item = self._contour_ma_items.pop(contour_index)
        for node in self._contour_nodes.pop(contour_index):
            self._view.removeItem(node)
        self._view.removeItem(line_item)
        if ma_item is not None:
            self._view.removeItem(ma_item)
        self._reindex_contour_nodes()

    def _create_contour_render(
        self,
        contour: Contour,
        contour_index: int,
    ) -> tuple[pg.PlotDataItem, pg.PlotDataItem | None, list[_ContourNodeItem]]:
        pen = self._contour_pen_for(contour)
        line_item = pg.PlotDataItem(pen=pen)
        line_item.setZValue(20)
        x_values, y_values = self._contour_xy(contour, closed=not contour.is_open_arc)
        line_item.setData(x_values, y_values)
        self._view.addItem(line_item)

        ma_item: pg.PlotDataItem | None = None
        if contour.is_open_arc and contour.mitral_annulus is not None:
            septal, lateral = contour.mitral_annulus
            ma_item = pg.PlotDataItem(pen=self._contour_pen_ma)
            ma_item.setZValue(19)
            ma_item.setData([septal[0], lateral[0]], [septal[1], lateral[1]])
            self._view.addItem(ma_item)

        node_items: list[_ContourNodeItem] = []
        for point_index, point in enumerate(contour.points):
            node = _ContourNodeItem(self, contour_index, point_index, point, pen)
            self._view.addItem(node)
            node_items.append(node)
        return line_item, ma_item, node_items

    def _reindex_contour_nodes(self) -> None:
        for contour_index, node_items in enumerate(self._contour_nodes):
            for point_index, node in enumerate(node_items):
                node.set_indices(contour_index, point_index)

    def _contour_pen_for(self, contour: Contour) -> pg.QtGui.QPen:
        if contour.source == "ai":
            return self._contour_pen_ai
        if contour.source == "model":
            return self._contour_pen_model
        return self._contour_pen_manual

    def _contour_xy(
        self,
        contour: Contour,
        *,
        closed: bool = False,
    ) -> tuple[list[float], list[float]]:
        points = list(contour.points)
        if contour.is_open_arc and len(points) >= 2:
            points = sample_spline(points, num_samples=max(len(points) * 8, 128))
        elif closed and points:
            points = points + [points[0]]
        if not points:
            return [], []
        x_values = [point[0] for point in points]
        y_values = [point[1] for point in points]
        return x_values, y_values

    def _sigma_for_contour_drag(self) -> float:
        x_range, _y_range = self._view.viewRange()
        range_width = x_range[1] - x_range[0]
        viewport_w = float(self._view.width())
        if viewport_w < 10.0 and self._current_frame is not None:
            viewport_w = max(range_width, float(self._current_frame.shape[1]))
        return sigma_from_view_range(range_width, max(viewport_w, 1.0))

    def _pinned_indices_for_contour(self, contour: Contour) -> frozenset[int]:
        if contour.is_open_arc and len(contour.points) >= 2:
            return frozenset({0, len(contour.points) - 1})
        return frozenset()

    def _snap_open_arc_endpoints(self, contour: Contour) -> None:
        if not contour.is_open_arc or contour.mitral_annulus is None:
            return
        septal, lateral = contour.mitral_annulus
        contour.points[0] = septal
        contour.points[-1] = lateral

    def _update_contour_node_highlights(
        self,
        contour_index: int,
        weights: np.ndarray,
    ) -> None:
        if contour_index < 0 or contour_index >= len(self._contour_nodes):
            return
        for idx, node in enumerate(self._contour_nodes[contour_index]):
            active = idx < len(weights) and weights[idx] > WEIGHT_ACTIVE_THRESHOLD
            node.set_rbf_highlight(active=active)

    def _clear_contour_node_highlights(self, contour_index: int) -> None:
        if contour_index < 0 or contour_index >= len(self._contour_nodes):
            return
        for node in self._contour_nodes[contour_index]:
            node.set_rbf_highlight(active=False)

    def _clear_drag_session(self) -> None:
        self._drag_session = None

    def _apply_rbf_drag_step(
        self,
        contour_index: int,
        x: float,
        y: float,
        *,
        force: bool = False,
    ) -> bool:
        """Return True if displacement was applied."""
        if contour_index < 0 or contour_index >= len(self._contours):
            return False
        contour = self._contours[contour_index]

        if self._drag_session is None or self._drag_session[0] != contour_index:
            self._drag_session = (contour_index, x, y)
            return False

        last_x, last_y = self._drag_session[1], self._drag_session[2]
        delta = (x - last_x, y - last_y)
        if not force and math.hypot(delta[0], delta[1]) < MIN_DELTA_NORM:
            return False

        sigma = self._sigma_for_contour_drag()
        cursor = (x, y)
        pinned = self._pinned_indices_for_contour(contour)
        weights = gaussian_weights(contour.points, cursor, sigma, pinned_indices=pinned)
        updated = apply_gaussian_displacement(contour.points, delta, weights)
        contour.points[:] = updated
        self._snap_open_arc_endpoints(contour)

        for idx, point in enumerate(contour.points):
            self._contour_nodes[contour_index][idx].setData([point[0]], [point[1]])
        self._update_contour_node_highlights(contour_index, weights)
        self._refresh_rendered_contour_geometry(contour_index)
        self._drag_session = (contour_index, x, y)
        return True

    def _drag_contour_point(
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
        self._apply_rbf_drag_step(contour_index, x, y)

    def _finalize_contour_point_drag(
        self,
        contour_index: int,
        point_index: int,
        x: float,
        y: float,
    ) -> None:
        if contour_index < 0 or contour_index >= len(self._contours):
            self._clear_drag_session()
            return
        contour = self._contours[contour_index]
        if self._drag_session is None and 0 <= point_index < len(contour.points):
            sx, sy = contour.points[point_index]
            self._drag_session = (contour_index, sx, sy)
        self._apply_rbf_drag_step(contour_index, x, y, force=True)
        contour = self._contours[contour_index]
        if contour.is_open_arc:
            num_nodes = contour.num_nodes or DEFAULT_NODE_COUNT
            resampled = resample_open_arc(contour.points, num_nodes=num_nodes)
            contour.points[:] = resampled
            if contour.mitral_annulus is not None:
                contour.mitral_annulus = (resampled[0], resampled[-1])
            for idx, point in enumerate(resampled):
                self._contour_nodes[contour_index][idx].setData([point[0]], [point[1]])
            self._refresh_rendered_contour_geometry(contour_index)
        self._clear_contour_node_highlights(contour_index)
        self._clear_drag_session()
        self._upsert_stored_contour(contour)
        self.contours_changed.emit(self.contours())
        current_frame = self._contour_frame_index()
        if (
            contour.chamber.upper() == "LV"
            and contour.frame_index == current_frame
        ):
            self._refresh_lv_frame_overlay()

    def _refresh_rendered_contour_geometry(self, contour_index: int) -> None:
        if contour_index < 0 or contour_index >= len(self._contours):
            return
        if contour_index >= len(self._contour_items):
            return
        contour = self._contours[contour_index]
        closed = not contour.is_open_arc
        x_values, y_values = self._contour_xy(contour, closed=closed)
        self._contour_items[contour_index].setData(x_values, y_values)

    def _resolve_contour_phase(self) -> str:
        return "ED"

    def _effective_pixel_spacing(self) -> tuple[tuple[float, float], bool]:
        if self._current_state is not None:
            spacing = self._current_state.effective_pixel_spacing
            if spacing is not None:
                row_spacing, col_spacing = spacing
                if row_spacing > 0.0 and col_spacing > 0.0:
                    return spacing, True
        return (1.0, 1.0), False

    def _refresh_lv_frame_overlay(self, *, extra_lines: tuple[str, ...] = ()) -> None:
        self.clear_frame_overlay()
        frame_index = self._contour_frame_index()
        spacing, spacing_calibrated = self._effective_pixel_spacing()
        if frame_index is not None:
            for contour in self._stored_contours:
                if (
                    contour.chamber.upper() == "LV"
                    and contour.is_open_arc
                    and contour.frame_index == frame_index
                ):
                    self.append_frame_overlay(
                        format_contour_overlay(
                            contour,
                            spacing,
                            spacing_calibrated=spacing_calibrated,
                        )
                    )
        for line in extra_lines:
            self.append_frame_overlay(line)

    def _pixel_spacing(self) -> tuple[float, float] | None:
        spacing, _calibrated = self._effective_pixel_spacing()
        return spacing

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

    def _show_active_ma_chord(self) -> None:
        if self._active_mitral_annulus is None:
            return
        if self._active_ma_chord_item is None:
            self._active_ma_chord_item = pg.PlotDataItem(pen=self._contour_pen_ma)
            self._active_ma_chord_item.setZValue(19)
            self._view.addItem(self._active_ma_chord_item)
        septal, lateral = self._active_mitral_annulus
        self._active_ma_chord_item.setData([septal[0], lateral[0]], [septal[1], lateral[1]])

    def _update_active_contour_item(self) -> None:
        if self._active_contour_item is None:
            return
        markers: list[tuple[float, float]] = []
        spline_points: list[tuple[float, float]] = []
        if self._contour_stage == "ma_septal" and self._active_mitral_septal is not None:
            markers = [self._active_mitral_septal]
        elif self._contour_stage == "ma_lateral":
            if self._active_mitral_septal is not None:
                markers = [self._active_mitral_septal]
        elif self._contour_stage == "apex" and self._active_mitral_annulus is not None:
            septal, lateral = self._active_mitral_annulus
            markers = [septal, lateral]
        elif self._contour_stage == "arc" and self._active_mitral_annulus is not None:
            septal, lateral = self._active_mitral_annulus
            markers = [septal, *self._active_arc_points, lateral]
            if len(markers) >= 2:
                spline_points = (
                    sample_spline(markers, num_samples=64) if len(markers) >= 3 else markers
                )
        elif self._contour_stage == "polygon" and self._active_arc_points:
            markers = list(self._active_arc_points)
            if len(markers) >= 2:
                closed = [*markers, markers[0]]
                spline_points = (
                    sample_spline(closed, num_samples=64) if len(closed) >= 3 else closed
                )
        if spline_points:
            x_values = [point[0] for point in spline_points]
            y_values = [point[1] for point in spline_points]
            self._active_contour_item.setData(x_values, y_values)
        elif markers:
            x_values = [point[0] for point in markers]
            y_values = [point[1] for point in markers]
            self._active_contour_item.setData(x_values, y_values)
        else:
            self._active_contour_item.setData([], [])

    def _build_current_linear_measurement(self) -> LinearMeasurement | None:
        if self._linear_roi is None:
            return None
        pixel_length = float(self._linear_roi.size().x())
        angle_degrees = float(self._linear_roi.angle())
        pixel_spacing = (
            self._current_state.effective_pixel_spacing if self._current_state else None
        )
        millimeter_length = (
            pixel_to_mm_length(pixel_length, angle_degrees, pixel_spacing)
            if pixel_spacing is not None
            else None
        )
        return LinearMeasurement(
            label=self._current_caliper_label(),
            pixel_length=pixel_length,
            millimeter_length=millimeter_length,
        )

    def _update_linear_measurement_preview(self, *_args) -> None:
        measurement = self._build_current_linear_measurement()
        if measurement is None:
            self._measurement_label.setText(f"{self._current_caliper_label()}: —")
            return
        self._measurement_label.setText(measurement.display_text())

    def _commit_linear_measurement(self, *_args) -> None:
        measurement = self._build_current_linear_measurement()
        if measurement is None:
            return
        self._stored_linear_measurements[measurement.label] = measurement
        self.append_frame_overlay(measurement.display_text())
        self._measurement_label.setText(measurement.display_text())
        self._emit_stored_linear_measurements()
        if self._caliper_sequence:
            next_label = self._caliper_sequence.pop(0)
            self._begin_linear_caliper(next_label)
        elif self._linear_roi is not None:
            self._view.removeItem(self._linear_roi)
            self._linear_roi = None

    def _emit_stored_linear_measurements(self) -> None:
        measurements = list(self._stored_linear_measurements.values())
        self.linear_measurements_changed.emit(measurements)

    def _set_caliper_label(self, label: str) -> None:
        if label not in self._caliper_labels:
            self._caliper_labels.append(label)
        self._caliper_label_index = self._caliper_labels.index(label)

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
        dr_low, dr_high = dr_percentiles_from_slider(self._dr_slider.value())
        low, high = compute_display_levels(
            frame,
            dr_low_pct=dr_low,
            dr_high_pct=dr_high,
            window_scale=self._window_slider.value() / 100.0,
            level_offset=(self._level_slider.value() - 50) / 50.0,
        )
        self._image_item.setLevels((low, high))

    def _current_caliper_label(self) -> str:
        return self._caliper_labels[self._caliper_label_index]
