"""WorkerAdapter — QH-3 worker lifecycle bridge (G3, issue 185, slice 3).

Spec §7.1 last row: owns the lifecycle of one task plus its result-delivery
token/generation.  It never mutates Qt/UI from the background thread; the
viewer facade delivers results only when `generation` still matches the current
ViewerContext (late callbacks are discarded, S-05, A-05).

This is intentionally tiny — the heavy lifting stays in application/workers.
The bridge just tags each spawn with (context, generation, revision) and
guards delivery.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject, Signal

from echo_personal_tool.presentation.viewer.commands import CommandResult, discarded_stale
from echo_personal_tool.presentation.viewer.context import ViewerContext


@dataclass(frozen=True, slots=True)
class WorkerToken:
    """Delivery token for one worker execution."""

    context: ViewerContext
    generation: int
    revision: int = 0
    operation: str = ""  # "decode" | "onnx" | "ste" | ...


class WorkerBridge(QObject):
    """Guards worker callbacks with generation checks.

    Usage:
        bridge = WorkerBridge(parent=viewer)
        token = bridge.spawn(ctx, operation="onnx")
        worker.finished.connect(lambda result: bridge.deliver(token, result, handler))
    """

    expired_discarded = Signal(object)  # WorkerToken that was too late

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._active: dict[int, WorkerToken] = {}  # id -> token
        self._next_id = 0
        self._current_context: ViewerContext | None = None
        self._cancelled: set[int] = set()

    def set_context(self, ctx: ViewerContext) -> None:
        self._current_context = ctx

    def spawn(self, ctx: ViewerContext, *, operation: str = "", revision: int = 0) -> WorkerToken:
        token = WorkerToken(context=ctx, generation=ctx.generation, revision=revision, operation=operation)
        tid = self._next_id
        self._next_id += 1
        self._active[tid] = token
        # Store id on the token holder for cancellation
        # Callers keep WorkerToken, bridge keeps tid mapping
        return token

    def cancel_all_for_generation(self, generation: int) -> int:
        """Cancel outstanding tokens for an old generation (tab close)."""
        to_remove = [tid for tid, tok in self._active.items() if tok.generation == generation]
        for tid in to_remove:
            self._active.pop(tid, None)
            self._cancelled.add(tid)
        return len(to_remove)

    def deliver(self, token: WorkerToken, result: Any, handler: Callable[[Any], CommandResult]) -> CommandResult:
        """Deliver only when the token's generation is still current."""
        if self._current_context is None:
            # No context yet — discard rather than guess
            self.expired_discarded.emit(token)
            return discarded_stale("no_current_context")
        if not self._current_context.is_same_generation(token.generation):
            self.expired_discarded.emit(token)
            return discarded_stale(f"stale_generation:{token.generation}!={self._current_context.generation}")
        # Remove from active (one-shot delivery)
        for tid, tok in list(self._active.items()):
            if tok == token:
                self._active.pop(tid, None)
                break
        return handler(result)

    def is_stale(self, token: WorkerToken) -> bool:
        if self._current_context is None:
            return True
        return not self._current_context.is_same_generation(token.generation)

    def active_count(self) -> int:
        return len(self._active)

    def dispose(self) -> None:
        self._active.clear()
        self._cancelled.clear()
        self._current_context = None
        try:
            self.expired_discarded.disconnect()
        except (RuntimeError, TypeError):
            pass


__all__ = ["WorkerBridge", "WorkerToken"]
