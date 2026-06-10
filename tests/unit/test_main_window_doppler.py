"""MainWindow Doppler view integration tests."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.presentation.main_window import MainWindow


def _make_window(qtbot) -> MainWindow:
    window = MainWindow(controller=AppController())
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    return window


def test_set_view_mode_switches_to_doppler_and_shows_current_frame(qtbot) -> None:
    window = _make_window(qtbot)
    frame = np.full((8, 6), 17, dtype=np.uint8)
    window._viewer.show_frame(frame)

    window.set_view_mode("doppler")

    assert window._view_mode == "doppler"
    assert window._view_stack.currentWidget() is window._doppler_widget
    assert window._doppler_widget._image_item.image is not None
    assert window._doppler_widget._image_item.image.shape == (8, 6)
    assert window.statusBar().currentMessage() == "Doppler view active"


def test_frame_loaded_routes_to_active_view(qtbot) -> None:
    window = _make_window(qtbot)

    frame_2d = np.full((4, 5), 3, dtype=np.uint8)
    window._on_frame_loaded(frame_2d)
    assert window._viewer._current_frame is not None
    assert window._viewer._current_frame.shape == (4, 5)

    doppler_frame = np.full((3, 7), 9, dtype=np.uint8)
    window.set_view_mode("doppler")
    window._on_frame_loaded(doppler_frame)
    assert window._doppler_widget._image_item.image is not None
    assert window._doppler_widget._image_item.image.shape == (3, 7)


def test_m_hotkey_only_changes_doppler_tool_mode_in_doppler_view(qtbot) -> None:
    window = _make_window(qtbot)

    qtbot.keyClick(window, Qt.Key.Key_M)
    assert window._doppler_widget.get_tool_mode() == "none"

    window.set_view_mode("doppler")
    qtbot.keyClick(window, Qt.Key.Key_M)
    assert window._doppler_widget.get_tool_mode() == "peak"
    qtbot.keyClick(window, Qt.Key.Key_T)
    assert window._doppler_widget.get_tool_mode() == "interval"
    qtbot.keyClick(window, Qt.Key.Key_V)
    assert window._doppler_widget.get_tool_mode() == "trace"


def test_escape_and_enter_delegate_to_active_doppler_tool(qtbot, monkeypatch) -> None:
    window = _make_window(qtbot)
    window.set_view_mode("doppler")
    window._doppler_widget.set_tool_mode("trace")

    cancel_calls: list[bool] = []
    finish_calls: list[bool] = []

    monkeypatch.setattr(
        window._doppler_widget,
        "cancel_active_tool",
        lambda: cancel_calls.append(True) or True,
    )
    monkeypatch.setattr(
        window._doppler_widget,
        "finish_trace",
        lambda: finish_calls.append(True) or True,
    )

    qtbot.keyClick(window, Qt.Key.Key_Return)
    qtbot.keyClick(window, Qt.Key.Key_Escape)

    assert finish_calls == [True]
    assert cancel_calls == [True]
