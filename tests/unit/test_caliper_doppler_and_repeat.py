"""Caliper behavior tests: Doppler-zone measuring (Δt ms + velocity) and
scanner-like repeat mode (multiple measurements while the tool is armed).

Feature spec:
1. Inside a calibrated Doppler ROI the generic caliper measures the time
   interval (ms) and the velocity amplitude (cm/s or m/s) — e.g. AcT RVOT —
   instead of a B-mode distance. Moving the cursor back to the B-mode zone
   restores distance measuring.
2. While the caliper is armed, every click pair commits one measurement and
   immediately starts the next one (Dist1, Dist2, …) without pressing the
   button again. Measurements stay inside the file (instance) they were taken
   on and never migrate to other files.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

pytestmark = pytest.mark.gui
pytest.importorskip("pytestqt")

from PySide6.QtCore import QPointF, Qt  # noqa: E402

from echo_personal_tool.domain.models import InstanceMetadata  # noqa: E402
from echo_personal_tool.domain.models.doppler_roi import (  # noqa: E402
    DopplerCalibrationState,
    DopplerSpectrogramRoi,
)
from echo_personal_tool.domain.models.viewer_state import ViewerState  # noqa: E402
from echo_personal_tool.presentation.viewer_widget import ViewerWidget  # noqa: E402

# ── helpers ──────────────────────────────────────────────────────────

_FRAME = 200
_ROI = DopplerSpectrogramRoi(x0=50.0, y0=50.0, width=100.0, height=80.0)
_BASELINE_Y = 90.0
_TIME_SPAN_MS = 1000.0  # → 10 ms/px across the 100 px ROI
_VELOCITY_SPAN = 160.0  # → 2 cm/s per px across the 80 px ROI


def _make_viewer(qtbot) -> ViewerWidget:
    w = ViewerWidget()
    qtbot.addWidget(w)
    w.resize(640, 480)
    w.show()
    qtbot.waitExposed(w)
    return w


def _make_state(uid: str = "1.2.3.4.5.6") -> ViewerState:
    instance = InstanceMetadata(
        sop_instance_uid=uid,
        series_uid="1.2.3.4.5",
        modality="US",
        number_of_frames=1,
        pixel_spacing=(0.5, 0.5),
        frame_time_ms=33.3,
        series_description="Test",
        path=None,
        media_format="dicom",
    )
    return ViewerState(
        instance=instance,
        current_frame_index=0,
        total_frames=1,
        frame_time_ms=33.3,
        is_playing=False,
    )


def _make_doppler_viewer(qtbot) -> ViewerWidget:
    """Viewer with a frame, an instance and a calibrated Doppler ROI."""
    w = _make_viewer(qtbot)
    w.show_frame(np.zeros((_FRAME, _FRAME), dtype=np.uint8))
    w.set_state(_make_state())
    state = DopplerCalibrationState(
        roi=_ROI,
        baseline_y_px=_BASELINE_Y,
        time_span_ms=_TIME_SPAN_MS,
        velocity_span_cm_s=_VELOCITY_SPAN,
    )
    w.apply_doppler_calibration_state(state, persist=False)
    return w


def _simulate_view_press(viewer: ViewerWidget, x: float, y: float) -> None:
    scene_pos = viewer._view.mapViewToScene(QPointF(x, y))
    ev = MagicMock()
    ev.button.return_value = Qt.MouseButton.LeftButton
    ev.scenePos.return_value = scene_pos
    assert viewer._handle_linear_caliper_mouse_press(ev)


def _place_caliper(viewer: ViewerWidget, start: tuple[float, float], end: tuple[float, float]) -> None:
    _simulate_view_press(viewer, *start)
    _simulate_view_press(viewer, *end)


# ═══════════════════════════════════════════════════════════════════
#  Feature 1 — caliper inside the Doppler ROI: Δt (ms) + velocity
# ═══════════════════════════════════════════════════════════════════


class TestDopplerZoneCaliper:
    def test_inside_roi_measures_time_and_velocity(self, qtbot) -> None:
        w = _make_doppler_viewer(qtbot)
        emitted: list[list] = []
        w.linear_measurements_changed.connect(emitted.append)

        w.activate_generic_dist_caliper()
        # AcT-style: onset at the baseline, peak 10 px later and 20 px above.
        _place_caliper(w, (60.0, _BASELINE_Y), (70.0, 70.0))

        measurement = emitted[-1][0]
        assert measurement.doppler is True
        assert measurement.time_ms == pytest.approx(100.0)  # 10 px * 10 ms/px
        assert measurement.velocity_cm_s == pytest.approx(40.0)  # 20 px * 2 cm/s/px
        assert measurement.millimeter_length is None
        text = measurement.display_text()
        assert "100.0 ms" in text
        assert "40.0 cm/s" in text
        assert "mm" not in text

    def test_high_velocity_displays_m_per_s(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((_FRAME, _FRAME), dtype=np.uint8))
        w.set_state(_make_state())
        # Steeper velocity scale: 320 cm/s over 80 px → 4 cm/s per px.
        state = DopplerCalibrationState(
            roi=_ROI,
            baseline_y_px=_BASELINE_Y,
            time_span_ms=_TIME_SPAN_MS,
            velocity_span_cm_s=320.0,
        )
        w.apply_doppler_calibration_state(state, persist=False)
        emitted: list[list] = []
        w.linear_measurements_changed.connect(emitted.append)

        w.activate_generic_dist_caliper()
        # 30 px above baseline → 120 cm/s → must switch to m/s.
        _place_caliper(w, (60.0, _BASELINE_Y), (70.0, 60.0))

        measurement = emitted[-1][0]
        assert measurement.velocity_cm_s == pytest.approx(120.0)
        assert "1.20 m/s" in measurement.display_text()
        assert "cm/s" not in measurement.display_text()

    def test_outside_roi_measures_distance(self, qtbot) -> None:
        w = _make_doppler_viewer(qtbot)
        emitted: list[list] = []
        w.linear_measurements_changed.connect(emitted.append)

        w.activate_generic_dist_caliper()
        # Both points in the B-mode zone (upper-left, outside the ROI).
        _place_caliper(w, (10.0, 10.0), (30.0, 10.0))

        measurement = emitted[-1][0]
        assert measurement.doppler is False
        assert measurement.velocity_cm_s is None
        assert measurement.time_ms is None
        assert measurement.millimeter_length == pytest.approx(10.0)  # 20 px * 0.5 mm
        assert "mm" in measurement.display_text()

    def test_second_point_back_in_bmode_restores_distance(self, qtbot) -> None:
        w = _make_doppler_viewer(qtbot)
        emitted: list[list] = []
        w.linear_measurements_changed.connect(emitted.append)

        w.activate_generic_dist_caliper()
        # Start inside the Doppler ROI, finish in the B-mode zone.
        _place_caliper(w, (60.0, 80.0), (10.0, 10.0))

        measurement = emitted[-1][0]
        assert measurement.doppler is False
        assert measurement.millimeter_length is not None

    def test_preview_switches_units_with_cursor_zone(self, qtbot) -> None:
        w = _make_doppler_viewer(qtbot)
        w.activate_generic_dist_caliper()

        start = (60.0, _BASELINE_Y)
        # Cursor inside the ROI → live preview in ms + cm/s.
        w._update_linear_caliper_label_preview(start, (70.0, 70.0))
        inside_text = w._measurement_label.text()
        assert "ms" in inside_text and "cm/s" in inside_text
        # Cursor moved to the B-mode zone → preview back to distance.
        w._update_linear_caliper_label_preview(start, (10.0, 10.0))
        outside_text = w._measurement_label.text()
        assert "ms" not in outside_text
        assert "mm" in outside_text

    def test_time_only_calibration_shows_ms_without_velocity(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((_FRAME, _FRAME), dtype=np.uint8))
        w.set_state(_make_state())
        state = DopplerCalibrationState(
            roi=_ROI,
            baseline_y_px=_BASELINE_Y,
            time_span_ms=_TIME_SPAN_MS,
            velocity_span_cm_s=0.0,
        )
        w.apply_doppler_calibration_state(state, persist=False)
        emitted: list[list] = []
        w.linear_measurements_changed.connect(emitted.append)

        w.activate_generic_dist_caliper()
        _place_caliper(w, (60.0, _BASELINE_Y), (75.0, _BASELINE_Y))

        measurement = emitted[-1][0]
        assert measurement.doppler is True
        assert measurement.time_ms == pytest.approx(150.0)
        assert measurement.velocity_cm_s is None
        text = measurement.display_text()
        assert "150.0 ms" in text
        # Doppler Δt must not render the M-mode HR line.
        assert "ЧСС" not in text and "HR" not in text

    def test_anatomical_label_inside_roi_stays_distance(self, qtbot) -> None:
        w = _make_doppler_viewer(qtbot)
        emitted: list[list] = []
        w.linear_measurements_changed.connect(emitted.append)

        # Anatomical calipers (IVSd, LVEDD, …) keep B-mode semantics.
        w.start_linear_caliper_for("LVEDD")
        _place_caliper(w, (60.0, _BASELINE_Y), (70.0, 70.0))

        measurement = emitted[-1][0]
        assert measurement.doppler is False
        assert measurement.millimeter_length is not None

    def test_doppler_caliper_survives_endpoint_drag(self, qtbot) -> None:
        w = _make_doppler_viewer(qtbot)
        w.activate_generic_dist_caliper()
        _place_caliper(w, (60.0, _BASELINE_Y), (70.0, 70.0))
        measurement = w._stored_linear_measurements[("Dist1", 0)]
        assert measurement.doppler is True

        # Disarm the repeat caliper first — node dragging works on idle calipers.
        w.toggle_linear_caliper()
        # Drag the end node deeper into the ROI → recompute in Doppler mode.
        key = ("Dist1", 0)
        w._begin_caliper_node_drag(key, 1, *measurement.end)
        w._apply_caliper_node_drag(80.0, 60.0)
        w._finish_caliper_node_drag()
        updated = w._stored_linear_measurements[key]
        assert updated.doppler is True
        assert updated.time_ms == pytest.approx(200.0)  # 60→80 px = 20 px * 10 ms
        assert updated.velocity_cm_s == pytest.approx(60.0)  # 30 px * 2 cm/s/px


# ═══════════════════════════════════════════════════════════════════
#  Feature 2 — repeat mode: many measurements while the tool is armed
# ═══════════════════════════════════════════════════════════════════


class TestCaliperRepeatMode:
    def test_multiple_measurements_without_reactivation(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((_FRAME, _FRAME), dtype=np.uint8))
        w.set_state(_make_state())
        emitted: list[list] = []
        w.linear_measurements_changed.connect(emitted.append)

        w.activate_generic_dist_caliper()
        assert w.is_caliper_repeat_mode

        _place_caliper(w, (10.0, 10.0), (30.0, 10.0))
        # Still armed — the next click pair starts Dist2 right away.
        assert w.is_linear_caliper_active
        assert w._current_caliper_label() == "Dist2"
        _place_caliper(w, (10.0, 20.0), (50.0, 20.0))
        assert w.is_linear_caliper_active
        assert w._current_caliper_label() == "Dist3"
        _place_caliper(w, (10.0, 30.0), (70.0, 30.0))

        labels = sorted(m.label for m in w._stored_linear_measurements.values())
        assert labels == ["Dist1", "Dist2", "Dist3"]
        assert len(emitted[-1]) == 3
        # All results are visible on the frame overlay at once.
        overlay = "\n".join(w._frame_overlay_lines)
        assert "Dist1" in overlay and "Dist2" in overlay and "Dist3" in overlay

    def test_toggle_switches_caliper_off(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((_FRAME, _FRAME), dtype=np.uint8))
        w.set_state(_make_state())

        w.toggle_linear_caliper()  # arm
        assert w.is_caliper_repeat_mode
        _place_caliper(w, (10.0, 10.0), (30.0, 10.0))
        assert w.is_linear_caliper_active
        w.toggle_linear_caliper()  # disarm
        assert not w.is_linear_caliper_active
        assert not w.is_caliper_repeat_mode
        # Committed measurements are kept.
        assert ("Dist1", 0) in w._stored_linear_measurements

    def test_escape_disarms_repeat_caliper(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((_FRAME, _FRAME), dtype=np.uint8))
        w.set_state(_make_state())

        w.activate_generic_dist_caliper()
        w.cancel_active_tool()
        assert not w.is_linear_caliper_active
        assert not w.is_caliper_repeat_mode

    def test_anatomical_caliper_stays_single_shot(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((_FRAME, _FRAME), dtype=np.uint8))
        w.set_state(_make_state())

        w.start_linear_caliper_for("IVSd")
        assert not w.is_caliper_repeat_mode
        _place_caliper(w, (10.0, 10.0), (30.0, 10.0))
        assert not w.is_linear_caliper_active

    def test_measurements_stay_inside_their_file(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((_FRAME, _FRAME), dtype=np.uint8))
        w.set_state(_make_state(uid="1.2.3.A"))

        w.activate_generic_dist_caliper()
        _place_caliper(w, (10.0, 10.0), (30.0, 10.0))
        _place_caliper(w, (10.0, 20.0), (50.0, 20.0))
        assert len(w._stored_linear_measurements) == 2
        assert all(m.sop_instance_uid == "1.2.3.A" for m in w._stored_linear_measurements.values())

        # Switch to another file: the calipers and the armed tool are gone.
        w.set_state(_make_state(uid="1.2.3.B"))
        assert w._stored_linear_measurements == {}
        assert not w.is_linear_caliper_active
        assert w.dist_caliper_serial == 1

        # Measuring on the new file starts from Dist1 and is tagged with B.
        w.activate_generic_dist_caliper()
        _place_caliper(w, (10.0, 10.0), (30.0, 10.0))
        assert len(w._stored_linear_measurements) == 1
        measurement = next(iter(w._stored_linear_measurements.values()))
        assert measurement.label == "Dist1"
        assert measurement.sop_instance_uid == "1.2.3.B"


# ═══════════════════════════════════════════════════════════════════
#  Main window wiring — the Caliper button toggles the repeat mode
# ═══════════════════════════════════════════════════════════════════


class TestMainWindowCaliperButton:
    def _make_window(self, qtbot, synthetic_dicom_path):
        from echo_personal_tool.application.app_controller import AppController
        from echo_personal_tool.presentation.main_window import MainWindow

        controller = AppController()
        controller.state_manager.set_instance(
            InstanceMetadata(
                sop_instance_uid="1.2.3.4.5",
                series_uid="1.2.3.4.6",
                modality="US",
                number_of_frames=10,
                pixel_spacing=(0.5, 0.5),
                frame_time_ms=33.3,
                series_description="Test",
                path=synthetic_dicom_path,
            ),
            total_frames=10,
            frame_time_ms=33.3,
        )
        window = MainWindow(controller=controller)
        qtbot.addWidget(window)
        window.show()
        qtbot.waitExposed(window)
        window._viewer.show_frame(np.zeros((_FRAME, _FRAME), dtype=np.uint8))
        return window

    def test_button_arms_then_disarms(self, qtbot, synthetic_dicom_path) -> None:
        window = self._make_window(qtbot, synthetic_dicom_path)
        viewer = window._viewer

        window._on_caliper_requested()
        assert viewer.is_linear_caliper_active
        assert viewer.is_caliper_repeat_mode

        _place_caliper(viewer, (10.0, 10.0), (30.0, 10.0))
        # One measurement committed — the tool is still armed for the next one.
        assert viewer.is_linear_caliper_active

        window._on_caliper_requested()
        assert not viewer.is_linear_caliper_active
        assert not viewer.is_caliper_repeat_mode

    def test_labeled_caliper_from_menu_stays_single_shot(self, qtbot, synthetic_dicom_path) -> None:
        window = self._make_window(qtbot, synthetic_dicom_path)
        viewer = window._viewer

        window._on_caliper_requested("RVOT")
        assert viewer.is_linear_caliper_active
        assert not viewer.is_caliper_repeat_mode
        _place_caliper(viewer, (10.0, 10.0), (30.0, 10.0))
        assert not viewer.is_linear_caliper_active
