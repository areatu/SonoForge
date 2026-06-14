"""ED/ES hotkey and viewer indicator tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.domain.models import InstanceMetadata
from echo_personal_tool.presentation.main_window import MainWindow


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
    assert window._viewer.is_linear_caliper_active
    assert window._viewer._measurement_label.text().startswith("LVEDD:")
    assert "1-й клик" in window._viewer._measurement_label.text()

    qtbot.keyClick(window, Qt.Key.Key_Tab)
    assert window._viewer._measurement_label.text().startswith("LVESD:")
    assert "1-й клик" in window._viewer._measurement_label.text()

    qtbot.keyClick(window, Qt.Key.Key_Escape)
    assert not window._viewer.is_linear_caliper_active
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

    window._viewer.handle_contour_click((10.0, 40.0))
    window._viewer.handle_contour_click((50.0, 40.0))
    window._viewer.handle_contour_click((30.0, 10.0))

    qtbot.keyClick(window, Qt.Key.Key_Return)
    assert not window._viewer.is_contour_mode_active
    assert len(window._viewer.contours()) == 1
    contour = window._viewer.contours()[0]
    assert contour.phase == "ED"
    assert contour.is_open_arc
    assert contour.mitral_annulus == ((10.0, 40.0), (50.0, 40.0))
    assert len(contour.points) == 32

    qtbot.keyClick(window, Qt.Key.Key_C)
    assert window._viewer.is_contour_mode_active
    window._viewer.handle_contour_click((5.0, 5.0))
    qtbot.keyClick(window, Qt.Key.Key_Escape)
    assert not window._viewer.is_contour_mode_active
    assert len(window._viewer.contours()) == 1


def test_main_window_m_hotkey_works_when_viewer_has_focus(qtbot) -> None:
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
    window._viewer._graphics.setFocus()

    qtbot.keyClick(window._viewer._graphics, Qt.Key.Key_M)
    assert window._viewer.is_contour_mode_active
    assert window._viewer._contour_mode_kind == "model"

    assert window._viewer.handle_contour_click((10.0, 40.0))
    assert window._viewer.handle_contour_click((50.0, 40.0))
    assert window._viewer.handle_contour_click((30.0, 10.0))
    assert not window._viewer.is_contour_mode_active
    assert window._viewer.contours()[0].source == "model"


def test_main_window_i_hotkey_requests_auto_segment_in_2d_mode(qtbot) -> None:
    controller = AppController()
    controller.state_manager.set_instance(
        _sample_instance(),
        total_frames=10,
        frame_time_ms=33.3,
    )
    controller.request_auto_segment = MagicMock()

    window = MainWindow(controller=controller)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)

    qtbot.keyClick(window, Qt.Key.Key_I)
    controller.request_auto_segment.assert_called_once()


def test_main_window_i_hotkey_blocked_during_playback(qtbot) -> None:
    controller = AppController()
    controller.state_manager.set_instance(
        _sample_instance(),
        total_frames=10,
        frame_time_ms=33.3,
    )
    controller.set_playing(True)
    controller.request_auto_segment = MagicMock()

    window = MainWindow(controller=controller)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)

    qtbot.keyClick(window, Qt.Key.Key_I)
    controller.request_auto_segment.assert_not_called()


def test_main_window_i_hotkey_ignored_in_doppler_mode(qtbot) -> None:
    controller = AppController()
    controller.state_manager.set_instance(
        _sample_instance(),
        total_frames=10,
        frame_time_ms=33.3,
    )
    controller.request_auto_segment = MagicMock()

    window = MainWindow(controller=controller)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    window.set_view_mode("doppler")

    qtbot.keyClick(window, Qt.Key.Key_I)
    controller.request_auto_segment.assert_not_called()


@pytest.fixture(scope="session", autouse=True)
def _qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app
