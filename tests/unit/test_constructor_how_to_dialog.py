"""Tests for the bilingual "how to measure" constructor dialog."""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytestmark = pytest.mark.gui

_THEME = {
    "bg_panel": "#1a2332",
    "bg_control": "#243044",
    "bg_button_hover": "#3a5068",
    "accent_tab": "#3b82f6",
    "text": "#f1f5f9",
    "border": "#334155",
}


@pytest.fixture
def dialog(qtbot):
    from echo_personal_tool.constructor.editors.how_to_dialog import HowToDialog

    with patch(
        "echo_personal_tool.constructor.editors.how_to_dialog.get_theme_palette",
        return_value=_THEME,
    ):
        widget = HowToDialog()
    qtbot.addWidget(widget)
    return widget


def test_reads_and_writes_ru_en_steps(dialog):
    dialog._editors["ru"].setPlainText("  Первый шаг  \n\nВторой шаг")
    dialog._editors["en"].setPlainText("First step\nSecond step")

    assert dialog.how_to == {
        "ru": ["Первый шаг", "Второй шаг"],
        "en": ["First step", "Second step"],
    }


def test_empty_translations_clear_the_optional_field(dialog):
    dialog._editors["ru"].setPlainText(" \n")
    dialog._editors["en"].setPlainText("")

    assert dialog.how_to is None


def test_one_locale_can_be_translated_before_the_other(qtbot):
    from echo_personal_tool.constructor.editors.how_to_dialog import HowToDialog

    with patch(
        "echo_personal_tool.constructor.editors.how_to_dialog.get_theme_palette",
        return_value=_THEME,
    ):
        widget = HowToDialog({"ru": ["Первый шаг"]})
    qtbot.addWidget(widget)

    assert widget._editors["ru"].toPlainText() == "Первый шаг"
    assert widget._editors["en"].toPlainText() == ""
    assert widget.how_to == {"ru": ["Первый шаг"], "en": []}
