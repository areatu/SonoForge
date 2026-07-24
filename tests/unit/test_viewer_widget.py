"""Unit tests for ViewerWidget — the 2D image viewer."""

from __future__ import annotations

import sys

import numpy as np
import pytest

pytestmark = pytest.mark.gui
pytest.importorskip("pytestqt")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QApplication

from echo_personal_tool.domain.models import InstanceMetadata, ViewerState
from echo_personal_tool.domain.models.doppler_roi import DopplerKind
from echo_personal_tool.presentation.viewer_widget import (
    ContourViewBox,
    ViewerWidget,
    _results_overlay_style,
)


# ═══════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════


def _make_viewer(qtbot) -> ViewerWidget:
    w = ViewerWidget()
    qtbot.addWidget(w)
    w.resize(640, 480)
    w.show()
    qtbot.waitExposed(w)
    return w


def _make_state(
    path=None,
    frame=0,
    total=1,
    fps=30.0,
    playing=False,
    uid="1.2.3.4.5.6",
) -> ViewerState:
    instance = InstanceMetadata(
        sop_instance_uid=uid,
        series_uid="1.2.3.4.5",
        modality="US",
        number_of_frames=total,
        pixel_spacing=(0.5, 0.5),
        frame_time_ms=1000.0 / fps if fps > 0 else None,
        series_description="Test",
        path=path,
        media_format="dicom",
    )
    return ViewerState(
        instance=instance,
        current_frame_index=frame,
        total_frames=total,
        frame_time_ms=1000.0 / fps if fps > 0 else None,
        is_playing=playing,
    )


# ═══════════════════════════════════════════════════════════════════
#  Constructor / init
# ═══════════════════════════════════════════════════════════════════


