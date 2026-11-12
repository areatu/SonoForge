"""Which viewer context the 2.0 measurement panel shows (§4.2).

``MainWindow`` owns the panel, the M-mode flag and the viewer, so the decision
is a pure function of those three inputs: the panel needs a *context* string
(``2d`` / ``doppler`` / ``m``) and, for Doppler, the resolved spectral mode.
Keeping the rule here means the calibration wiring, the M-mode toggle and the
properties update all call one function instead of growing the window class.
"""

from __future__ import annotations

from typing import Any


def sync_tool_panel_context(panel: Any, *, mmode_active: bool, doppler: Any) -> None:
    """Tell the 2.0 measurement panel which viewer context it is in.

    The legacy panel has no contexts at all, so anything without ``is_v2`` is
    left alone; M-mode wins over Doppler because its trace owns the frame.
    """
    if panel is None or not getattr(panel, "is_v2", False):
        return
    if mmode_active:
        panel.set_view_context("m", defer=True)
        return
    context = "doppler" if doppler.is_context() else "2d"
    mode = ""
    if context == "doppler":
        resolved = doppler.resolved_mode
        if callable(resolved):
            mode = resolved()
    panel.set_view_context(context, mode, defer=True)
