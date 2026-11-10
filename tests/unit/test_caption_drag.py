"""GUI unit tests for CaptionDragMixin window-chrome gestures (issue 483)."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QWidget

from echo_personal_tool.presentation.window_chrome.caption_drag import CaptionDragMixin
from echo_personal_tool.presentation.window_chrome.hit_test import Zone


class _HostWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.next_zone = Zone.CAPTION
        self.native_frame = False

    def chrome_hit_test(self, _pos: QPoint) -> Zone:
        return self.next_zone

    def is_native_window_frame(self) -> bool:
        return self.native_frame


class _CaptionRow(CaptionDragMixin, QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.double_clicks = 0

    def _caption_double_clicked(self) -> None:
        self.double_clicks += 1


class _NonDraggableRow(_CaptionRow):
    CAPTION_MOVE_ENABLED = False


def _mouse_event(
    event_type: QEvent.Type,
    local: tuple[float, float] = (20.0, 12.0),
    global_xy: tuple[float, float] = (120.0, 112.0),
    button: Qt.MouseButton = Qt.MouseButton.LeftButton,
    buttons: Qt.MouseButton = Qt.MouseButton.LeftButton,
) -> QMouseEvent:
    return QMouseEvent(
        event_type,
        QPointF(*local),
        QPointF(*global_xy),
        button,
        buttons,
        Qt.KeyboardModifier.NoModifier,
    )


@pytest.mark.gui
class TestCaptionDragMixin:
    def test_caption_zone_arms_drag_and_release_clears_state(self, qtbot) -> None:
        win = _HostWindow()
        win.resize(400, 300)
        row = _CaptionRow(win)
        row.setGeometry(0, 0, 400, 32)
        qtbot.addWidget(win)

        win.next_zone = Zone.CAPTION
        row.mousePressEvent(_mouse_event(QEvent.Type.MouseButtonPress))
        assert getattr(row, "_caption_drag_offset", None) is not None

        row.mouseReleaseEvent(
            _mouse_event(
                QEvent.Type.MouseButtonRelease,
                buttons=Qt.MouseButton.NoButton,
            )
        )
        assert getattr(row, "_caption_drag_offset", None) is None
        assert getattr(row, "_caption_drag_origin", None) is None

    def test_client_zone_or_disabled_move_does_not_arm_drag(self, qtbot) -> None:
        win = _HostWindow()
        win.resize(400, 300)
        row = _CaptionRow(win)
        passive_row = _NonDraggableRow(win)
        qtbot.addWidget(win)

        win.next_zone = Zone.CLIENT
        row.mousePressEvent(_mouse_event(QEvent.Type.MouseButtonPress))
        assert getattr(row, "_caption_drag_offset", None) is None

        win.next_zone = Zone.CAPTION
        passive_row.mousePressEvent(_mouse_event(QEvent.Type.MouseButtonPress))
        assert getattr(passive_row, "_caption_drag_offset", None) is None

    def test_double_click_respects_move_enabled_and_native_frame(self, qtbot) -> None:
        win = _HostWindow()
        row = _CaptionRow(win)
        passive_row = _NonDraggableRow(win)
        qtbot.addWidget(win)

        row.mouseDoubleClickEvent(_mouse_event(QEvent.Type.MouseButtonDblClick))
        assert row.double_clicks == 1

        win.native_frame = True
        row.mouseDoubleClickEvent(_mouse_event(QEvent.Type.MouseButtonDblClick))
        assert row.double_clicks == 1

        win.native_frame = False
        passive_row.mouseDoubleClickEvent(_mouse_event(QEvent.Type.MouseButtonDblClick))
        assert passive_row.double_clicks == 0
