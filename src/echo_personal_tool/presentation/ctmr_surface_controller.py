"""CT/MR stack surface controller (spec 557, spec 474 decomposition).

A slice of ``MainWindow`` moved into its own module: everything that decides
whether the image surface shows the classic CT/MR multi-page stack viewer
instead of the ultrasound ``ViewerWidget`` (spec 557), and what happens when it
does — the stack viewer widget itself, the ``CtMrIndex`` that backs it, the
surface-switching logic, and the visibility of the clip gallery / tool panel /
tool rail that only apply to ultrasound content.

The window keeps the widgets; this controller owns the CT/MR surface state and
the apply/show/hide routing.  Widget access goes through a protocol so the
controller does not import ``MainWindow`` (no circular dependency) and tests
can drive the flow with a lightweight double.
"""

from __future__ import annotations

import logging
from typing import Protocol

from PySide6.QtWidgets import QStackedWidget, QWidget

from echo_personal_tool.application.ctmr_study import build_ctmr_index
from echo_personal_tool.application.tab_session import TabSessionManager
from echo_personal_tool.domain.models.ctmr_stack import CtMrIndex
from echo_personal_tool.presentation.ctmr_stack_viewer import CtMrStackViewer

logger = logging.getLogger(__name__)


class CtMrSurfaceWindow(Protocol):
    """Window surface the CT/MR surface controller drives (implemented by MainWindow).

    The names are the window's own: the controller is a slice of the window in
    a separate file, not a new abstraction layer on top of it. Only what the
    moved code really touches is listed here.
    """

    _viewer_stack: QStackedWidget
    _viewer: QWidget
    _gallery: QWidget
    _tool_panel: QWidget
    _tool_rail: QWidget | None
    _content_widget: QWidget

    def _rebuild_layout(self) -> None: ...

    @property
    def _tabs(self) -> TabSessionManager: ...


class CtMrSurfaceController:
    """Owns the CT/MR stack viewer surface and its routing (spec 557).

    Created by ``MainWindow`` once the viewer stack exists; the controller
    creates the ``CtMrStackViewer`` and adds it to the stack, then drives
    which widget the stack shows based on whether the active tab is a classic
    CT/MR study (stack viewer) or an ultrasound study (``ViewerWidget``).
    """

    def __init__(self, window: CtMrSurfaceWindow) -> None:
        # Widget references are read lazily from the window: MainWindow creates
        # this controller before the widgets it drives exist, so they must not
        # be captured in __init__.
        self._window = window
        self._viewer: CtMrStackViewer | None = None
        self._active = False
        self._index: CtMrIndex | None = None

    def create_viewer(self) -> CtMrStackViewer:
        """Create the stack viewer widget and mount it in the viewer stack."""
        viewer = CtMrStackViewer(self._window._content_widget)
        viewer.hide()
        self._window._viewer_stack.addWidget(viewer)
        self._viewer = viewer
        return viewer

    @property
    def is_active(self) -> bool:
        """True while the image surface shows the CT/MR stack viewer."""
        return self._active

    def apply(self, studies: list) -> None:
        """Route a loaded study set to the CT/MR stack viewer when it is one.

        A classic CT/MR multi-file study is presented as one multi-page stack
        (spec 557): the stack viewer takes the image surface and the thumbnail
        gallery / tool panel are hidden, so the slices do not sit in the gallery
        as if they were ultrasound clips.  Anything without a usable CT/MR
        stack keeps the ordinary ultrasound surface.
        """
        index = build_ctmr_index(studies) if studies else None
        if index is not None:
            if not self._active or self._index is not index:
                self._index = index
                self._active = True
                assert self._viewer is not None
                self._viewer.set_index(index)
                self._window._viewer_stack.setCurrentWidget(self._viewer)
            self._window._viewer.hide()
            self._window._gallery.hide()
            self._window._tool_panel.hide()
            tool_rail = self._window._tool_rail
            if tool_rail is not None:
                tool_rail.hide()
            return
        if self._active:
            self._active = False
            self._index = None
            assert self._viewer is not None
            self._viewer.clear()
            self._window._viewer_stack.setCurrentWidget(self._window._viewer)
            self._window._viewer.show()
            self._window._rebuild_layout()

    def sync(self) -> None:
        """Re-evaluate the CT/MR surface for the currently active tab."""
        tab = self._window._tabs.active
        studies = list(tab.studies) if tab is not None else []
        self.apply(studies)

    def apply_layout_visibility(self) -> bool:
        """Show the stack viewer and hide ultrasound surfaces when active.

        Returns ``True`` when the CT/MR surface took over (the caller should
        stop configuring the ultrasound layout); ``False`` to continue with
        the normal layout.
        """
        if not self._active or self._viewer is None:
            return False
        self._window._viewer_stack.setCurrentWidget(self._viewer)
        self._window._viewer.hide()
        self._window._gallery.hide()
        self._window._tool_panel.hide()
        tool_rail = self._window._tool_rail
        if tool_rail is not None:
            tool_rail.hide()
        return True

    def show_stack_viewer(self) -> None:
        """Show the stack viewer as the current surface (never the welcome page).

        A CT/MR stack is a real content surface, so the welcome page is never
        selected while the stack viewer owns the image surface.
        """
        if self._active and self._viewer is not None:
            self._window._viewer_stack.setCurrentWidget(self._viewer)
