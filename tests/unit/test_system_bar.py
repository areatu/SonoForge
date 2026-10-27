"""Tests for SystemBar widget."""

from __future__ import annotations

import pytest

from echo_personal_tool.presentation.system_bar import SystemBar

pytestmark = pytest.mark.gui


def test_system_bar_has_no_caliper_or_layout_buttons_any_more(qtbot) -> None:
    """UI-1 PR-3 (spec §4.1): caliper lives in the tool panel, layout in the logo menu."""
    from PySide6.QtWidgets import QAbstractButton

    bar = SystemBar()
    qtbot.addWidget(bar)
    assert not hasattr(bar, "_btn_caliper")
    assert not hasattr(bar, "_btn_layout")
    assert not hasattr(bar, "_btn_settings")
    labels = {button.text() for button in bar.findChildren(QAbstractButton)}
    assert "Калипер" not in labels
    assert "Настройки" not in labels


def test_system_bar_is_42_px_tall(qtbot) -> None:
    """Spec §4.1: the patient line is one 42 px row (it grows only with the font)."""
    from echo_personal_tool.presentation.system_bar import PATIENT_LINE_HEIGHT_PX

    bar = SystemBar()
    qtbot.addWidget(bar)
    assert PATIENT_LINE_HEIGHT_PX == 42
    assert bar.height() == 42
    assert bar.minimumHeight() == bar.maximumHeight() == 42


def test_system_bar_study_context_and_status(qtbot) -> None:
    bar = SystemBar()
    qtbot.addWidget(bar)
    bar.set_study_context("A4C cine", "US")
    bar.set_status_message("Frame loaded")
    assert bar._study_label.text() == "A4C cine"
    assert "Frame" in bar._status_label.text()
    assert bar._actions_widget is not None


def test_system_bar_pacs_menu_holds_load_and_send(qtbot) -> None:
    """«PACS ▾» groups the two server actions (spec §4.1); both emit their signals."""
    bar = SystemBar()
    qtbot.addWidget(bar)
    load, send = bar._pacs_menu.actions()
    with qtbot.waitSignal(bar.load_from_server_requested, timeout=1000):
        load.trigger()
    with qtbot.waitSignal(bar.send_to_server_requested, timeout=1000):
        send.trigger()


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


def test_system_bar_has_no_caption_buttons_any_more(qtbot) -> None:
    """UI-1 PR-2 moved the window controls into the title bar (spec §4.1).

    The bar keeps no ``caption_buttons()`` of its own: the window controls
    «свернуть / развернуть / закрыть» — and with them ``HTMAXBUTTON`` for the
    Snap Layouts of Windows 11 — belong to
    :class:`~echo_personal_tool.presentation.window_chrome.title_bar.WindowTitleBar`
    and are covered by ``tests/unit/test_title_bar.py``.
    """
    from PySide6.QtWidgets import QWidget

    bar = SystemBar()
    qtbot.addWidget(bar)
    assert bar.caption_buttons() == {}
    for object_name in ("windowControls", "minimizeButton", "maximizeButton", "closeButton"):
        assert bar.findChild(QWidget, object_name) is None, object_name
    assert not hasattr(bar, "_window_controls")


def test_system_bar_drag_does_not_move_the_window(qtbot, monkeypatch) -> None:
    """The file-name row is not a caption (2026-10-27 UI list, item 3).

    A press in the patient line used to arm ``startSystemMove`` even though the
    window's own hit test calls that area CLIENT.  Only the title bar may move
    the window now; the regression is pinned in
    ``tests/unit/test_title_bar.py::test_caption_drag_calls_start_system_move``.
    """
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
    assert moved == []
    assert bar._caption_drag_offset is None


