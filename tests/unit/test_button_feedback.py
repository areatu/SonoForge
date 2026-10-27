"""Animated hover/press feedback of the settings «Готово» (item 1)."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QEnterEvent, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

pytestmark = pytest.mark.gui


def _send(button, event) -> None:
    QApplication.sendEvent(button, event)


def _enter(pos: QPointF) -> QEnterEvent:
    return QEnterEvent(pos, pos, pos)


def _mouse(kind: QEvent.Type, buttons: Qt.MouseButton) -> QMouseEvent:
    return QMouseEvent(
        kind,
        QPointF(5, 5),
        QPointF(100, 100),
        Qt.MouseButton.LeftButton,
        buttons,
        Qt.KeyboardModifier.NoModifier,
    )


def test_install_is_idempotent_and_keeps_the_button(qtbot) -> None:
    from echo_personal_tool.presentation.theme.button_feedback import ButtonFeedback

    button = QPushButton("Done")
    qtbot.addWidget(button)
    first = ButtonFeedback.install(button)
    assert ButtonFeedback.install(button) is first
    assert button.text() == "Done"
    assert button.toolTip() == ""


def test_hover_and_press_are_animated_then_released(qtbot) -> None:
    from echo_personal_tool.presentation.theme.button_feedback import ButtonFeedback

    button = QPushButton("Done")
    qtbot.addWidget(button)
    button.resize(120, 34)
    button.show()
    feedback = ButtonFeedback.install(button)

    _send(button, _enter(QPointF(5, 5)))
    QTest.qWait(160)
    assert feedback.overlay.hover_level() == pytest.approx(1.0)
    hover_opacity = feedback.overlay.opacity()
    assert hover_opacity > 0.2

    _send(button, _mouse(QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton))
    QTest.qWait(120)
    assert feedback.overlay.press_level() == pytest.approx(1.0)
    assert feedback.overlay.opacity() > hover_opacity

    _send(button, _mouse(QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton))
    QTest.qWait(120)
    assert feedback.overlay.press_level() == pytest.approx(0.0)


def test_reduce_motion_skips_the_interpolation_not_the_feedback(qtbot, monkeypatch) -> None:
    import echo_personal_tool.presentation.theme.button_feedback as module
    from echo_personal_tool.presentation.theme.button_feedback import ButtonFeedback

    monkeypatch.setattr(module, "_reduce_motion", lambda: True)
    button = QPushButton("Done")
    qtbot.addWidget(button)
    button.show()
    feedback = ButtonFeedback.install(button)
    _send(button, _enter(QPointF(5, 5)))
    QApplication.processEvents()
    assert feedback.overlay.hover_level() == pytest.approx(1.0)


def test_settings_done_button_has_the_feedback_and_all_states(qtbot) -> None:
    from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

    dialog = UserPreferencesDialog()
    qtbot.addWidget(dialog)
    ok = dialog._ok_button
    assert hasattr(ok, "_button_feedback")
    sheet = dialog.styleSheet()
    for state in (":hover", ":pressed", ":disabled", ":focus"):
        assert f"QPushButton#settingsOkButton{state}" in sheet


def test_interface_palette_picker_drives_the_two_comboboxes(qtbot) -> None:
    from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

    dialog = UserPreferencesDialog()
    qtbot.addWidget(dialog)
    picker = dialog._palette_picker
    assert picker.current_preset() is not None
    dialog._on_palette_preset_selected("light", "amber")
    assert dialog._theme_combo.currentData() == "light"
    assert dialog._accent_palette_combo.currentData() == "amber"
    assert picker.current_preset() == "paper"
    dialog._on_palette_preset_selected("graphite", "theme")
    assert picker.current_preset() == "graphite"
