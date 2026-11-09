"""Viewer transport A→B loop controls (issue 7)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from echo_personal_tool.presentation.viewer_widget import ViewerWidget


@pytest.fixture()
def widget(qtbot):
    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    return viewer


def test_loop_controls_present_and_flat(widget):
    assert widget._loop_a_button.text() == "A"
    assert widget._loop_b_button.text() == "B"
    assert widget._loop_repeat_button.isCheckable()
    assert widget._loop_strip.isHidden()  # no bounds painted yet


def test_loop_buttons_emit_requests(widget):
    fired: list[str] = []
    widget.loop_in_requested.connect(lambda: fired.append("a"))
    widget.loop_out_requested.connect(lambda: fired.append("b"))
    widget.loop_toggle_requested.connect(lambda: fired.append("toggle"))
    widget._loop_a_button.click()
    widget._loop_b_button.click()
    widget._loop_repeat_button.click()
    assert fired == ["a", "b", "toggle"]


def test_set_loop_region_shows_strip_and_toggle(widget):
    widget._loop_strip.set_total_frames(100)
    widget.set_loop_region(10, 20, True)
    assert not widget._loop_strip.isHidden()
    assert widget._loop_strip.region() == (10, 20)
    assert widget._loop_strip.is_armed()
    assert widget._loop_repeat_button.isChecked()
    widget.set_loop_region(10, 20, False)
    assert not widget._loop_strip.isHidden()
    assert not widget._loop_repeat_button.isChecked()
    widget.clear_loop_region()
    assert widget._loop_strip.isHidden()
    assert not widget._loop_repeat_button.isChecked()


def test_loop_strip_drag_emits_bound_changes(widget):
    widget._loop_strip.set_total_frames(100)
    widget.set_loop_region(10, 20, True)
    seen: list[tuple[str, int]] = []
    widget.loop_bound_changed.connect(lambda which, frame: seen.append((which, frame)))
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    x_for = widget._loop_strip._x  # geometry helper, kept in lockstep with the slider
    press = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPointF(x_for(10), 7.0),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget._loop_strip.mousePressEvent(press)
    move = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        QPointF(x_for(15), 7.0),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget._loop_strip.mouseMoveEvent(move)
    assert seen == [("a", 15)]


def test_auxiliary_viewer_hides_loop_controls(qtbot):
    viewer = ViewerWidget(loop_controls=False)
    qtbot.addWidget(viewer)
    assert viewer._loop_a_button.isHidden()
    assert viewer._loop_b_button.isHidden()
    assert viewer._loop_repeat_button.isHidden()
    viewer._loop_strip.set_total_frames(100)
    viewer.set_loop_region(10, 20, True)
    assert viewer._loop_strip.isHidden()
