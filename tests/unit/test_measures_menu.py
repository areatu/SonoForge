"""Measures tab accordion menu layout."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QPushButton

from echo_personal_tool.presentation.measures_menu import MeasuresMenuWidget


def test_lv_auto_biplane_buttons_disabled(_qapp) -> None:
    menu = MeasuresMenuWidget()
    buttons = [
        child
        for child in menu.findChildren(QPushButton)
        if child.text().startswith("Simpson Biplane") and not child.isEnabled()
    ]
    assert len(buttons) == 2
    assert all("следующей" in button.toolTip() for button in buttons)


@pytest.fixture(scope="session", autouse=True)
def _qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app
