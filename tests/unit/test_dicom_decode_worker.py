"""Unit tests for DicomDecodeWorker."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication, QWidget

from echo_personal_tool.application.workers.dicom_decode_worker import DicomDecodeWorker
from tests.fixtures.generate_synthetic_dicom import write_synthetic_multiframe_dicom

pytest.importorskip("pytestqt")


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def test_dicom_decode_worker_emits_all_frames(
    qapp: QApplication, qtbot, tmp_path: Path
) -> None:
    parent = QWidget()
    path = tmp_path / "multi.dcm"
    write_synthetic_multiframe_dicom(path, frame_count=4, rows=16, cols=16)

    finished: list[tuple[int, Path, np.ndarray]] = []
    worker = DicomDecodeWorker(path, request_id=7, parent=parent)
    worker.signals.finished.connect(
        lambda request_id, decoded_path, frames: finished.append(
            (request_id, decoded_path, frames)
        )
    )
    QThreadPool.globalInstance().start(worker)
    qtbot.waitUntil(lambda: len(finished) == 1, timeout=10000)

    request_id, decoded_path, frames = finished[0]
    assert request_id == 7
    assert decoded_path.resolve() == path.resolve()
    assert frames.shape == (4, 16, 16)
    assert frames[2, 0, 0] == 2


def test_dicom_decode_worker_emits_failed_for_missing_file(
    qapp: QApplication, qtbot, tmp_path: Path
) -> None:
    parent = QWidget()
    path = tmp_path / "missing.dcm"
    errors: list[tuple[int, str]] = []
    worker = DicomDecodeWorker(path, request_id=1, parent=parent)
    worker.signals.failed.connect(
        lambda request_id, message: errors.append((request_id, message))
    )
    QThreadPool.globalInstance().start(worker)
    qtbot.waitUntil(lambda: len(errors) == 1, timeout=5000)
    assert errors[0][0] == 1
    assert errors[0][1]