def test_system_bar_double_click_does_not_maximize(qtbot) -> None:
    """The same row must not answer a double click as a window caption."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    bar = SystemBar()
    qtbot.addWidget(bar)
    bar.resize(400, 42)
    seen: list[bool] = []
    bar.maximize_requested.connect(lambda: seen.append(True))
    ev = QMouseEvent(
        QEvent.Type.MouseButtonDblClick,
        QPointF(200.0, 20.0),
        QPointF(200.0, 20.0),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    bar.mouseDoubleClickEvent(ev)
    assert seen == []


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


def test_system_bar_localizes_send_to_server(qtbot) -> None:
    """UI-1 PR-1 localized «Send to server…»; UI-1 PR-3 moved it into the «PACS ▾» menu."""
    from echo_personal_tool.infrastructure.i18n import get_language, set_language, tr

    prev = get_language()
    try:
        set_language("ru")
        bar = SystemBar()
        qtbot.addWidget(bar)
        assert bar._act_send_server.text() == tr("system_bar.send_to_server")
        set_language("en")
        bar.reload_text()
        assert bar._act_send_server.text() == tr("system_bar.send_to_server")
    finally:
        set_language(prev)


class TestModeSwitch:
    """«Изображения | Отчёт» (UI-4 PR-1, spec §4.1/§4.6, UD-08: two states)."""

    def test_switch_starts_on_the_images(self, qtbot) -> None:
        bar = SystemBar()
        qtbot.addWidget(bar)
        assert bar.report_mode() is False
        assert bar._btn_mode_images.isChecked() is True
        assert bar._btn_mode_report.isChecked() is False
        assert bar._btn_mode_images.text() == "Изображения"
        assert bar._btn_mode_report.text() == "Отчёт"
        assert "Ctrl+R" in bar._btn_mode_report.toolTip()

    def test_clicking_the_segments_emits_the_mode(self, qtbot) -> None:
        bar = SystemBar()
        qtbot.addWidget(bar)
        with qtbot.waitSignal(bar.report_mode_changed, timeout=1000) as signal:
            bar._btn_mode_report.click()
        assert signal.args == [True]
        assert bar._btn_mode_images.isChecked() is False
        with qtbot.waitSignal(bar.report_mode_changed, timeout=1000) as signal:
            bar._btn_mode_images.click()
        assert signal.args == [False]
        assert bar.report_mode() is False

    def test_clicking_the_active_segment_keeps_it_checked(self, qtbot) -> None:
        bar = SystemBar()
        qtbot.addWidget(bar)
        bar._btn_mode_images.click()
        assert bar._btn_mode_images.isChecked() is True
        assert bar.report_mode() is False

    def test_set_report_mode_mirrors_without_emitting(self, qtbot) -> None:
        bar = SystemBar()
        qtbot.addWidget(bar)
        seen: list[bool] = []
        bar.report_mode_changed.connect(seen.append)
        bar.set_report_mode(True)
        assert bar.report_mode() is True
        assert bar._btn_mode_images.isChecked() is False
        bar.set_report_mode(True)  # same value — a no-op
        bar.set_report_mode(False)
        assert bar.report_mode() is False
        assert seen == []

    def test_switch_never_shrinks(self, qtbot) -> None:
        """Spec §6 (narrow window): captions give way before the switch."""
        from PySide6.QtWidgets import QSizePolicy

        bar = SystemBar()
        qtbot.addWidget(bar)
        assert bar._mode_switch.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Fixed

    def test_switch_localizes_with_the_bar(self, qtbot) -> None:
        from echo_personal_tool.infrastructure.i18n import get_language, set_language

        prev = get_language()
        try:
            set_language("ru")
            bar = SystemBar()
            qtbot.addWidget(bar)
            set_language("en")
            bar.reload_text()
            assert bar._btn_mode_images.text() == "Images"
            assert bar._btn_mode_report.text() == "Report"
        finally:
            set_language(prev)


def test_action_groups_are_separated_by_hairlines(qtbot) -> None:
    """The row is grouped (design A1), not one line of equal chips.

    «Открыть | PACS · Сравнить · Презентация · Справочник · Сброс» reads as a
    single undifferentiated set without the hairlines, and the destructive
    «Сброс» then sits as close to the safe actions as they sit to each other.
    """
    bar = SystemBar()
    qtbot.addWidget(bar)
    assert len(bar._action_separators) == 3
    # One logical pixel, fixed: the hairline must not stretch with the layout.
    assert all(
        separator.minimumWidth() == separator.maximumWidth() == 1 for separator, _group in bar._action_separators
    )

    bar.set_action_separators_visible(False)
    assert all(not separator.isVisibleTo(bar) for separator, _group in bar._action_separators)
    bar.set_action_separators_visible(True)


def test_a_hairline_disappears_with_the_group_before_it(qtbot) -> None:
    """Presenter builds hide «Справочник» — its hairline must go with it."""
    bar = SystemBar()
    qtbot.addWidget(bar)
    bar.show()
    bar.set_references_visible(False)
    references_line = next(separator for separator, group in bar._action_separators if bar._btn_references in group)
    assert not references_line.isVisibleTo(bar)
