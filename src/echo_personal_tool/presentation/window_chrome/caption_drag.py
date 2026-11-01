"""System move, system resize and double-click maximize for a caption row.

UI-1 PR-2 (spec §4.3, UD-13). The behaviour is shared by the window title bar
and — from UI-1 PR-3 — by the patient row: both are draggable empty space of the
same custom caption, and both let the *window manager* move and resize the
window (``QWindow.startSystemMove()`` / ``startSystemResize()``), so Aero Snap,
``Win+стрелки`` and the Linux window managers keep working.

The mixin only uses zones from :mod:`hit_test`: a press inside the 6 px border
starts a system resize, a press in the caption starts a system move (with the
deterministic fallback of :func:`start_system_move` for platforms where the
window manager refuses the gesture), and a double click toggles the maximized
state through the host's hook.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, Qt

from echo_personal_tool.presentation.window_chrome.hit_test import (
    DEFAULT_RESIZE_BORDER_PX,
    RESIZE_ZONES,
    Zone,
    collect_caption_geometry,
    hit_test,
    start_system_move,
    start_system_resize,
    zone_to_qt_edges,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from PySide6.QtWidgets import QWidget


class CaptionDragMixin:
    """Mouse behaviour of a caption row inside the frameless window.

    Hosts override :meth:`caption_buttons` — the ``Zone -> QWidget`` map of the
    window controls they own — and :meth:`_caption_double_clicked`; the drag and
    resize gestures themselves need no host code.
    """

    #: A row that is *below* the real title bar (the patient line with the file
    #: name) is not a caption for the user: a press there must not move the
    #: window.  Only WindowTitleBar keeps this on; see SystemBar.
    CAPTION_MOVE_ENABLED = True

    #: Double-click on empty caption space: maximize/restore (spec §4.3).
    def _caption_double_clicked(self) -> None:
        raise NotImplementedError

    def caption_buttons(self) -> Mapping[Zone, QWidget | None]:
        """Window-control buttons of this row (``Zone.MIN`` / ``MAX`` / ``CLOSE``)."""
        return {}

    # ----- geometry --------------------------------------------------------

    def _caption_hit_test(self, local_pos: QPoint) -> Zone:
        """Classify a point of this row using the window's chrome geometry."""
        window = self.window()
        local_in_win = self.mapTo(window, local_pos)
        window_hit_test = getattr(window, "chrome_hit_test", None)
        if callable(window_hit_test):
            return window_hit_test(local_in_win)
        caption_rect, buttons, interactive = collect_caption_geometry(
            window,
            [self],
            button_widgets=self.caption_buttons(),
        )
        return hit_test(
            local_in_win,
            window.size(),
            border=DEFAULT_RESIZE_BORDER_PX,
            caption=caption_rect,
            buttons=buttons,
            interactive=interactive,
            maximized=bool(window.isMaximized() or getattr(window, "_user_maximized", False)),
        )

    def _native_frame_active(self) -> bool:
        """True when the OS draws the frame, so the custom gestures must stand down."""
        window = self.window()
        checker = getattr(window, "is_native_window_frame", None)
        return bool(callable(checker) and checker())

    # ----- mouse -----------------------------------------------------------

    def mousePressEvent(self, event) -> None:  # noqa: ANN001 - QMouseEvent
        if event.button() != Qt.MouseButton.LeftButton or self._native_frame_active():
            super().mousePressEvent(event)  # type: ignore[misc]  # mypy does not check this file (outside tool.mypy.files)
            return
        window = self.window()
        zone = self._caption_hit_test(event.position().toPoint())
        if zone in RESIZE_ZONES:
            start_system_resize(window, zone_to_qt_edges(zone))
            return
        # Only *caption* space arms a move.  Previously every left press on a
        # row armed one — including a press on the file name of the patient
        # line, which the window's own hit test classifies as CLIENT.  Dragging
        # that area (to select/copy a name, or just to rest the pointer) used to
        # drag the whole window away.
        if zone is not Zone.CAPTION or not self.CAPTION_MOVE_ENABLED:
            self._caption_drag_origin = None
            self._caption_drag_offset = None
            self._caption_system_move_active = False
            super().mousePressEvent(event)  # type: ignore[misc]  # mypy does not check this file (outside tool.mypy.files)
            return
        global_pos = event.globalPosition().toPoint()
        self._caption_drag_origin = global_pos
        self._caption_drag_offset = global_pos - window.pos()
        self._caption_system_move_active = False

    def mouseMoveEvent(self, event) -> None:  # noqa: ANN001 - QMouseEvent
        drag_offset = getattr(self, "_caption_drag_offset", None)
        if drag_offset is None or not event.buttons() & Qt.MouseButton.LeftButton:
            super().mouseMoveEvent(event)  # type: ignore[misc]  # mypy does not check this file (outside tool.mypy.files)
            return
        if self._native_frame_active() or getattr(self, "_caption_system_move_active", False):
            return
        # ``start_system_move`` either hands the drag to the window manager (once)
        # or performs the deterministic manual move of its fallback path; a
        # maximized window is restored under the cursor on the way.
        window = self.window()
        global_pos = event.globalPosition().toPoint()
        self._caption_system_move_active = start_system_move(
            window,
            global_pos=global_pos,
            drag_offset=self._caption_drag_offset,
        )
        if not self._caption_system_move_active:
            self._caption_drag_offset = global_pos - window.pos()

    def mouseReleaseEvent(self, event) -> None:  # noqa: ANN001 - QMouseEvent
        self._caption_drag_origin = None
        self._caption_drag_offset = None
        self._caption_system_move_active = False
        super().mouseReleaseEvent(event)  # type: ignore[misc]  # mypy does not check this file (outside tool.mypy.files)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: ANN001 - QMouseEvent
        if event.button() != Qt.MouseButton.LeftButton or self._native_frame_active() or not self.CAPTION_MOVE_ENABLED:
            super().mouseDoubleClickEvent(event)  # type: ignore[misc]  # mypy does not check this file (outside tool.mypy.files)
            return
        self._caption_double_clicked()
