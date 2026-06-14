"""Click-click linear caliper workflow tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QApplication

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.domain.models import InstanceMetadata
from echo_personal_tool.domain.models.viewer_state import ViewerState
from echo_personal_tool.presentation.main_window import MainWindow
from echo_personal_tool.presentation.viewer_widget import ViewerWidget


def _sample_instance() -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid="1.2.3.4.5",
        series_uid="1.2.3.4.6",
        modality="US",
        number_of_frames=10,
        pixel_spacing=(0.5, 0.5),
        frame_time_ms=33.3,
        series_description="Test",
        path=Path("/tmp/test.dcm"),
    )


def _sample_state() -> ViewerState:
    return ViewerState(
        instance=_sample_instance(),
        current_frame_index=0,
        total_frames=10,
        frame_time_ms=33.3,
        is_playing=False,
    )


def _simulate_view_press(viewer: ViewerWidget, x: float, y: float) -> None:
    scene_pos = viewer._view.mapViewToScene(QPointF(x, y))
    ev = MagicMock()
    ev.button.return_value = Qt.MouseButton.LeftButton
    ev.scenePos.return_value = scene_pos
    assert viewer._handle_linear_caliper_mouse_press(ev)


def _place_caliper(viewer: ViewerWidget, x_start: float, x_end: float, y: float = 32.0) -> None:
    _simulate_view_press(viewer, x_start, y)
    _simulate_view_press(viewer, x_end, y)


def test_linear_caliper_two_clicks_commit_measurement(qtbot) -> None:
    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    viewer.show_frame(np.zeros((64, 64), dtype=np.uint8))
    viewer.set_state(_sample_state())

    emitted: list[list] = []
    viewer.linear_measurements_changed.connect(emitted.append)

    viewer.start_linear_caliper_for("LVEDD")
    assert viewer.is_linear_caliper_active
    assert viewer._linear_caliper_line_item is None

    _simulate_view_press(viewer, 10.0, 32.0)
    assert viewer._linear_caliper_start is not None
    assert viewer._linear_caliper_start[0] == pytest.approx(10.0)
    assert viewer._linear_caliper_start[1] == pytest.approx(32.0)
    assert viewer._linear_caliper_line_item is not None
    assert viewer._linear_caliper_marker_item is not None

    _simulate_view_press(viewer, 50.0, 32.0)

    assert not viewer.is_linear_caliper_active
    assert viewer._linear_caliper_line_item is None
    assert viewer._persistent_linear_graphics
    assert emitted
    measurement = emitted[-1][0]
    assert measurement.label == "LVEDD"
    assert measurement.millimeter_length == pytest.approx(20.0)
    assert measurement.pixel_length == pytest.approx(40.0)


def test_all_diastole_sequence_auto_advances_without_enter(qtbot) -> None:
    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    viewer.show_frame(np.zeros((64, 64), dtype=np.uint8))
    viewer.set_state(_sample_state())

    emitted: list[list] = []
    viewer.linear_measurements_changed.connect(emitted.append)

    viewer.start_linear_caliper_sequence(("IVSd", "LVEDD", "LVPWd"))
    _place_caliper(viewer, 5.0, 15.0)
    _place_caliper(viewer, 10.0, 50.0)
    _place_caliper(viewer, 52.0, 60.0)

    assert not viewer.is_linear_caliper_active
    labels = {item.label for item in viewer._stored_linear_measurements.values()}
    assert labels == {"IVSd", "LVEDD", "LVPWd"}
    assert len(emitted[-1]) == 3


def test_caliper_button_starts_click_click_mode(qtbot) -> None:
    controller = AppController()
    controller.state_manager.set_instance(
        _sample_instance(),
        total_frames=10,
        frame_time_ms=33.3,
    )
    window = MainWindow(controller=controller)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    window._viewer.show_frame(np.zeros((64, 64), dtype=np.uint8))

    window._on_caliper_requested()

    assert window._viewer.is_linear_caliper_active
    assert "1-й клик" in window._viewer._measurement_label.text()


def test_main_window_panel_updates_after_click_click_caliper(qtbot) -> None:
    controller = AppController()
    controller.state_manager.set_instance(
        _sample_instance(),
        total_frames=10,
        frame_time_ms=33.3,
    )

    window = MainWindow(controller=controller)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    window._viewer.show_frame(np.zeros((64, 64), dtype=np.uint8))

    window._viewer.start_linear_caliper_for("LVEDD")
    _place_caliper(window._viewer, 10.0, 50.0)

    text = window._measurement_panel._summary_label.text()
    assert "Linear geometry" in text
    assert "LVEDD: 20.0 mm" in text


@pytest.fixture(scope="session", autouse=True)
def _qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app
