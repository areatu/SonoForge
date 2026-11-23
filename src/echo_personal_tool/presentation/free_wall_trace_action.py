"""Start the RV free-wall strain trace from the measure menu (plan А.7).

The trace is a material line (chamber ``RV_FW``): the physician draws the free
wall — from the tricuspid-annulus corner toward the apex — on the phase they
parked on. An ED trace anchors the strain reference directly; an ES trace
still works (the worker re-zeros the curve at the tracked ED frame).

The window keeps its status bar; this module owns the sequence, which keeps
``MainWindow`` at its line ceiling (issue 474) and makes the rule testable
without a window. No Qt import on purpose.
"""

from __future__ import annotations

from typing import Protocol

from echo_personal_tool.domain.models.contour import RV_FREE_WALL_CHAMBER
from echo_personal_tool.domain.translation import tr
from echo_personal_tool.keyboard_shortcuts import shortcut_label


class _TraceViewer(Protocol):
    """The viewer slice the trace start needs."""

    def start_contour(self, *, chamber: str, view: str) -> bool: ...


class FreeWallTraceHost(Protocol):
    """The window slice the trace start needs."""

    @property
    def _viewer(self) -> _TraceViewer: ...

    def _show_status(self, message: str) -> None: ...


def start_rv_free_wall_trace(host: FreeWallTraceHost) -> None:
    """Start the freehand wall trace and name it in the status bar."""
    if host._viewer.start_contour(chamber=RV_FREE_WALL_CHAMBER, view="A4C"):
        host._show_status(tr("status.rv_free_wall_tool", finish_key=shortcut_label("finish_tool")))
        return
    host._show_status(f"Load a frame first or cancel the active tool ({shortcut_label('cancel_tool')})")
