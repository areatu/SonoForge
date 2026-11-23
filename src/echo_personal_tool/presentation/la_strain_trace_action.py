"""Start the LA strain roof-arc trace from the measure menu (plan А.6).

The trace is the LA roof arc (chamber ``LA``): the physician draws the arc
across the left-atrial roof — the tracker follows it through the cycle and the
worker reports reservoir/conduit/booster strain. An ED or ES arc both work
(the worker re-zeros the curve at the tracked ED frame).

Mirrors :mod:`echo_personal_tool.presentation.free_wall_trace_action`: the
window keeps its status bar; this module owns the sequence, which keeps
``MainWindow`` at its line ceiling (issue 474) and makes the rule testable
without a window. No Qt import on purpose.
"""

from __future__ import annotations

from typing import Protocol

from echo_personal_tool.domain.translation import tr
from echo_personal_tool.keyboard_shortcuts import shortcut_label


class _TraceViewer(Protocol):
    """The viewer slice the trace start needs."""

    def start_contour(self, *, chamber: str, view: str) -> bool: ...


class LaStrainTraceHost(Protocol):
    """The window slice the trace start needs."""

    @property
    def _viewer(self) -> _TraceViewer: ...

    def _show_status(self, message: str) -> None: ...


def start_la_strain_trace(host: LaStrainTraceHost) -> None:
    """Start the LA roof-arc trace and name it in the status bar."""
    if host._viewer.start_contour(chamber="LA", view="A4C"):
        host._show_status(tr("status.la_strain_tool", finish_key=shortcut_label("finish_tool")))
        return
    host._show_status(f"Load a frame first or cancel the active tool ({shortcut_label('cancel_tool')})")
