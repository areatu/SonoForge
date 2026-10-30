"""Wheel gestures scroll the page; they do not edit the hovered control."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit, QSpinBox, QStyle, QVBoxLayout, QWidget

from echo_personal_tool.presentation.scroll_policy import ScrollSafeStyle, protect_spinbox

pytestmark = pytest.mark.gui


def _wheel(delta: int = -120) -> QWheelEvent:
    return QWheelEvent(
        QPointF(5, 5),
        QPointF(5, 5),
        QPoint(0, 0),
        QPoint(0, delta),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )


def test_closed_combo_ignores_wheel_and_keeps_selection(qtbot) -> None:
    combo = QComboBox()
    qtbot.addWidget(combo)
    combo.setStyle(ScrollSafeStyle("Fusion"))
    combo.addItems(["low", "normal", "high"])
    combo.setCurrentIndex(1)
    changes: list[int] = []
    combo.currentIndexChanged.connect(changes.append)

    for _ in range(20):
        event = _wheel()
        QApplication.sendEvent(combo, event)
        assert not event.isAccepted()

    assert combo.currentIndex() == 1
    assert changes == []


def test_open_combo_popup_still_receives_wheel(qtbot) -> None:
    combo = QComboBox()
    qtbot.addWidget(combo)
    combo.setStyle(ScrollSafeStyle("Fusion"))
    combo.addItems(["low", "normal", "high"])
    # Exercise the popup's list view directly.  Showing the native popup under
    # the offscreen CI platform can leave a modal grab alive after the worker's
    # Qt event loop is torn down, hanging the whole xdist shard at 98%.
    view = combo.view()
    event = _wheel()
    QApplication.sendEvent(view, event)
    # The popup is a list view; the closed-combo style hint must not block it.
    assert event.isAccepted()
    assert combo.currentIndex() == 0


def test_unfocused_spinbox_ignores_wheel_but_focused_one_edits(qtbot) -> None:
    host = QWidget()
    qtbot.addWidget(host)
    layout = QVBoxLayout(host)
    spin = QSpinBox()
    spin.setRange(0, 250)
    spin.setValue(180)
    guard = protect_spinbox(spin)
    assert guard.parent() is spin
    other = QLineEdit()
    layout.addWidget(spin)
    layout.addWidget(other)
    host.show()
    other.setFocus()
    QApplication.processEvents()
    assert not spin.hasFocus()

    event = _wheel()
    QApplication.sendEvent(spin, event)
    assert not event.isAccepted()
    assert spin.value() == 180

    spin.setFocus()
    QApplication.processEvents()
    assert spin.hasFocus()
    event = _wheel()
    QApplication.sendEvent(spin, event)
    assert event.isAccepted()
    assert spin.value() == 179


def test_keyboard_selection_is_unchanged(qtbot) -> None:
    combo = QComboBox()
    qtbot.addWidget(combo)
    combo.setStyle(ScrollSafeStyle("Fusion"))
    combo.addItems(["low", "normal", "high"])
    combo.setCurrentIndex(1)
    combo.setFocus()
    qtbot.keyClick(combo, Qt.Key.Key_Down)
    assert combo.currentIndex() == 2


def test_style_disables_closed_combo_wheel_scrolling() -> None:
    style = ScrollSafeStyle("Fusion")
    assert style.styleHint(QStyle.StyleHint.SH_ComboBox_AllowWheelScrolling) == 0
