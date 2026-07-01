"""Tests for measurement workflow tool buttons."""

from __future__ import annotations

from pathlib import Path

from unittest.mock import MagicMock

import numpy as np
from PySide6.QtWidgets import QPushButton

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.domain.models import InstanceMetadata, ViewerState
from echo_personal_tool.presentation.main_window import MainWindow
from echo_personal_tool.presentation.measurement_tools_panel import MeasurementToolsPanel
from echo_personal_tool.presentation.tool_panel import ToolPanel
from echo_personal_tool.presentation.viewer_widget import ViewerWidget


def test_measurement_tools_panel_has_manual_and_mbs_buttons(qtbot) -> None:
    panel = MeasurementToolsPanel()
    qtbot.addWidget(panel)
    labels = {button.text() for button in panel.findChildren(QPushButton)}
    assert labels >= {
        "Калибровка",
        "Калипер",
        "Сброс",
        "КДР",
        "КСР",
        "КДО авто",
        "КСО авто",
        "МЖП-КДР-ЗСЛЖ (2D)",
        "КСР (2D)",
        "ЛП ПЗР",
        "ОЛП 4C",
        "ОЛП 2C",
        "ПП",
        "S ПП",
        "ОПП",
        "TAPSE",
        "ПЖ основание",
    }


def test_calibration_button_emits_signal(qtbot) -> None:
    panel = MeasurementToolsPanel()
    qtbot.addWidget(panel)
    received: list[bool] = []
    panel.calibration_requested.connect(lambda: received.append(True))
    for button in panel.findChildren(QPushButton):
        if button.text() == "Калибровка":
            button.click()
            break
    else:
        raise AssertionError("Calibration button not found")
    assert received == [True]


def test_lav_4c_starts_manual_contour(qtbot) -> None:
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

    window._on_lav_4c()

    assert window._viewer.is_contour_mode_active
    assert window._viewer._contour_mode_kind == "manual"
    assert window._viewer._active_contour_chamber == "LA"
    assert window._viewer._active_contour_view == "A4C"
    assert window._viewer._active_contour_phase == "ES"


def test_rav_4c_starts_manual_contour(qtbot) -> None:
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

    window._on_rav_volume()

    assert window._viewer.is_contour_mode_active
    assert window._viewer._contour_mode_kind == "manual"
    assert window._viewer._active_contour_chamber == "RA"
    assert window._viewer._active_contour_view == "A4C"
    assert window._viewer._active_contour_phase == "ES"


def test_reset_measurements_clears_controller_state(qtbot) -> None:
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
    controller.on_manual_calibration((0.5, 0.5))

    window._user_preferences.confirm_reset = False
    window._on_reset_measurements_requested()

    snapshot = controller.state_manager.snapshot
    assert snapshot.manual_pixel_spacing is None
    assert snapshot.contours == ()
    assert snapshot.linear_measurements == ()
    assert snapshot.measurement_snapshot is not None
    assert snapshot.measurement_snapshot.lvef is None
    assert snapshot.measurement_snapshot.la_simpson is None


def test_calibration_button_starts_caliper(qtbot) -> None:
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

    window._on_calibration_requested()

    assert window._viewer.is_calibration_active


def test_manual_4c_diastole_emits_a4c_ed(qtbot) -> None:
    panel = MeasurementToolsPanel()
    qtbot.addWidget(panel)
    received: list[tuple[str, str]] = []
    panel.manual_simpson_requested.connect(lambda v, p: received.append((v, p)))
    panel._manual_buttons[("4C", "ED")].click()
    assert received == [("A4C", "ED")]


def test_mbs_4c_edv_auto_emits_a4c_ed(qtbot) -> None:
    panel = MeasurementToolsPanel()
    qtbot.addWidget(panel)
    received: list[tuple[str, str]] = []
    panel.mbs_simpson_requested.connect(lambda v, p: received.append((v, p)))
    panel._mbs_buttons[("4C", "ED")].click()
    assert received == [("A4C", "ED")]


def test_es_prompt_blinks_target_button(qtbot) -> None:
    panel = MeasurementToolsPanel()
    qtbot.addWidget(panel)
    panel.start_es_prompt("manual", "4C")
    assert panel._blink_timer.isActive()
    panel.stop_es_prompt()
    assert not panel._blink_timer.isActive()


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


def test_manual_diastole_starts_manual_contour(qtbot) -> None:
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

    window._on_manual_simpson_requested("A4C", "ED")

    assert window._viewer.is_contour_mode_active
    assert window._viewer._contour_mode_kind == "manual"
    assert window._viewer._active_contour_view == "A4C"
    assert window._viewer._active_contour_phase == "ED"
    assert window._viewer._active_contour_chamber == "LV"


def test_mbs_edv_auto_starts_model_contour(qtbot) -> None:
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
    window._viewer.show_frame(np.zeros((64, 64), dtype=np.uint8))

    window._on_mbs_simpson_requested("A4C", "ED")

    controller.request_auto_segment.assert_called_once()
    assert controller._auto_segment_phase == "ED"
    assert controller._auto_segment_view == "A4C"
    assert "LV Auto" in window._viewer._frame_overlay_lines[0]
    assert not window._viewer.is_contour_mode_active


def test_ed_contour_completion_starts_es_prompt(qtbot, monkeypatch) -> None:
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

    window._on_manual_simpson_requested("A4C", "ED")
    window._viewer.handle_contour_click((10.0, 40.0))
    window._viewer.handle_contour_click((50.0, 40.0))
    window._viewer.handle_contour_click((30.0, 10.0))

    assert window._tool_panel.measure._menu._blink_timer.isActive()


def test_frame_overlay_clears_on_frame_change(qtbot) -> None:
    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    viewer.show()
    qtbot.waitExposed(viewer)
    viewer.show_frame(np.zeros((64, 64), dtype=np.uint8))
    viewer.append_frame_overlay("IVSd: 10.0 mm (20.0 px)")
    assert viewer._frame_overlay_lines
    assert viewer._overlay_label.isVisible()

    viewer.set_state(
        ViewerState(
            instance=_sample_instance(),
            current_frame_index=1,
            total_frames=10,
            frame_time_ms=33.3,
            is_playing=False,
        )
    )
    assert not viewer._overlay_label.isVisible()


def test_tool_panel_has_results_button_under_patient_metrics(qtbot) -> None:
    from echo_personal_tool.infrastructure.i18n import set_language
    set_language("ru")
    panel = ToolPanel()
    qtbot.addWidget(panel)
    labels = {button.text() for button in panel.findChildren(QPushButton)}
    assert "Измерения" in labels
    assert panel.measure._results_button.isVisibleTo(panel)
