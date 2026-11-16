"""Frame/transport owner extracted from :class:`ViewerWidget`.

The transport is a *presentation projection* owner: it owns the timeline,
play/pause, endpoint/step buttons, the frame counter, the FPS control and the
wheel-scroll debounce.  It never stores a ``ViewerState`` and never reads the
document; callers pass primitives and the application layer remains the only
owner of the document state.

Public signals mirror the historical ``ViewerWidget`` signals one-for-one; the
viewer relays them, so external listeners and the characterization harness see
the same names, order and count.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget

from echo_personal_tool.application.localization import tr
from echo_personal_tool.presentation import dark_theme
from echo_personal_tool.presentation.cine_phase_strip import CinePhaseStrip
from echo_personal_tool.presentation.display_formats import format_fps
from echo_personal_tool.presentation.loop_controls import LoopControls


class _FpsLabel(QLabel):
    """«FPS: 30.0» of the transport: a double-click asks to retime the clip."""

    double_clicked = Signal()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit()
        super().mouseDoubleClickEvent(event)


class ViewerTransport(QObject):
    """One owner for the cine transport widgets and their projection."""

    play_pause_requested = Signal()
    frame_selected = Signal(int)
    scroll_frame_selected = Signal(int)
    fps_override_requested = Signal()

    def __init__(
        self,
        *,
        parent: QWidget,
        loop: LoopControls | None,
        phase_strip: CinePhaseStrip,
        phase_label: QLabel,
    ) -> None:
        super().__init__(parent)
        self._disposed = False
        self._playing = False
        self._loop = loop

        self.bar = QWidget(parent)
        self.bar.setObjectName("viewerTransport")
        self._viewer_widget = parent
        controls = QVBoxLayout(self.bar)
        timeline_row = QHBoxLayout()

        self.timeline_slider = QSlider(Qt.Orientation.Horizontal, self.bar)
        self.timeline_slider.setSingleStep(1)
        self.timeline_slider.valueChanged.connect(self.on_timeline_changed)
        # Right-click on the timeline is the discoverable entry point of the
        # A→B loop (2026-11-16 list, item 3): the markers are placed on the
        # clicked frame, not on the playhead.
        self.timeline_slider.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.timeline_slider.customContextMenuRequested.connect(self._show_loop_menu)

        self.first_frame_button = self._make_transport_button(
            "cine_first", "viewer.first_frame", "a11y.viewer_first_desc"
        )
        self.last_frame_button = self._make_transport_button("cine_last", "viewer.last_frame", "a11y.viewer_last_desc")
        self.step_back_button = self._make_transport_button(
            "cine_previous", "viewer.step_back", "a11y.viewer_prev_desc"
        )
        self.step_forward_button = self._make_transport_button(
            "cine_next", "viewer.step_forward", "a11y.viewer_next_desc"
        )
        self.first_frame_button.clicked.connect(lambda: self.timeline_slider.setValue(0))
        self.last_frame_button.clicked.connect(lambda: self.timeline_slider.setValue(self.timeline_slider.maximum()))

        self.play_button = QPushButton(self.bar)
        self.play_button.clicked.connect(self.play_pause_requested.emit)

        self.fps_label = _FpsLabel("FPS: —", self.bar)
        self.fps_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.fps_label.setToolTip(tr("viewer.fps_override_tooltip"))
        self.fps_label.double_clicked.connect(self.fps_override_requested.emit)

        self.source_label = QLabel(tr("viewer.frame_none"), self.bar)

        self.step_back_button.clicked.connect(self.step_back)
        self.step_forward_button.clicked.connect(self.step_forward)

        self._scroll_debounce_ms = 70
        self._pending_scroll_index: int | None = None
        self._scroll_debounce_timer = QTimer(self)
        self._scroll_debounce_timer.setSingleShot(True)
        self._scroll_debounce_timer.timeout.connect(self.emit_pending_scroll)

        transport_buttons = (
            self.first_frame_button,
            self.step_back_button,
            self.play_button,
            self.step_forward_button,
            self.last_frame_button,
        )
        for button in (*transport_buttons, *(loop.buttons() if loop is not None else ())):
            timeline_row.addWidget(button, alignment=Qt.AlignmentFlag.AlignVCenter)

        slider_column = QWidget(self.bar)
        slider_column_layout = QVBoxLayout(slider_column)
        slider_column_layout.setContentsMargins(0, 0, 0, 0)
        slider_column_layout.setSpacing(0)
        slider_column_layout.addWidget(phase_strip)
        if loop is not None:
            slider_column_layout.addWidget(loop.strip)
        slider_column_layout.addWidget(self.timeline_slider)
        # The timeline yields first when the row runs out of room.
        slider_column.setMinimumWidth(0)
        self._slider_column = slider_column
        timeline_row.addWidget(slider_column, stretch=1)
        timeline_row.addWidget(self.source_label)
        timeline_row.addWidget(phase_label)
        timeline_row.addWidget(self.fps_label)
        controls.addLayout(timeline_row)
        self._timeline_row = timeline_row

        self.fix_play_button_width()
        self.bar.installEventFilter(self)
        self._fit_loop_buttons()

    # ── A→B loop context menu (2026-11-16 list, item 3) ─────────────────

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt naming
        if obj is self.bar and event.type() == QEvent.Type.Resize:
            self._fit_loop_buttons()
        return super().eventFilter(obj, event)

    def _fit_loop_buttons(self) -> None:
        """Show the «A»/«B»/«↻» trio at full size, or drop it entirely.

        Three fixed 32 px buttons spent the last of the width budget that the
        window needs to fit a 1366 px screen at 150 % (911 logical px — pinned
        by ``test_classic_left_gallery_compacts_at_1366_physical_pixels``).
        Squeezed below 32 px the letters clip into dashes, so the rule is:
        full size when the row can afford the whole trio (the timeline column
        yields first), otherwise the buttons hide — the «ПКМ» menu of the
        timeline keeps every action reachable.
        """
        loop = self._loop
        if loop is None or not getattr(loop, "enabled", True):
            return
        row = getattr(self, "_timeline_row", None)
        if row is None:
            return
        preferred = 0
        for index in range(row.count()):
            widget = row.itemAt(index).widget()
            if widget is None or widget is getattr(self, "_slider_column", None):
                continue
            preferred += widget.sizeHint().width()
        preferred += max(0, row.count() - 1) * row.spacing()
        margins = row.contentsMargins()
        preferred += margins.left() + margins.right()
        show = self.bar.width() >= preferred
        for button in loop.buttons():
            button.setVisible(show)

    def _frame_at_slider_x(self, x: int) -> int:
        """Frame index under a right-click on the timeline slider."""
        slider = self.timeline_slider
        width = max(1, slider.width() - 2)
        fraction = min(1.0, max(0.0, (x - 1) / width))
        span = slider.maximum() - slider.minimum()
        return slider.minimum() + round(fraction * span)

    def _show_loop_menu(self, pos) -> None:
        """«ПКМ по ползунку»: place the A/B markers on the clicked frame.

        The buttons «A»/«B»/«↻» stay on the transport for the playhead, and
        this menu gives the same tools at an arbitrary frame of the timeline —
        the pair the physician needs to loop one cardiac cycle without ECG.
        """
        if self._loop is None or not getattr(self._loop, "enabled", True):
            return
        frame = self._frame_at_slider_x(int(pos.x()))
        menu = self.build_loop_menu(frame)
        menu.exec(self.timeline_slider.mapToGlobal(pos))

    def build_loop_menu(self, frame: int):
        """The «ПКМ» menu of the timeline; every action is wired to a slot."""
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self.timeline_slider)
        menu.setObjectName("loopContextMenu")
        act_a = menu.addAction(tr("viewer.loop_menu_set_a", frame=frame + 1))
        act_b = menu.addAction(tr("viewer.loop_menu_set_b", frame=frame + 1))
        menu.addSeparator()
        act_toggle = menu.addAction(tr("viewer.loop_menu_toggle"))
        act_toggle.setCheckable(True)
        act_toggle.setChecked(self._loop.repeat_button.isChecked())
        act_clear = menu.addAction(tr("viewer.loop_menu_clear"))
        act_clear.setEnabled(self._loop.strip.region() is not None)
        act_a.triggered.connect(lambda: self._menu_set_bound("a", frame))
        act_b.triggered.connect(lambda: self._menu_set_bound("b", frame))
        act_toggle.triggered.connect(self._loop.repeat_button.click)
        act_clear.triggered.connect(self._menu_clear_loop)
        return menu

    def _menu_set_bound(self, which: str, frame: int) -> None:
        viewer = getattr(self, "_viewer_widget", None)
        if viewer is not None and hasattr(viewer, "loop_bound_changed"):
            viewer.loop_bound_changed.emit(which, frame)
        elif self._loop is not None:
            button = self._loop.a_button if which == "a" else self._loop.b_button
            button.click()

    def _menu_clear_loop(self) -> None:
        viewer = getattr(self, "_viewer_widget", None)
        if viewer is not None and hasattr(viewer, "loop_clear_requested"):
            viewer.loop_clear_requested.emit()

    # ── construction helpers ─────────────────────────────────────────

    def _make_transport_button(self, icon: str, title_key: str, desc_key: str) -> QPushButton:
        from echo_personal_tool.presentation.icon_loader import load_svg_icon

        button = QPushButton(self.bar)
        button.setText("")
        button.setIcon(load_svg_icon(icon))
        button.setFixedSize(32, 32)
        button.setFlat(True)
        button.setAccessibleName(tr(title_key))
        button.setAccessibleDescription(tr(desc_key))
        button.setToolTip(tr(title_key))
        return button

    # ── projection ───────────────────────────────────────────────────

    def apply_state(
        self,
        *,
        frame_index: int,
        total_frames: int,
        fps: float,
        is_playing: bool,
        decode_in_progress: bool = False,
        counter_current: int | None = None,
    ) -> None:
        """Project transport values; the document state stays with the caller."""
        try:
            total = max(0, int(total_frames))
            maximum = max(0, total - 1)
            if self.timeline_slider.maximum() != maximum:
                self.timeline_slider.setRange(0, maximum)
            controls_enabled = total > 1
            self.timeline_slider.setEnabled(controls_enabled)
            for button in (
                self.first_frame_button,
                self.step_back_button,
                self.step_forward_button,
                self.last_frame_button,
                *(self._loop.buttons() if self._loop is not None else ()),
            ):
                button.setEnabled(controls_enabled)
            self.play_button.setEnabled(controls_enabled and not decode_in_progress)
            target = min(max(0, int(frame_index)), maximum)
            if self.timeline_slider.value() != target:
                self.timeline_slider.blockSignals(True)
                self.timeline_slider.setValue(target)
                self.timeline_slider.blockSignals(False)
            self.sync_play_button(is_playing)
            fps_text = f"FPS: {format_fps(fps)}" if fps > 0 else "FPS: —"
            if self.fps_label.text() != fps_text:
                self.fps_label.setText(fps_text)
            if counter_current is None:
                counter_current = target + 1
            self.set_frame_counter_label(current=counter_current, total=total)
        except RuntimeError:
            # Widget already destroyed during window teardown.
            return

    def apply_frame_time(
        self,
        *,
        frame_index: int,
        total_frames: int,
        frame_time_ms: float | None,
        is_playing: bool,
    ) -> None:
        """Project a transport-only pane frame without a ``ViewerState``."""
        fps = 1000.0 / frame_time_ms if frame_time_ms and frame_time_ms > 0 else 0.0
        self.apply_state(
            frame_index=frame_index,
            total_frames=total_frames,
            fps=fps,
            is_playing=is_playing,
        )

    def refresh_labels(self, *, current: int, total: int, is_playing: bool) -> None:
        """Refresh play/counter labels after a retranslation without touching range."""
        self.sync_play_button(is_playing)
        self.set_frame_counter_label(current=current, total=total)
        self.fix_play_button_width()

    def retranslate(self) -> None:
        for button, key, desc_key in (
            (self.step_back_button, "viewer.step_back", "a11y.viewer_prev_desc"),
            (self.step_forward_button, "viewer.step_forward", "a11y.viewer_next_desc"),
            (self.first_frame_button, "viewer.first_frame", "a11y.viewer_first_desc"),
            (self.last_frame_button, "viewer.last_frame", "a11y.viewer_last_desc"),
        ):
            button.setToolTip(tr(key))
            button.setAccessibleName(tr(key))
            button.setAccessibleDescription(tr(desc_key))
        self.timeline_slider.setToolTip(tr("viewer.timeline"))

    def fix_play_button_width(self) -> None:
        self.play_button.setFixedSize(36, 36)
        self.sync_play_button(self._playing)

    def sync_play_button(self, playing: bool) -> None:
        from echo_personal_tool.presentation.icon_loader import load_svg_icon

        self._playing = bool(playing)
        caption = tr("viewer.pause") if playing else tr("viewer.play")
        self.play_button.setText("")
        self.play_button.setAccessibleName(caption)
        self.play_button.setAccessibleDescription(tr("a11y.viewer_play_desc"))
        self.play_button.setToolTip(caption)
        if self.play_button.property("cinePlaying") != playing or self.play_button.icon().isNull():
            self.play_button.setProperty("cinePlaying", playing)
            tokens = dark_theme.get_theme_tokens()
            self.play_button.setIcon(load_svg_icon("cine_pause" if playing else "cine_play", color=tokens["accent.on"]))
            self.play_button.setStyleSheet(
                f"QPushButton {{ border: none; border-radius: 18px; background: {tokens['accent']}; }}"
                f"QPushButton:hover {{ background: {tokens['accent.text']}; }}"
                f"QPushButton:disabled {{ background: {tokens['surface.3']}; }}"
            )

    def set_frame_counter_label(self, *, current: int, total: int) -> None:
        """Update the counter while reserving enough width for its largest value."""
        if total > 0:
            total = int(total)
            current = min(max(1, int(current)), total)
            source_text = tr("viewer.frame_counter", current=str(current), total=str(total))
            width_text = tr("viewer.frame_counter", current=str(total), total=str(total))
        else:
            source_text = tr("viewer.frame_none")
            width_text = source_text

        margins = self.source_label.contentsMargins()
        width = (
            self.source_label.fontMetrics().horizontalAdvance(width_text)
            + margins.left()
            + margins.right()
            + 2 * self.source_label.margin()
            + 2
        )
        if self.source_label.minimumWidth() != width or self.source_label.maximumWidth() != width:
            self.source_label.setFixedWidth(width)
        if self.source_label.text() != source_text:
            self.source_label.setText(source_text)

    def hide_playback_controls(self) -> None:
        """Speaker-facing viewers hide the playback row (presentation mode)."""
        for widget in (
            self.timeline_slider,
            self.play_button,
            self.step_back_button,
            self.step_forward_button,
            self.fps_label,
            self.source_label,
        ):
            widget.hide()

    # ── navigation ───────────────────────────────────────────────────

    def step_back(self) -> None:
        current = self.timeline_slider.value()
        if current > 0:
            self.timeline_slider.setValue(current - 1)

    def step_forward(self) -> None:
        current = self.timeline_slider.value()
        if current < self.timeline_slider.maximum():
            self.timeline_slider.setValue(current + 1)

    def select_frame(self, frame: int) -> None:
        if self.timeline_slider.minimum() <= frame <= self.timeline_slider.maximum():
            self.timeline_slider.setValue(frame)

    def on_timeline_changed(self, value: int) -> None:
        self.frame_selected.emit(value)

    # ── wheel-scroll debounce ────────────────────────────────────────

    @property
    def scroll_debounce_ms(self) -> int:
        return self._scroll_debounce_ms

    @scroll_debounce_ms.setter
    def scroll_debounce_ms(self, value: int) -> None:
        self._scroll_debounce_ms = max(0, int(value))

    @property
    def pending_scroll_index(self) -> int | None:
        return self._pending_scroll_index

    @pending_scroll_index.setter
    def pending_scroll_index(self, value: int | None) -> None:
        self._pending_scroll_index = value

    def set_scroll_debounce_ms(self, ms: int) -> None:
        self.scroll_debounce_ms = ms

    @property
    def debounce_active(self) -> bool:
        """Whether the wheel debounce timer is currently armed."""
        return self._scroll_debounce_timer.isActive()

    def queue_scroll(self, index: int) -> None:
        """Remember the next wheel frame and emit it after the debounce."""
        self._pending_scroll_index = int(index)
        if self._scroll_debounce_ms <= 0:
            self.emit_pending_scroll()
            return
        self._scroll_debounce_timer.start(self._scroll_debounce_ms)

    def emit_pending_scroll(self) -> None:
        if self._pending_scroll_index is None:
            return
        index = self._pending_scroll_index
        self._pending_scroll_index = None
        self.scroll_frame_selected.emit(index)

    def update_timeline_indicator(self, viewer_state: object | None = None) -> None:  # noqa: ARG002
        self.timeline_slider.setToolTip("")
        self.timeline_slider.setStyleSheet("")

    # ── lifecycle ────────────────────────────────────────────────────

    def dispose(self) -> None:
        """Idempotent teardown: stop the timer and drop the pending frame."""
        if self._disposed:
            return
        self._disposed = True
        self._pending_scroll_index = None
        try:
            self._scroll_debounce_timer.stop()
            self._scroll_debounce_timer.timeout.disconnect()
        except (RuntimeError, TypeError):
            pass
