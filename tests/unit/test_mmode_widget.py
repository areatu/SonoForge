from __future__ import annotations

import numpy as np
import pytest

pytestmark = pytest.mark.gui
from PySide6.QtWidgets import QApplication

from echo_personal_tool.presentation.mmode_widget import MModeWidget


def test_mmode_widget_creation(qtbot) -> None:
    w = MModeWidget()
    qtbot.addWidget(w)
    assert w._image_buffer is not None
    assert w._sweep_x == 0


def test_mmode_widget_on_new_column(qtbot) -> None:
    w = MModeWidget()
    qtbot.addWidget(w)
    col = np.full(256, 128, dtype=np.uint8)
    w.on_new_column(col)
    assert w._sweep_x == 1
    # After log+spatial+temporal smoothing, values are transformed
    assert w._image_buffer[0, 0] > 0
    assert w._image_buffer[0, 0] < 255


def test_mmode_widget_buffer_wraps(qtbot) -> None:
    w = MModeWidget(buffer_width=10)
    qtbot.addWidget(w)
    for i in range(15):
        col = np.full(256, i, dtype=np.uint8)
        w.on_new_column(col)
    assert w._sweep_x == 5


def test_mmode_widget_clear_buffer(qtbot) -> None:
    w = MModeWidget()
    qtbot.addWidget(w)
    col = np.full(256, 200, dtype=np.uint8)
    w.on_new_column(col)
    assert w._sweep_x == 1
    w.clear_buffer()
    assert w._sweep_x == 0
    assert w._image_buffer.sum() == 0


def test_mmode_widget_set_scan_line(qtbot) -> None:
    w = MModeWidget()
    qtbot.addWidget(w)
    w.set_scan_line((10.0, 20.0), (100.0, 200.0), num_samples=128)
    assert w._num_samples == 128
    assert w._image_buffer.shape[0] == 128


def test_mmode_widget_recalculate(qtbot) -> None:
    w = MModeWidget(buffer_width=10)
    qtbot.addWidget(w)
    for i in range(5):
        col = np.full(256, i * 10, dtype=np.uint8)
        w.on_new_column(col)
    frames = [np.full((64, 64), i * 10, dtype=np.uint8) for i in range(5)]
    w.recalculate_from_frames(frames, (0.0, 32.0), (63.0, 32.0))
    assert w._sweep_x == 5


def test_mmode_widget_time_calibration(qtbot) -> None:
    w = MModeWidget()
    qtbot.addWidget(w)
    w.set_time_calibration_ms_per_pixel(3.3)
    assert w._time_ms_per_pixel == 3.3


def test_mmode_widget_depth_calibration(qtbot) -> None:
    w = MModeWidget()
    qtbot.addWidget(w)
    w.set_depth_calibration_mm_per_pixel(0.15)
    assert w._depth_mm_per_pixel == 0.15


@pytest.fixture(scope="session", autouse=True)
def _qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app
