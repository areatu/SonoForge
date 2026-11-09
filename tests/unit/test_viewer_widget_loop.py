"""Viewer transport A→B loop controls (issue 7)."""

from __future__ import annotations

import pytest

from echo_personal_tool.presentation.viewer_widget import ViewerWidget


@pytest.fixture()
def widget(qtbot):
    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    return viewer


def test_loop_controls_present_and_flat(widget):
    assert widget.loop_a_button.text() == "A"
    assert widget.loop_b_button.text() == "B"
    assert widget.loop_repeat_button.isCheckable()
    assert widget.loop_strip.isHidden()  # no bounds painted yet


def test_loop_buttons_emit_requests(widget):
    fired: list[str] = []
    widget.loop_in_requested.connect(lambda: fired.append("a"))
    widget.loop_out_requested.connect(lambda: fired.append("b"))
    widget.loop_toggle_requested.connect(lambda: fired.append("toggle"))
    widget.loop_a_button.click()
    widget.loop_b_button.click()
    widget.loop_repeat_button.click()
    assert fired == ["a", "b", "toggle"]


def test_set_loop_region_shows_strip_and_toggle(widget):
    widget.loop_strip.set_total_frames(100)
    widget.set_loop_region(10, 20, True)
    assert not widget.loop_strip.isHidden()
    assert widget.loop_strip.region() == (10, 20)
    assert widget.loop_strip.is_armed()
    assert widget.loop_repeat_button.isChecked()
    widget.set_loop_region(10, 20, False)
    assert not widget.loop_strip.isHidden()
    assert not widget.loop_repeat_button.isChecked()
    widget.clear_loop_region()
    assert widget.loop_strip.isHidden()
    assert not widget.loop_repeat_button.isChecked()


def test_loop_strip_drag_emits_bound_changes(widget):
    widget.loop_strip.set_total_frames(100)
    widget.set_loop_region(10, 20, True)
    seen: list[tuple[str, int]] = []
    widget.loop_bound_changed.connect(lambda which, frame: seen.append((which, frame)))
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    from echo_personal_tool.presentation.cine_phase_geometry import SLIDER_INSET, x_for_frame

    strip = widget.loop_strip
    x_for = lambda frame: x_for_frame(frame, 100, 0.0, float(strip.width()), SLIDER_INSET)  # noqa: E731
    press = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPointF(x_for(10), 7.0),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.loop_strip.mousePressEvent(press)
    move = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        QPointF(x_for(15), 7.0),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.loop_strip.mouseMoveEvent(move)
    assert seen == [("a", 15)]


def test_auxiliary_viewer_hides_loop_controls(qtbot):
    viewer = ViewerWidget(loop_controls=False)
    qtbot.addWidget(viewer)
    assert viewer.loop_a_button.isHidden()
    assert viewer.loop_b_button.isHidden()
    assert viewer.loop_repeat_button.isHidden()
    viewer.loop_strip.set_total_frames(100)
    viewer.set_loop_region(10, 20, True)
    assert viewer.loop_strip.isHidden()
