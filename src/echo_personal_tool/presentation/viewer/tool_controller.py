"""ToolInteractionController — QH-3 slice for tool gestures (G3 #185).

Spec §7.1: owns active tool, draft gesture, commit/cancel, routing.  It does
not own disk/network I/O and never reaches for global identity via MainWindow.

The viewer facade forwards Qt events (press/move/release/cancel) to this
controller; the controller emits typed outcomes that the window turns into
application calls (append measurement, store contour, request ONNX).  No tool
mutates another source after a generation bump (S-02).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from PySide6.QtCore import QObject, Signal

from echo_personal_tool.presentation.viewer.commands import CommandResult, accepted, rejected
from echo_personal_tool.presentation.viewer.context import ViewerContext

ToolKind = Literal["none", "distance", "area", "volume", "calibration", "doppler", "vessel", "mmode_line"]

# ---------------------------------------------------------------------------
# ToolSession — draft state for the active tool
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ToolSession:
    kind: ToolKind = "none"
    label: str = ""
    start: tuple[float, float] | None = None
    current: tuple[float, float] | None = None
    committed: bool = False
    generation: int = 0

    def reset(self) -> None:
        self.kind = "none"
        self.label = ""
        self.start = None
        self.current = None
        self.committed = False

    @property
    def active(self) -> bool:
        return self.kind != "none"


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------


class ToolInteractionController(QObject):
    """Routing and lifecycle for all measurement-tool gestures.

    Created by the viewer facade (parent = ViewerWidget).  It holds no
    measurement storage — that remains in StudyMeasurementSessionStore — and
    never imports infrastructure ports.  All commits go through explicit
    callbacks supplied at construction time so tests can inject fakes.
    """

    # Typed outcomes observed by MainWindow / tests
    tool_committed = Signal(object)  # CommandResult with measurement payload
    tool_cancelled = Signal(object)  # CommandResult reason
    tool_preview = Signal(object)  # draft geometry for the viewer to draw

    def __init__(
        self,
        *,
        parent: QObject | None = None,
        commit_handler: Callable[
            [ToolKind, tuple[float, float] | None, tuple[float, float], ViewerContext], CommandResult
        ]
        | None = None,
        preview_handler: Callable[[ToolKind, tuple[float, float] | None, tuple[float, float]], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._session = ToolSession()
        self._context: ViewerContext | None = None
        self._commit_handler = commit_handler
        self._preview_handler = preview_handler
        # Sequence for chained calipers (e.g. LVEDD → IVSd → LVPWd)
        self._sequence: list[str] = []
        self._sequence_size: int = 0

    # -- context -------------------------------------------------------------

    @property
    def context(self) -> ViewerContext | None:
        return self._context

    def set_context(self, ctx: ViewerContext) -> None:
        """Generation bump cancels any draft from the old source (S-02)."""
        if self._context is not None and self._context.generation != ctx.generation:
            if self._session.active:
                self.cancel(reason="generation_bump")
        self._context = ctx
        self._session.generation = ctx.generation

    # -- tool activation -----------------------------------------------------

    def activate(self, kind: ToolKind, *, label: str = "", sequence: list[str] | None = None) -> CommandResult:
        if self._session.active:
            # Explicit cancel beats silent override — keeps characterization green
            self.cancel(reason="tool_switch")
        self._session.kind = kind
        self._session.label = label or self._choose_label(kind)
        self._session.start = None
        self._session.current = None
        self._session.committed = False
        if sequence is not None:
            self._sequence = list(sequence)
            self._sequence_size = len(sequence)
        elif kind == "distance":
            # Generic distance enters repeat mode (scanner UX)
            pass
        self._session.generation = self._context.generation if self._context else 0
        return accepted(payload={"kind": kind, "label": self._session.label})

    def deactivate(self) -> CommandResult:
        if not self._session.active:
            return accepted(reason="no_active_tool")
        self._session.reset()
        self._sequence.clear()
        self._sequence_size = 0
        return accepted(reason="deactivated")

    def _choose_label(self, kind: ToolKind) -> str:
        # Minimal — real label choice stays in viewer until the label picker slice
        if kind == "distance":
            return "Dist1"
        if kind == "area":
            return "Area"
        if kind == "volume":
            return "Vol"
        return ""

    # -- gesture (press/move/release) --------------------------------------

    def on_press(self, pos: tuple[float, float]) -> CommandResult:
        if not self._session.active:
            return accepted(reason="no_tool_ignore")
        if self._context is None:
            return rejected("no_context")
        if self._session.start is None:
            self._session.start = pos
            self._session.current = pos
            self._notify_preview()
            return accepted(reason="first_click")
        # Second click — commit
        end = pos
        return self._commit(self._session.start, end)

    def on_move(self, pos: tuple[float, float]) -> None:
        if not self._session.active or self._session.start is None:
            return
        self._session.current = pos
        self._notify_preview()

    def on_release(self, pos: tuple[float, float]) -> CommandResult:
        if not self._session.active or self._session.start is None:
            return accepted(reason="no_draft")
        # Freehand-style: release commits if we have enough points
        return self._commit(self._session.start, pos)

    def _commit(self, start: tuple[float, float], end: tuple[float, float]) -> CommandResult:
        if self._context is None:
            return rejected("no_context")
        if self._commit_handler is not None:
            result = self._commit_handler(self._session.kind, start, end, self._context)
            if not result.accepted:
                return result
        self.tool_committed.emit(
            accepted(payload={"kind": self._session.kind, "start": start, "end": end, "label": self._session.label})
        )
        # Sequence handling
        if self._sequence:
            next_label = self._sequence.pop(0)
            self._session.label = next_label
            self._session.start = end  # chain: start next where this ended
            self._session.current = end
            self._notify_preview()
        elif self._sequence_size > 1:
            self.deactivate()
        else:
            # Repeat mode for generic distance: stay armed
            if self._session.kind == "distance" and not self._session.label.startswith("Dist"):
                self._session.start = None
                self._session.current = None
            elif self._session.kind == "distance":
                # DistN → DistN+1
                try:
                    n = int(self._session.label.replace("Dist", "") or "1")
                    self._session.label = f"Dist{n + 1}"
                except ValueError:
                    pass
                self._session.start = None
                self._session.current = None
            else:
                self._session.start = None
                self._session.current = None
        return accepted(payload={"start": start, "end": end})

    def cancel(self, *, reason: str = "user_cancel") -> CommandResult:
        was_active = self._session.active
        self._session.reset()
        self._sequence.clear()
        self._sequence_size = 0
        if was_active:
            self.tool_cancelled.emit(accepted(reason=reason))
        return accepted(reason=reason)

    def _notify_preview(self) -> None:
        if self._session.start is None or self._session.current is None:
            return
        if self._preview_handler is not None:
            self._preview_handler(self._session.kind, self._session.start, self._session.current)
        self.tool_preview.emit({"kind": self._session.kind, "start": self._session.start, "end": self._session.current})

    # -- lifecycle -----------------------------------------------------------

    def dispose(self) -> None:
        self._session.reset()
        self._sequence.clear()
        try:
            self.tool_committed.disconnect()
        except (RuntimeError, TypeError):
            pass
        try:
            self.tool_cancelled.disconnect()
        except (RuntimeError, TypeError):
            pass
        try:
            self.tool_preview.disconnect()
        except (RuntimeError, TypeError):
            pass


__all__ = ["ToolInteractionController", "ToolSession", "ToolKind"]
