"""Unit tests for thumbnail QImage → QIcon conversion."""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import QApplication

from echo_personal_tool.application.workers import thumbnail_loader_worker as worker_module
from echo_personal_tool.application.workers.thumbnail_loader_worker import (
    THUMBNAIL_SIZE,
    ThumbnailLoaderWorker,
    numpy_grayscale_to_qimage,
)


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_numpy_grayscale_to_qimage_can_build_tree_icon(qapp: QApplication) -> None:
    pixels = np.arange(64 * 64, dtype=np.uint8).reshape(64, 64)
    image = numpy_grayscale_to_qimage(pixels)

    assert not image.isNull()
    assert image.width() == THUMBNAIL_SIZE
    assert image.height() == THUMBNAIL_SIZE
    pixmap = QPixmap.fromImage(image)
    assert not pixmap.isNull()

    icon = QIcon(pixmap)
    assert not icon.isNull()


def test_worker_preview_uses_requested_size(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_read_pixels(_self: object, _path: object, frame_index: int = 0) -> np.ndarray:
        assert frame_index == 0
        # Portrait ultrasound-like aspect (width < height).
        return np.zeros((160, 90), dtype=np.uint8)

    monkeypatch.setattr(worker_module.DicomReaderImpl, "read_pixels", fake_read_pixels)

    worker = ThumbnailLoaderWorker("/tmp/fake.dcm", "uid-1", preview_size=72)
    done: list[tuple[str, QImage]] = []
    worker.signals.finished.connect(lambda uid, image: done.append((uid, image)))

    worker.run()

    assert len(done) == 1
    assert done[0][0] == "uid-1"
    image = done[0][1]
    assert not image.isNull()
    assert image.width() <= 72
    assert image.height() <= 72
    assert max(image.width(), image.height()) == 72
    assert image.width() / image.height() == pytest.approx(90 / 160, rel=0.02)


def test_numpy_pixels_to_qimage_preserves_aspect_ratio(qapp: QApplication) -> None:
    pixels = np.zeros((120, 200), dtype=np.uint8)
    image = numpy_grayscale_to_qimage(pixels, size=100)

    assert not image.isNull()
    assert image.width() <= 100
    assert image.height() <= 100
    assert max(image.width(), image.height()) == 100
    assert image.width() / image.height() == pytest.approx(200 / 120, rel=0.02)


def test_worker_preview_default_size_is_96(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, int] = {}

    def fake_read_pixels(_self: object, _path: object, frame_index: int = 0) -> np.ndarray:
        assert frame_index == 0
        return np.zeros((8, 8), dtype=np.uint8)

    def fake_numpy_pixels_to_qimage(_pixels: np.ndarray, size: int = THUMBNAIL_SIZE) -> QImage:
        captured["size"] = size
        return QImage(8, 8, QImage.Format.Format_Grayscale8)

    monkeypatch.setattr(worker_module.DicomReaderImpl, "read_pixels", fake_read_pixels)
    monkeypatch.setattr(worker_module, "numpy_pixels_to_qimage", fake_numpy_pixels_to_qimage)

    worker = ThumbnailLoaderWorker("/tmp/fake.dcm", "uid-2")
    done: list[tuple[str, QImage]] = []
    worker.signals.finished.connect(lambda uid, image: done.append((uid, image)))

    worker.run()

    assert captured["size"] == 96
    assert len(done) == 1
    assert done[0][0] == "uid-2"


def test_worker_preview_only_false_is_ignored_in_mvp(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, int] = {}

    def fake_read_pixels(_self: object, _path: object, frame_index: int = 0) -> np.ndarray:
        assert frame_index == 0
        return np.zeros((8, 8), dtype=np.uint8)

    def fake_numpy_pixels_to_qimage(_pixels: np.ndarray, size: int = THUMBNAIL_SIZE) -> QImage:
        captured["size"] = size
        return QImage(8, 8, QImage.Format.Format_Grayscale8)

    monkeypatch.setattr(worker_module.DicomReaderImpl, "read_pixels", fake_read_pixels)
    monkeypatch.setattr(worker_module, "numpy_pixels_to_qimage", fake_numpy_pixels_to_qimage)

    worker = ThumbnailLoaderWorker(
        "/tmp/fake.dcm",
        "uid-3",
        preview_size=64,
        preview_only=False,
    )
    done: list[tuple[str, QImage]] = []
    worker.signals.finished.connect(lambda uid, image: done.append((uid, image)))

    worker.run()

    assert captured["size"] == 64
    assert len(done) == 1
    assert done[0][0] == "uid-3"


def test_worker_emits_failed_signal_when_reader_raises(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_read_pixels(_self: object, _path: object, frame_index: int = 0) -> np.ndarray:
        raise RuntimeError("boom")

    monkeypatch.setattr(worker_module.DicomReaderImpl, "read_pixels", fake_read_pixels)

    worker = ThumbnailLoaderWorker("/tmp/fake.dcm", "uid-fail")
    failures: list[tuple[str, str]] = []
    worker.signals.failed.connect(lambda uid, message: failures.append((uid, message)))

    worker.run()

    assert len(failures) == 1
    assert failures[0][0] == "uid-fail"
    assert "boom" in failures[0][1]
