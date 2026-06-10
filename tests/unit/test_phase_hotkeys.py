"""ED/ES hotkey and viewer indicator tests."""

from __future__ import annotations

from pathlib import Path

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


@pytest.fixture(scope="session", autouse=True)
def _qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app
