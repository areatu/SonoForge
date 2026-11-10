"""A→B cine loop wiring (issue 7) for the primary viewer.

Extracted from MainWindow: wires the viewer's «A»/«B»/«↻» transport and the
region strip to the loop state of the StateManager, and announces what
happened in the status bar.  Lives as a child of the window (kept alive by the
Qt parent–child link, no extra attribute on MainWindow).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject

from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.presentation.loop_controls import LoopControls

if TYPE_CHECKING:
    from echo_personal_tool.application.app_controller import AppController
    from echo_personal_tool.presentation.viewer_widget import ViewerWidget

__all__ = ["LoopCoordinator"]


class LoopCoordinator(QObject):
    """Wires the viewer's loop transport to the state manager."""

    def __init__(
        self,
        viewer: ViewerWidget,
        controller: AppController,
        show_status: Callable[[str], None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._viewer = viewer
        self._controller = controller
        self._show_status = show_status
        self._controls = viewer.findChild(LoopControls)
        viewer.loop_in_requested.connect(self._on_loop_in_requested)
        viewer.loop_out_requested.connect(self._on_loop_out_requested)
        viewer.loop_toggle_requested.connect(self._on_loop_toggle_requested)
        viewer.loop_bound_changed.connect(self._on_loop_bound_changed)
        self.sync()

    def sync(self) -> None:
        """Push the manager's loop region onto the strip and the toggle."""
        loop_in, loop_out, armed = self._controller.state_manager.loop_state()
        if self._controls is not None:
            self._controls.set_region(loop_in, loop_out, armed)

    def _pin_bound(self, which: str) -> None:
        frame = self._controller.state_manager.snapshot.current_frame_index
        bounds = self._controller.state_manager.set_loop_bound(which, frame)
        self.sync()
        if bounds is not None:
            self._show_status(tr("status.loop_bounds", a=bounds[0] + 1, b=bounds[1] + 1))

    def _on_loop_in_requested(self) -> None:
        self._pin_bound("a")

    def _on_loop_out_requested(self) -> None:
        self._pin_bound("b")

    def _on_loop_bound_changed(self, which: str, frame: int) -> None:
        self._controller.state_manager.set_loop_bound(which, frame)
        self.sync()

    def _on_loop_toggle_requested(self) -> None:
        armed = self._controller.state_manager.toggle_loop()
        self.sync()
        loop_in, loop_out, _ = self._controller.state_manager.loop_state()
        if armed and loop_in is not None and loop_out is not None:
            self._show_status(tr("status.loop_armed", a=loop_in + 1, b=loop_out + 1))
        elif loop_in is None:
            self._show_status(tr("status.loop_need_bounds"))
        else:
            self._show_status(tr("status.loop_disarmed"))
