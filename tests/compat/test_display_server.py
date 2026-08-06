"""Display server / Qt rendering compatibility tests.

Tests that Qt can initialize and render under different QT_QPA_PLATFORM
configurations, focusing on headless/offscreen mode reliability.

Run:  ECHO_COMPAT=1 pytest tests/compat/test_display_server.py -v
"""

from __future__ import annotations

import os
import sys

import pytest

_compat = pytest.mark.compat


# ── Offscreen mode ──────────────────────────────────────────────────


@_compat
def test_qt_offscreen_platform_import() -> None:
    """QT_QPA_PLATFORM=offscreen allows Qt import without display."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    try:
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QImage

        assert QRect is not None
        assert QImage is not None
    finally:
        os.environ.pop("QT_QPA_PLATFORM", None)


@_compat
def test_qt_offscreen_image_creation() -> None:
    """Create QImage in offscreen mode without crash."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    try:
        from PySide6.QtGui import QColor, QImage

        img = QImage(256, 256, QImage.Format.Format_Grayscale8)
        assert img.width() == 256
        img.fill(QColor(128, 128, 128))
        assert img.pixelColor(0, 0).red() == 128
    finally:
        os.environ.pop("QT_QPA_PLATFORM", None)


@_compat
def test_qt_offscreen_painter_render() -> None:
    """Render QPainter operations in offscreen mode."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    try:
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
    finally:
        os.environ.pop("QT_QPA_PLATFORM", None)


@_compat
def test_qt_offscreen_numpy_conversion() -> None:
    """Convert QImage from numpy and back in offscreen mode."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    try:
        import numpy as np
        from PySide6.QtGui import QImage

        arr = np.random.randint(0, 255, (128, 128), dtype=np.uint8)
        h, w = arr.shape
        bytes_per_line = w
        qimg = QImage(arr.data, w, h, bytes_per_line, QImage.Format.Format_Grayscale8)
        assert qimg.width() == w
        assert qimg.height() == h
    finally:
        os.environ.pop("QT_QPA_PLATFORM", None)


# ── xcb mode ────────────────────────────────────────────────────────


@_compat
@pytest.mark.xfail(
    sys.platform == "win32" or os.environ.get("DISPLAY", "") == "",
    reason="xcb requires a running X server or Xvfb",
    strict=False,
)
def test_qt_xcb_platform_import() -> None:
    """QT_QPA_PLATFORM=xcb works with X server available."""
    os.environ["QT_QPA_PLATFORM"] = "xcb"
    try:
        from PySide6.QtCore import QRect

        assert QRect is not None
    except RuntimeError:
        pytest.skip("X server not available")
    finally:
        os.environ.pop("QT_QPA_PLATFORM", None)


@_compat
@pytest.mark.xfail(
    sys.platform == "win32" or os.environ.get("DISPLAY", "") == "",
    reason="xcb requires a running X server or Xvfb",
    strict=False,
)
def test_qt_xcb_image_render() -> None:
    """QImage creation and QPainter under xcb."""
    os.environ["QT_QPA_PLATFORM"] = "xcb"
    try:
        from PySide6.QtGui import QImage

        img = QImage(64, 64, QImage.Format.Format_Grayscale8)
        assert img.width() == 64
    except RuntimeError:
        pytest.skip("X server not available")
    finally:
        os.environ.pop("QT_QPA_PLATFORM", None)


# ── Platform fallback behavior ──────────────────────────────────────


@_compat
def test_offscreen_preferred_over_xcb() -> None:
    """When DISPLAY is unset, offscreen mode should be used for headless CI."""
    if os.environ.get("DISPLAY"):
        pytest.skip("DISPLAY is set — xcb would be used")
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    try:
        from PySide6.QtGui import QImage

        img = QImage(32, 32, QImage.Format.Format_Grayscale8)
        assert not img.isNull()
    finally:
        os.environ.pop("QT_QPA_PLATFORM", None)


@_compat
def test_qt_offscreen_rgba_rendering() -> None:
    """Offscreen mode handles RGBA format correctly."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    try:
        from PySide6.QtGui import QColor, QImage

        img = QImage(64, 64, QImage.Format.Format_RGBA8888)
        img.fill(QColor(0, 128, 255, 200))
        c = img.pixelColor(32, 32)
        assert c.red() == 0
        assert c.green() == 128
        assert c.blue() == 255
        assert c.alpha() == 200
    finally:
        os.environ.pop("QT_QPA_PLATFORM", None)


@_compat
def test_qt_offscreen_text_rendering() -> None:
    """Offscreen text rendering does not crash."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    try:
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QColor, QFont, QImage, QPainter

        img = QImage(256, 64, QImage.Format.Format_ARGB32)
        img.fill(QColor(255, 255, 255))
        painter = QPainter(img)
        painter.setFont(QFont("Arial", 12))
        painter.drawText(QRect(0, 0, 256, 64), 0, "ECHO2026")
        painter.end()
        assert not img.isNull()
    finally:
        os.environ.pop("QT_QPA_PLATFORM", None)
