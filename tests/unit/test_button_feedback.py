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


def test_interface_palette_picker_drives_the_accent_and_never_the_theme(qtbot) -> None:
    """Item 1 of the 2026-10-27 list: the palette and the theme do not overlap.

    The cards used to write both comboboxes, so «Аметист» switched the ground,
    the panels and the text as well — the same promise the theme combo makes.
    A card now changes the accent only; the theme stays wherever the user left
    it, and the preview repaints its surfaces for that theme instead.
    """
    from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

    dialog = UserPreferencesDialog()
    qtbot.addWidget(dialog)
    picker = dialog._palette_picker
    assert picker.current_preset() is not None

    theme_before = dialog._theme_combo.currentData()
    dialog._on_palette_accent_selected("amber")
    assert dialog._accent_palette_combo.currentData() == "amber"
    assert dialog._theme_combo.currentData() == theme_before
    assert picker.current_preset() == "accent_amber"

    # A theme switch is the theme combo's business: the picker follows it with
    # its preview swatches and keeps the chosen accent checked.
    light_index = dialog._theme_combo.findData("light")
    if light_index >= 0:
        dialog._theme_combo.setCurrentIndex(light_index)
        assert picker.current_preset() == "accent_amber"

    dialog._on_palette_accent_selected("theme")
    assert picker.current_preset() == "accent_theme"


def test_accept_strips_graphics_effects_without_deleted_effect_crash(qtbot, monkeypatch) -> None:
    from PySide6.QtWidgets import QWidget

    import echo_personal_tool.presentation.user_preferences_dialog as prefs_mod
    from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

    monkeypatch.setattr(prefs_mod, "save_user_preferences", lambda _p: None)
    monkeypatch.setattr(prefs_mod, "save_server_settings", lambda _s: None)

    effects_during_apply: list[object] = []

    def _on_apply(_prefs) -> None:
        effects_during_apply.extend(
            w.graphicsEffect() for w in dialog.findChildren(QWidget) if w.graphicsEffect() is not None
        )

    dialog = UserPreferencesDialog(on_apply=_on_apply)
    qtbot.addWidget(dialog)
    dialog.show()

    # Start live hover + press animations on «Готово», then accept immediately.
    _send(dialog._ok_button, _enter(QPointF(5, 5)))
    _send(dialog._ok_button, _mouse(QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton))
    dialog._on_accept()
    QTest.qWait(150)

    assert effects_during_apply == []
    assert dialog._ok_button._button_feedback.overlay.opacity() == 0.0
