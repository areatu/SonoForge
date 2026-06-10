"""Unit tests for FrameLoaderWorker media routing."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication, QWidget

from echo_personal_tool.application.workers.frame_loader_worker import FrameLoaderWorker
from tests.fixtures.generate_synthetic_dicom import write_synthetic_dicom
from tests.fixtures.generate_synthetic_media import (
    write_synthetic_jpeg,
    write_synthetic_mp4,
    write_synthetic_png,
)

pytest.importorskip("pytestqt")


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _run_worker(qtbot, worker: FrameLoaderWorker) -> np.ndarray:
    received: list[np.ndarray] = []
    worker.signals.finished.connect(received.append)
    QThreadPool.globalInstance().start(worker)
    qtbot.waitUntil(lambda: len(received) == 1, timeout=5000)
    return received[0]


def test_frame_loader_reads_dicom(qapp: QApplication, qtbot, tmp_path: Path) -> None:
    parent = QWidget()
    path = tmp_path / "frame.dcm"
    write_synthetic_dicom(path)
    pixels = _run_worker(
        qtbot,
        FrameLoaderWorker(path, media_format="dicom", parent=parent),
    )
    assert pixels.shape == (64, 64)


def test_frame_loader_reads_mp4(qapp: QApplication, qtbot, tmp_path: Path) -> None:
    parent = QWidget()
    path = tmp_path / "clip.mp4"
    write_synthetic_mp4(path, frame_count=4, width=20, height=16)
    pixels = _run_worker(
        qtbot,
        FrameLoaderWorker(path, media_format="mp4", parent=parent),
    )
    assert pixels.shape == (16, 20, 3)


def test_frame_loader_reads_jpeg(qapp: QApplication, qtbot, tmp_path: Path) -> None:
    parent = QWidget()
    path = tmp_path / "still.jpg"
    write_synthetic_jpeg(path, width=24, height=18, value=42)
    pixels = _run_worker(
        qtbot,
        FrameLoaderWorker(path, media_format="jpeg", parent=parent),
    )
    assert pixels.shape == (18, 24, 3)
    assert int(pixels[0, 0, 0]) == 42


def test_frame_loader_reads_png(qapp: QApplication, qtbot, tmp_path: Path) -> None:
    parent = QWidget()
    path = tmp_path / "still.png"
    write_synthetic_png(path, width=24, height=18, value=17)
    pixels = _run_worker(
        qtbot,
        FrameLoaderWorker(path, media_format="png", parent=parent),
    )
    assert pixels.shape == (18, 24, 3)
    assert int(pixels[0, 0, 0]) == 17
