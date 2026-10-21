"""Explicit viewer commands — QH-3 composition primitive.

Spec §7.1: Tool/contour/calibration/overlay interactions are expressed as
immutable commands that carry captured context + generation.  ViewerWidget (Qt
facade) translates events into commands; controllers execute them and emit
typed outcomes.  No command mutates Qt from a worker thread; late callbacks
are delivered only when `generation` matches the current ViewerContext (§5.2).

This keeps behaviour parity with the monolithic ViewerWidget while making
ownership explicit: a gesture cannot leak into another source after a tab
switch because its generation mismatches (S-02), and a late ONNX result is
discarded rather than resurrecting deleted data (S-05).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

from echo_personal_tool.presentation.viewer.context import ViewerContext

# ---------------------------------------------------------------------------
# Result types (typed outcomes, not silent success/[] — QH-4a)
# ---------------------------------------------------------------------------

OutcomeKind = Literal["accepted", "rejected", "discarded_stale", "no_op"]


@dataclass(frozen=True, slots=True)
class CommandResult:
    kind: OutcomeKind
    reason: str = ""
    payload: Any | None = None

    @property
    def accepted(self) -> bool:
        return self.kind == "accepted"

    @property
    def discarded_stale(self) -> bool:
        return self.kind == "discarded_stale"


def accepted(payload: Any = None, *, reason: str = "") -> CommandResult:
    return CommandResult(kind="accepted", reason=reason, payload=payload)


def rejected(reason: str, payload: Any = None) -> CommandResult:
    return CommandResult(kind="rejected", reason=reason, payload=payload)


def discarded_stale(reason: str = "generation_mismatch") -> CommandResult:
    return CommandResult(kind="discarded_stale", reason=reason)


# ---------------------------------------------------------------------------
# Base command
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ViewerCommand(ABC):
    """Immutable command with captured context; pure data, no Qt."""

    context: ViewerContext
    # Monotonic per-source generation at creation time — delivery checks it.
    generation: int = field(default=-1)

    def __post_init__(self) -> None:
        if self.generation == -1:
            # default_generation = context.generation when not supplied
            object.__setattr__(self, "generation", self.context.generation)

    @abstractmethod
    def execute(self, controller: Any) -> CommandResult:
        """Execute against a concrete controller; returns a typed outcome."""

    def is_stale_for(self, current: ViewerContext) -> bool:
        """Stale when the context moved to another generation (S-02/S-05)."""
        return not current.is_same_generation(self.generation)


# ---------------------------------------------------------------------------
# Concrete commands used by the pilot (overlay + magnifier) and by tests
# ---------------------------------------------------------------------------


# -- Frame / navigation -----------------------------------------------------


@dataclass(frozen=True, slots=True)
class SetFrameCommand(ViewerCommand):
    frame_index: int = 0

    def execute(self, controller: Any) -> CommandResult:
        handler = getattr(controller, "set_frame", None)
        if handler is None:
            return rejected("controller_has_no_set_frame")
        return handler(self.frame_index, context=self.context, generation=self.generation)


# -- Overlay (pilot slice QH-3.1) -------------------------------------------


@dataclass(frozen=True, slots=True)
class SetResultsOverlayTextCommand(ViewerCommand):
    text: str = ""
    suppressed: bool = False

    def execute(self, controller: Any) -> CommandResult:
        if self.is_stale_for(getattr(controller, "context", self.context)):
            return discarded_stale()
        handler = getattr(controller, "set_text", None)
        if handler is None:
            return rejected("overlay_controller_has_no_set_text")
        return handler(self.text, suppressed=self.suppressed)


@dataclass(frozen=True, slots=True)
class SetResultsOverlayPositionCommand(ViewerCommand):
    x_ratio: float = 1.0
    y_ratio: float = 0.5
    custom: bool = True

    def execute(self, controller: Any) -> CommandResult:
        handler = getattr(controller, "set_position", None)
        if handler is None:
            return rejected("overlay_controller_has_no_set_position")
        return handler(self.x_ratio, self.y_ratio, custom=self.custom)


@dataclass(frozen=True, slots=True)
class ClearResultsOverlayCommand(ViewerCommand):
    def execute(self, controller: Any) -> CommandResult:
        handler = getattr(controller, "clear", None)
        if handler is None:
            return rejected("overlay_controller_has_no_clear")
        return handler()


# -- Magnifier (pilot slice QH-3.1) ------------------------------------------


@dataclass(frozen=True, slots=True)
class ConfigureMagnifierCommand(ViewerCommand):
    enabled: bool = True
    zoom: float = 3.0
    radius_px: float = 70.0
    linear_persistent: bool = False

    def execute(self, controller: Any) -> CommandResult:
        handler = getattr(controller, "configure", None)
        if handler is None:
            return rejected("magnifier_controller_has_no_configure")
        return handler(
            enabled=self.enabled,
            zoom=self.zoom,
            radius_px=self.radius_px,
            linear_persistent=self.linear_persistent,
        )


@dataclass(frozen=True, slots=True)
class SetMagnifierHeldCommand(ViewerCommand):
    held: bool = False
    cursor_scene_pos: Any | None = None

    def execute(self, controller: Any) -> CommandResult:
        if self.is_stale_for(getattr(controller, "context", self.context)):
            return discarded_stale()
        handler = getattr(controller, "set_held", None)
        if handler is None:
            return rejected("magnifier_controller_has_no_set_held")
        return handler(self.held, cursor_scene_pos=self.cursor_scene_pos)


# -- Generic typed outcome for domain-like operations ------------------------


@dataclass(frozen=True, slots=True)
class DeleteContourCommand(ViewerCommand):
    contour_id: str = ""

    def execute(self, controller: Any) -> CommandResult:
        handler = getattr(controller, "delete_contour", None) or getattr(controller, "delete", None)
        if handler is None:
            return rejected("controller_has_no_delete_contour")
        return handler(self.contour_id, context=self.context, generation=self.generation)


__all__ = [
    "CommandResult",
    "ViewerCommand",
    "accepted",
    "rejected",
    "discarded_stale",
    "SetFrameCommand",
    "SetResultsOverlayTextCommand",
    "SetResultsOverlayPositionCommand",
    "ClearResultsOverlayCommand",
    "ConfigureMagnifierCommand",
    "SetMagnifierHeldCommand",
    "DeleteContourCommand",
]
