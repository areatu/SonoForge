from __future__ import annotations

import pytest
pytestmark = pytest.mark.gui
from PySide6.QtWidgets import QApplication

from echo_personal_tool.presentation.mmode_caliper import MModeCaliperTool


def test_caliper_tool_creation(qtbot) -> None:
    tool = MModeCaliperTool()
    qtbot.addWidget(tool)
    assert tool.measurements == []


def test_caliper_tool_start_distance(qtbot) -> None:
    tool = MModeCaliperTool()
    qtbot.addWidget(tool)
    tool.start_distance_caliper()
    assert tool._active_mode == "distance"


def test_caliper_tool_start_time(qtbot) -> None:
    tool = MModeCaliperTool()
    qtbot.addWidget(tool)
    tool.start_time_caliper()
    assert tool._active_mode == "time"


def test_caliper_tool_click_distance(qtbot) -> None:
    tool = MModeCaliperTool()
    qtbot.addWidget(tool)
    tool.start_distance_caliper()
    tool.on_click(10.0, 5.0)
    assert tool._first_click == (10.0, 5.0)
    tool.on_click(10.0, 50.0)
    assert len(tool.measurements) == 1
    assert tool.measurements[0].kind == "distance"
    assert tool._active_mode is None


def test_caliper_tool_click_time(qtbot) -> None:
    tool = MModeCaliperTool()
    qtbot.addWidget(tool)
    tool.start_time_caliper()
    tool.on_click(5.0, 10.0)
    tool.on_click(100.0, 10.0)
    assert len(tool.measurements) == 1
    assert tool.measurements[0].kind == "time"


def test_caliper_tool_clear(qtbot) -> None:
    tool = MModeCaliperTool()
    qtbot.addWidget(tool)
    tool.start_distance_caliper()
    tool.on_click(10.0, 5.0)
    tool.on_click(10.0, 50.0)
    tool.clear()
    assert tool.measurements == []


def test_caliper_tool_with_calibration(qtbot) -> None:
    tool = MModeCaliperTool(depth_mm_per_pixel=0.15, time_ms_per_pixel=3.3)
    qtbot.addWidget(tool)
    tool.start_distance_caliper()
    tool.on_click(10.0, 5.0)
    tool.on_click(10.0, 50.0)
    assert tool.measurements[0].value_mm is not None
    assert tool.measurements[0].value_mm == pytest.approx(6.75, rel=0.01)


@pytest.fixture(scope="session", autouse=True)
def _qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app
