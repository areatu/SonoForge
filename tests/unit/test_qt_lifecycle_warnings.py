"""Regression guard for issue #622: no ``QObject: shared QObject was deleted
directly`` warnings during widget create/teardown cycles.

The warning means a QObject with shared ownership was destroyed on the wrong
side (direct C++ delete instead of ``deleteLater``). This test installs a Qt
message handler, drives the create → close → deleteLater → event-loop cycles
that previously produced the warning, and fails if the text appears.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.gui
pytest.importorskip("pytestqt")

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QtMsgType, qInstallMessageHandler
from PySide6.QtWidgets import QApplication, QWidget

_WARNING = "shared QObject was deleted directly"


@pytest.fixture
def captured_qt_warnings():
    messages: list[str] = []

    def handler(mode, context, message):
        if _WARNING in message:
            messages.append(message)

    qInstallMessageHandler(handler)
    yield messages
    qInstallMessageHandler(None)


def _drain_events() -> None:
    app = QApplication.instance()
    if app is not None:
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


def test_parented_widget_teardown_emits_no_shared_qobject_warning(qtbot, captured_qt_warnings) -> None:
    for _ in range(5):
        parent = QWidget()
        qtbot.addWidget(parent)
        child = QWidget(parent)
        worker = QObject(parent)
        worker.deleteLater()
        child.deleteLater()
        _drain_events()
    _drain_events()
    assert captured_qt_warnings == []


def test_unregistered_parent_widget_gc_emits_no_shared_qobject_warning(qapp, qtbot, captured_qt_warnings) -> None:
    # Workers parented to a throwaway widget: the parent must go through
    # deleteLater + event delivery, never a direct C++ delete.
    import gc

    parent = QWidget()
    qtbot.addWidget(parent)
    QObject(parent).deleteLater()
    _drain_events()
    gc.collect()
    _drain_events()
    assert captured_qt_warnings == []
