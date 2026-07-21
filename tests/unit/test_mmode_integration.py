from __future__ import annotations

import numpy as np
import pytest
pytestmark = pytest.mark.gui
from PySide6.QtWidgets import QApplication

from echo_personal_tool.domain.models import InstanceMetadata
from echo_personal_tool.domain.services.mmode_extractor import extract_mmode_column
from echo_personal_tool.presentation.mmode_caliper import MModeCaliperTool
from echo_personal_tool.presentation.mmode_scan_line import MModeScanLineItem
from echo_personal_tool.presentation.mmode_widget import MModeWidget


def _sample_instance() -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid="1.2.3.4.5",
        series_uid="1.2.3.4.6",
        modality="US",
        number_of_frames=10,
        pixel_spacing=(0.5, 0.5),
        frame_time_ms=33.3,
        series_description="Test",
        path=None,
    )


def test_mmode_extraction_pipeline() -> None:
    frame = np.zeros((100, 100), dtype=np.uint8)
    for y in range(100):
        frame[y, :] = y
    col = extract_mmode_column(frame, (50.0, 0.0), (50.0, 99.0), num_samples=50)
    assert col.shape == (50,)
    assert col[0] == 0
    assert col[-1] == 99


def test_mmode_widget_recieves_columns(qtbot) -> None:
    widget = MModeWidget(buffer_width=20)
    qtbot.addWidget(widget)
    for i in range(10):
        col = np.full(256, i * 10, dtype=np.uint8)
        widget.on_new_column(col)
    assert widget._sweep_x == 10
    # After smoothing pipeline, values are transformed
    assert widget._image_buffer[0, 0] >= 0
    assert widget._image_buffer[0, 9] > widget._image_buffer[0, 0]


def test_mmode_scan_line_endpoints() -> None:
    item = MModeScanLineItem(viewer_widget=None)
    item.set_start((20.0, 30.0))
    item.set_end((80.0, 70.0))
    start, end = item.get_endpoints()
    assert start == (20.0, 30.0)
    assert end == (80.0, 70.0)
    assert item.is_complete


def test_mmode_caliper_with_full_pipeline() -> None:
    tool = MModeCaliperTool(depth_mm_per_pixel=0.2, time_ms_per_pixel=5.0)
    tool.start_distance_caliper()
    tool.on_click(10.0, 10.0)
    tool.on_click(10.0, 60.0)
    assert tool.measurements[0].value_mm == pytest.approx(10.0)
    tool.start_time_caliper()
    tool.on_click(5.0, 30.0)
    tool.on_click(65.0, 30.0)
    assert tool.measurements[1].value_ms == pytest.approx(300.0)


def test_mmode_full_cine_loop() -> None:
    frames = [np.full((64, 64), i * 10, dtype=np.uint8) for i in range(20)]
    widget = MModeWidget(buffer_width=30)
    widget.recalculate_from_frames(frames, (0.0, 32.0), (63.0, 32.0))
    assert widget._sweep_x == 20
    # After smoothing pipeline, values are transformed
    assert widget._image_buffer[0, 0] >= 0
    assert widget._image_buffer[0, 19] > 0


@pytest.fixture(scope="session", autouse=True)
def _qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app
