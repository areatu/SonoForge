"""ED/ES hotkey and viewer indicator tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.domain.models import InstanceMetadata
from echo_personal_tool.presentation.main_window import MainWindow
from echo_personal_tool.presentation.viewer_widget import ViewerWidget


def _sample_instance() -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid="1.2.3.4.5",
        series_uid="1.2.3.4.6",
        modality="US",
        number_of_frames=10,
        pixel_spacing=None,
        frame_time_ms=33.3,
        series_description="Test",
        path=Path("/tmp/test.dcm"),
    )


def test_viewer_widget_updates_ed_es_labels_on_state_change(qtbot) -> None:
    controller = AppController()
    viewer = ViewerWidget()
    controller.state_manager.state_changed.connect(viewer.set_state)

    controller.state_manager.set_instance(
        _sample_instance(),
        total_frames=10,
        frame_time_ms=33.3,
    )
    controller.state_manager.set_frame(4)
    controller.mark_ed()
    controller.state_manager.set_frame(7)
    controller.mark_es()

    assert viewer._ed_label.text() == "ED: 5"
    assert viewer._es_label.text() == "ES: 8"
    assert "ED @ 5" in viewer._timeline_slider.toolTip()
    assert "ES @ 8" in viewer._timeline_slider.toolTip()


def test_main_window_d_and_s_hotkeys_mark_phases(qtbot) -> None:
    controller = AppController()
    controller.state_manager.set_instance(
        _sample_instance(),
        total_frames=10,
        frame_time_ms=33.3,
    )
    controller.state_manager.set_frame(2)

    window = MainWindow(controller=controller)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)

    qtbot.keyClick(window, Qt.Key.Key_D)
    assert controller.state_manager.snapshot.ed_frame_index == 2

    controller.state_manager.set_frame(6)
    qtbot.keyClick(window, Qt.Key.Key_S)
    assert controller.state_manager.snapshot.es_frame_index == 6


def test_main_window_l_and_escape_toggle_linear_caliper(qtbot) -> None:
    controller = AppController()
    instance = InstanceMetadata(
        sop_instance_uid="1.2.3.4.5",
        series_uid="1.2.3.4.6",
        modality="US",
        number_of_frames=10,
        pixel_spacing=(0.5, 0.5),
        frame_time_ms=33.3,
        series_description="Test",
        path=Path("/tmp/test.dcm"),
    )
    controller.state_manager.set_instance(
        instance,
        total_frames=10,
        frame_time_ms=33.3,
    )

    window = MainWindow(controller=controller)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    window._viewer.show_frame(np.zeros((64, 64), dtype=np.uint8))

    qtbot.keyClick(window, Qt.Key.Key_L)
    assert window._viewer._linear_roi is not None
    assert window._viewer._measurement_label.text().startswith("LVEDD:")
    assert "mm (" in window._viewer._measurement_label.text()
    assert window._viewer._measurement_label.text().endswith("px)")

    qtbot.keyClick(window, Qt.Key.Key_Tab)
    assert window._viewer._measurement_label.text().startswith("LVESD:")

    qtbot.keyClick(window, Qt.Key.Key_Escape)
    assert window._viewer._linear_roi is None
    assert window._viewer._measurement_label.text() == "LVESD: —"


def test_main_window_c_enter_and_escape_control_contours(qtbot) -> None:
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

    qtbot.keyClick(window, Qt.Key.Key_C)
    assert window._viewer.is_contour_mode_active

    window._viewer.handle_contour_click((10.0, 10.0))
    window._viewer.handle_contour_click((20.0, 10.0))
    window._viewer.handle_contour_click((20.0, 20.0))

    qtbot.keyClick(window, Qt.Key.Key_Return)
    assert not window._viewer.is_contour_mode_active
    assert len(window._viewer.contours()) == 1
    assert window._viewer.contours()[0].phase == "ED"
    assert window._viewer.contours()[0].points == [
        (10.0, 10.0),
        (20.0, 10.0),
        (20.0, 20.0),
    ]

    qtbot.keyClick(window, Qt.Key.Key_C)
    assert window._viewer.is_contour_mode_active
    window._viewer.handle_contour_click((5.0, 5.0))
    qtbot.keyClick(window, Qt.Key.Key_Escape)
    assert not window._viewer.is_contour_mode_active
    assert len(window._viewer.contours()) == 1


@pytest.fixture(scope="session", autouse=True)
def _qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app
