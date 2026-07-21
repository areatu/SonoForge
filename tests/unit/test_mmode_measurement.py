from __future__ import annotations

import pyqtgraph as pg
import pytest
pytestmark = pytest.mark.gui
from PySide6.QtWidgets import QApplication

from echo_personal_tool.presentation.mmode_measurement import MModeMeasurementTool


@pytest.fixture
def view_box():
    vb = pg.ViewBox()
    return vb


def test_measurement_tool_vertical(view_box) -> None:
    tool = MModeMeasurementTool()
    tool.set_view_box(view_box)
    tool.set_calibration(depth_mm_per_pixel=0.5, time_ms_per_pixel=10.0, num_samples=256)
    tool.start_vertical()
    tool.on_click(100.0, 50.0)
    tool.on_click(100.0, 150.0)
    assert len(tool.measurements) == 1
    m = tool.measurements[0]
    assert m.kind == "vertical"
    assert m.value_mm == pytest.approx(50.0)
    assert m.value_ms is None


def test_measurement_tool_horizontal(view_box) -> None:
    tool = MModeMeasurementTool()
    tool.set_view_box(view_box)
    tool.set_calibration(depth_mm_per_pixel=0.5, time_ms_per_pixel=10.0, num_samples=256)
    tool.start_horizontal()
    tool.on_click(50.0, 100.0)
    tool.on_click(200.0, 100.0)
    assert len(tool.measurements) == 1
    m = tool.measurements[0]
    assert m.kind == "horizontal"
    assert m.value_mm is None
    assert m.value_ms == pytest.approx(1500.0)


def test_measurement_tool_arbitrary(view_box) -> None:
    tool = MModeMeasurementTool()
    tool.set_view_box(view_box)
    tool.set_calibration(depth_mm_per_pixel=0.5, time_ms_per_pixel=10.0, num_samples=256)
    tool.start_arbitrary()
    tool.on_click(0.0, 0.0)
    tool.on_click(100.0, 200.0)
    assert len(tool.measurements) == 1
    m = tool.measurements[0]
    assert m.kind == "arbitrary"
    assert m.value_mm == pytest.approx(100.0)
    assert m.value_ms == pytest.approx(1000.0)


def test_measurement_tool_clear(view_box) -> None:
    tool = MModeMeasurementTool()
    tool.set_view_box(view_box)
    tool.set_calibration(depth_mm_per_pixel=0.5, time_ms_per_pixel=10.0, num_samples=256)
    tool.start_vertical()
    tool.on_click(100.0, 50.0)
    tool.on_click(100.0, 150.0)
    assert len(tool.measurements) == 1
    tool.clear()
    assert len(tool.measurements) == 0


def test_measurement_tool_cancel() -> None:
    tool = MModeMeasurementTool()
    tool.start_vertical()
    tool.on_click(100.0, 50.0)
    tool.cancel()
    assert tool._active_mode is None
    assert tool._first_click is None


@pytest.fixture(scope="session", autouse=True)
def _qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app
