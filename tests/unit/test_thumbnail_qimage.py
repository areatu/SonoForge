"""Unit tests for thumbnail QImage → QIcon conversion."""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication

from echo_personal_tool.application.workers.thumbnail_loader_worker import (
    numpy_grayscale_to_qimage,
)

pytest.importorskip("pytestqt")


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
    pixmap = QPixmap.fromImage(image)
    assert not pixmap.isNull()

    icon = QIcon(pixmap)
    assert not icon.isNull()
