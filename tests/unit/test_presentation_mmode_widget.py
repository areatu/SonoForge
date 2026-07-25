"""Unit tests for presentation/mmode_widget.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def _setup_qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture()
def mmode_widget():
    from echo_personal_tool.presentation.mmode_widget import MModeWidget

    w = MModeWidget(buffer_width=64)
    yield w
    w.close()


class TestMModeWidgetInit:
    def test_initial_state(self, mmode_widget):
        assert mmode_widget._buffer_width == 64
        assert mmode_widget._num_samples == 256
        assert mmode_widget._sweep_x == 0
        assert mmode_widget._time_ms_per_pixel is None
        assert mmode_widget._depth_mm_per_pixel is None

    def test_initial_buffer_shape(self, mmode_widget):
        assert mmode_widget._image_buffer.shape == (256, 64)

    def test_speed_buttons_created(self, mmode_widget):
        assert len(mmode_widget._speed_buttons) == 3
        assert "50 mm/s" in mmode_widget._speed_buttons

    def test_measure_buttons_created(self, mmode_widget):
        assert len(mmode_widget._measure_btns) == 3

    def test_default_speed_checked(self, mmode_widget):
        assert mmode_widget._speed_buttons["50 mm/s"].isChecked()

    def test_teichholz_es_disabled_initially(self, mmode_widget):
        assert not mmode_widget._teichholz_es_btn.isEnabled()


class TestSetSweepSpeed:
    def test_valid_speed(self, mmode_widget):
        mmode_widget.set_sweep_speed("25 mm/s")
        assert mmode_widget._buffer_width == 128

    def test_same_speed_noop(self):
        from echo_personal_tool.presentation.mmode_widget import MModeWidget

        w = MModeWidget(buffer_width=256)
        old_buf = w._image_buffer
        w.set_sweep_speed("50 mm/s")  # already 256 — should be noop
        assert w._image_buffer is old_buf
        w.close()

    def test_invalid_speed(self, mmode_widget):
        old_width = mmode_widget._buffer_width
        mmode_widget.set_sweep_speed("invalid")
        assert mmode_widget._buffer_width == old_width

    def test_speed_change_resets_sweep(self, mmode_widget):
        mmode_widget._sweep_x = 10
        mmode_widget.set_sweep_speed("37.5 mm/s")
        assert mmode_widget._sweep_x == 0

    def test_speed_change_updates_buffer(self, mmode_widget):
        mmode_widget.set_sweep_speed("25 mm/s")
        assert mmode_widget._image_buffer.shape == (256, 128)


class TestOnNewColumn:
    def test_adds_column(self, mmode_widget):
        col = np.arange(256, dtype=np.uint8)
        mmode_widget.on_new_column(col)
        assert mmode_widget._sweep_x == 1

    def test_wraps_around(self, mmode_widget):
        col = np.arange(256, dtype=np.uint8)
        mmode_widget._sweep_x = 63
        mmode_widget.on_new_column(col)
        assert mmode_widget._sweep_x == 0

    def test_preserves_previous_column(self, mmode_widget):
        col = np.arange(256, dtype=np.uint8)
        mmode_widget.on_new_column(col)
        assert mmode_widget._previous_column is not None

    def test_shorter_column(self, mmode_widget):
        col = np.arange(100, dtype=np.uint8)
        mmode_widget.on_new_column(col)
        assert mmode_widget._sweep_x == 1

    def test_with_time_calibration(self, mmode_widget):
        mmode_widget._time_ms_per_pixel = 10.0
        col = np.arange(256, dtype=np.uint8)
        mmode_widget.on_new_column(col)
        # sweep_line should be set to sweep_x * time_ms_per_pixel
        assert mmode_widget._sweep_line.value() > 0


class TestClearBuffer:
    def test_clears(self, mmode_widget):
        mmode_widget._sweep_x = 10
        mmode_widget._previous_column = np.zeros(256)
        mmode_widget.clear_buffer()
        assert mmode_widget._sweep_x == 0
        assert mmode_widget._previous_column is None
        assert np.all(mmode_widget._image_buffer == 0)


class TestClearCalibration:
    def test_clears(self, mmode_widget):
        mmode_widget._time_ms_per_pixel = 5.0
        mmode_widget._depth_mm_per_pixel = 0.1
        mmode_widget.clear_calibration()
        assert mmode_widget._time_ms_per_pixel is None
        assert mmode_widget._depth_mm_per_pixel is None


class TestSetScanLine:
    def test_sets_scan_line(self, mmode_widget):
        mmode_widget.set_scan_line((10, 20), (100, 200))
        assert mmode_widget._scan_start == (10, 20)
        assert mmode_widget._scan_end == (100, 200)

    def test_different_num_samples(self, mmode_widget):
        mmode_widget.set_scan_line((0, 0), (100, 100), num_samples=128)
        assert mmode_widget._num_samples == 128
        assert mmode_widget._image_buffer.shape[0] == 128


class TestCalibration:
    def test_time_calibration(self, mmode_widget):
        mmode_widget.set_time_calibration_ms_per_pixel(5.0)
        assert mmode_widget._time_ms_per_pixel == 5.0

    def test_depth_calibration_mm(self, mmode_widget):
        mmode_widget.set_depth_calibration_mm_per_pixel(0.1)
        assert mmode_widget._depth_mm_per_pixel == 0.1

    def test_depth_calibration_cm(self, mmode_widget):
        mmode_widget.set_depth_calibration_cm_per_pixel(0.01)
        assert mmode_widget._depth_mm_per_pixel == 0.1

    def test_depth_range_mm(self, mmode_widget):
        mmode_widget.set_depth_range_mm(128.0)
        expected = 128.0 / 256
        assert abs(mmode_widget._depth_mm_per_pixel - expected) < 1e-6


class TestMeasureButtons:
    def test_start_vertical(self, mmode_widget):
        mmode_widget._start_vertical_measurement()
        assert mmode_widget._measure_btns["▼ Вертикаль"].isChecked()
        assert mmode_widget._measurement_tool._active_mode is not None

    def test_start_horizontal(self, mmode_widget):
        mmode_widget._start_horizontal_measurement()
        assert mmode_widget._measure_btns["◄ Горизонталь"].isChecked()

    def test_start_arbitrary(self, mmode_widget):
        mmode_widget._start_arbitrary_measurement()
        assert mmode_widget._measure_btns["↗ Произвольное"].isChecked()

    def test_clear_measurements(self, mmode_widget):
        mmode_widget._start_vertical_measurement()
        mmode_widget._clear_measurements()
        for btn in mmode_widget._measure_btns.values():
            assert not btn.isChecked()


class TestTeichholz:
    def test_start_teichholz_ed(self, mmode_widget):
        mmode_widget._start_teichholz_ed()
        assert mmode_widget._teichholz_ed_btn.isChecked()
        assert mmode_widget._measurement_tool._active_mode is not None

    def test_teichholz_ed_complete_enables_es(self, mmode_widget):
        mmode_widget._on_teichholz_ed_complete([MagicMock(), MagicMock(), MagicMock()])
        assert mmode_widget._teichholz_es_btn.isEnabled()
        assert not mmode_widget._teichholz_ed_btn.isChecked()

    def test_teichholz_es_complete(self, mmode_widget):
        mmode_widget._on_teichholz_es_complete(MagicMock())
        assert not mmode_widget._teichholz_es_btn.isEnabled()

    def test_start_teichholz_es(self, mmode_widget):
        mmode_widget._start_teichholz_es()
        assert mmode_widget._teichholz_es_btn.isChecked()


class TestSignals:
    def test_deactivate_signal(self, mmode_widget):
        spy = MagicMock()
        mmode_widget.deactivate_requested.connect(spy)
        mmode_widget._close_btn.click()
        spy.assert_called_once()

    def test_sweep_speed_signal(self, mmode_widget):
        spy = MagicMock()
        mmode_widget.sweep_speed_changed.connect(spy)
        mmode_widget.set_sweep_speed("25 mm/s")
        spy.assert_called_once_with(128)
