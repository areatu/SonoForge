"""M-mode state of the 2D viewer — the first ownership slice of ``ViewerWidget`` (issue 479).

The controller owns everything the M-mode tools remember between two mouse
events:

* the panel calibration (ROI, depth and time scale) and its draft — the ROI
  step with its first corner, the pending ROI and the pending depth scale, the
  start of the time span;
* the anatomical scan line — whether placement is armed, the graphics item,
  which endpoint the next click sets and the vertical lock;
* the vertical caliper labels one M-mode frame sequence added for the session.

What only the widget can do is reached through :class:`MModeViewerPort` — a
frozen bag of late-bound callables (the current frame and panel layout, the
generic calibration caliper, the measurement label, the cursor, the number
dialog and the linear caliper). The controller never imports ``ViewerWidget``,
so a test builds the port from plain functions and drives the whole M-mode
flow without a widget.

The widget keeps one reference (``ViewerWidget.mmode``), re-emits the three
signals below under its historical names (``mmode_calibration_changed``,
``mmode_time_calibration_completed``, ``mmode_line_completed``) and reads the
state through the public properties when its generic tools need it — the
crosshair bounds, the TAPSE click guard, the vertical caliper scale.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from PySide6.QtCore import QObject, Qt, Signal

from echo_personal_tool.application.localization import tr
from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi
from echo_personal_tool.domain.models.frame_panels import MmodeCalibrationState
from echo_personal_tool.domain.services.doppler_calibration import roi_from_corners
from echo_personal_tool.domain.services.mmode_calibration import (
    horizontal_ms_from_frame_time,
    mmode_state_from_panel,
)
from echo_personal_tool.presentation.mmode_scan_line import MModeScanLineItem

if TYPE_CHECKING:
    import numpy as np

    from echo_personal_tool.domain.models.frame_panels import FramePanelLayout

MModeCalibrationKind = Literal["mmode_time", "mmode_depth"]

# The caliper label the M-mode vertical tool measures with.
MMODE_CALIPER_LABEL = "M-mode"


@dataclass(frozen=True)
class MModeViewerPort:
    """What the M-mode controller needs from the viewer, as late-bound callables."""

    # Frame and layout
    frame: Callable[[], np.ndarray | None]
    frame_time_ms: Callable[[], float | None]
    resolve_panels: Callable[[], FramePanelLayout | None]
    syncing: Callable[[], bool]
    view: Callable[[], Any]
    map_event: Callable[[Any], tuple[float, float] | None]
    # Generic tools of the widget
    cancel_tool: Callable[[], None]
    clear_calibration_caliper: Callable[[], None]
    arm_calibration: Callable[[MModeCalibrationKind, float | None], None]
    set_calibration_kind: Callable[[MModeCalibrationKind], None]
    # Feedback
    show_message: Callable[[str], None]
    unset_cursor: Callable[[], None]
    apply_viewport_cursor: Callable[[], None]
    ask_double: Callable[[str, str, float, float, float, int], tuple[float, bool]]
    # Linear caliper
    start_linear_caliper_for: Callable[[str], bool]
    start_linear_caliper_sequence: Callable[[tuple[str, ...]], bool]
    add_vertical_labels: Callable[[set[str]], None]
    remove_vertical_labels: Callable[[set[str]], None]


class MModeController(QObject):
    """M-mode calibration, scan line and frame caliper state of one viewer."""

    calibration_changed = Signal(object)  # MmodeCalibrationState
    time_calibration_completed = Signal(object)  # float, ms per pixel
    line_completed = Signal(object, object)  # (start, end) in image pixels

    def __init__(self, port: MModeViewerPort, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._port = port
        # Panel calibration and its draft
        self._calibration_state: MmodeCalibrationState | None = None
        self._cal_step: Literal["roi"] | None = None
        self._roi_corner1: tuple[float, float] | None = None
        self._pending_roi: DopplerSpectrogramRoi | None = None
        self._pending_depth_mm_per_pixel: float | None = None
        self._time_start_x: float | None = None
        # Anatomical scan line
        self._line_active = False
        self._line_item: MModeScanLineItem | None = None
        self._line_click_step: Literal["start", "end"] | None = None
        self._vertical_lock = False
        # Vertical labels the last M-mode frame sequence added
        self._session_vertical_labels: set[str] = set()

    # -- read-only state -----------------------------------------------------

    @property
    def calibration_state(self) -> MmodeCalibrationState | None:
        return self._calibration_state

    @property
    def cal_step(self) -> Literal["roi"] | None:
        """``"roi"`` while the user draws the M-mode panel rectangle."""
        return self._cal_step

    @property
    def roi_corner1(self) -> tuple[float, float] | None:
        return self._roi_corner1

    @property
    def pending_roi(self) -> DopplerSpectrogramRoi | None:
        return self._pending_roi

    @property
    def pending_depth_mm_per_pixel(self) -> float | None:
        return self._pending_depth_mm_per_pixel

    @property
    def time_start_x(self) -> float | None:
        """First click of the time span, ``None`` before it."""
        return self._time_start_x

    @property
    def line_active(self) -> bool:
        """True while the M-mode scan line is being placed."""
        return self._line_active

    @property
    def line_item(self) -> MModeScanLineItem | None:
        return self._line_item

    @property
    def line_click_step(self) -> Literal["start", "end"] | None:
        return self._line_click_step

    @property
    def vertical_lock(self) -> bool:
        return self._vertical_lock

    @property
    def session_vertical_labels(self) -> frozenset[str]:
        return frozenset(self._session_vertical_labels)

    @property
    def current_frame(self) -> np.ndarray | None:
        """The viewer's frame — the scan line item sizes its guides with it."""
        return self._port.frame()

    def is_calibrated(self) -> bool:
        return self._calibration_state is not None and self._calibration_state.is_complete()

    # -- calibration state ---------------------------------------------------

    def apply_calibration_state(self, state: MmodeCalibrationState) -> None:
        frame = self._port.frame()
        if frame is not None:
            height, width = frame.shape[:2]
            roi = state.roi.normalized(float(width), float(height))
            state = MmodeCalibrationState(
                roi=roi,
                vertical_mm_per_pixel=state.vertical_mm_per_pixel,
                horizontal_ms_per_pixel=state.horizontal_ms_per_pixel,
                from_dicom_tags=state.from_dicom_tags,
                depth_from_dicom_tags=state.depth_from_dicom_tags,
                time_from_dicom_tags=state.time_from_dicom_tags,
            )
        self._calibration_state = state
        if not self._port.syncing():
            self.calibration_changed.emit(state)

    def restore_state(self, calibration: MmodeCalibrationState | None) -> None:
        if calibration is not None:
            self.apply_calibration_state(calibration)
        elif self._port.frame() is not None:
            self.try_apply_from_dicom_or_heuristic()

    def try_apply_from_dicom_or_heuristic(self) -> bool:
        panels = self._port.resolve_panels()
        if panels is None:
            return False
        m_panel = panels.m_mode
        if m_panel is None:
            return False
        state = mmode_state_from_panel(m_panel)
        if state is None:
            return False

        # B-mode depth fallback
        vertical_mm = state.vertical_mm_per_pixel
        if vertical_mm is None and panels.b_mode is not None:
            b_depth = panels.b_mode.vertical_mm_per_pixel
            if b_depth is not None and b_depth > 0.0:
                vertical_mm = b_depth

        # FrameTime fallback
        horizontal_ms = state.horizontal_ms_per_pixel
        if horizontal_ms is None:
            horizontal_ms = horizontal_ms_from_frame_time(self._port.frame_time_ms(), state.roi.width)

        # Tick detection fallback
        frame = self._port.frame()
        if vertical_mm is None and frame is not None:
            from echo_personal_tool.domain.services.auto_depth_calibration import (
                try_auto_depth_calibration_in_roi,
            )

            tick_result = try_auto_depth_calibration_in_roi(frame, state.roi)
            if tick_result is not None and tick_result.spacing[0] > 0.0:
                vertical_mm = tick_result.spacing[0]

        if vertical_mm != state.vertical_mm_per_pixel or horizontal_ms != state.horizontal_ms_per_pixel:
            state = MmodeCalibrationState(
                roi=state.roi,
                vertical_mm_per_pixel=vertical_mm,
                horizontal_ms_per_pixel=horizontal_ms,
                from_dicom_tags=state.from_dicom_tags,
                depth_from_dicom_tags=state.depth_from_dicom_tags,
                time_from_dicom_tags=state.time_from_dicom_tags,
            )

        self.apply_calibration_state(state)
        if not state.is_complete():
            if state.vertical_mm_per_pixel is None:
                self._start_depth_only()
            elif state.horizontal_ms_per_pixel is None:
                self._start_time_only()
        return True

    # -- calibration flow: ROI -> depth -> time ------------------------------

    def start_panel_calibration(self) -> bool:
        if self._port.frame() is None:
            return False
        self._port.cancel_tool()
        self._port.clear_calibration_caliper()
        self._cal_step = "roi"
        self._roi_corner1 = None
        self._pending_roi = None
        self._pending_depth_mm_per_pixel = None
        self._port.show_message(tr("viewer.mmode_cal1"))
        return True

    def cancel_roi_step(self) -> bool:
        """Esc during the ROI step drops the whole draft; True when it was armed."""
        if self._cal_step is None:
            return False
        self._cal_step = None
        self._roi_corner1 = None
        self._pending_roi = None
        self._pending_depth_mm_per_pixel = None
        return True

    def handle_calibration_click(self, ev: Any) -> bool:
        frame = self._port.frame()
        if self._cal_step != "roi" or frame is None:
            return False
        if ev.button() != Qt.MouseButton.LeftButton:
            return False
        click = self._port.map_event(ev)
        if click is None:
            return False
        x, y = click
        if self._roi_corner1 is None:
            self._roi_corner1 = (x, y)
            self._port.show_message(tr("viewer.mmode_cal2"))
            return True
        height, width = frame.shape[:2]
        roi = roi_from_corners(self._roi_corner1, (x, y)).normalized(float(width), float(height))
        self._cal_step = None
        self._roi_corner1 = None
        self.start_depth_step(roi)
        return True

    def start_depth_step(self, roi: DopplerSpectrogramRoi) -> None:
        """Arm the vertical depth caliper inside ``roi`` (the ROI is kept as pending)."""
        self._pending_roi = roi
        self._pending_depth_mm_per_pixel = None
        self._port.arm_calibration("mmode_depth", roi.x0 + roi.width / 2.0)
        self._port.show_message(tr("viewer.mmode_cal_depth"))

    def mark_time_start(self, x: float) -> None:
        """First click of the time span (the widget draws the preview)."""
        self._time_start_x = x

    def on_calibration_caliper_cleared(self) -> None:
        """The widget dropped its generic calibration caliper."""
        self._time_start_x = None
        self._pending_depth_mm_per_pixel = None

    def prompt_depth_calibration(self, length_px: float) -> None:
        known_cm, accepted = self._port.ask_double(
            tr("viewer.mmode_calibration_title"),
            tr("viewer.mmode_depth_prompt"),
            1.0,
            0.01,
            100.0,
            2,
        )
        # Keep the ROI: clearing the caliper resets the pending depth only.
        pending_roi = self._pending_roi
        self._port.clear_calibration_caliper()
        if not accepted or pending_roi is None or length_px <= 0.0:
            self._pending_roi = None
            return
        self._pending_depth_mm_per_pixel = known_cm * 10.0 / length_px
        self._pending_roi = pending_roi
        # Chain to the time step instead of applying immediately.
        self._port.set_calibration_kind("mmode_time")
        self._time_start_x = None
        self._port.show_message(tr("viewer.mmode_cal_time"))

    def prompt_time_span(self, length_px: float) -> None:
        pending_roi = self._pending_roi
        pending_depth = self._pending_depth_mm_per_pixel

        current = self._calibration_state
        auto_time = current.horizontal_ms_per_pixel if current is not None and current.time_from_dicom_tags else None
        time_per_pixel_ms: float | None
        if auto_time is not None and auto_time > 0.0:
            time_per_pixel_ms = float(auto_time)
            accepted = True
        else:
            span_ms, accepted = self._port.ask_double(
                "M-mode time scale",
                tr("viewer.mmode_cal_time_prompt"),
                1000.0,
                1.0,
                10000.0,
                0,
            )
            time_per_pixel_ms = span_ms / length_px if accepted and length_px > 0.0 else None

        self._port.clear_calibration_caliper()
        if not accepted or time_per_pixel_ms is None or length_px <= 0.0:
            self._pending_roi = None
            self._pending_depth_mm_per_pixel = None
            return

        if pending_roi is not None and pending_depth is not None:
            previous = self._calibration_state
            state = MmodeCalibrationState(
                roi=pending_roi,
                vertical_mm_per_pixel=pending_depth,
                horizontal_ms_per_pixel=time_per_pixel_ms,
                from_dicom_tags=previous.from_dicom_tags if previous is not None else False,
                depth_from_dicom_tags=previous.depth_from_dicom_tags if previous is not None else False,
                time_from_dicom_tags=previous.time_from_dicom_tags if previous is not None else False,
            )
            self._pending_roi = None
            self._pending_depth_mm_per_pixel = None
            self.apply_calibration_state(state)
        elif not self._port.syncing():
            self.time_calibration_completed.emit(float(time_per_pixel_ms))

    def _start_depth_only(self) -> None:
        """Depth step on the existing (DICOM) ROI, without redrawing it."""
        if self._calibration_state is None:
            return
        self._port.cancel_tool()
        self._port.clear_calibration_caliper()
        self.start_depth_step(self._calibration_state.roi)

    def _start_time_only(self) -> None:
        """Time step on the existing (DICOM) ROI, without redrawing it."""
        if self._calibration_state is None:
            return
        self._port.cancel_tool()
        self._port.clear_calibration_caliper()
        self._port.arm_calibration("mmode_time", None)
        self._time_start_x = None
        self._port.show_message(tr("viewer.mmode_cal_time"))

    # -- vertical calipers on the M-mode strip -------------------------------

    def start_vertical_caliper(self) -> bool:
        """Vertical caliper on the M-mode strip (uses the M-mode depth scale)."""
        if not self.is_calibrated():
            return False
        return self._port.start_linear_caliper_for(MMODE_CALIPER_LABEL)

    def start_frame_caliper_sequence(self, labels: tuple[str, ...]) -> bool:
        """Caliper sequence on the current M-mode frame (vertical, M-mode depth scale)."""
        if not labels or not self.is_calibrated():
            return False
        if not self._port.start_linear_caliper_sequence(labels):
            return False
        self._port.add_vertical_labels(set(labels))
        self._session_vertical_labels.update(labels)
        return True

    def reset_session_vertical_labels(self) -> None:
        if self._session_vertical_labels:
            self._port.remove_vertical_labels(set(self._session_vertical_labels))
            self._session_vertical_labels.clear()

    # -- anatomical scan line ------------------------------------------------

    def start_line(self) -> None:
        self._line_active = True
        self._line_click_step = "start"
        if self._line_item is not None:
            self._line_item.remove_from_view(self._port.view())
        self._line_item = MModeScanLineItem(host=self)
        if self._vertical_lock:
            self._line_item.vertical_lock = True
        # The crosshair belongs to the 2D cine only: a cursor on the whole
        # widget would leak onto the transport buttons and the slider.
        self._port.unset_cursor()
        self._port.apply_viewport_cursor()

    def cancel_line(self) -> None:
        if self._line_item is not None:
            self._line_item.remove_from_view(self._port.view())
        self._line_active = False
        self._line_click_step = None
        self._line_item = None
        self._port.unset_cursor()
        self._port.apply_viewport_cursor()

    def set_vertical_lock(self, enabled: bool) -> None:
        """Enable/disable vertical-only movement for the scan line."""
        self._vertical_lock = enabled
        if self._line_item is not None:
            self._line_item.vertical_lock = enabled

    def handle_line_click_from_event(self, ev: Any) -> bool:
        if not self._line_active:
            return False
        if ev.button() != Qt.MouseButton.LeftButton:
            return False
        click = self._port.map_event(ev)
        if click is None:
            return False
        return self.handle_line_click(float(click[0]), float(click[1]))

    def handle_line_click(self, x: float, y: float) -> bool:
        if not self._line_active or self._line_item is None:
            return False
        # View coordinates have Y up (invertY); image rows grow downwards.
        h = self._frame_height()
        img_x, img_y = x, h - y
        view = self._port.view()
        if self._line_click_step == "start":
            if self._line_item.is_complete:
                self._line_item.remove_from_view(view)
            self._line_item.set_start((img_x, img_y))
            self._line_click_step = "end"
            self._update_line_preview(x, y)
            return True
        if self._line_click_step == "end":
            self._line_item.set_end((img_x, img_y))
            self._line_item.update_graphics_for_view(view, h)
            self.line_completed.emit(*self._line_item.get_endpoints())
            self._line_click_step = "start"
            self._port.apply_viewport_cursor()
            return True
        return False

    def handle_line_hover(self, x: float, y: float) -> bool:
        """Update the scan line preview while the second endpoint is pending."""
        if not self._line_active or self._line_click_step != "end":
            return False
        self._update_line_preview(x, y)
        return True

    def begin_node_drag(self, endpoint_index: int) -> None:
        """Endpoint drag started — nothing to remember until it moves."""

    def node_dragging(self, endpoint_index: int, pos: tuple[float, float]) -> None:
        if self._line_item is None:
            return
        h = self._frame_height()
        img_pos = (pos[0], h - pos[1])
        if self._vertical_lock:
            original = self._line_item.line_start if endpoint_index == 0 else self._line_item.line_end
            if original is not None:
                img_pos = (original[0], img_pos[1])
        if endpoint_index == 0:
            self._line_item.move_start_to(img_pos)
        else:
            self._line_item.move_end_to(img_pos)
        self._line_item.update_graphics_for_view(self._port.view(), h)
        if self._vertical_lock and self._line_item.has_guides:
            self._line_item.update_guides(img_pos, h)
        # line_completed is emitted on drag end only: it triggers an expensive
        # recalculation from every frame.

    def end_node_drag(self, endpoint_index: int) -> None:
        if self._line_item is not None:
            self.line_completed.emit(*self._line_item.get_endpoints())

    def _update_line_preview(self, mouse_x: float, mouse_y: float) -> None:
        if self._line_item is None or self._line_item.line_start is None:
            return
        h = self._frame_height()
        start_view = (self._line_item.line_start[0], h - self._line_item.line_start[1])
        self._line_item.update_preview_view(start_view, (mouse_x, mouse_y), self._port.view(), h)

    def _frame_height(self) -> float:
        frame = self._port.frame()
        return float(frame.shape[0]) if frame is not None else 1.0
