"""Start an M-mode caliper from the measure menu (TAPSE, IVC expiration/inspiration).

The three menu entries share one path: the M-mode calibration must be ready
(the saved calibration of the open instance, the DICOM/heuristic one, or the
interactive panel), then the caliper is armed with its fixed label so the
measurement lands in the report under the right row.

The window keeps its status bar and hint strip; this module owns the sequence,
which keeps ``MainWindow`` at its method/line ceiling (issue 474) and makes the rule
testable without a window.  No Qt import on purpose.
"""

from __future__ import annotations

from typing import Protocol

from echo_personal_tool.domain.translation import tr


class CaliperViewer(Protocol):
    """The viewer slice an M-mode caliper needs."""

    def start_linear_caliper_for(self, label: str) -> bool: ...


class ModeCaliperHost(Protocol):
    """The window slice an M-mode caliper needs."""

    @property
    def _viewer(self) -> CaliperViewer: ...

    def _ensure_mmode_ready_for_tapse(self) -> bool: ...

    def _show_status(self, message: str) -> None: ...

    def _show_hint(self, message: str) -> None: ...


def start_mode_caliper(host: ModeCaliperHost, label: str, menu_key: str) -> None:
    """Arm the M-mode caliper *label* and name it in the status bar."""
    if _armed(host, label):
        host._show_status(tr("status.linear_caliper_tool", label=tr(menu_key)))


def start_mode_caliper_hint(host: ModeCaliperHost, label: str, hint_key: str) -> None:
    """Arm the M-mode caliper *label* and prompt for it in the hint strip."""
    if _armed(host, label):
        host._show_hint(tr(hint_key))


def _armed(host: ModeCaliperHost, label: str) -> bool:
    """``True`` when the caliper is armed; otherwise the reason is reported."""
    if not host._ensure_mmode_ready_for_tapse():
        return False
    if host._viewer.start_linear_caliper_for(label):
        return True
    host._show_status(tr("status.load_first_frame"))
    return False
