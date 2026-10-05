"""Controller of the two-clip Multiview session.

Owns the session state, the single monotonic playback clock and the per-pane
frame routing.  Both panes are driven from one clock (never from two unrelated
``QTimer``s) and every late loader answer is checked against the pane's request
generation, so a clip that has already been replaced is never repainted
(spec §6.2, §11).

The *left* pane is the application's main viewer: in ``Независимо`` mode it
stays under ``AppController`` (measurements, Doppler, M-mode keep working), and
Multiview only takes it over while a synchronised mode runs.
"""

from __future__ import annotations

import logging
import time
from dataclasses import replace

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal

from echo_personal_tool.domain.models.metadata import InstanceMetadata
from echo_personal_tool.domain.models.multiview import (
    DEFAULT_EVENT_LABEL,
    ENDPOINT_HOLD_MS,
    MAX_EVENT_LABEL,
    EventMarker,
    MultiViewSession,
    PaneId,
    PlaybackMode,
)
from echo_personal_tool.domain.services.multiview_sync import (
    CommonWindow,
    CycleSchedule,
    build_cycle_schedule,
    clamp_frame,
    clamp_rate,
    common_window_frames,
    cycles_from_markers,
    frame_at_phase,
    frame_start_seconds,
    phase_of_frame,
    plan_common_window,
    validate_new_marker,
)

logger = logging.getLogger(__name__)

#: Clock resolution of the shared playhead (ms).
_CLOCK_INTERVAL_MS = 16


