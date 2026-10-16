"""Tests for SystemBar widget."""

from __future__ import annotations

import pytest

from echo_personal_tool.presentation.system_bar import SystemBar

pytestmark = pytest.mark.gui


def test_system_bar_emits_caliper_requested(qtbot) -> None:
    bar = SystemBar()
    qtbot.addWidget(bar)
    caliper_btn = bar._btn_caliper
    with qtbot.waitSignal(bar.caliper_requested, timeout=1000):
        caliper_btn.click()


def test_system_bar_study_context_and_status(qtbot) -> None:
    bar = SystemBar()
    qtbot.addWidget(bar)
    bar.set_study_context("A4C cine", "US")
    bar.set_status_message("Frame loaded")
    assert bar._study_label.text() == "A4C cine"
    assert "Frame" in bar._status_label.text()
    assert bar._actions_widget is not None


def test_system_bar_emits_settings_requested(qtbot) -> None:
    bar = SystemBar()
    qtbot.addWidget(bar)
    with qtbot.waitSignal(bar.settings_requested, timeout=1000):
        bar._btn_settings.click()


def test_system_bar_long_status_elides_with_tooltip(qtbot) -> None:
    bar = SystemBar()
    qtbot.addWidget(bar)
    bar.resize(720, 48)
    bar.show()
    qtbot.waitExposed(bar)

    long_message = (
        "Doppler калибровка 1/3: клик — первый угол окна спектра (не весь кадр), "
        "затем противоположный угол, baseline и шкала скорости на краю спектра"
    )
    bar.set_status_message(long_message)
    qtbot.wait(50)

    assert len(bar._status_label.text()) < len(long_message)
    assert bar._status_label.toolTip() == long_message
    assert bar._actions_widget.geometry().right() <= bar.width()


def test_system_bar_emits_references_requested(qtbot) -> None:
    bar = SystemBar()
    qtbot.addWidget(bar)
    with qtbot.waitSignal(bar.references_requested, timeout=1000):
        bar._btn_references.click()


def test_system_bar_window_controls_visibility_and_caption_buttons(qtbot) -> None:
    from echo_personal_tool.presentation.window_chrome import Zone

    bar = SystemBar()
    qtbot.addWidget(bar)
    buttons = bar.caption_buttons()
    assert set(buttons) == {Zone.MIN, Zone.MAX, Zone.CLOSE}
    assert bar.window_controls_visible() is True
    bar.set_window_controls_visible(False)
    assert bar.window_controls_visible() is False
    bar.set_window_controls_visible(True)
    assert bar.window_controls_visible() is True


def test_system_bar_caption_drag_calls_start_system_move(qtbot, monkeypatch) -> None:
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QMainWindow

    host = QMainWindow()
    bar = SystemBar(host)
    host.setCentralWidget(bar)
    qtbot.addWidget(host)
    host.resize(800, 48)
    host.show()

    moved: list[object] = []

    class _FakeWindowHandle:
        def startSystemMove(self) -> bool:  # noqa: N802
            moved.append("startSystemMove")
            return True

    monkeypatch.setattr(host, "windowHandle", lambda: _FakeWindowHandle())
    press_pos = QPointF(400.0, 20.0)
    press_ev = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        press_pos,
        host.mapToGlobal(press_pos.toPoint()).toPointF(),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    bar.mousePressEvent(press_ev)
    move_pos = QPointF(420.0, 24.0)
    move_ev = QMouseEvent(
        QEvent.Type.MouseMove,
        move_pos,
        host.mapToGlobal(move_pos.toPoint()).toPointF(),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    bar.mouseMoveEvent(move_ev)
    assert moved == ["startSystemMove"]


def test_system_bar_top_border_press_calls_start_system_resize(qtbot, monkeypatch) -> None:
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QMainWindow

    host = QMainWindow()
    bar = SystemBar(host)
    host.setCentralWidget(bar)
    qtbot.addWidget(host)
    host.resize(800, 48)
    host.show()

    resized: list[Qt.Edge] = []

    class _FakeWindowHandle:
        def startSystemResize(self, edges: Qt.Edge) -> bool:  # noqa: N802
            resized.append(edges)
            return True

    monkeypatch.setattr(host, "windowHandle", lambda: _FakeWindowHandle())
    pos = QPointF(400.0, 2.0)  # y=2 is inside the 6 px top resize border
    ev = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        pos,
        host.mapToGlobal(pos.toPoint()).toPointF(),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    bar.mousePressEvent(ev)
    assert resized == [Qt.Edge.TopEdge]


def test_system_bar_localizes_send_to_server_and_maximize_tooltips(qtbot) -> None:
    from echo_personal_tool.infrastructure.i18n import get_language, set_language, tr

    prev = get_language()
    try:
        set_language("ru")
        bar = SystemBar()
        qtbot.addWidget(bar)
        assert bar._btn_send_server.text() == tr("system_bar.send_to_server")
        bar.update_maximize_button(False)
        assert bar._btn_maximize.toolTip() == tr("system_bar.maximize")
        bar.update_maximize_button(True)
        assert bar._btn_maximize.toolTip() == tr("system_bar.restore")
    finally:
        set_language(prev)
