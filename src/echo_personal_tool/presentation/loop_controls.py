"""A→B cine loop controls (issue 7).

Collaborator extracted from :class:`ViewerWidget`: the «A»/«B» bound buttons,
the «↻» arm toggle and the region strip above the frame slider.  The viewer
creates one per instance (auxiliary viewers get a hidden, inert copy) and keeps
no direct reference — call sites reach it through ``findChild(LoopControls)``,
so the ownership of the widgets lives here and the god class does not grow.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QSignalBlocker
from PySide6.QtWidgets import QPushButton, QWidget

from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.presentation import dark_theme
from echo_personal_tool.presentation.loop_region_strip import LoopRegionStrip

__all__ = ["LoopControls", "attach_loop_controls"]


class LoopControls(QObject):
    """The «A»/«B»/«↻» buttons and the region strip of one viewer.

    ``enabled=False`` (the auxiliary panes) hides the buttons and makes
    :meth:`set_region` a no-op, so the strip stays hidden and playback wraps
    at the clip end there.
    """

    def __init__(
        self,
        viewer: QWidget,
        *,
        enabled: bool,
        on_in: Callable[[], None],
        on_out: Callable[[], None],
        on_toggle: Callable[[], None],
        on_bound: Callable[[str, int], None],
        on_frame_selected: Callable[[int], None],
    ) -> None:
        super().__init__(viewer)
        self.setObjectName("loopControls")
        self.enabled = bool(enabled)
        self.strip = LoopRegionStrip(viewer)
        self.strip.hide()
        self.strip.loop_bound_changed.connect(on_bound)
        self.strip.frame_selected.connect(on_frame_selected)
        self.a_button = QPushButton("A", viewer)
        self.b_button = QPushButton("B", viewer)
        self.repeat_button = QPushButton("↻", viewer)
        self.repeat_button.setCheckable(True)
        font = self.a_button.font()
        font.setBold(True)
        for button in self.buttons():
            button.setFixedSize(32, 32)
            button.setFlat(True)
            button.setFont(font)
        self.a_button.clicked.connect(on_in)
        self.b_button.clicked.connect(on_out)
        self.repeat_button.clicked.connect(on_toggle)
        self.reload_text()
        if not self.enabled:
            self.a_button.hide()
            self.b_button.hide()
            self.repeat_button.hide()

    def buttons(self) -> tuple[QPushButton, QPushButton, QPushButton]:
        """The three transport buttons, in display order."""
        return (self.a_button, self.b_button, self.repeat_button)

    def reload_text(self) -> None:
        """Re-translate tooltips and repaint the toggle's checked state."""
        for button, key in (
            (self.a_button, "viewer.loop_a_tip"),
            (self.b_button, "viewer.loop_b_tip"),
            (self.repeat_button, "viewer.loop_repeat_tip"),
        ):
            button.setToolTip(tr(key))
            button.setAccessibleName(tr(key))
        self.repeat_button.setStyleSheet(
            f"QPushButton:checked {{ background: {dark_theme.get_theme_tokens()['accent.tab']}; "
            f"color: {dark_theme.get_theme_tokens()['accent.on']}; border: none; border-radius: 4px; }}"
        )

    def set_region(self, loop_in: int | None, loop_out: int | None, armed: bool) -> None:
        """Show/hide the A→B strip and reflect the armed state on the toggle."""
        if not self.enabled:
            return
        self.strip.set_region(loop_in, loop_out, armed)
        with QSignalBlocker(self.repeat_button):
            self.repeat_button.setChecked(bool(armed))

    def clear(self) -> None:
        self.set_region(None, None, False)

    def set_total_frames(self, total: int) -> None:
        self.strip.set_total_frames(total)

    def set_current_frame(self, frame: int) -> None:
        self.strip.set_current_frame(frame)


def attach_loop_controls(viewer: Any, *, enabled: bool) -> LoopControls:
    """Create the controls for ``viewer`` and wire its loop signals to them."""
    return LoopControls(
        viewer,
        enabled=enabled,
        on_in=viewer.loop_in_requested.emit,
        on_out=viewer.loop_out_requested.emit,
        on_toggle=viewer.loop_toggle_requested.emit,
        on_bound=viewer.loop_bound_changed.emit,
        on_frame_selected=viewer._on_timeline_changed,
    )
