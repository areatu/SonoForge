"""Ensure QRunnable workers deliver cross-thread signals reliably."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication, QWidget

from echo_personal_tool.application.workers.frame_loader_worker import FrameLoaderWorker
from tests.fixtures.generate_synthetic_dicom import write_synthetic_dicom

pytest.importorskip("pytestqt")


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def test_frame_loader_delivers_signal_when_parented(qapp: QApplication, qtbot) -> None:
    parent = QWidget()
    path = Path(tempfile.mkdtemp()) / "frame.dcm"
    write_synthetic_dicom(path)

    received: list = []

    def on_finished(pixels: object) -> None:
        received.append(pixels)

    worker = FrameLoaderWorker(path, parent=parent)
    worker.signals.finished.connect(on_finished)
    QThreadPool.globalInstance().start(worker)

    qtbot.waitUntil(lambda: len(received) == 1, timeout=5000)
    assert received[0].shape == (64, 64)
