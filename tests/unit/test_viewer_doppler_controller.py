"""Doppler ownership and lifecycle without constructing ViewerWidget."""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi
from echo_personal_tool.domain.services.doppler_calibration import calibration_from_roi_and_baseline
from tests.unit.doppler_fakes import FakeDopplerViewer


def test_calibration_state_is_normalized_and_emitted_for_current_frame() -> None:
    fake = FakeDopplerViewer(np.zeros((60, 80), dtype=np.uint8))
    events = []
    fake.controller.calibration_changed.connect(events.append)
    state = calibration_from_roi_and_baseline(
        DopplerSpectrogramRoi(x0=10, y0=5, width=200, height=200),
        100,
        velocity_span_cm_s=120,
        time_span_ms=800,
    )
    fake.controller.apply_calibration_state(state)
    actual = fake.controller.calibration_state
    assert actual is not None
    assert actual.roi.x1 <= 80 and actual.roi.y1 <= 60
    assert actual.baseline_y_px == 59
    assert fake.controller.calibration_matches_instance()
    assert events == [actual]
    fake.uid = None
    assert not fake.controller.calibration_matches_instance()


def test_syncing_suppresses_calibration_and_frame_signals() -> None:
    fake = FakeDopplerViewer(np.zeros((60, 80), dtype=np.uint8))
    seen = []
    fake.controller.calibration_changed.connect(seen.append)
    fake.controller.frame_changed.connect(seen.append)
    fake.syncing = True
    state = calibration_from_roi_and_baseline(
        DopplerSpectrogramRoi(x0=0, y0=0, width=80, height=60),
        30,
        velocity_span_cm_s=120,
        time_span_ms=800,
    )
    fake.controller.apply_calibration_state(state)
    fake.controller.on_frame_changed(3, 4)
    assert seen == []
    assert fake.controller.calibration_state is None
    assert "clear_contour" in fake.calls


def test_dicom_mode_and_user_override_have_one_owner() -> None:
    fake = FakeDopplerViewer()
    fake.controller.set_dicom_mode("PW")
    fake.controller.set_mode_override("CW")
    assert fake.controller.resolved_mode() == "CW"
    fake.controller.reset_mode_override()
    assert fake.controller.resolved_mode() == "PW"
    assert fake.overlay.set_doppler_mode.call_args.args == ("PW",)


def test_manual_calibration_starts_and_can_be_cancelled() -> None:
    fake = FakeDopplerViewer(np.zeros((60, 80), dtype=np.uint8))
    assert fake.controller.start_calibration()
    assert fake.calls[:2] == ["cancel", "clear_caliper"]
    assert fake.controller.calibration_in_progress
    assert fake.controller.cancel_calibration_step()
    assert not fake.controller.calibration_in_progress
    assert not fake.controller.cancel_calibration_step()


def test_caliper_uses_current_roi_and_falls_back_outside_it() -> None:
    fake = FakeDopplerViewer(np.zeros((60, 80), dtype=np.uint8))
    state = calibration_from_roi_and_baseline(
        DopplerSpectrogramRoi(x0=0, y0=0, width=80, height=60),
        30,
        velocity_span_cm_s=120,
        time_span_ms=800,
    )
    fake.controller.apply_calibration_state(state)
    measurement = fake.controller.caliper_measurement((10, 10), (30, 20), "Dist1")
    assert measurement is not None
    assert measurement.time_ms == pytest.approx(200)
    assert measurement.velocity_cm_s == pytest.approx(20)
    assert fake.controller.caliper_measurement((10, 10), (90, 20), "Dist1") is None
    assert fake.controller.caliper_measurement((10, 10), (30, 20), "TAPSE") is None


def test_dispose_disconnects_overlay_signals_and_is_idempotent() -> None:
    fake = FakeDopplerViewer()
    seen = []
    other_listener = []
    fake.controller.markers_changed.connect(seen.append)
    fake.signals.markers_changed.connect(other_listener.append)
    fake.signals.markers_changed.emit("first")
    fake.controller.dispose()
    fake.controller.dispose()
    fake.signals.markers_changed.emit("second")
    assert seen == ["first"]
    assert other_listener == ["first", "second"]


def test_frame_change_orders_signals_and_contour_cleanup() -> None:
    fake = FakeDopplerViewer(np.zeros((60, 80), dtype=np.uint8))
    fake.controller.frame_changing.connect(lambda frame, dto: fake.calls.append(f"before:{frame}"))
    fake.controller.frame_changed.connect(lambda frame: fake.calls.append(f"after:{frame}"))
    fake.controller.on_frame_changed(3, 4)
    assert fake.calls == ["before:3", "clear_contour", "after:4"]
    fake.overlay.clear_measurements.assert_called_once_with(keep_calibration_graphics=False)


def test_manual_wizard_completes_and_reports_velocity() -> None:
    from dataclasses import dataclass

    from PySide6.QtCore import Qt

    @dataclass
    class Click:
        x: float = 20.0
        y: float = 30.0

        def button(self):
            return Qt.MouseButton.LeftButton

    fake = FakeDopplerViewer(np.zeros((60, 80), dtype=np.uint8))
    fake.answers.append((40.0, True))
    completed = []
    fake.controller.spectral_calibration_completed.connect(completed.append)
    assert fake.controller.start_calibration()
    assert fake.controller.handle_calibration_click(Click())
    assert fake.active
    fake.controller.prompt_spectral_velocity_span(20.0)
    assert not fake.active
    assert fake.controller.is_velocity_calibrated()
    assert completed == [pytest.approx(120.0)]
