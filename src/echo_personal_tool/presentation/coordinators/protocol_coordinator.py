"""Protocol workflow owner for MainWindow (issue 503)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject

from echo_personal_tool.application.localization import get_language, tr
from echo_personal_tool.application.protocol_runner import EscapeResult, StepAction
from echo_personal_tool.application.protocol_session import ProtocolSession
from echo_personal_tool.domain.protocol_definitions import PROTOCOLS_BY_ID


@dataclass(frozen=True)
class ProtocolWindowPort:
    """Explicit, late-bound interactions with the window; never the window itself."""

    create_bar: Callable[[], Any]
    create_session: Callable[[QObject], ProtocolSession]
    tool_panel: Callable[[], Any]
    finish_tool: Callable[[], None]
    open_reference: Callable[[], None]
    viewer_drawing: Callable[[], bool]
    cancel_viewer_tool: Callable[[], None]
    show_status: Callable[[str], None]
    ask_rap: Callable[[], tuple[float, bool]]
    set_rap: Callable[[float], None]


class ProtocolCoordinator(QObject):
    """Owns the session, step bar, armed step and per-protocol auto advance."""

    def __init__(self, port: ProtocolWindowPort, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._port = port
        self._protocol_step_bar: Any | None = None
        self._protocol_session: ProtocolSession | None = None
        self._protocol_armed_index: int | None = None
        self._protocol_auto_advance: dict[str, bool] = {}

    @property
    def session(self) -> ProtocolSession | None:
        return self._protocol_session

    @property
    def step_bar(self) -> Any | None:
        return self._protocol_step_bar

    @property
    def armed_index(self) -> int | None:
        return self._protocol_armed_index

    def is_active(self) -> bool:
        return self._protocol_session is not None and bool(self._protocol_session.active_protocol_id)

    def advance_pending(self) -> bool:
        session = self._protocol_session
        if session is None or session.runner.pending_advance is None:
            return False
        session.runner.advance_now()
        return True

    def study_changed(self) -> None:
        if self._protocol_session is not None:
            self._protocol_session.on_study_changed()

    def ensure_step_bar(self) -> Any:
        """The strip under the snapshot (UI-3); created once, then reused."""
        if self._protocol_step_bar is None:
            bar = self._port.create_bar()
            bar.skip_requested.connect(self.skip)
            bar.done_requested.connect(self._port.finish_tool)
            bar.cancel_point_requested.connect(self._on_protocol_cancel_point)
            bar.rap_chosen.connect(self._on_rap_chosen)
            bar.rap_other_requested.connect(self._on_rap_other_requested)
            bar.rap_reference_requested.connect(self._port.open_reference)
            self._protocol_step_bar = bar
        self.apply_step_bar_labels()
        return self._protocol_step_bar

    def apply_step_bar_labels(self) -> None:
        if self._protocol_step_bar is None:
            return
        self._protocol_step_bar.set_labels(
            cancel=tr("protocol.cancel_point"),
            skip=tr("protocol.skip"),
            done=tr("protocol.done"),
            rap_hint=tr("protocol.rap_hint"),
            notification_hint=tr("protocol.notification_hint"),
        )

    def ensure_session(self) -> ProtocolSession:
        """The protocol session of this tab (created on the first use)."""
        if self._protocol_session is None:
            session = self._port.create_session(self)
            session.progress_changed.connect(self._on_protocol_progress)
            session.action_requested.connect(self._on_protocol_step_action)
            session.notification.connect(self._on_protocol_notification)
            session.finished.connect(self._on_protocol_finished)
            session.stopped.connect(self._on_protocol_stopped)
            session.statuses_changed.connect(self._on_protocol_statuses)
            session.drawing_cancel_requested.connect(self._on_protocol_drawing_cancel)
            self._protocol_session = session
        return self._protocol_session

    def select(self, protocol_id: str) -> None:
        self.ensure_session().start(protocol_id)

    def activate_step(self, index: int) -> None:
        session = self._protocol_session
        if session is not None and session.active:
            session.arm(index)

    def stop_requested(self) -> None:
        self.ensure_session().stop("user")

    def auto_advance_toggled(self, protocol_id: str, enabled: bool) -> None:
        """The footer switch: remember the flag and retime the live runner."""
        self._protocol_auto_advance[protocol_id] = bool(enabled)
        session = self._protocol_session
        if session is None or not session.active:
            return
        from echo_personal_tool.application.protocol_runner import DEFAULT_AUTO_ADVANCE_MS

        session.runner.auto_advance_ms = DEFAULT_AUTO_ADVANCE_MS if enabled else 0

    def _push_protocol_auto_advance(self, protocol_id: str) -> None:
        """Sync the card footer with the remembered flag of the protocol.

        Default is **off**: a finished step waits for Enter or a click on the
        next tile instead of yanking the tool away mid-correction (2026-10-25).
        """
        enabled = self._protocol_auto_advance.get(protocol_id, False)
        self._port.tool_panel().set_protocol_auto_advance(protocol_id, enabled)
        session = self._protocol_session
        if session is not None and session.active:
            from echo_personal_tool.application.protocol_runner import DEFAULT_AUTO_ADVANCE_MS

            session.runner.auto_advance_ms = DEFAULT_AUTO_ADVANCE_MS if enabled else 0

    def study_projection_changed(self, _projection: object = None) -> None:
        if self._protocol_session is not None:
            self._protocol_session.refresh()

    def _on_protocol_progress(self, progress: object) -> None:
        self._port.tool_panel().set_protocol_progress(progress)
        protocol_id = getattr(progress, "protocol_id", "")
        if protocol_id:
            self._push_protocol_auto_advance(protocol_id)
        self.sync_step_bar(progress)
        self._sync_protocol_step_highlight(progress)

    def _on_protocol_statuses(self, statuses: object) -> None:
        self._port.tool_panel().set_tool_statuses(statuses)

    def _on_protocol_step_action(self, action: object) -> None:
        if not isinstance(action, StepAction):
            return
        self._protocol_armed_index = action.index
        if action.open_protocol:
            self.ensure_session().start(action.open_protocol)
            return
        if not action.tool_id:
            # A step without a tool (the RAP chips, П6.2) is driven by the bar.
            return
        if self._port.tool_panel().is_v2:
            self._port.tool_panel().activate_tool(action.tool_id)
            self._port.tool_panel().measure.highlight_tool(action.tool_id)

    def _on_protocol_notification(self, code: str) -> None:
        bar = self.ensure_step_bar()
        if code == "auto_advance":
            text = self._auto_advance_text()
            if text:
                bar.show_notification(text, hint=self._advance_hint_text())

    def _advance_hint_text(self) -> str:
        """Hint of the advance notification: the timer's Esc, or Enter to confirm."""
        session = self._protocol_session
        auto = self._protocol_auto_advance.get(session.active_protocol_id, False) if session else False
        return tr("protocol.notification_hint") if auto else tr("protocol.notification_confirm")

    def _auto_advance_text(self) -> str:
        """«✓ шаг → далее: следующий» — уведомление Q-07 по текущему прогрессу."""
        session = self._protocol_session
        if session is None:
            return ""
        spec = PROTOCOLS_BY_ID.get(session.active_protocol_id)
        progress = session.progress
        if spec is None or progress is None or progress.current_index is None:
            return ""
        language = get_language()
        next_label = spec.steps[progress.current_index].label(language)
        armed = self._protocol_armed_index
        done_label = (
            spec.steps[armed].label(language)
            if armed is not None and 0 <= armed < len(spec.steps)
            else tr("protocol.notification_advance")
        )
        return f"✓ {done_label} → {tr('protocol.notification_next', step=next_label)}"

    def _on_protocol_finished(self, _protocol_id: str) -> None:
        bar = self.ensure_step_bar()
        bar.show_notification(tr("protocol.notification_done"), hint=tr("protocol.notification_hint"))
        if self._port.tool_panel().is_v2:
            self._port.tool_panel().measure.clear_action_highlight()

    def _on_protocol_stopped(self, _reason: str) -> None:
        self._port.tool_panel().set_protocol_progress(None)
        self._protocol_armed_index = None
        self.ensure_step_bar().clear()
        if self._port.tool_panel().is_v2:
            self._port.tool_panel().measure.clear_action_highlight()

    def _on_protocol_drawing_cancel(self) -> None:
        self._port.cancel_viewer_tool()

    def skip(self) -> None:
        session = self._protocol_session
        if session is not None and session.active:
            session.skip()

    def _on_protocol_cancel_point(self) -> None:
        if self._viewer_drawing():
            self._port.cancel_viewer_tool()
            return
        session = self._protocol_session
        if session is not None and session.active:
            session.runner.cancel_point()

    def _on_rap_chosen(self, value: float) -> None:
        self._port.set_rap(float(value))

    def _on_rap_other_requested(self) -> None:
        value, accepted = self._port.ask_rap()
        if accepted:
            self._port.set_rap(float(value))

    def escape(self) -> bool:
        """A-09: drawing → auto-advance → stop; only a running protocol answers."""
        session = self._protocol_session
        if session is None or not session.active:
            return False
        drawing = self._viewer_drawing()
        session.runner.set_drawing_active(drawing)
        result = session.on_escape()
        if result is EscapeResult.DRAWING_CANCELLED:
            if drawing:
                self._port.cancel_viewer_tool()
            else:
                # The step was armed but nothing was drawn yet: drop the point
                # so the next Esc stops the protocol (A-09).
                session.runner.cancel_point()
            return True
        if result is EscapeResult.ADVANCE_CANCELLED:
            self._port.show_status(tr("protocol.advance_cancelled"))
            return True
        return result is EscapeResult.STOPPED

    def _viewer_drawing(self) -> bool:
        """Whether the viewer is mid-contour or mid-caliper — the Esc stage 1."""
        return self._port.viewer_drawing()

    def sync_step_bar(self, progress: object | None = None) -> None:
        """Show the current (or armed) step of a running protocol; else hide."""
        bar = self.ensure_step_bar()
        session = self._protocol_session
        if session is None or not session.active:
            bar.clear()
            return
        if progress is None:
            progress = session.progress
        spec = PROTOCOLS_BY_ID.get(session.active_protocol_id)
        if spec is None or progress is None:
            bar.clear()
            return
        runner = session.runner
        index = runner.armed_index if runner.armed_index is not None else getattr(progress, "current_index", None)
        if index is None or not (0 <= index < len(spec.steps)):
            bar.clear()
            return
        step = spec.steps[index]
        bar.set_step(
            protocol_label=spec.label(get_language()),
            index=index,
            total=len(spec.steps),
            step_label=step.label(get_language()),
            frame_hint=self._frame_hint_label(step.frame_hint),
            can_cancel=runner.armed_index is not None,
            rap=not step.tool_id and "ra.rap" in step.satisfied_keys,
        )

    def _sync_protocol_step_highlight(self, _progress: object | None = None) -> None:
        """Keep the armed step's row marked in the panel (spec §6.2)."""
        if not self._port.tool_panel().is_v2:
            return
        session = self._protocol_session
        armed = session.runner.armed_index if session is not None and session.active else None
        if armed is None or session is None:
            self._port.tool_panel().measure.clear_action_highlight()
            return
        spec = PROTOCOLS_BY_ID.get(session.active_protocol_id)
        if spec is None:
            return
        tool_id = spec.steps[armed].tool_id
        if tool_id:
            self._port.tool_panel().measure.highlight_tool(tool_id)

    def _frame_hint_label(self, frame_hint: str | None) -> str:
        key = {"ed": "protocol.frame_ed", "es": "protocol.frame_es"}.get(frame_hint or "")
        return tr(key) if key else (frame_hint or "")