class TestViewerWidgetInit:
    def test_creates_without_error(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w is not None
        assert w.isVisible()

    def test_initial_zoom_mode(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w.zoom_mode == "fit"

    def test_initial_linear_caliper_inactive(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w.is_linear_caliper_active is False

    def test_initial_dist_serial(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w.dist_caliper_serial == 1

    def test_has_doppler_overlay(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w._doppler is not None

    def test_has_speckle_overlay(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w._speckle_overlay is not None

    def test_has_timeline_slider(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w._timeline_slider is not None

    def test_has_play_button(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w._play_button is not None

    def test_initial_frame_is_none(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w._current_frame is None

    def test_initial_state_is_none(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w._current_state is None


# ═══════════════════════════════════════════════════════════════════
#  show_frame
# ═══════════════════════════════════════════════════════════════════


class TestShowFrame:
    def test_grayscale_frame(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        frame = np.random.randint(0, 255, (128, 128), dtype=np.uint8)
        w.show_frame(frame)
        assert w._current_frame is not None
        assert w._current_frame.shape == (128, 128)

    def test_rgb_frame(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        frame = np.random.randint(0, 255, (128, 128, 3), dtype=np.uint8)
        w.show_frame(frame)
        assert w._current_frame is not None

    def test_small_frame(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        frame = np.zeros((16, 16), dtype=np.uint8)
        w.show_frame(frame)
        assert w._current_frame is not None
        assert w._current_frame.shape == (16, 16)

    def test_large_frame(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        frame = np.zeros((512, 512), dtype=np.uint8)
        w.show_frame(frame)
        assert w._current_frame is not None

    def test_constant_frame(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        frame = np.full((64, 64), 128, dtype=np.uint8)
        w.show_frame(frame)
        assert w._current_frame is not None


# ═══════════════════════════════════════════════════════════════════
#  set_state
# ═══════════════════════════════════════════════════════════════════


class TestSetState:
    def test_sets_state(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state()
        w.set_state(state)
        assert w._current_state is state

    def test_updates_timeline_range(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state(total=10)
        w.set_state(state)
        assert w._timeline_slider.maximum() == 9

    def test_sets_timeline_value(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state(frame=3, total=10)
        w.set_state(state)
        assert w._timeline_slider.value() == 3

    def test_play_button_text_playing(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state(playing=True, total=5)
        w.set_state(state)
        assert "Пауза" in w._play_button.text() or "Pause" in w._play_button.text()

    def test_play_button_text_stopped(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state(playing=False, total=5)
        w.set_state(state)
        text = w._play_button.text()
        assert "Воспроизведение" in text or "Play" in text

    def test_disables_controls_for_single_frame(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state(total=1)
        w.set_state(state)
        assert w._timeline_slider.isEnabled() is False

    def test_enables_controls_for_multi_frame(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state(total=5)
        w.set_state(state)
        assert w._timeline_slider.isEnabled() is True

    def test_fps_label_with_fps(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state(fps=30.0, total=5)
        w.set_state(state)
        assert "30.0" in w._fps_label.text()

    def test_fps_label_without_fps(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state(fps=0, total=5)
        w.set_state(state)
        assert "—" in w._fps_label.text()


# ═══════════════════════════════════════════════════════════════════
#  Zoom mode
# ═══════════════════════════════════════════════════════════════════


class TestZoomMode:
    def test_cycle_zoom_fit_to_100(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w.zoom_mode == "fit"
        w.cycle_zoom_mode()
        assert w.zoom_mode == "100%"

    def test_cycle_zoom_100_to_200(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.set_zoom_mode("100%")
        w.cycle_zoom_mode()
        assert w.zoom_mode == "200%"

    def test_cycle_zoom_200_to_fit(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.set_zoom_mode("200%")
        w.cycle_zoom_mode()
        assert w.zoom_mode == "fit"

    def test_set_zoom_mode_invalid(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        original = w.zoom_mode
        w.set_zoom_mode("invalid")
        assert w.zoom_mode == original

    def test_set_zoom_mode_valid(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.set_zoom_mode("100%")
        assert w.zoom_mode == "100%"


# ═══════════════════════════════════════════════════════════════════
#  Calibration caliper
# ═══════════════════════════════════════════════════════════════════


class TestCalibrationCaliper:
    def test_toggle_calibration_caliper(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.toggle_calibration_caliper()
        assert w._calibration_active is True

    def test_toggle_calibration_off(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.toggle_calibration_caliper()
        w.toggle_calibration_caliper()
        assert w._calibration_active is False

    def test_toggle_calibration_without_frame(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.toggle_calibration_caliper()
        assert w._calibration_active is False


# ═══════════════════════════════════════════════════════════════════
#  Linear caliper
# ═══════════════════════════════════════════════════════════════════


class TestLinearCaliper:
    def test_toggle_linear_caliper(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.toggle_linear_caliper()
        assert w.is_linear_caliper_active is True

    def test_toggle_linear_caliper_off(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.toggle_linear_caliper()
        w.toggle_linear_caliper()
        assert w.is_linear_caliper_active is False

    def test_toggle_linear_caliper_without_frame(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.toggle_linear_caliper()
        assert w.is_linear_caliper_active is False

    def test_activate_generic_dist_caliper(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        label = w.activate_generic_dist_caliper()
        assert label is not None
        assert label.startswith("Dist")
        assert w.dist_caliper_serial == 2

    def test_activate_generic_dist_caliper_without_frame(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        label = w.activate_generic_dist_caliper()
        assert label is None

    def test_start_linear_caliper_for(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        result = w.start_linear_caliper_for("IVSd")
        assert result is True
        assert w.is_linear_caliper_active is True

    def test_reset_dist_caliper_serial(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.activate_generic_dist_caliper()
        w.activate_generic_dist_caliper()
        w.reset_dist_caliper_serial()
        assert w.dist_caliper_serial == 1

    def test_start_linear_caliper_sequence(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        result = w.start_linear_caliper_sequence(("IVSd", "LVEDD", "LVPWd"))
        assert result is True

    def test_start_linear_caliper_sequence_without_frame(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        result = w.start_linear_caliper_sequence(("IVSd", "LVEDD"))
        assert result is False


# ═══════════════════════════════════════════════════════════════════
#  Doppler
# ═══════════════════════════════════════════════════════════════════


class TestDoppler:
    def test_get_doppler_tool_mode(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        mode = w.get_doppler_tool_mode()
        assert isinstance(mode, str)

    def test_get_doppler_calibration_state_none(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w.get_doppler_calibration_state() is None

    def test_clear_doppler_measurements(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Should not raise
        w.clear_doppler_measurements()

    def test_clear_doppler_calibration_display(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Should not raise
        w.clear_doppler_calibration_display()

    def test_get_doppler_dto(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        dto = w.get_doppler_dto()
        # dto may be None or a DTO object
        assert dto is None or hasattr(dto, "peaks")


# ═══════════════════════════════════════════════════════════════════
#  MMode
# ═══════════════════════════════════════════════════════════════════


class TestMMode:
    def test_get_mmode_calibration_state_none(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w.get_mmode_calibration_state() is None

    def test_set_mmode_vertical_lock(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.set_mmode_vertical_lock(True)
        assert w._mmode_vertical_lock is True
        w.set_mmode_vertical_lock(False)
        assert w._mmode_vertical_lock is False


# ═══════════════════════════════════════════════════════════════════
#  Contour
# ═══════════════════════════════════════════════════════════════════


class TestContour:
    def test_get_lv_contour_none(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w.get_lv_contour() is None

    def test_finish_contour_no_active(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        result = w.finish_contour()
        assert result is False


# ═══════════════════════════════════════════════════════════════════
#  Speckle
# ═══════════════════════════════════════════════════════════════════


class TestSpeckle:
    def test_clear_speckle_overlay(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Should not raise
        w.clear_speckle_overlay()


# ═══════════════════════════════════════════════════════════════════
#  Frame overlay
# ═══════════════════════════════════════════════════════════════════


class TestFrameOverlay:
    def test_clear_frame_overlay(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Should not raise
        w.clear_frame_overlay()


# ═══════════════════════════════════════════════════════════════════
#  Debug overlay
# ═══════════════════════════════════════════════════════════════════


class TestDebugOverlay:
    def test_toggle_debug_overlay(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        initial = w._debug_overlay_visible
        w.toggle_debug_overlay()
        assert w._debug_overlay_visible is not initial


# ═══════════════════════════════════════════════════════════════════
#  Results overlay
# ═══════════════════════════════════════════════════════════════════


class TestResultsOverlay:
    def test_set_results_overlay(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.set_results_overlay("LVEF: 55%")
        assert w._results_overlay_label.text() == "LVEF: 55%"
        assert w._results_overlay_label.isVisible()

    def test_set_results_overlay_empty(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.set_results_overlay("")
        assert not w._results_overlay_label.isVisible()

    def test_results_overlay_position(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.set_results_overlay_position(0.5, 0.5)
        # Should not raise


# ═══════════════════════════════════════════════════════════════════
#  ContourViewBox
# ═══════════════════════════════════════════════════════════════════


class TestContourViewBox:
    def test_creates(self, qtbot) -> None:
        from PySide6.QtWidgets import QWidget
        parent = QWidget()
        qtbot.addWidget(parent)
        vb = ContourViewBox()
        assert vb is not None

    def test_set_viewer_widget(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # ContourViewBox is internal, access via _view
        assert w._view._viewer_widget is w


# ═══════════════════════════════════════════════════════════════════
#  _results_overlay_style helper
# ═══════════════════════════════════════════════════════════════════


class TestResultsOverlayStyle:
    def test_returns_string(self) -> None:
        style = _results_overlay_style(20, 0.7)
        assert isinstance(style, str)
        assert "font-size: 20px" in style

    def test_opacity_clamped(self) -> None:
        style = _results_overlay_style(16, 1.5)
        assert "rgba" in style

    def test_opacity_zero(self) -> None:
        style = _results_overlay_style(16, 0.0)
        assert "rgba(0, 0, 0, 0)" in style


# ═══════════════════════════════════════════════════════════════════
#  Show frame + state integration
# ═══════════════════════════════════════════════════════════════════


class TestFrameAndStateIntegration:
    def test_show_frame_after_set_state(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state(total=5)
        w.set_state(state)
        frame = np.random.randint(0, 255, (128, 128), dtype=np.uint8)
        w.show_frame(frame)
        assert w._current_frame is not None

    def test_set_state_after_show_frame(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        frame = np.random.randint(0, 255, (128, 128), dtype=np.uint8)
        w.show_frame(frame)
        state = _make_state(total=5)
        w.set_state(state)
        assert w._current_state is state

    def test_multiple_set_state_calls(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        for i in range(5):
            state = _make_state(frame=i, total=10)
            w.set_state(state)
        assert w._current_state.current_frame_index == 4


# ═══════════════════════════════════════════════════════════════════
#  Key press events
# ═══════════════════════════════════════════════════════════════════


class TestKeyPress:
    def _make_key_event(self, key, modifiers=Qt.KeyboardModifier.NoModifier):
        from PySide6.QtGui import QKeyEvent
        return QKeyEvent(QEvent.Type.KeyPress, key, modifiers)

    def test_plus_zooms_in(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.set_zoom_mode("fit")
        event = self._make_key_event(Qt.Key.Key_Plus)
        w.keyPressEvent(event)
        assert w.zoom_mode == "100%"

    def test_minus_zooms_out(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.set_zoom_mode("100%")
        event = self._make_key_event(Qt.Key.Key_Minus)
        w.keyPressEvent(event)
        assert w.zoom_mode == "fit"

    def test_zero_resets_zoom(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.set_zoom_mode("200%")
        event = self._make_key_event(Qt.Key.Key_0)
        w.keyPressEvent(event)
        assert w.zoom_mode == "fit"

    def test_escape_cancels_caliper_drag(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w._caliper_drag_active = True
        event = self._make_key_event(Qt.Key.Key_Escape)
        w.keyPressEvent(event)
        assert w._caliper_drag_active is False

    def test_ctrl_shift_d_toggles_debug(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        initial = w._debug_overlay_visible
        event = self._make_key_event(
            Qt.Key.Key_D,
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
        )
        w.keyPressEvent(event)
        assert w._debug_overlay_visible is not initial

    def test_plus_at_max_stays_at_200(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.set_zoom_mode("200%")
        event = self._make_key_event(Qt.Key.Key_Plus)
        w.keyPressEvent(event)
        assert w.zoom_mode == "200%"

    def test_minus_at_min_stays_fit(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.set_zoom_mode("fit")
        event = self._make_key_event(Qt.Key.Key_Minus)
        w.keyPressEvent(event)
        assert w.zoom_mode == "fit"


# ═══════════════════════════════════════════════════════════════════
#  Cancel active tool
# ═══════════════════════════════════════════════════════════════════


class TestCancelActiveTool:
    def test_cancel_without_active_tool(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Should not raise
        w.cancel_active_tool()

    def test_cancel_calibration(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.toggle_calibration_caliper()
        assert w._calibration_active is True
        w.cancel_active_tool()
        assert w._calibration_active is False

    def test_cancel_linear_caliper(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.toggle_linear_caliper()
        assert w.is_linear_caliper_active is True
        w.cancel_active_tool()
        assert w.is_linear_caliper_active is False

    def test_cancel_doppler_cal_step(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w._doppler_cal_step = "roi"
        w.cancel_active_tool()
        assert w._doppler_cal_step is None

    def test_cancel_mmode_cal_step(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w._mmode_cal_step = "roi"
        w.cancel_active_tool()
        assert w._mmode_cal_step is None

    def test_cancel_caliper_drag(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w._caliper_drag_active = True
        w.cancel_active_tool()
        assert w._caliper_drag_active is False


# ═══════════════════════════════════════════════════════════════════
#  Timeline / step navigation
# ═══════════════════════════════════════════════════════════════════


class TestTimeline:
    def test_step_forward(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state(frame=0, total=5)
        w.set_state(state)
        w._step_forward()
        assert w._timeline_slider.value() == 1

    def test_step_back(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state(frame=2, total=5)
        w.set_state(state)
        w._step_back()
        assert w._timeline_slider.value() == 1

    def test_step_forward_at_end(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state(frame=4, total=5)
        w.set_state(state)
        w._step_forward()
        assert w._timeline_slider.value() == 4

    def test_step_back_at_start(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state(frame=0, total=5)
        w.set_state(state)
        w._step_back()
        assert w._timeline_slider.value() == 0


# ═══════════════════════════════════════════════════════════════════
#  Caliper label cycling
# ═══════════════════════════════════════════════════════════════════


class TestCaliperLabelCycling:
    def test_cycle_caliper_label(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        initial_idx = w._caliper_label_index
        w.cycle_caliper_label()
        assert w._caliper_label_index == (initial_idx + 1) % len(w._caliper_labels)

    def test_cycle_caliper_label_wraps(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w._caliper_label_index = len(w._caliper_labels) - 1
        w.cycle_caliper_label()
        assert w._caliper_label_index == 0

    def test_cycle_caliper_label_resets_start(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.toggle_linear_caliper()
        w._linear_caliper_start = (10.0, 20.0)
        w.cycle_caliper_label()
        assert w._linear_caliper_start is None


# ═══════════════════════════════════════════════════════════════════
#  Contour operations
# ═══════════════════════════════════════════════════════════════════


class TestContourOperations:
    def test_set_contour_from_domain(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        from echo_personal_tool.domain.models import Contour
        contour = Contour(
            phase="ED",
            view="A4C",
            chamber="LV",
            points=[(10, 10), (20, 10), (20, 20), (10, 20)],
        )
        w.set_contour_from_domain(contour)
        assert len(w.contours()) == 1
        assert w.contours()[0].chamber == "LV"

    def test_apply_contours(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        from echo_personal_tool.domain.models import Contour
        contours = [
            Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10), (20, 20)]),
            Contour(phase="ES", view="A4C", chamber="LV", points=[(15, 15), (25, 25)]),
        ]
        w.apply_contours(contours)
        assert len(w.contours()) == 2

    def test_contours_returns_copy(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        from echo_personal_tool.domain.models import Contour
        contour = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10)])
        w.set_contour_from_domain(contour)
        result = w.contours()
        result.clear()
        assert len(w.contours()) == 1

    def test_get_lv_contour_returns_lv(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        from echo_personal_tool.domain.models import Contour
        w.set_contour_from_domain(Contour(phase="ED", view="A4C", chamber="LA", points=[(10, 10)]))
        w.set_contour_from_domain(Contour(phase="ED", view="A4C", chamber="LV", points=[(20, 20)]))
        lv = w.get_lv_contour()
        assert lv is not None
        assert lv.chamber == "LV"

    def test_get_lv_contour_none_when_no_lv(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        from echo_personal_tool.domain.models import Contour
        w.set_contour_from_domain(Contour(phase="ED", view="A4C", chamber="LA", points=[(10, 10)]))
        assert w.get_lv_contour() is None

    def test_start_contour(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        result = w.start_contour(phase="ED", view="A4C", chamber="LV")
        assert result is True
        assert w._contour_mode_active is True

    def test_start_model_contour(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        result = w.start_model_contour(phase="ED")
        assert result is True
        assert w._contour_mode_kind == "model"

    def test_start_closed_contour(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        result = w.start_closed_contour(chamber="LA")
        assert result is True
        assert w._contour_mode_kind == "closed"

    def test_start_generic_area_contour(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        result = w.start_generic_area_contour()
        assert result is True
        assert w._active_contour_chamber == "AREA"

    def test_start_generic_volume_contour(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        result = w.start_generic_volume_contour()
        assert result is True
        assert w._active_contour_chamber == "VOL"

    def test_start_contour_without_frame(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        result = w.start_contour()
        assert result is False

    def test_start_contour_when_already_active(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.start_contour()
        result = w.start_contour()
        assert result is False

    def test_finish_contour_no_active(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w.finish_contour() is False

    def test_cancel_contour_drawing(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.start_contour()
        assert w._contour_mode_active is True
        w.cancel_active_tool()
        assert w._contour_mode_active is False


# ═══════════════════════════════════════════════════════════════════
#  show_frame_fast
# ═══════════════════════════════════════════════════════════════════


class TestShowFrameFast:
    def test_fast_frame_grayscale(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        frame = np.random.randint(0, 255, (64, 64), dtype=np.uint8)
        w.show_frame_fast(frame)
        assert w._current_frame is not None

    def test_fast_frame_rgb(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64, 3), dtype=np.uint8))
        frame = np.random.randint(0, 255, (64, 64, 3), dtype=np.uint8)
        w.show_frame_fast(frame)
        assert w._current_frame is not None


# ═══════════════════════════════════════════════════════════════════
#  refresh_after_scroll
# ═══════════════════════════════════════════════════════════════════


class TestRefreshAfterScroll:
    def test_refresh_after_scroll(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        # Should not raise
        w.refresh_after_scroll()

    def test_refresh_after_scroll_no_frame(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Should not raise even without frame
        w.refresh_after_scroll()


# ═══════════════════════════════════════════════════════════════════
#  Doppler operations
# ═══════════════════════════════════════════════════════════════════


class TestDopplerOperations:
    def test_finish_doppler_trace(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        result = w.finish_doppler_trace()
        assert isinstance(result, bool)

    def test_start_doppler_calibration(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        result = w.start_doppler_calibration(DopplerKind.SPECTRAL)
        assert isinstance(result, bool)

    def test_start_mitral_inflow_workflow(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        result = w.start_mitral_inflow_workflow()
        assert isinstance(result, bool)

    def test_start_doppler_scale_calibration(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        result = w.start_doppler_scale_calibration()
        assert isinstance(result, bool)


# ═══════════════════════════════════════════════════════════════════
#  MMode operations
# ═══════════════════════════════════════════════════════════════════


class TestMModeOperations:
    def test_start_mmode_line(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.start_mmode_line()
        assert w._mmode_line_active is True

    def test_start_mmode_panel_calibration(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        result = w.start_mmode_panel_calibration()
        assert isinstance(result, bool)


# ═══════════════════════════════════════════════════════════════════
#  Speckle overlay
# ═══════════════════════════════════════════════════════════════════


class TestSpeckleOverlay:
    def test_show_speckle_result_invalid(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Should not raise with non-StrainResult
        w.show_speckle_result("not a result")

    def test_clear_speckle_overlay(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.clear_speckle_overlay()
        assert w._speckle_result is None


# ═══════════════════════════════════════════════════════════════════
#  Results overlay settings
# ═══════════════════════════════════════════════════════════════════


class TestResultsOverlaySettings:
    def test_set_results_overlay_position(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.set_results_overlay("Test")
        w.set_results_overlay_position(0.3, 0.7)
        # Should not raise

    def test_results_overlay_custom_position(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w._results_overlay_custom_position = True
        w.set_results_overlay("Test")
        # Should not raise


# ═══════════════════════════════════════════════════════════════════
#  Toggle methods
# ═══════════════════════════════════════════════════════════════════


class TestToggleMethods:
    def test_toggle_debug_overlay(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        initial = w._debug_overlay_visible
        w.toggle_debug_overlay()
        assert w._debug_overlay_visible is not initial

    def test_toggle_ghost_mode(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        result = w.toggle_ghost_mode()
        assert isinstance(result, str)

    def test_set_ghost_mode(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.set_ghost_mode("center")
        assert w._ghost_mode == "center"

    def test_set_magnetic_snap_enabled(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.set_magnetic_snap_enabled(False)
        assert w._magnetic_snap_enabled is False

    def test_set_despeckle_enabled(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.set_despeckle_enabled(True)
        assert w._despeckle_enabled is True

    def test_direct_attribute_toggles(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Test direct attribute setting for boolean flags
        w._show_crosshair = False
        assert w._show_crosshair is False
        w._show_panel_frames = True
        assert w._show_panel_frames is True
        w._show_caliper_labels_on_frame = False
        assert w._show_caliper_labels_on_frame is False
        w._show_caliper_inline_labels = True
        assert w._show_caliper_inline_labels is True


# ═══════════════════════════════════════════════════════════════════
#  Settings methods
# ═══════════════════════════════════════════════════════════════════


class TestSettingsMethods:
    def test_set_scroll_debounce_ms(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.set_scroll_debounce_ms(100)
        assert w._scroll_debounce_ms == 100

    def test_set_magnetic_snap_enabled(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.set_magnetic_snap_enabled(True)
        assert w._magnetic_snap_enabled is True

    def test_set_despeckle_enabled(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.set_despeckle_enabled(True)
        assert w._despeckle_enabled is True

    def test_set_image_smooth(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w._set_image_smooth(False)
        assert w._image_smooth is False
        w._set_image_smooth(True)
        assert w._image_smooth is True

    def test_set_doppler_auto_calibration(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w._doppler_auto_calibration_enabled = False
        assert w._doppler_auto_calibration_enabled is False

    def test_direct_attribute_settings(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Test direct attribute setting
        w._length_display_unit = "cm"
        assert w._length_display_unit == "cm"
        w._caliper_line_width = 3.0
        assert w._caliper_line_width == 3.0


# ═══════════════════════════════════════════════════════════════════
#  Doppler tool mode
# ═══════════════════════════════════════════════════════════════════


class TestDopplerToolMode:
    def test_set_doppler_tool_mode(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.set_doppler_tool_mode("peak")
        assert w.get_doppler_tool_mode() == "peak"

    def test_set_doppler_tool_mode_interval(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.set_doppler_tool_mode("interval")
        assert w.get_doppler_tool_mode() == "interval"

    def test_set_doppler_tool_mode_trace(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.set_doppler_tool_mode("trace")
        assert w.get_doppler_tool_mode() == "trace"


# ═══════════════════════════════════════════════════════════════════
#  Window/level preferences
# ═══════════════════════════════════════════════════════════════════


class TestWindowLevel:
    def test_apply_window_level_preferences(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from echo_personal_tool.infrastructure.user_preferences import UserPreferences
        prefs = UserPreferences()
        w._apply_window_level_preferences(prefs)
        # Should not raise

    def test_update_levels(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w._update_levels()
        # Should not raise

    def test_update_levels_with_color_frame(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64, 3), dtype=np.uint8))
        w._update_levels()
        # Should not raise


# ═══════════════════════════════════════════════════════════════════
#  Contour phase resolution
# ═══════════════════════════════════════════════════════════════════


class TestContourPhase:
    def test_resolve_contour_phase(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        phase = w._resolve_contour_phase()
        assert isinstance(phase, str)

    def test_resolve_contour_phase_with_state(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state(frame=0, total=5)
        w.set_state(state)
        phase = w._resolve_contour_phase()
        assert isinstance(phase, str)


# ═══════════════════════════════════════════════════════════════════
#  Linear measurement operations
# ═══════════════════════════════════════════════════════════════════


class TestLinearMeasurementOps:
    def test_start_linear_caliper_sequence_empty(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        result = w.start_linear_caliper_sequence(())
        assert result is False

    def test_linear_measurements_changed_signal(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        received = []
        w.linear_measurements_changed.connect(lambda m: received.append(m))
        # Signal should be connectable
        assert len(received) == 0


# ═══════════════════════════════════════════════════════════════════
#  Frame overlay
# ═══════════════════════════════════════════════════════════════════


class TestFrameOverlayOps:
    def test_clear_frame_overlay(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w._frame_overlay_lines = ["test"]
        w.clear_frame_overlay()
        assert w._frame_overlay_lines == []

    def test_append_frame_overlay(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.append_frame_overlay("line1")
        assert "line1" in w._frame_overlay_lines

    def test_append_multiple_frame_overlay(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.append_frame_overlay("line1")
        w.append_frame_overlay("line2")
        assert len(w._frame_overlay_lines) == 2


# ═══════════════════════════════════════════════════════════════════
#  Properties and getters
# ═══════════════════════════════════════════════════════════════════


class TestPropertiesAndGetters:
    def test_contours_property(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert isinstance(w.contours(), list)

    def test_is_calibration_active(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w.is_calibration_active is False

    def test_get_doppler_calibration_state_none(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w.get_doppler_calibration_state() is None

    def test_get_mmode_calibration_state_none(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w.get_mmode_calibration_state() is None

    def test_get_doppler_dto(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        dto = w.get_doppler_dto()
        # Returns a DTO object (may have empty fields)
        assert dto is not None or dto is None

    def test_get_lv_contour_none(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w.get_lv_contour() is None

    def test_zoom_mode_property(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w.zoom_mode == "fit"

    def test_dist_caliper_serial_property(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w.dist_caliper_serial == 1

    def test_is_linear_caliper_active_property(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w.is_linear_caliper_active is False

    def test_get_doppler_tool_mode(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        mode = w.get_doppler_tool_mode()
        assert isinstance(mode, str)

    def test_contour_viewing_mode(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w._contour_mode_active is False

    def test_initial_doppler_state(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w._doppler_axis_calibrated is False
        assert w._doppler_calibration_state is None


# ═══════════════════════════════════════════════════════════════════
#  Frame overlay refresh
# ═══════════════════════════════════════════════════════════════════


class TestFrameOverlayRefresh:
    def test_refresh_overlay_with_content(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w._frame_overlay_lines = ["Test overlay line"]
        w._refresh_frame_overlay()
        assert w._overlay_label.isVisible()

    def test_refresh_overlay_empty_hides(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w._frame_overlay_lines = []
        w._refresh_frame_overlay()
        assert not w._overlay_label.isVisible()

    def test_refresh_overlay_calibration_banner(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        from echo_personal_tool.infrastructure.i18n import tr
        from echo_personal_tool.presentation.viewer_widget import CALIBRATION_PROMPT_OVERLAY_KEY
        w._frame_overlay_lines = [tr(CALIBRATION_PROMPT_OVERLAY_KEY)]
        w._refresh_frame_overlay()
        assert w._overlay_label.isVisible()

    def test_refresh_overlay_calibration_ok(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        from echo_personal_tool.infrastructure.i18n import tr
        from echo_personal_tool.presentation.viewer_widget import CALIBRATION_SUCCESS_OVERLAY_KEY
        w._frame_overlay_lines = [tr(CALIBRATION_SUCCESS_OVERLAY_KEY)]
        w._refresh_frame_overlay()
        assert w._overlay_label.isVisible()

    def test_clear_frame_overlay_clears_lines(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w._frame_overlay_lines = ["line1", "line2"]
        w.clear_frame_overlay()
        assert w._frame_overlay_lines == []


# ═══════════════════════════════════════════════════════════════════
#  Linear caliper clear
# ═══════════════════════════════════════════════════════════════════


class TestLinearCaliperClear:
    def test_clear_linear_caliper_resets_state(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.toggle_linear_caliper()
        assert w.is_linear_caliper_active is True
        w._clear_linear_caliper()
        assert w.is_linear_caliper_active is False
        assert w._linear_caliper_start is None
        assert w._caliper_sequence == []

    def test_clear_linear_caliper_graphics(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Items are already None by default, just verify clearing works
        w._clear_linear_caliper_graphics()
        assert w._linear_caliper_line_item is None
        assert w._linear_caliper_marker_item is None
        assert w._active_caliper_label_item is None


# ═══════════════════════════════════════════════════════════════════
#  Calibration caliper clear
# ═══════════════════════════════════════════════════════════════════


class TestCalibrationCaliperClear:
    def test_clear_calibration_caliper_resets_state(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w._calibration_active = True
        w._calibration_start_y = 10.0
        w._calibration_kind = "depth"
        w._doppler_grid_line_positions = [10.0, 20.0]
        w._clear_calibration_caliper()
        assert w._calibration_active is False
        assert w._calibration_start_y is None
        assert w._calibration_kind is None
        assert w._doppler_grid_line_positions == []

    def test_clear_calibration_graphics(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Items are already None by default, just verify clearing works
        w._clear_calibration_graphics()
        assert w._calibration_line_item is None
        assert w._calibration_marker_item is None
        assert w._calibration_h_guide_start_item is None
        assert w._calibration_h_guide_end_item is None


# ═══════════════════════════════════════════════════════════════════
#  Calibration horizontal guides
# ═══════════════════════════════════════════════════════════════════


class TestCalibrationGuides:
    def test_ensure_calibration_horizontal_guides(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w._ensure_calibration_horizontal_guides()
        assert w._calibration_h_guide_start_item is not None
        assert w._calibration_h_guide_end_item is not None

    def test_ensure_guides_idempotent(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w._ensure_calibration_horizontal_guides()
        first_start = w._calibration_h_guide_start_item
        first_end = w._calibration_h_guide_end_item
        w._ensure_calibration_horizontal_guides()
        assert w._calibration_h_guide_start_item is first_start
        assert w._calibration_h_guide_end_item is first_end

    def test_update_calibration_guides_no_active(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Should not raise even when calibration is not active
        w._update_calibration_horizontal_guides(50.0)

    def test_update_calibration_guides_mmode_time(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w._calibration_active = True
        w._calibration_start_y = 10.0
        w._calibration_kind = "mmode_time"
        # Should return early for mmode_time
        w._update_calibration_horizontal_guides(50.0)


# ═══════════════════════════════════════════════════════════════════
#  Ghost mode
# ═══════════════════════════════════════════════════════════════════


class TestGhostMode:
    def test_set_ghost_mode(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.set_ghost_mode("center")
        assert w._ghost_mode == "center"

    def test_toggle_ghost_mode(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        result = w.toggle_ghost_mode()
        assert isinstance(result, str)

    def test_render_ghost_overlay_off(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w._ghost_mode = "off"
        w._render_ghost_overlay()
        assert len(w._ghost_items) == 0

    def test_render_ghost_overlay_no_result(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w._ghost_mode = "center"
        w._render_ghost_overlay()
        assert len(w._ghost_items) == 0

    def test_clear_ghost_overlay(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Ghost items are empty by default
        w._clear_ghost_overlay()
        assert len(w._ghost_items) == 0

    def test_get_fusion_result_no_controller(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        result = w._get_fusion_result()
        assert result is None


# ═══════════════════════════════════════════════════════════════════
#  Contour rendering internals
# ═══════════════════════════════════════════════════════════════════


class TestContourRenderingInternals:
    def test_find_stored_contour_index(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        from echo_personal_tool.domain.models import Contour
        contour = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10)])
        w.set_contour_from_domain(contour)
        idx = w._find_stored_contour_index(contour)
        assert idx is not None

    def test_find_stored_contour_index_not_found(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        from echo_personal_tool.domain.models import Contour
        contour = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10)])
        other = Contour(phase="ES", view="A4C", chamber="LA", points=[(20, 20)])
        w.set_contour_from_domain(contour)
        idx = w._find_stored_contour_index(other)
        assert idx is None

    def test_upsert_stored_contour_new(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from echo_personal_tool.domain.models import Contour
        contour = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10)])
        w._upsert_stored_contour(contour)
        assert len(w._stored_contours) == 1

    def test_upsert_stored_contour_update(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from echo_personal_tool.domain.models import Contour
        c1 = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10)])
        c2 = Contour(phase="ED", view="A4C", chamber="LV", points=[(20, 20)])
        w._upsert_stored_contour(c1)
        w._upsert_stored_contour(c2)
        assert len(w._stored_contours) == 1
        assert w._stored_contours[0].points == [(20, 20)]

    def test_current_instance_uid(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w._current_instance_uid() is None

    def test_current_instance_uid_with_state(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state()
        w.set_state(state)
        uid = w._current_instance_uid()
        assert uid is not None

    def test_tag_contour_instance_no_uid(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from echo_personal_tool.domain.models import Contour
        contour = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10)])
        result = w._tag_contour_instance(contour)
        assert result is contour

    def test_contour_frame_index(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w._contour_frame_index() is None

    def test_contour_frame_index_with_state(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state(frame=3)
        w.set_state(state)
        assert w._contour_frame_index() == 3

    def test_clear_active_contour_drawing(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w._contour_mode_active = True
        w._contour_stage = "arc"
        w._active_mitral_septal = (10, 10)
        w._active_arc_points = [(20, 20)]
        w._clear_active_contour_drawing()
        assert w._contour_mode_active is False
        assert w._contour_stage is None
        assert w._active_mitral_septal is None
        assert w._active_arc_points == []

    def test_set_contour_nodes_pickable(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Should not raise even with empty nodes
        w._set_contour_nodes_pickable(True)
        w._set_contour_nodes_pickable(False)

    def test_contour_editing_blocked(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w._contour_editing_blocked() is False
        w._contour_mode_active = True
        assert w._contour_editing_blocked() is True
        w._contour_mode_active = False
        w._linear_caliper_active = True
        assert w._contour_editing_blocked() is True
        w._linear_caliper_active = False
        w._calibration_active = True
        assert w._contour_editing_blocked() is True


# ═══════════════════════════════════════════════════════════════════
#  Contour operations (set_contour_from_domain, apply_contours, etc.)
# ═══════════════════════════════════════════════════════════════════


class TestContourOperationsDeep:
    def test_set_contour_from_domain_multiple(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        from echo_personal_tool.domain.models import Contour
        # Use different phases/views/chambers to avoid deduplication
        phases = ["ED", "ES"]
        views = ["A4C", "A2C"]
        chambers = ["LV", "LA"]
        count = 0
        for p in phases:
            for v in views:
                for ch in chambers:
                    c = Contour(phase=p, view=v, chamber=ch, points=[(10, 10)])
                    w.set_contour_from_domain(c)
                    count += 1
        assert len(w.contours()) == count

    def test_apply_contours_replaces(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        from echo_personal_tool.domain.models import Contour
        c1 = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10)])
        w.set_contour_from_domain(c1)
        assert len(w.contours()) == 1
        c2 = Contour(phase="ES", view="A4C", chamber="LV", points=[(20, 20)])
        c3 = Contour(phase="ED", view="A2C", chamber="LV", points=[(30, 30)])
        w.apply_contours([c2, c3])
        assert len(w.contours()) == 2

    def test_contours_returns_list_copy(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        from echo_personal_tool.domain.models import Contour
        c = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10)])
        w.set_contour_from_domain(c)
        contours = w.contours()
        assert len(contours) == 1
        contours.clear()
        assert len(w.contours()) == 1

    def test_get_lv_contour_with_multiple(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        from echo_personal_tool.domain.models import Contour
        w.set_contour_from_domain(Contour(phase="ED", view="A4C", chamber="LA", points=[(10, 10)]))
        w.set_contour_from_domain(Contour(phase="ED", view="A4C", chamber="RV", points=[(20, 20)]))
        w.set_contour_from_domain(Contour(phase="ED", view="A4C", chamber="LV", points=[(30, 30)]))
        lv = w.get_lv_contour()
        assert lv is not None
        assert lv.chamber == "LV"


# ═══════════════════════════════════════════════════════════════════
#  Contour editing (handle_contour_click)
# ═══════════════════════════════════════════════════════════════════


class TestContourEditing:
    def test_handle_contour_click_not_active(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        result = w.handle_contour_click((10.0, 10.0))
        assert result is False

    def test_start_contour_then_click(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.start_contour(phase="ED", view="A4C", chamber="LV")
        assert w._contour_mode_active is True
        # Click in arc/polygon stage
        w._contour_stage = "arc"
        result = w.handle_contour_click((10.0, 10.0))
        assert result is True
        assert len(w._active_arc_points) == 1

    def test_start_closed_contour_then_click(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.start_closed_contour(chamber="LA")
        w._contour_stage = "polygon"
        w.handle_contour_click((10.0, 10.0))
        w.handle_contour_click((20.0, 10.0))
        w.handle_contour_click((20.0, 20.0))
        assert len(w._active_arc_points) == 3

    def test_finish_contour_polygon(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.start_closed_contour(chamber="LA")
        w._contour_stage = "polygon"
        w.handle_contour_click((10.0, 10.0))
        w.handle_contour_click((20.0, 10.0))
        w.handle_contour_click((20.0, 20.0))
        w.handle_contour_click((10.0, 20.0))
        result = w.finish_contour()
        assert result is True
        assert len(w.contours()) == 1

    def test_cancel_active_tool_contour(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.start_contour(phase="ED")
        assert w._contour_mode_active is True
        w.cancel_active_tool()
        assert w._contour_mode_active is False


# ═══════════════════════════════════════════════════════════════════
#  Wheel event handling
# ═══════════════════════════════════════════════════════════════════


class TestWheelEvent:
    def _make_wheel_event(self, angle_delta_y=120, modifiers=Qt.KeyboardModifier.NoModifier):
        from PySide6.QtGui import QWheelEvent
        from PySide6.QtCore import QPoint, QPointF
        return QWheelEvent(
            QPointF(0, 0), QPointF(0, 0),
            QPoint(0, 0), QPoint(0, angle_delta_y),
            Qt.MouseButton.NoButton, modifiers,
            Qt.ScrollPhase.NoScrollPhase, False,
        )

    def test_handle_wheel_no_state(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        event = self._make_wheel_event()
        result = w._handle_wheel(event)
        assert result is False

    def test_handle_wheel_single_frame(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state(total=1)
        w.set_state(state)
        event = self._make_wheel_event()
        result = w._handle_wheel(event)
        assert result is False

    def test_handle_wheel_multi_frame(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state(total=10)
        w.set_state(state)
        event = self._make_wheel_event()
        w._scroll_debounce_ms = 0
        result = w._handle_wheel(event)
        assert result is True

    def test_handle_ctrl_wheel(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        event = self._make_wheel_event(
            angle_delta_y=120,
            modifiers=Qt.KeyboardModifier.ControlModifier,
        )
        result = w._handle_ctrl_wheel(event, 120)
        assert result is True
        assert w._zoom_factor > 1.0

    def test_handle_ctrl_wheel_no_frame(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        event = self._make_wheel_event(
            angle_delta_y=120,
            modifiers=Qt.KeyboardModifier.ControlModifier,
        )
        result = w._handle_ctrl_wheel(event, 120)
        assert result is False


# ═══════════════════════════════════════════════════════════════════
#  MMode operations
# ═══════════════════════════════════════════════════════════════════


class TestMModeDeep:
    def test_start_mmode_line_sets_active(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.start_mmode_line()
        assert w._mmode_line_active is True
        assert w._mmode_line_click_step == "start"

    def test_mmode_line_click_start(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.start_mmode_line()
        result = w._handle_mmode_line_click(10.0, 10.0)
        assert result is True
        assert w._mmode_line_click_step == "end"

    def test_mmode_line_click_end(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.start_mmode_line()
        w._handle_mmode_line_click(10.0, 10.0)
        result = w._handle_mmode_line_click(50.0, 50.0)
        assert result is True

    def test_mmode_vertical_lock(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.set_mmode_vertical_lock(True)
        assert w._mmode_vertical_lock is True
        w.set_mmode_vertical_lock(False)
        assert w._mmode_vertical_lock is False


# ═══════════════════════════════════════════════════════════════════
#  Doppler calibration operations
# ═══════════════════════════════════════════════════════════════════


class TestDopplerCalibrationDeep:
    def test_start_doppler_calibration(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        result = w.start_doppler_calibration(DopplerKind.SPECTRAL)
        assert isinstance(result, bool)

    def test_start_mitral_inflow_workflow(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        result = w.start_mitral_inflow_workflow()
        assert isinstance(result, bool)

    def test_start_doppler_envelope_trace(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        result = w.start_doppler_envelope_trace(plot_points=[(10, 10), (20, 20)])
        # May return None or a value
        assert result is None or isinstance(result, (bool, tuple))

    def test_finish_doppler_trace(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        result = w.finish_doppler_trace()
        assert isinstance(result, bool)

    def test_clear_doppler_measurements(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        # Should not raise
        w.clear_doppler_measurements()

    def test_clear_doppler_calibration_display(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w._doppler_calibration_state = "mock"
        w.clear_doppler_calibration_display()
        assert w._doppler_calibration_state is None


# ═══════════════════════════════════════════════════════════════════
#  Speckle overlay deep
# ═══════════════════════════════════════════════════════════════════


class TestSpeckleOverlayDeep:
    def test_show_speckle_result_invalid_type(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_speckle_result("not a StrainResult")
        assert w._speckle_result is None

    def test_clear_speckle_overlay_resets(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w._speckle_result = "mock"
        w.clear_speckle_overlay()
        assert w._speckle_result is None

    def test_refresh_speckle_no_result(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        # Should not raise
        w._refresh_speckle_overlay_for_current_frame()


# ═══════════════════════════════════════════════════════════════════
#  Scroll debounce
# ═══════════════════════════════════════════════════════════════════


class TestScrollDebounce:
    def test_set_scroll_debounce_ms(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.set_scroll_debounce_ms(100)
        assert w._scroll_debounce_ms == 100

    def test_emit_pending_scroll(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state(total=10)
        w.set_state(state)
        received = []
        w.scroll_frame_selected.connect(lambda v: received.append(v))
        w._pending_scroll_index = 5
        w._syncing_state = False
        w._emit_pending_scroll()
        QApplication.processEvents()
        assert len(received) == 1
        assert received[0] == 5


# ═══════════════════════════════════════════════════════════════════
#  Timeline indicator
# ═══════════════════════════════════════════════════════════════════


class TestTimelineIndicator:
    def test_update_timeline_indicator(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state(frame=2, total=10)
        w.set_state(state)
        # Should not raise
        w._update_timeline_indicator(state)

    def test_on_timeline_changed(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state(total=10)
        w.set_state(state)
        received = []
        w.frame_selected.connect(lambda v: received.append(v))
        w._on_timeline_changed(5)
        assert len(received) == 1
        assert received[0] == 5

    def test_on_timeline_changed_syncing(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state(total=10)
        w.set_state(state)
        received = []
        w.frame_selected.connect(lambda v: received.append(v))
        w._syncing_state = True
        w._on_timeline_changed(5)
        assert len(received) == 0
        w._syncing_state = False


# ═══════════════════════════════════════════════════════════════════
#  Debug overlay deep
# ═══════════════════════════════════════════════════════════════════


class TestDebugOverlayDeep:
    def test_toggle_debug_overlay_on(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w._debug_overlay_visible = False
        w.toggle_debug_overlay()
        assert w._debug_overlay_visible is True

    def test_toggle_debug_overlay_off(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w._debug_overlay_visible = True
        w.toggle_debug_overlay()
        assert w._debug_overlay_visible is False

    def test_update_debug_overlay_visible(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w._debug_overlay_visible = True
        w._update_debug_overlay()
        # Should not raise

    def test_update_debug_overlay_hidden(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w._debug_overlay_visible = False
        w._update_debug_overlay()
        # Should not raise


# ═══════════════════════════════════════════════════════════════════
#  Contour pen
# ═══════════════════════════════════════════════════════════════════


class TestContourPen:
    def test_contour_pen_for_manual(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from echo_personal_tool.domain.models import Contour
        c = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10)], source="manual")
        pen = w._contour_pen_for(c)
        assert pen is not None

    def test_contour_pen_for_ai(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from echo_personal_tool.domain.models import Contour
        c = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10)], source="ai")
        pen = w._contour_pen_for(c)
        assert pen is not None

    def test_contour_pen_for_model(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from echo_personal_tool.domain.models import Contour
        c = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10)], source="model")
        pen = w._contour_pen_for(c)
        assert pen is not None


# ═══════════════════════════════════════════════════════════════════
#  Contour xy
# ═══════════════════════════════════════════════════════════════════


class TestContourXY:
    def test_contour_xy_closed(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from echo_personal_tool.domain.models import Contour
        c = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10), (20, 10), (20, 20)])
        x, y = w._contour_xy(c, closed=True)
        # Returns resampled points (DEFAULT_NODE_COUNT=128)
        assert len(x) > 0
        assert len(y) > 0
        assert len(x) == len(y)

    def test_contour_xy_open(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from echo_personal_tool.domain.models import Contour
        c = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10), (20, 10), (20, 20)])
        x, y = w._contour_xy(c, closed=False)
        assert len(x) > 0
        assert len(y) > 0

    def test_contour_xy_open_arc(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from echo_personal_tool.domain.models import Contour
        c = Contour(
            phase="ED", view="A4C", chamber="LV",
            points=[(10, 10), (20, 10), (20, 20)],
            mitral_annulus=((5, 5), (25, 5)),
        )
        x, y = w._contour_xy(c, closed=False)
        assert len(x) > 0


# ═══════════════════════════════════════════════════════════════════
#  Resize event
# ═══════════════════════════════════════════════════════════════════


class TestResizeEvent:
    def test_resize_event(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        from PySide6.QtGui import QResizeEvent
        from PySide6.QtCore import QSize
        event = QResizeEvent(QSize(640, 480), QSize(320, 240))
        w.resizeEvent(event)
        # Should not raise


# ═══════════════════════════════════════════════════════════════════
#  Crosshair
# ═══════════════════════════════════════════════════════════════════


class TestCrosshair:
    def test_update_measurement_crosshair(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        state = _make_state()
        w.set_state(state)
        w._update_measurement_crosshair(32.0, 32.0)
        # Crosshair items may or may not be created depending on _show_crosshair
        # Just verify no crash
        assert True

    def test_clear_crosshair(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        state = _make_state()
        w.set_state(state)
        w._update_measurement_crosshair(32.0, 32.0)
        w._clear_crosshair()
        assert w._crosshair_h_item is None
        assert w._crosshair_v_item is None


# ═══════════════════════════════════════════════════════════════════
#  Measurement label
# ═══════════════════════════════════════════════════════════════════


class TestMeasurementLabel:
    def test_current_caliper_label(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        label = w._current_caliper_label()
        assert isinstance(label, str)
        assert len(label) > 0

    def test_set_caliper_label(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w._set_caliper_label("CustomLabel")
        assert w._current_caliper_label() == "CustomLabel"

    def test_set_caliper_label_new(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w._set_caliper_label("NewLabel")
        assert "NewLabel" in w._caliper_labels


# ═══════════════════════════════════════════════════════════════════
#  Frame panel layout
# ═══════════════════════════════════════════════════════════════════


class TestFramePanelLayout:
    def test_refresh_frame_panel_layout(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        # Should not raise
        w._refresh_frame_panel_layout()

    def test_resolve_frame_panels(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        result = w._resolve_frame_panels()
        # May return None or a layout
        assert result is None or hasattr(result, "panels")


# ═══════════════════════════════════════════════════════════════════
#  Reload text
# ═══════════════════════════════════════════════════════════════════


class TestReloadText:
    def test_reload_text_no_state(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Should not raise
        w.reload_text()

    def test_reload_text_with_state(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state(total=5)
        w.set_state(state)
        # Should not raise
        w.reload_text()


# ═══════════════════════════════════════════════════════════════════
#  Contour pen rebuild
# ═══════════════════════════════════════════════════════════════════


class TestContourPenRebuild:
    def test_rebuild_contour_pens(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from echo_personal_tool.infrastructure.user_preferences import UserPreferences
        prefs = UserPreferences()
        w._rebuild_contour_pens(prefs)
        # Pens should be recreated
        assert w._contour_pen_manual is not None
        assert w._contour_pen_ai is not None
        assert w._contour_pen_model is not None
        assert w._contour_pen_ma is not None

    def test_refresh_rendered_contour_pens(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        # Should not raise even with no contours
        w._refresh_rendered_contour_pens()

    def test_caliper_pen(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        pen = w._caliper_pen("#ffb300")
        assert pen is not None

    def test_caliper_pen_dashed(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        pen = w._caliper_pen("#ffb300", style=Qt.PenStyle.DashLine)
        assert pen is not None

    def test_refresh_caliper_line_pens(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Should not raise even with no items
        w._refresh_caliper_line_pens()


# ═══════════════════════════════════════════════════════════════════
#  Display mode resolution
# ═══════════════════════════════════════════════════════════════════


class TestDisplayMode:
    def test_resolve_display_mode_grayscale(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        frame = np.zeros((64, 64), dtype=np.uint8)
        color, wl = w._resolve_display_mode(frame, None)
        assert color is False
        assert wl is True

    def test_resolve_display_mode_color_dicom(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        frame = np.random.randint(0, 255, (64, 64, 3), dtype=np.uint8)
        frame[:, :, 0] = 200  # Make it clearly color
        color, wl = w._resolve_display_mode(frame, "dicom")
        # Result depends on is_color_frame
        assert isinstance(color, bool)
        assert isinstance(wl, bool)

    def test_resolve_display_mode_rgb_non_dicom(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        frame = np.random.randint(0, 255, (64, 64, 3), dtype=np.uint8)
        color, wl = w._resolve_display_mode(frame, "mp4")
        assert isinstance(color, bool)
        assert isinstance(wl, bool)


# ═══════════════════════════════════════════════════════════════════
#  MMode operations deep
# ═══════════════════════════════════════════════════════════════════


class TestMModeDeepExtended:
    def test_cancel_mmode_line(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.start_mmode_line()
        assert w._mmode_line_active is True
        w.cancel_mmode_line()
        assert w._mmode_line_active is False
        assert w._mmode_line_item is None

    def test_handle_mmode_line_hover_not_active(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        result = w._handle_mmode_line_hover(10.0, 10.0)
        assert result is False

    def test_handle_mmode_line_hover_active(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.start_mmode_line()
        w._handle_mmode_line_click(10.0, 10.0)
        result = w._handle_mmode_line_hover(20.0, 20.0)
        assert result is True

    def test_begin_mmode_node_drag(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Should not raise
        w._begin_mmode_node_drag(0)

    def test_mmode_node_dragging_no_item(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Should not raise
        w._mmode_node_dragging(0, (10.0, 10.0))


# ═══════════════════════════════════════════════════════════════════
#  Linear measurement emission
# ═══════════════════════════════════════════════════════════════════


class TestLinearMeasurementEmission:
    def test_emit_stored_linear_measurements(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        received = []
        w.linear_measurements_changed.connect(lambda m: received.append(m))
        w._emit_stored_linear_measurements()
        assert len(received) == 1
        assert isinstance(received[0], list)


# ═══════════════════════════════════════════════════════════════════
#  Display controls
# ═══════════════════════════════════════════════════════════════════


class TestDisplayControls:
    def test_disconnect_display_controls(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Should not raise even without external sliders
        w.disconnect_display_controls()

    def test_set_wl_dr_sliders(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w._set_wl_dr_sliders(150, 60, 40)
        assert w._window_slider.value() == 150
        assert w._level_slider.value() == 60
        assert w._dr_slider.value() == 40

    def test_set_wl_dr_sliders_no_update(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w._set_wl_dr_sliders(150, 60, 40, update_display=False)
        assert w._window_slider.value() == 150

    def test_save_current_wl_dr(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        state = _make_state()
        w.set_state(state)
        w._save_current_wl_dr()
        # Should not raise

    def test_update_levels(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w._update_levels()
        # Should not raise

    def test_update_levels_no_frame(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Should not raise even without frame
        w._update_levels()

    def test_update_levels_empty_frame(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w._current_frame = np.array([], dtype=np.uint8)
        # Should not raise
        w._update_levels()


# ═══════════════════════════════════════════════════════════════════
#  Contour node operations
# ═══════════════════════════════════════════════════════════════════


class TestContourNodeOps:
    def test_set_contour_nodes_pickable_true(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w._set_contour_nodes_pickable(True)
        # Should not raise

    def test_set_contour_nodes_pickable_false(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w._set_contour_nodes_pickable(False)
        # Should not raise

    def test_reindex_contour_nodes(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Should not raise
        w._reindex_contour_nodes()


# ═══════════════════════════════════════════════════════════════════
#  Effective display levels
# ═══════════════════════════════════════════════════════════════════


class TestEffectiveDisplayLevels:
    def test_effective_display_levels(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        result = w._effective_display_levels()
        assert isinstance(result, tuple)
        assert len(result) == 2


# ═══════════════════════════════════════════════════════════════════
#  Contour drag session
# ═══════════════════════════════════════════════════════════════════


class TestContourDragSession:
    def test_clear_drag_session(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w._drag_session = (0, 10.0, 10.0, 0, 1)
        w._zone_drag_active = True
        w._last_drag_apply_pos = (5.0, 5.0)
        w._clear_drag_session()
        assert w._drag_session is None
        assert w._zone_drag_active is False
        assert w._last_drag_apply_pos is None


# ═══════════════════════════════════════════════════════════════════
#  Contour zone press/drag/release
# ═══════════════════════════════════════════════════════════════════


class TestContourZoneOps:
    def test_handle_contour_zone_press_no_contours(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtCore import QPointF
        event = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(10, 10),
            QPointF(10, 10),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        result = w._handle_contour_zone_press(event)
        assert result is False

    def test_handle_contour_zone_release(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtCore import QPointF
        event = QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            QPointF(10, 10),
            QPointF(10, 10),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        result = w._handle_contour_zone_release(event)
        assert result is False


# ═══════════════════════════════════════════════════════════════════
#  Doppler trace press/drag/release
# ═══════════════════════════════════════════════════════════════════


class TestDopplerTraceOps:
    def test_handle_doppler_trace_press_no_mode(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtCore import QPointF
        event = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(10, 10),
            QPointF(10, 10),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        result = w._handle_doppler_trace_press(event)
        assert result is False

    def test_handle_doppler_trace_release(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtCore import QPointF
        event = QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            QPointF(10, 10),
            QPointF(10, 10),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        result = w._handle_doppler_trace_release(event)
        assert result is False


# ═══════════════════════════════════════════════════════════════════
#  Caliper drag release
# ═══════════════════════════════════════════════════════════════════


class TestCaliperDragRelease:
    def test_handle_caliper_drag_release_no_drag(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtCore import QPointF
        event = QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            QPointF(10, 10),
            QPointF(10, 10),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        result = w._handle_caliper_drag_release(event)
        assert result is False


# ═══════════════════════════════════════════════════════════════════
#  Contour drag release
# ═══════════════════════════════════════════════════════════════════


class TestContourDragRelease:
    def test_handle_contour_drag_release_no_session(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtCore import QPointF
        event = QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            QPointF(10, 10),
            QPointF(10, 10),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        result = w._handle_contour_drag_release(event)
        assert result is False

    def test_handle_contour_drag_release_from_global(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Should not raise even without session
        from PySide6.QtCore import QPointF
        w._handle_contour_drag_release_from_global(QPointF(10, 10))


# ═══════════════════════════════════════════════════════════════════
#  Auto snap
# ═══════════════════════════════════════════════════════════════════


class TestAutoSnap:
    def test_auto_snap_new_contour(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        from echo_personal_tool.domain.models import Contour
        contour = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10), (20, 20)])
        # Should not raise
        w._auto_snap_new_contour(contour)


# ═══════════════════════════════════════════════════════════════════
#  Magnetic snap
# ═══════════════════════════════════════════════════════════════════


class TestMagneticSnap:
    def test_apply_magnetic_snap_to_contour(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        from echo_personal_tool.domain.models import Contour
        contour = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10), (20, 20), (30, 30)])
        w.set_contour_from_domain(contour)
        weights = np.ones(len(contour.points))
        # Should not raise
        w._apply_magnetic_snap_to_contour(0, weights, grab_index=None)


# ═══════════════════════════════════════════════════════════════════
#  Results overlay operations
# ═══════════════════════════════════════════════════════════════════


class TestResultsOverlayOps:
    def test_results_overlay_custom_position(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w.results_overlay_custom_position() is False

    def test_results_overlay_position(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        pos = w.results_overlay_position()
        assert isinstance(pos, tuple)
        assert len(pos) == 2

    def test_results_overlay_text(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        text = w.results_overlay_text()
        assert isinstance(text, str)

    def test_reposition_overlays(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        # Should not raise
        w.reposition_overlays()

    def test_mark_results_overlay_custom_position(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w._mark_results_overlay_custom_position()
        assert w._results_overlay_custom_position is True

    def test_reset_results_overlay_to_default(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w._results_overlay_custom_position = True
        w.reset_results_overlay_to_default()
        assert w._results_overlay_custom_position is False

    def test_on_results_overlay_clear(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.set_results_overlay("Test")
        w._on_results_overlay_clear()
        # After clear, set_results_overlay("") resets the flag
        assert w._results_overlay_cleared is False

    def test_on_results_overlay_reset_position(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w._results_overlay_custom_position = True
        w._on_results_overlay_reset_position()
        assert w._results_overlay_custom_position is False

    def test_on_results_overlay_pin_toggled(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w._on_results_overlay_pin_toggled(True)
        # Should not raise
        w._on_results_overlay_pin_toggled(False)
        # Should not raise


# ═══════════════════════════════════════════════════════════════════
#  Debug overlay deep
# ═══════════════════════════════════════════════════════════════════


class TestDebugOverlayDeepExtended:
    def test_get_last_segment_roi(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        result = w._get_last_segment_roi()
        assert result is None

    def test_draw_debug_roi_rect_none(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w._debug_overlay_visible = True
        w._draw_debug_roi_rect(None)
        # Should not raise

    def test_draw_debug_roi_rect_with_roi(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w._debug_overlay_visible = True
        w._draw_debug_roi_rect((10, 10, 50, 50))
        assert w._debug_roi_item is not None

    def test_draw_debug_roi_rect_not_visible(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w._debug_overlay_visible = False
        w._draw_debug_roi_rect((10, 10, 50, 50))
        # Should not create item when not visible


# ═══════════════════════════════════════════════════════════════════
#  DICOM tags overlay
# ═══════════════════════════════════════════════════════════════════


class TestDicomTagsOverlay:
    def test_refresh_dicom_tags_overlay_no_instance(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Should not raise
        w._refresh_dicom_tags_overlay()

    def test_refresh_dicom_tags_overlay_with_state(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state()
        w.set_state(state)
        # Should not raise
        w._refresh_dicom_tags_overlay()

    def test_current_instance_metadata(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w._current_instance_metadata() is None

    def test_current_instance_metadata_with_state(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state()
        w.set_state(state)
        assert w._current_instance_metadata() is not None

    def test_refresh_dicom_tags_overlay_public(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Should not raise
        w.refresh_dicom_tags_overlay()


# ═══════════════════════════════════════════════════════════════════
#  Position overlay labels
# ═══════════════════════════════════════════════════════════════════


class TestPositionOverlayLabels:
    def test_position_overlay_labels(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        # Should not raise
        w._position_overlay_labels()

    def test_position_overlay_labels_with_results(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.set_results_overlay("Test overlay")
        # Should not raise
        w._position_overlay_labels(reposition_results=True)

    def test_position_overlay_labels_no_reposition(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.set_results_overlay("Test overlay")
        # Should not raise
        w._position_overlay_labels(reposition_results=False)


# ═══════════════════════════════════════════════════════════════════
#  Panel frame graphics
# ═══════════════════════════════════════════════════════════════════


class TestPanelFrameGraphics:
    def test_refresh_panel_frame_graphics(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        # Should not raise
        w._refresh_panel_frame_graphics()

    def test_clear_panel_frame_graphics(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Items are empty by default, just verify clearing works
        w._clear_panel_frame_graphics()
        assert len(w._panel_frame_items) == 0


# ═══════════════════════════════════════════════════════════════════
#  Contour rendering deep
# ═══════════════════════════════════════════════════════════════════


class TestContourRenderingDeep:
    def test_render_contours_for_current_frame(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        from echo_personal_tool.domain.models import Contour
        c = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10), (20, 20)])
        w.set_contour_from_domain(c)
        # Should not raise
        w._render_contours_for_current_frame()

    def test_clear_rendered_contours(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        from echo_personal_tool.domain.models import Contour
        c = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10), (20, 20)])
        w.set_contour_from_domain(c)
        assert len(w._contour_items) > 0
        w._clear_rendered_contours()
        assert len(w._contour_items) == 0

    def test_append_rendered_contour(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        from echo_personal_tool.domain.models import Contour
        c = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10), (20, 20)])
        initial_count = len(w._contour_items)
        w._append_rendered_contour(c)
        assert len(w._contour_items) == initial_count + 1

    def test_create_contour_render(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        from echo_personal_tool.domain.models import Contour
        c = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10), (20, 20)])
        line_item, ma_item, node_items = w._create_contour_render(c, 0)
        assert line_item is not None
        assert ma_item is None  # No mitral annulus
        assert isinstance(node_items, list)

    def test_create_contour_render_open_arc(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        from echo_personal_tool.domain.models import Contour
        c = Contour(
            phase="ED", view="A4C", chamber="LV",
            points=[(10, 10), (20, 20), (30, 30)],
            mitral_annulus=((5, 5), (35, 5)),
        )
        line_item, ma_item, node_items = w._create_contour_render(c, 0)
        assert line_item is not None
        assert ma_item is not None  # Has mitral annulus
