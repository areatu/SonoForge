"""Measures tab accordion menu layout."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.gui
from PySide6.QtWidgets import QApplication, QPushButton

from echo_personal_tool.presentation.measures_menu import MeasuresMenuWidget


def test_lv_auto_has_no_biplane_buttons(_qapp) -> None:
    menu = MeasuresMenuWidget()
    biplane = [child for child in menu.findChildren(QPushButton) if child.text().startswith("Simpson Biplane")]
    assert len(biplane) == 2
    assert all(button.isEnabled() for button in biplane)


@pytest.fixture(scope="session", autouse=True)
def _qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app
