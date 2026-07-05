"""2D image viewer using PyQtGraph."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QEvent, QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGraphicsView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.domain.calculations.lvef_simpson import format_contour_overlay
from echo_personal_tool.domain.calculations.planimeter import (
    GENERIC_AREA_CHAMBER,
    GENERIC_VOLUME_CHAMBER,
    is_planimeter_polygon,
    next_area_label,
    next_volume_label,
)
from echo_personal_tool.domain.models import Contour
from echo_personal_tool.infrastructure.profiler import profiled as _prof
from echo_personal_tool.domain.models.doppler_axis import DopplerAxisMapping
from echo_personal_tool.domain.models.doppler_roi import (
    DopplerCalibrationState,
    DopplerKind,
    DopplerSpectrogramRoi,
)
from echo_personal_tool.domain.models.frame_panels import (
    FramePanelLayout,
    MmodeCalibrationState,
)
from echo_personal_tool.domain.models.linear_measurement import (
    LinearMeasurement,
    inline_caliper_text,
    pixel_to_mm_length,
)
from echo_personal_tool.presentation.caliper_label_item import (
    compute_caliper_label_layout,
)
from echo_personal_tool.presentation.calibration_snap import snap_y_to_nearest_tick
from echo_personal_tool.domain.services.depth_scale_detector import (
    detect_depth_scale_ticks,
    find_scale_ticks,
)
from echo_personal_tool.domain.models.viewer_state import ViewerState
from echo_personal_tool.domain.services.contour_edge_snap import (
    EdgeMap,
    apply_soft_magnetic_snap,
    build_edge_map,
    magnetic_edge_snap_config_for_source,
)
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
from echo_personal_tool.domain.services.doppler_baseline import detect_baseline_y
from echo_personal_tool.domain.services.doppler_calibration import (
    build_axis_mapping,
    calibration_from_roi_and_baseline,
    roi_from_corners,
)
from echo_personal_tool.domain.services.frame_panel_parser import detect_panels_heuristic
from echo_personal_tool.domain.services.mbs_lite_service import (
    fit_contour_from_landmarks,
    refine_open_arc_contour,
)
from echo_personal_tool.domain.services.mmode_calibration import mmode_state_from_panel
from echo_personal_tool.domain.services.pixel_spacing_resolver import (
    spacing_from_known_distance,
)
from echo_personal_tool.domain.services.planimeter_formatter import format_planimeter_overlay_line
from echo_personal_tool.infrastructure.dicom_doppler_calibration import try_parse_from_path
from echo_personal_tool.infrastructure.dicom_frame_panels import (
    try_parse_from_path as try_parse_panels_from_path,
)
from echo_personal_tool.infrastructure.dicom_tag_inspector import read_interesting_dicom_tag_rows
from echo_personal_tool.infrastructure.pixel_utils import (
    apply_window_level_rgb,
    compute_display_levels,
    dr_percentiles_from_slider,
    is_color_frame,
    is_effective_grayscale,
    to_display_rgb,
    to_grayscale_array,
)
from echo_personal_tool.infrastructure.user_preferences import (
    DEFAULT_RESULTS_OVERLAY_Y_RATIO,
    RESULTS_OVERLAY_EDGE_MARGIN,
    UserPreferences,
    resolve_wl_values,
)
from echo_personal_tool.presentation.doppler_overlay import DopplerOverlayTools
from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.resources.bundled_fonts import FONT_FAMILY_MONO

CALIBRATION_PROMPT_OVERLAY_KEY = "viewer.calibration.calibration_prompt"
CALIBRATION_SUCCESS_OVERLAY_KEY = "viewer.calibration.auto_ok"

_DOPPLER_CAL_ROI_STEP1_KEY = "viewer.doppler.cal_roi1"
_DOPPLER_CAL_ROI_STEP2_KEY = "viewer.doppler.cal_roi2"
_DOPPLER_CAL_BASELINE_KEY = "viewer.doppler.cal_baseline"
_DOPPLER_CAL_VELOCITY_KEY = "viewer.doppler.cal_velocity"
_CALIBRATION_OVERLAY_STYLE = (
    "background-color: rgba(0, 0, 0, 210);"
    " color: #ffffff;"
    " padding: 20px 36px;"
    " font-size: 22px; font-weight: bold;"
    " border: 2px solid #ffb300;"
    " border-radius: 8px;"
)
_CALIBRATION_SUCCESS_STYLE = (
    "background-color: rgba(0, 0, 0, 210);"
    " color: #00b4d8;"
    " padding: 20px 36px;"
    " font-size: 22px; font-weight: bold;"
    " border: 2px solid #00b4d8;"
    " border-radius: 8px;"
)
_RESULTS_OVERLAY_STYLE = (
    "background-color: rgba(8, 16, 28, 215);"
    " color: #e8eef4;"
    " padding: 11px 18px;"
    f" font-family: '{FONT_FAMILY_MONO}', monospace;"
    " border: 2px solid #3d7cb8;"
    " border-radius: 5px;"
)


def _results_overlay_style(font_size: int, opacity: float = 0.84) -> str:
    alpha = int(max(0.0, min(1.0, opacity)) * 255)
    return (
        _RESULTS_OVERLAY_STYLE
        + f" font-size: {font_size}px;"
        + f" background-color: rgba(0, 0, 0, 0);"
    )
_DEFAULT_OVERLAY_STYLE = (
    "background-color: rgba(0, 0, 0, 180);"
    " color: #f5f5f5;"
    " padding: 8px;"
    " font-size: 12px;"
    " border: 1px solid #4caf50;"
)
_MAGNETIC_SNAP_WEIGHT_THRESHOLD = 0.15
_MAGNETIC_RELEASE_STRENGTH = 0.9
_MAGNETIC_RELEASE_MAX_RADIAL_PX = 15.0


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
        if self._viewer_widget is not None and self._viewer_widget._handle_doppler_mouse_click(ev):
            return
        if self._viewer_widget is not None and self._viewer_widget._handle_contour_mouse_click(ev):
            return
        ev.accept()

    @_prof
    def mousePressEvent(self, ev) -> None:  # type: ignore[override]
        if ev.button() == Qt.MouseButton.RightButton:
            ev.accept()
            return
        if self._viewer_widget is not None and self._viewer_widget._handle_doppler_calibration_click(
            ev
        ):
            ev.accept()
            return
        if self._viewer_widget is not None and self._viewer_widget._handle_mmode_calibration_click(
            ev
        ):
            ev.accept()
            return
        if self._viewer_widget is not None and self._viewer_widget._handle_calibration_mouse_press(
            ev
        ):
            ev.accept()
            return
        if (
            self._viewer_widget is not None
            and self._viewer_widget._handle_linear_caliper_mouse_press(ev)
        ):
            ev.accept()
            return
        if self._viewer_widget is not None and self._viewer_widget._handle_doppler_trace_press(ev):
            ev.accept()
            return
        if self._viewer_widget is not None and self._viewer_widget._handle_contour_zone_press(ev):
            ev.accept()
            return
        super().mousePressEvent(ev)

    @_prof
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
        if viewer is not None and viewer._handle_doppler_trace_drag(ev):
            ev.accept()
            return
        if viewer is not None and viewer._drag_session is not None:
            ev.accept()
            return
        ev.ignore()

    def mouseReleaseEvent(self, ev) -> None:  # type: ignore[override]
        if self._viewer_widget is not None and self._viewer_widget._handle_caliper_drag_release(ev):
            ev.accept()
            return
        if self._viewer_widget is not None and self._viewer_widget._handle_doppler_trace_release(ev):
            ev.accept()
            return
        if self._viewer_widget is not None and self._viewer_widget._handle_contour_drag_release(ev):
            ev.accept()
            return
        if self._viewer_widget is not None and self._viewer_widget._handle_contour_zone_release(ev):
            ev.accept()
            return
        super().mouseReleaseEvent(ev)

    def leaveEvent(self, ev) -> None:  # type: ignore[override]
        if self._viewer_widget is not None:
            self._viewer_widget._clear_contour_hover()
            if self._viewer_widget._caliper_drag_active:
                self._viewer_widget._finish_caliper_node_drag(cancel=True)
        super().leaveEvent(ev)

    @_prof
    def wheelEvent(self, ev, axis=None) -> None:  # type: ignore[override]
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

    @_prof
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


class _CaliperNodeItem(pg.ScatterPlotItem):
    """Single draggable caliper endpoint node."""

    _SYMBOL_DEFAULT = "+"
    _SYMBOL_HOVER = "o"

    def __init__(
        self,
        viewer_widget: "ViewerWidget",
        caliper_key: tuple[str, int],
        endpoint_index: int,
        position: tuple[float, float],
        pen: pg.functions.mkPen,
    ) -> None:
        super().__init__(
            symbol=self._SYMBOL_DEFAULT,
            size=12,
            pen=pen,
            brush=pg.mkBrush(pen.color()),
        )
        self._viewer_widget = viewer_widget
        self._caliper_key = caliper_key
        self._endpoint_index = endpoint_index
        self._base_pen = pen
        self._base_size = 12
        self.setZValue(30)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setAcceptHoverEvents(True)
        self.setData([position[0]], [position[1]])

    def hoverEvent(self, ev) -> None:  # type: ignore[override]
        if ev.isEnter():
            self.setSymbol(self._SYMBOL_HOVER)
            self.setSize(14)
            self.setPen(pg.mkPen("#ffb300", width=2))
            self.setBrush(pg.mkBrush("#ffb300"))
        elif ev.isExit():
            if self._viewer_widget._selected_caliper_key != self._caliper_key:
                self.setSymbol(self._SYMBOL_DEFAULT)
                self.setSize(self._base_size)
                self.setPen(self._base_pen)
                self.setBrush(pg.mkBrush(self._base_pen.color()))

    @_prof
    def mousePressEvent(self, ev) -> None:  # type: ignore[override]
        if ev.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(ev)
            return
        if self._viewer_widget._linear_caliper_active:
            ev.ignore()
            return
        ev.accept()
        view_box = self.getViewBox() or self._viewer_widget._view
        point = view_box.mapSceneToView(ev.scenePos())
        self._viewer_widget._select_caliper(self._caliper_key)
        self._viewer_widget._begin_caliper_node_drag(
            self._caliper_key,
            self._endpoint_index,
            float(point.x()),
            float(point.y()),
        )

    def mouseDragEvent(self, ev) -> None:  # type: ignore[override]
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        ev.accept()
        view_box = self.getViewBox() or self._viewer_widget._view
        point = view_box.mapSceneToView(ev.scenePos())
        self._viewer_widget._apply_caliper_node_drag(
            float(point.x()), float(point.y())
        )

    def mouseReleaseEvent(self, ev) -> None:  # type: ignore[override]
        if ev.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(ev)
            return
        ev.accept()
        self._viewer_widget._finish_caliper_node_drag()

    def set_selected(self, selected: bool) -> None:
        if selected:
            self.setSymbol(self._SYMBOL_HOVER)
            self.setSize(14)
            self.setPen(pg.mkPen("#ffb300", width=2))
            self.setBrush(pg.mkBrush("#ffb300"))
        else:
            self.setSymbol(self._SYMBOL_DEFAULT)
            self.setSize(self._base_size)
            self.setPen(self._base_pen)
            self.setBrush(pg.mkBrush(self._base_pen.color()))


class ResultsOverlayLabel(QLabel):
    """Draggable measurement summary overlay on the viewer."""

    position_changed = Signal(float, float)
    clear_requested = Signal()
    reset_position_requested = Signal()
    pin_toggled = Signal(bool)

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._x_ratio = 1.0
        self._y_ratio = DEFAULT_RESULTS_OVERLAY_Y_RATIO
        self._dragging = False
        self._drag_offset_x = 0.0
        self._drag_offset_y = 0.0
        self._pinned = False
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip(tr("viewer.results_drag_tip"))

    def set_position_ratios(self, x_ratio: float, y_ratio: float) -> None:
        self._x_ratio = max(0.0, min(1.0, x_ratio))
        self._y_ratio = max(0.0, min(1.0, y_ratio))

    def position_ratios(self) -> tuple[float, float]:
        return self._x_ratio, self._y_ratio

    @_prof
    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            viewer = self.parent()
            if isinstance(viewer, ViewerWidget):
                viewer._mark_results_overlay_custom_position()
            self._drag_offset_x = event.position().x()
            self._drag_offset_y = event.position().y()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    @_prof
    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if not self._dragging:
            super().mouseMoveEvent(event)
            return
        viewer = self.parent()
        if not isinstance(viewer, ViewerWidget):
            return
        geo = viewer._graphics_content_geometry()
        local = viewer.mapFromGlobal(event.globalPosition().toPoint())
        x = int(local.x() - self._drag_offset_x)
        y = int(local.y() - self._drag_offset_y)
        rw = self.width()
        rh = self.height()
        x = max(geo.x(), min(x, geo.x() + max(geo.width() - rw, 0)))
        y = max(geo.y(), min(y, geo.y() + max(geo.height() - rh, 0)))
        self.move(x, y)
        self._x_ratio = (x - geo.x()) / max(geo.width(), 1)
        self._y_ratio = (y - geo.y()) / max(geo.height(), 1)
        self.position_changed.emit(self._x_ratio, self._y_ratio)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event) -> None:  # type: ignore[override]
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        clear_action = menu.addAction(tr("viewer.overlay_clear"))
        reset_action = menu.addAction(tr("viewer.overlay_reset_position"))
        pin_action = menu.addAction(tr("viewer.overlay_unpin") if self._pinned else tr("viewer.overlay_pin"))
        action = menu.exec(event.globalPos())
        if action == clear_action:
            self.clear_requested.emit()
        elif action == reset_action:
            self.reset_position_requested.emit()
        elif action == pin_action:
            self._pinned = not self._pinned
            self.pin_toggled.emit(self._pinned)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class ViewerWidget(QWidget):
    """Display a frame with playback controls and window/level sliders."""

    play_pause_requested = Signal()
    frame_selected = Signal(int)
    scroll_frame_selected = Signal(int)
    contour_completed = Signal(object)
    contour_landmark_rejected = Signal(str)
    contours_changed = Signal(object)
    linear_measurements_changed = Signal(object)
    linear_caliper_sequence_completed = Signal()
    calibration_completed = Signal(object)
    doppler_markers_changed = Signal(object)
    spectral_calibration_completed = Signal(object)
    doppler_calibration_changed = Signal(object)
    doppler_frame_changing = Signal(int, object)
    doppler_frame_changed = Signal(int)
    mmode_calibration_changed = Signal(object)
    mmode_time_calibration_completed = Signal(object)
    results_overlay_position_changed = Signal(float, float)

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
        self._image_item.setAutoDownsample(False)
        self._image_item.setOpts(smooth=True)
        self._image_smooth = True
        self._view.addItem(self._image_item)
        self._doppler = DopplerOverlayTools(self._view, self)
        self._doppler.markers_changed.connect(self.doppler_markers_changed.emit)
        self._doppler.workflow_step_changed.connect(self._on_doppler_workflow_step_changed)
        self._doppler.workflow_completed.connect(self._on_doppler_workflow_completed)
        self._doppler.trace_prompt_changed.connect(self._on_doppler_trace_prompt_changed)
        from echo_personal_tool.presentation.speckle_overlay import SpeckleOverlay
        self._speckle_overlay = SpeckleOverlay(self._view, self)
        self._speckle_overlay.hide()
        self._speckle_result = None
        self._calibration_kind: Literal[
            "depth", "spectral", "doppler_velocity", "mmode_time", "mmode_depth"
        ] | None = None
        self._doppler_axis_calibrated = False
        self._doppler_calibration_state: DopplerCalibrationState | None = None
        self._doppler_calibration_instance_uid: str | None = None
        self._doppler_calibration_frame_index: int | None = None
        self._frame_panel_layout: FramePanelLayout | None = None
        self._mmode_calibration_state: MmodeCalibrationState | None = None
        self._mmode_cal_step: Literal["roi"] | None = None
        self._mmode_roi_corner1: tuple[float, float] | None = None
        self._mmode_pending_roi: DopplerSpectrogramRoi | None = None
        self._crosshair_h_item: pg.PlotDataItem | None = None
        self._crosshair_v_item: pg.PlotDataItem | None = None
        self._doppler_cal_step: Literal["roi", "baseline", "velocity"] | None = None
        self._doppler_cal_kind = DopplerKind.SPECTRAL
        self._doppler_roi_corner1: tuple[float, float] | None = None
        self._doppler_pending_roi: DopplerSpectrogramRoi | None = None
        self._doppler_pending_baseline_y: float | None = None
        self._mmode_time_start_x: float | None = None
        self._vertical_caliper_labels = frozenset({"TAPSE"})
        self._current_frame: np.ndarray | None = None
        self._current_state: ViewerState | None = None
        self._current_instance_path: Path | None = None
        self._linear_caliper_active = False
        self._linear_caliper_start: tuple[float, float] | None = None
        self._linear_caliper_line_item: pg.PlotDataItem | None = None
        self._linear_caliper_marker_item: pg.ScatterPlotItem | None = None
        self._calibration_active = False
        self._calibration_x = 0.0
        self._calibration_start_y: float | None = None
        self._calibration_line_item: pg.PlotDataItem | None = None
        self._calibration_marker_item: pg.ScatterPlotItem | None = None
        self._calibration_h_guide_start_item: pg.PlotDataItem | None = None
        self._calibration_h_guide_end_item: pg.PlotDataItem | None = None
        self._depth_tick_y_positions: list[float] = []
        self._calibration_tick_snap_enabled: bool = True
        self._calibration_tick_snap_radius_px: float = 8.0
        self._auto_calibration_succeeded: bool = False
        self._calibration_ok_timer: QTimer | None = None
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
        self._dist_serial = 1
        self._contour_mode_active = False
        self._contour_mode_kind: Literal["manual", "model", "closed"] | None = None
        self._active_contour_chamber: str = "LV"
        self._contour_stage: Literal["ma_septal", "ma_lateral", "arc", "apex", "polygon"] | None = (
            None
        )
        self._active_mitral_septal: tuple[float, float] | None = None
        self._active_mitral_annulus: tuple[tuple[float, float], tuple[float, float]] | None = None
        self._active_apex_landmark: tuple[float, float] | None = None
        self._active_arc_points: list[tuple[float, float]] = []
        self._active_contour_item: pg.PlotDataItem | None = None
        self._active_ma_chord_item: pg.PlotDataItem | None = None
        self._active_contour_phase: str | None = None
        self._contour_pen_manual = pg.mkPen("#ff6f00", width=2)
        self._contour_pen_ai = pg.mkPen("#00bcd4", width=2)
        self._contour_pen_ai_pending = pg.mkPen(
            "#00bcd4", width=2, style=Qt.PenStyle.DashLine
        )
        self._contour_pen_model = pg.mkPen("#4caf50", width=2)
        self._contour_pen_ma = pg.mkPen("#ff6f00", width=1, style=Qt.PenStyle.DashLine)
        self._contour_ma_items: list[pg.PlotDataItem | None] = []
        self._active_contour_view = "A4C"
        self._frame_overlay_lines: list[str] = []
        self._pending_viewer_state: ViewerState | None = None
        self._stored_linear_measurements: dict[tuple[str, int], LinearMeasurement] = {}
        self._persistent_linear_graphics: list[tuple[pg.PlotDataItem, pg.ScatterPlotItem]] = []
        self._active_caliper_label_item: pg.TextItem | None = None
        self._persistent_caliper_label_items: list[pg.TextItem] = []
        self._caliper_sequence: list[str] = []
        self._caliper_sequence_size = 0
        self._caliper_drag_active: bool = False
        self._caliper_drag_key: tuple[str, int] | None = None
        self._caliper_drag_node: int | None = None
        self._caliper_drag_original: LinearMeasurement | None = None
        self._caliper_drag_persistent_items: list | None = None
        self._selected_caliper_key: tuple[str, int] | None = None
        self._syncing_state = False
        self._zoom_mode: str = "fit"
        self._zoom_factor: float = 1.0  # continuous zoom for Ctrl+Scroll
        self._is_color_frame = False
        self._color_source_rgb: np.ndarray | None = None
        self._window_level_enabled = True
        self._cached_levels_key: tuple[int, int, int] | None = None
        self._last_color_frame_ptr: int | None = None
        self._drag_session: tuple[int, float, float, int, int] | None = None
        self._hover_contour_index: int | None = None
        self._hover_tier: int | None = None
        self._hover_grab_index: int | None = None
        self._zone_drag_active = False
        self._drag_overlay_contour_index: int | None = None
        self._last_drag_apply_pos: tuple[float, float] | None = None
        self._caliper_line_width = 2.0
        self._magnetic_snap_weight_threshold = _MAGNETIC_SNAP_WEIGHT_THRESHOLD
        self._magnetic_snap_release_strength = _MAGNETIC_RELEASE_STRENGTH
        self._magnetic_snap_release_max_radial_px = _MAGNETIC_RELEASE_MAX_RADIAL_PX
        self._show_crosshair = True
        self._show_panel_frames = False
        self._show_caliper_labels_on_frame = True
        self._show_caliper_inline_labels = False
        self._doppler_auto_calibration_enabled = True
        self._length_display_unit = "mm"
        self._interesting_dicom_tags: tuple[str, ...] = ()
        self._panel_frame_items: list[pg.PlotDataItem] = []
        self._magnetic_snap_enabled = True
        self._results_overlay_custom_position = False
        self._results_overlay_cleared = False
        self._edge_map_cache: EdgeMap | None = None
        self._edge_map_cache_key: tuple[int, tuple[float, float] | None] | None = None

        self._overlay_label = QLabel(self)
        self._overlay_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._overlay_label.setStyleSheet(_DEFAULT_OVERLAY_STYLE)
        self._overlay_label.hide()

        self._results_overlay_label = ResultsOverlayLabel(self)
        self._results_overlay_label.setStyleSheet(_results_overlay_style(20, 0.84))
        self._results_overlay_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self._results_overlay_label.position_changed.connect(
            self.results_overlay_position_changed.emit
        )
        self._results_overlay_label.clear_requested.connect(self._on_results_overlay_clear)
        self._results_overlay_label.reset_position_requested.connect(self._on_results_overlay_reset_position)
        self._results_overlay_label.pin_toggled.connect(self._on_results_overlay_pin_toggled)
        self._results_overlay_label.hide()

        self._dicom_tags_overlay_label = QLabel(self)
        self._dicom_tags_overlay_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        self._dicom_tags_overlay_label.setStyleSheet(_DEFAULT_OVERLAY_STYLE)
        self._dicom_tags_overlay_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self._dicom_tags_overlay_label.hide()

        self._debug_overlay_visible = False
        self._debug_overlay_label = QLabel(self)
        self._debug_overlay_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        self._debug_overlay_label.setStyleSheet(
            "background-color: rgba(0, 0, 0, 180); color: #0f0; "
            "font-family: monospace; font-size: 11px; padding: 4px;"
        )
        self._debug_overlay_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self._debug_overlay_label.hide()

        self._timeline_slider = QSlider(Qt.Orientation.Horizontal)
        self._timeline_slider.setSingleStep(1)
        self._timeline_slider.valueChanged.connect(self._on_timeline_changed)

        self._scroll_debounce_ms = 70
        self._pending_scroll_index: int | None = None
        self._scroll_debounce_timer = QTimer(self)
        self._scroll_debounce_timer.setSingleShot(True)
        self._scroll_debounce_timer.timeout.connect(self._emit_pending_scroll)

        self._step_back_button = QPushButton("⏮")
        self._step_back_button.setFixedWidth(32)
        self._step_back_button.setToolTip("Step back (Previous frame)")
        self._step_back_button.clicked.connect(self._step_back)

        self._play_button = QPushButton(tr("viewer.play"))
        self._play_button.setFixedWidth(self._play_button.sizeHint().width() + 12)
        self._play_button.clicked.connect(self.play_pause_requested.emit)

        self._step_forward_button = QPushButton("⏭")
        self._step_forward_button.setFixedWidth(32)
        self._step_forward_button.setToolTip("Step forward (Next frame)")
        self._step_forward_button.clicked.connect(self._step_forward)

        self._fps_label = QLabel("FPS: —")
        self._source_label = QLabel("Frame: —")
        self._measurement_label = QLabel(f"{self._current_caliper_label()}: —", self)
        self._measurement_label.hide()

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
        timeline_row.addWidget(self._step_back_button)
        timeline_row.addWidget(self._play_button)
        timeline_row.addWidget(self._step_forward_button)
        timeline_row.addWidget(self._timeline_slider, stretch=1)
        timeline_row.addWidget(self._source_label)
        timeline_row.addWidget(self._fps_label)
        controls.addLayout(timeline_row)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._graphics)
        layout.addLayout(controls)
        self._graphics.setMouseTracking(True)
        self._graphics.setViewportUpdateMode(
            QGraphicsView.ViewportUpdateMode.SmartViewportUpdate,
        )
        from PySide6.QtGui import QPainter
        self._graphics.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self._graphics.installEventFilter(self)
        viewport = self._graphics.viewport()
        if viewport is not None:
            viewport.setMouseTracking(True)
            viewport.installEventFilter(self)
        self._graphics.setFocusPolicy(Qt.FocusPolicy.WheelFocus)

    def _on_scene_mouse_moved(self, scene_pos) -> None:
        mapped = self._view.mapSceneToView(scene_pos)
        if mapped is not None:
            self._update_measurement_crosshair(float(mapped.x()), float(mapped.y()))
        if (
            mapped is not None
            and self._doppler.get_tool_mode() == "interval"
            and self._doppler.has_pending_interval_start()
        ):
            self._doppler.update_interval_preview_position(float(mapped.x()))
        if self._calibration_active:
            mapped = self._view.mapSceneToView(scene_pos)
            if mapped is not None and self._current_frame is not None:
                height = self._current_frame.shape[0]
                raw_y = max(0.0, min(float(mapped.y()), float(height - 1)))
                snapped_y = snap_y_to_nearest_tick(raw_y, self._depth_tick_y_positions, radius_px=self._calibration_tick_snap_radius_px)
                if self._calibration_start_y is not None:
                    self._update_calibration_preview(self._calibration_start_y, snapped_y)
                    self._update_calibration_horizontal_guides(snapped_y)
                else:
                    self._update_calibration_preview(snapped_y, snapped_y)
                    self._update_calibration_horizontal_guides(snapped_y)
            return
        if self._linear_caliper_active and self._linear_caliper_start is not None:
            mapped = self._view.mapSceneToView(scene_pos)
            if mapped is not None:
                end = (float(mapped.x()), float(mapped.y()))
                if self._linear_caliper_start is not None:
                    end = self._constrain_linear_endpoint(self._linear_caliper_start, end)
                self._update_linear_caliper_preview(self._linear_caliper_start, end)
                self._update_linear_caliper_label_preview(self._linear_caliper_start, end)
            return
        if self._caliper_drag_active and QApplication.mouseButtons() & Qt.MouseButton.LeftButton:
            mapped = self._view.mapSceneToView(scene_pos)
            if mapped is not None:
                self._apply_caliper_node_drag(float(mapped.x()), float(mapped.y()))
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
            if event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.RightButton:
                    self._show_save_context_menu(event)
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

    @_prof
    def wheelEvent(self, event) -> None:  # type: ignore[override]
        if self._handle_wheel(event):
            event.accept()
        else:
            super().wheelEvent(event)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._position_overlay_labels(reposition_results=True)

    def _position_overlay_labels(self, *, reposition_results: bool = False) -> None:
        geo = self._graphics.geometry()
        if self._overlay_label.isVisible():
            self._overlay_label.adjustSize()
            label_w = self._overlay_label.width()
            label_h = self._overlay_label.height()
            calibration_banner = self._frame_overlay_lines == [tr(CALIBRATION_PROMPT_OVERLAY_KEY)]
            calibration_ok = self._frame_overlay_lines == [tr(CALIBRATION_SUCCESS_OVERLAY_KEY)]
            if calibration_banner or calibration_ok:
                x = geo.x() + max((geo.width() - label_w) // 2, 8)
                y = geo.y() + max(geo.height() // 6 - label_h // 2, 8)
            else:
                x = geo.x() + 8
                y = geo.y() + 8
            self._overlay_label.move(x, y)

        if self._results_overlay_label.isVisible() and reposition_results:
            if not self._results_overlay_label._pinned:
                self._reposition_results_overlay_label(geo)

        if self._dicom_tags_overlay_label.isVisible():
            self._position_dicom_tags_overlay(geo)

    def _position_dicom_tags_overlay(self, geo) -> None:
        self._dicom_tags_overlay_label.adjustSize()
        self._dicom_tags_overlay_label.move(
            geo.x() + 8,
            geo.y() + geo.height() - self._dicom_tags_overlay_label.height() - 8,
        )

    def _request_results_overlay_reposition(self) -> None:
        if not self._results_overlay_label.isVisible():
            return
        if self._results_overlay_label._pinned:
            return
        QTimer.singleShot(0, self._reposition_results_overlay_deferred)

    def _reposition_results_overlay_deferred(self) -> None:
        if self._results_overlay_label.isVisible():
            self._reposition_results_overlay_label(self._graphics.geometry())

    def _reposition_results_overlay_label(self, geo) -> None:
        if geo.width() < 16 or geo.height() < 16:
            return
        self._results_overlay_label.adjustSize()
        rw = self._results_overlay_label.width()
        rh = self._results_overlay_label.height()
        if self._results_overlay_custom_position:
            x_ratio, y_ratio = self._results_overlay_label.position_ratios()
            x = geo.x() + int(x_ratio * max(geo.width() - rw, 0))
            y = geo.y() + int(y_ratio * max(geo.height() - rh, 0))
        else:
            x = geo.x() + geo.width() - rw - RESULTS_OVERLAY_EDGE_MARGIN - 28
            y = geo.y() + max(
                int(geo.height() * DEFAULT_RESULTS_OVERLAY_Y_RATIO) + 19,
                RESULTS_OVERLAY_EDGE_MARGIN,
            )
        x = max(geo.x(), min(x, geo.x() + max(geo.width() - rw, 0)))
        y = max(geo.y(), min(y, geo.y() + max(geo.height() - rh, 0)))
        self._results_overlay_label.move(x, y)
        if self._results_overlay_custom_position:
            self._results_overlay_label.set_position_ratios(
                (x - geo.x()) / max(geo.width(), 1),
                (y - geo.y()) / max(geo.height(), 1),
            )

    def reset_results_overlay_to_default(self) -> None:
        self._results_overlay_custom_position = False
        if self._results_overlay_label.isVisible():
            self._request_results_overlay_reposition()

    @_prof
    def _on_results_overlay_clear(self) -> None:
        self._results_overlay_cleared = True
        self._stored_linear_measurements.clear()
        self._clear_persistent_linear_calipers()
        self._emit_stored_linear_measurements()
        self.set_results_overlay("")

    def _on_results_overlay_reset_position(self) -> None:
        self.reset_results_overlay_to_default()

    def _on_results_overlay_pin_toggled(self, pinned: bool) -> None:
        if pinned:
            self._results_overlay_label.setCursor(Qt.CursorShape.ArrowCursor)
            if self._results_overlay_custom_position:
                x_ratio, y_ratio = self._results_overlay_label.position_ratios()
                self.results_overlay_position_changed.emit(x_ratio, y_ratio)
        else:
            self._results_overlay_label.setCursor(Qt.CursorShape.OpenHandCursor)

    def _graphics_content_geometry(self):
        return self._graphics.geometry()

    def apply_user_preferences(self, preferences: UserPreferences) -> None:
        self._caliper_line_width = preferences.caliper_line_width
        if not preferences.results_overlay_custom_position:
            self.reset_results_overlay_to_default()
        self._results_overlay_label.setStyleSheet(
            _results_overlay_style(
                preferences.results_overlay_font_size,
                preferences.results_overlay_opacity,
            )
        )
        self._dicom_tags_overlay_label.setStyleSheet(
            _results_overlay_style(
                preferences.results_overlay_font_size,
                preferences.results_overlay_opacity,
            )
        )
        self._show_crosshair = preferences.show_crosshair
        self._show_panel_frames = preferences.show_panel_frames
        self._show_caliper_labels_on_frame = preferences.show_caliper_labels_on_frame
        self._show_caliper_inline_labels = preferences.show_caliper_inline_labels
        self._render_persistent_linear_calipers()
        self._doppler_auto_calibration_enabled = preferences.doppler_auto_calibration_enabled
        self._calibration_tick_snap_enabled = preferences.calibration_tick_snap_enabled
        self._length_display_unit = preferences.length_display_unit
        self._interesting_dicom_tags = tuple(
            tag.strip()
            for tag in preferences.interesting_dicom_tags.split(",")
            if tag.strip()
        )
        self._magnetic_snap_weight_threshold = preferences.magnetic_snap_weight_threshold
        self._magnetic_snap_release_strength = preferences.magnetic_snap_release_strength
        self._magnetic_snap_release_max_radial_px = preferences.magnetic_snap_release_max_radial_px
        self._rebuild_contour_pens(preferences)
        self._refresh_caliper_line_pens()
        self._refresh_rendered_contour_pens()
        self._apply_window_level_preferences(preferences)
        self._refresh_panel_frame_graphics()
        self._refresh_dicom_tags_overlay()
        if not self._show_caliper_labels_on_frame:
            self._measurement_label.hide()
        self._position_overlay_labels()

    def reload_text(self) -> None:
        from echo_personal_tool.infrastructure.i18n import tr

        self._step_back_button.setToolTip(tr("viewer.step_back"))
        self._step_forward_button.setToolTip(tr("viewer.step_forward"))
        self._timeline_slider.setToolTip(tr("viewer.timeline"))
        if self._current_state is not None:
            self._play_button.setText(
                tr("viewer.pause") if self._current_state.is_playing else tr("viewer.play")
            )
            if self._current_state.total_frames > 0:
                current = min(
                    self._current_state.current_frame_index + 1,
                    self._current_state.total_frames,
                )
                self._source_label.setText(
                    tr(
                        "viewer.frame_counter",
                        current=str(current),
                        total=str(self._current_state.total_frames),
                    )
                )
            else:
                self._source_label.setText(tr("viewer.frame_none"))

    def _rebuild_contour_pens(self, preferences: UserPreferences) -> None:
        manual_width = preferences.contour_pen_manual_width
        ai_width = preferences.contour_pen_ai_width
        simpson_width = preferences.contour_pen_simpson_width
        self._contour_pen_manual = pg.mkPen("#ff6f00", width=manual_width)
        self._contour_pen_ai = pg.mkPen("#00bcd4", width=ai_width)
        self._contour_pen_ai_pending = pg.mkPen(
            "#00bcd4", width=ai_width, style=Qt.PenStyle.DashLine
        )
        self._contour_pen_model = pg.mkPen("#4caf50", width=simpson_width)
        ma_width = max(1.0, manual_width * 0.5)
        self._contour_pen_ma = pg.mkPen(
            "#ff6f00", width=ma_width, style=Qt.PenStyle.DashLine
        )

    def _refresh_rendered_contour_pens(self) -> None:
        if self._active_contour_item is not None:
            self._active_contour_item.setPen(self._contour_pen_manual)
        if self._active_ma_chord_item is not None:
            self._active_ma_chord_item.setPen(self._contour_pen_ma)
        for contour_index, contour in enumerate(self._contours):
            if contour_index >= len(self._contour_items):
                continue
            pen = self._contour_pen_for(contour)
            self._contour_items[contour_index].setPen(pen)
            if contour_index < len(self._contour_ma_items):
                ma_item = self._contour_ma_items[contour_index]
                if ma_item is not None:
                    ma_item.setPen(self._contour_pen_ma)
            if contour_index < len(self._contour_nodes):
                for node in self._contour_nodes[contour_index]:
                    node.setPen(pen)
                    node.setBrush(pg.mkBrush(pen.color()))

    def _caliper_pen(self, color: str, *, style: Qt.PenStyle = Qt.PenStyle.SolidLine):
        return pg.mkPen(color, width=self._caliper_line_width, style=style)

    def _refresh_caliper_line_pens(self) -> None:
        if self._linear_caliper_line_item is not None:
            self._linear_caliper_line_item.setPen(self._caliper_pen("#ffb300"))
        if self._linear_caliper_marker_item is not None:
            self._linear_caliper_marker_item.setPen(self._caliper_pen("#ffb300"))
        for line_item, marker_item in self._persistent_linear_graphics:
            pen = self._caliper_pen("#29b6f6")
            line_item.setPen(pen)
            marker_item.setPen(pen)
        if self._calibration_line_item is not None:
            self._calibration_line_item.setPen(self._caliper_pen("#29b6f6"))
        if self._calibration_marker_item is not None:
            self._calibration_marker_item.setPen(self._caliper_pen("#29b6f6"))

    def _apply_window_level_preferences(self, preferences: UserPreferences) -> None:
        window, level, dr = resolve_wl_values(preferences)
        for slider, value in (
            (self._window_slider, window),
            (self._level_slider, level),
            (self._dr_slider, dr),
        ):
            slider.blockSignals(True)
            slider.setValue(value)
            slider.blockSignals(False)
        self._update_levels()

    def _clear_panel_frame_graphics(self) -> None:
        for item in self._panel_frame_items:
            self._view.removeItem(item)
        self._panel_frame_items.clear()

    def _refresh_panel_frame_graphics(self) -> None:
        self._clear_panel_frame_graphics()
        if not self._show_panel_frames:
            return
        layout = self._resolve_frame_panels()
        if layout is None:
            return
        for panel in layout.panels:
            bounds = panel.bounds
            pen = pg.mkPen("#4fc3f7", width=1)
            item = pg.PlotDataItem(pen=pen)
            item.setZValue(12)
            item.setData(
                [bounds.x0, bounds.x1, bounds.x1, bounds.x0, bounds.x0],
                [bounds.y0, bounds.y0, bounds.y1, bounds.y1, bounds.y0],
            )
            self._view.addItem(item)
            self._panel_frame_items.append(item)

    def _refresh_dicom_tags_overlay(self) -> None:
        instance = self._current_instance_metadata()
        if instance is None or instance.path is None or not self._interesting_dicom_tags:
            self._dicom_tags_overlay_label.hide()
            return
        try:
            rows = read_interesting_dicom_tag_rows(instance.path, tuple(self._interesting_dicom_tags))
        except Exception:  # noqa: BLE001
            self._dicom_tags_overlay_label.hide()
            return
        lines = [
            f"{row.keyword or row.tag_hex}: {row.value}"
            for row in rows
            if row.value
        ]
        if not lines:
            self._dicom_tags_overlay_label.hide()
            return
        self._dicom_tags_overlay_label.setText("\n".join(lines))
        self._dicom_tags_overlay_label.adjustSize()
        self._dicom_tags_overlay_label.show()
        self._position_dicom_tags_overlay(self._graphics.geometry())

    def _current_instance_metadata(self):
        if self._current_state is not None and self._current_state.instance is not None:
            return self._current_state.instance
        return None

    @_prof
    def set_results_overlay(self, text: str) -> None:
        """Show session measurement summary (top-right box, left-aligned text)."""
        if self._results_overlay_cleared and text.strip():
            return
        self._results_overlay_cleared = False
        if text.strip():
            text_changed = text != self._results_overlay_label.text()
            was_visible = self._results_overlay_label.isVisible()
            if text_changed:
                self._results_overlay_label.setText(text)
                self._results_overlay_label.adjustSize()
            if not was_visible:
                self._results_overlay_label.show()
            self._results_overlay_label.raise_()
            if not self._results_overlay_custom_position and (not was_visible or text_changed):
                self._request_results_overlay_reposition()
        else:
            self._results_overlay_label.hide()
            self._position_dicom_tags_overlay(self._graphics.geometry())

    def refresh_dicom_tags_overlay(self) -> None:
        self._refresh_dicom_tags_overlay()

    @_prof
    def toggle_debug_overlay(self) -> None:
        self._debug_overlay_visible = not self._debug_overlay_visible
        if self._debug_overlay_visible:
            self._update_debug_overlay()
            self._debug_overlay_label.show()
        else:
            self._debug_overlay_label.hide()

    def _update_debug_overlay(self) -> None:
        if not self._debug_overlay_visible:
            return
        lines: list[str] = []
        if self._current_frame is not None:
            h, w = self._current_frame.shape[:2]
            lines.append(f"Native: {w}x{h}")
        geo = self._graphics.geometry()
        vw, vh = geo.width(), geo.height()
        lines.append(f"Viewport: {vw}x{vh}")
        if self._current_frame is not None:
            h, w = self._current_frame.shape[:2]
            if w > 0 and h > 0:
                scale = max(vw / w, vh / h)
                lines.append(f"Scale: {scale:.2f}x")
        dpr = self._graphics.devicePixelRatioF()
        lines.append(f"DPR: {dpr:.1f}")
        if self._current_state and self._current_state.instance:
            inst = self._current_state.instance
            lines.append(f"Format: {inst.media_format}")
            lines.append(f"Frames: {inst.number_of_frames}")
        self._debug_overlay_label.setText("\n".join(lines))
        self._debug_overlay_label.adjustSize()
        geo_viewer = self._graphics.geometry()
        self._debug_overlay_label.move(
            geo_viewer.x() + 4,
            geo_viewer.y() + 4,
        )
        self._debug_overlay_label.raise_()

    def _mark_results_overlay_custom_position(self) -> None:
        self._results_overlay_custom_position = True

    def results_overlay_custom_position(self) -> bool:
        return self._results_overlay_custom_position

    def set_results_overlay_position(
        self,
        x_ratio: float,
        y_ratio: float,
        *,
        custom: bool = True,
    ) -> None:
        self._results_overlay_custom_position = custom
        if custom:
            self._results_overlay_label.set_position_ratios(x_ratio, y_ratio)
        if self._results_overlay_label.isVisible():
            self._request_results_overlay_reposition()

    def results_overlay_position(self) -> tuple[float, float]:
        return self._results_overlay_label.position_ratios()

    @_prof
    def reposition_overlays(self) -> None:
        self._position_overlay_labels(reposition_results=not self._results_overlay_custom_position)

    def results_overlay_text(self) -> str:
        return self._results_overlay_label.text()

    def _position_overlay_label(self) -> None:
        self._position_overlay_labels()

    def _show_save_context_menu(self, ev) -> None:
        menu = QMenu(self)
        menu.addAction(tr("viewer.context_save_as"), self._save_viewer_image)
        menu.exec(QCursor.pos())

    def _save_viewer_image(self) -> None:
        if self._current_frame is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            tr("viewer.context_save_frame"),
            "",
            "PNG (*.png);JPEG (*.jpg)",
        )
        if not path:
            return
        full = self.grab()
        geo = self._graphics.geometry()
        cropped = full.copy(geo.x(), geo.y(), geo.width(), geo.height())
        cropped.save(path)

    def _resolve_display_mode(
        self,
        frame: np.ndarray,
        media_format: str | None,
    ) -> tuple[bool, bool]:
        """Return (color_display, window_level_enabled)."""
        if frame.ndim == 3 and frame.shape[2] >= 3:
            if media_format == "dicom":
                if is_color_frame(frame):
                    return True, False
                return False, True
            if is_effective_grayscale(frame, tolerance=24):
                return False, True
            color = is_color_frame(frame)
            return color, not color
        return False, True

    @_prof
    def show_frame(self, pixels: np.ndarray) -> None:
        """Render a 2D grayscale (H, W) or color BGR (H, W, 3) array."""
        frame = np.asarray(pixels)
        media_format = (
            self._current_state.instance.media_format
            if self._current_state is not None and self._current_state.instance is not None
            else None
        )
        # Cache display mode per instance to avoid re-detection
        instance_key = id(frame) if frame.base is None else None
        if not hasattr(self, "_display_mode_cache_key") or self._display_mode_cache_key != instance_key:
            self._is_color_frame, self._window_level_enabled = self._resolve_display_mode(
                frame, media_format,
            )
            self._display_mode_cache_key = instance_key
        channel_order = "rgb" if media_format == "dicom" else "bgr"
        self._current_frame = to_grayscale_array(frame)

        if self._is_color_frame:
            self._color_source_rgb = to_display_rgb(frame, channel_order=channel_order)
            self._image_item.setImage(self._color_source_rgb, autoLevels=False)
            if self._window_level_enabled:
                self._update_levels()
            else:
                self._image_item.setLevels((0, 255))
        else:
            self._color_source_rgb = None
            gray = self._current_frame
            self._image_item.setImage(gray, autoLevels=False)
            if self._window_level_enabled:
                self._update_levels()
            else:
                vmin = float(gray.min()) if gray.size else 0.0
                vmax = float(gray.max()) if gray.size else 255.0
                if vmin == vmax:
                    vmax = vmin + 1.0
                self._image_item.setLevels((vmin, vmax))
            new_path = Path(self._current_state.instance.path) if self._current_state and self._current_state.instance and self._current_state.instance.path else None
            if new_path != self._current_instance_path:
                with QSignalBlocker(self._dr_slider):
                    self._dr_slider.setValue(50)
                self._current_instance_path = new_path
            self._update_levels()
        self._window_slider.setEnabled(self._window_level_enabled)
        self._level_slider.setEnabled(self._window_level_enabled)
        self._dr_slider.setEnabled(self._window_level_enabled)
        sync_enabled = getattr(self, "_sync_display_control_enabled", None)
        if callable(sync_enabled):
            sync_enabled()
        if self._current_frame is not None:
            height, width = self._current_frame.shape[:2]
            self._view.setRange(xRange=(0, width), yRange=(0, height), padding=0)
            self._refresh_frame_panel_layout()
            self._configure_doppler_axis_for_frame()
            self._invalidate_edge_map_cache()
        self._update_debug_overlay()
        self._apply_zoom_mode()

    def _apply_zoom_mode(self) -> None:
        if self._current_frame is None:
            return
        h, w = self._current_frame.shape[:2]
        if self._zoom_mode == "fit":
            self._view.setRange(xRange=(0, w), yRange=(0, h), padding=0)
        elif self._zoom_mode == "100%":
            dpr = self._graphics.devicePixelRatioF()
            view_w = self._graphics.viewport().width() / dpr
            view_h = self._graphics.viewport().height() / dpr
            cx, cy = w / 2.0, h / 2.0
            half_w = view_w / 2.0
            half_h = view_h / 2.0
            self._view.setRange(
                xRange=(cx - half_w, cx + half_w),
                yRange=(cy - half_h, cy + half_h),
                padding=0,
            )
        elif self._zoom_mode == "200%":
            dpr = self._graphics.devicePixelRatioF()
            view_w = self._graphics.viewport().width() / dpr
            view_h = self._graphics.viewport().height() / dpr
            cx, cy = w / 2.0, h / 2.0
            half_w = view_w / 4.0
            half_h = view_h / 4.0
            self._view.setRange(
                xRange=(cx - half_w, cx + half_w),
                yRange=(cy - half_h, cy + half_h),
                padding=0,
            )

    def cycle_zoom_mode(self) -> None:
        modes = ["fit", "100%", "200%"]
        idx = modes.index(self._zoom_mode) if self._zoom_mode in modes else 0
        self._zoom_mode = modes[(idx + 1) % len(modes)]
        self._zoom_factor = 1.0
        self._apply_zoom_mode()

    def set_zoom_mode(self, mode: str) -> None:
        if mode in ("fit", "100%", "200%"):
            self._zoom_mode = mode
            self._zoom_factor = 1.0
            self._apply_zoom_mode()

    @property
    def zoom_mode(self) -> str:
        return self._zoom_mode

    @_prof
    def show_frame_fast(self, pixels: np.ndarray) -> None:
        """Fast render for playback: skip layout/doppler/panel detection."""
        frame = np.asarray(pixels)
        media_format = (
            self._current_state.instance.media_format
            if self._current_state is not None and self._current_state.instance is not None
            else None
        )
        # Cache display mode per instance to avoid re-detection every frame
        instance_key = id(frame) if frame.base is None else None
        if not hasattr(self, "_display_mode_cache_key") or self._display_mode_cache_key != instance_key:
            self._is_color_frame, self._window_level_enabled = self._resolve_display_mode(
                frame, media_format,
            )
            self._display_mode_cache_key = instance_key
        channel_order = "rgb" if media_format == "dicom" else "bgr"

        levels_key = (
            self._dr_slider.value(),
            self._window_slider.value(),
            self._level_slider.value(),
        )
        levels_changed = levels_key != self._cached_levels_key
        self._cached_levels_key = levels_key

        if self._is_color_frame:
            frame_data_ptr = frame.ctypes.data if hasattr(frame, 'ctypes') else id(frame)
            if frame_data_ptr != self._last_color_frame_ptr:
                self._color_source_rgb = to_display_rgb(frame, channel_order=channel_order)
                self._last_color_frame_ptr = frame_data_ptr
            self._current_frame = to_grayscale_array(frame)
            self._image_item.setImage(self._color_source_rgb, autoLevels=False)
            if self._window_level_enabled and levels_changed:
                self._update_levels()
            elif not self._window_level_enabled:
                self._image_item.setLevels((0, 255))
        else:
            self._color_source_rgb = None
            # Skip float64 conversion — pyqtgraph displays uint8 directly
            if frame.ndim == 2:
                self._current_frame = frame
            elif frame.ndim == 3 and frame.shape[2] >= 3:
                self._current_frame = np.mean(frame[..., :3], axis=2).astype(np.uint8) if not levels_changed else to_grayscale_array(frame)
            else:
                self._current_frame = frame[..., 0] if frame.ndim == 3 else frame
            self._image_item.setImage(self._current_frame, autoLevels=False)
            if self._window_level_enabled:
                self._update_levels()
            elif not self._window_level_enabled:
                vmin = float(self._current_frame.min()) if self._current_frame.size else 0.0
                vmax = float(self._current_frame.max()) if self._current_frame.size else 255.0
                if vmin == vmax:
                    vmax = vmin + 1.0
                self._image_item.setLevels((vmin, vmax))
        sync_enabled = getattr(self, "_sync_display_control_enabled", None)
        if callable(sync_enabled):
            sync_enabled()

    @_prof
    def refresh_after_scroll(self) -> None:
        """Restore layout/overlays after fast scroll without reprocessing pixels."""
        if self._current_frame is not None:
            height, width = self._current_frame.shape[:2]
            # Preserve zoom if user has zoomed in (custom or 100%/200%)
            if self._zoom_mode != "fit" or self._zoom_factor != 1.0:
                pass  # keep current view range, don't reset
            else:
                self._view.setRange(xRange=(0, width), yRange=(0, height), padding=0)
            if self._window_level_enabled:
                self._update_levels()
            self._refresh_frame_panel_layout()
            self._configure_doppler_axis_for_frame()
            self._invalidate_edge_map_cache()

    def clear(self) -> None:
        self._image_item.clear()
        self._clear_linear_caliper()
        self._clear_calibration_caliper()
        self._clear_contours()

    @_prof
    def set_state(self, viewer_state: ViewerState) -> None:
        if self._syncing_state:
            self._pending_viewer_state = viewer_state
            return
        self._syncing_state = True
        previous_instance = self._current_state.instance if self._current_state else None
        previous_frame = self._current_state.current_frame_index if self._current_state else None
        frame_changed = previous_frame != viewer_state.current_frame_index
        if previous_instance != viewer_state.instance:
            self._clear_linear_caliper()
            self._clear_calibration_caliper()
            self._clear_persistent_linear_calipers()
            self._clear_contours()
            self._stored_linear_measurements = {}
            self._results_overlay_cleared = False
            if self._doppler_cal_step is not None:
                self._doppler_cal_step = None
                self._doppler_roi_corner1 = None
                self._doppler_pending_roi = None
                self._doppler_pending_baseline_y = None
            self.clear_doppler_calibration_display()
        elif frame_changed:
            if previous_frame is not None and not self._syncing_state:
                self.doppler_frame_changing.emit(
                    previous_frame,
                    self.get_doppler_dto(),
                )
            self._clear_active_contour_drawing()
            self._doppler_calibration_state = None
            self._doppler_calibration_instance_uid = None
            self._doppler_calibration_frame_index = None
            self._doppler.clear_measurements(keep_calibration_graphics=False)
            if not self._syncing_state:
                self.doppler_frame_changed.emit(viewer_state.current_frame_index)
        self._stored_linear_measurements = {
            self._linear_measurement_key(measurement): measurement
            for measurement in viewer_state.linear_measurements
        }
        self._current_state = viewer_state
        try:
            maximum = max(0, viewer_state.total_frames - 1)
            self._timeline_slider.setRange(0, maximum)
            controls_enabled = viewer_state.total_frames > 1
            self._timeline_slider.setEnabled(controls_enabled)
            self._play_button.setEnabled(controls_enabled and not viewer_state.decode_in_progress)
            target_frame = min(viewer_state.current_frame_index, maximum)
            if self._timeline_slider.value() != target_frame:
                self._timeline_slider.setValue(target_frame)
            play_text = tr("viewer.pause") if viewer_state.is_playing else tr("viewer.play")
            if self._play_button.text() != play_text:
                self._play_button.setText(play_text)
            fps_text = f"FPS: {viewer_state.fps:.1f}" if viewer_state.fps > 0 else "FPS: —"
            if self._fps_label.text() != fps_text:
                self._fps_label.setText(fps_text)
            if viewer_state.total_frames > 0:
                current = min(viewer_state.current_frame_index + 1, viewer_state.total_frames)
                source_text = tr(
                    "viewer.frame_counter",
                    current=str(current),
                    total=str(viewer_state.total_frames),
                )
            else:
                source_text = tr("viewer.frame_none")
            if self._source_label.text() != source_text:
                self._source_label.setText(source_text)
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
            self._refresh_speckle_overlay_for_current_frame()
            self._set_image_smooth(not viewer_state.is_playing)
            if not viewer_state.is_playing:
                self._refresh_frame_panel_layout()
                self._refresh_panel_frame_graphics()
                self._refresh_dicom_tags_overlay()
        finally:
            self._syncing_state = False
            pending = self._pending_viewer_state
            self._pending_viewer_state = None
            if pending is not None:
                self.set_state(pending)

    def _set_image_smooth(self, enabled: bool) -> None:
        if self._image_smooth == enabled:
            return
        self._image_smooth = enabled
        self._image_item.setOpts(smooth=enabled)

    @_prof
    def toggle_linear_caliper(self) -> None:
        if self._linear_caliper_active:
            self._clear_linear_caliper()
            return
        self._clear_calibration_caliper()
        self.activate_generic_dist_caliper()

    def activate_generic_dist_caliper(self) -> str | None:
        """Start click-click caliper with the next DistN label; return label or None."""
        label = f"Dist{self._dist_serial}"
        if self.start_linear_caliper_for(label):
            self._dist_serial += 1
            return label
        return None

    def reset_dist_caliper_serial(self) -> None:
        self._dist_serial = 1

    @property
    def dist_caliper_serial(self) -> int:
        return self._dist_serial

    @property
    def is_linear_caliper_active(self) -> bool:
        return self._linear_caliper_active

    @_prof
    def toggle_calibration_caliper(self) -> None:
        if self._calibration_active:
            self._clear_calibration_caliper()
            return
        self.start_calibration_caliper()

    @_prof
    def start_calibration_caliper(self) -> bool:
        self._clear_linear_caliper()
        self._clear_calibration_caliper()
        if self._current_frame is None:
            return False

        height, width = self._current_frame.shape[:2]
        self._calibration_kind = "depth"
        self._calibration_active = True
        self._calibration_x = min(float(width) * 0.96, float(width - 5))
        self._calibration_start_y = None
        if self._calibration_tick_snap_enabled:
            self._depth_tick_y_positions = self._detect_calibration_ticks()
        else:
            self._depth_tick_y_positions = []
        self._measurement_label.setText(tr("viewer.calibration_click_start"))
        return True

    def _detect_calibration_ticks(self) -> list[float]:
        if self._current_frame is None:
            return []
        return find_scale_ticks(self._current_frame)

    def start_spectral_calibration(self) -> bool:
        """Start Doppler calibration wizard (ROI → baseline → velocity scale)."""
        return self.start_doppler_calibration(DopplerKind.SPECTRAL)

    def start_doppler_calibration(self, kind: DopplerKind = DopplerKind.SPECTRAL) -> bool:
        if self._current_frame is None:
            return False
        self.cancel_active_tool()
        self._clear_calibration_caliper()
        self._doppler_cal_kind = kind
        self._doppler_cal_step = "roi"
        self._doppler_roi_corner1 = None
        self._doppler_pending_roi = None
        self._doppler_pending_baseline_y = None
        self._measurement_label.setText(tr(_DOPPLER_CAL_ROI_STEP1_KEY))
        self._measurement_label.show()
        return True

    @staticmethod
    def doppler_calibration_prompt() -> str:
        return tr("viewer.doppler_calibration_prompt")

    def _current_instance_uid(self) -> str | None:
        if self._current_state is None or self._current_state.instance is None:
            return None
        return self._current_state.instance.sop_instance_uid

    def _current_frame_index(self) -> int | None:
        if self._current_state is None:
            return None
        return self._current_state.current_frame_index

    def _doppler_calibration_matches_instance(self) -> bool:
        current_uid = self._current_instance_uid()
        if current_uid is None or self._doppler_calibration_instance_uid is None:
            return False
        if current_uid != self._doppler_calibration_instance_uid:
            return False
        frame_index = self._current_frame_index()
        if frame_index is None or self._doppler_calibration_frame_index is None:
            return False
        return frame_index == self._doppler_calibration_frame_index

    def clear_doppler_calibration_display(self) -> None:
        self._doppler_calibration_state = None
        self._doppler_calibration_instance_uid = None
        self._doppler_calibration_frame_index = None
        self._doppler_axis_calibrated = False
        self._doppler.clear_measurements(keep_calibration_graphics=False)
        if self._current_frame is None:
            return
        height, width = self._current_frame.shape[:2]
        self._doppler.set_axis_mapping(
            DopplerAxisMapping.from_frame_size(width, height)
        )

    def is_doppler_axis_calibrated(self) -> bool:
        return self.is_doppler_velocity_calibrated() and self.is_doppler_time_calibrated()

    def is_doppler_velocity_calibrated(self) -> bool:
        state = self._doppler_calibration_state
        return state is not None and state.has_velocity_scale()

    def is_doppler_time_calibrated(self) -> bool:
        state = self._doppler_calibration_state
        return state is not None and state.has_time_scale_from_dicom()

    def start_mitral_inflow_workflow(self) -> bool:
        if self._current_frame is None:
            return False
        self.cancel_active_tool()
        self._doppler.start_mitral_inflow_workflow()
        prompt = self._doppler.workflow_prompt()
        if prompt:
            self._measurement_label.setText(prompt)
        return True

    def _on_doppler_workflow_step_changed(self, prompt: str) -> None:
        self._measurement_label.setText(prompt)

    def _on_doppler_workflow_completed(self) -> None:
        self._measurement_label.setText(tr("viewer.mitral_inflow_done"))

    def _on_doppler_trace_prompt_changed(self, prompt: str) -> None:
        self._measurement_label.setText(prompt)

    def restore_doppler_measurements(self, dto: object) -> None:
        from echo_personal_tool.domain.models.doppler import DopplerMeasurementDTO

        if isinstance(dto, DopplerMeasurementDTO):
            self._doppler.load_measurement_dto(dto)

    def clear_doppler_measurements(self) -> None:
        self._doppler.clear_measurements(keep_calibration_graphics=False)

    def get_doppler_calibration_state(self) -> DopplerCalibrationState | None:
        return self._doppler_calibration_state

    def apply_doppler_calibration_state(
        self,
        state: DopplerCalibrationState,
        *,
        persist: bool = True,
    ) -> None:
        if self._current_frame is not None:
            height, width = self._current_frame.shape[:2]
            roi = state.roi.normalized(float(width), float(height))
            baseline_y = max(roi.y0, min(state.baseline_y_px, roi.y1))
            state = DopplerCalibrationState(
                roi=roi,
                baseline_y_px=baseline_y,
                time_origin_ms=state.time_origin_ms,
                time_span_ms=state.time_span_ms,
                velocity_span_cm_s=state.velocity_span_cm_s,
                kind=state.kind,
                from_dicom_tags=state.from_dicom_tags,
            )
        self._doppler_calibration_state = state
        self._doppler_calibration_instance_uid = self._current_instance_uid()
        self._doppler_calibration_frame_index = self._current_frame_index()
        self._doppler.set_axis_mapping(build_axis_mapping(state))
        self._doppler_axis_calibrated = state.has_velocity_scale()
        if (
            persist
            and not self._syncing_state
            and self._doppler_calibration_matches_instance()
        ):
            self.doppler_calibration_changed.emit(state)

    def restore_doppler_state(
        self,
        calibration: DopplerCalibrationState | None,
        dto: object | None,
    ) -> None:
        if calibration is not None:
            self.apply_doppler_calibration_state(calibration, persist=False)
        elif not self._try_auto_detect_doppler_calibration():
            self.clear_doppler_calibration_display()
        if dto is not None:
            from echo_personal_tool.domain.models.doppler import DopplerMeasurementDTO

            if isinstance(dto, DopplerMeasurementDTO):
                self._doppler.load_measurement_dto(dto)
        else:
            self._doppler.clear_measurements(keep_calibration_graphics=True)

    def start_doppler_envelope_trace(
        self,
        plot_points: tuple[tuple[float, float], ...],
        *,
        trace_label: str = "VTI",
    ) -> None:
        self._doppler.set_trace_label(trace_label)
        self._doppler.start_trace_from_plot_points(plot_points, label=trace_label)

    def set_doppler_tool_mode(
        self,
        mode: str,
        *,
        peak_label: str | None = None,
        interval_label: str | None = None,
        trace_label: str | None = None,
    ) -> None:
        self.cancel_active_tool()
        self._doppler.set_tool_mode(mode)
        if mode == "peak":
            self._doppler.set_peak_label(peak_label or "E", single_shot=True)
        elif mode == "interval":
            self._doppler.set_interval_label(interval_label or "DT", single_shot=True)
        elif interval_label is not None:
            self._doppler.set_interval_label(interval_label, single_shot=True)
        elif peak_label is not None:
            self._doppler.set_peak_label(peak_label, single_shot=True)
        if trace_label is not None:
            self._doppler.set_trace_label(trace_label)
        if mode != "none":
            prompt = self._doppler.workflow_prompt()
            if prompt:
                self._measurement_label.setText(prompt)
            elif mode == "trace":
                prompt = self._doppler.trace_prompt()
                self._measurement_label.setText(
                    prompt
                    or tr("viewer.doppler_trace_prompt")
                )
            else:
                self._measurement_label.setText(tr("viewer.doppler_mode_click", mode=mode))
            self._ensure_crosshair_graphics()

    def is_doppler_context(self) -> bool:
        if self._doppler.get_tool_mode() != "none":
            return True
        if self._doppler_cal_step is not None:
            return True
        if self._calibration_kind in {"spectral", "doppler_velocity"}:
            return True
        if self._doppler_calibration_state is not None:
            return True
        panels = self._resolve_frame_panels()
        return panels is not None and panels.doppler is not None

    def start_doppler_scale_calibration(self) -> bool:
        if self._current_frame is None:
            return False
        self.cancel_active_tool()
        return self.start_doppler_calibration(DopplerKind.SPECTRAL)

    def is_mmode_calibrated(self) -> bool:
        return (
            self._mmode_calibration_state is not None
            and self._mmode_calibration_state.is_complete()
        )

    def get_mmode_calibration_state(self) -> MmodeCalibrationState | None:
        return self._mmode_calibration_state

    def apply_mmode_calibration_state(self, state: MmodeCalibrationState) -> None:
        if self._current_frame is not None:
            height, width = self._current_frame.shape[:2]
            roi = state.roi.normalized(float(width), float(height))
            state = MmodeCalibrationState(
                roi=roi,
                vertical_mm_per_pixel=state.vertical_mm_per_pixel,
                horizontal_ms_per_pixel=state.horizontal_ms_per_pixel,
            )
        self._mmode_calibration_state = state
        if not self._syncing_state:
            self.mmode_calibration_changed.emit(state)

    def restore_mmode_state(self, calibration: MmodeCalibrationState | None) -> None:
        if calibration is not None:
            self.apply_mmode_calibration_state(calibration)
        elif self._current_frame is not None:
            self.try_apply_mmode_from_dicom_or_heuristic()

    def try_apply_mmode_from_dicom_or_heuristic(self) -> bool:
        panels = self._resolve_frame_panels()
        if panels is None:
            return False
        m_panel = panels.m_mode
        if m_panel is None:
            return False
        state = mmode_state_from_panel(m_panel)
        if state is None:
            return False
        self.apply_mmode_calibration_state(state)
        return True

    def start_mmode_panel_calibration(self) -> bool:
        if self._current_frame is None:
            return False
        self.cancel_active_tool()
        self._clear_calibration_caliper()
        self._mmode_cal_step = "roi"
        self._mmode_roi_corner1 = None
        self._mmode_pending_roi = None
        self._measurement_label.setText(tr("viewer.mmode_cal1"))
        return True

    def _handle_mmode_calibration_click(self, ev) -> bool:
        if self._mmode_cal_step != "roi" or self._current_frame is None:
            return False
        if ev.button() != Qt.MouseButton.LeftButton:
            return False
        click = self._map_view_event(ev)
        if click is None:
            return False
        x, y = click
        if self._mmode_roi_corner1 is None:
            self._mmode_roi_corner1 = (x, y)
            self._measurement_label.setText(tr("viewer.mmode_cal2"))
            return True
        height, width = self._current_frame.shape[:2]
        roi = roi_from_corners(self._mmode_roi_corner1, (x, y)).normalized(
            float(width),
            float(height),
        )
        self._mmode_cal_step = None
        self._mmode_roi_corner1 = None
        self._mmode_pending_roi = roi
        self._calibration_kind = "mmode_depth"
        self._calibration_active = True
        self._calibration_x = roi.x0 + roi.width / 2.0
        self._calibration_start_y = None
        self._measurement_label.setText(tr("viewer.mmode_cal_depth"))
        return True

    def _refresh_frame_panel_layout(self) -> None:
        self._frame_panel_layout = None
        if self._current_frame is None:
            return
        instance = self._current_state.instance if self._current_state else None
        if instance is not None and instance.media_format == "dicom" and instance.path is not None:
            self._frame_panel_layout = try_parse_panels_from_path(instance.path)
        if self._frame_panel_layout is None:
            gray = self._current_frame
            if gray.ndim == 3:
                gray = np.mean(gray, axis=2)
            self._frame_panel_layout = detect_panels_heuristic(gray)

    def _resolve_frame_panels(self) -> FramePanelLayout | None:
        if self._frame_panel_layout is None:
            self._refresh_frame_panel_layout()
        return self._frame_panel_layout

    def _crosshair_panel_bounds(self) -> DopplerSpectrogramRoi | None:
        if self.get_doppler_tool_mode() != "none" and self._doppler_calibration_state is not None:
            return self._doppler_calibration_state.roi
        if (
            self._linear_caliper_active
            and self._current_caliper_label() in self._vertical_caliper_labels
            and self._mmode_calibration_state is not None
        ):
            return self._mmode_calibration_state.roi
        if self._calibration_kind in {"mmode_time", "mmode_depth"}:
            if self._mmode_pending_roi is not None:
                return self._mmode_pending_roi
            if self._mmode_calibration_state is not None:
                return self._mmode_calibration_state.roi
            if self._calibration_kind == "mmode_time":
                panels = self._resolve_frame_panels()
                if panels is not None and panels.m_mode is not None:
                    return panels.m_mode.bounds
        if self._doppler_cal_step is not None and self._doppler_pending_roi is not None:
            return self._doppler_pending_roi
        return None

    def _measurement_crosshair_active(self) -> bool:
        if self._crosshair_panel_bounds() is not None:
            return True
        return False

    def _ensure_crosshair_graphics(self) -> None:
        pen = pg.mkPen("#9e9e9e", width=1, style=Qt.PenStyle.DashLine)
        if self._crosshair_h_item is None:
            self._crosshair_h_item = pg.PlotDataItem(pen=pen)
            self._crosshair_h_item.setZValue(30)
            self._crosshair_h_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self._crosshair_h_item.setAcceptHoverEvents(False)
            self._view.addItem(self._crosshair_h_item)
        if self._crosshair_v_item is None:
            self._crosshair_v_item = pg.PlotDataItem(pen=pen)
            self._crosshair_v_item.setZValue(30)
            self._crosshair_v_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self._crosshair_v_item.setAcceptHoverEvents(False)
            self._view.addItem(self._crosshair_v_item)

    def _clear_crosshair(self) -> None:
        if self._crosshair_h_item is not None:
            self._crosshair_h_item.setData([], [])
        if self._crosshair_v_item is not None:
            self._crosshair_v_item.setData([], [])

    def _update_measurement_crosshair(self, x: float, y: float) -> None:
        if not self._show_crosshair:
            self._clear_crosshair()
            return
        panel = self._crosshair_panel_bounds()
        if panel is None or not self._measurement_crosshair_active():
            self._clear_crosshair()
            return
        if not panel.contains(x, y):
            self._clear_crosshair()
            return
        self._ensure_crosshair_graphics()
        assert self._crosshair_h_item is not None
        assert self._crosshair_v_item is not None
        self._crosshair_h_item.setData([panel.x0, panel.x1], [y, y])
        self._crosshair_v_item.setData([x, x], [panel.y0, panel.y1])

    def get_doppler_tool_mode(self) -> str:
        return self._doppler.get_tool_mode()

    def finish_doppler_trace(self) -> bool:
        finished = self._doppler.finish_trace()
        if finished:
            self._measurement_label.setText(f"{self._current_caliper_label()}: —")
        else:
            self._measurement_label.setText(
                tr("viewer.doppler_trace_finish")
            )
        return finished

    def get_doppler_dto(self):
        return self._doppler.get_measurement_dto()

    def _try_auto_detect_doppler_calibration(self) -> bool:
        if not self._doppler_auto_calibration_enabled:
            return False
        if self._current_frame is None:
            return False
        instance = self._current_state.instance if self._current_state else None
        if instance is not None and instance.media_format == "dicom" and instance.path is not None:
            parsed = try_parse_from_path(
                instance.path,
                kind=DopplerKind.SPECTRAL,
                frame=self._current_frame,
            )
            if parsed is not None and parsed.has_time_scale_from_dicom():
                self.apply_doppler_calibration_state(parsed, persist=True)
                return True
        return False

    def _configure_doppler_axis_for_frame(self) -> None:
        if self._current_frame is None:
            return
        if (
            self._doppler_calibration_state is not None
            and self._doppler_calibration_matches_instance()
        ):
            self.apply_doppler_calibration_state(
                self._doppler_calibration_state,
                persist=False,
            )
            return
        if self._doppler_calibration_state is not None:
            self.clear_doppler_calibration_display()

        if self._try_auto_detect_doppler_calibration():
            return

        height, width = self._current_frame.shape[:2]
        mapping = DopplerAxisMapping.from_frame_size(width, height)
        self._doppler.set_axis_mapping(mapping)
        self._doppler_axis_calibrated = False

    def _handle_doppler_calibration_click(self, ev) -> bool:
        if self._doppler_cal_step is None or self._current_frame is None:
            return False
        if ev.button() != Qt.MouseButton.LeftButton:
            return False
        click = self._map_view_event(ev)
        if click is None:
            return False
        x, y = click

        if self._doppler_cal_step == "roi":
            if self._doppler_roi_corner1 is None:
                self._doppler_roi_corner1 = (x, y)
                self._measurement_label.setText(_DOPPLER_CAL_ROI_STEP2)
                return True
            roi = roi_from_corners(self._doppler_roi_corner1, (x, y))
            height, width = self._current_frame.shape[:2]
            roi = roi.normalized(float(width), float(height))
            frame = self._current_frame
            if frame.ndim == 3:
                gray = np.mean(frame, axis=2)
            else:
                gray = frame
            baseline_y = detect_baseline_y(gray, roi)
            self._doppler_pending_roi = roi
            self._doppler_pending_baseline_y = baseline_y
            self._doppler_cal_step = "baseline"
            partial = calibration_from_roi_and_baseline(
                roi,
                baseline_y,
                kind=self._doppler_cal_kind,
            )
            self._doppler.set_axis_mapping(build_axis_mapping(partial))
            self._measurement_label.setText(_DOPPLER_CAL_BASELINE)
            return True

        if self._doppler_cal_step == "baseline":
            self._doppler_pending_baseline_y = y
            if self._doppler_pending_roi is not None:
                partial = calibration_from_roi_and_baseline(
                    self._doppler_pending_roi,
                    y,
                    kind=self._doppler_cal_kind,
                )
                self._doppler.set_axis_mapping(build_axis_mapping(partial))
            self._begin_doppler_velocity_calibration()
            return True

        return False

    def _begin_doppler_velocity_calibration(self) -> None:
        if self._current_frame is None:
            return
        width = self._current_frame.shape[1]
        self._doppler_cal_step = None
        self._calibration_kind = "doppler_velocity"
        self._calibration_active = True
        roi = self._doppler_pending_roi
        if roi is not None:
            self._calibration_x = min(roi.x1 - 4.0, float(width - 5))
        else:
            self._calibration_x = min(float(width) * 0.96, float(width - 5))
        self._calibration_start_y = None
        self._measurement_label.setText(_DOPPLER_CAL_VELOCITY)

    def _handle_doppler_mouse_click(self, ev) -> bool:
        if self._doppler_cal_step is not None or self._calibration_active:
            return False
        if self._doppler.get_tool_mode() == "none":
            return False
        if self._doppler.get_tool_mode() == "trace":
            if self._doppler.consume_trace_click_suppression():
                return True
            # Trace onset/close and optional click points use click, not press-drag.
        if ev.button() != Qt.MouseButton.LeftButton:
            return False
        click = self._map_view_event(ev)
        if click is None:
            return False
        double = hasattr(ev, "double") and ev.double()
        return self._doppler.handle_click(click[0], click[1], double=double)

    def _handle_doppler_trace_press(self, ev) -> bool:
        if self._doppler_cal_step is not None or self._calibration_active:
            return False
        if self._doppler.get_tool_mode() != "trace":
            return False
        if ev.button() != Qt.MouseButton.LeftButton:
            return False
        click = self._map_view_event(ev)
        if click is None:
            return False
        if not self._doppler.has_trace_onset():
            return False
        return self._doppler.begin_trace_stroke(click[0], click[1])

    def _handle_doppler_trace_drag(self, ev) -> bool:
        if self._doppler_cal_step is not None or self._calibration_active:
            return False
        if self._doppler.get_tool_mode() != "trace":
            return False
        if ev.button() != Qt.MouseButton.LeftButton:
            return False
        click = self._map_view_event(ev)
        if click is None:
            return False
        return self._doppler.extend_trace_stroke(click[0], click[1])

    def _handle_doppler_trace_release(self, ev) -> bool:
        if self._doppler_cal_step is not None or self._calibration_active:
            return False
        if self._doppler.get_tool_mode() != "trace":
            return False
        if ev.button() != Qt.MouseButton.LeftButton:
            return False
        click = self._map_view_event(ev)
        if click is None:
            return False
        return self._doppler.end_trace_stroke(click[0], click[1])

    def finish_calibration(self) -> bool:
        return False

    @property
    def is_calibration_active(self) -> bool:
        return self._calibration_active

    def start_linear_caliper_for(self, label: str) -> bool:
        self._caliper_sequence = []
        self._caliper_sequence_size = 0
        return self._begin_linear_caliper(label)

    def activate_linear_caliper(self) -> bool:
        """Start (or restart) click-click caliper for the next Dist label."""
        self._clear_calibration_caliper()
        return self.activate_generic_dist_caliper() is not None

    @_prof
    def start_linear_caliper_sequence(self, labels: tuple[str, ...]) -> bool:
        if not labels:
            return False
        self._caliper_sequence = list(labels[1:])
        self._caliper_sequence_size = len(labels)
        return self._begin_linear_caliper(labels[0])

    def _begin_linear_caliper(self, label: str) -> bool:
        self._clear_linear_caliper_graphics()
        self._clear_calibration_caliper()
        if self._current_frame is None:
            return False
        self._set_caliper_label(label)
        self._linear_caliper_active = True
        self._linear_caliper_start = None
        self._measurement_label.setText(tr("viewer.linear_caliper_click_start", label=label))
        return True

    def cycle_caliper_label(self) -> None:
        self._caliper_label_index = (self._caliper_label_index + 1) % len(self._caliper_labels)
        label = self._current_caliper_label()
        if not self._linear_caliper_active:
            self._measurement_label.setText(f"{label}: —")
            return
        self._linear_caliper_start = None
        self._clear_linear_caliper_graphics()
        self._measurement_label.setText(tr("viewer.linear_caliper_click_start", label=label))

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

    def start_generic_area_contour(self) -> bool:
        """Closed polygon planimeter (Площадь1, Площадь2, …)."""
        if not self._start_contour_drawing(
            mode_kind="closed",
            pen=self._contour_pen_manual,
            phase="GEN",
            view="A4C",
            chamber=GENERIC_AREA_CHAMBER,
        ):
            return False
        self._measurement_label.setText(
            tr("viewer.area_contour_prompt")
        )
        return True

    def start_generic_volume_contour(self) -> bool:
        """Closed polygon → Simpson volume (Объем1, Объем2, …)."""
        if not self._start_contour_drawing(
            mode_kind="closed",
            pen=self._contour_pen_manual,
            phase="GEN",
            view="A4C",
            chamber=GENERIC_VOLUME_CHAMBER,
        ):
            return False
        self._measurement_label.setText(
            tr("viewer.volume_contour_prompt")
        )
        return True

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
        self._active_apex_landmark = None
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
        self._upsert_stored_contour(self._tag_contour_instance(contour))
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
            self._active_apex_landmark = click
            self._update_active_contour_item()
            if self._contour_mode_kind == "model":
                finished = self._finish_model_contour(apex=click)
            else:
                finished = self._finish_manual_contour(apex=click)
            if not finished:
                self._contour_stage = "apex"
            return True
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
        except ValueError as exc:
            self.contour_landmark_rejected.emit(str(exc))
            return False
        self._clear_active_contour_drawing()
        self.set_contour_from_domain(contour)
        self.contour_completed.emit(contour)
        return True

    def refine_active_open_contour(self) -> tuple[bool, str]:
        """Smooth manual/model LV open-arc nodes on the current frame (R key)."""
        if self._current_frame is None:
            return False, ""
        frame_index = self._contour_frame_index()
        instance_uid = self._current_instance_uid()
        for contour_index, contour in enumerate(self._contours):
            if (
                contour.source not in {"manual", "model", "ai"}
                or not contour.is_open_arc
                or contour.mitral_annulus is None
                or contour.frame_index != frame_index
                or (
                    instance_uid is not None
                    and contour.sop_instance_uid is not None
                    and contour.sop_instance_uid != instance_uid
                )
            ):
                continue
            refined, mode = refine_open_arc_contour(
                self._current_frame,
                contour,
                display_levels=self._effective_display_levels(),
            )
            self._contours[contour_index] = refined
            self._upsert_stored_contour(refined)
            self._render_contours_for_current_frame()
            self._refresh_frame_overlays()
            if not self._syncing_state:
                self.contours_changed.emit(self.contours())
            return True, mode
        return False, ""

    def refine_active_model_contour(self) -> tuple[bool, str]:
        """Backward-compatible alias for refine_active_open_contour."""
        return self.refine_active_open_contour()

    def _finish_manual_contour(self, *, apex: tuple[float, float]) -> bool:
        if self._active_mitral_annulus is None:
            return False

        septal, lateral = self._active_mitral_annulus
        chamber = self._active_contour_chamber.upper()
        if chamber in {"LV", "LA", "RA", "RV"}:
            try:
                contour = fit_contour_from_landmarks(
                    septal=septal,
                    lateral=lateral,
                    apex=apex,
                    phase=self._active_contour_phase or "ED",
                    view=self._active_contour_view,
                    chamber=chamber,
                )
            except ValueError as exc:
                self.contour_landmark_rejected.emit(str(exc))
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
        apex_landmark = self._active_arc_points[0] if self._active_arc_points else None
        contour = Contour(
            phase=self._active_contour_phase or "GEN",
            view=self._active_contour_view,
            chamber=self._active_contour_chamber,
            mitral_annulus=self._active_mitral_annulus,
            apex_landmark=apex_landmark,
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

        chamber = self._active_contour_chamber
        chamber_key = chamber.upper()
        measurement_label = None
        if chamber_key == GENERIC_AREA_CHAMBER:
            measurement_label = next_area_label(tuple(self._stored_contours))
        elif chamber_key == GENERIC_VOLUME_CHAMBER:
            measurement_label = next_volume_label(tuple(self._stored_contours))

        contour = Contour(
            phase=self._active_contour_phase or "GEN",
            view=self._active_contour_view,
            chamber=chamber,
            points=list(self._active_arc_points),
            frame_index=self._contour_frame_index(),
            measurement_label=measurement_label,
        )
        self._clear_active_contour_drawing()
        self.set_contour_from_domain(contour)
        self.contour_completed.emit(contour)
        return True

    def cancel_active_tool(self) -> None:
        if self._caliper_drag_active:
            self._finish_caliper_node_drag(cancel=True)
            return
        if self._mmode_cal_step is not None:
            self._mmode_cal_step = None
            self._mmode_roi_corner1 = None
            self._mmode_pending_roi = None
            self._clear_crosshair()
            return
        if self._doppler_cal_step is not None:
            self._doppler_cal_step = None
            self._doppler_roi_corner1 = None
            self._doppler_pending_roi = None
            self._doppler_pending_baseline_y = None
            return
        if self._doppler.cancel_active_tool():
            return
        if self._active_contour_item is not None:
            self._clear_active_contour_drawing()
            return
        if self._calibration_active:
            self._clear_calibration_caliper()
            self._clear_crosshair()
            return
        self._clear_linear_caliper()
        self._clear_crosshair()

    def contours(self) -> list[Contour]:
        return list(self._stored_contours)

    def get_lv_contour(self) -> Contour | None:
        """Return the first LV contour, or None if no LV contour exists."""
        for contour in self._stored_contours:
            if contour.chamber == "LV":
                return contour
        return None

    def show_speckle_result(self, result: object) -> None:
        """Display speckle tracking overlay from StrainResult."""
        from echo_personal_tool.domain.models.speckle import StrainResult
        if not isinstance(result, StrainResult):
            return
        self._speckle_result = result
        self._refresh_speckle_overlay_for_current_frame()
        self._speckle_overlay.show()

    def _refresh_speckle_overlay_for_current_frame(self) -> None:
        """Update kernel markers for the currently displayed frame."""
        from echo_personal_tool.domain.models.speckle import StrainResult

        result = self._speckle_result
        if not isinstance(result, StrainResult):
            return

        frame = self._current_frame_index()
        if frame is None:
            return

        ed_index = result.ed_index
        es_index = result.es_index
        phase_lo = result.tracking_window_start
        phase_hi = result.tracking_window_end
        if phase_hi < phase_lo:
            phase_lo = min(ed_index, es_index)
            phase_hi = max(ed_index, es_index)
        ncc_threshold = result.ncc_threshold

        if result.tracked_positions_all is None or result.ncc_all_frames is None:
            es_positions = result.tracked_es_positions
            ed_positions = result.tracked_ed_positions
            ncc = result.es_ncc_scores or result.last_ncc_scores
            valid = result.es_valid_mask or result.last_valid_mask
            if result.kernels and es_positions is not None:
                self._speckle_overlay.show_kernels(
                    result.kernels, valid, ncc, positions=es_positions
                )
            if ed_positions is not None and es_positions is not None:
                endo_mask = [i for i, k in enumerate(result.kernels) if k.layer == "endo"]
                if endo_mask:
                    self._speckle_overlay.show_ed_es_displacements(
                        ed_positions[endo_mask], es_positions[endo_mask]
                    )
            if result.kernels and result.per_kernel_longitudinal is not None and es_positions is not None:
                self._speckle_overlay.show_strain_color_map(
                    result.kernels, result.per_kernel_longitudinal, positions=es_positions
                )
            self._speckle_overlay.show_phase_contours(result.ed_contour, result.es_contour)
            return

        has_tracked = (
            0 <= frame < result.tracked_positions_all.shape[0]
            and np.any(np.isfinite(result.tracked_positions_all[frame, :, 0]))
        )
        if not (phase_lo <= frame <= phase_hi) or not has_tracked:
            self._speckle_overlay.show_kernels([], None, None)
            self._speckle_overlay.show_ed_es_displacements(None, None)
            self._speckle_overlay.show_strain_color_map([], np.array([]))
            self._speckle_overlay.show_phase_contours(result.ed_contour, result.es_contour)
            return

        positions = result.tracked_positions_all[frame]
        ncc = result.ncc_all_frames[frame]
        valid = np.isfinite(ncc) & (ncc >= ncc_threshold)

        if result.kernels:
            self._speckle_overlay.show_kernels(
                result.kernels, valid, ncc, positions=positions
            )

        endo_indices = [i for i, k in enumerate(result.kernels) if k.layer == "endo"]
        if endo_indices and frame != ed_index:
            ed_positions = result.tracked_positions_all[ed_index]
            self._speckle_overlay.show_ed_es_displacements(
                ed_positions[endo_indices],
                positions[endo_indices],
            )
        else:
            self._speckle_overlay.show_ed_es_displacements(None, None)

        if endo_indices:
            endo_pts = positions[endo_indices, :]
            sorted_endo = sorted(
                endo_indices, key=lambda i: result.kernels[i].node_index
            )
            sorted_pts = positions[sorted_endo, :]
            self._speckle_overlay.show_myocardial_zone_dynamic(sorted_pts)

            ed_positions = result.tracked_positions_all[ed_index]
            ed_sorted = ed_positions[sorted_endo, :]
            self._speckle_overlay.show_phase_contours(ed_sorted, sorted_pts)

        if result.kernels and result.per_kernel_longitudinal is not None:
            self._speckle_overlay.show_strain_color_map(
                result.kernels,
                result.per_kernel_longitudinal,
                positions=positions,
            )
        else:
            self._speckle_overlay.show_strain_color_map([], np.array([]))

    def clear_speckle_overlay(self) -> None:
        self._speckle_result = None
        self._speckle_overlay.clear()
        self._speckle_overlay.hide()

    def pending_ai_review_contour(self) -> Contour | None:
        frame_index = self._contour_frame_index()
        instance_uid = self._current_instance_uid()
        if frame_index is None:
            return None
        for contour in self._stored_contours:
            if (
                contour.source == "ai"
                and contour.review_pending
                and contour.frame_index == frame_index
                and (
                    instance_uid is None
                    or contour.sop_instance_uid is None
                    or contour.sop_instance_uid == instance_uid
                )
            ):
                return contour
        return None

    def discard_pending_ai_contour(self) -> bool:
        pending = self.pending_ai_review_contour()
        if pending is None:
            return False
        self._stored_contours = [
            c
            for c in self._stored_contours
            if not (
                c.source == "ai"
                and c.review_pending
                and c.frame_index == pending.frame_index
                and c.phase == pending.phase
                and c.view == pending.view
            )
        ]
        self._render_contours_for_current_frame()
        return True

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

    def set_scroll_debounce_ms(self, ms: int) -> None:
        self._scroll_debounce_ms = max(0, ms)

    def _emit_pending_scroll(self) -> None:
        if self._pending_scroll_index is None:
            return
        index = self._pending_scroll_index
        self._pending_scroll_index = None
        self.scroll_frame_selected.emit(index)

    def _handle_wheel(self, ev) -> bool:
        if self._current_state is None:
            return False
        if hasattr(ev, "angleDelta"):
            delta_y = ev.angleDelta().y()
        elif hasattr(ev, "delta"):
            delta_y = ev.delta()
        else:
            return False
        if delta_y == 0:
            return False

        # Ctrl+Scroll → zoom
        modifiers = ev.modifiers() if hasattr(ev, "modifiers") else Qt.KeyboardModifier.NoModifier
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            return self._handle_ctrl_wheel(ev, delta_y)

        # Plain scroll → frame navigation
        if self._current_state.total_frames <= 1:
            return False
        step = -1 if delta_y > 0 else 1
        current = (
            self._pending_scroll_index
            if self._pending_scroll_index is not None
            else self._current_state.current_frame_index
        )
        total = self._current_state.total_frames
        new_index = (current + step) % total
        if new_index == current:
            return False
        ev.accept()
        self._pending_scroll_index = new_index
        if self._scroll_debounce_ms <= 0:
            self._emit_pending_scroll()
            return True
        self._scroll_debounce_timer.start(self._scroll_debounce_ms)
        return True

    def _handle_ctrl_wheel(self, ev, delta_y: int) -> bool:
        if self._current_frame is None:
            return False

        zoom_step = 1.1
        if delta_y > 0:
            new_factor = self._zoom_factor * zoom_step
        else:
            new_factor = self._zoom_factor / zoom_step

        # Clamp zoom to [0.1, 20.0]
        new_factor = max(0.1, min(20.0, new_factor))
        if abs(new_factor - self._zoom_factor) < 1e-6:
            return False

        # Get mouse position in view coordinates
        if hasattr(ev, "position"):
            mouse_pos = ev.position()
            mx, my = mouse_pos.x(), mouse_pos.y()
        elif hasattr(ev, "pos"):
            p = ev.pos()
            mx, my = p.x(), p.y()
        else:
            # Fallback: zoom around viewport center
            viewport = self._graphics.viewport()
            mx = viewport.width() / 2.0
            my = viewport.height() / 2.0

        # Convert mouse pixel position to scene (data) coordinates
        scene_pos = self._graphics.mapToScene(mx, my)
        data_x = scene_pos.x()
        data_y = scene_pos.y()

        h, w = self._current_frame.shape[:2]
        old_factor = self._zoom_factor
        self._zoom_factor = new_factor
        self._zoom_mode = "custom"  # Ctrl+Scroll enters custom zoom

        # Compute visible range centered on mouse, scaled by new_factor
        view_w = self._graphics.viewport().width() / self._graphics.devicePixelRatioF()
        view_h = self._graphics.viewport().height() / self._graphics.devicePixelRatioF()

        # Portion of image visible at 1x is (view_w, view_h); at zoom factor it's (view_w/f, view_h/f)
        half_w = (view_w / 2.0) / new_factor
        half_h = (view_h / 2.0) / new_factor

        # Shift so that data_x, data_y stays under the mouse
        # Ratio of mouse position within viewport
        if view_w > 0 and view_h > 0:
            ratio_x = mx / view_w
            ratio_y = my / view_h
        else:
            ratio_x = 0.5
            ratio_y = 0.5

        cx = data_x - half_w * (2 * ratio_x - 1)
        cy = data_y - half_h * (2 * ratio_y - 1)

        self._view.setRange(
            xRange=(cx - half_w, cx + half_w),
            yRange=(cy - half_h, cy + half_h),
            padding=0,
        )
        ev.accept()
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
            calibration_banner = self._frame_overlay_lines == [tr(CALIBRATION_PROMPT_OVERLAY_KEY)]
            calibration_ok = self._frame_overlay_lines == [tr(CALIBRATION_SUCCESS_OVERLAY_KEY)]
            if calibration_banner:
                self._overlay_label.setStyleSheet(_CALIBRATION_OVERLAY_STYLE)
                self._overlay_label.setMinimumWidth(360)
            elif calibration_ok:
                self._overlay_label.setStyleSheet(_CALIBRATION_SUCCESS_STYLE)
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
        self._caliper_sequence_size = 0
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
        if self._active_caliper_label_item is not None:
            self._view.removeItem(self._active_caliper_label_item)
            self._active_caliper_label_item = None

    def _clear_calibration_caliper(self) -> None:
        self._calibration_active = False
        self._calibration_start_y = None
        self._mmode_time_start_x = None
        self._calibration_kind = None
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
        if self._calibration_h_guide_start_item is not None:
            self._view.removeItem(self._calibration_h_guide_start_item)
            self._calibration_h_guide_start_item = None
        if self._calibration_h_guide_end_item is not None:
            self._view.removeItem(self._calibration_h_guide_end_item)
            self._calibration_h_guide_end_item = None

    def _ensure_calibration_horizontal_guides(self) -> None:
        pen = pg.mkPen("#9e9e9e", width=1, style=Qt.PenStyle.DashLine)
        if self._calibration_h_guide_start_item is None:
            self._calibration_h_guide_start_item = pg.PlotDataItem(pen=pen)
            self._calibration_h_guide_start_item.setZValue(24)
            self._calibration_h_guide_start_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self._calibration_h_guide_start_item.setAcceptHoverEvents(False)
            self._view.addItem(self._calibration_h_guide_start_item)
        if self._calibration_h_guide_end_item is None:
            self._calibration_h_guide_end_item = pg.PlotDataItem(pen=pen)
            self._calibration_h_guide_end_item.setZValue(24)
            self._calibration_h_guide_end_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self._calibration_h_guide_end_item.setAcceptHoverEvents(False)
            self._view.addItem(self._calibration_h_guide_end_item)

    def _update_calibration_horizontal_guides(self, end_y: float) -> None:
        if not self._calibration_active or self._calibration_start_y is None:
            return
        if self._calibration_kind == "mmode_time":
            return
        self._ensure_calibration_horizontal_guides()
        assert self._calibration_h_guide_start_item is not None
        assert self._calibration_h_guide_end_item is not None
        start_y = float(self._calibration_start_y)
        end_y = float(end_y)
        x_start = float(self._calibration_x)
        if self._current_frame is None:
            return
        x_end = float(self._current_frame.shape[1] - 1)
        if x_start >= x_end:
            self._calibration_h_guide_start_item.setData([], [])
            self._calibration_h_guide_end_item.setData([], [])
            return
        self._calibration_h_guide_start_item.setData(
            [x_start, x_end],
            [start_y, start_y],
        )
        self._calibration_h_guide_end_item.setData(
            [x_start, x_end],
            [end_y, end_y],
        )

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
            instance_uid = self._current_instance_uid()
            visible = [
                contour
                for contour in self._stored_contours
                if contour.frame_index == frame_index
                and (
                    instance_uid is None
                    or contour.sop_instance_uid is None
                    or contour.sop_instance_uid == instance_uid
                )
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
        instance_uid = contour.sop_instance_uid
        for index, existing in enumerate(self._stored_contours):
            if (
                existing.phase.casefold() == contour.phase.casefold()
                and existing.view.casefold() == contour.view.casefold()
                and existing.chamber.casefold() == contour.chamber.casefold()
                and existing.frame_index == contour.frame_index
                and existing.sop_instance_uid == instance_uid
            ):
                return index
        return None

    def _current_instance_uid(self) -> str | None:
        if self._current_state is None or self._current_state.instance is None:
            return None
        return self._current_state.instance.sop_instance_uid

    def _tag_contour_instance(self, contour: Contour) -> Contour:
        instance_uid = self._current_instance_uid()
        if instance_uid is None or contour.sop_instance_uid == instance_uid:
            return contour
        contour.sop_instance_uid = instance_uid
        return contour

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
        self._active_apex_landmark = None
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
            if contour.review_pending:
                return self._contour_pen_ai_pending
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
        if is_planimeter_polygon(contour) or (
            contour.is_open_arc and len(points) >= 2
        ):
            if closed and points:
                points = [*points, points[0]]
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
        if len(contour.points) < 2:
            return

        last_index = len(contour.points) - 1
        if self._drag_session is not None:
            contour_index, _, _, grab_index, _ = self._drag_session
            if 0 <= contour_index < len(self._contours) and self._contours[contour_index] is contour:
                if grab_index == 0:
                    septal = (float(contour.points[0][0]), float(contour.points[0][1]))
                    lateral = contour.mitral_annulus[1]
                    contour.mitral_annulus = (septal, lateral)
                    self._refresh_mitral_annulus_line(contour_index)
                    return
                if grab_index == last_index:
                    septal = contour.mitral_annulus[0]
                    lateral = (
                        float(contour.points[last_index][0]),
                        float(contour.points[last_index][1]),
                    )
                    contour.mitral_annulus = (septal, lateral)
                    self._refresh_mitral_annulus_line(contour_index)
                    return

        septal, lateral = contour.mitral_annulus
        contour.points[0] = septal
        contour.points[last_index] = lateral

    def _refresh_mitral_annulus_line(self, contour_index: int) -> None:
        if contour_index < 0 or contour_index >= len(self._contour_ma_items):
            return
        ma_item = self._contour_ma_items[contour_index]
        if ma_item is None or contour_index >= len(self._contours):
            return
        contour = self._contours[contour_index]
        if contour.mitral_annulus is None:
            return
        septal, lateral = contour.mitral_annulus
        ma_item.setData([septal[0], lateral[0]], [septal[1], lateral[1]])

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
        return self._contour_mode_active or self._linear_caliper_active or self._calibration_active

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

        last_index = len(contour.points) - 1
        if is_planimeter_polygon(contour):
            contour.points[session_grab] = (x, y)
            for idx, point in enumerate(contour.points):
                self._contour_nodes[contour_index][idx].setData([point[0]], [point[1]])
            self._refresh_rendered_contour_geometry(contour_index, during_drag=True)
            self._last_drag_apply_pos = rounded_cursor
            self._drag_session = (contour_index, x, y, session_grab, locked_tier)
            self._flush_drag_paint()
            return True

        if contour.is_open_arc and session_grab in (0, last_index):
            contour.points[session_grab] = (x, y)
            self._snap_open_arc_endpoints(contour)
            for idx, point in enumerate(contour.points):
                self._contour_nodes[contour_index][idx].setData([point[0]], [point[1]])
            self._refresh_rendered_contour_geometry(contour_index, during_drag=True)
            self._last_drag_apply_pos = rounded_cursor
            self._drag_session = (contour_index, x, y, session_grab, locked_tier)
            self._flush_drag_paint()
            return True

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
        locked_tier = self._drag_session[4] if self._drag_session is not None else 1
        contour.refine_step = 0
        contour.refine_locked_indices = ()
        if contour.is_open_arc:
            num_nodes = contour.num_nodes or DEFAULT_NODE_COUNT
            if contour.mitral_annulus is not None and len(contour.points) >= 2:
                septal = (float(contour.points[0][0]), float(contour.points[0][1]))
                lateral = (
                    float(contour.points[-1][0]),
                    float(contour.points[-1][1]),
                )
                contour.mitral_annulus = (septal, lateral)
                apex = contour.apex_landmark or apex_point(contour.points, contour.mitral_annulus)
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
            weights = self._locked_drag_weights(contour, grab_index, locked_tier)
            self._apply_magnetic_snap_to_contour(
                contour_index,
                weights,
                grab_index=grab_index,
            )
            for idx, point in enumerate(contour.points):
                self._contour_nodes[contour_index][idx].setData([point[0]], [point[1]])
        self._end_drag_overlay(contour_index)
        self._refresh_rendered_contour_geometry(contour_index)
        self._refresh_mitral_annulus_line(contour_index)
        self._clear_contour_node_highlights(contour_index)
        self._clear_drag_session()
        self._clear_contour_hover()
        self._upsert_stored_contour(contour)
        self.contours_changed.emit(self.contours())
        current_frame = self._contour_frame_index()
        if contour.is_open_arc and contour.frame_index == current_frame:
            self._refresh_frame_overlays()
        elif is_planimeter_polygon(contour) and contour.frame_index == current_frame:
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
            if not contour.is_open_arc and is_planimeter_polygon(contour) and contour.points:
                closed_points = [*contour.points, contour.points[0]]
                x_values = [point[0] for point in closed_points]
                y_values = [point[1] for point in closed_points]
            else:
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

    def _auto_calibration_ok(self) -> bool:
        if self._current_state is None or self._current_state.instance is None:
            return False
        if self._current_state.instance.media_format == "dicom":
            return False
        _, spacing_calibrated = self._effective_pixel_spacing()
        return spacing_calibrated and self._auto_calibration_succeeded

    def show_calibration_ok_overlay(self) -> None:
        self._auto_calibration_succeeded = True
        self._refresh_frame_overlays()
        if self._calibration_ok_timer is not None:
            self._calibration_ok_timer.stop()
        self._calibration_ok_timer = QTimer(self)
        self._calibration_ok_timer.setSingleShot(True)
        self._calibration_ok_timer.timeout.connect(self._fade_out_calibration_ok)
        self._calibration_ok_timer.start(4000)

    def _fade_out_calibration_ok(self) -> None:
        self._auto_calibration_succeeded = False
        self._refresh_frame_overlays()

    def _refresh_frame_overlays(self, *, extra_lines: tuple[str, ...] = ()) -> None:
        self.clear_frame_overlay()
        if self._needs_calibration_prompt():
            self.append_frame_overlay(tr(CALIBRATION_PROMPT_OVERLAY_KEY))
        elif self._auto_calibration_ok():
            self.append_frame_overlay(tr(CALIBRATION_SUCCESS_OVERLAY_KEY))
        frame_index = self._contour_frame_index()
        spacing, spacing_calibrated = self._effective_pixel_spacing()
        if frame_index is not None:
            for contour in self._stored_contours:
                if contour.frame_index != frame_index:
                    continue
                chamber = contour.chamber.upper()
                if chamber in {GENERIC_AREA_CHAMBER, GENERIC_VOLUME_CHAMBER}:
                    line = format_planimeter_overlay_line(
                        contour,
                        spacing,
                        spacing_calibrated=spacing_calibrated,
                    )
                    if line:
                        self.append_frame_overlay(line)
                    continue
                if contour.is_open_arc:
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
        frame_key = measurement.frame_index if measurement.frame_index is not None else -1
        return measurement.label, frame_key

    def _linear_measurements_for_frame(self, frame_index: int) -> list[LinearMeasurement]:
        measurements: list[LinearMeasurement] = []
        for measurement in self._stored_linear_measurements.values():
            if measurement.frame_index is None or measurement.frame_index == frame_index:
                measurements.append(measurement)
        return measurements

    @_prof
    def _clear_persistent_linear_calipers(self) -> None:
        for item in self._persistent_linear_graphics:
            self._view.removeItem(item[0])
            self._view.removeItem(item[1])
            self._view.removeItem(item[2])
        self._persistent_linear_graphics.clear()
        for item in self._persistent_caliper_label_items:
            self._view.removeItem(item)
        self._persistent_caliper_label_items.clear()

    @_prof
    def _render_persistent_linear_calipers(self) -> None:
        self._clear_persistent_linear_calipers()
        frame_index = self._contour_frame_index()
        if frame_index is None:
            return
        for measurement in self._linear_measurements_for_frame(frame_index):
            if measurement.start is None or measurement.end is None:
                continue
            key = (measurement.label, measurement.frame_index if measurement.frame_index is not None else -1)
            line_item, start_node, end_node = self._create_linear_graphics_items(
                measurement.start,
                measurement.end,
                key,
            )
            self._persistent_linear_graphics.append((line_item, start_node, end_node, key))
            if self._show_caliper_inline_labels:
                self._update_caliper_label_graphics(
                    measurement.start, measurement.end,
                    color="#29b6f6", is_preview=False,
                )

    def _create_linear_graphics_items(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        caliper_key: tuple[str, int],
    ) -> tuple[pg.PlotDataItem, _CaliperNodeItem, _CaliperNodeItem]:
        pen = self._caliper_pen("#29b6f6")
        line_item = pg.PlotDataItem(pen=pen)
        line_item.setZValue(24)
        line_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        line_item.setAcceptHoverEvents(False)
        line_item.setData([start[0], end[0]], [start[1], end[1]])
        self._view.addItem(line_item)
        start_node = _CaliperNodeItem(
            self, caliper_key, 0, start, pen,
        )
        start_node.setZValue(30)
        self._view.addItem(start_node)
        end_node = _CaliperNodeItem(
            self, caliper_key, 1, end, pen,
        )
        end_node.setZValue(30)
        self._view.addItem(end_node)
        return line_item, start_node, end_node

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

    def _preview_open_arc_points(
        self,
        septal: tuple[float, float],
        lateral: tuple[float, float],
        apex: tuple[float, float],
    ) -> list[tuple[float, float]]:
        from echo_personal_tool.domain.services.mbs_lite_service import fit_contour_from_landmarks

        try:
            contour = fit_contour_from_landmarks(
                septal=septal,
                lateral=lateral,
                apex=apex,
                phase=self._active_contour_phase or "ED",
                view=self._active_contour_view,
                chamber=self._active_contour_chamber,
            )
        except ValueError:
            return []
        return list(contour.points)

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
            if self._active_apex_landmark is not None:
                markers.append(self._active_apex_landmark)
                spline_points = self._preview_open_arc_points(
                    septal,
                    lateral,
                    self._active_apex_landmark,
                )
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
                spline_points = closed
            else:
                spline_points = markers
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
        width = self._current_frame.shape[1]
        x = max(0.0, min(float(click[0]), float(width - 1)))
        y = max(0.0, min(float(click[1]), float(height - 1)))

        if self._calibration_kind == "mmode_time":
            if self._mmode_time_start_x is None:
                self._mmode_time_start_x = x
                self._calibration_start_y = y
                self._update_mmode_time_preview(x, x, y)
                return True
            length_px = abs(x - float(self._mmode_time_start_x))
            if length_px >= 1.0:
                self._prompt_mmode_time_span(length_px)
            return True

        y = max(0.0, min(float(click[1]), float(height - 1)))
        y = snap_y_to_nearest_tick(y, self._depth_tick_y_positions, radius_px=self._calibration_tick_snap_radius_px)
        if self._calibration_start_y is None:
            self._calibration_start_y = y
            self._update_calibration_preview(y, y)
            self._update_calibration_horizontal_guides(y)
            if self._calibration_kind in {"spectral", "doppler_velocity"}:
                self._measurement_label.setText(tr("viewer.spectral_click_end"))
            else:
                self._measurement_label.setText(tr("viewer.calibration_click_end"))
            return True

        length_px = abs(y - self._calibration_start_y)
        if length_px >= 1.0:
            if self._calibration_kind == "mmode_depth":
                self._prompt_mmode_depth_calibration(length_px)
            elif self._calibration_kind in {"spectral", "doppler_velocity"}:
                self._prompt_spectral_velocity_span(length_px)
            else:
                self._prompt_calibration_distance(length_px)
        return True

    def _prompt_spectral_velocity_span(self, length_px: float) -> None:
        default_span = self._doppler_cal_kind.default_velocity_span_cm_s
        span_cm_s, accepted = QInputDialog.getDouble(
            self,
            tr("viewer.calibration_spectral_title"),
            tr("viewer.calibration_spectral_prompt"),
            default_span,
            1.0,
            1000.0,
            0,
        )
        self._clear_calibration_caliper()
        if not accepted or self._current_frame is None:
            return

        if self._doppler_pending_roi is not None and self._doppler_pending_baseline_y is not None:
            roi = self._doppler_pending_roi
            if length_px > 0.0:
                velocity_span = span_cm_s * (roi.height / length_px)
            else:
                velocity_span = span_cm_s
            state = calibration_from_roi_and_baseline(
                roi,
                self._doppler_pending_baseline_y,
                velocity_span_cm_s=velocity_span,
                kind=self._doppler_cal_kind,
            )
            self.apply_doppler_calibration_state(state)
            self._doppler_pending_roi = None
            self._doppler_pending_baseline_y = None
            self._measurement_label.setText(tr("viewer.doppler_calibration_complete"))
            self.spectral_calibration_completed.emit(velocity_span)
            return

        height, width = self._current_frame.shape[:2]
        mapping = DopplerAxisMapping.from_frame_size(
            width,
            height,
            velocity_span_cm_s=span_cm_s,
        )
        self._doppler.set_axis_mapping(mapping)
        self._doppler_axis_calibrated = False
        if not self._syncing_state:
            self.spectral_calibration_completed.emit(span_cm_s)

    def _ensure_calibration_graphics(self) -> None:
        if self._calibration_line_item is None:
            pen = self._caliper_pen("#29b6f6")
            self._calibration_line_item = pg.PlotDataItem(pen=pen)
            self._calibration_line_item.setZValue(25)
            self._calibration_line_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self._calibration_line_item.setAcceptHoverEvents(False)
            self._view.addItem(self._calibration_line_item)
        if self._calibration_marker_item is None:
            marker_pen = self._caliper_pen("#29b6f6")
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

    def _update_mmode_time_preview(self, x_start: float, x_end: float, y: float) -> None:
        self._ensure_calibration_graphics()
        assert self._calibration_line_item is not None
        assert self._calibration_marker_item is not None
        self._calibration_line_item.setData([x_start, x_end], [y, y])
        self._calibration_marker_item.setData([x_start, x_end], [y, y])

    def _prompt_mmode_time_span(self, length_px: float) -> None:
        span_ms, accepted = QInputDialog.getDouble(
            self,
            "M-mode time scale",
            tr("viewer.mmode_time_prompt"),
            1000.0,
            1.0,
            10000.0,
            0,
        )
        self._clear_calibration_caliper()
        if not accepted or length_px <= 0.0:
            return
        time_per_pixel_ms = span_ms / length_px
        if not self._syncing_state:
            self.mmode_time_calibration_completed.emit(float(time_per_pixel_ms))

    def _prompt_mmode_depth_calibration(self, length_px: float) -> None:
        known_cm, accepted = QInputDialog.getDouble(
            self,
            tr("viewer.mmode_calibration_title"),
            tr("viewer.mmode_depth_prompt"),
            1.0,
            0.01,
            100.0,
            2,
        )
        self._clear_calibration_caliper()
        if not accepted or self._mmode_pending_roi is None or length_px <= 0.0:
            self._mmode_pending_roi = None
            return
        known_mm = known_cm * 10.0
        state = MmodeCalibrationState(
            roi=self._mmode_pending_roi,
            vertical_mm_per_pixel=known_mm / length_px,
        )
        self._mmode_pending_roi = None
        self.apply_mmode_calibration_state(state)

    def _prompt_calibration_distance(self, length_px: float) -> None:
        known_cm, accepted = QInputDialog.getDouble(
            self,
            tr("viewer.calibration_depth_title"),
            tr("viewer.calibration_distance_prompt"),
            5.0,
            0.01,
            1000.0,
            2,
        )
        self._clear_calibration_caliper()
        if not accepted:
            if self._needs_calibration_prompt():
                self.start_calibration_caliper()
            return
        known_mm = known_cm * 10.0
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

        if (
            self._current_caliper_label() in self._vertical_caliper_labels
            and self._mmode_calibration_state is not None
            and not self._mmode_calibration_state.roi.contains(click[0], click[1])
        ):
            self._measurement_label.setText(tr("viewer.tapse_click_in_mmode"))
            return True

        if self._linear_caliper_start is None:
            self._linear_caliper_start = click
            self._update_linear_caliper_preview(click, click)
            self._measurement_label.setText(tr("viewer.linear_caliper_click_end", label=self._current_caliper_label()))
            return True

        start = self._linear_caliper_start
        end = self._constrain_linear_endpoint(start, click)
        self._commit_linear_measurement_from_endpoints(start, end)
        return True

    def _constrain_linear_endpoint(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        label: str | None = None,
    ) -> tuple[float, float]:
        if (label or self._current_caliper_label()) in self._vertical_caliper_labels:
            end_y = end[1]
            if self._mmode_calibration_state is not None:
                roi = self._mmode_calibration_state.roi
                end_y = max(roi.y0, min(end_y, roi.y1))
            return (start[0], end_y)
        return end

    def _pixel_spacing_for_linear_label(
        self,
        label: str,
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> tuple[float, float] | None:
        if label in self._vertical_caliper_labels:
            return None
        panels = self._resolve_frame_panels()
        if panels is not None and panels.b_mode is not None:
            mid_x = (start[0] + end[0]) / 2.0
            mid_y = (start[1] + end[1]) / 2.0
            b_panel = panels.b_mode
            if b_panel.contains(mid_x, mid_y):
                row = b_panel.vertical_mm_per_pixel
                col = b_panel.horizontal_mm_per_pixel
                if row is not None and col is not None:
                    return (row, col)
                if row is not None:
                    return (row, row)
        if self._current_state is not None:
            return self._current_state.effective_pixel_spacing
        return None

    def start_atrial_area_length_contour(
        self,
        *,
        chamber: str,
        view: str = "A4C",
        phase: str = "ES",
    ) -> bool:
        if not self._start_contour_drawing(
            mode_kind="closed",
            pen=self._contour_pen_manual,
            phase=phase,
            view=view,
            chamber=chamber,
        ):
            return False
        length_label = "LAL" if chamber.upper() == "LA" else "RA"
        self.append_frame_overlay(
            f"{chamber} area-length {view}: closed contour, then {length_label} caliper"
        )
        return True

    def start_mmode_time_calibration(self) -> bool:
        if self._current_frame is None:
            return False
        self.cancel_active_tool()
        self._clear_calibration_caliper()
        self._calibration_kind = "mmode_time"
        self._calibration_active = True
        self._mmode_time_start_x = None
        self._calibration_start_y = None
        return True

    def _ensure_linear_caliper_graphics(self) -> None:
        if self._linear_caliper_line_item is None:
            pen = self._caliper_pen("#ffb300")
            self._linear_caliper_line_item = pg.PlotDataItem(pen=pen)
            self._linear_caliper_line_item.setZValue(25)
            self._linear_caliper_line_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self._linear_caliper_line_item.setAcceptHoverEvents(False)
            self._view.addItem(self._linear_caliper_line_item)
        if self._linear_caliper_marker_item is None:
            marker_pen = self._caliper_pen("#ffb300")
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
        self._update_caliper_label_graphics(start, end, color="#ffb300", is_preview=True)

    def _update_caliper_label_graphics(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        *,
        color: str,
        is_preview: bool,
    ) -> None:
        measurement = self._linear_measurement_from_endpoints(
            start, end, self._current_caliper_label()
        )
        text = inline_caliper_text(measurement, length_unit=self._length_display_unit)
        layout = compute_caliper_label_layout(
            start, end,
            vertical_labels=self._vertical_caliper_labels,
            label=measurement.label,
        )
        if is_preview:
            if self._active_caliper_label_item is None:
                self._active_caliper_label_item = pg.TextItem(
                    color=color, anchor=(0.5, 0.5)
                )
                self._active_caliper_label_item.setZValue(27)
                self._view.addItem(self._active_caliper_label_item)
            item = self._active_caliper_label_item
        else:
            item = pg.TextItem(color=color, anchor=(0.5, 0.5))
            item.setZValue(27)
            item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            item.setAcceptHoverEvents(False)
            self._view.addItem(item)
            self._persistent_caliper_label_items.append(item)
        item.setText(text)
        item.setPos(layout.anchor_x + layout.offset_x, layout.anchor_y + layout.offset_y)
        item.setRotation(layout.angle_deg)

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
        if label in self._vertical_caliper_labels and self._mmode_calibration_state is not None:
            millimeter_length = abs(dy) * self._mmode_calibration_state.vertical_mm_per_pixel
        else:
            pixel_spacing = self._pixel_spacing_for_linear_label(label, start, end)
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
        self._measurement_label.setText(
            measurement.display_text(length_unit=self._length_display_unit)
        )

    def _update_linear_caliper_label_preview_from_state(self) -> None:
        if not self._linear_caliper_active:
            return
        if self._linear_caliper_start is None:
            label = self._current_caliper_label()
            self._measurement_label.setText(tr("viewer.linear_caliper_click_start", label=label))
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
        self._stored_linear_measurements[self._linear_measurement_key(measurement)] = measurement
        self._measurement_label.setText(
            measurement.display_text(length_unit=self._length_display_unit)
        )
        self._emit_stored_linear_measurements()
        self._render_persistent_linear_calipers()
        self._refresh_frame_overlays()
        self._linear_caliper_start = None
        self._clear_linear_caliper_graphics()
        if self._caliper_sequence:
            next_label = self._caliper_sequence.pop(0)
            # Chain: next segment starts where this one ended
            self._linear_caliper_start = end
            self._set_caliper_label(next_label)
            self._linear_caliper_active = True
            self._update_linear_caliper_preview(end, end)
            self._measurement_label.setText(tr("viewer.linear_caliper_click_end", label=next_label))
        else:
            self._linear_caliper_active = False
            if self._caliper_sequence_size > 1:
                self._caliper_sequence_size = 0
                if not self._syncing_state:
                    self.linear_caliper_sequence_completed.emit()

    def _emit_stored_linear_measurements(self) -> None:
        measurements = list(self._stored_linear_measurements.values())
        self.linear_measurements_changed.emit(measurements)

    # ── Caliper node drag (endpoint correction) ────────────────────

    def _begin_caliper_node_drag(
        self,
        caliper_key: tuple[str, int],
        endpoint_index: int,
        x: float,
        y: float,
    ) -> None:
        if self._linear_caliper_active:
            return
        measurement = self._stored_linear_measurements.get(caliper_key)
        if measurement is None:
            return
        self._caliper_drag_active = True
        self._caliper_drag_key = caliper_key
        self._caliper_drag_node = endpoint_index
        self._caliper_drag_original = measurement
        self._caliper_drag_persistent_items: list | None = None
        for item in self._persistent_linear_graphics:
            if len(item) >= 4 and item[3] == caliper_key:
                self._caliper_drag_persistent_items = item
                line_item, start_node, end_node, _ = item
                line_item.setPen(self._caliper_pen("#ffb300"))
                start_node.setPen(self._caliper_pen("#ffb300"))
                end_node.setPen(self._caliper_pen("#ffb300"))
                break

    def _apply_caliper_node_drag(self, x: float, y: float) -> None:
        if not self._caliper_drag_active or self._caliper_drag_key is None:
            return
        measurement = self._stored_linear_measurements.get(self._caliper_drag_key)
        if measurement is None:
            return
        if self._caliper_drag_node == 0:
            new_end = measurement.end
            new_start = self._constrain_linear_endpoint(
                new_end, (x, y), label=measurement.label,
            )
        else:
            new_start = measurement.start
            new_end = self._constrain_linear_endpoint(
                measurement.start, (x, y), label=measurement.label,
            )
        updated = self._linear_measurement_from_endpoints(
            new_start, new_end, measurement.label,
        )
        self._stored_linear_measurements[self._caliper_drag_key] = updated
        if self._caliper_drag_persistent_items is not None:
            line_item, start_node, end_node, _ = self._caliper_drag_persistent_items
            line_item.setData(
                [new_start[0], new_end[0]],
                [new_start[1], new_end[1]],
            )
            start_node.setData([new_start[0]], [new_start[1]])
            end_node.setData([new_end[0]], [new_end[1]])
        self._update_caliper_label_graphics(
            new_start, new_end, color="#ffb300", is_preview=True,
        )
        self._measurement_label.setText(
            updated.display_text(length_unit=self._length_display_unit)
        )
        self._update_results_overlay_for_caliper_drag(updated)

    def _finish_caliper_node_drag(self, *, cancel: bool = False) -> None:
        if not self._caliper_drag_active:
            return
        if cancel and self._caliper_drag_original is not None and self._caliper_drag_key is not None:
            self._stored_linear_measurements[self._caliper_drag_key] = self._caliper_drag_original
        if self._caliper_drag_persistent_items is not None:
            line_item, start_node, end_node, _ = self._caliper_drag_persistent_items
            line_item.show()
            start_node.show()
            end_node.show()
        self._caliper_drag_active = False
        self._caliper_drag_key = None
        self._caliper_drag_node = None
        self._caliper_drag_original = None
        self._caliper_drag_persistent_items = None
        self._clear_linear_caliper_graphics()
        self._emit_stored_linear_measurements()
        self._render_persistent_linear_calipers()
        self._refresh_frame_overlays()

    def _update_results_overlay_for_caliper_drag(self, measurement: "LinearMeasurement") -> None:
        if self._results_overlay_label is None:
            return
        lines: list[str] = []
        for m in self._stored_linear_measurements.values():
            lines.append(m.display_text(length_unit=self._length_display_unit))
        text = "\n".join(lines)
        self._results_overlay_label.setText(text)
        self._results_overlay_label.adjustSize()
        self._results_overlay_label.show()
        self._results_overlay_label.raise_()

    def _handle_caliper_drag_release(self, ev) -> bool:
        if not self._caliper_drag_active:
            return False
        if ev.button() == Qt.MouseButton.LeftButton:
            self._finish_caliper_node_drag()
            return True
        return False

    def _select_caliper(self, caliper_key: tuple[str, int] | None) -> None:
        old_key = self._selected_caliper_key
        if old_key == caliper_key:
            return
        self._selected_caliper_key = caliper_key
        for item in self._persistent_linear_graphics:
            if len(item) >= 4:
                is_selected = item[3] == caliper_key
                item[1].set_selected(is_selected)
                item[2].set_selected(is_selected)

    @_prof
    def _delete_selected_caliper(self) -> bool:
        if self._selected_caliper_key is None:
            return False
        key = self._selected_caliper_key
        if key in self._stored_linear_measurements:
            del self._stored_linear_measurements[key]
        self._selected_caliper_key = None
        self._emit_stored_linear_measurements()
        self._render_persistent_linear_calipers()
        self._refresh_frame_overlays()
        return True

    @_prof
    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.key() == Qt.Key.Key_Escape:
            if self._caliper_drag_active:
                self._finish_caliper_node_drag(cancel=True)
                event.accept()
                return
        if event.key() == Qt.Key.Key_Delete:
            if self._delete_selected_caliper():
                event.accept()
                return
        if (event.key() == Qt.Key.Key_D
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier
                and event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.toggle_debug_overlay()
            event.accept()
            return
        if not event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.key() == Qt.Key.Key_Plus or event.key() == Qt.Key.Key_Equal:
                modes = ["fit", "100%", "200%"]
                idx = modes.index(self._zoom_mode) if self._zoom_mode in modes else 0
                self._zoom_mode = modes[min(idx + 1, len(modes) - 1)]
                self._zoom_factor = 1.0
                self._apply_zoom_mode()
                event.accept()
                return
            if event.key() == Qt.Key.Key_Minus:
                modes = ["fit", "100%", "200%"]
                idx = modes.index(self._zoom_mode) if self._zoom_mode in modes else 0
                self._zoom_mode = modes[max(idx - 1, 0)]
                self._zoom_factor = 1.0
                self._apply_zoom_mode()
                event.accept()
                return
            if event.key() == Qt.Key.Key_0:
                self._zoom_mode = "fit"
                self._zoom_factor = 1.0
                self._apply_zoom_mode()
                event.accept()
                return
        super().keyPressEvent(event)

    def _set_caliper_label(self, label: str) -> None:
        if label not in self._caliper_labels:
            self._caliper_labels.append(label)
        self._caliper_label_index = self._caliper_labels.index(label)

    def _step_back(self) -> None:
        current = self._timeline_slider.value()
        if current > 0:
            self._timeline_slider.setValue(current - 1)

    def _step_forward(self) -> None:
        current = self._timeline_slider.value()
        if current < self._timeline_slider.maximum():
            self._timeline_slider.setValue(current + 1)

    def _on_timeline_changed(self, value: int) -> None:
        if self._syncing_state:
            return
        self.frame_selected.emit(value)

    def bind_display_controls(
        self,
        window_slider: object,
        level_slider: object,
        dr_slider: object,
    ) -> None:
        """Wire external sliders to internal window/level/DR logic."""
        from echo_personal_tool.presentation.ge_labeled_slider import (
            GeLabeledSlider,
            TopLabeledSlider,
        )

        sliders: list[tuple[object, object]] = []
        for external, internal in (
            (window_slider, self._window_slider),
            (level_slider, self._level_slider),
            (dr_slider, self._dr_slider),
        ):
            if not isinstance(external, (GeLabeledSlider, TopLabeledSlider)):
                continue
            ext = external.slider()
            sliders.append((external, internal))
            ext.setRange(internal.minimum(), internal.maximum())
            ext.setValue(internal.value())
            ext.valueChanged.connect(internal.setValue)
            internal.valueChanged.connect(ext.setValue)
            ext.valueChanged.connect(self._update_levels)

        def sync_enabled() -> None:
            enabled = self._window_level_enabled
            for external, internal in sliders:
                external.setEnabled(enabled)
                internal.setEnabled(enabled)

        self._sync_display_control_enabled = sync_enabled  # type: ignore[attr-defined]
        sync_enabled()

    @_prof
    def _update_levels(self) -> None:
        if self._current_frame is None or not self._window_level_enabled:
            return
        frame = np.asarray(self._current_frame)
        if frame.size == 0:
            return
        dr_low, dr_high = dr_percentiles_from_slider(self._dr_slider.value())
        window_scale = self._window_slider.value() / 100.0
        level_offset = (self._level_slider.value() - 50) / 50.0
        if self._is_color_frame and self._color_source_rgb is not None:
            low, high = compute_display_levels(
                np.asarray(frame, dtype=float),
                dr_low_pct=dr_low,
                dr_high_pct=dr_high,
                window_scale=window_scale,
                level_offset=level_offset,
            )
            display = apply_window_level_rgb(self._color_source_rgb, low, high)
            self._image_item.setImage(display, autoLevels=False)
        else:
            from echo_personal_tool.infrastructure.pixel_utils import apply_wl_lut

            display = apply_wl_lut(
                frame,
                dr_low_pct=dr_low,
                dr_high_pct=dr_high,
                window_scale=window_scale,
                level_offset=level_offset,
            )
            self._image_item.setImage(display, autoLevels=False)
        self._invalidate_edge_map_cache()

    def set_magnetic_snap_enabled(self, enabled: bool) -> None:
        self._magnetic_snap_enabled = bool(enabled)

    def magnetic_snap_enabled(self) -> bool:
        return self._magnetic_snap_enabled

    def _grayscale_frame_for_edges(self) -> np.ndarray | None:
        if self._current_frame is None:
            return None
        frame = np.asarray(self._current_frame)
        if frame.ndim == 3:
            return np.mean(frame[..., :3], axis=2, dtype=np.float64)
        return frame.astype(np.float64, copy=False)

    def _effective_display_levels(self) -> tuple[float, float] | None:
        frame = self._grayscale_frame_for_edges()
        if frame is None or frame.size == 0:
            return None
        dr_low, dr_high = dr_percentiles_from_slider(self._dr_slider.value())
        return compute_display_levels(
            frame,
            dr_low_pct=dr_low,
            dr_high_pct=dr_high,
            window_scale=self._window_slider.value() / 100.0,
            level_offset=(self._level_slider.value() - 50) / 50.0,
        )

    def _invalidate_edge_map_cache(self) -> None:
        self._edge_map_cache = None
        self._edge_map_cache_key = None

    def _get_edge_map(self) -> EdgeMap | None:
        if self._current_frame is None:
            return None
        frame_id = id(self._current_frame)
        levels = self._effective_display_levels()
        cache_key = (frame_id, levels, self._is_color_frame)
        if self._edge_map_cache is not None and self._edge_map_cache_key == cache_key:
            return self._edge_map_cache
        self._edge_map_cache = build_edge_map(
            self._current_frame,
            display_levels=levels,
        )
        self._edge_map_cache_key = cache_key
        return self._edge_map_cache

    def _apply_magnetic_snap_to_contour(
        self,
        contour_index: int,
        weights: np.ndarray,
        *,
        grab_index: int | None = None,
    ) -> None:
        if not self._magnetic_snap_enabled:
            return
        edge_map = self._get_edge_map()
        if edge_map is None:
            return
        if contour_index < 0 or contour_index >= len(self._contours):
            return
        contour = self._contours[contour_index]
        if not contour.is_open_arc:
            return
        snap_cfg = magnetic_edge_snap_config_for_source(contour.source)
        pinned = self._pinned_indices_for_contour(contour)
        snapped = apply_soft_magnetic_snap(
            list(contour.points),
            weights,
            edge_map,
            strength=self._magnetic_snap_release_strength,
            max_radial_px=self._magnetic_snap_release_max_radial_px,
            weight_threshold=self._magnetic_snap_weight_threshold,
            config=snap_cfg,
            pinned_indices=pinned,
            grab_index=grab_index,
        )
        contour.points[:] = snapped
        self._snap_open_arc_endpoints(contour)

    def _current_caliper_label(self) -> str:
        return self._caliper_labels[self._caliper_label_index]
