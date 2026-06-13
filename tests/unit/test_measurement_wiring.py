"""End-to-end wiring tests for measurement panel updates."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.domain.models import InstanceMetadata, LinearMeasurement
from echo_personal_tool.domain.services.mbs_lite_service import fit_contour_from_landmarks
from echo_personal_tool.presentation.main_window import MainWindow


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


def test_main_window_measurement_panel_updates_after_contour(qtbot) -> None:
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

    ed = fit_contour_from_landmarks(
        septal=(10.0, 40.0),
        lateral=(50.0, 40.0),
        apex=(30.0, 10.0),
        phase="ED",
        view="A4C",
    )
    es = fit_contour_from_landmarks(
        septal=(12.0, 40.0),
        lateral=(48.0, 40.0),
        apex=(30.0, 15.0),
        phase="ES",
        view="A4C",
    )
    controller.on_contours_changed([ed, es])

    text = window._measurement_panel._summary_label.text()
    assert "Объёмы ЛЖ (Симпсон)" in text
    assert "КДО ЛЖ 4C" in text
    assert "ФВ ЛЖ" in text


def test_main_window_measurement_panel_updates_after_linear_caliper(qtbot) -> None:
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

    controller.on_linear_measurements_changed(
        [
            LinearMeasurement(label="LVEDD", pixel_length=100.0, millimeter_length=50.0),
        ]
    )

    text = window._measurement_panel._summary_label.text()
    assert "Linear geometry" in text
    assert "LVEDD: 50.0 mm" in text


@pytest.fixture(scope="session", autouse=True)
def _qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app
