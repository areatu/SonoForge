"""Display server / Qt rendering compatibility tests.

Tests that Qt can initialize and render under different QT_QPA_PLATFORM
configurations, focusing on headless/offscreen mode reliability.

Run:  pytest tests/compat/test_display_server.py -v
"""

from __future__ import annotations

import os
import sys

import pytest

_compat = pytest.mark.compat


# ── Offscreen mode ──────────────────────────────────────────────────


@_compat
def test_qt_offscreen_platform_import(monkeypatch: pytest.MonkeyPatch) -> None:
    """QT_QPA_PLATFORM=offscreen allows Qt import without display."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QImage

    assert QRect is not None
    assert QImage is not None


@_compat
def test_qt_offscreen_image_creation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Create QImage in offscreen mode without crash."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QColor, QImage

    img = QImage(256, 256, QImage.Format.Format_Grayscale8)
    assert img.width() == 256
    img.fill(QColor(128, 128, 128))
    assert img.pixelColor(0, 0).red() == 128


@_compat
def test_qt_offscreen_painter_render(monkeypatch: pytest.MonkeyPatch) -> None:
    """Render QPainter operations in offscreen mode."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QColor, QImage, QPainter, QPen

    img = QImage(512, 512, QImage.Format.Format_ARGB32)
    img.fill(QColor(0, 0, 0))
    painter = QPainter(img)
    painter.setPen(QPen(QColor(255, 0, 0)))
    painter.setBrush(QColor(255, 0, 0))
    painter.drawRect(QRect(10, 10, 100, 100))
    painter.end()
    assert img.pixelColor(50, 50).red() == 255


@_compat
def test_qt_offscreen_numpy_conversion(monkeypatch: pytest.MonkeyPatch) -> None:
    """Convert QImage from numpy and back in offscreen mode."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    import numpy as np
    from PySide6.QtGui import QImage

    arr = np.random.randint(0, 255, (128, 128), dtype=np.uint8)
    h, w = arr.shape
    bytes_per_line = w
    qimg = QImage(arr.data, w, h, bytes_per_line, QImage.Format.Format_Grayscale8)
    assert qimg.width() == w
    assert qimg.height() == h


# ── xcb mode ────────────────────────────────────────────────────────


@_compat
@pytest.mark.xfail(
    sys.platform == "win32" or os.environ.get("DISPLAY", "") == "",
    reason="xcb requires a running X server or Xvfb",
    strict=True,
)
def test_qt_xcb_platform_import(monkeypatch: pytest.MonkeyPatch) -> None:
    """QT_QPA_PLATFORM=xcb works with X server available."""
    if sys.platform == "win32" or not os.environ.get("DISPLAY"):
        pytest.fail("DISPLAY is not set — xcb platform requires an X server")
    monkeypatch.setenv("QT_QPA_PLATFORM", "xcb")
    from PySide6.QtCore import QRect

    assert QRect is not None


@_compat
@pytest.mark.xfail(
    sys.platform == "win32" or os.environ.get("DISPLAY", "") == "",
    reason="xcb requires a running X server or Xvfb",
    strict=True,
)
def test_qt_xcb_image_render(monkeypatch: pytest.MonkeyPatch) -> None:
    """QImage creation and QPainter under xcb."""
    if sys.platform == "win32" or not os.environ.get("DISPLAY"):
        pytest.fail("DISPLAY is not set — xcb platform requires an X server")
    monkeypatch.setenv("QT_QPA_PLATFORM", "xcb")
    from PySide6.QtGui import QImage

    img = QImage(64, 64, QImage.Format.Format_Grayscale8)
    assert img.width() == 64


# ── Platform fallback behavior ──────────────────────────────────────


@_compat
def test_offscreen_preferred_over_xcb(monkeypatch: pytest.MonkeyPatch) -> None:
    """When DISPLAY is unset, offscreen mode should be used for headless CI."""
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QImage

    img = QImage(32, 32, QImage.Format.Format_Grayscale8)
    assert not img.isNull()


@_compat
def test_qt_offscreen_rgba_rendering(monkeypatch: pytest.MonkeyPatch) -> None:
    """Offscreen mode handles RGBA format correctly."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QColor, QImage

    img = QImage(64, 64, QImage.Format.Format_RGBA8888)
    img.fill(QColor(0, 128, 255, 200))
    c = img.pixelColor(32, 32)
    assert c.red() == 0
    assert c.green() == 128
    assert c.blue() == 255
    assert c.alpha() == 200


@_compat
def test_qt_offscreen_text_rendering(monkeypatch: pytest.MonkeyPatch) -> None:
    """Offscreen text rendering does not crash when QApplication is active."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QColor, QFont, QImage, QPainter
    from PySide6.QtWidgets import QApplication

    if QApplication.instance() is None:
        QApplication([])
    img = QImage(256, 64, QImage.Format.Format_ARGB32)
    img.fill(QColor(255, 255, 255))
    painter = QPainter(img)
    painter.setFont(QFont("Sans Serif", 12))
    painter.drawText(QRect(0, 0, 256, 64), 0, "ECHO2026")
    painter.end()
    assert not img.isNull()
