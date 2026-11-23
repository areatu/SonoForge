"""Unit tests for the RV free-wall trace menu action (plan А.7, issue #645)."""

from __future__ import annotations

from echo_personal_tool.domain.translation import tr
from echo_personal_tool.keyboard_shortcuts import shortcut_label
from echo_personal_tool.presentation.free_wall_trace_action import start_rv_free_wall_trace


class _FakeViewer:
    def __init__(self, *, starts: bool) -> None:
        self.starts = starts
        self.calls: list[dict[str, str]] = []

    def start_contour(self, *, chamber: str, view: str) -> bool:
        self.calls.append({"chamber": chamber, "view": view})
        return self.starts


class _FakeWindow:
    """The slice of ``MainWindow`` the action drives, without a window."""

    def __init__(self, *, starts: bool = True) -> None:
        self._viewer = _FakeViewer(starts=starts)
        self.status: list[str] = []

    def _show_status(self, message: str) -> None:
        self.status.append(message)


def test_the_trace_starts_on_the_free_wall_chamber_of_a4c() -> None:
    window = _FakeWindow()

    start_rv_free_wall_trace(window)

    assert window._viewer.calls == [{"chamber": "RV_FW", "view": "A4C"}]
    assert window.status == [tr("status.rv_free_wall_tool", finish_key=shortcut_label("finish_tool"))]
    assert len(window.status[0]) > 0


def test_a_frame_that_cannot_start_explains_the_missing_frame() -> None:
    window = _FakeWindow(starts=False)

    start_rv_free_wall_trace(window)

    assert window._viewer.calls == [{"chamber": "RV_FW", "view": "A4C"}]
    assert "Load a frame first" in window.status[0]
