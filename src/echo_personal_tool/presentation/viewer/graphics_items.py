"""Graphics items and relays of the study viewer (extracted from viewer_widget).

The pyqtgraph view box and its node items, the results-overlay label, the
compare-state cache and the loupe key relay used to live at the top of
``viewer_widget.py`` (audit 2026-11-27 seam 1 preparation).  They are
self-contained: only ``viewer_widget`` consumes them, nothing else imports
these names (private ones included).  No behaviour changed in the move.
"""

from __future__ import annotations

import weakref
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pyqtgraph as pg
from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QLabel, QWidget
from shiboken6 import isValid

from echo_personal_tool.application.diagnostics import profiled as _prof
from echo_personal_tool.application.localization import tr
from echo_personal_tool.application.preferences_contract import DEFAULT_RESULTS_OVERLAY_Y_RATIO
from echo_personal_tool.domain.models import Contour
from echo_personal_tool.presentation import dark_theme

if TYPE_CHECKING:
    from echo_personal_tool.presentation.viewer_widget import ViewerWidget


class ContourViewBox(pg.ViewBox):
    """ViewBox: clicks for tools; wheel steps frames; no pan/zoom drag."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
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

    def mouseClickEvent(self, ev: Any) -> None:
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
    def mousePressEvent(self, ev: Any) -> None:
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
        # The armed second half of a paired tool starts here and places its first
        # point. A click on an existing node keeps dragging instead. The frame,
        # not the anatomy, is the gate: anywhere on the ED frame edits the ED
        # contour rather than starting ES (which used to eat the pair).
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
    def mouseMoveEvent(self, ev: Any) -> None:
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

    def mouseDragEvent(self, ev: Any) -> None:
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

    def mouseReleaseEvent(self, ev: Any) -> None:
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

    def leaveEvent(self, ev: Any) -> None:
        if self._viewer_widget is not None:
            self._viewer_widget._clear_contour_hover()
            if self._viewer_widget._caliper_drag_active:
                self._viewer_widget._finish_caliper_node_drag(cancel=True)
        super().leaveEvent(ev)

    @_prof
    def wheelEvent(self, ev: Any, axis: Any = None) -> None:
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
    def mousePressEvent(self, ev: Any) -> None:
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

    def mouseDragEvent(self, ev: Any) -> None:
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

    def hoverEvent(self, ev: Any) -> None:
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
    def mousePressEvent(self, ev: Any) -> None:
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

    def mouseDragEvent(self, ev: Any) -> None:
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        ev.accept()
        view_box = self.getViewBox() or self._viewer_widget._view
        point = view_box.mapSceneToView(ev.scenePos())
        self._viewer_widget._apply_caliper_node_drag(float(point.x()), float(point.y()))

    def mouseReleaseEvent(self, ev: Any) -> None:
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

    def _link_at(self, pos: Any) -> str | None:
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
    def on_link_activated(self) -> Any:
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

    def contextMenuEvent(self, event: Any) -> None:
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

    def __init__(self, viewer: ViewerWidget) -> None:
        super().__init__()
        self._viewer: weakref.ReferenceType[ViewerWidget] | None = weakref.ref(viewer)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
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
