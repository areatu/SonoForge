"""2D image viewer using PyQtGraph."""

from __future__ import annotations

import logging
import math
import os
import time
import weakref
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import cv2
import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QKeyEvent, QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsView,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import delete as shiboken_delete
from shiboken6 import isValid

from echo_personal_tool.application.diagnostics import log_boundary_failure
from echo_personal_tool.application.diagnostics import profiled as _prof
from echo_personal_tool.application.dicom_io import (
    load_samsung_tick_calibration,
    read_ecg_waveform,
    try_parse_dicom_doppler_calibration,
    try_parse_dicom_frame_panels,
)
from echo_personal_tool.application.localization import tr, tr_plural
from echo_personal_tool.application.measurement_undo_redo import UndoEntry, UndoRedoManager
from echo_personal_tool.application.user_preferences import (
    DEFAULT_RESULTS_OVERLAY_Y_RATIO,
    UserPreferences,
    resolve_wl_values,
)
from echo_personal_tool.domain.calculations.lvef_simpson import format_contour_overlay
from echo_personal_tool.domain.calculations.planimeter import (
    GENERIC_AREA_CHAMBER,
    GENERIC_VOLUME_CHAMBER,
    closed_polygon_area_cm2,
    closed_polygon_volume_ml,
    is_planimeter_polygon,
    next_area_label,
    next_volume_label,
)
from echo_personal_tool.domain.doppler_catalog import format_velocity_measurement
from echo_personal_tool.domain.measurement_catalog import format_measurement as _fmt
from echo_personal_tool.domain.measurement_catalog import measurement_for_caliper
from echo_personal_tool.domain.models import Contour
from echo_personal_tool.domain.models.doppler_roi import (
    DopplerSpectrogramRoi,
)
from echo_personal_tool.domain.models.frame_panels import FramePanelLayout
from echo_personal_tool.domain.models.linear_measurement import (
    AREA_LABELS,
    PERCENT_LABELS,
    LinearMeasurement,
    inline_caliper_text,
    pixel_to_mm_length,
)
from echo_personal_tool.domain.models.viewer_state import ViewerState
from echo_personal_tool.domain.services.auto_doppler_velocity_calibration import (
    try_auto_doppler_velocity_calibration,
)
from echo_personal_tool.domain.services.cine_phase_timeline import (
    PHASE_DIASTOLE,
    PHASE_SYSTOLE,
    PhaseTimeline,
)
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
from echo_personal_tool.domain.services.depth_scale_detector import (
    find_scale_ticks,
)
from echo_personal_tool.domain.services.frame_panel_parser import detect_panels_heuristic
from echo_personal_tool.domain.services.mbs_lite_service import (
    fit_contour_from_landmarks,
    infer_apex_from_open_arc,
    refine_open_arc_contour,
)
from echo_personal_tool.domain.services.mmode_extractor import extract_mmode_column
from echo_personal_tool.domain.services.pixel_spacing_resolver import (
    spacing_from_known_distance,
)
from echo_personal_tool.domain.services.planimeter_formatter import format_planimeter_overlay_line
from echo_personal_tool.imaging.display import (
    is_color_frame,
    to_display_rgb,
    to_grayscale_array,
)
from echo_personal_tool.keyboard_shortcuts import event_matches_shortcut, shortcut_label
from echo_personal_tool.presentation import dark_theme, ecg_strip_loader
from echo_personal_tool.presentation.anonymization_filter import AnonymizationFilter
from echo_personal_tool.presentation.calibration_snap import snap_y_to_nearest_tick
from echo_personal_tool.presentation.caliper_label_item import (
    compute_caliper_label_layout,
)
from echo_personal_tool.presentation.cine_phase_strip import CinePhaseStrip
from echo_personal_tool.presentation.display_formats import format_dpr, format_scale_factor
from echo_personal_tool.presentation.doppler_overlay import DopplerOverlayTools
from echo_personal_tool.presentation.ecg_strip_widget import EcgStripWidget
from echo_personal_tool.presentation.loop_controls import LoopControls, attach_loop_controls
from echo_personal_tool.presentation.viewer.compare_tools import (
    AREA_HINTS,
    DIAMETER_HINTS,
    compare_labels,
    live_caliper_label,
    percent_d,
    percent_s,
    resolve_frame_panels,
    start_hint,
    stored_widths,
)
from echo_personal_tool.presentation.viewer.context import ViewerContext, ViewerPaneIdentity, ViewTransform
from echo_personal_tool.presentation.viewer.display import ViewerDisplay
from echo_personal_tool.presentation.viewer.doppler_controller import (
    DopplerController,
    DopplerViewerPort,
)
from echo_personal_tool.presentation.viewer.label_picker_owner import ViewerLabelPicker
from echo_personal_tool.presentation.viewer.magnifier_controller import MagnifierController
from echo_personal_tool.presentation.viewer.mmode_controller import (
    MModeCalibrationKind,
    MModeController,
    MModeViewerPort,
)
from echo_personal_tool.presentation.viewer.overlay_controller import (
    ResultsOverlayController,
    TagsOverlayController,
)
from echo_personal_tool.presentation.viewer.transport import ViewerTransport
from echo_personal_tool.presentation.viewer.zoom import ViewerZoom
from echo_personal_tool.presentation.viewer_contract import ViewerContract
from echo_personal_tool.resources.bundled_fonts import FONT_FAMILY_MONO

if TYPE_CHECKING:
    from echo_personal_tool.domain.models.speckle import StrainResult

logger = logging.getLogger(__name__)

CALIBRATION_PROMPT_OVERLAY_KEY = "viewer.calibration.calibration_prompt"
CALIBRATION_SUCCESS_OVERLAY_KEY = "viewer.calibration.auto_ok"


#: Points removed per freehand rollback (Backspace / right-click).
_FREEHAND_ROLLBACK_POINTS = 8


def _hint_bar_style() -> str:
    """Tool-hint overlay style: readable on the viewer's black letterbox."""
    return (
        "QLabel#viewerHintBar {"
        " background: #000000; color: #eaeaea;"
        " padding: 4px 12px; font-size: 15px; font-weight: 600;"
        " border: none; }"
    )


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


def _results_overlay_style(font_size: int, opacity: float = 0.70) -> str:
    alpha = int(max(0.0, min(1.0, opacity)) * 255)
    return (
        f" background-color: rgba(0, 0, 0, {alpha});"
        + " color: #e8eef4;"
        + " padding: 11px 18px;"
        + f" font-family: '{FONT_FAMILY_MONO}', monospace;"
        + " border: 2px solid #3d7cb8;"
        + " border-radius: 5px;"
        + f" font-size: {font_size}px;"
    )


_DEFAULT_OVERLAY_STYLE = (
    "background-color: rgba(0, 0, 0, 180); color: #f5f5f5; padding: 8px; font-size: 12px; border: 1px solid #4caf50;"
)
_MAGNETIC_SNAP_WEIGHT_THRESHOLD = 0.15
_MAGNETIC_RELEASE_STRENGTH = 0.9
_MAGNETIC_RELEASE_MAX_RADIAL_PX = 15.0
#: How many colour clips the viewer remembers as colour (sticky per instance).
_COLOR_INSTANCE_MEMORY = 64
#: Hot spot of the magnifier pointer: the centre of the lens, not its corner.
_ZOOM_CURSOR_HOTSPOT = (9, 9)

# ── Contour point placement / "finish" gesture ───────────────────────
# Qt reports a second click as a double-click purely on *time*: it ignores how
# far apart the two clicks are. The viewer used to treat every double-click as
# "close the contour", so placing points faster than the double-click interval
# silently swallowed the second click (the polygon got one point less and often
# closed by itself). The gesture is therefore recognised here, with a spatial
# condition of its own, and every click that is *not* a finish gesture places a
# point — including clicks Qt flagged as double.
#: Max time between two clicks of a deliberate finish double-click.
_CONTOUR_FINISH_MAX_INTERVAL_MS = 400.0
#: Max on-screen distance between the two clicks of a finish double-click.
_CONTOUR_FINISH_MAX_SCREEN_PX = 12.0
#: Clicking this close to the first point closes the polygon instead of adding.
_CONTOUR_CLOSE_FIRST_POINT_PX = 16.0
#: A polygon needs at least this many points before any gesture can close it.
_CONTOUR_MIN_POINTS_TO_CLOSE = 3
#: Clicks closer than this (image px) to the previous point are ignored, so a
#: trembling hand cannot create zero-length edges that break the area math.
_CONTOUR_MIN_POINT_SPACING_PX = 0.5

_FREEZE_DIAG = os.environ.get("ECHO_FREEZE_DIAG", "0") == "1"
_diag_log = logging.getLogger("echo_freeze_diag") if _FREEZE_DIAG else None

#: Prefix of the generic distance caliper labels (Dist1, Dist2, …).
_GENERIC_DIST_LABEL_PREFIX = "Dist"


def _contour_picker_reference(contour: Contour) -> str:
    """Identity of a contour for the label picker (item 10 of the 2026-11-06 list).

    A stored ``measurement_id`` is the stable name; older documents have none,
    and then the clip/frame/chamber triple identifies the polygon well enough
    for the picker that was just opened for it.
    """
    if contour.measurement_id:
        return f"id:{contour.measurement_id}"
    return ":".join(
        (
            "legacy",
            contour.sop_instance_uid or "",
            str(contour.frame_index if contour.frame_index is not None else ""),
            contour.chamber.upper(),
            contour.view.upper(),
            contour.phase.upper(),
        )
    )


def _is_generic_dist_label(label: str) -> bool:
    """True for the generic caliper (DistN), which adapts to the Doppler ROI."""
    return label.startswith(_GENERIC_DIST_LABEL_PREFIX)


_JPEG_SUFFIXES = frozenset({".jpg", ".jpeg", ".jpe", ".jfif"})


def _force_png_suffix(path: str) -> str:
    """Normalise a frame-export path to a single ``.png`` suffix.

    The save dialog only offers PNG, but the typed name may still carry an
    image extension from habit (``frame.jpg``); appending would produce
    ``frame.jpg.png``.
    """
    suffix = Path(path).suffix.lower()
    if suffix in _JPEG_SUFFIXES:
        return f"{path[: -len(suffix)]}.png"
    if suffix == ".png":
        return path
    return f"{path}.png"


def _magnifier_cursor():
    """The «лупа» pointer: the bundled search glyph, or a cross as a fallback.

    A magnifier cursor is the whole point of item 4 of the 2026-10-23 acceptance
    list — the tool has to *announce* itself before the click, not after it.
    The glyph is rendered by the same SVG loader the chrome uses and tinted with
    the theme, so it stays visible on light themes too.
    """
    from PySide6.QtGui import QCursor

    try:
        from echo_personal_tool.presentation.window_chrome.title_bar import load_icon

        icon = load_icon("search")
        if not icon.isNull():
            pixmap = icon.pixmap(32, 32)
            if not pixmap.isNull():
                return QCursor(pixmap, *_ZOOM_CURSOR_HOTSPOT)
    except Exception:  # pragma: no cover - a broken install still gets a cursor
        # No payload: the diagnostics ratchet (ER-08/ER-09) forbids logging the
        # exception object, and the fallback below is the whole recovery.
        logger.debug("magnifier cursor unavailable, falling back to a cross")
    return QCursor(Qt.CursorShape.CrossCursor)


