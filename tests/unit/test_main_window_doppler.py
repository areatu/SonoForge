"""MainWindow Doppler integration tests (single ViewerWidget)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.domain.models import InstanceMetadata, SeriesMetadata, StudyMetadata
from echo_personal_tool.presentation.main_window import MainWindow

pytestmark = pytest.mark.gui


def _make_window(qtbot) -> MainWindow:
    window = MainWindow(controller=AppController())
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    return window


def _build_study(total_instances: int = 8) -> StudyMetadata:
    instances = tuple(
        InstanceMetadata(
            sop_instance_uid=f"main-window-uid-{index}",
            series_uid="main-window-series-1",
            modality="US",
            number_of_frames=10,
            pixel_spacing=None,
            frame_time_ms=33.3,
            series_description="A4C",
            path=Path(f"/tmp/main-window-uid-{index}.dcm"),
            media_format="dicom",
        )
        for index in range(total_instances)
    )
    series = SeriesMetadata(
        series_uid="main-window-series-1",
        study_uid="main-window-study-1",
        modality="US",
        description="A4C",
        instances=instances,
    )
    return StudyMetadata(
        study_uid="main-window-study-1",
        study_datetime=datetime(2026, 6, 13, 12, 0, 0),
        series=(series,),
    )


def test_main_window_has_integrated_viewer_and_tool_panel(qtbot) -> None:
    window = _make_window(qtbot)
    assert window._system_bar is not None
    assert window._viewer is not None
    assert window._tool_panel is not None


def test_frame_loaded_updates_viewer(qtbot) -> None:
    window = _make_window(qtbot)

    frame_2d = np.full((4, 5), 3, dtype=np.uint8)
    window._on_frame_loaded(frame_2d)
    assert window._viewer._current_frame is not None
    assert window._viewer._current_frame.shape == (4, 5)

    doppler_frame = np.full((3, 7), 9, dtype=np.uint8)
    window._on_frame_loaded(doppler_frame)
    assert window._viewer._current_frame is not None
    assert window._viewer._current_frame.shape == (3, 7)


def test_m_hotkey_starts_model_contour_in_bmode(qtbot) -> None:
    window = _make_window(qtbot)
    window._viewer.show_frame(np.zeros((64, 64), dtype=np.uint8))

    qtbot.keyClick(window, Qt.Key.Key_M)

    assert window._viewer.is_contour_mode_active
    assert window._viewer._contour_mode_kind == "model"


def test_doppler_hotkeys_require_time_calibration(qtbot, monkeypatch) -> None:
    window = _make_window(qtbot)
    window._viewer.show_frame(np.zeros((64, 64), dtype=np.uint8))
    monkeypatch.setattr(window._viewer, "is_doppler_time_calibrated", lambda: True)

    qtbot.keyClick(window, Qt.Key.Key_T)
    assert window._viewer.get_doppler_tool_mode() == "interval"
    qtbot.keyClick(window, Qt.Key.Key_V)
    assert window._viewer.get_doppler_tool_mode() == "trace"


def test_escape_and_enter_delegate_to_active_doppler_tool(qtbot, monkeypatch) -> None:
    window = _make_window(qtbot)
    window._viewer.show_frame(np.zeros((64, 64), dtype=np.uint8))
    window._viewer.set_doppler_tool_mode("trace")

    finish_calls: list[bool] = []
    cancel_calls: list[bool] = []

    monkeypatch.setattr(
        window._viewer,
        "finish_doppler_trace",
        lambda: finish_calls.append(True) or True,
    )
    monkeypatch.setattr(
        window._viewer._doppler,
        "cancel_active_tool",
        lambda: cancel_calls.append(True) or True,
    )

    qtbot.keyClick(window, Qt.Key.Key_Return)
    qtbot.keyClick(window, Qt.Key.Key_Escape)

    assert finish_calls == [True]
    assert cancel_calls == [True]


def test_studies_loaded_requests_visible_previews_once_in_real_flow(qtbot, monkeypatch) -> None:
    window = _make_window(qtbot)
    window._browser.resize(320, 260)
    window._browser.show()
    qtbot.waitExposed(window._browser)

    call_count = 0
    original_request_visible_previews = window._browser.request_visible_previews

    def counted_request_visible_previews(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return original_request_visible_previews(*args, **kwargs)

    monkeypatch.setattr(
        window._browser,
        "request_visible_previews",
        counted_request_visible_previews,
    )
    # First-frame autoload performs a real load of the synthetic study. Its
    # files do not exist, so the load fails: stub the failure dialog (a modal
    # QMessageBox would block headless CI forever) and assert the load was
    # actually attempted.
    warnings: list[tuple] = []

    def fake_warning(*args, **kwargs):
        warnings.append(args)
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "warning", fake_warning)
    window._on_studies_loaded([_build_study()])
    assert call_count == 1
    # The failing decode runs in a worker thread: wait until its failure
    # warning is delivered (stubbed above, so no modal loop can block us).
    qtbot.waitUntil(lambda: bool(warnings), timeout=10000)
    assert warnings


def test_doppler_heart_rate_menu_rejects_uncalibrated_time(qtbot, monkeypatch) -> None:
    from echo_personal_tool.infrastructure.i18n import tr
    from echo_personal_tool.presentation.measurement_action import MeasurementAction

    window = _make_window(qtbot)
    window._viewer.show_frame(np.zeros((64, 64), dtype=np.uint8))
    messages = []
    monkeypatch.setattr(window, "_show_status", messages.append)

    window._on_measure_action(MeasurementAction.DOPPLER_INTERVAL, "A4C", "ED", "RR")

    assert window._viewer.get_doppler_tool_mode() == "none"
    assert messages[-1] == tr("status.doppler_no_time")


def test_doppler_heart_rate_menu_to_result_without_velocity_scale(qtbot, sample_instance_metadata) -> None:
    from echo_personal_tool.domain.models.doppler_roi import DopplerCalibrationState, DopplerSpectrogramRoi
    from echo_personal_tool.domain.services.report_builder import build_report_document
    from echo_personal_tool.infrastructure.i18n import tr

    controller = AppController()
    controller.state_manager.set_instance(sample_instance_metadata, total_frames=4, frame_time_ms=40.0)
    window = MainWindow(controller=controller)
    qtbot.addWidget(window)
    viewer = window._viewer
    viewer.show_frame(np.zeros((200, 1000), dtype=np.uint8))
    viewer.apply_doppler_calibration_state(
        DopplerCalibrationState(
            roi=DopplerSpectrogramRoi(0.0, 0.0, 1000.0, 200.0),
            baseline_y_px=110.0,
            time_span_ms=2000.0,
            time_from_dicom_tags=True,
            velocity_span_cm_s=0.0,
        ),
        persist=False,
    )
    window._sync_doppler_tool_availability()
    menu = window._tool_panel.measure._menu
    button = next(button for button, spec in menu._tool_buttons if spec.doppler_interval == "RR")

    assert viewer.is_doppler_time_calibrated()
    assert not viewer.is_doppler_velocity_calibrated()
    assert button.isEnabled()
    button.click()
    assert viewer._measurement_label.text() == tr("status.doppler_heart_rate_tool")
    assert viewer._doppler.handle_click(100.0, 20.0)
    assert viewer._doppler.handle_click(500.0, 80.0)

    snapshot = controller.state_manager.snapshot.measurement_snapshot
    assert snapshot.display_doppler.heart_rate_bpm == pytest.approx(75.0)
    assert "75" in viewer.results_overlay_text()
    assert tr("result.doppler_heart_rate") in viewer.results_overlay_text()
    report = build_report_document(controller.compute_study_snapshot())
    assert any(value.label == tr("result.doppler_heart_rate") for group in report.groups for value in group.values)
