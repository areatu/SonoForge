"""Mode buttons of the tool row: wiring and pressed state.

Acceptance list of 2026-10-23, item 3: «часть кнопок инструментов не подключена и
непонятна по функции (doppler, calibration, interval); при нажатии клавиш кнопки
не подсвечиваются».  The tests below pin the three rules that fixed it:

* every mode button resolves to a handler (a click and its key cannot drift);
* the pressed look is read from the viewer, so a hotkey lights the same button a
  click does;
* a click that arms nothing (a Doppler mode refused on a 2D frame, a cancelled
  tool) leaves no button looking pressed.
"""

from __future__ import annotations

import numpy as np
import pytest

pytestmark = pytest.mark.gui

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest

from echo_personal_tool.presentation.tool_buttons import buttons as tool_buttons


@pytest.fixture(autouse=True)
def _isolate_qsettings(isolated_qsettings):
    return isolated_qsettings


def _key_press(key: Qt.Key) -> QKeyEvent:
    return QKeyEvent(QKeyEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)


def _window(qtbot):
    """A window with the 2.0 panel, a fake frame and a «loaded» study.

    Without a clip every button is legitimately dimmed (D-08), and a dimmed
    button cannot show its pressed look — the assertions below are about the
    look, so the state the row reads is made explicit.
    """
    from echo_personal_tool.application.app_controller import AppController
    from echo_personal_tool.infrastructure.user_preferences import UserPreferences
    from echo_personal_tool.presentation.layout.presets import LayoutConfigV2
    from echo_personal_tool.presentation.main_window import MainWindow

    window = MainWindow(
        controller=AppController(),
        user_preferences=UserPreferences(tool_panel_v2=True),
    )
    window._layout_document = LayoutConfigV2(single_file_focus=False)
    window._multiview_mode = False
    qtbot.addWidget(window)
    window.resize(1280, 800)
    window.show()
    qtbot.waitExposed(window)
    window._viewer._current_frame = np.full((160, 200), 60, dtype=np.uint8)
    window._has_loaded_study = True
    window._refresh_tool_buttons()
    return window


def _pressed(window) -> list[str]:
    row = window._tool_row
    return [spec.id for spec in row._specs if row._controls[spec.id].isChecked()]


def test_every_mode_button_has_a_handler(qtbot) -> None:
    window = _window(qtbot)
    handlers = window._tool_button_handlers()
    wiring = {
        spec.id: bool(tool_buttons.payload(spec) is not None or spec.ref in handlers)
        for spec in tool_buttons.TOOL_BUTTONS
    }
    assert [button for button, wired in wiring.items() if not wired] == []


def test_mode_buttons_explain_themselves(qtbot) -> None:
    window = _window(qtbot)
    row = window._tool_row
    tips = {
        button: row._controls[button].toolTip() for button in ("calibration", "doppler_interval", "vti_trace", "zoom")
    }
    assert all(tips.values())
    assert len(set(tips.values())) == len(tips)


def test_calibration_button_lights_then_esc_unlights(qtbot) -> None:
    window = _window(qtbot)
    QTest.mouseClick(window._tool_row._controls["calibration"], Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: window._viewer.is_calibration_active)
    assert window._tool_button_active == "calibration"
    assert _pressed(window) == ["calibration"]

    window._cancel_active_tool()
    assert window._viewer.is_calibration_active is False
    assert window._tool_button_active is None
    assert _pressed(window) == []


def test_hotkey_lights_the_same_button_a_click_does(qtbot) -> None:
    window = _window(qtbot)
    window._handle_key_press(_key_press(Qt.Key.Key_K))
    assert window._viewer.is_calibration_active
    assert _pressed(window) == ["calibration"]

    window._cancel_active_tool()
    QTest.mouseClick(window._tool_row._controls["calibration"], Qt.MouseButton.LeftButton)
    assert _pressed(window) == ["calibration"]


def test_loupe_button_toggles_the_viewer_loupe(qtbot) -> None:
    window = _window(qtbot)
    button = window._tool_row._controls["zoom"]

    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert window._viewer.zoom_loupe_active() is True
    assert _pressed(window) == ["zoom"]

    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert window._viewer.zoom_loupe_active() is False
    assert _pressed(window) == []


def test_esc_drops_a_contour_mode_that_has_no_nodes_yet(qtbot) -> None:
    """Esc used to leave the contour mode armed: the drawing item was None."""
    window = _window(qtbot)
    window._on_tool_button_requested("freehand_area")
    assert window._viewer.is_contour_mode_active is True
    assert window._viewer.area_tool_mode() == "freehand"

    window._cancel_active_tool()
    assert window._viewer.is_contour_mode_active is False
    assert _pressed(window) == []


def test_freehand_volume_lights_its_own_button(qtbot) -> None:
    window = _window(qtbot)
    window._on_tool_button_requested("freehand_volume")
    assert window._viewer.is_contour_mode_active is True
    assert window._viewer.area_tool_mode() == "freehand"
    assert _pressed(window) == ["freehand_volume"]


def test_plain_area_restores_the_preference_mode_after_freehand(qtbot) -> None:
    """The plain pair must not stay stuck in stroke mode after a freehand use."""
    window = _window(qtbot)
    window._on_tool_button_requested("freehand_area")
    assert window._viewer.area_tool_mode() == "freehand"
    window._on_tool_button_requested("spline_area")
    assert window._viewer.area_tool_mode() == window._user_preferences.area_tool_mode


def test_a_click_that_arms_nothing_does_not_stay_pressed(qtbot) -> None:
    """The VTI button on a 2D frame is refused — the row must not keep it lit."""
    window = _window(qtbot)
    for button_id in ("vti_trace", "doppler_interval"):
        QTest.mouseClick(window._tool_row._controls[button_id], Qt.MouseButton.LeftButton)
        assert window._viewer.get_doppler_tool_mode() == "none"
        assert _pressed(window) == []


def test_measure_action_accepts_the_catalog_payload_string(qtbot, monkeypatch) -> None:
    """The sink reads the payload of the catalog, and that payload is a string.

    ``MeasurementAction`` is a string enum, so ``isinstance`` never complained
    about the enum itself — only about the plain «caliper» the tool row hands
    over, and the gate dropped it: the three measurement buttons did nothing
    while their hotkeys (which call the handlers directly) worked (item 3 of
    the 2026-10-23 list).
    """
    window = _window(qtbot)
    seen: list[str] = []
    monkeypatch.setattr(window, "_on_caliper_requested", lambda label=None: seen.append("caliper"))

    window._on_measure_action("caliper", "A4C", "ED", "")
    assert seen == ["caliper"]


@pytest.mark.parametrize(
    ("button_id", "handler"),
    [
        ("caliper", "_on_caliper_requested"),
        ("spline_area", "_on_spline_area_requested"),
        ("spline_volume", "_on_spline_volume_requested"),
    ],
)
def test_the_first_three_buttons_arm_their_tool(qtbot, monkeypatch, button_id, handler) -> None:
    """A click of «Калипер» / «Площадь» / «Объём» reaches its own handler."""
    window = _window(qtbot)
    calls: list[str] = []
    monkeypatch.setattr(window, handler, lambda *_args, **_kwargs: calls.append(handler))

    QTest.mouseClick(window._tool_row._controls[button_id], Qt.MouseButton.LeftButton)
    assert calls == [handler]
