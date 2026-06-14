"""2D image viewer using PyQtGraph."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QEvent, QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsView,
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
    apex_point,
    apply_gaussian_displacement,
    nearest_control_point_index,
    rbf_influence_weights,
    resample_open_arc,
    resample_open_arc_landmarks,
    sample_spline,
    tiered_influence_weights,
)
from echo_personal_tool.domain.services.mbs_lite_service import (
    fit_contour_from_landmarks,
    refine_open_arc_contour,
)
from echo_personal_tool.domain.services.pixel_spacing_resolver import (
    spacing_from_known_distance,
)
from echo_personal_tool.infrastructure.pixel_utils import (
    bgr_to_rgb,
    compute_display_levels,
    dr_percentiles_from_slider,
)

CALIBRATION_PROMPT_OVERLAY = "Проведите калибровку"
_CALIBRATION_OVERLAY_STYLE = (
    "background-color: rgba(0, 0, 0, 210);"
    " color: #ffffff;"
    " padding: 20px 36px;"
    " font-size: 22px; font-weight: bold;"
    " border: 2px solid #ffb300;"
    " border-radius: 8px;"
)
_DEFAULT_OVERLAY_STYLE = (
    "background-color: rgba(0, 0, 0, 180);"
    " color: #f5f5f5;"
    " padding: 8px;"
    " font-size: 12px;"
    " border: 1px solid #4caf50;"
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

    def mousePressEvent(self, ev) -> None:  # type: ignore[override]
        if ev.button() == Qt.MouseButton.RightButton:
            ev.accept()
            return
        if (
            self._viewer_widget is not None
            and self._viewer_widget._handle_calibration_mouse_press(ev)
        ):
            ev.accept()
            return
        if (
            self._viewer_widget is not None
            and self._viewer_widget._handle_linear_caliper_mouse_press(ev)
        ):
            ev.accept()
            return
        if (
            self._viewer_widget is not None
            and self._viewer_widget._handle_contour_zone_press(ev)
        ):
            ev.accept()
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev) -> None:  # type: ignore[override]
        if self._viewer_widget is not None and self._viewer_widget._handle_contour_hover(ev):
            ev.accept()
            return
        super().mouseMoveEvent(ev)

    def mouseDragEvent(self, ev) -> None:  # type: ignore[override]
        if ev.button() == Qt.MouseButton.RightButton:
            ev.accept()
            return
        viewer = self._viewer_widget
        if viewer is not None and viewer._handle_contour_zone_drag(ev):
            ev.accept()
            return
        if viewer is not None and viewer._drag_session is not None:
            ev.accept()
            return
        ev.ignore()

    def mouseReleaseEvent(self, ev) -> None:  # type: ignore[override]
        if (
            self._viewer_widget is not None
            and self._viewer_widget._handle_contour_drag_release(ev)
        ):
            ev.accept()
            return
        if (
            self._viewer_widget is not None
            and self._viewer_widget._handle_contour_zone_release(ev)
        ):
            ev.accept()
            return
        super().mouseReleaseEvent(ev)

    def leaveEvent(self, ev) -> None:  # type: ignore[override]
        if self._viewer_widget is not None:
            self._viewer_widget._clear_contour_hover()
        super().leaveEvent(ev)

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
        self.setAcceptHoverEvents(True)
        self.setData([position[0]], [position[1]])

    def set_indices(self, contour_index: int, point_index: int) -> None:
        self._contour_index = contour_index
        self._point_index = point_index

    def set_rbf_highlight(self, *, active: bool, color: str = "#4caf50") -> None:
        if active:
            highlight = pg.mkPen(color, width=2)
            self.setPen(highlight)
            self.setBrush(pg.mkBrush(color))
            self.setSize(12)
        else:
            self.setPen(self._base_pen)
            self.setBrush(pg.mkBrush(self._base_pen.color()))
            self.setSize(10)

    def mousePressEvent(self, ev) -> None:  # type: ignore[override]
        if ev.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(ev)
            return
        ev.accept()
        view_box = self.getViewBox() or self._viewer_widget._view
        point = view_box.mapSceneToView(ev.scenePos())
        self._viewer_widget._begin_contour_node_drag(
            self._contour_index,
            self._point_index,
            float(point.x()),
            float(point.y()),
        )

    def mouseDragEvent(self, ev) -> None:  # type: ignore[override]
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        ev.accept()
        return


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
        scene = self._view.scene()
        if scene is not None:
            scene.sigMouseMoved.connect(self._on_scene_mouse_moved)
        self._image_item = pg.ImageItem(axisOrder="row-major")
        self._image_item.setAutoDownsample(True)
        self._view.addItem(self._image_item)
        self._current_frame: np.ndarray | None = None
        self._current_state: ViewerState | None = None
        self._linear_caliper_active = False
        self._linear_caliper_start: tuple[float, float] | None = None
        self._linear_caliper_line_item: pg.PlotDataItem | None = None
        self._linear_caliper_marker_item: pg.ScatterPlotItem | None = None
        self._calibration_active = False
        self._calibration_x = 0.0
        self._calibration_start_y: float | None = None
        self._calibration_line_item: pg.PlotDataItem | None = None
        self._calibration_marker_item: pg.ScatterPlotItem | None = None
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
            "RA",
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
        self._stored_linear_measurements: dict[tuple[str, int], LinearMeasurement] = {}
        self._persistent_linear_graphics: list[
            tuple[pg.PlotDataItem, pg.ScatterPlotItem]
        ] = []
        self._caliper_sequence: list[str] = []
        self._syncing_state = False
        self._is_color_frame = False
        self._drag_session: tuple[int, float, float, int, int] | None = None
        self._hover_contour_index: int | None = None
        self._hover_tier: int | None = None
        self._hover_grab_index: int | None = None
        self._zone_drag_active = False
        self._drag_overlay_contour_index: int | None = None
        self._last_drag_apply_pos: tuple[float, float] | None = None

        self._overlay_label = QLabel(self)
        self._overlay_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._overlay_label.setStyleSheet(_DEFAULT_OVERLAY_STYLE)
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
        self._graphics.setMouseTracking(True)
        self._graphics.setViewportUpdateMode(
            QGraphicsView.ViewportUpdateMode.FullViewportUpdate,
        )
        self._graphics.installEventFilter(self)
        viewport = self._graphics.viewport()
        if viewport is not None:
            viewport.setMouseTracking(True)
            viewport.installEventFilter(self)
        self._graphics.setFocusPolicy(Qt.FocusPolicy.WheelFocus)

    def _on_scene_mouse_moved(self, scene_pos) -> None:
        if self._calibration_active and self._calibration_start_y is not None:
            mapped = self._view.mapSceneToView(scene_pos)
            if mapped is not None and self._current_frame is not None:
                height = self._current_frame.shape[0]
                end_y = max(0.0, min(float(mapped.y()), float(height - 1)))
                self._update_calibration_preview(self._calibration_start_y, end_y)
            return
        if self._linear_caliper_active and self._linear_caliper_start is not None:
            mapped = self._view.mapSceneToView(scene_pos)
            if mapped is not None:
                end = (float(mapped.x()), float(mapped.y()))
                self._update_linear_caliper_preview(self._linear_caliper_start, end)
                self._update_linear_caliper_label_preview(self._linear_caliper_start, end)
            return
        if self._contour_editing_blocked():
            self._clear_contour_hover()
            return
        if self._drag_session is not None:
            if QApplication.mouseButtons() & Qt.MouseButton.LeftButton:
                mapped = self._view.mapSceneToView(scene_pos)
                if mapped is not None:
                    contour_index, _, _, grab_index, _ = self._drag_session
                    self._apply_rbf_drag_step(
                        contour_index,
                        float(mapped.x()),
                        float(mapped.y()),
                        grab_index=grab_index,
                    )
            return
        mapped = self._view.mapSceneToView(scene_pos)
        if mapped is None:
            return
        self._update_contour_hover((float(mapped.x()), float(mapped.y())))

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        graphics_target = watched is self._graphics or watched is self._graphics.viewport()
        if graphics_target:
            if event.type() == QEvent.Type.Wheel:
                if self._handle_wheel(event):
                    return True
            if event.type() == QEvent.Type.MouseMove:
                if self._drag_session is None and hasattr(event, "globalPosition"):
                    self._handle_contour_hover_at_global(event.globalPosition())
            if (
                event.type() == QEvent.Type.MouseButtonRelease
                and event.button() == Qt.MouseButton.LeftButton
                and self._drag_session is not None
                and hasattr(event, "globalPosition")
            ):
                self._handle_contour_drag_release_from_global(event.globalPosition())
        return super().eventFilter(watched, event)

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        if self._handle_wheel(event):
            event.accept()
        else:
            super().wheelEvent(event)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._position_overlay_label()

    def _position_overlay_label(self) -> None:
        if not self._overlay_label.isVisible():
            return
        geo = self._graphics.geometry()
        self._overlay_label.adjustSize()
        label_w = self._overlay_label.width()
        label_h = self._overlay_label.height()
        calibration_banner = self._frame_overlay_lines == [CALIBRATION_PROMPT_OVERLAY]
        if calibration_banner:
            x = geo.x() + max((geo.width() - label_w) // 2, 8)
            y = geo.y() + max(geo.height() // 6 - label_h // 2, 8)
        else:
            x = geo.x() + 8
            y = geo.y() + 8
        self._overlay_label.move(x, y)

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
            self._clear_persistent_linear_calipers()
            self._clear_contours()
            self._stored_linear_measurements = {}
        elif frame_changed:
            self._clear_active_contour_drawing()
        self._stored_linear_measurements = {
            self._linear_measurement_key(measurement): measurement
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
            self._render_persistent_linear_calipers()
            self._update_linear_caliper_label_preview_from_state()
            if frame_changed or contours_updated:
                self._refresh_frame_overlays()
        finally:
            self._syncing_state = False
            pending = self._pending_viewer_state
            self._pending_viewer_state = None
            if pending is not None:
                self.set_state(pending)

    def toggle_linear_caliper(self) -> None:
        if self._linear_caliper_active:
            self._clear_linear_caliper()
            return
        self._clear_calibration_caliper()
        self.start_linear_caliper_for(self._current_caliper_label())

    @property
    def is_linear_caliper_active(self) -> bool:
        return self._linear_caliper_active

    def toggle_calibration_caliper(self) -> None:
        if self._calibration_active:
            self._clear_calibration_caliper()
            return
        self.start_calibration_caliper()

    def start_calibration_caliper(self) -> bool:
        self._clear_linear_caliper()
        self._clear_calibration_caliper()
        if self._current_frame is None:
            return False

        height, width = self._current_frame.shape[:2]
        self._calibration_active = True
        self._calibration_x = min(float(width) * 0.96, float(width - 5))
        self._calibration_start_y = None
        self._measurement_label.setText("Калибровка: 1-й клик — верхняя метка")
        return True

    def finish_calibration(self) -> bool:
        return False

    @property
    def is_calibration_active(self) -> bool:
        return self._calibration_active

    def start_linear_caliper_for(self, label: str) -> bool:
        self._caliper_sequence = []
        return self._begin_linear_caliper(label)

    def activate_linear_caliper(self) -> bool:
        """Start (or restart) click-click caliper for the current label."""
        self._clear_calibration_caliper()
        return self._begin_linear_caliper(self._current_caliper_label())

    def start_linear_caliper_sequence(self, labels: tuple[str, ...]) -> bool:
        if not labels:
            return False
        self._caliper_sequence = list(labels[1:])
        return self._begin_linear_caliper(labels[0])

    def _begin_linear_caliper(self, label: str) -> bool:
        self._clear_linear_caliper_graphics()
        self._clear_calibration_caliper()
        if self._current_frame is None:
            return False
        self._set_caliper_label(label)
        self._linear_caliper_active = True
        self._linear_caliper_start = None
        self._measurement_label.setText(f"{label}: 1-й клик — начало")
        return True

    def cycle_caliper_label(self) -> None:
        self._caliper_label_index = (self._caliper_label_index + 1) % len(
            self._caliper_labels
        )
        label = self._current_caliper_label()
        if not self._linear_caliper_active:
            self._measurement_label.setText(f"{label}: —")
            return
        self._linear_caliper_start = None
        self._clear_linear_caliper_graphics()
        self._measurement_label.setText(f"{label}: 1-й клик — начало")

    def start_contour(
        self,
        *,
        phase: str | None = None,
        view: str = "A4C",
        chamber: str = "LV",
    ) -> bool:
        return self._start_contour_drawing(
            mode_kind="manual",
            pen=self._contour_pen_manual,
            phase=phase,
            view=view,
            chamber=chamber,
        )

    def start_model_contour(
        self,
        *,
        phase: str | None = None,
        view: str = "A4C",
        chamber: str = "LV",
    ) -> bool:
        return self._start_contour_drawing(
            mode_kind="model",
            pen=self._contour_pen_model,
            phase=phase,
            view=view,
            chamber=chamber,
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
        active_pen = self._contour_pen_manual
        self._active_contour_item = pg.PlotDataItem(
            pen=active_pen,
            symbol="o",
            symbolSize=6,
            symbolBrush=active_pen.color(),
        )
        self._active_contour_item.setZValue(20)
        self._view.addItem(self._active_contour_item)
        self._clear_contour_hover()
        self._set_contour_nodes_pickable(False)
        return True

    def set_contour_from_domain(self, contour: Contour) -> None:
        self._upsert_stored_contour(contour)
        self._render_contours_for_current_frame()
        self._refresh_frame_overlays()
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
                chamber=self._active_contour_chamber,
            )
            contour.frame_index = self._contour_frame_index()
        except ValueError:
            return False
        self._clear_active_contour_drawing()
        self.set_contour_from_domain(contour)
        self.contour_completed.emit(contour)
        return True

    def refine_active_open_contour(self) -> bool:
        """Smooth manual/model LV open-arc nodes on the current frame (R key)."""
        if self._current_frame is None:
            return False
        frame_index = self._contour_frame_index()
        for contour_index, contour in enumerate(self._contours):
            if (
                contour.source not in {"manual", "model"}
                or not contour.is_open_arc
                or contour.mitral_annulus is None
                or contour.frame_index != frame_index
            ):
                continue
            refined = refine_open_arc_contour(self._current_frame, contour)
            self._contours[contour_index] = refined
            self._upsert_stored_contour(refined)
            self._render_contours_for_current_frame()
            self._refresh_frame_overlays()
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
        if self._active_contour_chamber.upper() == "LV":
            try:
                contour = fit_contour_from_landmarks(
                    septal=septal,
                    lateral=lateral,
                    apex=apex,
                    phase=self._active_contour_phase or "ED",
                    view=self._active_contour_view,
                    chamber="LV",
                )
            except ValueError:
                return False
            contour.source = "manual"
            contour.frame_index = self._contour_frame_index()
            contour.apex_landmark = apex
        else:
            raw_arc = [septal, apex, lateral]
            resampled = resample_open_arc(raw_arc, num_nodes=DEFAULT_NODE_COUNT)
            contour = Contour(
                phase=self._active_contour_phase or "ED",
                view=self._active_contour_view,
                chamber=self._active_contour_chamber,
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
            chamber=self._active_contour_chamber,
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
        if self._calibration_active:
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
            calibration_banner = self._frame_overlay_lines == [CALIBRATION_PROMPT_OVERLAY]
            if calibration_banner:
                self._overlay_label.setStyleSheet(_CALIBRATION_OVERLAY_STYLE)
                self._overlay_label.setMinimumWidth(360)
            else:
                self._overlay_label.setStyleSheet(_DEFAULT_OVERLAY_STYLE)
                self._overlay_label.setMinimumWidth(0)
            self._overlay_label.setText("\n".join(self._frame_overlay_lines))
            self._overlay_label.adjustSize()
            self._overlay_label.show()
            self._overlay_label.raise_()
            self._position_overlay_label()
        else:
            self._overlay_label.hide()

    def _clear_linear_caliper(self) -> None:
        self._linear_caliper_active = False
        self._linear_caliper_start = None
        self._clear_linear_caliper_graphics()
        self._caliper_sequence = []
        self._measurement_label.setText(f"{self._current_caliper_label()}: —")
        if not self._syncing_state:
            self._emit_stored_linear_measurements()

    def _clear_linear_caliper_graphics(self) -> None:
        if self._linear_caliper_line_item is not None:
            self._view.removeItem(self._linear_caliper_line_item)
            self._linear_caliper_line_item = None
        if self._linear_caliper_marker_item is not None:
            self._view.removeItem(self._linear_caliper_marker_item)
            self._linear_caliper_marker_item = None

    def _clear_calibration_caliper(self) -> None:
        self._calibration_active = False
        self._calibration_start_y = None
        self._clear_calibration_graphics()
        if not self._linear_caliper_active:
            self._measurement_label.setText(f"{self._current_caliper_label()}: —")

    def _clear_calibration_graphics(self) -> None:
        if self._calibration_line_item is not None:
            self._view.removeItem(self._calibration_line_item)
            self._calibration_line_item = None
        if self._calibration_marker_item is not None:
            self._view.removeItem(self._calibration_marker_item)
            self._calibration_marker_item = None

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
        self._set_contour_nodes_pickable(True)

    def _set_contour_nodes_pickable(self, enabled: bool) -> None:
        buttons = Qt.MouseButton.LeftButton if enabled else Qt.MouseButton.NoButton
        for node_items in self._contour_nodes:
            for node in node_items:
                node.setAcceptedMouseButtons(buttons)

    def _remove_rendered_contour(self, contour_index: int) -> None:
        if self._drag_session is not None and self._drag_session[0] == contour_index:
            self._clear_drag_session()
        elif self._drag_session is not None and self._drag_session[0] > contour_index:
            idx, lx, ly, grab, tier = self._drag_session
            self._drag_session = (idx - 1, lx, ly, grab, tier)
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
        if not points:
            return [], []
        if contour.is_open_arc and len(points) >= 2:
            # Polyline only: B-spline overshoots past MA/apex landmarks on open arcs.
            return [point[0] for point in points], [point[1] for point in points]
        if closed and points:
            points = sample_spline(points + [points[0]], num_samples=max(len(points) * 8, 128))
        elif len(points) >= 3:
            points = sample_spline(points, num_samples=max(len(points) * 8, 128))
        return [point[0] for point in points], [point[1] for point in points]

    def _rbf_highlight_color(self, contour: Contour) -> str:
        if contour.source == "model":
            return "#ff6f00"
        return "#4caf50"

    def _view_metrics_for_rbf(self) -> tuple[float, float]:
        x_range, _y_range = self._view.viewRange()
        range_width = x_range[1] - x_range[0]
        viewport_w = float(self._view.width())
        if viewport_w < 10.0 and self._current_frame is not None:
            viewport_w = max(range_width, float(self._current_frame.shape[1]))
        return range_width, max(viewport_w, 1.0)

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
        *,
        color: str,
    ) -> None:
        if contour_index < 0 or contour_index >= len(self._contour_nodes):
            return
        for idx, node in enumerate(self._contour_nodes[contour_index]):
            active = idx < len(weights) and weights[idx] > 0.0
            node.set_rbf_highlight(active=active, color=color)

    def _clear_contour_node_highlights(self, contour_index: int) -> None:
        if contour_index < 0 or contour_index >= len(self._contour_nodes):
            return
        for node in self._contour_nodes[contour_index]:
            node.set_rbf_highlight(active=False)

    def _clear_contour_hover(self) -> None:
        if self._hover_contour_index is None:
            return
        if self._hover_contour_index < len(self._contour_nodes):
            self._clear_contour_node_highlights(self._hover_contour_index)
        self._hover_contour_index = None
        self._hover_tier = None
        self._hover_grab_index = None

    def _start_drag_session(
        self,
        contour_index: int,
        x: float,
        y: float,
        grab_index: int,
        locked_tier: int,
    ) -> None:
        self._last_drag_apply_pos = None
        self._drag_session = (
            contour_index,
            float(x),
            float(y),
            grab_index,
            locked_tier,
        )

    def _resolve_locked_tier(
        self,
        contour_index: int,
        grab_index: int,
        cursor: tuple[float, float],
    ) -> int:
        if (
            self._hover_contour_index == contour_index
            and self._hover_tier is not None
            and self._hover_grab_index == grab_index
        ):
            return self._hover_tier

        contour = self._contours[contour_index]
        pinned = self._pinned_indices_for_contour(contour)
        range_width, viewport_w = self._view_metrics_for_rbf()
        _weights, _arc_distance, tier = rbf_influence_weights(
            contour.points,
            cursor,
            grab_index,
            range_width,
            viewport_w,
            pinned_indices=pinned,
        )
        return tier or 1

    def _locked_drag_weights(
        self,
        contour: Contour,
        grab_index: int,
        locked_tier: int,
    ) -> np.ndarray:
        pinned = self._pinned_indices_for_contour(contour)
        return tiered_influence_weights(
            contour.points,
            grab_index,
            tier=locked_tier,
            pinned_indices=pinned,
        )

    def _clear_drag_session(self) -> None:
        self._drag_session = None
        self._zone_drag_active = False
        self._last_drag_apply_pos = None

    def _contour_editing_blocked(self) -> bool:
        return (
            self._contour_mode_active
            or self._linear_caliper_active
            or self._calibration_active
        )

    def _map_view_event(self, ev) -> tuple[float, float] | None:
        if hasattr(ev, "globalPosition"):
            return self._cursor_from_global(ev.globalPosition())
        point = ev.scenePos()
        if point is None:
            return None
        mapped = self._view.mapSceneToView(point)
        if mapped is None:
            return None
        return float(mapped.x()), float(mapped.y())

    def _cursor_from_global(self, global_pos) -> tuple[float, float] | None:
        local = self._graphics.mapFromGlobal(global_pos.toPoint())
        scene_pos = self._graphics.mapToScene(local)
        mapped = self._view.mapSceneToView(scene_pos)
        if mapped is None:
            return None
        return float(mapped.x()), float(mapped.y())

    def _handle_contour_hover_at_global(self, global_pos) -> bool:
        if self._drag_session is not None or self._contour_editing_blocked():
            return False
        cursor = self._cursor_from_global(global_pos)
        if cursor is None:
            return False
        return self._update_contour_hover(cursor)

    def _handle_contour_hover(self, ev) -> bool:
        if self._drag_session is not None or self._contour_editing_blocked():
            return False
        cursor = self._map_view_event(ev)
        if cursor is None:
            return False
        return self._update_contour_hover(cursor)

    def _update_contour_hover(self, cursor: tuple[float, float]) -> bool:
        target = self._compute_hover_target(cursor)
        if target is None:
            self._clear_contour_hover()
            return False

        contour_index, _grab_index, weights, tier = target
        if self._hover_contour_index not in (None, contour_index):
            self._clear_contour_node_highlights(self._hover_contour_index)
        self._hover_contour_index = contour_index
        self._hover_grab_index = _grab_index
        self._hover_tier = tier
        color = self._rbf_highlight_color(self._contours[contour_index])
        self._update_contour_node_highlights(contour_index, weights, color=color)
        return True

    def _compute_hover_target(
        self,
        cursor: tuple[float, float],
    ) -> tuple[int, int, np.ndarray, float] | None:
        if self._contour_editing_blocked() or not self._contours:
            return None

        range_width, viewport_w = self._view_metrics_for_rbf()
        best: tuple[float, int, int, np.ndarray, float] | None = None
        for contour_index, contour in enumerate(self._contours):
            if len(contour.points) < 2:
                continue
            pinned = self._pinned_indices_for_contour(contour)
            grab_index = nearest_control_point_index(
                contour.points,
                cursor,
                pinned_indices=pinned,
            )
            weights, _arc_distance, tier = rbf_influence_weights(
                contour.points,
                cursor,
                grab_index,
                range_width,
                viewport_w,
                pinned_indices=pinned,
            )
            if tier is None:
                continue
            if best is None or _arc_distance < best[0]:
                best = (_arc_distance, contour_index, grab_index, weights, tier)
        if best is None:
            return None
        _, contour_index, grab_index, weights, _tier = best
        return contour_index, grab_index, weights, _tier

    def _handle_contour_zone_press(self, ev) -> bool:
        if ev.button() != Qt.MouseButton.LeftButton:
            return False
        if self._contour_editing_blocked() or self._drag_session is not None:
            return False
        cursor = self._map_view_event(ev)
        if cursor is None:
            return False

        target = self._compute_hover_target(cursor)
        if target is None:
            return False

        contour_index, grab_index, _weights, tier = target
        self._zone_drag_active = True
        self._start_drag_session(contour_index, cursor[0], cursor[1], grab_index, tier)
        self._begin_drag_overlay(contour_index)
        self._hover_contour_index = contour_index
        self._hover_grab_index = grab_index
        self._hover_tier = tier
        return True

    def _handle_contour_zone_drag(self, ev) -> bool:
        if not self._zone_drag_active or self._drag_session is None:
            return False
        if ev.button() != Qt.MouseButton.LeftButton:
            return False
        return True

    def _handle_contour_drag_release(self, ev) -> bool:
        if self._drag_session is None:
            return False
        if ev.button() != Qt.MouseButton.LeftButton:
            return False
        cursor = self._map_view_event(ev)
        if cursor is None:
            self._cancel_contour_drag()
            return True
        contour_index, _, _, grab_index, _ = self._drag_session
        self._finalize_contour_point_drag(
            contour_index,
            grab_index,
            cursor[0],
            cursor[1],
        )
        return True

    def _handle_contour_drag_release_from_global(self, global_pos) -> None:
        if self._drag_session is None:
            return
        cursor = self._cursor_from_global(global_pos)
        if cursor is None:
            self._cancel_contour_drag()
            return
        contour_index, _, _, grab_index, _ = self._drag_session
        self._finalize_contour_point_drag(
            contour_index,
            grab_index,
            cursor[0],
            cursor[1],
        )

    def _handle_contour_zone_release(self, ev) -> bool:
        if not self._zone_drag_active or self._drag_session is None:
            return False
        return self._handle_contour_drag_release(ev)

    def _apply_rbf_drag_step(
        self,
        contour_index: int,
        x: float,
        y: float,
        *,
        grab_index: int,
        force: bool = False,
    ) -> bool:
        """Return True if displacement was applied."""
        if contour_index < 0 or contour_index >= len(self._contours):
            return False
        contour = self._contours[contour_index]

        if self._drag_session is None or self._drag_session[0] != contour_index:
            locked_tier = self._resolve_locked_tier(contour_index, grab_index, (x, y))
            self._start_drag_session(contour_index, x, y, grab_index, locked_tier)
            return False

        last_x, last_y = self._drag_session[1], self._drag_session[2]
        session_grab = self._drag_session[3]
        locked_tier = self._drag_session[4]
        rounded_cursor = (round(x, 4), round(y, 4))
        if not force and self._last_drag_apply_pos == rounded_cursor:
            return False
        delta = (x - last_x, y - last_y)
        if not force and math.hypot(delta[0], delta[1]) < MIN_DELTA_NORM:
            return False

        weights = self._locked_drag_weights(contour, session_grab, locked_tier)
        updated = apply_gaussian_displacement(contour.points, delta, weights)
        contour.points[:] = updated
        self._snap_open_arc_endpoints(contour)

        color = self._rbf_highlight_color(contour)
        for idx, point in enumerate(contour.points):
            self._contour_nodes[contour_index][idx].setData([point[0]], [point[1]])
        self._update_contour_node_highlights(contour_index, weights, color=color)
        self._refresh_rendered_contour_geometry(contour_index, during_drag=True)
        self._last_drag_apply_pos = rounded_cursor
        self._drag_session = (contour_index, x, y, session_grab, locked_tier)
        self._flush_drag_paint()
        return True

    def _begin_contour_node_drag(
        self,
        contour_index: int,
        point_index: int,
        x: float,
        y: float,
    ) -> None:
        if self._contour_editing_blocked():
            return
        if contour_index < 0 or contour_index >= len(self._contours):
            return
        contour = self._contours[contour_index]
        if point_index < 0 or point_index >= len(contour.points):
            return
        locked_tier = self._resolve_locked_tier(contour_index, point_index, (x, y))
        self._clear_contour_hover()
        sx, sy = contour.points[point_index]
        self._start_drag_session(contour_index, sx, sy, point_index, locked_tier)
        self._begin_drag_overlay(contour_index)

    def _begin_drag_overlay(self, contour_index: int) -> None:
        """Mark contour as actively dragged; geometry updates hit visible items."""
        if contour_index < 0 or contour_index >= len(self._contours):
            return
        self._drag_overlay_contour_index = contour_index
        contour = self._contours[contour_index]
        if self._drag_session is None:
            return
        weights = self._locked_drag_weights(
            contour,
            self._drag_session[3],
            self._drag_session[4],
        )
        self._update_contour_node_highlights(
            contour_index,
            weights,
            color=self._rbf_highlight_color(contour),
        )

    def _update_drag_overlay(
        self,
        contour_index: int,
        contour: Contour,
        weights: np.ndarray,
        *,
        color: str,
    ) -> None:
        del contour_index, contour, weights, color  # drag updates use visible items

    def _end_drag_overlay(self, contour_index: int) -> None:
        self._drag_overlay_contour_index = None
        del contour_index

    def _cancel_contour_drag(self) -> None:
        if self._drag_session is not None:
            self._end_drag_overlay(self._drag_session[0])
        self._clear_drag_session()
        self._clear_contour_hover()

    def _flush_drag_paint(self) -> None:
        scene = self._view.scene()
        if scene is not None:
            scene.update()
        if self._drag_overlay_contour_index is not None:
            contour_index = self._drag_overlay_contour_index
            if 0 <= contour_index < len(self._contour_items):
                self._contour_items[contour_index].update()
            if 0 <= contour_index < len(self._contour_nodes):
                for node in self._contour_nodes[contour_index]:
                    node.update()
        self._view.update()
        self._graphics.update()
        viewport = self._graphics.viewport()
        if viewport is not None:
            viewport.update()

    def _repaint_contour_view(self, contour_index: int | None = None) -> None:
        self._flush_drag_paint()

    def _drag_contour_point(
        self,
        contour_index: int,
        point_index: int,
        x: float,
        y: float,
    ) -> None:
        """Programmatic drag step (used by unit tests)."""
        if self._drag_session is None or self._drag_session[0] != contour_index:
            self._begin_contour_node_drag(contour_index, point_index, x, y)
        self._apply_rbf_drag_step(
            contour_index,
            x,
            y,
            grab_index=point_index,
        )

    def _finalize_contour_point_drag(
        self,
        contour_index: int,
        point_index: int,
        x: float,
        y: float,
    ) -> None:
        if self._drag_session is None:
            return
        if contour_index < 0 or contour_index >= len(self._contours):
            self._cancel_contour_drag()
            return
        contour = self._contours[contour_index]
        grab_index = point_index
        if self._drag_session is not None and self._drag_session[0] == contour_index:
            grab_index = self._drag_session[3]
        elif 0 <= point_index < len(contour.points):
            sx, sy = contour.points[point_index]
            locked_tier = self._resolve_locked_tier(
                contour_index,
                point_index,
                (x, y),
            )
            self._start_drag_session(contour_index, sx, sy, point_index, locked_tier)
        self._apply_rbf_drag_step(
            contour_index,
            x,
            y,
            grab_index=grab_index,
            force=True,
        )
        contour = self._contours[contour_index]
        if contour.is_open_arc:
            num_nodes = contour.num_nodes or DEFAULT_NODE_COUNT
            if contour.mitral_annulus is not None:
                septal, lateral = contour.mitral_annulus
                apex = contour.apex_landmark or apex_point(
                    contour.points, contour.mitral_annulus
                )
                resampled = resample_open_arc_landmarks(
                    contour.points,
                    septal=septal,
                    lateral=lateral,
                    apex=apex,
                    num_nodes=num_nodes,
                )
                contour.points[:] = resampled
                contour.mitral_annulus = (septal, lateral)
                contour.apex_landmark = apex
            else:
                resampled = resample_open_arc(contour.points, num_nodes=num_nodes)
                contour.points[:] = resampled
            for idx, point in enumerate(contour.points):
                self._contour_nodes[contour_index][idx].setData([point[0]], [point[1]])
        self._end_drag_overlay(contour_index)
        self._refresh_rendered_contour_geometry(contour_index)
        self._clear_contour_node_highlights(contour_index)
        self._clear_drag_session()
        self._clear_contour_hover()
        self._upsert_stored_contour(contour)
        self.contours_changed.emit(self.contours())
        current_frame = self._contour_frame_index()
        if contour.is_open_arc and contour.frame_index == current_frame:
            self._refresh_frame_overlays()

    def _refresh_rendered_contour_geometry(
        self,
        contour_index: int,
        *,
        during_drag: bool = False,
    ) -> None:
        if contour_index < 0 or contour_index >= len(self._contours):
            return
        if contour_index >= len(self._contour_items):
            return
        contour = self._contours[contour_index]
        closed = not contour.is_open_arc
        if during_drag:
            x_values = [point[0] for point in contour.points]
            y_values = [point[1] for point in contour.points]
        else:
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

    def _needs_calibration_prompt(self) -> bool:
        if self._current_state is None or self._current_state.instance is None:
            return False
        if self._current_state.instance.media_format == "dicom":
            return False
        _, spacing_calibrated = self._effective_pixel_spacing()
        return not spacing_calibrated

    def _refresh_frame_overlays(self, *, extra_lines: tuple[str, ...] = ()) -> None:
        self.clear_frame_overlay()
        if self._needs_calibration_prompt():
            self.append_frame_overlay(CALIBRATION_PROMPT_OVERLAY)
        frame_index = self._contour_frame_index()
        spacing, spacing_calibrated = self._effective_pixel_spacing()
        if frame_index is not None:
            for contour in self._stored_contours:
                if (
                    contour.is_open_arc
                    and contour.frame_index == frame_index
                ):
                    self.append_frame_overlay(
                        format_contour_overlay(
                            contour,
                            spacing,
                            spacing_calibrated=spacing_calibrated,
                        )
                    )
            for measurement in self._linear_measurements_for_frame(frame_index):
                self.append_frame_overlay(measurement.display_text())
        for line in extra_lines:
            self.append_frame_overlay(line)

    def _refresh_lv_frame_overlay(self, *, extra_lines: tuple[str, ...] = ()) -> None:
        self._refresh_frame_overlays(extra_lines=extra_lines)

    def _linear_measurement_key(self, measurement: LinearMeasurement) -> tuple[str, int]:
        frame_key = (
            measurement.frame_index if measurement.frame_index is not None else -1
        )
        return measurement.label, frame_key

    def _linear_measurements_for_frame(self, frame_index: int) -> list[LinearMeasurement]:
        measurements: list[LinearMeasurement] = []
        for measurement in self._stored_linear_measurements.values():
            if measurement.frame_index is None or measurement.frame_index == frame_index:
                measurements.append(measurement)
        return measurements

    def _clear_persistent_linear_calipers(self) -> None:
        for line_item, marker_item in self._persistent_linear_graphics:
            self._view.removeItem(line_item)
            self._view.removeItem(marker_item)
        self._persistent_linear_graphics.clear()

    def _render_persistent_linear_calipers(self) -> None:
        self._clear_persistent_linear_calipers()
        frame_index = self._contour_frame_index()
        if frame_index is None:
            return
        for measurement in self._linear_measurements_for_frame(frame_index):
            if measurement.start is None or measurement.end is None:
                continue
            line_item, marker_item = self._create_linear_graphics_items(
                measurement.start,
                measurement.end,
            )
            self._persistent_linear_graphics.append((line_item, marker_item))

    def _create_linear_graphics_items(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> tuple[pg.PlotDataItem, pg.ScatterPlotItem]:
        pen = pg.mkPen("#29b6f6", width=2)
        line_item = pg.PlotDataItem(pen=pen)
        line_item.setZValue(24)
        line_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        line_item.setAcceptHoverEvents(False)
        line_item.setData([start[0], end[0]], [start[1], end[1]])
        self._view.addItem(line_item)
        marker_item = pg.ScatterPlotItem(
            symbol="+",
            size=12,
            pen=pen,
            brush=pg.mkBrush("#29b6f6"),
        )
        marker_item.setZValue(25)
        marker_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        marker_item.setAcceptHoverEvents(False)
        marker_item.setData([start[0], end[0]], [start[1], end[1]])
        self._view.addItem(marker_item)
        return line_item, marker_item

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

    def _handle_calibration_mouse_press(self, ev) -> bool:
        if not self._calibration_active or self._current_frame is None:
            return False
        if ev.button() != Qt.MouseButton.LeftButton:
            return False

        click = self._map_view_event(ev)
        if click is None:
            return False

        height = self._current_frame.shape[0]
        y = max(0.0, min(float(click[1]), float(height - 1)))
        if self._calibration_start_y is None:
            self._calibration_start_y = y
            self._update_calibration_preview(y, y)
            self._measurement_label.setText("Калибровка: 2-й клик — нижняя метка")
            return True

        length_px = abs(y - self._calibration_start_y)
        if length_px >= 1.0:
            self._prompt_calibration_distance(length_px)
        return True

    def _ensure_calibration_graphics(self) -> None:
        if self._calibration_line_item is None:
            pen = pg.mkPen("#29b6f6", width=2)
            self._calibration_line_item = pg.PlotDataItem(pen=pen)
            self._calibration_line_item.setZValue(25)
            self._calibration_line_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self._calibration_line_item.setAcceptHoverEvents(False)
            self._view.addItem(self._calibration_line_item)
        if self._calibration_marker_item is None:
            marker_pen = pg.mkPen("#29b6f6", width=2)
            self._calibration_marker_item = pg.ScatterPlotItem(
                symbol="+",
                size=14,
                pen=marker_pen,
                brush=pg.mkBrush(0, 0, 0, 0),
            )
            self._calibration_marker_item.setZValue(26)
            self._calibration_marker_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self._calibration_marker_item.setAcceptHoverEvents(False)
            self._view.addItem(self._calibration_marker_item)

    def _update_calibration_preview(self, start_y: float, end_y: float) -> None:
        self._ensure_calibration_graphics()
        assert self._calibration_line_item is not None
        assert self._calibration_marker_item is not None
        x = self._calibration_x
        self._calibration_line_item.setData([x, x], [start_y, end_y])
        self._calibration_marker_item.setData([x, x], [start_y, end_y])

    def _prompt_calibration_distance(self, length_px: float) -> None:
        known_mm, accepted = QInputDialog.getDouble(
            self,
            "Калибровка по шкале глубины",
            "Известное расстояние (мм), например 50 для отметок 0–5 см:",
            50.0,
            0.1,
            10000.0,
            1,
        )
        self._clear_calibration_caliper()
        if not accepted:
            if self._needs_calibration_prompt():
                self.start_calibration_caliper()
            return
        spacing = spacing_from_known_distance(length_px, known_mm)
        if not self._syncing_state:
            self.calibration_completed.emit(spacing)
            self._refresh_frame_overlays()

    def _handle_linear_caliper_mouse_press(self, ev) -> bool:
        if not self._linear_caliper_active:
            return False
        if ev.button() != Qt.MouseButton.LeftButton:
            return False
        if self._calibration_active:
            return False

        click: tuple[float, float] | None = None
        if hasattr(ev, "scenePos"):
            point = self._view.mapSceneToView(ev.scenePos())
            if point is not None:
                click = (float(point.x()), float(point.y()))
        if click is None:
            click = self._map_view_event(ev)
        if click is None:
            return False

        if self._linear_caliper_start is None:
            self._linear_caliper_start = click
            self._update_linear_caliper_preview(click, click)
            self._measurement_label.setText(
                f"{self._current_caliper_label()}: 2-й клик — конец"
            )
            return True

        start = self._linear_caliper_start
        self._commit_linear_measurement_from_endpoints(start, click)
        return True

    def _ensure_linear_caliper_graphics(self) -> None:
        if self._linear_caliper_line_item is None:
            pen = pg.mkPen("#ffb300", width=2)
            self._linear_caliper_line_item = pg.PlotDataItem(pen=pen)
            self._linear_caliper_line_item.setZValue(25)
            self._linear_caliper_line_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self._linear_caliper_line_item.setAcceptHoverEvents(False)
            self._view.addItem(self._linear_caliper_line_item)
        if self._linear_caliper_marker_item is None:
            marker_pen = pg.mkPen("#ffb300", width=2)
            self._linear_caliper_marker_item = pg.ScatterPlotItem(
                symbol="+",
                size=14,
                pen=marker_pen,
                brush=pg.mkBrush(0, 0, 0, 0),
            )
            self._linear_caliper_marker_item.setZValue(26)
            self._linear_caliper_marker_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self._linear_caliper_marker_item.setAcceptHoverEvents(False)
            self._view.addItem(self._linear_caliper_marker_item)

    def _update_linear_caliper_preview(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> None:
        self._ensure_linear_caliper_graphics()
        assert self._linear_caliper_line_item is not None
        assert self._linear_caliper_marker_item is not None
        self._linear_caliper_line_item.setData(
            [start[0], end[0]],
            [start[1], end[1]],
        )
        self._linear_caliper_marker_item.setData(
            [start[0], end[0]],
            [start[1], end[1]],
        )

    def _linear_measurement_from_endpoints(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        label: str,
    ) -> LinearMeasurement:
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        pixel_length = math.hypot(dx, dy)
        angle_degrees = math.degrees(math.atan2(dy, dx))
        pixel_spacing = (
            self._current_state.effective_pixel_spacing if self._current_state else None
        )
        millimeter_length = (
            pixel_to_mm_length(pixel_length, angle_degrees, pixel_spacing)
            if pixel_spacing is not None
            else None
        )
        return LinearMeasurement(
            label=label,
            pixel_length=pixel_length,
            millimeter_length=millimeter_length,
            frame_index=self._contour_frame_index(),
            start=start,
            end=end,
        )

    def _update_linear_caliper_label_preview(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> None:
        measurement = self._linear_measurement_from_endpoints(
            start,
            end,
            self._current_caliper_label(),
        )
        self._measurement_label.setText(measurement.display_text())

    def _update_linear_caliper_label_preview_from_state(self) -> None:
        if not self._linear_caliper_active:
            return
        if self._linear_caliper_start is None:
            label = self._current_caliper_label()
            self._measurement_label.setText(f"{label}: 1-й клик — начало")
            return
        self._update_linear_caliper_label_preview(
            self._linear_caliper_start,
            self._linear_caliper_start,
        )

    def _commit_linear_measurement_from_endpoints(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> None:
        measurement = self._linear_measurement_from_endpoints(
            start,
            end,
            self._current_caliper_label(),
        )
        self._stored_linear_measurements[self._linear_measurement_key(measurement)] = (
            measurement
        )
        self._measurement_label.setText(measurement.display_text())
        self._emit_stored_linear_measurements()
        self._render_persistent_linear_calipers()
        self._refresh_frame_overlays()
        self._linear_caliper_start = None
        self._clear_linear_caliper_graphics()
        if self._caliper_sequence:
            next_label = self._caliper_sequence.pop(0)
            self._begin_linear_caliper(next_label)
            self._measurement_label.setText(f"{next_label}: 1-й клик — начало")
        else:
            self._linear_caliper_active = False

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