class ContourViewBox(pg.ViewBox):
    """ViewBox: clicks for tools; wheel steps frames; no pan/zoom drag."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._viewer_widget: ViewerWidget | None = None
        self._prepared_draw_tool = None  # speaker-only visual teaching tool
        self.setMenuEnabled(False)
        self.setMouseEnabled(x=False, y=False)

    def set_viewer_widget(self, viewer_widget: ViewerWidget) -> None:
        self._viewer_widget = viewer_widget

    @property
    def viewer_widget(self) -> ViewerWidget | None:
        """The viewer this ViewBox forwards tool events to (issue 327 public seam)."""
        return self._viewer_widget

    @viewer_widget.setter
    def viewer_widget(self, viewer_widget: ViewerWidget | None) -> None:
        self._viewer_widget = viewer_widget

    def mouseClickEvent(self, ev) -> None:
        if self._prepared_draw_tool is not None and self._prepared_draw_tool.structure is not None:
            if ev.button() == Qt.MouseButton.RightButton:
                self._prepared_draw_tool.cancel()
            ev.accept()
            return
        if ev.button() == Qt.MouseButton.RightButton:
            # While a contour is open, right-click removes the last point.
            if self._viewer_widget is not None and self._viewer_widget._handle_contour_mouse_click(ev):
                return
            ev.accept()
            return
        if self._viewer_widget is not None and self._viewer_widget.doppler.handle_mouse_click(ev):
            return
        if self._viewer_widget is not None and self._viewer_widget._handle_contour_mouse_click(ev):
            return
        ev.accept()

    @_prof
    def mousePressEvent(self, ev) -> None:
        if self._prepared_draw_tool is not None and self._prepared_draw_tool.structure is not None:
            if ev.button() == Qt.MouseButton.LeftButton:
                self._prepared_draw_tool.handle_press(ev.scenePos())
            ev.accept()
            return
        if self._viewer_widget is not None and self._viewer_widget.is_label_picker_visible():
            self._viewer_widget.dismiss_label_picker()
        if ev.button() == Qt.MouseButton.RightButton:
            # A right-click is «undo», never the start of a chained tool.
            if self._viewer_widget is not None:
                self._viewer_widget.clear_armed_next()
            ev.accept()
            return
        # The armed second half of a paired tool (ТЗ п. 2): the operator has
        # scrolled to the systolic frame, and this click both starts the tool and
        # places its first point — the handlers below see a running tool.
        # A click that grabs a node of an existing contour keeps dragging it:
        # correcting the previous measurement must not spawn the next one.
        # Item 13 of the 2026-11-06 list: the gate is the frame, not the anatomy
        # of the click.  A press anywhere on the frame the chain was armed on —
        # inside or outside the influence zone of the line — belongs to the
        # contour that was just drawn, so it edits instead of starting the ES
        # step on the ED frame (which also used to eat the pair).
        if ev.button() == Qt.MouseButton.LeftButton and self._viewer_widget is not None:
            if self._viewer_widget.armed_next() is not None:
                if self._viewer_widget._handle_contour_zone_press(ev):
                    ev.accept()
                    return
                if self._viewer_widget.armed_next_waits_for_another_frame():
                    self._viewer_widget.hint_armed_next_needs_another_frame()
                    ev.accept()
                    return
                self._viewer_widget.start_armed_next()
        if self._viewer_widget is not None and self._viewer_widget.doppler.handle_calibration_click(ev):
            ev.accept()
            return
        if self._viewer_widget is not None and self._viewer_widget.mmode.handle_calibration_click(ev):
            ev.accept()
            return
        if self._viewer_widget is not None and self._viewer_widget._handle_calibration_mouse_press(ev):
            ev.accept()
            return
        if self._viewer_widget is not None and self._viewer_widget._handle_linear_caliper_mouse_press(ev):
            ev.accept()
            return
        if self._viewer_widget is not None and self._viewer_widget.doppler.handle_trace_press(ev):
            ev.accept()
            return
        if self._viewer_widget is not None and self._viewer_widget.doppler.handle_peak_press(ev):
            ev.accept()
            return
        if self._viewer_widget is not None and self._viewer_widget.doppler.handle_vessel_press(ev):
            ev.accept()
            return
        if self._viewer_widget is not None and self._viewer_widget._handle_contour_zone_press(ev):
            ev.accept()
            return
        if self._viewer_widget is not None and self._viewer_widget.mmode.handle_line_click_from_event(ev):
            ev.accept()
            return
        super().mousePressEvent(ev)

    @_prof
    def mouseMoveEvent(self, ev) -> None:
        if self._prepared_draw_tool is not None and self._prepared_draw_tool.structure is not None:
            self._prepared_draw_tool.handle_move(ev.scenePos())
            ev.accept()
            return
        if self._viewer_widget is not None and self._viewer_widget.doppler.handle_peak_drag(ev):
            ev.accept()
            return
        if self._viewer_widget is not None and self._viewer_widget._handle_contour_hover(ev):
            ev.accept()
            return
        super().mouseMoveEvent(ev)

    def mouseDragEvent(self, ev) -> None:
        if self._prepared_draw_tool is not None and self._prepared_draw_tool.drag(ev):
            return
        if ev.button() == Qt.MouseButton.RightButton:
            ev.accept()
            return
        viewer = self._viewer_widget
        if viewer is not None and viewer._handle_contour_zone_drag(ev):
            ev.accept()
            return
        if viewer is not None and viewer.doppler.handle_trace_drag(ev):
            ev.accept()
            return
        if viewer is not None and viewer.doppler.handle_peak_drag(ev):
            ev.accept()
            return
        if viewer is not None and viewer.doppler.handle_vessel_drag(ev):
            ev.accept()
            return
        if viewer is not None and viewer._drag_session is not None:
            ev.accept()
            return
        ev.ignore()

    def mouseReleaseEvent(self, ev) -> None:
        if self._prepared_draw_tool is not None and self._prepared_draw_tool.structure is not None:
            if ev.button() == Qt.MouseButton.LeftButton:
                self._prepared_draw_tool.handle_release()
            ev.accept()
            return
        if (
            self._viewer_widget is not None
            and self._viewer_widget._freehand_recording
            and not self._viewer_widget._freehand_open_arc
            and self._viewer_widget._contour_mode_active
            and ev.button() == Qt.MouseButton.LeftButton
            and len(self._viewer_widget._freehand_points) >= 3
        ):
            self._viewer_widget._finish_active_freehand_contour()
            super().mouseReleaseEvent(ev)
            return
        if self._viewer_widget is not None and self._viewer_widget._handle_caliper_drag_release(ev):
            ev.accept()
            return
        if self._viewer_widget is not None and self._viewer_widget.doppler.handle_trace_release(ev):
            ev.accept()
            return
        if self._viewer_widget is not None and self._viewer_widget.doppler.handle_peak_release(ev):
            ev.accept()
            return
        if self._viewer_widget is not None and self._viewer_widget.doppler.handle_vessel_release(ev):
            ev.accept()
            return
        if self._viewer_widget is not None and self._viewer_widget._handle_contour_drag_release(ev):
            ev.accept()
            return
        if self._viewer_widget is not None and self._viewer_widget._handle_contour_zone_release(ev):
            ev.accept()
            return
        super().mouseReleaseEvent(ev)

    def leaveEvent(self, ev) -> None:
        if self._viewer_widget is not None:
            self._viewer_widget._clear_contour_hover()
            if self._viewer_widget._caliper_drag_active:
                self._viewer_widget._finish_caliper_node_drag(cancel=True)
        super().leaveEvent(ev)

    @_prof
    def wheelEvent(self, ev, axis=None) -> None:
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

    def set_rbf_highlight(
        self, *, active: bool, color: str = dark_theme.get_theme_tokens()["overlay.contour.model"]
    ) -> None:
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
    def mousePressEvent(self, ev) -> None:
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

    def mouseDragEvent(self, ev) -> None:
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
        viewer_widget: ViewerWidget,
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

    def hoverEvent(self, ev) -> None:
        if ev.isEnter():
            self.setSymbol(self._SYMBOL_HOVER)
            self.setSize(14)
            self.setPen(pg.mkPen(dark_theme.get_theme_tokens()["overlay.caliper"], width=2))
            self.setBrush(pg.mkBrush(dark_theme.get_theme_tokens()["overlay.caliper"]))
        elif ev.isExit():
            if self._viewer_widget._selected_caliper_key != self._caliper_key:
                self.setSymbol(self._SYMBOL_DEFAULT)
                self.setSize(self._base_size)
                self.setPen(self._base_pen)
                self.setBrush(pg.mkBrush(self._base_pen.color()))

    @_prof
    def mousePressEvent(self, ev) -> None:
        if ev.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(ev)
            return
        if not self._viewer_widget._caliper_node_edit_allowed():
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

    def mouseDragEvent(self, ev) -> None:
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        ev.accept()
        view_box = self.getViewBox() or self._viewer_widget._view
        point = view_box.mapSceneToView(ev.scenePos())
        self._viewer_widget._apply_caliper_node_drag(float(point.x()), float(point.y()))

    def mouseReleaseEvent(self, ev) -> None:
        if ev.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(ev)
            return
        ev.accept()
        self._viewer_widget._finish_caliper_node_drag()

    def set_selected(self, selected: bool) -> None:
        if selected:
            self.setSymbol(self._SYMBOL_HOVER)
            self.setSize(14)
            self.setPen(pg.mkPen(dark_theme.get_theme_tokens()["overlay.caliper"], width=2))
            self.setBrush(pg.mkBrush(dark_theme.get_theme_tokens()["overlay.caliper"]))
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
    parameter_clicked = Signal(str)  # param_id when a link is clicked

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setOpenExternalLinks(False)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.linkActivated.connect(self.on_link_activated)
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

    def _link_at(self, pos) -> str | None:
        """Return href of the <a> tag under *pos*, or None."""
        from PySide6.QtGui import QTextCursor, QTextDocument

        doc = self.findChild(QTextDocument)
        if doc is None:
            return None
        layout = doc.documentLayout()
        if layout is None:
            return None
        offset = layout.hitTest(pos, Qt.HitTestAccuracy.ExactHit)
        if offset < 0:
            return None
        cursor = QTextCursor(doc)
        cursor.setPosition(offset)
        char_fmt = cursor.charFormat()
        href = char_fmt.anchorHref()
        return href if href else None

    @_prof
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            # Check if clicking on a link — if so, let TextBrowserInteraction handle it
            if self._link_at(event.position().toPoint()):
                super().mousePressEvent(event)
                return
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

    @property
    def pinned(self) -> bool:
        """Whether the overlay keeps its custom position (issue 327 public seam)."""
        return self._pinned

    @pinned.setter
    def pinned(self, value: bool) -> None:
        self._pinned = bool(value)

    @property
    def on_link_activated(self):
        """Link-activation handler as a public slot (issue 327 public seam)."""
        return self._on_link_activated

    def _on_link_activated(self, href: str) -> None:
        if href:
            self.parameter_clicked.emit(href)

    @_prof
    def mouseMoveEvent(self, event: QMouseEvent) -> None:
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

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event) -> None:
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


@dataclass
class _ComparisonState:
    kind: str = ""  # "diameter", "area", "stenosis_diameter", "ar_jet_diameter", "ar_jet_area"…
    segment1_start: tuple[float, float] | None = None
    segment1_end: tuple[float, float] | None = None
    segment1_mm: float | None = None
    segment2_start: tuple[float, float] | None = None
    segment2_end: tuple[float, float] | None = None
    segment2_mm: float | None = None
    contour1_points: list[tuple[float, float]] | None = None
    contour1_area_cm2: float | None = None
    contour2_points: list[tuple[float, float]] | None = None
    contour2_area_cm2: float | None = None
    frame_index: int | None = None

    @property
    def first_segment_done(self) -> bool:
        return self.segment1_end is not None and self.segment1_mm is not None

    @property
    def first_contour_done(self) -> bool:
        return self.contour1_points is not None and self.contour1_area_cm2 is not None

    @property
    def is_active(self) -> bool:
        return self.kind != ""

    def reset(self) -> None:
        self.kind = ""
        self.segment1_start = None
        self.segment1_end = None
        self.segment1_mm = None
        self.segment2_start = None
        self.segment2_end = None
        self.segment2_mm = None
        self.contour1_points = None
        self.contour1_area_cm2 = None
        self.contour2_points = None
        self.contour2_area_cm2 = None
        self.frame_index = None


class _LoupeKeyRelay(QObject):
    """Forwards Z to one viewer without installing the viewer on QApplication.

    The viewer is held weakly: a strong back-reference is a QObject cycle, and
    collecting that cycle segfaults on Linux. The relay is deleted in
    ``hideEvent`` so a later ``gc.collect()`` does not free an installed
    filter. Layout and paint events must not touch the viewer — ``isVisible()``
    re-enters the layout that is delivering the event and stalls
    ``QLayout.addWidget`` past the 60s pytest-timeout.
    """

    def __init__(self, viewer: QWidget) -> None:
        super().__init__()
        self._viewer = weakref.ref(viewer)

    def eventFilter(self, watched, event) -> bool:
        if event.type() not in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            return False
        viewer = self._viewer() if self._viewer is not None else None
        if viewer is None or not isValid(viewer):
            self._viewer = None
            return False
        try:
            return bool(viewer._loupe_key_from_app(watched, event))
        except RuntimeError:
            self._viewer = None
            return False


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
    vessel_accept_requested = Signal(object)
    mmode_calibration_changed = Signal(object)
    mmode_time_calibration_completed = Signal(object)
    results_overlay_position_changed = Signal(float, float)
    results_overlay_parameter_clicked = Signal(str)
    gold_export_requested = Signal(str, int, str)  # phase, frame_index, chamber
    mmode_column_ready = Signal(object, object)  # (column: np.ndarray, frame_index: int)
    mmode_line_completed = Signal(object, object)  # (start: tuple, end: tuple)

    context_calibration_bmode_requested = Signal()
    context_doppler_calibration_requested = Signal()
    context_properties_requested = Signal()
    context_reset_requested = Signal()
    #: Double-click on the transport's «FPS: …» — retime the current clip.
    fps_override_requested = Signal()
    loop_in_requested = Signal()
    loop_out_requested = Signal()
    loop_toggle_requested = Signal()
    loop_bound_changed = Signal(str, int)

    def __init__(self, parent: QWidget | None = None, *, loop_controls: bool = True) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._graphics = pg.GraphicsLayoutWidget()
        self._graphics.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
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
        # Spectral Doppler calibration, mode, auto-detect and overlay tools
        # (issue 420): owned by DopplerController; widget re-emits its signals.
        self.doppler = DopplerController(self._build_doppler_port(), eager_overlay=True, parent=self)
        self.doppler.markers_changed.connect(self.doppler_markers_changed)
        self.doppler.calibration_changed.connect(self.doppler_calibration_changed)
        self.doppler.spectral_calibration_completed.connect(self.spectral_calibration_completed)
        self.doppler.frame_changing.connect(self.doppler_frame_changing)
        self.doppler.frame_changed.connect(self.doppler_frame_changed)
        from echo_personal_tool.presentation.speckle_overlay import SpeckleOverlay

        self._speckle_overlay = SpeckleOverlay(self._view, self)
        self._speckle_overlay.hide()
        self._speckle_result = None

        from echo_personal_tool.presentation.ste_sensitivity_overlay import SteSensitivityOverlay

        self._ste_sensitivity = SteSensitivityOverlay(self)
        self._ste_sensitivity.smoothness_changed.connect(self._on_ste_smoothness_changed)

        from echo_personal_tool.presentation.vessel_sensitivity_overlay import (
            VesselSensitivityOverlay,
        )

        self._vessel_sensitivity = VesselSensitivityOverlay(self)
        self._vessel_sensitivity.preset_changed.connect(self._on_vessel_preset_changed)
        self._vessel_direction: str | None = None
        self._vessel_site_label: str = ""
        self._vessel_current_preset: str = "normal"

        self._calibration_kind: Literal["depth", "spectral", "doppler_velocity", "mmode_time", "mmode_depth"] | None = (
            None
        )
        self._frame_panel_layout: FramePanelLayout | None = None
        self._frame_panels_from_dicom = False
        # M-mode calibration, scan line and frame calipers (issue 479): the
        # controller owns that state; the widget re-emits its signals.
        self.mmode = MModeController(self._build_mmode_port(), parent=self)
        self.mmode.calibration_changed.connect(self.mmode_calibration_changed)
        self.mmode.time_calibration_completed.connect(self.mmode_time_calibration_completed)
        self.mmode.line_completed.connect(self.mmode_line_completed)
        self._crosshair_h_item: pg.PlotDataItem | None = None
        self._crosshair_v_item: pg.PlotDataItem | None = None
        self._last_view_cursor_xy: tuple[float, float] | None = None
        self._vertical_caliper_labels: set[str] = {"TAPSE", "M-mode"}
        self._horizontal_time_caliper_labels = frozenset({"Time"})
        self._current_frame: np.ndarray | None = None
        self._current_state: ViewerState | None = None
        self._linear_caliper_active = False
        self._linear_caliper_start: tuple[float, float] | None = None
        # Generic caliper stays armed after each measurement (scanner-like UX):
        # click-click → result, next click-click → new DistN measurement.
        self._caliper_repeat_mode = False
        self._comparison_state = _ComparisonState()
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
        self._dist_serial = 1
        self._contour_mode_active = False
        # the radial-menu controller the window attaches; the viewer
        # only forwards the three gesture entry points (QH-3 rule).
        self.radial_controller = None
        # Last accepted contour click (screen px + monotonic ms) — the state the
        # finish-gesture detector below is built on.
        self._last_contour_click_ms: float | None = None
        self._last_contour_click_screen: tuple[float, float] | None = None
        self._last_contour_point_screen: tuple[float, float] | None = None
        self._first_contour_point_screen: tuple[float, float] | None = None
        self._contour_mode_kind: Literal["manual", "model", "closed"] | None = None
        self._active_contour_chamber: str = "LV"
        self._contour_stage: Literal["ma_septal", "ma_lateral", "arc", "apex", "polygon", "trace"] | None = None
        self._active_mitral_septal: tuple[float, float] | None = None
        self._active_mitral_annulus: tuple[tuple[float, float], tuple[float, float]] | None = None
        self._active_apex_landmark: tuple[float, float] | None = None
        self._active_arc_points: list[tuple[float, float]] = []
        self._freehand_recording = False
        self._freehand_points: list[tuple[float, float]] = []
        #: True while the freehand stroke belongs to an open LV arc (trace mode)
        #: rather than the closed area tool; release then pauses instead of finishing.
        self._freehand_open_arc = False
        self._area_tool_mode: str = "click"
        self._lv_contour_input: str = "landmarks"
        self._atrial_contour_input: str = "landmarks"
        self._active_contour_item: pg.PlotDataItem | None = None
        self._active_ma_chord_item: pg.PlotDataItem | None = None
        self._active_contour_phase: str | None = None
        self._contour_pen_manual = pg.mkPen(dark_theme.get_theme_tokens()["overlay.contour.manual"], width=2)
        self._contour_pen_ai = pg.mkPen(dark_theme.get_theme_tokens()["overlay.contour.auto"], width=2)
        self._contour_pen_ai_pending = pg.mkPen(
            dark_theme.get_theme_tokens()["overlay.contour.auto"], width=2, style=Qt.PenStyle.DashLine
        )
        self._contour_pen_model = pg.mkPen(dark_theme.get_theme_tokens()["overlay.contour.model"], width=2)
        self._contour_pen_ma = pg.mkPen(
            dark_theme.get_theme_tokens()["overlay.contour.manual"], width=1, style=Qt.PenStyle.DashLine
        )
        # Ghost overlay pens (temporal fusion)
        self._contour_pen_ghost_center = pg.mkPen(
            dark_theme.get_theme_tokens()["overlay.contour.auto"],
            width=1,
            style=Qt.PenStyle.DashLine,
        )
        self._contour_pen_ghost_neighbor = pg.mkPen(
            dark_theme.get_theme_tokens()["overlay.label"],
            width=1,
            style=Qt.PenStyle.DotLine,
        )
        self._ghost_mode: str = "off"  # off | center | neighbor
        self._ghost_neighbor_index: int = 0
        self._ghost_items: list[pg.PlotDataItem] = []
        self._contour_ma_items: list[pg.PlotDataItem | None] = []
        self._contour_simpson_items: list[pg.PlotDataItem] = []
        self._contour_pen_simpson = pg.mkPen(
            dark_theme.get_theme_tokens()["overlay.caliper"], width=1, style=Qt.PenStyle.DashLine
        )
        self._active_contour_view = "A4C"
        self._frame_overlay_lines: list[str] = []
        self._pending_viewer_state: ViewerState | None = None
        self._initialize_measurement_state()
        # A4: the naming popup and the caliper-label cycle live in their own
        # owner; the viewer keeps only the clinical apply path.
        self.label_picker_owner = ViewerLabelPicker(
            parent=self,
            apply_label=self._apply_picked_label,
            can_cycle_label=lambda: not self._caliper_repeat_mode,
            cardiac_provider=self._header_cardiac_context,
        )
        self._protocol_active: bool = False
        self._protocol_active_provider: Callable[[], bool] | None = None
        self._init_controller_providers()
        #: The second half of a paired tool armed for the *next click* (the chain
        #: resolves on the click: scrolling cancels a running tool, ТЗ 2026-10-23
        #: п. 2) and the ``(frame, clip)`` it was armed on — item 13: a click on the
        #: ED-contour frame stays a click instead of starting ES there.
        self._armed_next: tuple | None = None
        self._armed_next_origin: tuple[int | None, str | None] = (None, None)
        self._syncing_state = False
        #: Viewport mode/factor and the loupe state live in one owner; the
        #: widget keeps only public delegate methods for callers/tests.
        self.zoom = ViewerZoom(
            graphics=self._graphics,
            view=self._view,
            frame_provider=lambda: self._current_frame,
            set_hint=self.set_hint,
            refresh_cursor=self._apply_viewport_cursor,
        )
        self._is_color_frame = False
        #: Instances (clips) that showed colour at least once.  A colour Doppler
        #: clip keeps its colour even when a particular frame carries a tiny jet
        #: or none at all — re-detecting per frame made it flicker or stay gray.
        self._color_instances: set[object] = set()
        self._color_source_rgb: np.ndarray | None = None
        self._window_level_enabled = True
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
        # Issue 420: the magnifier has exactly one owner — `_magnifier_controller`,
        # created below.  enabled/zoom/radius/linear-persistent, the transient
        # held/persistent flags, reduce-motion and the lens itself live there;
        # this widget only translates Qt events into controller calls.
        self._loupe_key_relay: _LoupeKeyRelay | None = None
        self.destroyed.connect(self._remove_loupe_key_relay)
        self._show_panel_frames = False
        self._init_caliper_display_state()
        self._panel_frame_items: list[pg.PlotDataItem] = []
        self._magnetic_snap_enabled = True
        self._despeckle_enabled = False
        # Burned-in PHI (name/ID/date) is masked before anything else sees the
        # frame, so calibration, M-mode and export all work on masked pixels.
        self._phi_filter = AnonymizationFilter(enabled=True)
        self._edge_map_cache: EdgeMap | None = None
        self._edge_map_cache_key: tuple[int, tuple[float, float] | None] | None = None

        self._overlay_label = QLabel(self)
        self._overlay_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._overlay_label.setStyleSheet(_DEFAULT_OVERLAY_STYLE)
        self._overlay_label.hide()

        self._results_overlay_label = ResultsOverlayLabel(self)
        self._results_overlay_label.setAccessibleName(tr("a11y.results_overlay"))
        self._results_overlay_label.setAccessibleDescription(tr("a11y.results_overlay_desc"))
        self._results_overlay_label.setStyleSheet(_results_overlay_style(20, 0.70))
        self._results_overlay_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._results_overlay_label.position_changed.connect(self.results_overlay_position_changed.emit)
        self._results_overlay_label.clear_requested.connect(self._on_results_overlay_clear)
        self._results_overlay_label.reset_position_requested.connect(self._on_results_overlay_reset_position)
        self._results_overlay_label.pin_toggled.connect(self._on_results_overlay_pin_toggled)
        self._results_overlay_label.parameter_clicked.connect(self.results_overlay_parameter_clicked.emit)
        self._results_overlay_label.hide()

        self._debug_overlay_visible = False
        self._debug_overlay_label = QLabel(self)
        self._debug_overlay_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._debug_overlay_label.setStyleSheet(
            "background-color: rgba(0, 0, 0, 180); color: #0f0; font-family: monospace; font-size: 11px; padding: 4px;"
        )
        self._debug_overlay_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._debug_overlay_label.hide()

        # ── QH-3 composition pilot (overlay / magnifier / context) ──────────
        # ViewerWidget stays the Qt facade; logic lives in small owner-scoped
        # controllers. Overlay widgets remain children of the viewer for Qt
        # lifetime and geometry, while each controller owns its workflow.
        self._viewer_context = ViewerContext()
        self._generation = 0
        self._viewer_context_generation = 0
        self._results_overlay_controller = ResultsOverlayController(
            self._results_overlay_label,
            lambda: self._graphics.geometry() if hasattr(self, "_graphics") else None,
            parent=self,
        )
        self.tags_overlay = TagsOverlayController(
            self,
            lambda: self._graphics.geometry() if hasattr(self, "_graphics") else None,
            lambda: getattr(self._current_instance_metadata(), "path", None),
        )
        self._magnifier_controller = MagnifierController(
            parent=self,
            lens_factory=self._create_magnifier_lens,
            geometry_provider=lambda: self._graphics.geometry() if hasattr(self, "_graphics") else None,
            cursor_provider=lambda: (
                self._scene_pos_under_cursor() if hasattr(self, "_scene_pos_under_cursor") else None
            ),
        )
        # Live owner-scoped controllers share the generation-scoped context (S-02, S-05).
        self._all_qh3_controllers: list[QObject] = [
            self._results_overlay_controller,
            self.tags_overlay,
            self._magnifier_controller,
        ]

        attach_loop_controls(self, enabled=loop_controls)
        self._measurement_label = QLabel(f"{self._current_caliper_label()}: —", self)
        self._measurement_label.hide()

        self.display = ViewerDisplay(
            parent=self,
            frame_provider=lambda: self._current_frame,
            enabled_provider=lambda: self._window_level_enabled,
            color_source_provider=lambda: self._color_source_rgb,
            color_active_provider=lambda: self._color_display_active,
            image_item=self._image_item,
            invalidate_edge_map=self._invalidate_edge_map_cache,
        )

        # The whole transport lives in one widget so the focus view (UI-6) can
        # hide it and show its floating cine plate instead — without touching
        # the timeline, the frame cache or any playback state.
        self._build_cine_transport()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._graphics, stretch=1)

        # ECG strip (shown when Doppler is active)
        self._ecg_strip = EcgStripWidget()
        self._ecg_strip.hide()
        layout.addWidget(self._ecg_strip)

        # PR-UI: the tool prompt is drawn inside the viewport's unused black
        # letterbox (the strip under the aspect-locked image) instead of a
        # separate row above the timeline. Larger font, black background; the
        # overlay is transparent to mouse so it never steals viewer input.
        _viewport = self._graphics.viewport()
        self._hint_bar = QLabel("", _viewport)
        self._hint_bar.setObjectName("viewerHintBar")
        self._hint_bar.setWordWrap(True)
        self._hint_bar.setStyleSheet(_hint_bar_style())
        self._hint_bar.setFixedHeight(30)
        self._hint_bar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._hint_bar.hide()
        layout.addWidget(self.transport.bar)
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

    def _initialize_measurement_state(self) -> None:
        """Initialize per-viewer measurement and undo state outside the long constructor."""
        self._stored_linear_measurements: dict[tuple[str, int], LinearMeasurement] = {}
        self._persistent_linear_graphics: list[tuple[pg.PlotDataItem, pg.ScatterPlotItem]] = []
        self._active_caliper_label_item: pg.TextItem | None = None
        self._persistent_caliper_label_items: list[pg.TextItem] = []
        self._caliper_sequence: list[str] = []
        self._caliper_sequence_size = 0
        #: Labels of the last started sequence.  The completion signal carries
        #: no payload, and the window has to know whether the finished chain
        #: was the LV diastole or the general organ-volume triplet.
        self._last_caliper_sequence_labels: tuple[str, ...] = ()
        self._undo_redo: UndoRedoManager = UndoRedoManager()
        self._caliper_drag_active: bool = False
        self._caliper_drag_key: tuple[str, int] | None = None
        self._caliper_drag_node: int | None = None
        self._caliper_drag_original: LinearMeasurement | None = None
        self._caliper_drag_persistent_items: list | None = None
        self._selected_caliper_key: tuple[str, int] | None = None

    def _on_scene_mouse_moved(self, scene_pos) -> None:
        mapped = self._view.mapSceneToView(scene_pos)
        if mapped is not None:
            self._update_measurement_crosshair(float(mapped.x()), float(mapped.y()))
        self._update_magnifier_loupe(scene_pos)
        if mapped is not None:
            self.doppler.update_interval_preview(float(mapped.x()))
        if self._calibration_active:
            if mapped is not None and self._current_frame is not None:
                if self._calibration_kind == "mmode_time":
                    width = self._current_frame.shape[1]
                    current_x = max(0.0, min(float(mapped.x()), float(width - 1)))
                    if self.mmode.time_start_x is None:
                        y = max(0.0, min(float(mapped.y()), float(self._current_frame.shape[0] - 1)))
                        self._update_mmode_time_preview(current_x, current_x, y)
                    else:
                        start_x = float(self.mmode.time_start_x)
                        y = self._calibration_start_y if self._calibration_start_y is not None else float(mapped.y())
                        self._update_mmode_time_preview(start_x, current_x, y)
                    return
                height = self._current_frame.shape[0]
                raw_y = max(0.0, min(float(mapped.y()), float(height - 1)))
                if self._calibration_kind == "doppler_velocity" and self.doppler.grid_line_positions:
                    tick_positions = self.doppler.grid_line_positions
                else:
                    tick_positions = self._depth_tick_y_positions
                snapped_y = snap_y_to_nearest_tick(
                    raw_y, tick_positions, radius_px=self._calibration_tick_snap_radius_px
                )
                if self._calibration_start_y is not None:
                    self._update_calibration_preview(self._calibration_start_y, snapped_y)
                    self._update_calibration_horizontal_guides(snapped_y)
                else:
                    self._update_calibration_preview(snapped_y, snapped_y)
                    self._update_calibration_horizontal_guides(snapped_y)
            return
        if self._linear_caliper_active and self._linear_caliper_start is not None:
            if mapped is not None:
                end = (float(mapped.x()), float(mapped.y()))
                if self._linear_caliper_start is not None:
                    if self._comparison_state.kind:
                        end = self._constrain_linear_endpoint(self._linear_caliper_start, end, label="Dx")
                    else:
                        end = self._constrain_linear_endpoint(self._linear_caliper_start, end)
                self._update_linear_caliper_preview(self._linear_caliper_start, end)
                self._update_linear_caliper_label_preview(self._linear_caliper_start, end)
            return
        if self._caliper_drag_active and QApplication.mouseButtons() & Qt.MouseButton.LeftButton:
            if mapped is not None:
                self._apply_caliper_node_drag(float(mapped.x()), float(mapped.y()))
            return
        if (
            self._freehand_recording
            and self._contour_mode_active
            and QApplication.mouseButtons() & Qt.MouseButton.LeftButton
        ):
            if mapped is not None:
                pt = (float(mapped.x()), float(mapped.y()))
                if not self._freehand_points or self._distance(self._freehand_points[-1], pt) > 8.0:
                    self._freehand_points.append(pt)
                    if len(self._freehand_points) > 200:
                        self._freehand_points = self._freehand_points[::2]
                    self._update_freehand_preview()
            return
        if self._contour_editing_blocked():
            self._clear_contour_hover()
            return
        if self._drag_session is not None:
            if QApplication.mouseButtons() & Qt.MouseButton.LeftButton:
                if mapped is not None:
                    contour_index, _, _, grab_index, _ = self._drag_session
                    self._apply_rbf_drag_step(
                        contour_index,
                        float(mapped.x()),
                        float(mapped.y()),
                        grab_index=grab_index,
                    )
            return
        if mapped is None:
            return
        self._update_contour_hover((float(mapped.x()), float(mapped.y())))

    def showEvent(self, event) -> None:
        # Z must reach the loupe even when focus sits on the gallery or the tool panel.
        self._install_loupe_key_relay()
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        self._remove_loupe_key_relay()
        super().hideEvent(event)

    def _install_loupe_key_relay(self) -> None:
        """Relay Z from the focused control, never from QApplication.

        An application-wide Python filter forces Shiboken to wrap every event
        receiver, including QtWebEngine's internal no-RTTI compositor objects.
        The focus-scoped relay keeps the shortcut available over the gallery and
        tool panel without observing unrelated native objects.
        """
        app = QApplication.instance()
        if app is None or self._loupe_key_relay is not None:
            return
        relay = _LoupeKeyRelay(self)
        self._loupe_key_relay = relay
        window = self.window()
        if window is not None and window is not self:
            window.installEventFilter(relay)
            self._loupe_window_target = window
        self._loupe_focus_connection = app.focusChanged.connect(self._update_loupe_key_relay_focus)
        self._update_loupe_key_relay_focus(None, app.focusWidget())

    def _update_loupe_key_relay_focus(self, _old: QWidget | None, focused: QWidget | None) -> None:
        relay = self._loupe_key_relay
        if relay is None:
            return
        previous = getattr(self, "_loupe_focus_widget", None)
        if previous is not None and isValid(previous):
            try:
                previous.removeEventFilter(relay)
            except RuntimeError:
                pass
        self._loupe_focus_widget = None
        if focused is None or not isValid(focused):
            return
        # Do not attach to QtWebEngine internals; the web reference has its own
        # keyboard handling and must not drive the cine loupe.
        if "WebEngine" in focused.metaObject().className():
            return
        if self._graphics is not None and focused in (self._graphics, self._graphics.viewport()):
            return
        focused.installEventFilter(relay)
        self._loupe_focus_widget = focused

    def _remove_loupe_key_relay(self) -> None:
        relay = self._loupe_key_relay
        self._loupe_key_relay = None
        app = QApplication.instance()
        connection = getattr(self, "_loupe_focus_connection", None)
        if connection is not None and app is not None:
            try:
                app.focusChanged.disconnect(connection)
            except (RuntimeError, TypeError):
                pass
        self._loupe_focus_connection = None
        for target in (getattr(self, "_loupe_focus_widget", None), getattr(self, "_loupe_window_target", None)):
            if target is not None and isValid(target) and relay is not None and isValid(relay):
                try:
                    target.removeEventFilter(relay)
                except RuntimeError:
                    pass
        self._loupe_focus_widget = None
        self._loupe_window_target = None
        if relay is None:
            return
        relay._viewer = None
        # deleteLater races the between-test gc.collect() and double-frees.
        if isValid(relay):
            shiboken_delete(relay)

    def _loupe_key_from_app(self, watched, event) -> bool:  # type: ignore[no-untyped-def]  # mypy does not check this file (outside tool.mypy.files)
        if not hasattr(self, "_graphics") or self._graphics is None or not self.isVisible():
            return False
        if event.type() not in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            return False
        if (
            not event_matches_shortcut(event, "magnifier_hold", exact_modifiers=False, forbidden_modifiers=("Ctrl",))
            or event.isAutoRepeat()
        ):
            return False
        if self._text_input_has_focus():
            return False
        if watched is self._graphics or watched is self._graphics.viewport():
            return False
        if event.type() == QEvent.Type.KeyPress and self._scene_pos_under_cursor() is not None:
            self.keyPressEvent(event)
            return True
        if event.type() == QEvent.Type.KeyRelease and self.magnifier_controller.held:
            self.keyReleaseEvent(event)
            return True
        return False

    def eventFilter(self, watched, event) -> bool:
        if not hasattr(self, "_graphics") or self._graphics is None:
            return super().eventFilter(watched, event)
        graphics_target = watched is self._graphics or watched is self._graphics.viewport()
        if graphics_target:
            if (
                self.zoom.loupe_active
                and event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
                and hasattr(event, "position")
                and self.zoom.loupe_click(event)
            ):
                # The loupe owns the left click while it is armed: a zoom must not
                # also drop a caliper point on the frame under the pointer.
                return True
            if event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.RightButton:
                    # Freehand: right-click rolls back the last segment (B)
                    # instead of opening the save menu while a stroke is drawn.
                    if self.rollback_freehand_segment():
                        return True
                    # an idle right-press starts the radial-menu gesture
                    # (three controller entry points; the window owns it).
                    if (
                        self.radial_controller is not None
                        and not self._contour_mode_active
                        and not self._freehand_recording
                        and self.radial_controller.on_right_press(event.globalPosition())
                    ):
                        return True
                    self._show_save_context_menu(event)
                    return True
            if event.type() == QEvent.Type.MouseMove:
                if (
                    self.radial_controller is not None
                    and self.radial_controller.gesture_active
                    and hasattr(event, "globalPosition")
                    and self.radial_controller.on_pointer_move(event.globalPosition())
                ):
                    return True
                if self._drag_session is None and hasattr(event, "globalPosition"):
                    self._handle_contour_hover_at_global(event.globalPosition())
                # Keep the loupe glued to the cursor while Z is held: some
                # platforms do not deliver scene.sigMouseMoved reliably.
                magnifier = self.magnifier_controller
                if (
                    magnifier.lens is not None
                    and (magnifier.held or magnifier.persistent_active)
                    and hasattr(event, "position")
                ):
                    self._update_magnifier_loupe(self._graphics.mapToScene(event.position().toPoint()))
            if event.type() == QEvent.Type.Resize:
                self._position_hint_bar()
            if (
                event.type() == QEvent.Type.MouseButtonRelease
                and event.button() == Qt.MouseButton.LeftButton
                and self._drag_session is not None
                and hasattr(event, "globalPosition")
            ):
                self._handle_contour_drag_release_from_global(event.globalPosition())
            if (
                event.type() == QEvent.Type.MouseButtonRelease
                and event.button() == Qt.MouseButton.RightButton
                and self.radial_controller is not None
                and hasattr(event, "globalPosition")
                and self.radial_controller.on_right_release(event.globalPosition())
            ):
                return True
            # Forward key events (Delete/Backspace/Escape) so they reach
            # ViewerWidget.keyPressEvent — pyqtgraph.GraphicsView eats them
            # by sending them to the scene, which ignores unhandled ones.
            if event.type() == QEvent.Type.KeyPress:
                self.keyPressEvent(event)
                return event.isAccepted()
            if event.type() == QEvent.Type.KeyRelease:
                self.keyReleaseEvent(event)
                return event.isAccepted()
        return super().eventFilter(watched, event)

    # -- Magnifier loupe (variant B: offset, hold-Z) -------------------------
    @property
    def magnifier_controller(self) -> MagnifierController:
        """The single owner of magnifier state and of the loupe (issue 420)."""
        return self._magnifier_controller

    def _create_magnifier_lens(self):
        """Lens factory: the controller configures and tracks the widget.

        The lens stays a plain child of the viewer for lifetime reasons (§7.3:
        a QGraphicsEffect on a native sub-window crashed X11), so only the
        parentage is the viewer's business here.
        """
        from echo_personal_tool.presentation.magnifier_lens import MagnifierLens

        return MagnifierLens(self)

    def _magnifier_display(self):
        """Already-masked display buffer the loupe crops from."""
        try:
            return self._image_item.image
        except (AttributeError, RuntimeError):
            return None

    def _update_magnifier_loupe(self, scene_pos) -> None:  # type: ignore[no-untyped-def]  # mypy does not check this file (outside tool.mypy.files)
        """Event → controller translation; geometry and the lens live in the owner."""
        self._magnifier_controller.update_loupe(
            scene_pos,
            display=self._magnifier_display(),
            view_mapping=self._view.mapSceneToView,
        )

    def _hide_magnifier_on_point(self) -> None:
        # Point placed (click): the hold drops unless the persistent (second
        # point in a linear caliper) mode is armed — owned by the controller.
        self._magnifier_controller.notify_point_placed()

    def _scene_pos_under_cursor(self):  # type: ignore[no-untyped-def]  # mypy does not check this file (outside tool.mypy.files)
        """Scene position when the cursor is over the viewer, else None."""
        if not self.isVisible():
            return None
        try:
            global_pos = QCursor.pos()
        except RuntimeError:
            return None
        if not self.rect().contains(self.mapFromGlobal(global_pos)):
            return None
        graphics_local = self._graphics.mapFromGlobal(global_pos)
        if not self._graphics.rect().contains(graphics_local):
            return None
        return self._graphics.mapToScene(graphics_local)

    def _text_input_has_focus(self) -> bool:
        focus = QApplication.focusWidget()
        if focus is None:
            return False
        from PySide6.QtWidgets import QAbstractSpinBox, QComboBox, QLineEdit, QPlainTextEdit, QTextEdit

        return isinstance(focus, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox, QComboBox))

    def _sync_persistent_loupe(self) -> None:
        """The persistent-loupe predicate (linear B/M only) lives in the controller."""
        self._magnifier_controller.sync_persistent(
            bool(self._linear_caliper_active),
            doppler_mode=self.doppler.get_tool_mode(),
            vessel_status=self.doppler.overlay.vessel_status(),
        )

    @_prof
    def wheelEvent(self, event) -> None:
        if self._handle_wheel(event):
            event.accept()
        else:
            super().wheelEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_overlay_labels(reposition_results=True)
        self.doppler.reposition_manual_calibration_hint()

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

        # Position/pin ownership lives on the controller alone (issue #420
        # follow-up, slice 3); the widget only decides *whether* a reposition
        # is due this pass, same as for the other overlay labels above.
        self._results_overlay_controller.reposition(reposition_results=reposition_results)

        self.tags_overlay.reposition()

        if self._ste_sensitivity.isVisible():
            self._position_ste_overlay()

        if self._vessel_sensitivity.isVisible():
            self._position_vessel_sensitivity_overlay()

    def reset_results_overlay_to_default(self) -> None:
        self._results_overlay_controller.reset_to_default()

    def reset_results_overlay_cleared(self) -> None:
        """Allow measurements to reappear after a state change (study/frame switch)."""
        self._results_overlay_controller.reset_cleared()

    @property
    def results_overlay_controller(self) -> ResultsOverlayController:
        """Owner of the results overlay (position, pin state, style).

        Callers read the pin state here instead of through a forwarding method on
        the widget; the inventory of the remaining forwarding bridges is kept in
        docs/reviews/2026-11-05-qh-3-bridge-inventory-ru.md.
        """
        return self._results_overlay_controller

    # ── QH-3 ViewerContext + generation (S-02 isolation) ──────────────────

    def get_viewer_context(self) -> ViewerContext:
        """Current explicit context (identity + generation) for controllers."""
        if hasattr(self, "_viewer_context"):
            return self._viewer_context
        return ViewerContext()

    def _sync_viewer_context(self, *, bump_generation: bool = False) -> ViewerContext:
        """Rebuild ViewerContext from current state; bump generation on source change."""
        instance = self._current_state.instance if self._current_state is not None else None
        if instance is not None:
            identity = ViewerPaneIdentity(
                study_uid=getattr(instance, "study_uid", "") or "",
                sop_instance_uid=getattr(instance, "sop_instance_uid", "") or "",
                series_uid=getattr(instance, "series_uid", "") or "",
            )
        else:
            identity = ViewerPaneIdentity()
        # Generation bumps on source change (§5.2 dependency map, S-05)
        prev_uid = self._viewer_context.identity.sop_instance_uid if hasattr(self, "_viewer_context") else ""
        new_uid = identity.sop_instance_uid
        if bump_generation or (prev_uid and new_uid and prev_uid != new_uid):
            self._generation = getattr(self, "_generation", 0) + 1
        elif not hasattr(self, "_generation"):
            self._generation = 0
        # View transform (image size + view range) for hit-testing.
        # S2-02: narrow catches; a degraded snapshot is an explicit, logged
        # decision rather than a silent broad swallow.
        try:
            x_range, y_range = self._view.viewRange() if hasattr(self, "_view") else (None, None)
            view_range = (
                (float(x_range[0]), float(x_range[1]), float(y_range[0]), float(y_range[1]))
                if x_range and y_range
                else None
            )
        except (ArithmeticError, AttributeError, IndexError, RuntimeError, TypeError, ValueError) as exc:
            log_boundary_failure(logger, "viewer.context_sync", exc, code="invalid", level=logging.DEBUG)
            view_range = None
        try:
            vp_size = (
                (float(self._graphics.viewport().width()), float(self._graphics.viewport().height()))
                if hasattr(self, "_graphics")
                else None
            )
        except (ArithmeticError, AttributeError, IndexError, RuntimeError, TypeError, ValueError) as exc:
            log_boundary_failure(logger, "viewer.context_sync", exc, code="invalid", level=logging.DEBUG)
            vp_size = None
        try:
            img_size = tuple(self._current_frame.shape[1::-1]) if self._current_frame is not None else None  # (w,h)
        except (ArithmeticError, AttributeError, IndexError, RuntimeError, TypeError, ValueError) as exc:
            log_boundary_failure(logger, "viewer.context_sync", exc, code="invalid", level=logging.DEBUG)
            img_size = None
        vt = ViewTransform(
            view_range=view_range,
            viewport_size=vp_size,
            device_pixel_ratio=float(self._graphics.devicePixelRatioF()) if hasattr(self, "_graphics") else 1.0,
            image_size=img_size,
        )
        spacing = getattr(self._current_state, "effective_pixel_spacing", None) if self._current_state else None
        if callable(spacing):
            spacing = spacing()
        ctx = ViewerContext(
            identity=identity,
            frame_index=self._current_state.current_frame_index if self._current_state else 0,
            total_frames=self._current_state.total_frames if self._current_state else 0,
            generation=self._generation,
            pixel_spacing=spacing,
            view_transform=vt,
        )
        self._viewer_context = ctx
        # Propagate to all controllers (S-02 isolation)
        for c in getattr(self, "_all_qh3_controllers", ()):
            if hasattr(c, "set_context"):
                try:
                    c.set_context(ctx)
                except Exception as exc:  # noqa: BLE001, S110
                    log_boundary_failure(logger, "viewer.context_propagate", exc, code="ui", level=logging.DEBUG)
            else:
                try:
                    c.context = ctx
                except Exception as exc:  # noqa: BLE001, S110
                    log_boundary_failure(logger, "viewer.context_propagate", exc, code="ui", level=logging.DEBUG)
        return ctx

    def dispose_viewer_resources(self) -> None:
        """Owner-scoped teardown: idempotent, breaks QObject cycles (§7.3)."""
        for c in getattr(self, "_all_qh3_controllers", ()):
            dispose = getattr(c, "dispose", None)
            if callable(dispose):
                try:
                    dispose()
                except RuntimeError:
                    pass
        doppler = getattr(self, "doppler", None)
        if doppler is not None:
            try:
                doppler.dispose()
            except RuntimeError:
                pass
        # The transport is not generation-scoped, so it is not in the
        # controller inventory; it still owns a debounce timer that must stop.
        transport = getattr(self, "transport", None)
        if transport is not None:
            transport.dispose()
        # Break the relay cycle that segfaults on Linux if not deleted before GC
        relay = getattr(self, "_loupe_key_relay", None)
        if relay is not None:
            self._remove_loupe_key_relay()
        # Timers that accumulate if not stopped (50/500-cycle budget)
        import warnings

        for attr in ("_calibration_ok_timer",):
            t = getattr(self, attr, None)
            if t is not None:
                try:
                    t.stop()
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", RuntimeWarning)
                        t.timeout.disconnect()
                except (RuntimeError, TypeError):
                    pass
        # S2-04: no measurement data survives beyond tab/viewer life.
        self.clear_undo_redo()

    def qh3_controller_inventory(self) -> list[str]:
        """Names of owner-scoped controllers (lifecycle harness checks they are gone)."""
        return [type(c).__name__ for c in getattr(self, "_all_qh3_controllers", ())]

    @_prof
    def _on_results_overlay_clear(self) -> None:
        self._results_overlay_controller.mark_cleared()
        self._stored_linear_measurements.clear()
        self._clear_persistent_linear_calipers()
        self._emit_stored_linear_measurements()
        self.set_results_overlay("")

    def _on_results_overlay_reset_position(self) -> None:
        self.reset_results_overlay_to_default()

    def _on_results_overlay_pin_toggled(self, pinned: bool) -> None:
        if pinned:
            self._results_overlay_label.setCursor(Qt.CursorShape.ArrowCursor)
            if self._results_overlay_controller.custom_position():
                x_ratio, y_ratio = self._results_overlay_controller.position()
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
        self._phi_filter.set_enabled(preferences.anonymize_frames)
        self._phi_filter.set_top_percent(preferences.phi_mask_top_percent)
        self._show_crosshair = preferences.show_crosshair
        # Issue 420: applying preferences is one configure() on the single
        # owner — no local copy of the magnifier settings to drift out of sync.
        if hasattr(self, "_magnifier_controller"):
            try:
                self._magnifier_controller.configure(
                    enabled=preferences.magnifier_enabled,
                    zoom=preferences.magnifier_zoom,
                    radius_px=preferences.magnifier_radius_px,
                    linear_persistent=preferences.magnifier_linear_persistent,
                    reduce_motion=preferences.reduce_motion,
                )
            except Exception as exc:  # noqa: BLE001, S110
                log_boundary_failure(logger, "magnifier.configure", exc, code="ui", level=logging.DEBUG)
        # Overlay style via controller (pure formatting stays in domain)
        if hasattr(self, "_results_overlay_controller"):
            try:
                self._results_overlay_controller.apply_style(
                    preferences.results_overlay_font_size, preferences.results_overlay_opacity
                )
            except Exception as exc:  # noqa: BLE001, S110
                log_boundary_failure(logger, "results_overlay.apply_style", exc, code="ui", level=logging.DEBUG)
        self.tags_overlay.configure(
            preferences.interesting_dicom_tags,
            preferences.results_overlay_font_size,
            preferences.results_overlay_opacity,
        )
        self._show_panel_frames = preferences.show_panel_frames
        self._show_caliper_labels_on_frame = preferences.show_caliper_labels_on_frame
        self._show_caliper_inline_labels = preferences.show_caliper_inline_labels
        self.doppler.set_show_calibration_roi(preferences.show_doppler_calibration_roi)
        self._render_persistent_linear_calipers()
        self.doppler.set_auto_calibration_enabled(preferences.doppler_auto_calibration_enabled)
        self._calibration_tick_snap_enabled = preferences.calibration_tick_snap_enabled
        self._length_display_unit = preferences.length_display_unit
        self._tenth_mm_precision = bool(getattr(preferences, "measurement_precision_tenth_mm", True))
        self.set_label_picker_enabled(preferences.label_picker_enabled)
        self.set_magnetic_snap_enabled(preferences.magnetic_snap_enabled)
        self._magnetic_snap_weight_threshold = preferences.magnetic_snap_weight_threshold
        self._magnetic_snap_release_strength = preferences.magnetic_snap_release_strength
        self._magnetic_snap_release_max_radial_px = preferences.magnetic_snap_release_max_radial_px
        self._despeckle_enabled = preferences.despeckle_enabled
        self._rebuild_contour_pens(preferences)
        self._refresh_caliper_line_pens()
        self._refresh_rendered_contour_pens()
        self._apply_window_level_preferences(preferences)
        self._refresh_panel_frame_graphics()
        self.tags_overlay.refresh()
        if not self._show_caliper_labels_on_frame:
            self._measurement_label.hide()
        self._position_overlay_labels()

    def reload_text(self) -> None:
        self.transport.retranslate()
        self._results_overlay_label.setAccessibleName(tr("a11y.results_overlay"))
        self._results_overlay_label.setAccessibleDescription(tr("a11y.results_overlay_desc"))
        if (loop := self.findChild(LoopControls)) is not None:
            loop.reload_text()
        if self._current_state is not None:
            total = self._current_state.total_frames
            current = self._current_state.current_frame_index + 1 if total > 0 else 0
            self.transport.refresh_labels(current=current, total=total, is_playing=self._current_state.is_playing)
        else:
            self.transport.fix_play_button_width()
        self._fix_phase_label_width()
        self.doppler.reload_text()
        self._ste_sensitivity.reload_text()

    def _build_cine_transport(self) -> None:
        """Build the shared cine timeline through its transport owner."""
        self._phase_strip = CinePhaseStrip(translate=tr)
        self._phase_strip.hide()
        self._phase_strip.frame_selected.connect(self._on_phase_frame_selected)
        self._phase_strip.marker_moved.connect(self._on_phase_marker_moved)
        self._phase_strip.marker_reset_requested.connect(self._on_phase_marker_reset)
        self._phase_timeline: PhaseTimeline | None = None
        self._phase_label = QLabel("")
        self.transport = ViewerTransport(
            parent=self,
            loop=self.findChild(LoopControls),
            phase_strip=self._phase_strip,
            phase_label=self._phase_label,
        )
        self.transport.play_pause_requested.connect(self.play_pause_requested.emit)
        self.transport.frame_selected.connect(self._relay_frame_selected)
        self.transport.scroll_frame_selected.connect(self.scroll_frame_selected.emit)
        self.transport.fps_override_requested.connect(self.fps_override_requested.emit)
        # Reserve the width of the longest phase caption so the label never
        # appears/disappears and pushes the «Frame: …» counter sideways.
        self._fix_phase_label_width()

    def _relay_frame_selected(self, value: int) -> None:
        """Keep the historical guard: programmatic state sync is silent."""
        if not self._syncing_state:
            self.frame_selected.emit(value)

    def _fix_phase_label_width(self) -> None:
        """Pin the phase caption to the widest localized phase name (fixed phase text)."""
        longest = max(
            (
                tr("cine.phase.label_systole"),
                tr("cine.phase.label_diastole"),
                tr("cine.phase.label_unknown"),
            ),
            key=len,
        )
        margins = self._phase_label.contentsMargins()
        width = (
            self._phase_label.fontMetrics().horizontalAdvance(longest)
            + margins.left()
            + margins.right()
            + 2 * self._phase_label.margin()
            + 2
        )
        self._phase_label.setFixedWidth(width)

    def _rebuild_contour_pens(self, preferences: UserPreferences) -> None:
        manual_width = preferences.contour_pen_manual_width
        ai_width = preferences.contour_pen_ai_width
        simpson_width = preferences.contour_pen_simpson_width
        self._contour_pen_manual = pg.mkPen(dark_theme.get_theme_tokens()["overlay.contour.manual"], width=manual_width)
        self._contour_pen_ai = pg.mkPen(dark_theme.get_theme_tokens()["overlay.contour.auto"], width=ai_width)
        self._contour_pen_ai_pending = pg.mkPen(
            dark_theme.get_theme_tokens()["overlay.contour.auto"], width=ai_width, style=Qt.PenStyle.DashLine
        )
        self._contour_pen_model = pg.mkPen(dark_theme.get_theme_tokens()["overlay.contour.model"], width=simpson_width)
        ma_width = max(1.0, manual_width * 0.5)
        self._contour_pen_ma = pg.mkPen(
            dark_theme.get_theme_tokens()["overlay.contour.manual"], width=ma_width, style=Qt.PenStyle.DashLine
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
            self._linear_caliper_line_item.setPen(self._caliper_pen(dark_theme.get_theme_tokens()["overlay.caliper"]))
        if self._linear_caliper_marker_item is not None:
            self._linear_caliper_marker_item.setPen(self._caliper_pen(dark_theme.get_theme_tokens()["overlay.caliper"]))
        for item in self._persistent_linear_graphics:
            line_item, start_node, end_node = item[0], item[1], item[2]
            pen = self._caliper_pen(dark_theme.get_theme_tokens()["overlay.caliper.doppler"])
            line_item.setPen(pen)
            start_node.setPen(pen)
            end_node.setPen(pen)
        if self._calibration_line_item is not None:
            self._calibration_line_item.setPen(
                self._caliper_pen(dark_theme.get_theme_tokens()["overlay.caliper.doppler"])
            )
        if self._calibration_marker_item is not None:
            self._calibration_marker_item.setPen(
                self._caliper_pen(dark_theme.get_theme_tokens()["overlay.caliper.doppler"])
            )

    def _apply_window_level_preferences(self, preferences: UserPreferences) -> None:
        window, level, dr = resolve_wl_values(preferences)
        for slider, value in (
            (self.display.window_slider, window),
            (self.display.level_slider, level),
            (self.display.dr_slider, dr),
        ):
            slider.blockSignals(True)
            slider.setValue(value)
            slider.blockSignals(False)
        self.display.update_levels()

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
            pen = pg.mkPen(dark_theme.get_theme_tokens()["overlay.point"], width=1)
            item = pg.PlotDataItem(pen=pen)
            item.setZValue(12)
            item.setData(
                [bounds.x0, bounds.x1, bounds.x1, bounds.x0, bounds.x0],
                [bounds.y0, bounds.y0, bounds.y1, bounds.y1, bounds.y0],
            )
            self._view.addItem(item)
            self._panel_frame_items.append(item)

    def _current_instance_metadata(self):
        if self._current_state is not None and self._current_state.instance is not None:
            return self._current_state.instance
        return None

    @_prof
    def set_transport_visible(self, visible: bool) -> None:
        """Show or hide the built-in cine strip (UI-6 uses the floating plate)."""
        self.transport.bar.setVisible(bool(visible))

    def transport_visible(self) -> bool:
        return self.transport.bar.isVisible()

    def set_results_overlay_suppressed(self, suppressed: bool) -> None:
        """Hide the on-image results box while the focus card shows the same values.

        The text is not discarded: the window re-syncs it when the focus view is
        left, so a measurement made inside focus is not lost.
        """
        self._results_overlay_controller.set_suppressed(suppressed)

    def results_overlay_suppressed(self) -> bool:
        return self._results_overlay_controller.is_suppressed()

    def set_results_overlay(self, text: str) -> None:
        """Show session measurement summary (top-right box, left-aligned text)."""
        result = self._results_overlay_controller.set_text(text)
        if result.reason == "erased":
            self.tags_overlay.reposition()

    @property
    def is_debug_overlay_visible(self) -> bool:
        return self._debug_overlay_visible

    def debug_overlay_text(self) -> str:
        """Text of the debug overlay while it is on; an empty string while it is off."""
        return self._debug_overlay_label.text() if self._debug_overlay_visible else ""

    @_prof
    def toggle_debug_overlay(self) -> None:
        self._debug_overlay_visible = not self._debug_overlay_visible
        if self._debug_overlay_visible:
            self._update_debug_overlay()
            self._debug_overlay_label.show()
        else:
            self._debug_overlay_label.hide()
            self._draw_debug_roi_rect(None)
        self._debug_roi_item: pg.PlotDataItem | None = None

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
                lines.append(f"Scale: {format_scale_factor(scale)}x")
        dpr = self._graphics.devicePixelRatioF()
        lines.append(f"DPR: {format_dpr(dpr)}")
        if self._current_state and self._current_state.instance:
            inst = self._current_state.instance
            lines.append(f"Format: {inst.media_format}")
            lines.append(f"Frames: {inst.number_of_frames}")
        # ROI info
        roi = self._get_last_segment_roi()
        if roi is not None:
            x0, y0, x1, y1 = roi
            lines.append(f"ROI: {int(x0)},{int(y0)}-{int(x1)},{int(y1)}")
        self._debug_overlay_label.setText("\n".join(lines))
        self._debug_overlay_label.adjustSize()
        geo_viewer = self._graphics.geometry()
        self._debug_overlay_label.move(
            geo_viewer.x() + 4,
            geo_viewer.y() + 4,
        )
        self._debug_overlay_label.raise_()
        # Draw ROI rectangle on ViewBox
        self._draw_debug_roi_rect(roi)

    def _get_last_segment_roi(self) -> tuple[float, float, float, float] | None:
        """Get last auto-segment ROI from the controller (if a provider was wired)."""
        if self._last_segment_roi_provider is not None:
            return self._last_segment_roi_provider()
        return None

    def _draw_debug_roi_rect(self, roi: tuple[float, float, float, float] | None) -> None:
        """Draw ROI rectangle on ViewBox when debug overlay is visible."""
        # Remove previous ROI rect
        if hasattr(self, "_debug_roi_item") and self._debug_roi_item is not None:
            self._view.removeItem(self._debug_roi_item)
            self._debug_roi_item = None

        if roi is None or not self._debug_overlay_visible:
            return

        x0, y0, x1, y1 = roi
        pen = pg.mkPen("#ff0000", width=1, style=Qt.PenStyle.DashLine)
        rect_item = pg.PlotDataItem(
            pen=pen,
            connect="all",
        )
        rect_item.setZValue(25)
        # Draw rectangle as closed polygon
        rect_item.setData(
            [x0, x1, x1, x0, x0],
            [y0, y0, y1, y1, y0],
        )
        self._view.addItem(rect_item)
        self._debug_roi_item = rect_item

    def _mark_results_overlay_custom_position(self) -> None:
        self._results_overlay_controller.mark_custom_position()

    def results_overlay_custom_position(self) -> bool:
        return self._results_overlay_controller.custom_position()

    def set_results_overlay_position(
        self,
        x_ratio: float,
        y_ratio: float,
        *,
        custom: bool = True,
    ) -> None:
        self._results_overlay_controller.set_position(x_ratio, y_ratio, custom=custom)

    def results_overlay_position(self) -> tuple[float, float]:
        return self._results_overlay_controller.position()

    @_prof
    def reposition_overlays(self) -> None:
        self._position_overlay_labels(reposition_results=not self._results_overlay_controller.custom_position())

    def results_overlay_text(self) -> str:
        return self._results_overlay_controller.text()

    def _position_overlay_label(self) -> None:
        self._position_overlay_labels()

    def _show_save_context_menu(self, ev) -> None:
        from echo_personal_tool.presentation.system_bar import _load_icon

        menu = QMenu(self)
        menu.addAction(tr("viewer.context_save_as"), self._save_viewer_image)
        self._add_gold_export_actions(menu)
        menu.addSeparator()
        menu.addAction(
            _load_icon("tune"),
            tr("system_bar.calibration_bmode"),
            self.context_calibration_bmode_requested.emit,
        )
        menu.addAction(
            _load_icon("show_chart"),
            tr("system_bar.calibration_doppler"),
            self.context_doppler_calibration_requested.emit,
        )
        menu.addAction(tr("tool_panel.properties"), self.context_properties_requested.emit)
        menu.addSeparator()
        menu.addAction(
            _load_icon("refresh"),
            tr("system_bar.reset"),
            self.context_reset_requested.emit,
        )
        menu.exec(QCursor.pos())

    def _add_gold_export_actions(self, menu: QMenu) -> None:
        """Add gold export menu items when conditions are met."""
        import os

        from echo_personal_tool.application.user_preferences import gold_annotation_enabled

        gold_enabled = gold_annotation_enabled()
        if not gold_enabled and os.environ.get("ECHO_GOLD_EXPORT", "") != "1":
            return
        if self._current_state is None or self._current_state.instance is None:
            return
        if self._current_state.instance.media_format != "dicom":
            return

        frame_index = self._current_state.current_frame_index
        for contour in self._stored_contours:
            if (
                contour.chamber in ("LV", "LA")
                and contour.view == "A4C"
                and not contour.review_pending
                and (contour.frame_index is None or contour.frame_index == frame_index)
            ):
                phase = contour.phase
                if phase in ("ED", "ES"):
                    chamber = contour.chamber
                    label = tr(
                        "viewer.context_save_gold",
                        phase=phase,
                        frame=frame_index,
                    )
                    menu.addAction(
                        label,
                        lambda p=phase, fi=frame_index, ch=chamber: self.gold_export_requested.emit(p, fi, ch),
                    )

    def _save_viewer_image(self) -> None:
        if self._current_frame is None:
            return
        from echo_personal_tool.presentation.styled_dialogs import styled_save_file

        path, _ = styled_save_file(
            self,
            tr("viewer.context_save_frame"),
            "",
            "PNG (*.png)",
        )
        if not path:
            return
        path = _force_png_suffix(path)
        full = self.grab()
        if full.isNull():
            QMessageBox.warning(self, tr("viewer.save_frame_failed.title"), tr("viewer.save_frame_failed.grab"))
            return
        geo = self._graphics.geometry()
        cropped = full.copy(geo.x(), geo.y(), geo.width(), geo.height())
        if cropped.isNull():
            QMessageBox.warning(
                self, tr("viewer.save_frame_failed.title"), tr("viewer.save_frame_failed.body", path=path)
            )
            return
        self.composite_frame_export(cropped, geo)
        if not cropped.save(path):
            QMessageBox.warning(
                self, tr("viewer.save_frame_failed.title"), tr("viewer.save_frame_failed.body", path=path)
            )

    def composite_frame_export(self, capture: QPixmap, geo: QRect) -> None:
        """Paint the pyqtgraph scene and the Qt overlay labels into *capture*.

        ``QWidget.grab()`` cannot read back a QOpenGLWidget viewport: the GL
        scene is drawn into its own framebuffer and is never part of the
        ancestor's paint, so on GPU-backed machines (``useOpenGL=True``) the raw
        capture is a blank sheet showing only the Qt-drawn overlay labels.
        ``QGraphicsView.render()`` draws the scene with a plain QPainter, which
        works for both the GL and the raster viewport; the overlay labels are
        re-drawn on top of it afterwards.
        """
        painter = QPainter(capture)
        try:
            viewport = self._graphics.viewport()
            source = viewport.rect() if viewport is not None else self._graphics.rect()
            self._graphics.render(painter, QRect(QPoint(0, 0), capture.size()), source)
            for child in self.children():
                if not isinstance(child, QWidget) or child is self._graphics:
                    continue
                child_geo = child.geometry()
                if not child.isVisible() or not child_geo.intersects(geo):
                    continue
                painter.save()
                painter.translate(child_geo.x() - geo.x(), child_geo.y() - geo.y())
                child.render(painter, QPoint(0, 0))
                painter.restore()
        finally:
            painter.end()

    def _resolve_display_mode(
        self,
        frame: np.ndarray,
        media_format: str | None,
    ) -> tuple[bool, bool]:
        """Return (color_display, window_level_enabled).

        Colour is decided by :func:`~echo_personal_tool.imaging.display.is_color_frame`
        alone, for DICOM and video alike.  The former «effectively grayscale at
        tolerance 24» gate was evaluated *before* the colour test, so a frame
        whose colour box is small — a spectral Doppler screen with a 2D colour
        reference, the usual echo layout — was declared grayscale and its ЦДК
        disappeared (UI acceptance 2026-10-23, item 6).  A packed B-mode frame
        still answers «no colour»: its channels are equal, so the coloured share
        is zero.  Window/level belongs to monochrome frames only.
        """
        if frame.ndim == 3 and frame.shape[2] >= 3 and is_color_frame(frame):
            return True, False
        return False, True

    def _frame_confirms_color(self, instance_key: object, frame: np.ndarray, media_format: str | None) -> bool:
        """Whether this frame (or an earlier one of the same clip) carries colour.

        Colour is sticky per instance: once a clip showed a colour Doppler jet,
        every frame of it is drawn in colour — a frame with a small or absent jet
        must not fall back to gray and make the display flicker.  Returning True
        also updates the cached display mode, so the caller renders the RGB frame
        instead of the grayscale copy.
        """
        del media_format  # channel order is handled by the caller
        if instance_key in self._color_instances:
            return True
        if frame.ndim != 3 or frame.shape[2] < 3 or not is_color_frame(frame):
            return False
        if len(self._color_instances) >= _COLOR_INSTANCE_MEMORY:
            # A long playlist must not grow the memory without a bound; the
            # oldest clip simply re-detects its colour on the next frame.
            self._color_instances.pop()
        self._color_instances.add(instance_key)
        return True

    @property
    def _color_display_active(self) -> bool:
        """Whether the frame is drawn in colour right now.

        The «Убрать цвет» (grayscale) switch of the tool panel keeps the source
        RGB for detection and for measurements but shows the grayscale copy; it
        must never erase the colour of a Doppler clip on its own (that switch is
        the only thing allowed to).
        """
        return self._is_color_frame and not self._despeckle_enabled

    def mask_phi(self, pixels: np.ndarray) -> np.ndarray:
        """Mask burned-in PHI on a frame outside the render path.

        Used where frames are consumed directly rather than drawn — the M-mode
        sweep rebuilt from cached frames, and later the export seams.  Keeps one
        owner of the profile and of the on/off switch.
        """
        return self._phi_filter.apply(pixels, self._phi_mask_source_path())

    @property
    def phi_masking_enabled(self) -> bool:
        """Whether frames are anonymized on display — one switch for all paths.

        Export asks the viewer instead of reading preferences again, so a file
        exported right after the checkbox was toggled behaves like the frame on
        screen.
        """
        return self._phi_filter.enabled

    def _phi_mask_source_path(self) -> Path | None:
        """Path of the file currently displayed, used to pick a PHI profile."""
        if self._current_state is None or self._current_state.instance is None:
            return None
        return self._current_state.instance.path

    @property
    def contract(self) -> ViewerContract:
        """Declared inspection seam for the viewer tests (issue 327).

        Tests use ``w.contract.<name>`` instead of ``w._<name>``; the adapter
        owns the mapping in one place, so splitting this widget no longer
        breaks hundreds of tests. See ``presentation/viewer_contract.py``.
        """
        return ViewerContract(self)

    @property
    def has_frame(self) -> bool:
        """True once a frame has been shown."""
        return self._current_frame is not None

    @property
    def frame_shape(self) -> tuple[int, int] | None:
        """(height, width) of the frame on screen, also for a colour frame; ``None`` without a frame."""
        if self._current_frame is None:
            return None
        height, width = self._current_frame.shape[:2]
        return int(height), int(width)

    @property
    def is_window_level_enabled(self) -> bool:
        """False for colour frames and display modes where window/level does not apply."""
        return self._window_level_enabled

    @_prof
    def show_frame(self, pixels: np.ndarray) -> None:
        """Render a 2D grayscale (H, W) or color BGR (H, W, 3) array."""
        self._vessel_sensitivity.hide()
        frame = np.asarray(pixels)
        frame = self._phi_filter.apply(frame, self._phi_mask_source_path())
        media_format = (
            self._current_state.instance.media_format
            if self._current_state is not None and self._current_state.instance is not None
            else None
        )
        # Cache display mode per INSTANCE (file), not per frame.
        instance_uid = None
        if self._current_state is not None and self._current_state.instance is not None:
            instance_uid = self._current_state.instance.sop_instance_uid
        instance_key = instance_uid or id(frame)
        if self._frame_confirms_color(instance_key, frame, media_format):
            self._is_color_frame, self._window_level_enabled = True, False
            self._display_mode_cache_key = instance_key
        elif not hasattr(self, "_display_mode_cache_key") or self._display_mode_cache_key != instance_key:
            self._is_color_frame, self._window_level_enabled = self._resolve_display_mode(
                frame,
                media_format,
            )
            self._display_mode_cache_key = instance_key
            # Invalidate cached levels when switching to a new file/instance
            self.display.invalidate_cached_levels()
            self._display_mode_cache_key = instance_key
        channel_order = "rgb" if media_format == "dicom" else "bgr"
        self._current_frame = to_grayscale_array(frame)
        if self._despeckle_enabled:
            from echo_personal_tool.imaging.display import despeckle_frame

            self._current_frame = despeckle_frame(self._current_frame)

        if self._color_display_active:
            self._color_source_rgb = to_display_rgb(frame, channel_order=channel_order)
            self._image_item.setImage(self._color_source_rgb, autoLevels=False)
            if self._window_level_enabled:
                self.display.update_levels()
            else:
                self._image_item.setLevels((0, 255))
        else:
            self._color_source_rgb = None
            gray = self._current_frame
            self._image_item.setImage(gray, autoLevels=False)
            if self._window_level_enabled:
                self.display.update_levels()
            else:
                vmin = float(gray.min()) if gray.size else 0.0
                vmax = float(gray.max()) if gray.size else 255.0
                if vmin == vmax:
                    vmax = vmin + 1.0
                self._image_item.setLevels((vmin, vmax))
            new_path = (
                Path(self._current_state.instance.path)
                if self._current_state and self._current_state.instance and self._current_state.instance.path
                else None
            )
            self.display.set_current_path(new_path)
        self.display.set_enabled(self._window_level_enabled)
        if self._current_frame is not None:
            height, width = self._current_frame.shape[:2]
            self._view.setRange(xRange=(0, width), yRange=(0, height), padding=0)
            self._refresh_frame_panel_layout()
            self.doppler.configure_axis_for_frame()
            self._invalidate_edge_map_cache()
            if self.mmode.line_item is not None and self.mmode.line_item.is_complete:
                start, end = self.mmode.line_item.get_endpoints()
                # Convert view coords (invertY=True) to image coords (Y=0 at top)
                h = self._current_frame.shape[0]
                start_img = (start[0], h - start[1])
                end_img = (end[0], h - end[1])
                col = extract_mmode_column(self._current_frame, start_img, end_img, num_samples=256)
                frame_idx = self._current_state.current_frame_index if self._current_state else 0
                self.mmode_column_ready.emit(col, frame_idx)
        self._update_debug_overlay()
        self.zoom.apply_mode()

    def cycle_zoom_mode(self) -> None:
        self.zoom.cycle_mode()

    def set_zoom_mode(self, mode: str) -> None:
        self.zoom.set_mode(mode)

    @property
    def zoom_mode(self) -> str:
        return self.zoom.mode

    @property
    def zoom_factor(self) -> float:
        """Factor of the manual zoom (wheel, loupe); 1.0 in the fit, 100% and 200% modes."""
        return self.zoom.factor

    @_prof
    def show_frame_fast(self, pixels: np.ndarray) -> None:
        """Fast render for playback: skip layout/doppler/panel detection."""
        frame = np.asarray(pixels)
        frame = self._phi_filter.apply(frame, self._phi_mask_source_path())
        media_format = (
            self._current_state.instance.media_format
            if self._current_state is not None and self._current_state.instance is not None
            else None
        )
        # Cache display mode per INSTANCE (file), not per frame.
        # Using id(frame) caused re-detection every frame → color/grayscale flickering.
        instance_uid = None
        if self._current_state is not None and self._current_state.instance is not None:
            instance_uid = self._current_state.instance.sop_instance_uid
        instance_key = instance_uid or id(frame)
        if self._frame_confirms_color(instance_key, frame, media_format):
            self._is_color_frame, self._window_level_enabled = True, False
            self._display_mode_cache_key = instance_key
        elif not hasattr(self, "_display_mode_cache_key") or self._display_mode_cache_key != instance_key:
            self._is_color_frame, self._window_level_enabled = self._resolve_display_mode(
                frame,
                media_format,
            )
            self._display_mode_cache_key = instance_key
            # Invalidate cached levels when switching to a new file
            self.display.invalidate_cached_levels()
        channel_order = "rgb" if media_format == "dicom" else "bgr"

        # NOTE: _cached_levels_key is deliberately NOT written here. It records the slider
        # values the cached display levels belong to, so only the display owner may set it.
        # Stamping it per frame made the freshness check inside the display owner trivially
        # true (and, with the key order the two methods used to disagree on, permanently
        # false), so the W/L window was either frozen or recomputed on every frame.

        # NOTE: no per-frame derived-data cache keyed on the frame's memory
        # address.  Decoded and PHI-masked frames are fresh temporaries; the
        # allocator recycles their addresses, so an address-keyed cache
        # false-hits after the first frame and the viewer keeps re-rendering an
        # older frame (frozen playback, stale/artefact frames on scroll).
        if self._color_display_active:
            self._color_source_rgb = to_display_rgb(frame, channel_order=channel_order)
            self._current_frame = to_grayscale_array(frame)
            self._image_item.setImage(self._color_source_rgb, autoLevels=False)
            if self._window_level_enabled:
                self.display.update_levels()
            else:
                self._image_item.setLevels((0, 255))
        else:
            self._color_source_rgb = None
            # Skip float64 conversion — pyqtgraph displays uint8 directly
            if frame.ndim == 2:
                self._current_frame = frame
            elif frame.ndim == 3 and frame.shape[2] >= 3:
                # SIMD: cv2.cvtColor returns WRITABLE contiguous uint8
                frame_c = np.ascontiguousarray(frame)  # Safety for cv2
                if channel_order == "bgr":
                    self._current_frame = cv2.cvtColor(frame_c[..., :3], cv2.COLOR_BGR2GRAY)
                else:
                    self._current_frame = cv2.cvtColor(frame_c[..., :3], cv2.COLOR_RGB2GRAY)
            else:
                self._current_frame = frame[..., 0] if frame.ndim == 3 else frame
            if self._despeckle_enabled:
                from echo_personal_tool.imaging.display import despeckle_frame

                self._current_frame = despeckle_frame(self._current_frame)
            if self._window_level_enabled:
                # W/L path: the display owner will call setImage with the LUT result.
                # Skip redundant 1st setImage to avoid double GPU texture upload.
                self.display.update_levels()
            else:
                self._image_item.setImage(self._current_frame, autoLevels=False)
                vmin = float(self._current_frame.min()) if self._current_frame.size else 0.0
                vmax = float(self._current_frame.max()) if self._current_frame.size else 255.0
                if vmin == vmax:
                    vmax = vmin + 1.0
                self._image_item.setLevels((vmin, vmax))
        self.display.sync_external_enabled()
        if self._current_frame is not None and self.mmode.line_item is not None and self.mmode.line_item.is_complete:
            start, end = self.mmode.line_item.get_endpoints()
            # Convert view coords (invertY=True) to image coords (Y=0 at top)
            h = self._current_frame.shape[0]
            start_img = (start[0], h - start[1])
            end_img = (end[0], h - end[1])
            col = extract_mmode_column(self._current_frame, start_img, end_img, num_samples=256)
            frame_idx = self._current_state.current_frame_index if self._current_state else 0
            self.mmode_column_ready.emit(col, frame_idx)

    @_prof
    def refresh_after_scroll(self) -> None:
        """Restore layout/overlays after fast scroll without reprocessing pixels."""
        if self._current_frame is not None:
            height, width = self._current_frame.shape[:2]
            # Preserve zoom if user has zoomed in (custom or 100%/200%)
            if self.zoom.preserve_range:
                pass  # keep current view range, don't reset
            else:
                self._view.setRange(xRange=(0, width), yRange=(0, height), padding=0)
            if self._window_level_enabled:
                self.display.update_levels()
            self._refresh_frame_panel_layout()
            self.doppler.configure_axis_for_frame()
            self._invalidate_edge_map_cache()

    def clear(self) -> None:
        self._image_item.clear()
        self._clear_linear_caliper()
        self._clear_calibration_caliper()
        self._clear_contours()
        self._clear_persistent_linear_calipers()
        self._clear_ghost_overlay()

    def set_phase_timeline(self, timeline: PhaseTimeline | None) -> None:
        """Show a detected phase annotation on the playback bar."""
        self._phase_timeline = timeline
        self._phase_strip.set_timeline(timeline)
        self._phase_strip.setVisible(timeline is not None and bool(timeline.markers()))
        self._update_phase_label()

    def _update_phase_label(self, *, frame: int | None = None) -> None:
        if frame is None:
            frame = self.transport.timeline_slider.value()
        phase = self._phase_strip.phase_at(frame)
        tokens = dark_theme.get_theme_tokens()
        if phase == PHASE_SYSTOLE:
            text, color = tr("cine.phase.label_systole"), tokens["state.err"]
        elif phase == PHASE_DIASTOLE:
            text, color = tr("cine.phase.label_diastole"), tokens["state.info"]
        elif self._phase_timeline is not None and self._phase_timeline.source != "unavailable":
            text, color = tr("cine.phase.label_unknown"), tokens["text.disabled"]
        else:
            text, color = "", tokens["text.disabled"]
        if self._phase_label.text() != text:
            self._phase_label.setText(text)
        self._phase_label.setStyleSheet(f"color: {color}; font-size: 10px;")

    def _on_phase_frame_selected(self, frame: int) -> None:
        self.transport.select_frame(frame)

    def _on_phase_marker_moved(self, cycle_index: int, kind: str, frame: int) -> None:
        timeline = self._phase_timeline
        if timeline is None or not (0 <= cycle_index < len(timeline.cycles)):
            return
        cycle = timeline.cycles[cycle_index]
        ed_frame = frame if kind == "ed" else cycle.ed_frame
        es_frame = frame if kind == "es" else cycle.es_frame
        self.set_phase_timeline(timeline.with_manual_ed_es(cycle_index, ed_frame, es_frame))

    def _on_phase_marker_reset(self, cycle_index: int, kind: str) -> None:  # noqa: ARG002
        base = self._phase_strip.base_timeline()
        if base is not None:
            self.set_phase_timeline(base)

    def set_transport_state(
        self,
        *,
        frame_index: int,
        total_frames: int,
        frame_time_ms: float | None,
        is_playing: bool,
    ) -> None:
        """Update only the transport widgets (slider, counters, play button).

        Used by the Multiview panes, which drive frames through their own loader
        instead of a ``ViewerState``.  No measurement or contour state is
        touched, so a pane never inherits the annotations of another clip.
        """
        try:
            total = max(0, int(total_frames))
            target = min(max(0, int(frame_index)), max(0, total - 1))
            self.transport.apply_frame_time(
                frame_index=frame_index,
                total_frames=total,
                frame_time_ms=frame_time_ms,
                is_playing=is_playing,
            )
            self._phase_strip.set_total_frames(total)
            self._phase_strip.set_current_frame(target)
            loop = self.findChild(LoopControls)
            if loop is not None:
                loop.set_total_frames(total)
                loop.set_current_frame(target)
            self._update_phase_label(frame=target)
        except RuntimeError:
            # Widget already destroyed during window teardown.
            return

    def current_state(self) -> ViewerState | None:
        """The state last passed to :meth:`set_state`; ``None`` before the first one."""
        return self._current_state

    @_prof
    def set_state(self, viewer_state: ViewerState) -> None:
        if self._syncing_state:
            self._pending_viewer_state = viewer_state
            return
        self._syncing_state = True
        # Reset overlay cleared flag so measurements can reappear after state changes
        self._results_overlay_controller.reset_cleared()
        previous_instance = self._current_state.instance if self._current_state else None
        previous_frame = self._current_state.current_frame_index if self._current_state else None
        frame_changed = previous_frame != viewer_state.current_frame_index
        if previous_instance != viewer_state.instance:
            # Save WL/DR for the old instance
            if previous_instance is not None:
                self.display.remember_instance(previous_instance.sop_instance_uid)
            self.clear_armed_next()
            self._clear_linear_caliper()
            self.dismiss_label_picker()
            self._clear_calibration_caliper()
            self._clear_persistent_linear_calipers()
            self._clear_contours()
            # Speckle kernels belong to the previous clip: drop them here, at
            # the swap (state for the new instance arrives with its first
            # frame), so nothing leaks onto the new cine and the old frame
            # keeps its graphics until the swap instead of popping early.
            self.clear_speckle_overlay()
            if (loop := self.findChild(LoopControls)) is not None:
                loop.clear()
            self._stored_linear_measurements = {}
            self._dist_serial = 1
            # S2-04: undo/redo belongs to the previous clip — clear on instance change.
            self.clear_undo_redo()
            self.doppler.on_instance_changed()
            # Restore WL/DR for the new instance if cached
            new_uid = viewer_state.instance.sop_instance_uid if viewer_state.instance else None
            self.display.restore_instance(new_uid)
        elif frame_changed:
            self.dismiss_label_picker()
            self.doppler.on_frame_changed(previous_frame, viewer_state.current_frame_index)
        comparison_keys = {("D1", -1), ("D2", -1)}
        if self._comparison_state.frame_index is not None:
            comparison_keys = {
                ("D1", self._comparison_state.frame_index),
                ("D2", self._comparison_state.frame_index),
            }
        preserved = {k: v for k, v in self._stored_linear_measurements.items() if k in comparison_keys}
        self._stored_linear_measurements = {
            self._linear_measurement_key(measurement): measurement for measurement in viewer_state.linear_measurements
        }
        self._stored_linear_measurements.update(preserved)
        self._current_state = viewer_state
        try:
            current = viewer_state.current_frame_index + 1 if viewer_state.total_frames > 0 else 0
            self.transport.apply_state(
                frame_index=viewer_state.current_frame_index,
                total_frames=viewer_state.total_frames,
                fps=viewer_state.fps,
                is_playing=viewer_state.is_playing,
                decode_in_progress=viewer_state.decode_in_progress,
                counter_current=current,
            )
            self._phase_strip.set_total_frames(viewer_state.total_frames)
            self._phase_strip.set_current_frame(viewer_state.current_frame_index)
            loop = self.findChild(LoopControls)
            if loop is not None:
                loop.set_total_frames(viewer_state.total_frames)
                loop.set_current_frame(viewer_state.current_frame_index)
            self._update_phase_label(frame=viewer_state.current_frame_index)
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
            self._set_viewport_update_for_playback(viewer_state.is_playing)
            if not viewer_state.is_playing:
                self._refresh_frame_panel_layout()
                self._refresh_panel_frame_graphics()
                self.tags_overlay.refresh()
        finally:
            self._syncing_state = False
            # rebuild explicit context + propagate generation to controllers
            bump = previous_instance is not None and previous_instance != viewer_state.instance
            try:
                self._sync_viewer_context(bump_generation=bool(bump))
            except Exception as exc:  # noqa: BLE001, S110
                log_boundary_failure(logger, "viewer.context_sync", exc, code="ui", level=logging.DEBUG)
            pending = self._pending_viewer_state
            self._pending_viewer_state = None
            if pending is not None:
                self.set_state(pending)

    def _set_image_smooth(self, enabled: bool) -> None:
        if self._image_smooth == enabled:
            return
        self._image_smooth = enabled
        self._image_item.setOpts(smooth=enabled)

    def _set_viewport_update_for_playback(self, is_playing: bool) -> None:
        mode = (
            QGraphicsView.ViewportUpdateMode.FullViewportUpdate
            if is_playing
            else QGraphicsView.ViewportUpdateMode.SmartViewportUpdate
        )
        if self._graphics.viewportUpdateMode() != mode:
            self._graphics.setViewportUpdateMode(mode)

    @_prof
    def toggle_linear_caliper(self) -> None:
        if self._linear_caliper_active:
            self._clear_linear_caliper()
            return
        self._clear_calibration_caliper()
        self.activate_generic_dist_caliper()

    def start_diameter_compare(self, *, kind: str = "diameter") -> bool:
        if self._current_frame is None:
            return False
        self._clear_calibration_caliper()
        self._clear_linear_caliper_graphics()
        self._linear_caliper_active = True
        self._linear_caliper_start = None
        self._comparison_state = _ComparisonState(
            kind=kind,
            frame_index=self._contour_frame_index(),
        )
        self._measurement_label.setText(tr(start_hint(kind)))
        return True

    def start_area_compare(self, *, kind: str = "area") -> bool:
        if self._current_frame is None:
            return False
        self.cancel_active_tool()
        if not self.start_generic_area_contour():
            return False
        self._comparison_state = _ComparisonState(
            kind=kind,
            frame_index=self._contour_frame_index(),
        )
        self._measurement_label.setText(tr(start_hint(kind)))
        return True

    def _handle_area_compare_contour(self, contour: Contour) -> None:
        state = self._comparison_state
        if state.kind not in {"area", "ar_jet_area"}:
            return
        spacing, _ = self._effective_pixel_spacing()
        if spacing is None or len(contour.points) < 3:
            self._measurement_label.setText(tr("viewer.acmp_need_calibration"))
            return
        from echo_personal_tool.domain.calculations.planimeter import closed_polygon_area_cm2

        area_cm2 = closed_polygon_area_cm2(contour, spacing)
        if area_cm2 is None or area_cm2 <= 0:
            self._measurement_label.setText(tr("viewer.acmp_invalid_contour"))
            return
        frame = state.frame_index
        instance_uid = self.current_instance_uid() or ""
        points = list(contour.points)
        first_label, second_label, pct_label = compare_labels(state.kind)
        second_start_hint, result_hint = AREA_HINTS[state.kind]
        if not state.first_contour_done:
            state.contour1_points = points
            state.contour1_area_cm2 = area_cm2
            s_key = (first_label, frame if (frame := state.frame_index) is not None else -1)
            self._stored_linear_measurements[s_key] = LinearMeasurement(
                label=first_label,
                pixel_length=0.0,
                millimeter_length=area_cm2,
                frame_index=frame,
                sop_instance_uid=instance_uid,
            )
            self._measurement_label.setText(tr(second_start_hint))
            self._render_persistent_linear_calipers()
            self._emit_stored_linear_measurements()
            self._refresh_frame_overlays()
            saved = _ComparisonState(
                kind=state.kind,
                frame_index=state.frame_index,
                contour1_points=state.contour1_points,
                contour1_area_cm2=state.contour1_area_cm2,
            )
            self.start_generic_area_contour()
            self._comparison_state = saved
            return
        state.contour2_points = points
        state.contour2_area_cm2 = area_cm2
        pct_s = self._compute_percent_s()
        s2_key = (second_label, frame if frame is not None else -1)
        self._stored_linear_measurements[s2_key] = LinearMeasurement(
            label=second_label,
            pixel_length=0.0,
            millimeter_length=area_cm2,
            frame_index=frame,
            sop_instance_uid=instance_uid,
        )
        if pct_s is not None:
            pct_key = (pct_label, frame if frame is not None else -1)
            self._stored_linear_measurements[pct_key] = LinearMeasurement(
                label=pct_label,
                pixel_length=0.0,
                millimeter_length=pct_s,
                frame_index=frame,
                sop_instance_uid=instance_uid,
            )
        self._comparison_state = _ComparisonState(
            kind=state.kind,
            frame_index=state.frame_index,
            contour1_points=state.contour1_points,
            contour1_area_cm2=state.contour1_area_cm2,
            contour2_points=state.contour2_points,
            contour2_area_cm2=state.contour2_area_cm2,
        )
        self._render_persistent_linear_calipers()
        self._refresh_frame_overlays()
        self._emit_stored_linear_measurements()
        self._measurement_label.setText(
            tr(
                result_hint,
                area1=_fmt("planimeter.area", state.contour1_area_cm2 or 0.0, "cm²"),
                area2=_fmt("planimeter.area", area_cm2, "cm²"),
                percent_s=_fmt("vessel.stenosis_area", pct_s, "%"),
            )
        )

    def _compute_percent_s(self) -> float:
        state = self._comparison_state
        # Contour 1 is the jet and contour 2 the LVOT in the AR workflow, so the
        # ratio keeps that direction (see ``compare_tools.percent_s``).
        return percent_s(state.kind, state.contour1_area_cm2, state.contour2_area_cm2)

    def _build_comparison_s_overlay(self) -> str:
        state = self._comparison_state
        if state.kind not in {"area", "ar_jet_area"} or not state.first_contour_done or state.contour2_area_cm2 is None:
            return ""
        a1 = state.contour1_area_cm2 if state.contour1_area_cm2 is not None else 0.0
        a2 = state.contour2_area_cm2 if state.contour2_area_cm2 is not None else 0.0
        if a1 == 0 and a2 == 0:
            return ""
        pct_s = self._compute_percent_s()
        return tr(
            AREA_HINTS[state.kind][1],
            area1=_fmt("planimeter.area", a1, "cm²"),
            area2=_fmt("planimeter.area", a2, "cm²"),
            percent_s=_fmt("vessel.stenosis_area", pct_s, "%"),
        )

    # ── Vessel stenosis tools ───────────────────────────────────────

    def start_vessel_stenosis_diameter(self) -> bool:
        if self._current_frame is None or not self._vessel_spatial_calibration_ready():
            return False
        self._clear_calibration_caliper()
        self._clear_linear_caliper_graphics()
        self._linear_caliper_active = True
        self._linear_caliper_start = None
        self._comparison_state = _ComparisonState(
            kind="stenosis_diameter",
            frame_index=self._contour_frame_index(),
        )
        self._measurement_label.setText(tr("viewer.stenosis_d_click_start"))
        return True

    def start_vessel_stenosis_area(self) -> bool:
        if self._current_frame is None or not self._vessel_spatial_calibration_ready():
            return False
        self.cancel_active_tool()
        if not self.start_generic_area_contour():
            return False
        self._comparison_state = _ComparisonState(
            kind="stenosis_area",
            frame_index=self._contour_frame_index(),
        )
        self._measurement_label.setText(tr("viewer.stenosis_a_click_start"))
        return True

    @staticmethod
    def _compute_stenosis_diameter(d1: float | None, d2: float | None) -> float | None:
        if d1 is None or d2 is None:
            return None
        bigger = max(d1, d2)
        if bigger == 0:
            return None
        return (1.0 - min(d1, d2) / bigger) * 100.0

    @staticmethod
    def _compute_stenosis_area(s_total: float | None, s_lumen: float | None) -> float | None:
        if s_total is None or s_lumen is None:
            return None
        if s_total <= 0:
            return None
        return (s_total - s_lumen) / s_total * 100.0

    def _build_stenosis_diameter_overlay(self) -> str:
        state = self._comparison_state
        if state.kind != "stenosis_diameter" or not state.first_segment_done or state.segment2_mm is None:
            return ""
        d1 = state.segment1_mm if state.segment1_mm is not None else 0.0
        d2 = state.segment2_mm if state.segment2_mm is not None else 0.0
        if d1 == 0 and d2 == 0:
            return ""
        stenosis = self._compute_stenosis_diameter(d1, d2)
        unit = self._length_display_unit
        m1 = LinearMeasurement(
            label="D1",
            pixel_length=0,
            millimeter_length=d1,
            submillimeter=self._vessel_measurement_mode or self._tenth_mm_precision,
        )
        m2 = LinearMeasurement(
            label="D2",
            pixel_length=0,
            millimeter_length=d2,
            submillimeter=self._vessel_measurement_mode or self._tenth_mm_precision,
        )
        return tr(
            "viewer.stenosis_d_result",
            length1=inline_caliper_text(m1, length_unit=unit),
            length2=inline_caliper_text(m2, length_unit=unit),
            percent=f"{_fmt('vessel.stenosis_d', stenosis, '%')}%" if stenosis is not None else "—",
        )

    def _build_stenosis_area_overlay(self) -> str:
        state = self._comparison_state
        if state.kind != "stenosis_area" or not state.first_contour_done or state.contour2_area_cm2 is None:
            return ""
        s_total = state.contour1_area_cm2 if state.contour1_area_cm2 is not None else 0.0
        s_lumen = state.contour2_area_cm2 if state.contour2_area_cm2 is not None else 0.0
        if s_total == 0 and s_lumen == 0:
            return ""
        stenosis = self._compute_stenosis_area(s_total, s_lumen)
        return tr(
            "viewer.stenosis_a_result",
            area_total=_fmt("planimeter.area", s_total, "cm²"),
            area_lumen=_fmt("planimeter.area", s_lumen, "cm²"),
            percent=f"{_fmt('vessel.stenosis_area', stenosis, '%')}%" if stenosis is not None else "—",
        )

    def _handle_stenosis_area_contour(self, contour: Contour) -> None:
        state = self._comparison_state
        if state.kind != "stenosis_area":
            return
        spacing, _ = self._effective_pixel_spacing()
        if spacing is None or len(contour.points) < 3:
            self._measurement_label.setText(tr("viewer.stenosis_a_need_calibration"))
            return
        from echo_personal_tool.domain.calculations.planimeter import closed_polygon_area_cm2

        area_cm2 = closed_polygon_area_cm2(contour, spacing)
        if area_cm2 is None or area_cm2 <= 0:
            self._measurement_label.setText(tr("viewer.stenosis_a_invalid_contour"))
            return
        frame = state.frame_index
        instance_uid = self.current_instance_uid() or ""
        points = list(contour.points)
        if not state.first_contour_done:
            state.contour1_points = points
            state.contour1_area_cm2 = area_cm2
            s_key = ("S1", frame if (frame := state.frame_index) is not None else -1)
            self._stored_linear_measurements[s_key] = LinearMeasurement(
                label="S1",
                pixel_length=0.0,
                millimeter_length=area_cm2,
                frame_index=frame,
                sop_instance_uid=instance_uid,
            )
            self._measurement_label.setText(tr("viewer.stenosis_a_second_start"))
            self._render_persistent_linear_calipers()
            self._emit_stored_linear_measurements()
            self._refresh_frame_overlays()
            saved = _ComparisonState(
                kind=state.kind,
                frame_index=state.frame_index,
                contour1_points=state.contour1_points,
                contour1_area_cm2=state.contour1_area_cm2,
            )
            self.start_generic_area_contour()
            self._comparison_state = saved
            return
        state.contour2_points = points
        state.contour2_area_cm2 = area_cm2
        stenosis = self._compute_stenosis_area(state.contour1_area_cm2, area_cm2)
        s2_key = ("S2", frame if frame is not None else -1)
        self._stored_linear_measurements[s2_key] = LinearMeasurement(
            label="S2",
            pixel_length=0.0,
            millimeter_length=area_cm2,
            frame_index=frame,
            sop_instance_uid=instance_uid,
        )
        if stenosis is not None:
            pct_key = ("%S", frame if frame is not None else -1)
            self._stored_linear_measurements[pct_key] = LinearMeasurement(
                label="%S",
                pixel_length=0.0,
                millimeter_length=stenosis,
                frame_index=frame,
                sop_instance_uid=instance_uid,
            )
        self._comparison_state = _ComparisonState(
            kind=state.kind,
            frame_index=state.frame_index,
            contour1_points=state.contour1_points,
            contour1_area_cm2=state.contour1_area_cm2,
            contour2_points=state.contour2_points,
            contour2_area_cm2=state.contour2_area_cm2,
        )
        self._render_persistent_linear_calipers()
        self._refresh_frame_overlays()
        self._emit_stored_linear_measurements()
        self._measurement_label.setText(
            tr(
                "viewer.stenosis_a_result",
                area_total=_fmt("planimeter.area", state.contour1_area_cm2 or 0.0, "cm²"),
                area_lumen=_fmt("planimeter.area", area_cm2, "cm²"),
                percent=f"{_fmt('vessel.stenosis_area', stenosis, '%')}%" if stenosis is not None else "—",
            )
        )

    def activate_generic_dist_caliper(self) -> str | None:
        """Start click-click caliper with the next DistN label; return label or None.

        The generic caliper stays armed after each measurement (repeat mode):
        two clicks commit DistN, the next two clicks commit DistN+1, and so on
        until the tool is switched off (button / L hotkey / Esc).
        """
        label = f"Dist{self._dist_serial}"
        if self.start_linear_caliper_for(label):
            self._caliper_repeat_mode = True
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

    @property
    def is_caliper_repeat_mode(self) -> bool:
        """True while the generic caliper stays armed for multiple measurements."""
        return self._caliper_repeat_mode and self._linear_caliper_active

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

    def current_instance_uid(self) -> str | None:
        if self._current_state is None or self._current_state.instance is None:
            return None
        return self._current_state.instance.sop_instance_uid

    def _current_frame_index(self) -> int | None:
        if self._current_state is None:
            return None
        return self._current_state.current_frame_index

    def set_hint(self, text: str) -> None:
        """Show a tool prompt in the viewer's black hint strip.

        Empty text hides the overlay (idle keeps the letterbox clean).
        """
        bar = getattr(self, "_hint_bar", None)
        if bar is None:
            return
        bar.setText(text)
        if text:
            self._position_hint_bar()
            bar.show()
            bar.raise_()
        else:
            bar.hide()

    def _position_hint_bar(self) -> None:
        """Pin the hint overlay to the bottom of the image viewport."""
        bar = getattr(self, "_hint_bar", None)
        if bar is None:
            return
        viewport = self._graphics.viewport()
        if viewport is None:
            return
        height = bar.height()
        bar.setGeometry(0, max(0, viewport.height() - height), viewport.width(), height)

    def refresh_hint_theme(self) -> None:
        """Re-apply the hint overlay style after a theme switch."""
        bar = getattr(self, "_hint_bar", None)
        if bar is None:
            return
        bar.setStyleSheet(_hint_bar_style())
        self._position_hint_bar()

    def _init_caliper_display_state(self) -> None:
        self._show_caliper_labels_on_frame = True
        self._show_caliper_inline_labels = False
        self._length_display_unit = "mm"
        self._tenth_mm_precision = True
        self._vessel_measurement_mode = False

    def set_vessel_measurement_mode(self, enabled: bool) -> None:
        """Explicit spatial override: Samsung acquisition tags remain untouched."""
        enabled = bool(enabled)
        if enabled == self._vessel_measurement_mode:
            return
        self.cancel_active_tool()
        self._vessel_measurement_mode = enabled
        self.doppler.sync_manual_calibration_hint()

    def _vessel_spatial_calibration_ready(self) -> bool:
        if not self._vessel_measurement_mode or self._effective_pixel_spacing()[1]:
            return True
        prompt = tr("viewer.vessel_spatial_calibration_required")
        self._measurement_label.setText(prompt)
        self.set_hint(prompt)
        return False

    def is_vessel_available(self) -> bool:
        if self._current_frame is None:
            return False
        if not self.doppler.is_velocity_calibrated():
            return False
        state = self.doppler.get_calibration_state()
        if state is None or state.baseline_y_px is None:
            return False
        return True

    def start_vessel_psv(self, site_label: str = "") -> bool:
        if not self.is_vessel_available():
            return False
        self.cancel_active_tool()
        self._vessel_site_label = site_label
        self.doppler.overlay.set_vessel_mode()
        self._measurement_label.setText(tr("viewer.vessel_psv_prompt"))
        self._measurement_label.show()
        return True

    def start_vessel_auto_trace(self, preset: str = "normal", direction: str | None = None) -> bool:
        """Run the auto-trace envelope over the current Doppler frame.

        When *direction* is ``"up"`` or ``"down"`` the envelope is forced
        to the corresponding side of the baseline; ``None`` picks the
        side with the strongest signal automatically.  If the initial
        preset yields no envelope, retries with the ``"low"`` preset to
        handle weak AK/MK signals.
        """
        if not self.is_vessel_available():
            return False
        if self._current_frame is None:
            return False
        state = self.doppler.get_calibration_state()
        if state is None or state.roi is None or state.baseline_y_px is None:
            return False
        self.cancel_active_tool()
        from echo_personal_tool.domain.services.doppler_envelope import (
            extract_doppler_envelope,
        )

        envelope = extract_doppler_envelope(
            self._current_frame,
            state.roi,
            state.baseline_y_px,
            preset=preset,
            force_direction=direction,
        )
        used_preset = preset
        # Retry with lower sensitivity if the initial preset found nothing
        if not envelope and preset != "low":
            envelope = extract_doppler_envelope(
                self._current_frame,
                state.roi,
                state.baseline_y_px,
                preset="low",
                force_direction=direction,
            )
            used_preset = "low"
        if not envelope:
            self._measurement_label.setText(tr("viewer.vessel_auto_trace_failed"))
            self._measurement_label.show()
            return False
        cycles = self.doppler.cardiac_cycles(envelope)
        result = self.doppler.overlay.apply_auto_trace(envelope, cycles=cycles)
        if result is None:
            self._measurement_label.setText(tr("viewer.vessel_auto_trace_failed"))
            self._measurement_label.show()
            return False
        psv, edv = result
        self._measurement_label.setText(tr("viewer.vessel_auto_trace_done", psv=psv, edv=edv))
        self._measurement_label.show()
        self._vessel_direction = direction
        self._vessel_current_preset = used_preset
        self._vessel_sensitivity.set_preset(used_preset)
        self._show_vessel_sensitivity_overlay()
        return True

    def _show_vessel_sensitivity_overlay(self) -> None:
        self._vessel_sensitivity.show()
        self._position_vessel_sensitivity_overlay()

    def _position_vessel_sensitivity_overlay(self) -> None:
        # The overlay is a top-level Qt.Tool window, so move() takes *global*
        # coordinates.  The right edge of a maximised/fullscreen host window
        # (presenter mode) can push the strip past the monitor edge, where it
        # silently reappears on the second display — clamp it to the screen
        # the viewer actually lives on.
        geo = self._graphics.geometry()
        vw = self._vessel_sensitivity.width()
        vh = self._vessel_sensitivity.height()
        x = geo.x() + geo.width() - vw - 5 + 235
        y = geo.y() + (geo.height() - vh) // 2 + 310
        screen = self._graphics.screen()
        if screen is not None:
            avail = screen.availableGeometry()
            x = max(avail.x(), min(x, avail.x() + avail.width() - vw))
            y = max(avail.y(), min(y, avail.y() + avail.height() - vh))
        self._vessel_sensitivity.move(x, y)

    def _on_vessel_preset_changed(self, preset: str) -> None:
        if not self.is_vessel_available():
            return
        if self._current_frame is None:
            return
        state = self.doppler.get_calibration_state()
        if state is None or state.roi is None or state.baseline_y_px is None:
            return
        self._vessel_current_preset = preset
        from echo_personal_tool.domain.services.doppler_envelope import (
            extract_doppler_envelope,
        )

        envelope = extract_doppler_envelope(
            self._current_frame,
            state.roi,
            state.baseline_y_px,
            preset=preset,
            force_direction=self._vessel_direction,
        )
        if not envelope:
            return
        cycles = self.doppler.cardiac_cycles(envelope)
        result = self.doppler.overlay.apply_auto_trace(envelope, cycles=cycles)
        if result is None:
            return
        psv, edv = result
        self._measurement_label.setText(tr("viewer.vessel_auto_trace_done", psv=psv, edv=edv))

    def average_vessel_cycles(self) -> bool:
        """Average PSV/EDV over up to 3 ECG cycles."""
        if not self.is_vessel_available():
            return False
        if self._current_frame is None:
            return False
        envelope = self.doppler.extract_envelope()
        if not envelope or len(envelope) < 2:
            self._measurement_label.setText(tr("viewer.vessel_auto_trace_failed"))
            self._measurement_label.show()
            return False
        cycles = self.doppler.cardiac_cycles(envelope)
        result = self.doppler.overlay.apply_averaged_vessel(envelope, cycles=cycles)
        if result is None:
            self._measurement_label.setText(tr("viewer.vessel_average_failed"))
            self._measurement_label.show()
            return False
        psv, edv = result
        count = self.doppler.overlay.vessel_averaged_cycles()
        self._measurement_label.setText(tr_plural("viewer.vessel_average_done", count, psv=psv, edv=edv))
        self._measurement_label.show()
        if self.doppler.overlay.vessel_cycle_selection_active():
            self._update_vessel_cycle_selection_label()
        return True

    def _update_vessel_cycle_selection_label(self) -> None:
        candidate = self.doppler.overlay.vessel_cycle_candidate()
        index = self.doppler.overlay.vessel_cycle_index()
        count = self.doppler.overlay.vessel_cycle_count()
        if candidate is None:
            return
        self._measurement_label.setText(
            tr(
                "viewer.vessel_cycle_candidate",
                value=candidate,
                index=index + 1,
                count=count,
                left_key=shortcut_label("vessel_previous_cycle"),
                right_key=shortcut_label("vessel_next_cycle"),
                accept_key=shortcut_label("finish_tool"),
                cancel_key=shortcut_label("cancel_tool"),
            )
        )
        self._measurement_label.show()

    def _restore_vessel_average_label(self) -> None:
        values = self.doppler.overlay.get_vessel_values()
        if values is None:
            self._measurement_label.hide()
            return
        psv, edv = values
        count = self.doppler.overlay.vessel_averaged_cycles()
        self._measurement_label.setText(tr_plural("viewer.vessel_average_done", count, psv=psv, edv=edv))
        self._measurement_label.show()

    def accept_vessel_measurement(self) -> bool:
        if not self.is_vessel_available():
            return False
        metrics = self.doppler.overlay.get_vessel_metrics()
        if metrics is None:
            return False
        values = self.doppler.overlay.get_vessel_values()
        if values is None:
            return False
        psv, edv = values
        instance_uid = self.current_instance_uid()
        if instance_uid is None:
            return False
        from echo_personal_tool.domain.models.vessel_measurement import VesselMeasurement

        measurement = VesselMeasurement(
            psv_cm_s=psv,
            edv_cm_s=edv,
            ri=metrics.ri,
            sd=metrics.sd,
            mv_approx=metrics.mv_approx or 0.0,
            sop_instance_uid=instance_uid,
            frame_index=self._current_frame_index() or 0,
            cycle_source=self.doppler.overlay.vessel_cycle_source() or "manual",
            averaged_cycles=self.doppler.overlay.vessel_averaged_cycles(),
            label=self._vessel_site_label,
        )
        self.vessel_accept_requested.emit(measurement)
        self.doppler.overlay.clear_vessel()
        self._measurement_label.hide()
        return True

    def clear_vessel_measurement(self) -> bool:
        had = self.doppler.overlay.vessel_status() != "none"
        self.doppler.overlay.clear_vessel()
        self._vessel_site_label = ""
        self._measurement_label.hide()
        self._vessel_sensitivity.hide()
        self._vessel_direction = None
        return had

    def show_ecg_strip(self) -> None:
        ecg_strip_loader.show_ecg_strip(self)

    def hide_ecg_strip(self) -> None:
        ecg_strip_loader.hide_ecg_strip(self)

    def set_ecg_waveform_for_strip(self, ecg: object | None) -> None:
        ecg_strip_loader.set_ecg_waveform_for_strip(self, ecg)

    def set_cardiac_cycles_for_strip(self, cycles: object) -> None:
        ecg_strip_loader.set_cardiac_cycles_for_strip(self, cycles)

    def highlight_ecg_cycle_for_strip(self, cycle_index: int | None) -> None:
        ecg_strip_loader.highlight_ecg_cycle_for_strip(self, cycle_index)

    def _load_ecg_for_strip(self) -> None:
        """Load ECG for the strip; shows it only when a usable waveform exists."""
        ecg_strip_loader.load_ecg_for_strip(self)

    def _build_doppler_port(self) -> DopplerViewerPort:
        """Late-bound access the Doppler controller needs (issue 420)."""
        return DopplerViewerPort(
            frame=lambda: self._current_frame,
            instance_metadata=lambda: self._current_instance_metadata(),
            instance_uid=lambda: self.current_instance_uid(),
            frame_index=lambda: self._current_frame_index(),
            contour_frame_index=lambda: self._contour_frame_index(),
            resolve_panels=lambda: self._resolve_frame_panels(),
            vendor_panels=lambda: (
                self._frame_panel_layout
                if self._frame_panels_from_dicom and self._frame_panel_layout is not None
                else None
            ),
            dicom_doppler_panel=lambda: (
                self._frame_panel_layout.doppler
                if self._frame_panels_from_dicom and self._frame_panel_layout is not None
                else None
            ),
            syncing=lambda: self._syncing_state,
            calibration_active=lambda: self._calibration_active,
            calibration_kind=lambda: self._calibration_kind,
            vessel_measurement_mode=lambda: self._vessel_measurement_mode,
            tick_snap_enabled=lambda: self._calibration_tick_snap_enabled,
            tick_snap_radius_px=lambda: self._calibration_tick_snap_radius_px,
            last_cursor_xy=lambda: self._last_view_cursor_xy,
            create_overlay=lambda: DopplerOverlayTools(self._view, self),
            map_event=lambda ev: self._map_view_event(ev),
            cancel_tool=lambda: self.cancel_active_tool(),
            clear_calibration_caliper=lambda: self._clear_calibration_caliper(),
            clear_active_contour=lambda: self._clear_active_contour_drawing(),
            arm_velocity_calibration=self._arm_doppler_velocity_calibration,
            ensure_crosshair_graphics=lambda: self._ensure_crosshair_graphics(),
            load_ecg_strip=lambda: self._load_ecg_for_strip(),
            show_message=self._show_doppler_message,
            set_hint=lambda text: self.set_hint(text),
            ask_double=lambda title, prompt, value, low, high, decimals: QInputDialog.getDouble(
                self, title, prompt, value, low, high, decimals
            ),
            on_trace_committed=self._on_doppler_trace_committed,
            parse_dicom_calibration=lambda path, *, kind, frame: try_parse_dicom_doppler_calibration(
                path, kind=kind, frame=frame
            ),
            auto_detect_velocity=lambda frame, *, roi, baseline_y, kind: try_auto_doppler_velocity_calibration(
                frame, roi=roi, baseline_y=baseline_y, kind=kind
            ),
            load_tick_calibration=lambda: load_samsung_tick_calibration(),
            read_ecg=lambda path: read_ecg_waveform(path),
        )

    def _arm_doppler_velocity_calibration(self, x: float, start_y: float | None) -> None:
        self._calibration_kind = "doppler_velocity"
        self._calibration_active = True
        self._calibration_x = x
        self._calibration_start_y = start_y

    def _show_doppler_message(self, text: str, show: bool) -> None:
        self._measurement_label.setText(text)
        if show:
            self._measurement_label.show()

    def _build_mmode_port(self) -> MModeViewerPort:
        """Late-bound access the M-mode controller needs (issue 479)."""
        return MModeViewerPort(
            frame=lambda: self._current_frame,
            frame_time_ms=lambda: self._current_state.frame_time_ms if self._current_state is not None else None,
            resolve_panels=lambda: self._resolve_frame_panels(),
            syncing=lambda: self._syncing_state,
            view=lambda: self._view,
            map_event=lambda ev: self._map_view_event(ev),
            cancel_tool=lambda: self.cancel_active_tool(),
            clear_calibration_caliper=lambda: self._clear_calibration_caliper(),
            arm_calibration=self._arm_mmode_calibration,
            show_message=lambda text: self._measurement_label.setText(text),
            unset_cursor=lambda: self.unsetCursor(),
            apply_viewport_cursor=lambda: self._apply_viewport_cursor(),
            ask_double=lambda title, prompt, value, low, high, decimals: QInputDialog.getDouble(
                self, title, prompt, value, low, high, decimals
            ),
            start_linear_caliper_for=lambda label: self.start_linear_caliper_for(label),
            start_linear_caliper_sequence=lambda labels: self.start_linear_caliper_sequence(labels),
            add_vertical_labels=lambda labels: self._vertical_caliper_labels.update(labels),
            remove_vertical_labels=lambda labels: self._vertical_caliper_labels.difference_update(labels),
        )

    def _arm_mmode_calibration(self, kind: MModeCalibrationKind, x: float | None) -> None:
        """Arm the generic calibration caliper for an M-mode step (x: depth caliper column)."""
        self._calibration_kind = kind
        self._calibration_active = True
        if x is not None:
            self._calibration_x = x
        self._calibration_start_y = None

    def _apply_viewport_cursor(self) -> None:
        """One pointer for the image area: loupe > M-mode scan line > default.

        Children of the ViewerWidget (buttons, slider, labels) do not inherit
        this cursor because it is set on the graphics viewport alone — exactly
        the pattern the magnifier tool already used.
        """
        viewport = self._graphics.viewport() if self._graphics is not None else None
        if viewport is None:
            return
        if self.zoom.loupe_active:
            viewport.setCursor(_magnifier_cursor())
        elif self.mmode.line_active:
            viewport.setCursor(Qt.CursorShape.CrossCursor)
        else:
            viewport.unsetCursor()

        # NOTE: Do NOT emit mmode_line_completed here — it triggers expensive
        # recalculate_from_frames on every mouse-move. Only emit on drag end.

    def _refresh_frame_panel_layout(self) -> None:
        self._frame_panel_layout = None
        self._frame_panels_from_dicom = False
        if self._current_frame is None:
            return
        instance = self._current_state.instance if self._current_state else None
        if instance is not None and instance.media_format == "dicom" and instance.path is not None:
            self._frame_panel_layout = try_parse_dicom_frame_panels(instance.path)
            self._frame_panels_from_dicom = self._frame_panel_layout is not None
        if self._frame_panel_layout is None:
            gray = self._current_frame
            if gray.ndim == 3:
                gray = np.mean(gray, axis=2)
            self._frame_panel_layout = detect_panels_heuristic(gray)

    def _resolve_frame_panels(self) -> FramePanelLayout | None:
        """Vendor panel geometry with the user's spectral zone applied.

        The merge rule lives in ``compare_tools.resolve_frame_panels`` so the
        hint veto and the tests read the very same rule.
        """
        if self._frame_panel_layout is None:
            self._refresh_frame_panel_layout()
        return resolve_frame_panels(self._frame_panel_layout, self.doppler.spectral_zone())

    def _crosshair_panel_bounds(self) -> DopplerSpectrogramRoi | None:
        if self.doppler.get_tool_mode() != "none" and self.doppler.calibration_state is not None:
            return self.doppler.calibration_state.roi
        if (
            self._linear_caliper_active
            and not self._vessel_measurement_mode
            and _is_generic_dist_label(self._current_caliper_label())
        ):
            # Generic caliper over the Doppler ROI: show the scanner-style
            # crosshair so the time/velocity measuring zone is visible.
            doppler_zone = self.doppler.caliper_zone()
            if doppler_zone is not None:
                return doppler_zone
        if (
            self._linear_caliper_active
            and self._current_caliper_label() in self._vertical_caliper_labels
            and self.mmode.calibration_state is not None
        ):
            return self.mmode.calibration_state.roi
        if self._calibration_kind in {"mmode_time", "mmode_depth"}:
            if self.mmode.pending_roi is not None:
                return self.mmode.pending_roi
            if self.mmode.calibration_state is not None:
                return self.mmode.calibration_state.roi
            if self._calibration_kind == "mmode_time":
                panels = self._resolve_frame_panels()
                if panels is not None and panels.m_mode is not None:
                    return panels.m_mode.bounds
        if self.doppler.cal_step is not None and self.doppler.pending_roi is not None:
            return self.doppler.pending_roi
        return None

    def _measurement_crosshair_active(self) -> bool:
        if self._crosshair_panel_bounds() is not None:
            return True
        return False

    def _ensure_crosshair_graphics(self) -> None:
        pen = pg.mkPen(dark_theme.get_theme_tokens()["overlay.label"], width=1, style=Qt.PenStyle.DashLine)
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
        self._last_view_cursor_xy = (float(x), float(y))
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

    def finish_calibration(self) -> bool:
        return False

    @property
    def is_calibration_active(self) -> bool:
        return self._calibration_active

    def start_linear_caliper_for(self, label: str) -> bool:
        # Anatomical calipers are single-shot; only the generic Dist caliper
        # (activate_generic_dist_caliper) re-arms itself after each commit.
        self._caliper_repeat_mode = False
        self.mmode.reset_session_vertical_labels()
        self._caliper_sequence = []
        self._caliper_sequence_size = 0
        self._last_caliper_sequence_labels = ()
        return self._begin_linear_caliper(label)

    def activate_linear_caliper(self) -> bool:
        """Start (or restart) click-click caliper for the next Dist label."""
        self._clear_calibration_caliper()
        return self.activate_generic_dist_caliper() is not None

    @_prof
    def start_linear_caliper_sequence(self, labels: tuple[str, ...]) -> bool:
        if not labels:
            return False
        self._caliper_repeat_mode = False
        self.mmode.reset_session_vertical_labels()
        self._caliper_sequence = list(labels[1:])
        self._caliper_sequence_size = len(labels)
        self._last_caliper_sequence_labels = tuple(labels)
        return self._begin_linear_caliper(labels[0])

    def last_caliper_sequence(self) -> tuple[str, ...]:
        """Labels of the last started caliper sequence (empty for a single one)."""
        return self._last_caliper_sequence_labels

    def _begin_linear_caliper(self, label: str) -> bool:
        if self._comparison_state.kind:
            self._comparison_state.reset()
        self._clear_linear_caliper_graphics()
        self._clear_calibration_caliper()
        if self._current_frame is None:
            return False
        self._set_caliper_label(label)
        self._linear_caliper_active = True
        self._linear_caliper_start = None
        self._measurement_label.setText(tr("viewer.linear_caliper_click_start", label=label))
        self._sync_persistent_loupe()
        return True

    def cycle_caliper_label(self) -> None:
        if self.label_picker_owner.cycle_visible_selection(emit_tab=False):
            return
        label = self.label_picker_owner.cycle_label()
        if not self._linear_caliper_active:
            self._measurement_label.setText(f"{label}: —")
            return
        self._linear_caliper_start = None
        self._clear_linear_caliper_graphics()
        self._measurement_label.setText(tr("viewer.linear_caliper_click_start", label=label))

    def _trace_enabled_for(self, chamber: str) -> bool:
        key = chamber.upper()
        if key == "LV":
            return self._lv_contour_input == "trace"
        if key in {"LA", "RA"}:
            return self._atrial_contour_input == "trace"
        return False

    def start_contour(
        self,
        *,
        phase: str | None = None,
        view: str = "A4C",
        chamber: str = "LV",
        force_landmarks: bool = False,
    ) -> bool:
        if not force_landmarks and self._trace_enabled_for(chamber):
            return self._start_trace_contour(phase=phase, view=view, chamber=chamber)
        return self._start_contour_drawing(
            mode_kind="manual",
            pen=self._contour_pen_manual,
            phase=phase,
            view=view,
            chamber=chamber,
        )

    def _start_trace_contour(
        self,
        *,
        phase: str | None = None,
        view: str = "A4C",
        chamber: str = "LV",
    ) -> bool:
        """Freehand manual contour: line-only stroke, release pauses, Enter finishes."""
        if self._current_frame is None:
            return False
        if self._active_contour_item is not None:
            return False

        self.cancel_active_tool()
        self._active_contour_view = view
        self._active_contour_phase = phase or self._resolve_contour_phase()
        self._active_contour_chamber = chamber
        self._contour_mode_active = True
        self._reset_contour_click_tracking()
        self._contour_mode_kind = "manual"
        self._contour_stage = "trace"
        self._active_mitral_septal = None
        self._active_mitral_annulus = None
        self._active_apex_landmark = None
        self._active_arc_points = []
        self._freehand_points = []
        self._freehand_recording = True
        self._freehand_open_arc = True
        pen = self._contour_pen_manual
        # No per-sample marker: a continuous stroke reads as one line while
        # tracing; only the finished, decimated nodes become draggable handles.
        self._active_contour_item = pg.PlotDataItem(pen=pen)
        self._active_contour_item.setZValue(20)
        self._view.addItem(self._active_contour_item)
        self._clear_contour_hover()
        self._set_contour_nodes_pickable(False)
        prompt_key = "viewer.lv_trace_prompt" if chamber.upper() == "LV" else "viewer.atrial_trace_prompt"
        self._measurement_label.setText(tr(prompt_key, finish_key=shortcut_label("finish_tool")))
        return True

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
        if self._area_tool_mode == "freehand":
            self._freehand_recording = True
            self._freehand_points = []
            self._measurement_label.setText(tr("viewer.area_freehand_prompt"))
        else:
            self._measurement_label.setText(tr("viewer.area_contour_prompt"))
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
        if self._area_tool_mode == "freehand":
            self._freehand_recording = True
            self._freehand_points = []
            self._measurement_label.setText(tr("viewer.volume_freehand_prompt"))
        else:
            self._measurement_label.setText(tr("viewer.volume_contour_prompt"))
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
        self._reset_contour_click_tracking()
        self._contour_mode_kind = mode_kind
        self._freehand_open_arc = False
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
            if (
                self._magnetic_snap_enabled
                and not self._is_unassisted_freehand_trace()
                and len(self._active_arc_points) >= 5
            ):
                edge_map = self.get_edge_map()
                if edge_map is not None:
                    from echo_personal_tool.domain.services.contour_edge_snap import (
                        outward_normal_at_index_closed,
                        snap_magnetic_point,
                    )

                    idx = len(self._active_arc_points) - 1
                    normal = outward_normal_at_index_closed(self._active_arc_points, idx)
                    snapped = snap_magnetic_point(
                        edge_map,
                        self._active_arc_points[idx][0],
                        self._active_arc_points[idx][1],
                        normal,
                    )
                    if snapped is not None:
                        self._active_arc_points[idx] = snapped
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
            contour = replace(contour, frame_index=self._contour_frame_index())
        except ValueError:
            self.contour_landmark_rejected.emit("invalid")
            return False
        self._clear_active_contour_drawing()
        self.set_contour_from_domain(contour)
        self._auto_snap_new_contour(contour)
        self.contour_completed.emit(contour)
        return True

    def refine_active_open_contour(self) -> tuple[bool, str]:
        """Smooth manual/model LV open-arc nodes on the current frame (R key)."""
        if self._current_frame is None:
            return False, ""
        frame_index = self._contour_frame_index()
        instance_uid = self.current_instance_uid()
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
                display_levels=self.display.effective_levels(),
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
        # Captured before `_clear_active_contour_drawing()` resets `_active_contour_phase`
        # to None below — reading the instance attribute after that point always sees
        # None, which silently defeats the "ES" check in the LA-assist trigger further
        # down (issue 420 follow-up, slice 1: found while testing the refactor).
        phase = self._active_contour_phase or "ED"
        view = self._active_contour_view
        if chamber in {"LV", "LA", "RA", "RV"}:
            try:
                contour = fit_contour_from_landmarks(
                    septal=septal,
                    lateral=lateral,
                    apex=apex,
                    phase=phase,
                    view=view,
                    chamber=chamber,
                )
            except ValueError:
                self.contour_landmark_rejected.emit("invalid")
                return False
            contour = replace(
                contour,
                source="manual",
                frame_index=self._contour_frame_index(),
                apex_landmark=apex,
            )
        else:
            raw_arc = [septal, apex, lateral]
            resampled = resample_open_arc(raw_arc, num_nodes=DEFAULT_NODE_COUNT)
            contour = Contour(
                phase=phase,
                view=view,
                chamber=self._active_contour_chamber,
                mitral_annulus=self._active_mitral_annulus,
                points=resampled,
                num_nodes=DEFAULT_NODE_COUNT,
                frame_index=self._contour_frame_index(),
            )
        self._clear_active_contour_drawing()
        self.set_contour_from_domain(contour)
        if contour.is_open_arc:
            self._auto_snap_new_contour(contour)
        self.contour_completed.emit(contour)

        # --- Trigger LA assist for A4C ES manual contour ---
        if chamber == "LA" and view == "A4C" and phase == "ES" and self._la_assist_request is not None:
            self._request_la_assist_for_manual(
                septal=septal,
                lateral=lateral,
                apex=apex,
                frame_index=self._contour_frame_index(),
            )
        # --- END NEW ---

        return True

    def _request_la_assist_for_manual(
        self,
        *,
        septal: tuple[float, float],
        lateral: tuple[float, float],
        apex: tuple[float, float],
        frame_index: int,
    ) -> None:
        """Request LA AI assist for the current manual contour."""
        if self._la_assist_request is None:
            return
        # Connect signal (once)
        if not self._la_assist_connected and self._la_assist_ready_signal is not None:
            self._la_assist_ready_signal.connect(self._on_la_assist_contour_ready)
            self._la_assist_connected = True

        self._la_assist_request(
            frame_index=frame_index,
            user_septal=septal,
            user_lateral=lateral,
            user_apex=apex,
        )

    def _on_la_assist_contour_ready(self, contour) -> None:
        """Replace current LA contour with AI-assisted version."""
        if contour.chamber != "LA":
            return
        # Guard: ignore stale assist results if user moved to a different frame
        current_frame = self._contour_frame_index()
        if contour.frame_index is not None and current_frame is not None and contour.frame_index != current_frame:
            return
        # Find and replace the existing LA contour
        for i, c in enumerate(self._contours):
            if c.chamber == "LA" and c.view == contour.view and c.phase == contour.phase:
                if c.unassisted:
                    return
                self._contours[i] = contour
                # Update stored contour too
                self._upsert_stored_contour(contour)
                # Re-render all contours for current frame
                self._render_contours_for_current_frame()
                # Apply magnetic snap to refine edges
                self._apply_magnetic_snap_to_contour(
                    i,
                    np.ones(len(contour.points)),
                    grab_index=None,
                )
                # Apply optical flow refinement in background
                self._apply_optical_flow_refinement(i)
                self.contours_changed.emit(self.contours())
                break

    def _apply_optical_flow_refinement(self, contour_index: int) -> None:
        """Launch optical flow refinement for a contour in a background thread."""
        if contour_index < 0 or contour_index >= len(self._contours):
            return
        contour = self._contours[contour_index]
        if contour.unassisted:
            return
        if self._current_state is None or self._current_state.instance is None:
            return
        instance = self._current_state.instance
        if instance.path is None:
            return
        # Only refine open-arc contours (LV/LA)
        if not contour.is_open_arc or len(contour.points) < 4:
            return

        from PySide6.QtCore import QThreadPool

        from echo_personal_tool.application.workers.optical_flow_refine_worker import (
            OpticalFlowRefineWorker,
        )

        worker = OpticalFlowRefineWorker(
            source_path=instance.path,
            media_format=instance.media_format,
            contour_points=list(contour.points),
            current_frame_idx=self._current_state.current_frame_index or 0,
            total_frames=instance.number_of_frames,
            frame_time_ms=instance.frame_time_ms,
        )
        worker.signals.finished.connect(
            lambda points, idx=contour_index: self._on_optical_flow_refined(idx, points),
            Qt.ConnectionType.QueuedConnection,
        )
        QThreadPool.globalInstance().start(worker)

    def _on_optical_flow_refined(self, contour_index: int, refined_points: list) -> None:
        """Apply optical flow refined points to the contour."""
        if contour_index < 0 or contour_index >= len(self._contours):
            return
        contour = self._contours[contour_index]
        if len(refined_points) != len(contour.points):
            return
        # Update contour points
        contour.points[:] = refined_points
        self._upsert_stored_contour(contour)
        # Re-render
        self._render_contours_for_current_frame()
        self.contours_changed.emit(self.contours())

    def finish_contour(self) -> bool:
        if not self._contour_mode_active or self._active_contour_item is None:
            return False
        if self._contour_stage == "trace":
            return self._finish_freehand_open_arc()
        if self._contour_stage == "polygon":
            return self._finish_closed_contour()
        if self._contour_stage != "arc" or self._active_mitral_annulus is None or len(self._active_arc_points) < 1:
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

    @staticmethod
    def _dedupe_closed_polygon(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
        """Drop consecutive repeats (and a repeat of the first point at the end).

        Zero-length edges make the shoelace area unstable and confuse the
        magnetic snap, so a polygon is cleaned before it is measured.
        """
        cleaned: list[tuple[float, float]] = []
        for point in points:
            if not cleaned:
                cleaned.append(point)
                continue
            last = cleaned[-1]
            if math.hypot(point[0] - last[0], point[1] - last[1]) > _CONTOUR_MIN_POINT_SPACING_PX:
                cleaned.append(point)
        while len(cleaned) > 1:
            first, last = cleaned[0], cleaned[-1]
            if math.hypot(first[0] - last[0], first[1] - last[1]) > _CONTOUR_MIN_POINT_SPACING_PX:
                break
            cleaned.pop()
        return cleaned

    def _finish_closed_contour(self) -> bool:
        from echo_personal_tool.domain.services.contour_edge_snap import snap_closed_polygon

        points = self._dedupe_closed_polygon(list(self._active_arc_points))
        if len(points) < _CONTOUR_MIN_POINTS_TO_CLOSE:
            # Not enough distinct points: keep the drawing so the operator can
            # add the missing point instead of losing the whole contour.
            self._measurement_label.setText(tr_plural("viewer.area_points_needed", _CONTOUR_MIN_POINTS_TO_CLOSE))
            return False

        if self._magnetic_snap_enabled:
            edge_map = self.get_edge_map()
            if edge_map is not None:
                points = snap_closed_polygon(points, edge_map)

        probe = Contour(
            phase=self._active_contour_phase or "GEN",
            view=self._active_contour_view,
            chamber=self._active_contour_chamber,
            points=list(points),
            frame_index=self._contour_frame_index(),
        )
        if closed_polygon_area_cm2(probe, (1.0, 1.0)) is None:
            # Collinear/degenerate polygon — the area would be meaningless.
            self._measurement_label.setText(tr("viewer.area_degenerate_polygon"))
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
            points=points,
            frame_index=self._contour_frame_index(),
            measurement_label=measurement_label,
        )
        contour = self._with_measurement_identity(contour)
        self._clear_active_contour_drawing()
        self.set_contour_from_domain(contour)
        self._open_label_picker_for_contour(contour)
        self.contour_completed.emit(contour)
        return True

    def rollback_freehand_segment(self) -> bool:
        """Undo the last drawn segment of an in-progress freehand stroke.

        Bound to Backspace and right-click while a freehand stroke is being
        recorded (A+B). Returns False when no freehand stroke is active so the
        key/button can fall through to its normal handler.
        """
        if not self._freehand_recording or not self._contour_mode_active:
            return False
        if len(self._freehand_points) <= 3:
            # Nothing meaningful left: cancel the whole stroke.
            self._freehand_points = []
            self._freehand_recording = False
            self._freehand_open_arc = False
            self.cancel_active_tool()
            return True
        del self._freehand_points[-_FREEHAND_ROLLBACK_POINTS:]
        self._update_freehand_preview()
        return True

    def _finish_freehand_contour(self) -> bool:
        if len(self._freehand_points) < 3:
            self._clear_active_contour_drawing()
            return False

        from echo_personal_tool.domain.services.contour_edge_snap import (
            snap_closed_polygon,
        )
        from echo_personal_tool.domain.services.polygon_reduce import reduce_polygon_points

        unassisted = self._is_unassisted_freehand_trace()
        reduced = reduce_polygon_points(self._freehand_points, epsilon=3.0, closed=False)
        if len(reduced) > 30:
            reduced = reduce_polygon_points(reduced, epsilon=5.0, closed=False)
        if len(reduced) > 30:
            reduced = reduce_polygon_points(reduced, epsilon=8.0, closed=False)
        if len(reduced) > 30:
            step = max(1, -(-len(reduced) // 30))
            reduced = reduced[::step]
        if reduced[0] != reduced[-1]:
            reduced.append(reduced[0])

        if self._magnetic_snap_enabled and not unassisted:
            edge_map = self.get_edge_map()
            if edge_map is not None:
                reduced = snap_closed_polygon(reduced, edge_map)

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
            points=reduced,
            frame_index=self._contour_frame_index(),
            measurement_label=measurement_label,
            unassisted=unassisted,
        )
        self._freehand_recording = False
        self._freehand_points = []
        contour = self._with_measurement_identity(contour)
        self._clear_active_contour_drawing()
        self.set_contour_from_domain(contour)
        self._open_label_picker_for_contour(contour)
        self.contour_completed.emit(contour)
        return True

    def _finish_active_freehand_contour(self) -> bool:
        """Finish the running freehand stroke for whichever contour kind is active."""
        if self._freehand_open_arc:
            return self._finish_freehand_open_arc()
        return self._finish_freehand_contour()

    def _finish_freehand_open_arc(self) -> bool:
        """Build an open-arc contour from a freehand trace (Variant B).

        The trace is the endocardium; the mitral annulus chord is the automatic
        closing line between the first (septal) and last (lateral) points.
        Simpson volume is independent of which end is septal, so only the strain
        numbering needs the trace to start at the septum (the prompt says so).
        """
        from echo_personal_tool.domain.services.polygon_reduce import reduce_polygon_points

        unassisted = self._is_unassisted_freehand_trace()
        points = self._dedupe_closed_polygon(list(self._freehand_points))
        if len(points) < _CONTOUR_MIN_POINTS_TO_CLOSE:
            self._measurement_label.setText(tr_plural("viewer.area_points_needed", _CONTOUR_MIN_POINTS_TO_CLOSE))
            return False

        reduced = reduce_polygon_points(points, epsilon=3.0, closed=False)
        if len(reduced) < 3:
            reduced = points
        septal = reduced[0]
        lateral = reduced[-1]
        apex = infer_apex_from_open_arc(reduced, septal, lateral)

        resampled = resample_open_arc(reduced, num_nodes=DEFAULT_NODE_COUNT)
        contour = Contour(
            phase=self._active_contour_phase or "ED",
            view=self._active_contour_view,
            chamber=self._active_contour_chamber,
            source="manual",
            mitral_annulus=(septal, lateral),
            apex_landmark=apex,
            points=resampled,
            num_nodes=DEFAULT_NODE_COUNT,
            frame_index=self._contour_frame_index(),
            unassisted=unassisted,
        )
        self._clear_active_contour_drawing()
        self.set_contour_from_domain(contour)
        if not unassisted:
            self._auto_snap_new_contour(contour)
        self.contour_completed.emit(contour)
        return True

    def arm_next_caliper(self, label: str) -> None:
        """Make the next click on the image start the caliper *label*.

        Used by the paired diastole/systole tools: after «МЖП · КДР ЛЖ · ЗСЛЖ»
        the operator scrolls to the systolic frame, and that first click is
        already the first point of LVESD — no button press in between (ТЗ п. 2).
        """
        self._armed_next = ("caliper", str(label))
        self._remember_armed_frame()

    def arm_next_contour(
        self,
        *,
        chamber: str,
        view: str,
        phase: str,
        model: bool = False,
    ) -> None:
        """Make the next click on the image start this contour (ES after ED)."""
        self._armed_next = (
            "contour",
            str(chamber).upper(),
            str(view).upper(),
            str(phase).upper(),
            bool(model),
        )
        self._remember_armed_frame()

    def _remember_armed_frame(self) -> None:
        """Remember where the chain was armed (frame + clip), for the gate."""
        self._armed_next_origin = (self._current_frame_index(), self.current_instance_uid())

    def clear_armed_next(self) -> None:
        """Forget the chained step (Esc, tool switch, another clip)."""
        self._armed_next = None
        self._armed_next_origin = (None, None)

    def armed_next(self) -> tuple | None:
        """What the next click would start, for tests and the status line."""
        return self._armed_next

    def armed_next_waits_for_another_frame(self) -> bool:
        """Whether the chain is armed but the operator is still on that frame.

        ``True`` while the armed step must not start: the click belongs to the
        contour that was just drawn.  A missing frame index (a still image, so
        no systole to scroll to) never blocks: there is no other frame to wait
        for, and the click keeps its old meaning.
        """
        if self._armed_next is None:
            return False
        armed_frame, armed_uid = self._armed_next_origin
        if armed_frame is None or (armed_uid is not None and self.current_instance_uid() != armed_uid):
            return False
        return self._current_frame_index() == armed_frame

    def hint_armed_next_needs_another_frame(self) -> None:
        """Tell the operator why the click did nothing (item 13, no silent no-op)."""
        if self._armed_next is None:
            return
        phase = "ES" if self._armed_next[0] == "contour" else ""
        self.set_hint(tr("viewer.armed_next_scroll", phase=phase) if phase else tr("viewer.armed_next_scroll_generic"))

    def start_armed_next(self, *, force: bool = False) -> bool:
        """Start the armed step now.  ``False`` when nothing is armed/frame-less.

        ``force=True`` skips the «scroll to another frame first» gate: the panel
        button and the protocol step are explicit requests for the tool, while a
        click on the image is an ambiguous one (see
        :meth:`armed_next_waits_for_another_frame`).
        """
        pending = self._armed_next
        if pending is None:
            return False
        if not force and self.armed_next_waits_for_another_frame():
            return False
        self.clear_armed_next()
        if pending[0] == "caliper":
            return self.start_linear_caliper_for(pending[1])
        _kind, chamber, view, phase, model = pending
        if model:
            return self.start_model_contour(chamber=chamber, phase=phase, view=view)
        return self.start_contour(chamber=chamber, phase=phase, view=view)

    def cancel_active_tool(self) -> None:
        # A tool switch must not leave the previous tool's prompt in the strip
        # (e.g. the Doppler "AV VTI" hint sticking after selecting a contour).
        if self.zoom.loupe_active:
            self.set_zoom_loupe_active(False)
        self._armed_next = None
        self.dismiss_label_picker()
        self.set_hint("")
        if self._caliper_drag_active:
            self._finish_caliper_node_drag(cancel=True)
            return
        if self.mmode.cancel_roi_step():
            self._clear_crosshair()
            return
        if self.doppler.cancel_calibration_step():
            return
        if self.doppler.cancel_active_tool():
            return
        if self._active_contour_item is not None or self._contour_mode_active:
            # A contour mode armed but *not yet drawn* (no node placed) used to
            # survive Esc: the drawing item was None, so every branch fell
            # through and the mode stayed on, leaving the «Контур» button lit
            # forever (item 3 of the 2026-10-23 list).
            self._clear_active_contour_drawing()
            return
        if self._calibration_active:
            self._clear_calibration_caliper()
            self._clear_crosshair()
            return
        self._clear_linear_caliper()
        self._clear_crosshair()
        self._comparison_state = _ComparisonState()

    def contours(self) -> list[Contour]:
        return list(self._stored_contours)

    def get_lv_contour(self, *, phase: str | None = None, view: str | None = None) -> Contour | None:
        """Return an LV contour, preferring the requested phase/view.

        With no filters this matches the historical behaviour (first LV
        contour), so existing callers keep working.
        """
        for contour in self._stored_contours:
            if contour.chamber != "LV":
                continue
            if phase is not None and (contour.phase or "").upper() != phase.upper():
                continue
            if view is not None and (contour.view or "").upper() != view.upper():
                continue
            return contour
        return None

    def get_lv_epicardial_contour(self, *, phase: str, view: str = "A4C") -> Contour | None:
        """Return the editable STE epicardial contour for a phase/view."""
        for contour in self._stored_contours:
            if (
                contour.chamber == "LV_EPI"
                and (contour.phase or "").upper() == phase.upper()
                and (contour.view or "").upper() == view.upper()
            ):
                return contour
        return None

    def ensure_lv_epicardial_contours(self, *, view: str = "A4C", thickness_mm: float = 8.0) -> list[Contour]:
        """Create editable epicardial contours from existing endocardial LV contours.

        For every phase (ED/ES) that has an endo contour but no LV_EPI contour,
        generate the epicardium by expanding the endo along its outward normals
        by ``thickness_mm`` (the STE wall-thickness setting; 8 mm default).
        Existing LV_EPI contours are never overwritten.

        The epicardium is stored as an **open arc with its own mitral-annulus and
        apex landmarks**, exactly like the Simpson LV contour it was expanded
        from. That is what makes it editable with the same toolchain: the
        annulus endpoints stay pinned, every node drag is followed by
        arc-length resampling and the magnetic edge snap, and the displayed
        geometry is the material line rather than a spline closed across the
        annulus. Previously the generated epicardium carried no landmarks, was
        therefore treated as a *closed* contour and silently skipped all of
        that — a dragged node stayed where it was dropped and the node spacing
        became uneven (user report, confirmed by measurement).
        """
        from echo_personal_tool.domain.services.contour_geometry import apex_index_on_open_arc
        from echo_personal_tool.domain.services.myocardial_zone import expand_contour_to_zone

        spacing = self._pixel_spacing() or (1.0, 1.0)
        thickness_px = max(float(thickness_mm), 0.1) / max(float(np.mean(spacing)), 1e-6)
        updated = list(self._stored_contours)
        created: list[Contour] = []
        for phase in ("ED", "ES"):
            endo = self.get_lv_contour(phase=phase, view=view)
            if endo is None or len(endo.points) < 3:
                continue
            if self.get_lv_epicardial_contour(phase=phase, view=view) is not None:
                continue
            epi = expand_contour_to_zone(np.asarray(endo.points, dtype=np.float64), thickness_px)
            epi_points = [(float(x), float(y)) for x, y in epi]
            annulus = (epi_points[0], epi_points[-1])
            apex_index = apex_index_on_open_arc(epi_points, annulus)
            created.append(
                replace(
                    endo,
                    chamber="LV_EPI",
                    points=epi_points,
                    source="ste_auto",
                    mitral_annulus=annulus,
                    apex_landmark=epi_points[apex_index],
                    num_nodes=len(epi_points),
                )
            )
        if created:
            updated.extend(created)
            self.apply_contours(updated)
        return created

    def show_speckle_result(self, result: object) -> None:
        """Display speckle tracking overlay from StrainResult."""
        from echo_personal_tool.domain.models.speckle import StrainResult

        if not isinstance(result, StrainResult):
            return
        self._speckle_result = result
        self._refresh_speckle_overlay_for_current_frame()
        self._speckle_overlay.show()

        if result.raw_tracked_positions is not None:
            self._ste_sensitivity.set_smoothness(1.0)
            self._ste_sensitivity.show()
            self._position_ste_overlay()
        else:
            self._ste_sensitivity.hide()

    def _position_ste_overlay(self) -> None:
        """Position the STE sensitivity overlay at bottom-left of viewer."""
        vh = self.height()
        oh = self._ste_sensitivity.sizeHint().height()
        self._ste_sensitivity.move(10, vh - oh - 10)

    def _on_ste_smoothness_changed(self, smoothness: float) -> None:
        """Re-smooth trajectories with new smoothness factor and refresh overlay."""
        from echo_personal_tool.domain.models.speckle import StrainResult

        result = self._speckle_result
        if not isinstance(result, StrainResult):
            return
        if result.raw_tracked_positions is None:
            return

        from echo_personal_tool.domain.services.strain_computation import (
            apply_drift_compensation,
            compute_gls,
            compute_weighted_longitudinal_strain_gl,
            compute_weighted_radial_strain_gl,
        )
        from echo_personal_tool.domain.services.tracking_smoothing import (
            re_smooth_trajectories,
        )

        raw = result.raw_tracked_positions
        ncc = result.ncc_all_frames
        if raw is None or ncc is None:
            return

        # raw/ncc are full-cine arrays with NaN outside the tracked window;
        # smoothing must run on the window slice only (splines and the
        # Savitzky-Golay filter cannot handle NaN rows).  No motion model is
        # applied here: it is gated off in the worker by default (issue #7,
        # honest tracking) and would fabricate displacement on re-smooth.
        ws = int(result.tracking_window_start)
        we = int(result.tracking_window_end)
        raw_win = raw[ws : we + 1]
        ncc_win = ncc[ws : we + 1]
        if raw_win.size == 0 or not np.all(np.isfinite(raw_win)):
            return
        smoothed = re_smooth_trajectories(raw_win, ncc_win, result.kernels, smoothness)

        n_frames = raw.shape[0]
        tracked = np.full_like(raw, np.nan)
        tracked[ws : we + 1] = smoothed

        ps = self._current_state.pixel_spacing if self._current_state else (1.0, 1.0)
        endo_indices = [i for i, k in enumerate(result.kernels) if k.layer == "endo"]
        epi_indices = [i for i, k in enumerate(result.kernels) if k.layer == "epi"]
        local_ed = result.ed_index - result.tracking_window_start
        local_es = result.es_index - result.tracking_window_start
        ed_ncc = ncc_win[local_ed].copy() if local_ed < len(ncc_win) else np.ones(ncc.shape[1])

        window_long = compute_weighted_longitudinal_strain_gl(smoothed, local_ed, ps, endo_indices, ed_ncc)
        if result.drift_compensation_applied:
            window_long = apply_drift_compensation(window_long, local_ed, local_es)
        from echo_personal_tool.application.workers.speckle_worker import _embed_window_curve

        longitudinal = _embed_window_curve(
            window_long,
            n_frames,
            result.tracking_window_start,
            result.tracking_window_end,
        )

        n_pairs = min(len(endo_indices), len(epi_indices))
        if n_pairs > 0:
            window_radial = compute_weighted_radial_strain_gl(
                smoothed,
                local_ed,
                ps,
                endo_indices[:n_pairs],
                epi_indices[:n_pairs],
                ed_ncc,
            )
            radial = _embed_window_curve(
                window_radial,
                n_frames,
                result.tracking_window_start,
                result.tracking_window_end,
            )
        else:
            radial = np.full(n_frames, np.nan)

        self._speckle_result = replace(
            result,
            longitudinal=longitudinal,
            radial=radial,
            gls=compute_gls(window_long, local_ed, local_es),
            tracked_positions_all=tracked,
            tracked_es_positions=smoothed[local_es].copy()
            if local_es < smoothed.shape[0]
            else result.tracked_es_positions,
            tracked_ed_positions=smoothed[local_ed].copy()
            if local_ed < smoothed.shape[0]
            else result.tracked_ed_positions,
        )

        self._refresh_speckle_overlay_for_current_frame()

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
                self._speckle_overlay.show_kernels(result.kernels, valid, ncc, positions=es_positions)
                # Segment names sit on the wall they measure (documentation §5.3 п.4).
                self._speckle_overlay.show_segment_labels(result.kernels, es_positions)
            if ed_positions is not None and es_positions is not None:
                endo_mask = [i for i, k in enumerate(result.kernels) if k.layer == "endo"]
                if endo_mask:
                    self._speckle_overlay.show_ed_es_displacements(ed_positions[endo_mask], es_positions[endo_mask])
            if result.kernels and result.per_kernel_longitudinal is not None and es_positions is not None:
                self._speckle_overlay.show_strain_color_map(
                    result.kernels, result.per_kernel_longitudinal, positions=es_positions
                )
            self._speckle_overlay.show_verification_marks(None, None, None)
            self._speckle_overlay.show_phase_contours(result.ed_contour, result.es_contour)
            return

        has_tracked = 0 <= frame < result.tracked_positions_all.shape[0] and np.any(
            np.isfinite(result.tracked_positions_all[frame, :, 0])
        )
        if not (phase_lo <= frame <= phase_hi) or not has_tracked:
            self._speckle_overlay.show_kernels([], None, None)
            self._speckle_overlay.show_segment_labels([], None)
            self._speckle_overlay.show_ed_es_displacements(None, None)
            self._speckle_overlay.show_strain_color_map([], np.array([]))
            self._speckle_overlay.show_verification_marks(None, None, None)
            self._speckle_overlay.show_phase_contours(result.ed_contour, result.es_contour)
            return

        positions = result.tracked_positions_all[frame]
        ncc = result.ncc_all_frames[frame]
        valid = np.isfinite(ncc) & (ncc >= ncc_threshold)

        if result.kernels:
            self._speckle_overlay.show_kernels(result.kernels, valid, ncc, positions=positions)
            self._speckle_overlay.show_segment_labels(result.kernels, positions)

        # Round-trip verdicts for the frame on screen (clinical review Q6): the
        # reader sees where the drawn contour is not backed by the image, judged
        # by the same gate the report counted with.
        closure = result.closure_all_frames
        gate_px = float(getattr(result, "closure_gate_px", 0.0) or 0.0)
        if closure is not None and gate_px > 0.0 and 0 <= frame < closure.shape[0]:
            row = np.asarray(closure[frame], dtype=np.float64)
            rejected = np.isfinite(row) & (row > gate_px)
            unverified = ~np.isfinite(row)
            n_rejected, n_unverified = int(np.sum(rejected)), int(np.sum(unverified))
            legend = (
                tr(
                    "strain.overlay_verification",
                    rejected=n_rejected,
                    unverified=n_unverified,
                )
                if (n_rejected or n_unverified)
                else ""
            )
            self._speckle_overlay.show_verification_marks(positions, rejected, unverified, legend)
        else:
            self._speckle_overlay.show_verification_marks(None, None, None)

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
            sorted_endo = sorted(endo_indices, key=lambda i: result.kernels[i].node_index)
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
        self._ste_sensitivity.hide()

    def speckle_result(self) -> StrainResult | None:
        """The speckle-tracking result on display; ``None`` when nothing is shown."""
        return self._speckle_result

    def pending_ai_review_contour(self) -> Contour | None:
        frame_index = self._contour_frame_index()
        instance_uid = self.current_instance_uid()
        if frame_index is None:
            return None
        for contour in self._stored_contours:
            if (
                contour.source == "ai"
                and contour.review_pending
                and contour.frame_index == frame_index
                and (
                    instance_uid is None or contour.sop_instance_uid is None or contour.sop_instance_uid == instance_uid
                )
            ):
                return contour
        return None

    def discard_pending_ai_contour(self) -> bool:
        pending = self.pending_ai_review_contour()
        if pending is None:
            return False
        instance_uid = self.current_instance_uid()
        self._stored_contours = [
            c
            for c in self._stored_contours
            if not (
                c.source == "ai"
                and c.review_pending
                and c.frame_index == pending.frame_index
                and c.phase == pending.phase
                and c.view == pending.view
                and (instance_uid is None or c.sop_instance_uid == instance_uid)
            )
        ]
        self._render_contours_for_current_frame()
        return True

    def delete_contour_for_current_phase(self, view: str = "A4C") -> bool:
        """Remove the last contour for the current frame and view (one at a time).

        The deleted contour is pushed onto the undo/redo stack (S2-04) so it
        can be restored with :meth:`undo`.
        """
        if self._current_state is None:
            return False
        frame_index = self._current_state.current_frame_index
        # Find the last matching contour (LIFO — most recently added)
        last_idx: int | None = None
        for idx in reversed(range(len(self._stored_contours))):
            c = self._stored_contours[idx]
            if c.view.casefold() == view.casefold() and c.frame_index == frame_index:
                last_idx = idx
                break
        if last_idx is None:
            return False
        deleted = self._stored_contours[last_idx]
        del self._stored_contours[last_idx]
        self._undo_redo.push(
            UndoEntry(
                kind="contour",
                payload={"contour": deleted, "index": last_idx},
            )
        )
        self._render_contours_for_current_frame()
        if not self._syncing_state:
            self.contours_changed.emit(self.contours())
        return True

    # ── Undo/redo (S2-04) ───────────────────────────────────────────

    def can_undo(self) -> bool:
        """Whether an undo is available (measurement deletion to reverse)."""
        return self._undo_redo.can_undo

    def can_redo(self) -> bool:
        """Whether a redo is available (undone deletion to re-apply)."""
        return self._undo_redo.can_redo

    def undo(self) -> bool:
        """Undo the last measurement deletion.

        Restores the deleted contour or linear measurement.  Returns ``True``
        when an undo was performed, ``False`` when the stack is empty.
        """
        entry = self._undo_redo.undo()
        if entry is None:
            return False
        if entry.kind == "contour":
            contour = entry.payload["contour"]
            idx = entry.payload.get("index")
            if idx is not None and 0 <= idx <= len(self._stored_contours):
                self._stored_contours.insert(idx, contour)
            else:
                self._stored_contours.append(contour)
            self._render_contours_for_current_frame()
            if not self._syncing_state:
                self.contours_changed.emit(self.contours())
        elif entry.kind == "linear_measurement":
            key = entry.payload["key"]
            measurement = entry.payload["measurement"]
            self._stored_linear_measurements[key] = measurement
            self._emit_stored_linear_measurements()
            self._render_persistent_linear_calipers()
            self._refresh_frame_overlays()
        return True

    def redo(self) -> bool:
        """Re-apply the last undone measurement deletion.

        Deletes the contour or linear measurement again.  Returns ``True``
        when a redo was performed, ``False`` when the redo stack is empty.
        """
        entry = self._undo_redo.redo()
        if entry is None:
            return False
        if entry.kind == "contour":
            contour = entry.payload["contour"]
            # Remove the first matching contour (same identity by points/view/frame).
            for i, c in enumerate(self._stored_contours):
                if (
                    c.points == contour.points
                    and c.view == contour.view
                    and c.frame_index == contour.frame_index
                    and c.phase == contour.phase
                ):
                    del self._stored_contours[i]
                    break
            self._render_contours_for_current_frame()
            if not self._syncing_state:
                self.contours_changed.emit(self.contours())
        elif entry.kind == "linear_measurement":
            key = entry.payload["key"]
            self._stored_linear_measurements.pop(key, None)
            self._emit_stored_linear_measurements()
            self._render_persistent_linear_calipers()
            self._refresh_frame_overlays()
        return True

    def clear_undo_redo(self) -> None:
        """Clear the undo/redo stack.

        Called when the tab/viewer closes so that no measurement data
        survives beyond tab life (S2-04: no PHI beyond tab life).
        """
        self._undo_redo.clear()

    @property
    def is_contour_mode_active(self) -> bool:
        return self._contour_mode_active

    def set_scroll_debounce_ms(self, ms: int) -> None:
        self.transport.set_scroll_debounce_ms(ms)

    def _handle_wheel(self, ev) -> bool:
        _wt0 = time.perf_counter() if _FREEZE_DIAG else 0
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
            return self.zoom.handle_ctrl_wheel(ev, delta_y)

        # Plain scroll → frame navigation
        if self._current_state.total_frames <= 1:
            return False
        step = -1 if delta_y > 0 else 1
        pending = self.transport.pending_scroll_index
        current = pending if pending is not None else self._current_state.current_frame_index
        total = self._current_state.total_frames
        new_index = (current + step) % total
        if new_index == current:
            return False
        ev.accept()
        if _FREEZE_DIAG and _diag_log:
            _diag_log.warning(
                "[wheel] new_idx=%d elapsed=%.3fms",
                new_index,
                (time.perf_counter() - _wt0) * 1000,
            )
        self.transport.queue_scroll(new_index)
        return True

    def zoom_around(self, mx: float, my: float, factor: float) -> bool:
        """Show the frame at *factor*, keeping the scene point under (mx, my) fixed."""
        return self.zoom.zoom_around(mx, my, factor)

    # ── «лупа»: click-to-zoom tool of the tool row ───────────────────────

    def set_zoom_loupe_active(self, active: bool) -> None:
        """Arm/disarm the magnifier tool (the row's «Лупа» button)."""
        self.zoom.set_loupe_active(active)

    def zoom_loupe_active(self) -> bool:
        return self.zoom.loupe_active

    def _update_timeline_indicator(self, viewer_state: ViewerState) -> None:
        self.transport.update_timeline_indicator(viewer_state)

    def append_frame_overlay(self, line: str) -> None:
        self._frame_overlay_lines.append(line)
        self._refresh_frame_overlay()

    def clear_frame_overlay(self) -> None:
        self._frame_overlay_lines.clear()
        self._refresh_frame_overlay()

    def frame_overlay_lines(self) -> tuple[str, ...]:
        """The lines of the frame overlay, in the order they were added."""
        return tuple(self._frame_overlay_lines)

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
        if self._comparison_state.kind:
            self._comparison_state.reset()
        self._linear_caliper_active = False
        self._caliper_repeat_mode = False
        self._linear_caliper_start = None
        self._clear_linear_caliper_graphics()
        self._caliper_sequence = []
        self._caliper_sequence_size = 0
        self.mmode.reset_session_vertical_labels()
        self._measurement_label.setText(f"{self._current_caliper_label()}: —")
        self._sync_persistent_loupe()
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
        self.mmode.on_calibration_caliper_cleared()
        self._calibration_kind = None
        self._clear_calibration_graphics()
        if not self._linear_caliper_active:
            self._measurement_label.setText(f"{self._current_caliper_label()}: —")
        self.doppler.on_calibration_caliper_cleared()

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
        pen = pg.mkPen(dark_theme.get_theme_tokens()["overlay.label"], width=1, style=Qt.PenStyle.DashLine)
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
        for simpson_item in self._contour_simpson_items:
            self._view.removeItem(simpson_item)
        self._contour_items.clear()
        self._contour_nodes.clear()
        self._contour_ma_items.clear()
        self._contour_simpson_items.clear()
        self._contours.clear()

    def _clear_contours(self) -> None:
        self._stored_contours.clear()
        self._clear_rendered_contours()
        self._clear_active_contour_drawing()
        if not self._syncing_state:
            self.contours_changed.emit([])

    # ── Ghost overlays (temporal fusion) ──────────────────────────────────

    @property
    def ghost_mode(self) -> str:
        return self._ghost_mode

    def toggle_ghost_mode(self) -> str:
        """Toggle center-only ghost overlay. Returns new mode."""
        if self._ghost_mode == "center":
            self._ghost_mode = "off"
        else:
            self._ghost_mode = "center"
        self._render_ghost_overlay()
        return self._ghost_mode

    def set_ghost_mode(self, mode: str) -> None:
        self._ghost_mode = mode
        self._render_ghost_overlay()

    def cycle_neighbor_ghost(self, direction: int = 1) -> None:
        """Cycle which neighbor ghost is shown."""
        result = self._get_fusion_result()
        if result is None or not result.neighbor_contours:
            return
        keys = sorted(result.neighbor_contours.keys())
        if not keys:
            return
        current_pos = 0
        if self._ghost_neighbor_index in keys:
            current_pos = keys.index(self._ghost_neighbor_index)
        new_pos = (current_pos + direction) % len(keys)
        self._ghost_neighbor_index = keys[new_pos]
        self._ghost_mode = "neighbor"
        self._render_ghost_overlay()

    def _get_fusion_result(self):
        """Get temporal fusion result from the controller (if a provider was wired)."""
        if self._fusion_result_provider is not None:
            return self._fusion_result_provider()
        return None

    def _clear_ghost_overlay(self) -> None:
        for item in self._ghost_items:
            self._view.removeItem(item)
        self._ghost_items.clear()

    def _render_ghost_overlay(self) -> None:
        """Render ghost contour based on current ghost_mode."""
        self._clear_ghost_overlay()
        if self._ghost_mode == "off":
            return
        result = self._get_fusion_result()
        if result is None:
            return

        if self._ghost_mode == "center":
            contour = result.center_contour
            pen = self._contour_pen_ghost_center
        elif self._ghost_mode == "neighbor":
            contour = result.neighbor_contours.get(self._ghost_neighbor_index)
            pen = self._contour_pen_ghost_neighbor
        else:
            return

        if contour is None:
            return

        x_values, y_values = self._contour_xy(contour, closed=not contour.is_open_arc)
        line_item = pg.PlotDataItem(pen=pen)
        line_item.setZValue(18)
        line_item.setAlpha(0.5, auto=False)
        line_item.setData(x_values, y_values)
        self._view.addItem(line_item)
        self._ghost_items.append(line_item)

        if contour.is_open_arc and contour.mitral_annulus is not None:
            septal, lateral = contour.mitral_annulus
            ma_item = pg.PlotDataItem(pen=self._contour_pen_ghost_center)
            ma_item.setZValue(17)
            ma_item.setAlpha(0.3, auto=False)
            ma_item.setData([septal[0], lateral[0]], [septal[1], lateral[1]])
            self._view.addItem(ma_item)
            self._ghost_items.append(ma_item)

    def _render_contours_for_current_frame(self) -> None:
        if self._current_state is None:
            visible = list(self._stored_contours)
        else:
            frame_index = self._current_state.current_frame_index
            instance_uid = self.current_instance_uid()
            visible = [
                contour
                for contour in self._stored_contours
                if contour.frame_index == frame_index
                and (
                    instance_uid is None or contour.sop_instance_uid is None or contour.sop_instance_uid == instance_uid
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
        is_planimeter = contour.chamber.upper() in {GENERIC_AREA_CHAMBER, GENERIC_VOLUME_CHAMBER}
        for index, existing in enumerate(self._stored_contours):
            if (
                existing.phase.casefold() == contour.phase.casefold()
                and existing.view.casefold() == contour.view.casefold()
                and existing.chamber.casefold() == contour.chamber.casefold()
                and existing.frame_index == contour.frame_index
                and existing.sop_instance_uid == instance_uid
            ):
                if is_planimeter and existing.measurement_label != contour.measurement_label:
                    continue
                return index
        return None

    def _tag_contour_instance(self, contour: Contour) -> Contour:
        instance_uid = self.current_instance_uid()
        if instance_uid is None or contour.sop_instance_uid == instance_uid:
            return contour
        return replace(contour, sop_instance_uid=instance_uid)

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
        self._freehand_recording = False
        self._freehand_open_arc = False
        self._freehand_points = []
        self._active_contour_phase = None
        self._contour_stage = None
        self._contour_mode_kind = None
        self._contour_mode_active = False
        self._reset_contour_click_tracking()
        self._set_contour_nodes_pickable(True)

    # ── Contour click tracking / finish gesture ────────────────────

    def _reset_contour_click_tracking(self) -> None:
        """Forget previous clicks so a new contour starts with a clean gesture state."""
        self._last_contour_click_ms = None
        self._last_contour_click_screen = None
        self._last_contour_point_screen = None
        self._first_contour_point_screen = None

    @staticmethod
    def _event_screen_point(ev) -> tuple[float, float] | None:
        """Screen-space position of a graphics event, or None when unavailable."""
        try:
            pos = ev.screenPos()
        except Exception:  # noqa: BLE001 - test doubles may not provide it
            return None
        if pos is None:
            return None
        return float(pos.x()), float(pos.y())

    def _remember_contour_click(self, screen_point: tuple[float, float] | None) -> None:
        self._last_contour_click_ms = time.monotonic() * 1000.0
        self._last_contour_click_screen = screen_point

    def _is_repeat_click(
        self,
        screen_point: tuple[float, float] | None,
        *,
        qt_double: bool,
    ) -> bool:
        """True when this click lands on the previous one (a real double-click).

        Qt's ``double()`` flag is time-only, so it also fires when the user
        clicks two *different* contour points quickly. Requiring the clicks to
        be within :data:`_CONTOUR_FINISH_MAX_SCREEN_PX` of each other is what
        separates "close the contour" from "next point, fast".
        """
        previous = self._last_contour_click_screen
        previous_ms = self._last_contour_click_ms
        if previous is None or previous_ms is None or screen_point is None:
            # Without a reference click the gesture cannot be verified — never
            # close a contour on a guess.
            return False
        elapsed = (time.monotonic() * 1000.0) - previous_ms
        if elapsed > _CONTOUR_FINISH_MAX_INTERVAL_MS:
            return False
        distance = math.hypot(screen_point[0] - previous[0], screen_point[1] - previous[1])
        return distance <= _CONTOUR_FINISH_MAX_SCREEN_PX

    def _is_close_first_point_click(self, screen_point: tuple[float, float] | None) -> bool:
        """True when the click lands on the first polygon point (click-to-close)."""
        if screen_point is None or self._first_contour_point_screen is None:
            return False
        if len(self._active_arc_points) < _CONTOUR_MIN_POINTS_TO_CLOSE:
            return False
        first = self._first_contour_point_screen
        distance = math.hypot(screen_point[0] - first[0], screen_point[1] - first[1])
        return distance <= _CONTOUR_CLOSE_FIRST_POINT_PX

    def _forget_contour_point_screens(self) -> None:
        self._first_contour_point_screen = None
        self._last_contour_point_screen = None

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

        # Simpson visualization for confirmed LV contours
        if contour.chamber.upper() == "LV" and contour.is_open_arc and not contour.review_pending:
            self._append_simpson_lines(contour)

        node_items: list[_ContourNodeItem] = []
        for point_index, point in enumerate(contour.points):
            node = _ContourNodeItem(self, contour_index, point_index, point, pen)
            self._view.addItem(node)
            node_items.append(node)
        return line_item, ma_item, node_items

    def _append_simpson_lines(self, contour: Contour) -> None:
        """Add central axis + transverse disk lines for Simpson visualization."""
        from echo_personal_tool.domain.calculations.lvef_simpson import (
            compute_simpson_lines,
        )

        lines = compute_simpson_lines(contour)
        if lines is None:
            return

        # Central axis line (MV midpoint → apex)
        base, tip = lines.central_line
        central_item = pg.PlotDataItem(pen=self._contour_pen_simpson)
        central_item.setZValue(15)
        central_item.setData([base[0], tip[0]], [base[1], tip[1]])
        self._view.addItem(central_item)
        self._contour_simpson_items.append(central_item)

        # Transverse disk lines
        for left, right in lines.disk_lines:
            disk_item = pg.PlotDataItem(pen=self._contour_pen_simpson)
            disk_item.setZValue(15)
            disk_item.setData([left[0], right[0]], [left[1], right[1]])
            self._view.addItem(disk_item)
            self._contour_simpson_items.append(disk_item)

    def _update_simpson_lines(self, contour_index: int, contour: Contour) -> None:
        """Remove old Simpson lines and re-render from updated contour."""
        from echo_personal_tool.domain.calculations.lvef_simpson import (
            compute_simpson_lines,
        )

        # Remove all existing Simpson lines
        for item in self._contour_simpson_items:
            self._view.removeItem(item)
        self._contour_simpson_items.clear()

        # Compute and render new lines
        lines = compute_simpson_lines(contour)
        if lines is None:
            return

        base, tip = lines.central_line
        central_item = pg.PlotDataItem(pen=self._contour_pen_simpson)
        central_item.setZValue(15)
        central_item.setData([base[0], tip[0]], [base[1], tip[1]])
        self._view.addItem(central_item)
        self._contour_simpson_items.append(central_item)

        for left, right in lines.disk_lines:
            disk_item = pg.PlotDataItem(pen=self._contour_pen_simpson)
            disk_item.setZValue(15)
            disk_item.setData([left[0], right[0]], [left[1], right[1]])
            self._view.addItem(disk_item)
            self._contour_simpson_items.append(disk_item)

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
        if contour.chamber.upper() == "LV_EPI":
            return pg.mkPen(dark_theme.get_theme_tokens()["overlay.marker"], width=2, style=Qt.PenStyle.DashLine)
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
        if is_planimeter_polygon(contour) or (contour.is_open_arc and len(points) >= 2):
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
            return dark_theme.get_theme_tokens()["overlay.contour.manual"]
        return dark_theme.get_theme_tokens()["overlay.contour.model"]

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
                    self._contours[contour_index] = replace(contour, mitral_annulus=(septal, lateral))
                    self._refresh_mitral_annulus_line(contour_index)
                    return
                if grab_index == last_index:
                    septal = contour.mitral_annulus[0]
                    lateral = (
                        float(contour.points[last_index][0]),
                        float(contour.points[last_index][1]),
                    )
                    self._contours[contour_index] = replace(contour, mitral_annulus=(septal, lateral))
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
        if self.mmode.handle_line_hover(float(cursor[0]), float(cursor[1])):
            return True
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
        contour = replace(contour, refine_step=0, refine_locked_indices=())
        if contour.is_open_arc:
            num_nodes = contour.num_nodes or DEFAULT_NODE_COUNT
            if contour.mitral_annulus is not None and len(contour.points) >= 2:
                septal = (float(contour.points[0][0]), float(contour.points[0][1]))
                lateral = (
                    float(contour.points[-1][0]),
                    float(contour.points[-1][1]),
                )
                contour = replace(contour, mitral_annulus=(septal, lateral))
                apex = contour.apex_landmark or apex_point(contour.points, contour.mitral_annulus)
                resampled = resample_open_arc_landmarks(
                    contour.points,
                    septal=septal,
                    lateral=lateral,
                    apex=apex,
                    num_nodes=num_nodes,
                )
                contour.points[:] = resampled
                contour = replace(contour, mitral_annulus=(septal, lateral), apex_landmark=apex)
            else:
                resampled = resample_open_arc(contour.points, num_nodes=num_nodes)
                contour.points[:] = resampled
            self._contours[contour_index] = contour
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
            self._recalculate_percent_s()
            self._recalculate_stenosis_area()
            self._emit_stored_linear_measurements()
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
        # Update Simpson lines if this is a confirmed LV contour
        if not during_drag and contour.chamber.upper() == "LV" and contour.is_open_arc and not contour.review_pending:
            self._update_simpson_lines(contour_index, contour)

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
        if self._calibration_ok_timer is None:
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
                    if self._comparison_state.kind in {"area", "ar_jet_area"}:
                        continue
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
                            finish_key=shortcut_label("finish_tool"),
                        )
                    )
            for measurement in self._linear_measurements_for_frame(frame_index):
                # Ratios and planimeter areas get their own comparison line
                # below; listing them as calipers would print each number twice.
                if measurement.label in PERCENT_LABELS or measurement.label in AREA_LABELS:
                    continue
                self.append_frame_overlay(measurement.display_text())
        if self._comparison_state.kind in {"diameter", "ar_jet_diameter"} and self._comparison_state.first_segment_done:
            cmp_line = self._build_comparison_d_overlay()
            if cmp_line:
                self.append_frame_overlay(cmp_line)
        if self._comparison_state.kind in {"area", "ar_jet_area"} and self._comparison_state.first_contour_done:
            cmp_line = self._build_comparison_s_overlay()
            if cmp_line:
                self.append_frame_overlay(cmp_line)
        if self._comparison_state.kind == "stenosis_diameter" and self._comparison_state.first_segment_done:
            cmp_line = self._build_stenosis_diameter_overlay()
            if cmp_line:
                self.append_frame_overlay(cmp_line)
        if self._comparison_state.kind == "stenosis_area" and self._comparison_state.first_contour_done:
            cmp_line = self._build_stenosis_area_overlay()
            if cmp_line:
                self.append_frame_overlay(cmp_line)
        for line in extra_lines:
            self.append_frame_overlay(line)

    def _build_comparison_d_overlay(self) -> str:
        state = self._comparison_state
        if (
            state.kind not in {"diameter", "ar_jet_diameter"}
            or not state.first_segment_done
            or state.segment2_mm is None
        ):
            return ""
        l1 = state.segment1_mm if state.segment1_mm is not None else 0.0
        l2 = state.segment2_mm if state.segment2_mm is not None else 0.0
        if l1 == 0 and l2 == 0:
            return ""
        if state.kind == "ar_jet_diameter":
            pct = (l1 / l2 * 100.0) if l2 > 0 else 0.0
            label1, label2 = "AR Jet D1", "LVOTd"
        else:
            bigger = max(l1, l2)
            smaller = min(l1, l2)
            pct = (smaller / bigger * 100.0) if bigger > 0 else 0.0
            label1, label2 = "D1", "D2"
        unit = self._length_display_unit
        m1 = LinearMeasurement(label=label1, pixel_length=0, millimeter_length=l1)
        m2 = LinearMeasurement(label=label2, pixel_length=0, millimeter_length=l2)
        return tr(
            "viewer.ar_jet_dcmp_result" if state.kind == "ar_jet_diameter" else "viewer.dcmp_result",
            label1=label1,
            length1=inline_caliper_text(m1, length_unit=unit),
            label2=label2,
            length2=inline_caliper_text(m2, length_unit=unit),
            percent_d=f"{_fmt('vessel.stenosis_d', pct, '%')}%",
        )

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
                    measurement.start,
                    measurement.end,
                    color=dark_theme.get_theme_tokens()["overlay.caliper.doppler"],
                    is_preview=False,
                    measurement=measurement,
                )

    def _create_linear_graphics_items(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        caliper_key: tuple[str, int],
    ) -> tuple[pg.PlotDataItem, _CaliperNodeItem, _CaliperNodeItem]:
        pen = self._caliper_pen(dark_theme.get_theme_tokens()["overlay.caliper.doppler"])
        line_item = pg.PlotDataItem(pen=pen)
        line_item.setZValue(24)
        line_item.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        line_item.setAcceptHoverEvents(True)
        line_item.setData([start[0], end[0]], [start[1], end[1]])
        line_item.sigClicked.connect(lambda _, k=caliper_key: self._select_caliper(k))
        self._view.addItem(line_item)
        start_node = _CaliperNodeItem(
            self,
            caliper_key,
            0,
            start,
            pen,
        )
        start_node.setZValue(30)
        self._view.addItem(start_node)
        end_node = _CaliperNodeItem(
            self,
            caliper_key,
            1,
            end,
            pen,
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

        if ev.button() == Qt.MouseButton.RightButton:
            # Right-click = undo the last point instead of losing the whole contour.
            if self._undo_last_contour_point():
                ev.accept()
                return True
            return False

        if ev.button() != Qt.MouseButton.LeftButton:
            return False

        self._hide_magnifier_on_point()
        ev.accept()
        qt_double = bool(ev.double())
        screen_point = self._event_screen_point(ev)
        repeat_click = self._is_repeat_click(screen_point, qt_double=qt_double)

        if self._freehand_recording and (self._area_tool_mode == "freehand" or self._freehand_open_arc):
            # A repeat click in place is the finish gesture. Otherwise an
            # open-arc trace also lets a plain click drop a single node.
            self._remember_contour_click(screen_point)
            if repeat_click and len(self._freehand_points) >= _CONTOUR_MIN_POINTS_TO_CLOSE:
                self._finish_active_freehand_contour()
                return True
            if self._freehand_open_arc:
                point = self._view.mapSceneToView(ev.scenePos())
                view_point = (float(point.x()), float(point.y()))
                if (
                    not self._freehand_points
                    or self._distance(self._freehand_points[-1], view_point) > _CONTOUR_MIN_POINT_SPACING_PX
                ):
                    self._freehand_points.append(view_point)
                    self._update_freehand_preview()
            return True

        point = self._view.mapSceneToView(ev.scenePos())
        view_point = (float(point.x()), float(point.y()))
        placed_points = self._active_arc_points if self._contour_stage == "polygon" else None

        if placed_points is not None:
            if self._is_close_first_point_click(screen_point):
                # Click on the first point closes the polygon (no duplicate point).
                self.finish_contour()
                return True
            if repeat_click and len(placed_points) >= _CONTOUR_MIN_POINTS_TO_CLOSE:
                # Deliberate double-click in one spot: finish, do not add the
                # duplicate point that Qt folded into this event.
                self.finish_contour()
                return True
            if self._is_duplicate_point(view_point, screen_point):
                # Same spot twice — keep the polygon clean, but remember the
                # click so a following one still counts as a finish gesture.
                self._remember_contour_click(screen_point)
                return True
            if len(placed_points) == 0:
                self._first_contour_point_screen = screen_point
            self._last_contour_point_screen = screen_point
            self._remember_contour_click(screen_point)
            self.handle_contour_click(view_point)
            return True

        # Landmark stages (LV/LA contour: MA septal → MA lateral → apex → arc).
        # Only a double-click *in one spot* finishes; a Qt "double" that lands
        # elsewhere is the next landmark placed quickly.
        if repeat_click:
            self.finish_contour()
            return True
        self._remember_contour_click(screen_point)
        self.handle_contour_click(view_point)
        return True

    def _is_duplicate_point(
        self,
        view_point: tuple[float, float],
        screen_point: tuple[float, float] | None,
    ) -> bool:
        """True when the click repeats the previous point (trembling hand)."""
        if not self._active_arc_points:
            return False
        last = self._active_arc_points[-1]
        if math.hypot(view_point[0] - last[0], view_point[1] - last[1]) <= _CONTOUR_MIN_POINT_SPACING_PX:
            return True
        if screen_point is None or self._last_contour_point_screen is None:
            return False
        previous = self._last_contour_point_screen
        return math.hypot(screen_point[0] - previous[0], screen_point[1] - previous[1]) <= _CONTOUR_MIN_POINT_SPACING_PX

    def _undo_last_contour_point(self) -> bool:
        """Remove the most recently placed point of the active contour."""
        if self._freehand_recording and self._freehand_points:
            self._freehand_points.pop()
            self._update_freehand_preview()
            return True
        if not self._active_arc_points:
            return False
        self._active_arc_points.pop()
        self._last_contour_point_screen = None
        if self._contour_stage == "polygon" and not self._active_arc_points:
            self._first_contour_point_screen = None
        self._update_active_contour_item()
        self._update_planimeter_progress_label()
        return True

    @staticmethod
    def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
        return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5

    def _update_freehand_preview(self) -> None:
        if self._active_contour_item is None or not self._freehand_points:
            return
        xs = [p[0] for p in self._freehand_points]
        ys = [p[1] for p in self._freehand_points]
        self._active_contour_item.setData(xs, ys)

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
                spline_points = sample_spline(markers, num_samples=64) if len(markers) >= 3 else markers
        elif self._contour_stage == "polygon" and self._active_arc_points:
            markers = list(self._active_arc_points)
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
        self._update_planimeter_progress_label()

    def _update_planimeter_progress_label(self) -> None:
        """Show the provisional area/volume while the polygon is still open.

        The planimeter is a comparison tool as often as it is an absolute one,
        so the operator needs the number *while* drawing — not only after the
        contour is closed and can no longer be corrected cheaply.
        """
        if self._contour_stage != "polygon" or not self._active_arc_points:
            return
        chamber = (self._active_contour_chamber or "").upper()
        if chamber not in {GENERIC_AREA_CHAMBER, GENERIC_VOLUME_CHAMBER}:
            return
        if len(self._active_arc_points) < _CONTOUR_MIN_POINTS_TO_CLOSE:
            self._measurement_label.setText(tr_plural("viewer.area_points_needed", _CONTOUR_MIN_POINTS_TO_CLOSE))
            return
        spacing, calibrated = self._effective_pixel_spacing()
        probe = Contour(
            phase=self._active_contour_phase or "GEN",
            view=self._active_contour_view,
            chamber=chamber,
            points=list(self._active_arc_points),
            frame_index=self._contour_frame_index(),
        )
        if chamber == GENERIC_VOLUME_CHAMBER:
            value = closed_polygon_volume_ml(probe, spacing)
            text = (
                tr("viewer.volume_progress", value=_fmt("planimeter.volume", value, "mL"))
                if value is not None
                else None
            )
        else:
            value = closed_polygon_area_cm2(probe, spacing)
            text = (
                tr("viewer.area_progress", value=_fmt("planimeter.area", value, "cm²")) if value is not None else None
            )
        if text is None:
            return
        if not calibrated:
            text += tr("viewer.area_progress_no_calibration")
        self._measurement_label.setText(text)

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
            if self.mmode.time_start_x is None:
                self.mmode.mark_time_start(x)
                self._calibration_start_y = y
                self._update_mmode_time_preview(x, x, y)
                return True
            length_px = abs(x - float(self.mmode.time_start_x))
            if length_px >= 1.0:
                self.mmode.prompt_time_span(length_px)
            return True

        y = max(0.0, min(float(click[1]), float(height - 1)))
        if self._calibration_kind == "doppler_velocity" and self.doppler.grid_line_positions:
            y = snap_y_to_nearest_tick(
                y, self.doppler.grid_line_positions, radius_px=self._calibration_tick_snap_radius_px
            )
        else:
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
                self.mmode.prompt_depth_calibration(length_px)
            elif self._calibration_kind in {"spectral", "doppler_velocity"}:
                self.doppler.prompt_spectral_velocity_span(length_px)
            else:
                self._prompt_calibration_distance(length_px)
        return True

    def _ensure_calibration_graphics(self) -> None:
        if self._calibration_line_item is None:
            pen = self._caliper_pen(dark_theme.get_theme_tokens()["overlay.caliper.doppler"])
            self._calibration_line_item = pg.PlotDataItem(pen=pen)
            self._calibration_line_item.setZValue(25)
            self._calibration_line_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self._calibration_line_item.setAcceptHoverEvents(False)
            self._view.addItem(self._calibration_line_item)
        if self._calibration_marker_item is None:
            marker_pen = self._caliper_pen(dark_theme.get_theme_tokens()["overlay.caliper.doppler"])
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
        if self.is_label_picker_visible():
            self.dismiss_label_picker()
        if not self._linear_caliper_active:
            return False
        if self._comparison_state.kind in {"diameter", "ar_jet_diameter"}:
            return self._handle_diameter_compare_press(ev)
        if self._comparison_state.kind == "stenosis_diameter":
            return self._handle_diameter_compare_press(ev, stenosis=True)
        if ev.button() != Qt.MouseButton.LeftButton:
            return False
        if self._calibration_active:
            return False
        self._hide_magnifier_on_point()

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
            and self.mmode.calibration_state is not None
            and not self.mmode.calibration_state.roi.contains(click[0], click[1])
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

    def _handle_diameter_compare_press(self, ev, *, stenosis: bool = False) -> bool:
        if ev.button() != Qt.MouseButton.LeftButton:
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

        state = self._comparison_state
        frame = state.frame_index
        is_stenosis = stenosis or state.kind == "stenosis_diameter"
        is_ar_jet = state.kind == "ar_jet_diameter"
        label1, label2, pct_label = compare_labels("ar_jet_diameter" if is_ar_jet else "diameter")
        mode = "ar_jet" if is_ar_jet else "stenosis" if is_stenosis else "diameter"
        click_end_key, second_start_key, second_end_key = DIAMETER_HINTS[mode]

        if state.segment1_start is None:
            state.segment1_start = click
            self._update_linear_caliper_preview(click, click)
            self._measurement_label.setText(tr(click_end_key))
            return True

        if state.segment1_end is None:
            state.segment1_end = click
            state.segment1_mm = self._compare_mm_length(label1, state.segment1_start, click)
            key = (label1, frame if frame is not None else -1)
            instance_uid = self.current_instance_uid() or ""
            self._stored_linear_measurements[key] = LinearMeasurement(
                label=label1,
                pixel_length=math.hypot(click[0] - state.segment1_start[0], click[1] - state.segment1_start[1]),
                millimeter_length=state.segment1_mm,
                frame_index=frame,
                start=state.segment1_start,
                end=click,
                sop_instance_uid=instance_uid,
                submillimeter=self._vessel_measurement_mode or self._tenth_mm_precision,
            )
            self._render_persistent_linear_calipers()
            self._refresh_frame_overlays()
            self._emit_stored_linear_measurements()
            self._linear_caliper_start = None
            self._clear_linear_caliper_graphics()
            self._linear_caliper_active = True
            self._measurement_label.setText(tr(second_start_key))
            return True

        if state.segment2_start is None:
            state.segment2_start = click
            self._linear_caliper_start = click
            self._update_linear_caliper_preview(click, click)
            self._measurement_label.setText(tr(second_end_key))
            return True

        state.segment2_end = click
        state.segment2_mm = self._compare_mm_length(label2, state.segment2_start, click)
        key = (label2, frame if frame is not None else -1)
        instance_uid = self.current_instance_uid() or ""
        self._stored_linear_measurements[key] = LinearMeasurement(
            label=label2,
            pixel_length=math.hypot(click[0] - state.segment2_start[0], click[1] - state.segment2_start[1]),
            millimeter_length=state.segment2_mm,
            frame_index=frame,
            start=state.segment2_start,
            end=click,
            sop_instance_uid=instance_uid,
            submillimeter=self._vessel_measurement_mode or self._tenth_mm_precision,
        )
        if is_stenosis:
            stenosis_pct = self._compute_stenosis_diameter(state.segment1_mm, state.segment2_mm)
            if stenosis_pct is not None:
                pct_key = ("%D", frame if frame is not None else -1)
                self._stored_linear_measurements[pct_key] = LinearMeasurement(
                    label="%D",
                    pixel_length=0.0,
                    millimeter_length=stenosis_pct,
                    frame_index=frame,
                    sop_instance_uid=instance_uid,
                )
        else:
            # The AR tool keeps jet / LVOT, the generic one smaller / larger.
            pct_d = percent_d(state.kind, state.segment1_mm, state.segment2_mm)
            if pct_d is not None:
                pct_key = (pct_label, frame if frame is not None else -1)
                self._stored_linear_measurements[pct_key] = LinearMeasurement(
                    label=pct_label,
                    pixel_length=0.0,
                    millimeter_length=pct_d,
                    frame_index=frame,
                    sop_instance_uid=instance_uid,
                )
        self._linear_caliper_start = None
        self._clear_linear_caliper_graphics()
        self._render_persistent_linear_calipers()
        self._refresh_frame_overlays()
        self._linear_caliper_active = False
        self._emit_stored_linear_measurements()
        if is_stenosis:
            result_text = self._build_stenosis_diameter_overlay()
        else:
            result_text = self._build_comparison_d_overlay()
        if result_text:
            self._measurement_label.setText(result_text)
        return True

    def _compare_mm_length(
        self,
        label: str,
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> float:
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        pixel_length = math.hypot(dx, dy)
        angle_degrees = math.degrees(math.atan2(dy, dx))
        pixel_spacing = self._pixel_spacing_for_linear_label(label, start, end)
        if pixel_spacing is not None:
            return pixel_to_mm_length(pixel_length, angle_degrees, pixel_spacing)
        return pixel_length

    def _recalculate_percent_d(self) -> None:
        kind = self._comparison_state.kind
        if kind not in {"diameter", "ar_jet_diameter"}:
            return
        first_label, second_label, pct_label = compare_labels(kind)
        d1_mm, d2_mm, frame, instance_uid = stored_widths(self._stored_linear_measurements, first_label, second_label)
        pct_d = percent_d(kind, d1_mm, d2_mm)
        pct_key = (pct_label, frame if frame is not None else -1)
        if pct_d is not None:
            self._stored_linear_measurements[pct_key] = LinearMeasurement(
                label=pct_label,
                pixel_length=0.0,
                millimeter_length=pct_d,
                frame_index=frame,
                sop_instance_uid=instance_uid,
            )
        elif pct_key in self._stored_linear_measurements:
            del self._stored_linear_measurements[pct_key]

    def _recalculate_percent_s(self) -> None:
        state = self._comparison_state
        if state.kind not in {"area", "ar_jet_area"}:
            return
        frame = state.frame_index
        instance_uid = self.current_instance_uid() or ""
        spacing, _ = self._effective_pixel_spacing()
        if spacing is None:
            return
        from echo_personal_tool.domain.calculations.planimeter import closed_polygon_area_cm2

        # Recompute areas from the *actual* stored contours, not from the
        # cached values in ``_comparison_state``.  The cached areas go stale
        # as soon as the user drags/corrects a contour node — then %S would
        # stop updating (the reported bug).  Reading from ``_stored_contours``
        # mirrors what _recalculate_stenosis_area already does.
        first_label, second_label, pct_label = compare_labels(state.kind)
        area1: float | None = None
        area2: float | None = None
        for c in self._stored_contours:
            if c.chamber.upper() not in {GENERIC_AREA_CHAMBER, GENERIC_VOLUME_CHAMBER}:
                continue
            if c.frame_index != frame:
                continue
            a = closed_polygon_area_cm2(c, spacing)
            if a is None or a <= 0:
                continue
            if area1 is None:
                area1 = a
                s1_key = (first_label, frame if frame is not None else -1)
                self._stored_linear_measurements[s1_key] = LinearMeasurement(
                    label=first_label,
                    pixel_length=0.0,
                    millimeter_length=a,
                    frame_index=frame,
                    sop_instance_uid=instance_uid,
                )
            elif area2 is None:
                area2 = a
                s2_key = (second_label, frame if frame is not None else -1)
                self._stored_linear_measurements[s2_key] = LinearMeasurement(
                    label=second_label,
                    pixel_length=0.0,
                    millimeter_length=a,
                    frame_index=frame,
                    sop_instance_uid=instance_uid,
                )
        state.contour1_area_cm2 = area1
        state.contour2_area_cm2 = area2
        pct_s = self._compute_percent_s()
        pct_key = (pct_label, frame if frame is not None else -1)
        if pct_s is not None:
            self._stored_linear_measurements[pct_key] = LinearMeasurement(
                label=pct_label,
                pixel_length=0.0,
                millimeter_length=pct_s,
                frame_index=frame,
                sop_instance_uid=instance_uid,
            )
        elif pct_key in self._stored_linear_measurements:
            del self._stored_linear_measurements[pct_key]

    def _recalculate_stenosis_diameter(self) -> None:
        if self._comparison_state.kind != "stenosis_diameter":
            return
        d1_mm: float | None = None
        d2_mm: float | None = None
        frame: int | None = None
        instance_uid = ""
        for key, m in self._stored_linear_measurements.items():
            if isinstance(key, tuple) and key[0] in ("D1", "D2"):
                if m.label == "D1":
                    d1_mm = m.millimeter_length
                    frame = m.frame_index
                    instance_uid = m.sop_instance_uid
                elif m.label == "D2":
                    d2_mm = m.millimeter_length
                    frame = m.frame_index
                    instance_uid = m.sop_instance_uid
        stenosis = self._compute_stenosis_diameter(d1_mm, d2_mm)
        pct_key = ("%D", frame if frame is not None else -1)
        if stenosis is not None:
            self._stored_linear_measurements[pct_key] = LinearMeasurement(
                label="%D",
                pixel_length=0.0,
                millimeter_length=stenosis,
                frame_index=frame,
                sop_instance_uid=instance_uid,
            )
        elif pct_key in self._stored_linear_measurements:
            del self._stored_linear_measurements[pct_key]

    def _recalculate_stenosis_area(self) -> None:
        state = self._comparison_state
        if state.kind != "stenosis_area":
            return
        frame = state.frame_index
        instance_uid = self.current_instance_uid() or ""
        spacing, _ = self._effective_pixel_spacing()
        if spacing is None:
            return
        from echo_personal_tool.domain.calculations.planimeter import closed_polygon_area_cm2

        area1: float | None = None
        area2: float | None = None
        for c in self._stored_contours:
            if c.chamber.upper() not in {GENERIC_AREA_CHAMBER, GENERIC_VOLUME_CHAMBER}:
                continue
            if c.frame_index != frame:
                continue
            a = closed_polygon_area_cm2(c, spacing)
            if a is None or a <= 0:
                continue
            if area1 is None:
                area1 = a
                s1_key = ("S1", frame if frame is not None else -1)
                self._stored_linear_measurements[s1_key] = LinearMeasurement(
                    label="S1",
                    pixel_length=0.0,
                    millimeter_length=a,
                    frame_index=frame,
                    sop_instance_uid=instance_uid,
                )
            elif area2 is None:
                area2 = a
                s2_key = ("S2", frame if frame is not None else -1)
                self._stored_linear_measurements[s2_key] = LinearMeasurement(
                    label="S2",
                    pixel_length=0.0,
                    millimeter_length=a,
                    frame_index=frame,
                    sop_instance_uid=instance_uid,
                )
        state.contour1_area_cm2 = area1
        state.contour2_area_cm2 = area2
        stenosis = self._compute_stenosis_area(area1, area2)
        pct_key = ("%S", frame if frame is not None else -1)
        if stenosis is not None:
            self._stored_linear_measurements[pct_key] = LinearMeasurement(
                label="%S",
                pixel_length=0.0,
                millimeter_length=stenosis,
                frame_index=frame,
                sop_instance_uid=instance_uid,
            )
        elif pct_key in self._stored_linear_measurements:
            del self._stored_linear_measurements[pct_key]

    def _constrain_linear_endpoint(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        label: str | None = None,
    ) -> tuple[float, float]:
        effective_label = label or self._current_caliper_label()
        if effective_label in self._vertical_caliper_labels:
            end_y = end[1]
            if self.mmode.calibration_state is not None:
                roi = self.mmode.calibration_state.roi
                end_y = max(roi.y0, min(end_y, roi.y1))
            return (start[0], end_y)
        if effective_label in self._horizontal_time_caliper_labels:
            end_x = end[0]
            if self.mmode.calibration_state is not None:
                roi = self.mmode.calibration_state.roi
                end_x = max(roi.x0, min(end_x, roi.x1))
            return (end_x, start[1])
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
        mid_x = (start[0] + end[0]) / 2.0
        mid_y = (start[1] + end[1]) / 2.0
        # Never take B-mode geometry inside a spectral zone: that region carries
        # ms / cm·s⁻¹ axes, not millimetres per pixel.
        b_panel = panels.b_mode_panel_at(mid_x, mid_y) if panels is not None else None
        if b_panel is not None:
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
        self.append_frame_overlay(f"{chamber} area-length {view}: closed contour, then {length_label} caliper")
        return True

    def _ensure_linear_caliper_graphics(self) -> None:
        if self._linear_caliper_line_item is None:
            pen = self._caliper_pen(dark_theme.get_theme_tokens()["overlay.caliper"])
            self._linear_caliper_line_item = pg.PlotDataItem(pen=pen)
            self._linear_caliper_line_item.setZValue(25)
            self._linear_caliper_line_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self._linear_caliper_line_item.setAcceptHoverEvents(False)
            self._view.addItem(self._linear_caliper_line_item)
        if self._linear_caliper_marker_item is None:
            marker_pen = self._caliper_pen(dark_theme.get_theme_tokens()["overlay.caliper"])
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
        state = self._comparison_state
        label = live_caliper_label(state.kind, state.first_segment_done)
        self._update_caliper_label_graphics(
            start, end, color=dark_theme.get_theme_tokens()["overlay.caliper"], is_preview=True, label=label
        )

    def _update_caliper_label_graphics(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        *,
        color: str,
        is_preview: bool,
        label: str | None = None,
        measurement: LinearMeasurement | None = None,
    ) -> None:
        if measurement is None:
            measurement = self._linear_measurement_from_endpoints(start, end, label or self._current_caliper_label())
        text = inline_caliper_text(measurement, length_unit=self._length_display_unit)
        layout = compute_caliper_label_layout(
            start,
            end,
            vertical_labels=self._vertical_caliper_labels,
            label=measurement.label,
        )
        if is_preview:
            if self._active_caliper_label_item is None:
                self._active_caliper_label_item = pg.TextItem(color=color, anchor=(0.5, 0.5))
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
        *,
        spatial_only: bool | None = None,
    ) -> LinearMeasurement:
        if not (self._vessel_measurement_mode if spatial_only is None else spatial_only):
            doppler_measurement = self.doppler.caliper_measurement(start, end, label)
            if doppler_measurement is not None:
                return doppler_measurement
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        pixel_length = math.hypot(dx, dy)
        angle_degrees = math.degrees(math.atan2(dy, dx))
        millimeter_length: float | None = None
        time_ms: float | None = None
        if (
            label in self._vertical_caliper_labels
            and self.mmode.calibration_state is not None
            and self.mmode.calibration_state.vertical_mm_per_pixel is not None
        ):
            millimeter_length = abs(dy) * self.mmode.calibration_state.vertical_mm_per_pixel
        elif (
            label in self._horizontal_time_caliper_labels
            and self.mmode.calibration_state is not None
            and self.mmode.calibration_state.horizontal_ms_per_pixel is not None
        ):
            time_ms = abs(dx) * self.mmode.calibration_state.horizontal_ms_per_pixel
        else:
            pixel_spacing = self._pixel_spacing_for_linear_label(label, start, end)
            millimeter_length = (
                pixel_to_mm_length(pixel_length, angle_degrees, pixel_spacing) if pixel_spacing is not None else None
            )
        instance_uid = self.current_instance_uid() or ""
        return LinearMeasurement(
            label=label,
            pixel_length=pixel_length,
            millimeter_length=millimeter_length,
            frame_index=self._contour_frame_index(),
            start=start,
            end=end,
            sop_instance_uid=instance_uid,
            time_ms=time_ms,
            submillimeter=self._vessel_measurement_mode or self._tenth_mm_precision,
        )

    def _update_linear_caliper_label_preview(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> None:
        state = self._comparison_state
        label = live_caliper_label(state.kind, state.first_segment_done) or self._current_caliper_label()
        measurement = self._linear_measurement_from_endpoints(start, end, label)
        self._measurement_label.setText(measurement.display_text(length_unit=self._length_display_unit))

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
        committed_key = self._linear_measurement_key(measurement)
        was_free_caliper = (
            _is_generic_dist_label(measurement.label)
            and not self._caliper_sequence
            and self._caliper_sequence_size <= 1
        )
        self._stored_linear_measurements[committed_key] = measurement
        self._measurement_label.setText(measurement.display_text(length_unit=self._length_display_unit))
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
        elif self._caliper_sequence_size > 1:
            self._linear_caliper_active = False
            self._caliper_sequence_size = 0
            if not self._syncing_state:
                self.linear_caliper_sequence_completed.emit()
        elif self._caliper_repeat_mode:
            # Scanner-like behavior: the caliper stays armed, so the next two
            # clicks start a fresh measurement with the next Dist label.
            next_label = f"Dist{self._dist_serial}"
            self._dist_serial += 1
            self._set_caliper_label(next_label)
            self._linear_caliper_active = True
            self._linear_caliper_start = None
            self._update_linear_caliper_label_preview_from_state()
        else:
            self._linear_caliper_active = False
        self._sync_persistent_loupe()
        if was_free_caliper:
            self._open_label_picker_for_caliper(committed_key, measurement)

    # ── Label picker after free measurement (TP-4, spec §4.4) ──────

    def _ensure_label_picker(self):
        return self.label_picker_owner.picker()

    def label_picker(self):
        """Return (creating if needed) the viewer's :class:`LabelPicker` widget."""
        return self.label_picker_owner.picker()

    def is_label_picker_visible(self) -> bool:
        return self.label_picker_owner.visible

    def set_label_picker_enabled(self, enabled: bool) -> None:
        self.label_picker_owner.set_enabled(enabled)

    def is_label_picker_enabled(self) -> bool:
        return self.label_picker_owner.enabled

    def set_protocol_active(self, active: bool) -> None:
        self._protocol_active = bool(active)
        if self._protocol_active:
            self.dismiss_label_picker()

    def set_protocol_active_provider(self, provider: Callable[[], bool] | None) -> None:
        self._protocol_active_provider = provider

    def _init_controller_providers(self) -> None:
        """Narrow providers replacing the untyped `_controller_ref` poked onto the
        widget by MainWindow/PresenterView (issue 420 follow-up, slice 1): each
        callback is exactly the one piece of the application controller this
        widget needs, set explicitly instead of discovered through hasattr.
        """
        self._last_segment_roi_provider: Callable[[], tuple[float, float, float, float] | None] | None = None
        self._fusion_result_provider: Callable[[], Any] | None = None
        self._la_assist_request: Callable[..., None] | None = None
        self._la_assist_ready_signal: Any | None = None
        self._la_assist_connected = False

    def set_last_segment_roi_provider(
        self,
        provider: Callable[[], tuple[float, float, float, float] | None] | None,
    ) -> None:
        """Wire the ROI of the last automatic segmentation (issue 420 follow-up, slice 1)."""
        self._last_segment_roi_provider = provider

    def set_fusion_result_provider(self, provider: Callable[[], Any] | None) -> None:
        """Wire the application controller's temporal fusion result (issue 420 follow-up, slice 1)."""
        self._fusion_result_provider = provider

    def set_la_assist_provider(
        self,
        request: Callable[..., None] | None,
        ready_signal: Any | None = None,
    ) -> None:
        """Wire the LA AI-assist request/response ports (issue 420 follow-up, slice 1).

        ``request`` performs the actual call on the application controller;
        ``ready_signal`` is the bound Qt signal the controller emits with the
        assisted contour. The signal is connected lazily, on the first request,
        same timing as before this slice.
        """
        self._la_assist_request = request
        self._la_assist_ready_signal = ready_signal
        self._la_assist_connected = False

    def is_protocol_active(self) -> bool:
        if self._protocol_active:
            return True
        if self._protocol_active_provider is not None and bool(self._protocol_active_provider()):
            return True
        if self._caliper_sequence or self._caliper_sequence_size > 1:
            return True
        if self.doppler.workflow_active():
            return True
        return False

    def set_label_picker_context(self, context: str | None) -> None:
        self.label_picker_owner.set_context(context)

    def set_cardiac_context(self, cardiac: bool | None) -> None:
        """Tell the viewer whether the study is echocardiography.

        ``None`` restores the header-derived rule.  General ultrasound has no
        closed set of measurement names, so the naming window is a cardiology
        affordance (:mod:`domain.services.cardiac_study`).
        """
        self.label_picker_owner.set_cardiac_context(cardiac)

    def _header_cardiac_context(self) -> bool:
        instance = self._current_instance_metadata()
        if instance is None:
            return False
        from echo_personal_tool.domain.services.cardiac_study import is_cardiac_study

        return is_cardiac_study(
            body_part=getattr(instance, "body_part", ""),
            series_description=getattr(instance, "series_description", ""),
            study_description=getattr(instance, "study_description", ""),
        )

    def is_cardiac_context(self) -> bool:
        """Is this an echocardiographic clip?  Unknown means *no* (ТЗ п. 1)."""
        return self.label_picker_owner.is_cardiac_context()

    def _should_show_label_picker(self) -> bool:
        return (
            self.label_picker_owner.enabled
            and not self._vessel_measurement_mode
            and not self.is_protocol_active()
            and self.is_cardiac_context()
        )

    def _resolve_label_picker_context(self, *, doppler_measurement: bool = False) -> str:
        if doppler_measurement:
            default = "doppler"
        elif self.mmode.is_calibrated():
            default = "m"
        elif self.doppler.is_context() and not (
            self.doppler.calibration_state is not None and self.doppler.calibration_state.roi is not None
        ):
            default = "doppler"
        else:
            default = "2d"
        return self.label_picker_owner.resolve_context(default)

    def _map_image_point_to_viewer(self, point: tuple[float, float]) -> QPoint:
        try:
            scene_pt = self._view.mapViewToScene(QPointF(float(point[0]), float(point[1])))
            graphics_pt = self._graphics.mapFromScene(scene_pt)
            return self._graphics.mapTo(self, graphics_pt)
        except Exception:  # noqa: BLE001
            return QPoint(int(point[0]), int(point[1]))

    def _format_caliper_value_for_picker(self, measurement: LinearMeasurement) -> str:
        mid = measurement_for_caliper(measurement.label)
        if measurement.doppler:
            if measurement.velocity_cm_s is not None:
                vel_str, unit = format_velocity_measurement(
                    mid or "doppler.vmax", abs(measurement.velocity_cm_s), measurement.doppler_mode
                )
                return f"{vel_str} {unit}"
            if measurement.time_ms is not None:
                return f"{_fmt(mid or 'doppler.pht', measurement.time_ms, 'ms')} {tr('unit.ms')}"
            return ""
        if measurement.millimeter_length is not None:
            mm = float(measurement.millimeter_length)
            if self._length_display_unit == "cm":
                return f"{_fmt(mid or 'caliper.length', mm / 10.0, 'cm')} {tr('unit.cm')}"
            fallback_id = "caliper.length_submm" if measurement.submillimeter else "caliper.length"
            return f"{_fmt(mid or fallback_id, mm, 'mm')} {tr('unit.mm')}"
        return f"{_fmt(mid or 'caliper.length', measurement.pixel_length, 'px')} px"

    def _open_label_picker_for_contour(self, contour: Contour) -> None:
        """Offer to name a just-traced planimeter polygon (item 10).

        «Площадь1» and «Площадь2» of one frame are indistinguishable in the
        report, so the contour is named where it is created: the same picker as
        a free caliper, with the planimetry catalog, and Esc keeps the
        automatic name.  The picker is offered only for the generic area/volume
        polygons — the cardiac LV/LA/RV contours have their own anatomy.
        """
        if contour.chamber.upper() not in {GENERIC_AREA_CHAMBER, GENERIC_VOLUME_CHAMBER}:
            return
        if not self.label_picker_owner.enabled or self.is_protocol_active():
            return
        target = ("contour", _contour_picker_reference(contour))
        points = contour.closed_polygon_points()
        value_text = ""
        spacing = self._current_state.effective_pixel_spacing if self._current_state is not None else None
        if spacing is not None and points:
            if contour.chamber.upper() == GENERIC_VOLUME_CHAMBER:
                volume = closed_polygon_volume_ml(contour, spacing)
                if volume is not None:
                    value_text = f"{_fmt('planimeter.volume', volume, 'mL')} {tr('unit.ml')}"
            else:
                area = closed_polygon_area_cm2(contour, spacing)
                if area is not None:
                    value_text = f"{_fmt('planimeter.area', area, 'cm²')} {tr('unit.cm2')}"
        anchor_point = points[-1] if points else (self.width() / 2.0, self.height() / 2.0)
        from echo_personal_tool.presentation.label_picker import PICKER_CONTEXT_PLANIMETER

        self.label_picker_owner.offer(
            target=target,
            value_text=value_text,
            context=PICKER_CONTEXT_PLANIMETER,
            anchor=self._map_image_point_to_viewer(anchor_point),
            bounds=self._graphics_content_geometry(),
        )

    def _with_measurement_identity(self, contour: Contour) -> Contour:
        """Give a freshly drawn contour its stable id (item 10 of the 2026-11-06 list).

        A name has to be addressable: the picker that names the polygon right
        after it closes and the report card that renames it later both travel
        by ``measurement_id``, and a document without one could not tell two
        polygons of one frame apart.
        """
        if contour.measurement_id:
            return contour
        from echo_personal_tool.domain.services.doppler_repeats import new_measurement_id

        return replace(contour, measurement_id=new_measurement_id())

    def rename_contour_measurement(self, measurement_id: str, label: str) -> bool:
        """Rename a stored contour by its ``measurement_id`` (item 10).

        Used by the report sheet: the physician sees «Площадь1» twice in the
        protocol and names the row in place.  The contour is the single source
        of the name, so the overlay and the report follow the same edit.
        """
        return self._apply_contour_label(f"id:{measurement_id}", label)

    def _apply_contour_label(self, reference: object, label: str) -> bool:
        """Rename the traced polygon the picker was opened for (item 10)."""
        if not label:
            return False
        target = str(reference or "")
        for index, contour in enumerate(self._stored_contours):
            if _contour_picker_reference(contour) != target:
                continue
            if contour.measurement_label == label:
                return True
            renamed = replace(contour, measurement_label=label, revision=contour.revision + 1)
            self._stored_contours[index] = renamed
            self._render_contours_for_current_frame()
            self._refresh_frame_overlays()
            if not self._syncing_state:
                self.contours_changed.emit(self.contours())
            return True
        return False

    def _open_label_picker_for_caliper(
        self,
        key: tuple[str, int],
        measurement: LinearMeasurement,
    ) -> None:
        if not self._should_show_label_picker():
            return
        value_text = self._format_caliper_value_for_picker(measurement)
        context = self._resolve_label_picker_context(doppler_measurement=measurement.doppler)
        anchor = self._map_image_point_to_viewer(measurement.end)
        self.label_picker_owner.offer(
            target=("caliper", key),
            value_text=value_text,
            context=context,
            anchor=anchor,
            bounds=self._graphics_content_geometry(),
        )

    def _on_doppler_trace_committed(self, trace: object) -> None:
        raw_label = getattr(trace, "label", "") or ""
        if raw_label.strip().upper() != "VTI":
            return
        if not self._should_show_label_picker():
            return
        measurement_id = getattr(trace, "measurement_id", "") or ""
        metrics = self.doppler.last_committed_metrics()
        vti_cm = getattr(metrics, "vti_cm", None) if metrics is not None else None
        value_text = f"{_fmt('doppler.vti', vti_cm, 'cm')} {tr('unit.cm')}" if vti_cm is not None else ""
        points = getattr(trace, "points", ()) or ()
        if points:
            mapping = self.doppler.overlay.axis_mapping()
            end_xy = (
                mapping.x_from_time_ms(points[-1][0]),
                mapping.y_from_velocity_cm_s(points[-1][1]),
            )
            anchor = self._map_image_point_to_viewer(end_xy)
        else:
            anchor = QPoint(self.width() // 2, self.height() // 2)
        self.label_picker_owner.offer(
            target=("trace", measurement_id),
            value_text=value_text,
            context="doppler",
            anchor=anchor,
            bounds=self._graphics_content_geometry(),
        )

    def accept_label_picker(self) -> bool:
        return self.label_picker_owner.accept()

    def dismiss_label_picker(self) -> bool:
        return self.label_picker_owner.dismiss()

    def handle_label_picker_key(self, event: QKeyEvent) -> bool:
        return self.label_picker_owner.handle_key(event)

    def _apply_picked_label(self, option: object, target: tuple[str, Any] | None = None) -> None:
        if target is None:
            target = self.label_picker_owner.take_target()
        if target is None:
            return
        target_kind, target_ref = target
        target_label = str(getattr(option, "target_label", "") or "")
        option_kind = str(getattr(option, "kind", "") or "")
        if not target_label:
            return

        if target_kind == "contour":
            # Item 10: the name of a traced polygon lives in the contour, so it
            # reaches the overlay, the report, the JSON and the DICOM annotation
            # through the one path a contour already travels.
            self._apply_contour_label(target_ref, target_label)
            return

        if target_kind == "caliper" and isinstance(target_ref, tuple):
            measurement = self._stored_linear_measurements.get(target_ref)
            if measurement is None:
                return
            del self._stored_linear_measurements[target_ref]
            if option_kind == "caliper" and measurement.doppler:
                mm_length = measurement.millimeter_length
                if mm_length is None:
                    mm_length = self._calculate_mm_length(measurement.start, measurement.end, label=target_label)
                updated = replace(
                    measurement,
                    label=target_label,
                    millimeter_length=mm_length,
                    doppler=False,
                    time_ms=None,
                    velocity_cm_s=None,
                )
            else:
                updated = replace(measurement, label=target_label)
            new_key = self._linear_measurement_key(updated)
            self._stored_linear_measurements[new_key] = updated
            if self._selected_caliper_key == target_ref:
                self._selected_caliper_key = new_key

            if measurement.doppler and self.doppler.overlay.axis_mapping().has_roi_calibration:
                mapping = self.doppler.overlay.axis_mapping()
                if option_kind == "peak":
                    v_start = mapping.velocity_cm_s_from_y(measurement.start[1])
                    v_end = mapping.velocity_cm_s_from_y(measurement.end[1])
                    if abs(v_end) >= abs(v_start):
                        peak_t = mapping.time_ms_from_x(measurement.end[0])
                        peak_v = v_end
                    else:
                        peak_t = mapping.time_ms_from_x(measurement.start[0])
                        peak_v = v_start
                    self.doppler.overlay.record_labeled_peak(
                        target_label,
                        peak_t,
                        peak_v,
                        mode=measurement.doppler_mode or self.doppler.resolved_mode(),
                    )
                elif option_kind == "interval":
                    t0 = mapping.time_ms_from_x(measurement.start[0])
                    t1 = mapping.time_ms_from_x(measurement.end[0])
                    self.doppler.overlay.record_labeled_interval(target_label, t0, t1)

            self._measurement_label.setText(updated.display_text(length_unit=self._length_display_unit))
            self._emit_stored_linear_measurements()
            self._render_persistent_linear_calipers()
            self._refresh_frame_overlays()
            return

        if target_kind == "trace":
            from echo_personal_tool.domain.doppler_catalog import flow_site_from_peak_label

            trace_label = target_label
            if option_kind == "peak":
                site = flow_site_from_peak_label(target_label)
                if site is not None:
                    trace_label = f"{site} VTI"
            if self.doppler.overlay.relabel_last_trace(trace_label, measurement_id=str(target_ref or "")):
                metrics = self.doppler.last_committed_metrics()
                if metrics is not None:
                    self._measurement_label.setText(
                        self.doppler.trace_summary(metrics, self.doppler.overlay.last_committed_trace_label())
                    )

    def add_linear_measurements(self, measurements: Iterable[LinearMeasurement]) -> None:
        """Insert calipers measured outside the click-click flow (e.g. M-mode).

        The viewer is the authoritative list of a clip's calipers, so anything
        measured elsewhere has to enter through here: writing straight into the
        study session would make the next viewer report look like a deletion.
        """
        added = False
        for measurement in measurements:
            self._stored_linear_measurements[self._linear_measurement_key(measurement)] = measurement
            added = True
        if not added:
            return
        self._emit_stored_linear_measurements()
        self._render_persistent_linear_calipers()
        self._refresh_frame_overlays()

    def _emit_stored_linear_measurements(self) -> None:
        measurements = list(self._stored_linear_measurements.values())
        self.linear_measurements_changed.emit(measurements)

    # ── Caliper node drag (endpoint correction) ────────────────────

    def _caliper_node_edit_allowed(self) -> bool:
        """Endpoint nodes are draggable only while an armed caliper is idle.

        A pending placement click (first/second endpoint, diameter or
        stenosis comparison) must keep winning over node dragging,
        otherwise clicking an existing endpoint would start a new segment
        instead of moving the node.
        """
        if not self._linear_caliper_active:
            return True
        if self._linear_caliper_start is not None:
            return False
        state = self._comparison_state
        if state.kind in ("diameter", "stenosis_diameter") and state.segment2_end is None:
            return False
        return True

    def _begin_caliper_node_drag(
        self,
        caliper_key: tuple[str, int],
        endpoint_index: int,
        x: float,
        y: float,
    ) -> None:
        if not self._caliper_node_edit_allowed():
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
                line_item.setPen(self._caliper_pen(dark_theme.get_theme_tokens()["overlay.caliper"]))
                start_node.setPen(self._caliper_pen(dark_theme.get_theme_tokens()["overlay.caliper"]))
                end_node.setPen(self._caliper_pen(dark_theme.get_theme_tokens()["overlay.caliper"]))
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
                new_end,
                (x, y),
                label=measurement.label,
            )
        else:
            new_start = measurement.start
            new_end = self._constrain_linear_endpoint(
                measurement.start,
                (x, y),
                label=measurement.label,
            )
        updated = self._linear_measurement_from_endpoints(
            new_start,
            new_end,
            measurement.label,
            spatial_only=not measurement.doppler,
        )
        updated = replace(updated, submillimeter=measurement.submillimeter)
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
            new_start,
            new_end,
            color=dark_theme.get_theme_tokens()["overlay.caliper"],
            is_preview=True,
            measurement=updated,
        )
        self._measurement_label.setText(updated.display_text(length_unit=self._length_display_unit))
        self._recalculate_percent_d()
        self._recalculate_stenosis_diameter()
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

    def _update_results_overlay_for_caliper_drag(self, measurement: LinearMeasurement) -> None:
        if self._results_overlay_label is None:
            return
        # Deduplicate by label — keep the most recent measurement per label.
        deduped: dict[str, LinearMeasurement] = {}
        for m in self._stored_linear_measurements.values():
            deduped[m.label] = m
        lines: list[str] = []
        for m in deduped.values():
            lines.append(m.display_text(length_unit=self._length_display_unit))
        html = "<br>".join(lines)
        self._results_overlay_label.setText(html)
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
        deleted = self._stored_linear_measurements.pop(key, None)
        self._selected_caliper_key = None
        if deleted is not None:
            self._undo_redo.push(
                UndoEntry(
                    kind="linear_measurement",
                    payload={"key": key, "measurement": deleted},
                )
            )
        self._emit_stored_linear_measurements()
        self._render_persistent_linear_calipers()
        self._refresh_frame_overlays()
        return True

    @_prof
    def keyPressEvent(self, event) -> None:
        if self.is_label_picker_visible() and self.handle_label_picker_key(event):
            return
        if (
            event_matches_shortcut(event, "magnifier_hold", exact_modifiers=False, forbidden_modifiers=("Ctrl",))
            and not event.isAutoRepeat()
        ):
            magnifier = self.magnifier_controller
            if magnifier.enabled:
                # Ownership (#420): the controller raises the hold and asks the
                # viewer for the cursor position through its own provider.
                magnifier.set_held(True)
                event.accept()
                return
        if event_matches_shortcut(event, "cancel_tool", exact_modifiers=False):
            if self._caliper_drag_active:
                self._finish_caliper_node_drag(cancel=True)
                event.accept()
                return
        if (
            event_matches_shortcut(event, "vessel_psv", exact_modifiers=False, forbidden_modifiers=("Ctrl",))
            and self.is_vessel_available()
        ):
            self.start_vessel_psv()
            event.accept()
            return
        if event_matches_shortcut(event, "finish_tool", exact_modifiers=False):
            if self.doppler.overlay.vessel_cycle_selection_active() and self.doppler.overlay.assign_vessel_cycle_psv():
                self.accept_vessel_measurement()
                event.accept()
                return
            if self.doppler.overlay.vessel_status() == "done" and self.is_vessel_available():
                self.accept_vessel_measurement()
                event.accept()
                return
            if self._freehand_recording and self._contour_mode_active:
                if self._finish_active_freehand_contour():
                    event.accept()
                    return
        if event_matches_shortcut(event, "cancel_tool", exact_modifiers=False):
            if self.doppler.overlay.vessel_cycle_selection_active():
                self.doppler.overlay.cancel_vessel_cycle_selection()
                self._restore_vessel_average_label()
                event.accept()
                return
            if self.doppler.overlay.vessel_status() != "none":
                self.clear_vessel_measurement()
                event.accept()
                return
        if event_matches_shortcut(event, "delete_selection", exact_modifiers=False):
            if self.doppler.remove_measurement_at_cursor():
                event.accept()
                return
            if self._delete_selected_caliper():
                event.accept()
                return
        if event_matches_shortcut(event, "debug_overlay", exact_modifiers=False):
            self.toggle_debug_overlay()
            event.accept()
            return
        if event_matches_shortcut(event, "zoom_in", exact_modifiers=False, forbidden_modifiers=("Ctrl",)):
            self.zoom.step_mode(1)
            event.accept()
            return
        if event_matches_shortcut(event, "zoom_out", exact_modifiers=False, forbidden_modifiers=("Ctrl",)):
            self.zoom.step_mode(-1)
            event.accept()
            return
        if event_matches_shortcut(event, "zoom_fit", exact_modifiers=False, forbidden_modifiers=("Ctrl",)):
            self.zoom.set_mode("fit")
            event.accept()
            return
        if (
            self.doppler.overlay.vessel_cycle_selection_active()
            and event_matches_shortcut(
                event, "vessel_previous_cycle", exact_modifiers=False, forbidden_modifiers=("Ctrl",)
            )
            and self.doppler.overlay.move_vessel_cycle(-1)
        ):
            self._update_vessel_cycle_selection_label()
            event.accept()
            return
        if (
            self.doppler.overlay.vessel_cycle_selection_active()
            and event_matches_shortcut(event, "vessel_next_cycle", exact_modifiers=False, forbidden_modifiers=("Ctrl",))
            and self.doppler.overlay.move_vessel_cycle(1)
        ):
            self._update_vessel_cycle_selection_label()
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:
        if (
            event_matches_shortcut(event, "magnifier_hold", exact_modifiers=False, forbidden_modifiers=("Ctrl",))
            and not event.isAutoRepeat()
        ):
            # set_held(False) drops the hold and hides the lens unless the
            # persistent (linear caliper) mode is armed — all in the owner.
            self.magnifier_controller.set_held(False)
            event.accept()
            return
        super().keyReleaseEvent(event)

    def _set_caliper_label(self, label: str) -> None:
        self.label_picker_owner.set_label(label)

    def _on_timeline_changed(self, value: int) -> None:
        """Loop-strip entry point; the transport owns the emit and the guard."""
        self.transport.on_timeline_changed(value)

    def bind_display_controls(
        self,
        window_slider: object,
        level_slider: object,
        dr_slider: object,
    ) -> None:
        """Wire external sliders to the display projection owner."""
        self.display.bind_external(window_slider, level_slider, dr_slider)

    def disconnect_display_controls(self) -> None:
        """Block external slider signals to prevent dangling references."""
        self.display.disconnect_external()

    def set_magnetic_snap_enabled(self, enabled: bool) -> None:
        self._magnetic_snap_enabled = bool(enabled)

    def magnetic_snap_enabled(self) -> bool:
        return self._magnetic_snap_enabled

    def set_area_tool_mode(self, mode: str) -> None:
        if mode in ("click", "freehand"):
            self._area_tool_mode = mode

    def area_tool_mode(self) -> str:
        return self._area_tool_mode

    def set_lv_contour_input(self, mode: str) -> None:
        if mode in ("landmarks", "trace"):
            self._lv_contour_input = mode

    def lv_contour_input(self) -> str:
        return self._lv_contour_input

    def set_atrial_contour_input(self, mode: str) -> None:
        if mode in ("landmarks", "trace"):
            self._atrial_contour_input = mode

    def atrial_contour_input(self) -> str:
        return self._atrial_contour_input

    def set_despeckle_enabled(self, enabled: bool) -> None:
        self._despeckle_enabled = bool(enabled)
        # Re-render current frame with updated filter
        if self._current_frame is not None:
            self.display.update_levels()

    def despeckle_enabled(self) -> bool:
        return self._despeckle_enabled

    def _invalidate_edge_map_cache(self) -> None:
        self._edge_map_cache = None
        self._edge_map_cache_key = None

    def get_edge_map(self) -> EdgeMap | None:
        if self._current_frame is None:
            return None
        frame_id = id(self._current_frame)
        levels = self.display.effective_levels()
        cache_key = (frame_id, levels, self._is_color_frame)
        if self._edge_map_cache is not None and self._edge_map_cache_key == cache_key:
            return self._edge_map_cache
        self._edge_map_cache = build_edge_map(
            self._current_frame,
            display_levels=levels,
        )
        self._edge_map_cache_key = cache_key
        return self._edge_map_cache

    def _is_unassisted_freehand_trace(self) -> bool:
        """True while a freehand LV/atrial trace or freehand area stroke is being finished."""
        return bool(self._freehand_recording and (self._freehand_open_arc or self._area_tool_mode == "freehand"))

    def _apply_magnetic_snap_to_contour(
        self,
        contour_index: int,
        weights: np.ndarray,
        *,
        grab_index: int | None = None,
    ) -> None:
        if not self._magnetic_snap_enabled:
            return
        if 0 <= contour_index < len(self._contours) and self._contours[contour_index].unassisted:
            return
        edge_map = self.get_edge_map()
        if edge_map is None:
            return
        if contour_index < 0 or contour_index >= len(self._contours):
            return
        contour = self._contours[contour_index]
        if contour.is_open_arc:
            snap_cfg = magnetic_edge_snap_config_for_source(contour.source, chamber=contour.chamber)
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
        else:
            from echo_personal_tool.domain.services.contour_edge_snap import snap_closed_polygon

            snapped = snap_closed_polygon(list(contour.points), edge_map)
            contour.points[:] = snapped

    def _auto_snap_new_contour(self, contour: Contour) -> None:
        """Apply magnetic edge snap to a freshly placed contour."""
        if contour.unassisted or self._is_unassisted_freehand_trace():
            return
        if not self._magnetic_snap_enabled:
            return
        frame_index = self._contour_frame_index()
        instance_uid = self.current_instance_uid()
        for i, c in enumerate(self._contours):
            if c.unassisted:
                continue
            if (c is contour or (c.frame_index == frame_index and c.chamber == contour.chamber)) and (
                instance_uid is None or c.sop_instance_uid is None or c.sop_instance_uid == instance_uid
            ):
                self._apply_magnetic_snap_to_contour(
                    i,
                    np.ones(len(contour.points)),
                    grab_index=None,
                )
                self._refresh_rendered_contour_geometry(i)
                break

    def _current_caliper_label(self) -> str:
        return self.label_picker_owner.current_label()
