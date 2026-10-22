"""TP-6 radial menu: the hold, the jerk, the fallbacks (spec §4.4, A-14)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.gui

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent

from echo_personal_tool.presentation.radial_menu import (
    JERK_PX,
    MORE_ID,
    SHOW_DELAY_MS,
    RadialMenuController,
    sector_at,
)

_SECTORS = (("tool.caliper", "Калипер"), ("tool.area", "Площадь"), ("tool.volume", "Объём"))


class _Recorder:
    def __init__(self) -> None:
        self.tools: list[str] = []
        self.more_calls = 0

    def on_tool(self, tool_id: str) -> None:
        self.tools.append(tool_id)

    def on_more(self) -> None:
        self.more_calls += 1

    def sectors(self):
        return _SECTORS


def _controller() -> tuple[RadialMenuController, _Recorder]:
    recorder = _Recorder()
    controller = RadialMenuController(sectors=recorder.sectors, on_tool=recorder.on_tool, on_more=recorder.on_more)
    return controller, recorder


def test_sector_at_maps_the_clock_face() -> None:
    assert sector_at(0.0, -1.0) == 0  # top
    assert sector_at(1.0, 0.0) == 2  # right
    assert sector_at(0.0, 1.0) == 4  # bottom
    assert sector_at(-1.0, 0.0) == 6  # left


def test_hold_shows_the_wheel_after_the_delay(qtbot) -> None:
    controller, _ = _controller()
    assert controller.on_right_press(QPointF(400.0, 300.0)) is True
    assert controller.gesture_active is True
    assert controller.menu is None

    qtbot.wait(SHOW_DELAY_MS + 80)
    menu = controller.menu
    assert menu is not None
    assert menu.isVisible()
    assert menu.sector_ids() == (
        "tool.caliper",
        "tool.area",
        "tool.volume",
        MORE_ID,
        MORE_ID,
        MORE_ID,
        MORE_ID,
        MORE_ID,
    )
    controller.cancel()
    assert controller.menu is None


def test_jerk_picks_a_sector_without_showing_the_wheel(qtbot) -> None:
    controller, recorder = _controller()
    controller.on_right_press(QPointF(400.0, 300.0))
    # Downwards travel: the bottom sector (index 4) is beyond the defaults.
    controller.on_pointer_move(QPointF(400.0, 300.0 + JERK_PX + 4))
    qtbot.wait(SHOW_DELAY_MS + 80)
    assert controller.menu is None  # the wheel never appears after a jerk

    controller.on_right_release(QPointF(400.0, 300.0 + JERK_PX + 4))
    assert not controller.gesture_active
    assert recorder.tools == []  # index 4 has no tool in this three-sector wheel
    assert recorder.more_calls == 1


def test_jerk_on_the_first_sector_activates_the_tool(qtbot) -> None:
    controller, recorder = _controller()
    controller.on_right_press(QPointF(400.0, 300.0))
    controller.on_pointer_move(QPointF(400.0, 300.0 - (JERK_PX + 4)))  # straight up = sector 0
    controller.on_right_release(QPointF(400.0, 300.0 - (JERK_PX + 4)))
    assert recorder.tools == ["tool.caliper"]
    assert recorder.more_calls == 0


def test_quick_click_falls_back_to_the_legacy_menu(qtbot) -> None:
    controller, recorder = _controller()
    controller.on_right_press(QPointF(400.0, 300.0))
    controller.on_right_release(QPointF(400.0, 300.0))
    qtbot.wait(20)
    assert recorder.tools == []
    assert recorder.more_calls == 1
    assert controller.menu is None


def test_more_sector_opens_the_legacy_menu(qtbot) -> None:
    controller, recorder = _controller()
    controller.on_right_press(QPointF(400.0, 300.0))
    qtbot.wait(SHOW_DELAY_MS + 80)
    menu = controller.menu
    assert menu is not None
    menu.select_sector(len(menu.sector_ids()) - 1)  # the fixed «Ещё…»
    assert recorder.more_calls == 1
    assert controller.menu is None


def test_wheel_sector_activates_the_tool(qtbot) -> None:
    controller, recorder = _controller()
    controller.on_right_press(QPointF(400.0, 300.0))
    qtbot.wait(SHOW_DELAY_MS + 80)
    menu = controller.menu
    assert menu is not None
    menu.select_sector(0)
    assert recorder.tools == ["tool.caliper"]
    assert controller.menu is None


def test_center_disc_dismisses_the_wheel(qtbot) -> None:
    controller, recorder = _controller()
    controller.on_right_press(QPointF(400.0, 300.0))
    qtbot.wait(SHOW_DELAY_MS + 80)
    menu = controller.menu
    assert menu is not None
    dismissed = []
    menu.dismissed.connect(lambda: dismissed.append(True))
    menu.dismiss()
    assert dismissed
    assert controller.menu is None
    assert recorder.tools == []
    assert recorder.more_calls == 0


def test_viewer_forwards_an_idle_right_press_to_the_controller(make_viewer, monkeypatch) -> None:
    viewer = make_viewer()
    controller, recorder = _controller()
    viewer.radial_controller = controller
    legacy: list[bool] = []
    monkeypatch.setattr(viewer, "_show_save_context_menu", lambda ev: legacy.append(True))

    press = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(40.0, 40.0),
        QPointF(40.0, 40.0),
        QPointF(140.0, 140.0),
        Qt.MouseButton.RightButton,
        Qt.MouseButton.RightButton,
        Qt.KeyboardModifier.NoModifier,
    )
    handled = viewer.eventFilter(viewer._graphics, press)

    assert handled is True
    assert controller.gesture_active is True
    assert legacy == []
    controller.cancel()


def test_viewer_keeps_the_legacy_menu_while_drawing(make_viewer, monkeypatch) -> None:
    viewer = make_viewer()
    controller, _ = _controller()
    viewer.radial_controller = controller
    legacy: list[bool] = []
    monkeypatch.setattr(viewer, "_show_save_context_menu", lambda ev: legacy.append(True))
    viewer._contour_mode_active = True

    press = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(40.0, 40.0),
        QPointF(40.0, 40.0),
        QPointF(140.0, 140.0),
        Qt.MouseButton.RightButton,
        Qt.MouseButton.RightButton,
        Qt.KeyboardModifier.NoModifier,
    )
    handled = viewer.eventFilter(viewer._graphics, press)

    assert handled is True
    assert controller.gesture_active is False
    assert legacy == [True]
