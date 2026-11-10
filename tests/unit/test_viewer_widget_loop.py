"""Viewer transport A→B loop controls (issue 7)."""

from __future__ import annotations

import pytest

from echo_personal_tool.presentation.loop_controls import LoopControls
from echo_personal_tool.presentation.viewer_widget import ViewerWidget


@pytest.fixture()
def widget(qtbot):
    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    return viewer


def controls(widget: ViewerWidget) -> LoopControls:
    found = widget.findChild(LoopControls)
    assert found is not None
    return found


def test_loop_controls_present_and_flat(widget):
    loop = controls(widget)
    assert loop.a_button.text() == "A"
    assert loop.b_button.text() == "B"
    assert loop.repeat_button.isCheckable()
    assert loop.strip.isHidden()  # no bounds painted yet


def test_loop_buttons_emit_requests(widget):
    fired: list[str] = []
    widget.loop_in_requested.connect(lambda: fired.append("a"))
    widget.loop_out_requested.connect(lambda: fired.append("b"))
    widget.loop_toggle_requested.connect(lambda: fired.append("toggle"))
    loop = controls(widget)
    loop.a_button.click()
    loop.b_button.click()
    loop.repeat_button.click()
    assert fired == ["a", "b", "toggle"]


def test_set_loop_region_shows_strip_and_toggle(widget):
    loop = controls(widget)
    loop.strip.set_total_frames(100)
    loop.set_region(10, 20, True)
    assert not loop.strip.isHidden()
    assert loop.strip.region() == (10, 20)
    assert loop.strip.is_armed()
    assert loop.repeat_button.isChecked()
    loop.set_region(10, 20, False)
    assert not loop.strip.isHidden()
    assert not loop.repeat_button.isChecked()
    loop.clear()
    assert loop.strip.isHidden()
    assert not loop.repeat_button.isChecked()


def test_loop_strip_drag_emits_bound_changes(widget):
    loop = controls(widget)
    loop.strip.set_total_frames(100)
    loop.set_region(10, 20, True)
    seen: list[tuple[str, int]] = []
    widget.loop_bound_changed.connect(lambda which, frame: seen.append((which, frame)))
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    from echo_personal_tool.presentation.cine_phase_geometry import SLIDER_INSET, x_for_frame

    strip = loop.strip
    x_for = lambda frame: x_for_frame(frame, 100, 0.0, float(strip.width()), SLIDER_INSET)  # noqa: E731
    press = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPointF(x_for(10), 7.0),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    strip.mousePressEvent(press)
    move = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        QPointF(x_for(15), 7.0),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    strip.mouseMoveEvent(move)
    assert seen == [("a", 15)]


def test_auxiliary_viewer_hides_loop_controls(qtbot):
    viewer = ViewerWidget(loop_controls=False)
    qtbot.addWidget(viewer)
    loop = controls(viewer)
    assert loop.a_button.isHidden()
    assert loop.b_button.isHidden()
    assert loop.repeat_button.isHidden()
    loop.strip.set_total_frames(100)
    loop.set_region(10, 20, True)
    assert loop.strip.isHidden()