class MultiViewController(QObject):
    """Session state, shared clock and frame routing for Multiview."""

    status_message = Signal(str)
    warning_requested = Signal(str, str)
    replace_requested = Signal(PaneId)
    session_changed = Signal()
    left_pane_released = Signal(int)  # frame index handed back to the controller

    def __init__(self, controller, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self.session = MultiViewSession()
        self._panes: dict[PaneId, object] = {}
        #: (generation, frame index) of the request currently in flight.
        self._inflight: dict[PaneId, tuple[int, int]] = {}
        #: True while a synchronised mode drives the main viewer as well.
        self._owns_left = False
        self._window: CommonWindow | None = None
        self._schedule: CycleSchedule | None = None
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(_CLOCK_INTERVAL_MS)
        self._clock_timer.timeout.connect(self._on_clock_tick)
        self._clock_origin_ms = 0.0
        self._hold_until_ms: float | None = None
        self._warned_retiming = False
        #: Independent playback of the right pane: its own clock (spec §8.1).
        self._indep_timer = QTimer(self)
        self._indep_timer.setInterval(_CLOCK_INTERVAL_MS)
        self._indep_timer.timeout.connect(self._on_indep_tick)
        self._indep_origin_ms = 0.0
        self._indep_start_frame = 0

    # ── wiring ──────────────────────────────────────────────────────

    def attach_pane(self, pane_id: PaneId, pane_widget: object) -> None:
        self._panes[pane_id] = pane_widget

    def pane_widget(self, pane_id: PaneId):
        return self._panes.get(pane_id)

    def shutdown(self) -> None:
        """Stop the clock and drop pane references (window teardown)."""
        self._clock_timer.stop()
        self._indep_timer.stop()
        self._panes.clear()

    # ── helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _now_ms() -> float:
        return time.monotonic() * 1000.0

    def _instance(self, pane_id: PaneId) -> InstanceMetadata | None:
        return self.session.pane(pane_id).instance

    def _total_frames(self, pane_id: PaneId) -> int:
        return self.session.pane(pane_id).total_frames

    def _frame_seconds(self, pane_id: PaneId, frame_index: int) -> float | None:
        """Wall-clock offset of a frame inside its own clip (seconds)."""
        return frame_start_seconds(self._instance(pane_id), frame_index)

    # ── pane lifecycle ──────────────────────────────────────────────

    def load_instance(self, pane_id: PaneId, instance: InstanceMetadata, study_uid: str | None = None) -> None:
        """Load a clip into one pane, dropping everything pane-local.

        Replacing a clip always stops the synchronised playback and clears that
        pane's markers, frame and cached speed factors (spec 6.2); the other
        pane is untouched.
        """
        pane = self.session.pane(pane_id)
        self.pause()
        pane.instance = instance
        pane.study_uid = study_uid
        pane.current_frame = 0
        pane.load_error = None
        pane.generation += 1
        pane.clear_markers()
        self._inflight.pop(pane_id, None)
        self._window = None
        self._schedule = None
        self.session.common_start[pane_id] = 0
        if pane_id is PaneId.LEFT and not self._owns_left:
            # The main controller owns the main viewer: keep the two in step.
            self._release_left(0)
        else:
            self._request_pane_frame(pane_id)
        self._refresh_ui()

    def clear_pane(self, pane_id: PaneId) -> None:
        pane = self.session.pane(pane_id)
        self.pause()
        pane.instance = None
        pane.study_uid = None
        pane.current_frame = 0
        pane.load_error = None
        pane.generation += 1
        pane.clear_markers()
        self._inflight.pop(pane_id, None)
        self._window = None
        self._schedule = None
        if pane_id is PaneId.LEFT and not self._owns_left:
            self._release_left(0)
        self._refresh_ui()

    def reset_session(self) -> None:
        """Drop both panes (explicit load of another study/patient)."""
        self.pause()
        for pane_id in (PaneId.LEFT, PaneId.RIGHT):
            pane = self.session.pane(pane_id)
            pane.instance = None
            pane.study_uid = None
            pane.current_frame = 0
            pane.load_error = None
            pane.generation += 1
            pane.clear_markers()
            self._inflight.pop(pane_id, None)
        self.session.active_pane = None
        self.session.playback_mode = PlaybackMode.INDEPENDENT
        self.session.selected_cycle_count = 1
        self.session.global_rate = 1.0
        self.session.is_playing = False
        self._window = None
        self._schedule = None
        self._owns_left = False
        self._refresh_ui()

    def set_pane_load_error(self, pane_id: PaneId, message: str) -> None:
        pane = self.session.pane(pane_id)
        pane.load_error = message
        self._refresh_ui()

    # ── active pane ─────────────────────────────────────────────────

    def activate(self, pane_id: PaneId) -> None:
        if self.session.active_pane is pane_id:
            return
        if not self.session.pane(pane_id).has_clip:
            # An empty pane can never become the active one (spec §10.1).
            return
        self.session.active_pane = pane_id
        self._refresh_ui()

    def request_replace(self, pane_id: PaneId) -> None:
        """«Заменить клип»: arm the pane and let the window pick a clip."""
        self.activate(pane_id)
        self.replace_requested.emit(pane_id)

    # ── frame navigation ────────────────────────────────────────────

    def set_frame(self, pane_id: PaneId, frame_index: int, *, user_initiated: bool = True) -> None:
        pane = self.session.pane(pane_id)
        if pane.instance is None:
            return
        frame_index = clamp_frame(pane.instance, frame_index)
        mode = self.session.playback_mode
        if mode is PlaybackMode.COMMON_WINDOW and user_initiated:
            # Re-anchor the shared window on the frame the user just chose.
            self.session.common_start[pane_id] = frame_index
            self._plan_window()
        pane.current_frame = frame_index
        if mode is PlaybackMode.INDEPENDENT and pane_id is PaneId.RIGHT and pane.playing:
            # Keep independent playback running from the frame the user chose.
            self._indep_origin_ms = self._now_ms()
            self._indep_start_frame = frame_index
        if pane_id is PaneId.LEFT and not self._owns_left:
            self._release_left(frame_index)
            self._refresh_ui()
            return
        self._request_pane_frame(pane_id)
        self._refresh_ui()

    def nudge_frame(self, pane_id: PaneId, delta: int) -> None:
        pane = self.session.pane(pane_id)
        self.set_frame(pane_id, pane.current_frame + delta)

    def on_main_frame_changed(self, frame_index: int) -> None:
        """Mirror the main viewer's frame while it is controller-owned."""
        if self._owns_left:
            return
        pane = self.session.pane(PaneId.LEFT)
        if pane.instance is None:
            return
        pane.current_frame = clamp_frame(pane.instance, frame_index)
        self._refresh_ui()

    def scroll_by(self, pane_id: PaneId, frame_index: int) -> None:
        """Wheel over a pane image.

        Independent mode: that pane only.  While a synchronised mode runs, the
        wheel moves the shared playhead by the equivalent amount of time and
        both clips follow (spec §9).
        """
        pane = self.session.pane(pane_id)
        if pane.instance is None:
            return
        if self.session.playback_mode is PlaybackMode.INDEPENDENT:
            self.set_frame(pane_id, frame_index)
            return
        delta_frames = frame_index - pane.current_frame
        step_seconds = self._frame_seconds(pane_id, pane.current_frame)
        if step_seconds is None:
            step_seconds = 0.0
        self._advance_playhead(delta_frames * step_seconds)

    def _advance_playhead(self, delta_seconds: float) -> None:
        if not self.session.is_playing:
            return
        elapsed_ms = self._elapsed_ms() + delta_seconds * 1000.0
        total_ms = self._schedule_total_ms()
        elapsed_ms = min(max(elapsed_ms, 0.0), max(0.0, total_ms))
        self._clock_origin_ms = self._now_ms() - elapsed_ms
        self._advance(self._now_ms(), elapsed_ms)

    def seek_marker(self, pane_id: PaneId, frame_index: int) -> None:
        """Click on a timeline marker (spec §9).

        Independent mode moves that pane only.  In a synchronised mode the
        shared playhead moves instead, so the other clip follows; playback is
        paused for the repositioning and stays where the user put it.
        """
        pane = self.session.pane(pane_id)
        if pane.instance is None:
            return
        if self.session.playback_mode is PlaybackMode.INDEPENDENT:
            self.set_frame(pane_id, frame_index)
            return
        elapsed_seconds = self._playhead_seconds_for_frame(pane_id, frame_index)
        if elapsed_seconds is None:
            self.set_frame(pane_id, frame_index)
            return
        self.pause()
        self._clock_origin_ms = self._now_ms() - elapsed_seconds * 1000.0
        self._advance(self._now_ms(), elapsed_seconds * 1000.0)

    def _playhead_seconds_for_frame(self, pane_id: PaneId, frame_index: int) -> float | None:
        mode = self.session.playback_mode
        instance = self._instance(pane_id)
        if mode is PlaybackMode.COMMON_WINDOW:
            window = self._window
            if window is None or window.duration_s is None:
                return None
            start = window.left_start if pane_id is PaneId.LEFT else window.right_start
            end = window.left_end if pane_id is PaneId.LEFT else window.right_end
            span = end - start
            if span <= 0:
                return 0.0
            ratio = min(1.0, max(0.0, (frame_index - start) / float(span)))
            return ratio * window.duration_s
        schedule = self._schedule
        if schedule is None or not schedule.is_valid:
            return None
        for entry in schedule.entries:
            cycle = entry.left if pane_id is PaneId.LEFT else entry.right
            if cycle.start_frame <= frame_index <= cycle.end_frame:
                phase = phase_of_frame(instance, cycle.start_frame, cycle.end_frame, frame_index)
                return entry.start_s + phase * entry.duration_s
        return None

    # ── playback ────────────────────────────────────────────────────

    def play(self) -> None:
        if not self._can_sync():
            self.status_message.emit(self._tr("multiview.status.need_two_clips"))
            return
        if self.session.is_playing:
            return
        mode = self.session.playback_mode
        if mode is PlaybackMode.COMMON_WINDOW:
            self._plan_window()
            if self._window is None or not self._window.is_valid:
                self.status_message.emit(self._tr("multiview.status.window_unavailable"))
                return
        elif mode is PlaybackMode.EVENT_CYCLE:
            self._plan_schedule()
            if self._schedule is None or not self._schedule.is_valid:
                self.status_message.emit(self._tr("multiview.status.markers_incomplete"))
                return
            self._warn_if_retimed()
            self._rewind_to_first_marker()
        else:
            return
        if mode is not PlaybackMode.INDEPENDENT and not self._owns_left:
            self._take_over_left()
        self.session.is_playing = True
        self._clock_origin_ms = self._now_ms()
        self._hold_until_ms = None
        self._clock_timer.start()
        self._refresh_ui()

    def pause(self) -> None:
        if not self.session.is_playing:
            return
        self.session.is_playing = False
        self._clock_timer.stop()
        self._indep_timer.stop()
        self._hold_until_ms = None
        for pane_id in (PaneId.LEFT, PaneId.RIGHT):
            self.session.pane(pane_id).playing = False
        self._refresh_ui()

    def toggle_play(self, pane_id: PaneId | None = None) -> None:
        """Any pane's Play/Pause drives the shared playback in sync modes.

        In ``INDEPENDENT`` each pane keeps its own playback: the left pane is
        owned by ``AppController``, the right pane by this controller, and a
        missing ``pane_id`` resolves to the active pane (spec §8.1).
        """
        if self.session.playback_mode is PlaybackMode.INDEPENDENT:
            target = pane_id if pane_id is not None else (self.session.active_pane or PaneId.LEFT)
            if target is PaneId.LEFT:
                self._controller.toggle_playback()
                self._refresh_ui()
                return
            self._toggle_independent_pane()
            return
        if self.session.is_playing:
            self.pause()
        else:
            self.play()

    def toggle_global_play(self) -> None:
        """Toggle both panes from the common transport.

        Pane-local buttons remain independent, but the bar below both panes is
        deliberately global.  In independent mode it starts every loaded cine
        and, crucially, pauses both the AppController-owned left cine and the
        locally-clocked right cine regardless of which pane is active.
        """

        if self.session.playback_mode is not PlaybackMode.INDEPENDENT:
            self.toggle_play()
            return
        if self.any_playback_active():
            try:
                self._controller.set_playing(False)
            except Exception:  # noqa: BLE001 - tolerate small test doubles
                if self._left_native_playing():
                    self._controller.toggle_playback()
            right = self.session.pane(PaneId.RIGHT)
            right.playing = False
            self._indep_timer.stop()
            self.session.is_playing = False
            self._refresh_ui()
            return

        left = self.session.pane(PaneId.LEFT)
        if left.has_clip:
            try:
                self._controller.set_playing(True)
            except Exception:  # noqa: BLE001
                self._controller.toggle_playback()
        right = self.session.pane(PaneId.RIGHT)
        if right.has_clip:
            self._start_independent_right()
        self.session.is_playing = left.has_clip or right.playing
        self._refresh_ui()

    def _start_independent_right(self) -> bool:
        pane = self.session.pane(PaneId.RIGHT)
        instance = pane.instance
        frame_time_ms = instance.frame_time_ms if instance is not None else None
        if instance is None or not frame_time_ms or frame_time_ms <= 0 or pane.total_frames <= 1:
            return False
        pane.playing = True
        self._indep_origin_ms = self._now_ms()
        self._indep_start_frame = pane.current_frame
        self._indep_timer.start()
        return True

    def _toggle_independent_pane(self) -> None:
        """Start/stop the right pane's own playback clock (spec §8.1)."""
        pane = self.session.pane(PaneId.RIGHT)
        if not pane.has_clip:
            return
        if pane.playing:
            pane.playing = False
            self.session.is_playing = False
            self._indep_timer.stop()
        else:
            if not self._start_independent_right():
                return
            self.session.is_playing = True
        self._refresh_ui()

    def _on_indep_tick(self) -> None:
        """Advance the right pane's frame index and wrap around the clip."""
        pane = self.session.pane(PaneId.RIGHT)
        instance = pane.instance
        if not pane.playing or instance is None:
            self._indep_timer.stop()
            return
        frame_time_ms = instance.frame_time_ms or 0.0
        total = pane.total_frames
        if frame_time_ms <= 0 or total <= 1:
            self.pause()
            return
        elapsed_ms = max(0.0, self._now_ms() - self._indep_origin_ms)
        offset = int(elapsed_ms / frame_time_ms)
        frame_index = (self._indep_start_frame + offset) % total
        if frame_index == pane.current_frame:
            return
        pane.current_frame = frame_index
        self._request_pane_frame(PaneId.RIGHT)

    def stop(self) -> None:
        """Return both clips to the start position of the current mode."""
        self.pause()
        mode = self.session.playback_mode
        if mode is PlaybackMode.COMMON_WINDOW:
            for pane_id in (PaneId.LEFT, PaneId.RIGHT):
                self.set_frame(pane_id, self.session.common_start[pane_id])
        elif mode is PlaybackMode.EVENT_CYCLE:
            for pane_id in (PaneId.LEFT, PaneId.RIGHT):
                cycles = cycles_from_markers(self.session.pane(pane_id).markers, self.session.selected_cycle_count)
                if cycles:
                    self.set_frame(pane_id, cycles[0].start_frame)
        self._refresh_ui()

    def _rewind_to_first_marker(self) -> None:
        """Both clips show their own first marker when a cycle starts."""
        for pane_id in (PaneId.LEFT, PaneId.RIGHT):
            pane = self.session.pane(pane_id)
            cycles = cycles_from_markers(pane.markers, self.session.selected_cycle_count)
            if not cycles:
                continue
            pane.current_frame = clamp_frame(pane.instance, cycles[0].start_frame)
            self._request_pane_frame(pane_id)

    def _can_sync(self) -> bool:
        left = self.session.pane(PaneId.LEFT)
        right = self.session.pane(PaneId.RIGHT)
        return left.has_clip and right.has_clip

    def pane_is_playing(self, pane_id: PaneId) -> bool:
        """State a pane's own Play/Pause button should show (spec §8.1)."""
        if self.session.playback_mode is not PlaybackMode.INDEPENDENT:
            return self.session.is_playing
        if pane_id is PaneId.LEFT:
            return self._left_native_playing()
        return self.session.pane(pane_id).playing

    def any_playback_active(self) -> bool:
        """Shared transport label: true while any pane is playing."""
        if self.session.playback_mode is PlaybackMode.INDEPENDENT:
            return self.pane_is_playing(PaneId.LEFT) or self.pane_is_playing(PaneId.RIGHT)
        return self.session.is_playing

    def _left_native_playing(self) -> bool:
        """Mirror AppController's playback state; conservative for doubles."""
        try:
            value = self._controller.state_manager.snapshot.is_playing
        except Exception:  # noqa: BLE001 - controller may be a test double
            return False
        return value if isinstance(value, bool) else False

    # ── mode / rate ─────────────────────────────────────────────────

    def set_mode(self, mode: PlaybackMode) -> None:
        if mode is self.session.playback_mode:
            return
        self.pause()
        self.session.playback_mode = mode
        if mode is PlaybackMode.COMMON_WINDOW:
            for pane_id in (PaneId.LEFT, PaneId.RIGHT):
                self.session.common_start[pane_id] = self.session.pane(pane_id).current_frame
            self._plan_window()
        elif mode is PlaybackMode.EVENT_CYCLE:
            self._plan_schedule()
            self._warn_if_retimed()
        if mode is PlaybackMode.INDEPENDENT and self._owns_left:
            self._release_left(self.session.pane(PaneId.LEFT).current_frame)
        self._refresh_ui()

    def set_rate(self, rate: float) -> None:
        self.session.global_rate = clamp_rate(rate)
        if self.session.playback_mode is PlaybackMode.EVENT_CYCLE:
            self._plan_schedule()
            if self.session.is_playing:
                self._warn_if_retimed()
        self._refresh_ui()

    def set_cycle_count(self, cycle_count: int) -> None:
        count = 2 if int(cycle_count) >= 2 else 1
        if count == self.session.selected_cycle_count:
            return
        self.pause()
        self.session.selected_cycle_count = count
        self._plan_schedule()
        self._refresh_ui()

    def _plan_window(self) -> None:
        self._window = plan_common_window(
            self._instance(PaneId.LEFT),
            self.session.common_start[PaneId.LEFT],
            self._instance(PaneId.RIGHT),
            self.session.common_start[PaneId.RIGHT],
        )

    def _plan_schedule(self) -> None:
        count = self.session.selected_cycle_count
        left_cycles = cycles_from_markers(self.session.pane(PaneId.LEFT).markers, count)
        right_cycles = cycles_from_markers(self.session.pane(PaneId.RIGHT).markers, count)
        if not left_cycles or not right_cycles:
            self._schedule = None
            return
        self._schedule = build_cycle_schedule(
            self._instance(PaneId.LEFT),
            left_cycles,
            self._instance(PaneId.RIGHT),
            right_cycles,
            self.session.global_rate,
        )

    def _warn_if_retimed(self) -> None:
        schedule = self._schedule
        if schedule is None or self._warned_retiming:
            return
        worst = max((entry.timing for entry in schedule.entries), key=lambda timing: timing.max_abs_deviation)
        if not worst.needs_warning:
            return
        self._warned_retiming = True
        self.warning_requested.emit(
            self._tr("multiview.warning.retiming_title"),
            self._tr(
                "multiview.warning.retiming_body",
                left=f"{worst.k_left:.2f}",
                right=f"{worst.k_right:.2f}",
            ),
        )

    # ── markers ─────────────────────────────────────────────────────

    def place_marker(self, pane_id: PaneId, ordinal: int) -> None:
        """Place (or re-place) marker ``ordinal`` at the pane's current frame."""
        pane = self.session.pane(pane_id)
        if pane.instance is None:
            self.status_message.emit(self._tr("multiview.status.no_clip"))
            return
        if self.session.is_playing:
            # Manual marker editing always breaks playback (spec §9).
            self.pause()
        frame_index = clamp_frame(pane.instance, pane.current_frame)
        markers = list(pane.markers[:ordinal])
        problem = validate_new_marker(markers, frame_index, pane.total_frames)
        if problem is not None:
            self.status_message.emit(self._tr(problem))
            return
        markers.append(EventMarker(frame_index=frame_index, label=DEFAULT_EVENT_LABEL))
        pane.markers = markers
        self._plan_schedule()
        self._refresh_ui()

    def remove_marker(self, pane_id: PaneId, ordinal: int) -> None:
        pane = self.session.pane(pane_id)
        if ordinal < 0 or ordinal >= len(pane.markers):
            return
        self.pause()
        pane.markers = list(pane.markers[:ordinal])
        self._plan_schedule()
        self._refresh_ui()

    def rename_marker(self, pane_id: PaneId, ordinal: int, label: str) -> None:
        """Give one marker a user label instead of the default МК (spec 7.1)."""
        pane = self.session.pane(pane_id)
        if ordinal < 0 or ordinal >= len(pane.markers):
            return
        text = (label or "").strip() or DEFAULT_EVENT_LABEL
        markers = list(pane.markers)
        markers[ordinal] = replace(markers[ordinal], label=text[:MAX_EVENT_LABEL])
        pane.markers = tuple(markers)
        self._refresh_ui()

    def clear_markers(self, pane_id: PaneId) -> None:
        pane = self.session.pane(pane_id)
        if not pane.markers:
            return
        self.pause()
        pane.clear_markers()
        self._plan_schedule()
        self._refresh_ui()

    def clear_all_markers(self) -> None:
        self.pause()
        for pane_id in (PaneId.LEFT, PaneId.RIGHT):
            self.session.pane(pane_id).clear_markers()
        self._plan_schedule()
        self._refresh_ui()

    # ── clock ───────────────────────────────────────────────────────

    def _elapsed_ms(self) -> float:
        return max(0.0, self._now_ms() - self._clock_origin_ms)

    def _schedule_total_ms(self) -> float:
        if self._window is not None and self._window.duration_s is not None:
            return self._window.duration_s * 1000.0
        if self._schedule is not None:
            return self._schedule.total_s * 1000.0
        return 0.0

    def _on_clock_tick(self) -> None:
        now_ms = self._now_ms()
        if self._hold_until_ms is not None:
            if now_ms < self._hold_until_ms:
                return
            self._hold_until_ms = None
            self._clock_origin_ms = now_ms
        self._advance(now_ms, now_ms - self._clock_origin_ms)

    def _advance(self, now_ms: float, elapsed_ms: float) -> None:
        mode = self.session.playback_mode
        if mode is PlaybackMode.COMMON_WINDOW:
            self._advance_common_window(now_ms, elapsed_ms)
        elif mode is PlaybackMode.EVENT_CYCLE:
            self._advance_event_cycle(now_ms, elapsed_ms)

    def _advance_common_window(self, now_ms: float, elapsed_ms: float) -> None:
        window = self._window
        if window is None or window.duration_s is None:
            self.pause()
            return
        duration_ms = window.duration_s * 1000.0
        if elapsed_ms >= duration_ms:
            self._show_frames(window.left_end, window.right_end)
            if self._hold_until_ms is None:
                self._hold_until_ms = now_ms + ENDPOINT_HOLD_MS
            return
        left, right = common_window_frames(
            window,
            elapsed_ms / 1000.0,
            self._instance(PaneId.LEFT),
            self._instance(PaneId.RIGHT),
        )
        self._show_frames(left, right)

    def _advance_event_cycle(self, now_ms: float, elapsed_ms: float) -> None:
        schedule = self._schedule
        if schedule is None or not schedule.is_valid:
            self.pause()
            return
        if elapsed_ms >= schedule.total_s * 1000.0:
            last = schedule.entries[-1]
            self._show_frames(last.left.end_frame, last.right.end_frame)
            if self._hold_until_ms is None:
                self._hold_until_ms = now_ms + ENDPOINT_HOLD_MS
            return
        entry, phase = schedule.locate(elapsed_ms / 1000.0)
        if entry is None:
            return
        left = frame_at_phase(self._instance(PaneId.LEFT), entry.left.start_frame, entry.left.end_frame, phase)
        right = frame_at_phase(self._instance(PaneId.RIGHT), entry.right.start_frame, entry.right.end_frame, phase)
        self._show_frames(left, right)

    def _show_frames(self, left_frame: int, right_frame: int) -> None:
        for pane_id, frame_index in ((PaneId.LEFT, left_frame), (PaneId.RIGHT, right_frame)):
            pane = self.session.pane(pane_id)
            if pane.instance is None:
                continue
            if pane.current_frame != frame_index:
                pane.current_frame = frame_index
                self._request_pane_frame(pane_id)
            else:
                self._refresh_pane(pane_id)

    # ── frame loading ───────────────────────────────────────────────

    def _request_pane_frame(self, pane_id: PaneId) -> None:
        pane = self.session.pane(pane_id)
        instance = pane.instance
        if instance is None or instance.path is None:
            return
        if pane_id in self._inflight:
            # One request per pane: the running one chains to the newest frame.
            return
        frame_index = clamp_frame(instance, pane.current_frame)
        pane.current_frame = frame_index
        generation = pane.generation
        self._inflight[pane_id] = (generation, frame_index)
        cache = getattr(self._controller, "_frame_cache", None)
        if cache is not None and cache.is_ready(instance.path):
            try:
                pixels = np.asarray(cache.get(frame_index))
            except (RuntimeError, IndexError, ValueError):
                pixels = None
            if pixels is not None:
                self._on_pane_frame(pane_id, generation, frame_index, pixels)
                return
        self._start_worker(pane_id, generation, frame_index)

    def _start_worker(self, pane_id: PaneId, generation: int, frame_index: int) -> None:
        from PySide6.QtCore import Qt, QThreadPool

        from echo_personal_tool.application.workers.frame_loader_worker import FrameLoaderWorker

        instance = self.session.pane(pane_id).instance
        if instance is None or instance.path is None:
            self._inflight.pop(pane_id, None)
            return
        worker = FrameLoaderWorker(
            instance.path,
            frame_index,
            instance.media_format,
            total_frames=instance.number_of_frames,
        )
        worker.signals.finished.connect(
            lambda pixels, pane_id=pane_id, generation=generation, frame_index=frame_index: self._on_pane_frame(
                pane_id, generation, frame_index, np.asarray(pixels)
            ),
            Qt.ConnectionType.QueuedConnection,
        )
        worker.signals.failed.connect(
            lambda message, pane_id=pane_id, generation=generation: self._on_pane_frame_failed(
                pane_id, generation, message
            ),
            Qt.ConnectionType.QueuedConnection,
        )
        QThreadPool.globalInstance().start(worker)

    def _on_pane_frame(self, pane_id: PaneId, generation: int, frame_index: int, pixels: np.ndarray) -> None:
        self._inflight.pop(pane_id, None)
        pane = self.session.pane(pane_id)
        if pane.generation != generation or pane.instance is None:
            return  # stale answer for a clip that has already been replaced
        pane.load_error = None
        pane_widget = self._panes.get(pane_id)
        if pane_widget is None:
            return
        try:
            viewer = pane_widget.viewer
        except RuntimeError:
            return
        viewer.show_frame(pixels)
        if pane.current_frame != frame_index:
            self._request_pane_frame(pane_id)
            return
        self._refresh_pane(pane_id)

    def _on_pane_frame_failed(self, pane_id: PaneId, generation: int, message: str) -> None:
        self._inflight.pop(pane_id, None)
        pane = self.session.pane(pane_id)
        if pane.generation != generation:
            return
        pane.load_error = message
        logger.warning("[multiview] pane %s frame load failed: %s", pane_id.value, message)
        if self.session.is_playing:
            self.pause()
        self.status_message.emit(message)
        self._refresh_ui()

    # ── left-pane ownership ─────────────────────────────────────────

    def _take_over_left(self) -> None:
        """Drive the main viewer from the shared clock."""
        if self._owns_left:
            return
        try:
            self._controller.set_playing(False)
        except Exception:  # noqa: BLE001 - controller may be a test double
            logger.debug("[multiview] controller has no set_playing", exc_info=True)
        self._owns_left = True

    def _release_left(self, frame_index: int) -> None:
        """Hand the main viewer back to ``AppController``."""
        self._owns_left = False
        self.left_pane_released.emit(frame_index)

    # ── UI refresh ──────────────────────────────────────────────────

    def refresh(self) -> None:
        """Public entry point: repaint both panes and notify the transport."""
        self._refresh_ui()

    def _refresh_ui(self) -> None:
        for pane_id in (PaneId.LEFT, PaneId.RIGHT):
            self._refresh_pane(pane_id)
        self.session_changed.emit()

    def _refresh_pane(self, pane_id: PaneId) -> None:
        pane_widget = self._panes.get(pane_id)
        pane = self.session.pane(pane_id)
        if pane_widget is None:
            return
        try:
            viewer = pane_widget.viewer
        except RuntimeError:
            return
        instance = pane.instance
        total = pane.total_frames
        file_name = self._pane_file_name(instance)
        frame_text = self._pane_frame_text(pane_id)
        try:
            viewer.set_transport_state(
                frame_index=pane.current_frame,
                total_frames=total,
                frame_time_ms=None if instance is None else instance.frame_time_ms,
                is_playing=self.pane_is_playing(pane_id),
            )
        except RuntimeError:
            return
        pane_widget.set_header(
            file_name=file_name,
            frame_text=frame_text,
            has_clip=instance is not None,
            error=pane.load_error,
        )
        pane_widget.set_active(self.session.active_pane is pane_id)
        pane_widget.set_cycle_count(self.session.selected_cycle_count)
        pane_widget.set_markers(pane.markers, total, pane.current_frame)
        pane_widget.set_window(self._pane_window(pane_id))

    def _pane_window(self, pane_id: PaneId) -> tuple[int, int] | None:
        """Start and common end of the shared window, drawn on the timeline.

        Spec 8.2: every pane shows its own start and the common endpoint, so
        the unplayed tail of the longer clip stays visible.
        """
        if self.session.playback_mode is not PlaybackMode.COMMON_WINDOW:
            return None
        window = self._window
        if window is None or not window.is_valid:
            return None
        if pane_id is PaneId.LEFT:
            return window.left_start, window.left_end
        return window.right_start, window.right_end

    def _pane_file_name(self, instance: InstanceMetadata | None) -> str:
        if instance is None:
            return "—"
        if instance.path is not None:
            return instance.path.name
        return instance.sop_instance_uid

    def _pane_frame_text(self, pane_id: PaneId) -> str:
        pane = self.session.pane(pane_id)
        total = pane.total_frames
        if total <= 0:
            return "—"
        seconds = self._frame_seconds(pane_id, pane.current_frame)
        frame_part = f"{pane.current_frame + 1}/{total}"
        if seconds is None:
            return frame_part
        return f"{frame_part} · {seconds:.2f} с"

    # ── status for the transport bar ────────────────────────────────

    def status_text(self) -> str:
        mode = self.session.playback_mode
        if mode is PlaybackMode.INDEPENDENT:
            return self._tr("multiview.status.independent")
        if mode is PlaybackMode.COMMON_WINDOW:
            window = self._window
            if window is None or window.duration_s is None:
                return self._tr("multiview.status.common_window_unknown")
            return self._tr("multiview.status.common_window", duration=f"{window.duration_s:.2f}")
        schedule = self._schedule
        if schedule is None or not schedule.is_valid:
            return self._tr("multiview.status.markers_incomplete")
        cycles = (
            self._tr("multiview.cycles.one")
            if self.session.selected_cycle_count == 1
            else self._tr("multiview.cycles.two")
        )
        basis = (
            self._tr("multiview.status.basis_phase")
            if schedule.timing_known
            else self._tr("multiview.status.basis_phase_unknown")
        )
        return self._tr("multiview.status.event_cycle", cycles=cycles, basis=basis)

    def pane_rate_texts(self) -> tuple[str, str]:
        """Per-pane speed factors of the running cycle (spec §8.3)."""
        schedule = self._schedule
        if schedule is None or not schedule.is_valid:
            return "—", "—"
        entry = schedule.entries[0]
        if self.session.is_playing:
            located, _phase = schedule.locate(self._elapsed_ms() / 1000.0)
            if located is not None:
                entry = located
        left = f"{entry.timing.k_left:.2f}×"
        right = f"{entry.timing.k_right:.2f}×"
        if len(schedule.entries) > 1:
            left = f"{left} / {schedule.entries[1].timing.k_left:.2f}×"
            right = f"{right} / {schedule.entries[1].timing.k_right:.2f}×"
        return left, right

    def current_timing(self) -> object | None:
        schedule = self._schedule
        if schedule is None or not schedule.is_valid:
            return None
        return schedule.entries[0].timing

    @staticmethod
    def _tr(key: str, **kwargs: str) -> str:
        from echo_personal_tool.infrastructure.i18n import tr

        return tr(key, **kwargs)
