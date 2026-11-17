"""Behavioral tests for the PACS loader's frameless title bar."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget

from echo_personal_tool.application.localization import tr
from echo_personal_tool.infrastructure.i18n import set_language
from echo_personal_tool.presentation.pacs_title_bar import build_pacs_title_bar
from echo_personal_tool.presentation.ui_metrics import title_bar_height

pytestmark = pytest.mark.gui

_TOKENS = {
    "surface.0": "#101014",
    "text.1": "#e6e6ea",
    "text.2": "#9a9aa4",
    "state.warn": "#e0a030",
}


@pytest.fixture(autouse=True)
def _qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    set_language("ru")
    yield app
    set_language("ru")


@pytest.fixture()
def parent():
    """A real parent widget: the bar measures its font metrics."""
    widget = QWidget()
    yield widget
    widget.deleteLater()


def _build(parent: QWidget, on_close: object | None = None):
    return build_pacs_title_bar(parent, _TOKENS, on_close=on_close or MagicMock())


def test_the_bar_carries_the_title_and_its_own_surface(parent) -> None:
    """The frameless window has no native caption, so this bar *is* the caption."""
    bar, _server, _transport, title, _close = _build(parent)
    assert bar.height() == title_bar_height(parent)
    assert isinstance(title, QLabel)
    assert title.text()
    assert _TOKENS["surface.0"] in bar.styleSheet()


def test_the_transport_pill_starts_hidden(parent) -> None:
    """It only speaks up when the transport is not the plain DICOMweb path."""
    _bar, _server, transport, _title, _close = _build(parent)
    assert isinstance(transport, QLabel)
    assert transport.isHidden()


def test_the_close_button_is_named_and_accessible(parent) -> None:
    """A symbol-only button needs a name for screen readers (the 484 gate)."""
    _bar, _server, _transport, _title, close = _build(parent)
    assert isinstance(close, QPushButton)
    assert close.objectName() == "closeButton"
    assert close.accessibleName()
    assert close.toolTip()
    assert not close.icon().isNull()


def test_the_close_button_calls_the_callback(parent) -> None:
    on_close = MagicMock()
    _bar, _server, _transport, _title, close = _build(parent, on_close=on_close)
    close.click()
    on_close.assert_called_once_with()


def test_the_close_button_can_take_focus(parent) -> None:
    """The dialog checks ``hasFocus()`` on this button in its key handler."""
    _bar, _server, _transport, _title, close = _build(parent)
    assert close.focusPolicy() != Qt.FocusPolicy.NoFocus


def test_the_server_pill_reports_that_the_check_is_running(parent) -> None:
    _bar, server, _transport, _title, _close = _build(parent)
    assert server.text() == tr("orthanc.checking_server")
