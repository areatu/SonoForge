"""Unit tests for ViewerWidget — the 2D image viewer."""

from __future__ import annotations

import numpy as np
import pytest

from tests.unit.viewer_guard_helpers import guard_snapshot

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


def _la_contour(*, points=((10, 10), (20, 20), (30, 30)), frame_index=0, uid=None):
    from echo_personal_tool.domain.models import Contour

    return Contour(
        phase="ED", view="A4C", chamber="LA", points=list(points), frame_index=frame_index, sop_instance_uid=uid
    )


def _open_arc_contour():
    """An LV open arc with four nodes: the shape optical-flow refinement accepts."""
    from echo_personal_tool.domain.models import Contour

    return Contour(
        phase="ED",
        view="A4C",
        chamber="LV",
        points=[(10, 10), (20, 20), (30, 30), (40, 40)],
        mitral_annulus=((5, 5), (45, 45)),
        frame_index=0,
    )


def _strain_result():
    from echo_personal_tool.domain.models.speckle import StrainResult

    return StrainResult(
        longitudinal=np.zeros(5),
        radial=np.zeros(5),
        gls=0.0,
        kernels=[],
        raw_tracked_positions=None,
    )


def _doppler_state():
    """A velocity calibration the viewer accepts without a frame."""
    from echo_personal_tool.domain.models.doppler_roi import DopplerCalibrationState, DopplerSpectrogramRoi

    return DopplerCalibrationState(
        roi=DopplerSpectrogramRoi(x0=0.0, y0=0.0, width=120.0, height=80.0),
        baseline_y_px=50.0,
        velocity_span_cm_s=200.0,
    )


def _one_peak_dto():
    from echo_personal_tool.domain.models.doppler import DopplerMeasurementDTO, DopplerPeakMarker

    return DopplerMeasurementDTO(
        peaks=(DopplerPeakMarker(label="E", time_ms=100.0, velocity_cm_s=120.0),),
        intervals=(),
        traces=(),
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
        assert w.doppler.overlay is not None

    def test_has_speckle_overlay(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w.contract.speckle_overlay is not None

    def test_has_timeline_slider(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w.contract.timeline_slider is not None

    def test_has_play_button(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w.contract.play_button is not None

    def test_initial_frame_is_none(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert not w.has_frame

    def test_initial_state_is_none(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w.current_state() is None


# ═══════════════════════════════════════════════════════════════════
#  show_frame
# ═══════════════════════════════════════════════════════════════════


class TestShowFrame:
    def test_grayscale_frame(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        frame = np.random.randint(0, 255, (128, 128), dtype=np.uint8)
        w.show_frame(frame)
        assert w.has_frame
        assert w.frame_shape == (128, 128)

    def test_rgb_frame(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        frame = np.random.randint(0, 255, (128, 128, 3), dtype=np.uint8)
        w.show_frame(frame)
        assert w.has_frame

    def test_small_frame(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        frame = np.zeros((16, 16), dtype=np.uint8)
        w.show_frame(frame)
        assert w.has_frame
        assert w.frame_shape == (16, 16)

    def test_large_frame(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        frame = np.zeros((512, 512), dtype=np.uint8)
        w.show_frame(frame)
        assert w.has_frame

    def test_constant_frame(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        frame = np.full((64, 64), 128, dtype=np.uint8)
        w.show_frame(frame)
        assert w.has_frame


# ═══════════════════════════════════════════════════════════════════
#  set_state
# ═══════════════════════════════════════════════════════════════════


class TestSetState:
    def test_sets_state(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state()
        w.set_state(state)
        assert w.current_state() is state

    def test_updates_timeline_range(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state(total=10)
        w.set_state(state)
        assert w.contract.timeline_slider.maximum() == 9

    def test_sets_timeline_value(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state(frame=3, total=10)
        w.set_state(state)
        assert w.contract.timeline_slider.value() == 3

    def test_play_button_accessible_caption_playing(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state(playing=True, total=5)
        w.set_state(state)
        assert "Пауза" in w.contract.play_button.accessibleName() or "Pause" in w.contract.play_button.accessibleName()
        assert w.contract.play_button.text() == ""
        assert not w.contract.play_button.icon().isNull()

    def test_play_button_accessible_caption_stopped(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state(playing=False, total=5)
        w.set_state(state)
        text = w.contract.play_button.accessibleName()
        assert w.contract.play_button.text() == ""
        assert not w.contract.play_button.icon().isNull()
        assert "Воспроизведение" in text or "Play" in text

    def test_disables_controls_for_single_frame(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state(total=1)
        w.set_state(state)
        assert w.contract.timeline_slider.isEnabled() is False

    def test_enables_controls_for_multi_frame(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state(total=5)
        w.set_state(state)
        assert w.contract.timeline_slider.isEnabled() is True

    def test_frame_counter_keeps_its_width_while_digit_count_changes(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.set_transport_state(frame_index=8, total_frames=120, frame_time_ms=33.3, is_playing=True)
        reserved_width = w.contract.source_label.width()

        w.set_transport_state(frame_index=99, total_frames=120, frame_time_ms=33.3, is_playing=True)

        assert w.contract.source_label.width() == reserved_width
        assert "100/120" in w.contract.source_label.text()

    def test_fps_label_with_fps(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state(fps=30.0, total=5)
        w.set_state(state)
        assert "30.0" in w.contract.fps_label.text()

    def test_fps_label_without_fps(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state(fps=0, total=5)
        w.set_state(state)
        assert "—" in w.contract.fps_label.text()

    def test_fps_label_double_click_requests_override(self, qtbot) -> None:
        """The transport's «FPS» label is the entry point of the per-clip retiming dialog."""
        from PySide6.QtCore import QEvent, QPointF
        from PySide6.QtGui import QMouseEvent

        w = _make_viewer(qtbot)
        received: list[bool] = []
        w.fps_override_requested.connect(lambda: received.append(True))

        label = w.contract.fps_label
        center = QPointF(label.rect().center())
        label.mouseDoubleClickEvent(
            QMouseEvent(
                QEvent.Type.MouseButtonDblClick,
                center,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )

        assert received == [True]


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
        assert w.is_calibration_active is True

    def test_toggle_calibration_off(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.toggle_calibration_caliper()
        w.toggle_calibration_caliper()
        assert w.is_calibration_active is False

    def test_toggle_calibration_without_frame(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.toggle_calibration_caliper()
        assert w.is_calibration_active is False


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

    def test_start_mmode_frame_caliper_sequence_requires_calibration(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        assert w.mmode.start_frame_caliper_sequence(("IVSd", "LVEDD", "LVPWd")) is False

    def test_start_mmode_frame_caliper_sequence_marks_labels_vertical(self, qtbot) -> None:
        from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi
        from echo_personal_tool.domain.models.frame_panels import MmodeCalibrationState

        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.mmode.apply_calibration_state(
            MmodeCalibrationState(
                roi=DopplerSpectrogramRoi(x0=0, y0=0, width=64, height=64),
                vertical_mm_per_pixel=0.5,
                horizontal_ms_per_pixel=4.0,
            )
        )
        assert w.mmode.start_frame_caliper_sequence(("IVSd", "LVEDD", "LVPWd")) is True
        assert {"IVSd", "LVEDD", "LVPWd"} <= w.contract.vertical_caliper_labels

    def test_generic_caliper_resets_mmode_session_vertical_labels(self, qtbot) -> None:
        from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi
        from echo_personal_tool.domain.models.frame_panels import MmodeCalibrationState

        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.mmode.apply_calibration_state(
            MmodeCalibrationState(
                roi=DopplerSpectrogramRoi(x0=0, y0=0, width=64, height=64),
                vertical_mm_per_pixel=0.5,
                horizontal_ms_per_pixel=4.0,
            )
        )
        assert w.mmode.start_frame_caliper_sequence(("IVSd", "LVEDD", "LVPWd")) is True
        assert w.start_linear_caliper_for("IVSd") is True
        assert "IVSd" not in w.contract.vertical_caliper_labels
        assert "TAPSE" in w.contract.vertical_caliper_labels


# ═══════════════════════════════════════════════════════════════════
#  Doppler
# ═══════════════════════════════════════════════════════════════════


class TestDoppler:
    def test_get_doppler_tool_mode(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        mode = w.doppler.get_tool_mode()
        assert isinstance(mode, str)

    def test_get_doppler_calibration_state_none(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w.doppler.get_calibration_state() is None

    def test_clear_doppler_measurements(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.doppler.restore_measurements(_one_peak_dto())
        assert len(w.doppler.get_dto().peaks) == 1

        w.doppler.clear_measurements()

        dto = w.doppler.get_dto()
        assert (dto.peaks, dto.intervals, dto.traces) == ((), (), ())

    def test_clear_doppler_calibration_display(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Should not raise
        w.doppler.clear_calibration_display()
        assert w.doppler.get_calibration_state() is None

        w.doppler.apply_calibration_state(_doppler_state(), persist=False)
        assert w.doppler.is_velocity_calibrated()
        w.doppler.clear_calibration_display()
        assert w.doppler.get_calibration_state() is None
        assert not w.doppler.is_velocity_calibrated()

    def test_get_doppler_dto(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        dto = w.doppler.get_dto()
        # dto may be None or a DTO object
        assert dto is None or hasattr(dto, "peaks")


# ═══════════════════════════════════════════════════════════════════
#  MMode
# ═══════════════════════════════════════════════════════════════════


class TestMMode:
    def test_get_mmode_calibration_state_none(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w.mmode.calibration_state is None

    def test_set_mmode_vertical_lock(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.mmode.set_vertical_lock(True)
        assert w.mmode.vertical_lock is True
        w.mmode.set_vertical_lock(False)
        assert w.mmode.vertical_lock is False


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
        w.show_speckle_result(_strain_result())
        assert w.speckle_result() is not None

        w.clear_speckle_overlay()

        assert w.speckle_result() is None


# ═══════════════════════════════════════════════════════════════════
#  Frame overlay
# ═══════════════════════════════════════════════════════════════════


class TestFrameOverlay:
    def test_clear_frame_overlay(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.append_frame_overlay("line 1")
        assert w.frame_overlay_lines() == ("line 1",)

        w.clear_frame_overlay()

        assert w.frame_overlay_lines() == ()


# ═══════════════════════════════════════════════════════════════════
#  Debug overlay
# ═══════════════════════════════════════════════════════════════════


class TestDebugOverlay:
    def test_toggle_debug_overlay(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        initial = w.is_debug_overlay_visible
        w.toggle_debug_overlay()
        assert w.is_debug_overlay_visible is not initial


# ═══════════════════════════════════════════════════════════════════
#  Results overlay
# ═══════════════════════════════════════════════════════════════════


class TestResultsOverlay:
    def test_set_results_overlay(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.set_results_overlay("LVEF: 55%")
        assert w.contract.results_overlay_label.text() == "LVEF: 55%"
        assert w.contract.results_overlay_label.isVisible()

    def test_set_results_overlay_empty(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.set_results_overlay("")
        assert not w.contract.results_overlay_label.isVisible()

    def test_results_overlay_position(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.set_results_overlay_position(0.5, 0.5)
        # Should not raise
        assert w.results_overlay_position() == (0.5, 0.5)
        assert w.results_overlay_custom_position() is True


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
        assert w.contract.view.viewer_widget is w


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
        assert w.has_frame

    def test_set_state_after_show_frame(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        frame = np.random.randint(0, 255, (128, 128), dtype=np.uint8)
        w.show_frame(frame)
        state = _make_state(total=5)
        w.set_state(state)
        assert w.current_state() is state

    def test_multiple_set_state_calls(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        for i in range(5):
            state = _make_state(frame=i, total=10)
            w.set_state(state)
        assert w.current_state().current_frame_index == 4


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
        w.contract.caliper_drag_active = True
        event = self._make_key_event(Qt.Key.Key_Escape)
        w.keyPressEvent(event)
        assert w.contract.caliper_drag_active is False

    def test_ctrl_shift_d_toggles_debug(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        initial = w.is_debug_overlay_visible
        event = self._make_key_event(
            Qt.Key.Key_D,
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
        )
        w.keyPressEvent(event)
        assert w.is_debug_overlay_visible is not initial

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

        assert w.is_calibration_active is False
        assert w.is_linear_caliper_active is False
        assert w.doppler.get_tool_mode() == "none"

    def test_cancel_calibration(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.toggle_calibration_caliper()
        assert w.is_calibration_active is True
        w.cancel_active_tool()
        assert w.is_calibration_active is False

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
        w.doppler.cal_step = "baseline"
        w.cancel_active_tool()
        assert w.doppler.cal_step is None

    def test_cancel_mmode_cal_step(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        assert w.mmode.start_panel_calibration() is True
        w.cancel_active_tool()
        assert w.mmode.cal_step is None

    def test_cancel_caliper_drag(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.contract.caliper_drag_active = True
        w.cancel_active_tool()
        assert w.contract.caliper_drag_active is False


# ═══════════════════════════════════════════════════════════════════
#  Timeline / step navigation
# ═══════════════════════════════════════════════════════════════════


class TestTimeline:
    def test_step_forward(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state(frame=0, total=5)
        w.set_state(state)
        w.contract.step_forward()
        assert w.contract.timeline_slider.value() == 1

    def test_step_back(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state(frame=2, total=5)
        w.set_state(state)
        w.contract.step_back()
        assert w.contract.timeline_slider.value() == 1

    def test_step_forward_at_end(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state(frame=4, total=5)
        w.set_state(state)
        w.contract.step_forward()
        assert w.contract.timeline_slider.value() == 4

    def test_step_back_at_start(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state(frame=0, total=5)
        w.set_state(state)
        w.contract.step_back()
        assert w.contract.timeline_slider.value() == 0


# ═══════════════════════════════════════════════════════════════════
#  Caliper label cycling
# ═══════════════════════════════════════════════════════════════════


class TestCaliperLabelCycling:
    def test_cycle_caliper_label(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        initial_idx = w.contract.caliper_label_index
        w.cycle_caliper_label()
        assert w.contract.caliper_label_index == (initial_idx + 1) % len(w.contract.caliper_labels)

    def test_cycle_caliper_label_wraps(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.contract.caliper_label_index = len(w.contract.caliper_labels) - 1
        w.cycle_caliper_label()
        assert w.contract.caliper_label_index == 0

    def test_cycle_caliper_label_resets_start(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.toggle_linear_caliper()
        w.contract.linear_caliper_start = (10.0, 20.0)
        w.cycle_caliper_label()
        assert w.contract.linear_caliper_start is None


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
        assert w.is_contour_mode_active is True

    def test_start_model_contour(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        result = w.start_model_contour(phase="ED")
        assert result is True
        assert w.contract.contour_mode_kind == "model"

    def test_start_closed_contour(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        result = w.start_closed_contour(chamber="LA")
        assert result is True
        assert w.contract.contour_mode_kind == "closed"

    def test_start_generic_area_contour(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        result = w.start_generic_area_contour()
        assert result is True
        assert w.contract.active_contour_chamber == "AREA"

    def test_start_generic_volume_contour(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        result = w.start_generic_volume_contour()
        assert result is True
        assert w.contract.active_contour_chamber == "VOL"

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
        assert w.is_contour_mode_active is True
        w.cancel_active_tool()
        assert w.is_contour_mode_active is False


# ═══════════════════════════════════════════════════════════════════
#  show_frame_fast
# ═══════════════════════════════════════════════════════════════════


class TestShowFrameFast:
    def test_fast_frame_grayscale(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        frame = np.random.randint(0, 255, (64, 64), dtype=np.uint8)
        w.show_frame_fast(frame)
        assert w.has_frame

    def test_fast_frame_rgb(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64, 3), dtype=np.uint8))
        frame = np.random.randint(0, 255, (64, 64, 3), dtype=np.uint8)
        w.show_frame_fast(frame)
        assert w.has_frame


# ═══════════════════════════════════════════════════════════════════
#  refresh_after_scroll
# ═══════════════════════════════════════════════════════════════════


class TestRefreshAfterScroll:
    def test_refresh_after_scroll(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.contract.frame_panels_from_dicom = True
        w.contract.frame_panel_layout = object()
        # Should not raise
        w.refresh_after_scroll()
        assert w.contract.frame_panels_from_dicom is False
        assert w.contract.frame_panel_layout is None, "the layout must be recomputed, not inherited"

    def test_refresh_after_scroll_no_frame(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Should not raise even without frame
        before = guard_snapshot(w)
        w.refresh_after_scroll()
        assert guard_snapshot(w) == before, "test_refresh_after_scroll_no_frame: guard handler changed viewer state"
        assert w.has_frame is False


# ═══════════════════════════════════════════════════════════════════
#  Doppler operations
# ═══════════════════════════════════════════════════════════════════


class TestDopplerOperations:
    def test_finish_doppler_trace(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        result = w.doppler.finish_trace()
        assert isinstance(result, bool)

    def test_finish_doppler_trace_shows_vti_value(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        from echo_personal_tool.domain.models.doppler_axis import DopplerAxisMapping
        from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi

        roi = DopplerSpectrogramRoi(x0=0.0, y0=0.0, width=1000.0, height=200.0)
        mapping = DopplerAxisMapping(
            roi=roi,
            baseline_y_px=100.0,
            velocity_span_cm_s=200.0,
            velocity_min_cm_s=-100.0,
            velocity_max_cm_s=100.0,
            plot_width=1000.0,
            plot_height=200.0,
            time_span_ms=2000.0,
        )
        w.doppler.overlay.set_axis_mapping(mapping)

        w.doppler.start_envelope_trace(
            ((0.0, 100.0), (100.0, 50.0), (200.0, 100.0)),
            trace_label="VTI MV",
        )
        assert w.doppler.finish_trace() is True
        assert "MV VTI" in w.contract.measurement_label.text()
        assert "10 cm" in w.contract.measurement_label.text()
        assert "—" not in w.contract.measurement_label.text()

    def test_start_doppler_calibration(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        result = w.doppler.start_calibration(DopplerKind.SPECTRAL)
        assert isinstance(result, bool)

    def test_start_mitral_inflow_workflow(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        result = w.doppler.start_mitral_inflow_workflow()
        assert isinstance(result, bool)

    def test_start_doppler_scale_calibration(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        result = w.doppler.start_scale_calibration()
        assert isinstance(result, bool)


# ═══════════════════════════════════════════════════════════════════
#  MMode operations
# ═══════════════════════════════════════════════════════════════════


class TestMModeOperations:
    def test_start_mmode_line(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.mmode.start_line()
        assert w.mmode.line_active is True

    def test_start_mmode_panel_calibration(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        result = w.mmode.start_panel_calibration()
        assert isinstance(result, bool)


# ═══════════════════════════════════════════════════════════════════
#  Speckle overlay
# ═══════════════════════════════════════════════════════════════════


class TestSpeckleOverlay:
    def test_show_speckle_result_invalid(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        result = _strain_result()
        w.show_speckle_result(result)

        # Should not raise with non-StrainResult
        w.show_speckle_result("not a result")

        assert w.speckle_result() is result, "an object that is not a StrainResult does not replace the shown one"

    def test_clear_speckle_overlay(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.clear_speckle_overlay()
        assert w.speckle_result() is None


# ═══════════════════════════════════════════════════════════════════
#  Results overlay settings
# ═══════════════════════════════════════════════════════════════════


class TestResultsOverlaySettings:
    def test_set_results_overlay_position(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.set_results_overlay("Test")
        w.set_results_overlay_position(0.3, 0.7)
        # Should not raise
        assert w.results_overlay_position() == (0.3, 0.7)
        assert "Test" in w.results_overlay_text()

    def test_results_overlay_custom_position(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.set_results_overlay_position(0.2, 0.4)  # the physician dragged the box
        w.set_results_overlay("Test")
        # Should not raise
        assert w.results_overlay_custom_position() is True, "new text does not take the box back to its default place"
        assert w.results_overlay_position() == (0.2, 0.4)
        assert "Test" in w.results_overlay_text()


# ═══════════════════════════════════════════════════════════════════
#  Toggle methods
# ═══════════════════════════════════════════════════════════════════


class TestToggleMethods:
    def test_toggle_debug_overlay(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        initial = w.is_debug_overlay_visible
        w.toggle_debug_overlay()
        assert w.is_debug_overlay_visible is not initial

    def test_toggle_ghost_mode(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        result = w.toggle_ghost_mode()
        assert isinstance(result, str)

    def test_set_ghost_mode(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.set_ghost_mode("center")
        assert w.ghost_mode == "center"

    def test_set_magnetic_snap_enabled(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.set_magnetic_snap_enabled(False)
        assert w.magnetic_snap_enabled() is False

    def test_set_despeckle_enabled(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.set_despeckle_enabled(True)
        assert w.despeckle_enabled() is True

    def test_direct_attribute_toggles(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Test direct attribute setting for boolean flags
        w.contract.show_crosshair = False
        assert w.contract.show_crosshair is False
        w.contract.show_panel_frames = True
        assert w.contract.show_panel_frames is True
        w.contract.show_caliper_labels_on_frame = False
        assert w.contract.show_caliper_labels_on_frame is False
        w.contract.show_caliper_inline_labels = True
        assert w.contract.show_caliper_inline_labels is True


# ═══════════════════════════════════════════════════════════════════
#  Settings methods
# ═══════════════════════════════════════════════════════════════════


class TestSettingsMethods:
    def test_set_scroll_debounce_ms(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.set_scroll_debounce_ms(100)
        assert w.contract.scroll_debounce_ms == 100

    def test_set_magnetic_snap_enabled(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.set_magnetic_snap_enabled(True)
        assert w.magnetic_snap_enabled() is True

    def test_set_despeckle_enabled(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.set_despeckle_enabled(True)
        assert w.despeckle_enabled() is True

    def test_set_image_smooth(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.contract.set_image_smooth(False)
        assert w.contract.image_smooth is False
        w.contract.set_image_smooth(True)
        assert w.contract.image_smooth is True

    def test_set_doppler_auto_calibration(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.doppler.auto_calibration_enabled = False
        assert w.doppler.auto_calibration_enabled is False

    def test_direct_attribute_settings(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Test direct attribute setting
        w.contract.length_display_unit = "cm"
        assert w.contract.length_display_unit == "cm"
        w.contract.caliper_line_width = 3.0
        assert w.contract.caliper_line_width == 3.0


# ═══════════════════════════════════════════════════════════════════
#  Doppler tool mode
# ═══════════════════════════════════════════════════════════════════


class TestDopplerToolMode:
    def test_set_doppler_tool_mode(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.doppler.set_tool_mode("peak")
        assert w.doppler.get_tool_mode() == "peak"

    def test_set_doppler_tool_mode_interval(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.doppler.set_tool_mode("interval")
        assert w.doppler.get_tool_mode() == "interval"

    def test_set_doppler_tool_mode_trace(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.doppler.set_tool_mode("trace")
        assert w.doppler.get_tool_mode() == "trace"


# ═══════════════════════════════════════════════════════════════════
#  Window/level preferences
# ═══════════════════════════════════════════════════════════════════


class TestWindowLevel:
    def test_apply_window_level_preferences(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from echo_personal_tool.infrastructure.user_preferences import UserPreferences

        prefs = UserPreferences()
        before = guard_snapshot(w)
        w.contract.apply_window_level_preferences(prefs)
        assert guard_snapshot(w) == before, "test_apply_window_level_preferences: guard handler changed viewer state"
        from echo_personal_tool.application.user_preferences import resolve_wl_values

        window, level, dr = resolve_wl_values(prefs)
        assert w.contract.window_slider.value() == window
        assert w.contract.level_slider.value() == level
        assert w.contract.dr_slider.value() == dr
        # Should not raise

    def test_update_levels(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        before = guard_snapshot(w)
        w.contract.update_levels()
        assert guard_snapshot(w) == before, "test_update_levels: guard handler changed viewer state"
        # Should not raise

    def test_update_levels_with_color_frame(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64, 3), dtype=np.uint8))
        before = guard_snapshot(w)
        w.contract.update_levels()
        assert guard_snapshot(w) == before, "test_update_levels_with_color_frame: guard handler changed viewer state"
        # Should not raise


# ═══════════════════════════════════════════════════════════════════
#  Contour phase resolution
# ═══════════════════════════════════════════════════════════════════


class TestContourPhase:
    def test_resolve_contour_phase(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        phase = w.contract.resolve_contour_phase()
        assert isinstance(phase, str)

    def test_resolve_contour_phase_with_state(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state(frame=0, total=5)
        w.set_state(state)
        phase = w.contract.resolve_contour_phase()
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
        w.contract.frame_overlay_lines = ["test"]
        w.clear_frame_overlay()
        assert w.frame_overlay_lines() == ()

    def test_append_frame_overlay(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.append_frame_overlay("line1")
        assert "line1" in w.frame_overlay_lines()

    def test_append_multiple_frame_overlay(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.append_frame_overlay("line1")
        w.append_frame_overlay("line2")
        assert len(w.frame_overlay_lines()) == 2


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
        assert w.doppler.get_calibration_state() is None

    def test_get_mmode_calibration_state_none(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w.mmode.calibration_state is None

    def test_get_doppler_dto(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        dto = w.doppler.get_dto()
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
        mode = w.doppler.get_tool_mode()
        assert isinstance(mode, str)

    def test_contour_viewing_mode(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w.is_contour_mode_active is False

    def test_initial_doppler_state(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w.doppler.axis_calibrated is False
        assert w.doppler.get_calibration_state() is None


# ═══════════════════════════════════════════════════════════════════
#  Frame overlay refresh
# ═══════════════════════════════════════════════════════════════════


class TestFrameOverlayRefresh:
    def test_refresh_overlay_with_content(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.contract.frame_overlay_lines = ["Test overlay line"]
        w.contract.refresh_frame_overlay()
        assert w.contract.overlay_label.isVisible()

    def test_refresh_overlay_empty_hides(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.contract.frame_overlay_lines = []
        w.contract.refresh_frame_overlay()
        assert not w.contract.overlay_label.isVisible()

    def test_refresh_overlay_calibration_banner(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        from echo_personal_tool.infrastructure.i18n import tr
        from echo_personal_tool.presentation.viewer_widget import CALIBRATION_PROMPT_OVERLAY_KEY

        w.contract.frame_overlay_lines = [tr(CALIBRATION_PROMPT_OVERLAY_KEY)]
        w.contract.refresh_frame_overlay()
        assert w.contract.overlay_label.isVisible()

    def test_refresh_overlay_calibration_ok(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        from echo_personal_tool.infrastructure.i18n import tr
        from echo_personal_tool.presentation.viewer_widget import CALIBRATION_SUCCESS_OVERLAY_KEY

        w.contract.frame_overlay_lines = [tr(CALIBRATION_SUCCESS_OVERLAY_KEY)]
        w.contract.refresh_frame_overlay()
        assert w.contract.overlay_label.isVisible()

    def test_clear_frame_overlay_clears_lines(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.contract.frame_overlay_lines = ["line1", "line2"]
        w.clear_frame_overlay()
        assert w.frame_overlay_lines() == ()


# ═══════════════════════════════════════════════════════════════════
#  Linear caliper clear
# ═══════════════════════════════════════════════════════════════════


class TestLinearCaliperClear:
    def test_clear_linear_caliper_resets_state(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.toggle_linear_caliper()
        assert w.is_linear_caliper_active is True
        w.contract.clear_linear_caliper()
        assert w.is_linear_caliper_active is False
        assert w.contract.linear_caliper_start is None
        assert w.contract.caliper_sequence == []

    def test_clear_linear_caliper_graphics(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Items are already None by default, just verify clearing works
        w.contract.clear_linear_caliper_graphics()
        assert w.contract.linear_caliper_line_item is None
        assert w.contract.linear_caliper_marker_item is None
        assert w.contract.active_caliper_label_item is None


# ═══════════════════════════════════════════════════════════════════
#  Calibration caliper clear
# ═══════════════════════════════════════════════════════════════════


class TestCalibrationCaliperClear:
    def test_clear_calibration_caliper_resets_state(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.contract.calibration_active = True
        w.contract.calibration_start_y = 10.0
        w.contract.calibration_kind = "depth"
        w.doppler.grid_line_positions = [10.0, 20.0]
        w.contract.clear_calibration_caliper()
        assert w.is_calibration_active is False
        assert w.contract.calibration_start_y is None
        assert w.contract.calibration_kind is None
        assert w.doppler.grid_line_positions == []

    def test_clear_calibration_graphics(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Items are already None by default, just verify clearing works
        w.contract.clear_calibration_graphics()
        assert w.contract.calibration_line_item is None
        assert w.contract.calibration_marker_item is None
        assert w.contract.calibration_h_guide_start_item is None
        assert w.contract.calibration_h_guide_end_item is None


# ═══════════════════════════════════════════════════════════════════
#  Calibration horizontal guides
# ═══════════════════════════════════════════════════════════════════


class TestCalibrationGuides:
    def test_ensure_calibration_horizontal_guides(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.contract.ensure_calibration_horizontal_guides()
        assert w.contract.calibration_h_guide_start_item is not None
        assert w.contract.calibration_h_guide_end_item is not None

    def test_ensure_guides_idempotent(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.contract.ensure_calibration_horizontal_guides()
        first_start = w.contract.calibration_h_guide_start_item
        first_end = w.contract.calibration_h_guide_end_item
        w.contract.ensure_calibration_horizontal_guides()
        assert w.contract.calibration_h_guide_start_item is first_start
        assert w.contract.calibration_h_guide_end_item is first_end

    def test_update_calibration_guides_no_active(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Should not raise even when calibration is not active
        before = guard_snapshot(w)
        w.contract.update_calibration_horizontal_guides(50.0)
        assert guard_snapshot(w) == before, (
            "test_update_calibration_guides_no_active: guard handler changed viewer state"
        )

    def test_update_calibration_guides_mmode_time(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.contract.calibration_active = True
        w.contract.calibration_start_y = 10.0
        w.contract.calibration_kind = "mmode_time"
        # Should return early for mmode_time
        before = guard_snapshot(w)
        w.contract.update_calibration_horizontal_guides(50.0)
        assert guard_snapshot(w) == before, (
            "test_update_calibration_guides_mmode_time: guard handler changed viewer state"
        )


# ═══════════════════════════════════════════════════════════════════
#  Ghost mode
# ═══════════════════════════════════════════════════════════════════


class TestGhostMode:
    def test_set_ghost_mode(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.set_ghost_mode("center")
        assert w.ghost_mode == "center"

    def test_toggle_ghost_mode(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        result = w.toggle_ghost_mode()
        assert isinstance(result, str)

    def test_render_ghost_overlay_off(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.set_ghost_mode("off")
        w.contract.render_ghost_overlay()
        assert len(w.contract.ghost_items) == 0

    def test_render_ghost_overlay_no_result(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.set_ghost_mode("center")
        w.contract.render_ghost_overlay()
        assert len(w.contract.ghost_items) == 0

    def test_clear_ghost_overlay(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Ghost items are empty by default
        w.contract.clear_ghost_overlay()
        assert len(w.contract.ghost_items) == 0

    def test_get_fusion_result_no_controller(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        result = w.contract.get_fusion_result()
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
        idx = w.contract.find_stored_contour_index(contour)
        assert idx is not None

    def test_find_stored_contour_index_not_found(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        from echo_personal_tool.domain.models import Contour

        contour = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10)])
        other = Contour(phase="ES", view="A4C", chamber="LA", points=[(20, 20)])
        w.set_contour_from_domain(contour)
        idx = w.contract.find_stored_contour_index(other)
        assert idx is None

    def test_upsert_stored_contour_new(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from echo_personal_tool.domain.models import Contour

        contour = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10)])
        w.contract.upsert_stored_contour(contour)
        assert len(w.contract.stored_contours) == 1

    def test_upsert_stored_contour_update(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from echo_personal_tool.domain.models import Contour

        c1 = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10)])
        c2 = Contour(phase="ED", view="A4C", chamber="LV", points=[(20, 20)])
        w.contract.upsert_stored_contour(c1)
        w.contract.upsert_stored_contour(c2)
        assert len(w.contract.stored_contours) == 1
        assert w.contract.stored_contours[0].points == [(20, 20)]

    def test_current_instance_uid(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w.current_instance_uid() is None

    def test_current_instance_uid_with_state(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state()
        w.set_state(state)
        uid = w.current_instance_uid()
        assert uid is not None

    def test_tag_contour_instance_no_uid(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from echo_personal_tool.domain.models import Contour

        contour = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10)])
        result = w.contract.tag_contour_instance(contour)
        assert result is contour

    def test_contour_frame_index(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w.contract.contour_frame_index() is None

    def test_contour_frame_index_with_state(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state(frame=3)
        w.set_state(state)
        assert w.contract.contour_frame_index() == 3

    def test_clear_active_contour_drawing(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.contract.contour_mode_active = True
        w.contract.contour_stage = "arc"
        w.contract.active_mitral_septal = (10, 10)
        w.contract.active_arc_points = [(20, 20)]
        w.contract.clear_active_contour_drawing()
        assert w.is_contour_mode_active is False
        assert w.contract.contour_stage is None
        assert w.contract.active_mitral_septal is None
        assert w.contract.active_arc_points == []

    def test_set_contour_nodes_pickable(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Should not raise even with empty nodes
        w.contract.set_contour_nodes_pickable(True)
        before = guard_snapshot(w)
        w.contract.set_contour_nodes_pickable(False)
        assert guard_snapshot(w) == before, "test_set_contour_nodes_pickable: guard handler changed viewer state"

    def test_contour_editing_blocked(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w.contract.contour_editing_blocked() is False
        w.contract.contour_mode_active = True
        assert w.contract.contour_editing_blocked() is True
        w.contract.contour_mode_active = False
        w.contract.linear_caliper_active = True
        assert w.contract.contour_editing_blocked() is True
        w.contract.linear_caliper_active = False
        w.contract.calibration_active = True
        assert w.contract.contour_editing_blocked() is True


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
        assert w.is_contour_mode_active is True
        # Click in arc/polygon stage
        w.contract.contour_stage = "arc"
        result = w.handle_contour_click((10.0, 10.0))
        assert result is True
        assert len(w.contract.active_arc_points) == 1

    def test_start_closed_contour_then_click(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.start_closed_contour(chamber="LA")
        w.contract.contour_stage = "polygon"
        w.handle_contour_click((10.0, 10.0))
        w.handle_contour_click((20.0, 10.0))
        w.handle_contour_click((20.0, 20.0))
        assert len(w.contract.active_arc_points) == 3

    def test_finish_contour_polygon(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.start_closed_contour(chamber="LA")
        w.contract.contour_stage = "polygon"
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
        assert w.is_contour_mode_active is True
        w.cancel_active_tool()
        assert w.is_contour_mode_active is False


# ═══════════════════════════════════════════════════════════════════
#  Wheel event handling
# ═══════════════════════════════════════════════════════════════════


class TestWheelEvent:
    def _make_wheel_event(self, angle_delta_y=120, modifiers=Qt.KeyboardModifier.NoModifier):
        from PySide6.QtCore import QPoint, QPointF
        from PySide6.QtGui import QWheelEvent

        return QWheelEvent(
            QPointF(0, 0),
            QPointF(0, 0),
            QPoint(0, 0),
            QPoint(0, angle_delta_y),
            Qt.MouseButton.NoButton,
            modifiers,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )

    def test_handle_wheel_no_state(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        event = self._make_wheel_event()
        result = w.contract.handle_wheel(event)
        assert result is False

    def test_handle_wheel_single_frame(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state(total=1)
        w.set_state(state)
        event = self._make_wheel_event()
        result = w.contract.handle_wheel(event)
        assert result is False

    def test_handle_wheel_multi_frame(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state(total=10)
        w.set_state(state)
        event = self._make_wheel_event()
        w.contract.scroll_debounce_ms = 0
        result = w.contract.handle_wheel(event)
        assert result is True

    def test_handle_ctrl_wheel(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        event = self._make_wheel_event(
            angle_delta_y=120,
            modifiers=Qt.KeyboardModifier.ControlModifier,
        )
        result = w.contract.handle_ctrl_wheel(event, 120)
        assert result is True
        assert w.zoom_factor > 1.0

    def test_handle_ctrl_wheel_no_frame(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        event = self._make_wheel_event(
            angle_delta_y=120,
            modifiers=Qt.KeyboardModifier.ControlModifier,
        )
        result = w.contract.handle_ctrl_wheel(event, 120)
        assert result is False


# ═══════════════════════════════════════════════════════════════════
#  MMode operations
# ═══════════════════════════════════════════════════════════════════


class TestMModeDeep:
    def test_start_mmode_line_sets_active(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.mmode.start_line()
        assert w.mmode.line_active is True
        assert w.mmode.line_click_step == "start"

    def test_mmode_line_click_start(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.mmode.start_line()
        result = w.mmode.handle_line_click(10.0, 10.0)
        assert result is True
        assert w.mmode.line_click_step == "end"

    def test_mmode_line_click_end(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.mmode.start_line()
        w.mmode.handle_line_click(10.0, 10.0)
        result = w.mmode.handle_line_click(50.0, 50.0)
        assert result is True

    def test_mmode_vertical_lock(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.mmode.set_vertical_lock(True)
        assert w.mmode.vertical_lock is True
        w.mmode.set_vertical_lock(False)
        assert w.mmode.vertical_lock is False


# ═══════════════════════════════════════════════════════════════════
#  Doppler calibration operations
# ═══════════════════════════════════════════════════════════════════


class TestDopplerCalibrationDeep:
    def test_start_doppler_calibration(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        result = w.doppler.start_calibration(DopplerKind.SPECTRAL)
        assert isinstance(result, bool)

    def test_start_mitral_inflow_workflow(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        result = w.doppler.start_mitral_inflow_workflow()
        assert isinstance(result, bool)

    def test_start_doppler_envelope_trace(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        result = w.doppler.start_envelope_trace(plot_points=[(10, 10), (20, 20)])
        # May return None or a value
        assert result is None or isinstance(result, (bool, tuple))

    def test_finish_doppler_trace(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        result = w.doppler.finish_trace()
        assert isinstance(result, bool)

    def test_clear_doppler_measurements(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.doppler.restore_measurements(_one_peak_dto())
        assert len(w.doppler.get_dto().peaks) == 1

        w.doppler.clear_measurements()

        dto = w.doppler.get_dto()
        assert (dto.peaks, dto.intervals, dto.traces) == ((), (), ())

    def test_clear_doppler_calibration_display(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.doppler.calibration_state = "mock"
        w.doppler.clear_calibration_display()
        assert w.doppler.get_calibration_state() is None


# ═══════════════════════════════════════════════════════════════════
#  Speckle overlay deep
# ═══════════════════════════════════════════════════════════════════


class TestSpeckleOverlayDeep:
    def test_show_speckle_result_invalid_type(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_speckle_result("not a StrainResult")
        assert w.speckle_result() is None

    def test_clear_speckle_overlay_resets(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.contract.speckle_result = "mock"
        w.clear_speckle_overlay()
        assert w.speckle_result() is None

    def test_refresh_speckle_no_result(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        # Should not raise
        before = guard_snapshot(w)
        w.contract.refresh_speckle_overlay_for_current_frame()
        assert guard_snapshot(w) == before, "test_refresh_speckle_no_result: guard handler changed viewer state"
        assert w.contract.speckle_overlay.segment_labels == []

    def test_ste_smoothness_replaces_frozen_result(self, qtbot) -> None:
        """Moving the smoothness slider must not crash on the frozen StrainResult
        dataclass and must re-smooth only the tracked window (regression: direct
        attribute assignment raised FrozenInstanceError, and NaN rows outside the
        window were fed into the spline/Savitzky-Golay filters)."""
        import numpy as np

        from echo_personal_tool.domain.models.speckle import StrainResult, TrackingKernel

        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        n_frames, n_kern = 20, 12
        kernels = [
            TrackingKernel(
                center=(32.0, 32.0),
                node_index=i,
                layer="endo" if i < 4 else ("mid" if i < 8 else "epi"),
                radius=4,
                arc_length_param=i / (n_kern - 1),
            )
            for i in range(n_kern)
        ]
        # raw/ncc full-cine arrays with NaN outside the tracked window
        raw = np.full((n_frames, n_kern, 2), np.nan)
        ncc = np.full((n_frames, n_kern), np.nan)
        ws, we = 4, 14
        rng = np.random.default_rng(3)
        raw[ws : we + 1] = rng.normal(30, 2, (we - ws + 1, n_kern, 2))
        ncc[ws : we + 1] = 0.9
        result = StrainResult(
            longitudinal=np.zeros(n_frames),
            radial=np.zeros(n_frames),
            gls=-15.0,
            ed_index=4,
            es_index=14,
            kernels=kernels,
            tracked_positions_all=raw.copy(),
            raw_tracked_positions=raw,
            ncc_all_frames=ncc,
            tracking_window_start=ws,
            tracking_window_end=we,
            tracked_ed_positions=raw[ws].copy(),
            tracked_es_positions=raw[we].copy(),
        )
        w.contract.speckle_result = result

        w.contract.on_ste_smoothness_changed(1.0)  # previously raised FrozenInstanceError

        new_result = w.speckle_result()
        assert new_result is not result  # immutable: replaced, not mutated
        assert new_result.tracked_positions_all.shape == raw.shape
        assert np.all(np.isfinite(new_result.tracked_positions_all[ws : we + 1]))
        assert np.all(np.isnan(new_result.tracked_positions_all[:ws]))
        assert np.all(np.isnan(new_result.tracked_positions_all[we + 1 :]))

    def test_ste_smoothness_guards_missing_window(self, qtbot) -> None:
        """A result without raw positions must be ignored, not crash."""
        import numpy as np

        from echo_personal_tool.domain.models.speckle import StrainResult

        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        result = StrainResult(
            longitudinal=np.zeros(5),
            radial=np.zeros(5),
            gls=0.0,
            kernels=[],
            raw_tracked_positions=None,
        )
        w.show_speckle_result(result)
        w.contract.on_ste_smoothness_changed(1.0)  # must not raise

        assert w.speckle_result() is result, "a result without raw positions is left as it was"

    def test_segment_labels_follow_the_displayed_frame(self, qtbot) -> None:
        """§5.3 п.4: the cine names the walls it measures, and un-names them
        when the frame leaves the tracked window (labels belong to the overlay)."""
        import numpy as np

        from echo_personal_tool.domain.models.speckle import StrainResult, TrackingKernel

        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        n_frames, n_kern = 6, 4
        kernels = [
            TrackingKernel(
                center=(10.0 + 10 * i, 50.0),
                node_index=i,
                layer="endo",
                radius=4,
                aha_segment=(3, 9, 6, 18)[i],
            )
            for i in range(n_kern)
        ]
        positions = np.tile(np.array([[20.0, 50.0], [30.0, 50.0], [40.0, 50.0], [50.0, 50.0]]), (n_frames, 1, 1))
        result = StrainResult(
            longitudinal=np.zeros(n_frames),
            radial=np.zeros(n_frames),
            gls=-18.0,
            ed_index=0,
            es_index=3,
            kernels=kernels,
            tracked_positions_all=positions.copy(),
            ncc_all_frames=np.full((n_frames, n_kern), 0.9),
            tracking_window_start=0,
            tracking_window_end=3,
        )
        from echo_personal_tool.infrastructure.i18n import set_language

        w.contract.speckle_result = result
        w.contract.speckle_overlay.show()

        set_language("ru")
        try:
            # Frame 0 is inside [tracking_window_start, tracking_window_end].
            w.contract.current_state = _make_state(frame=0, total=n_frames)
            w.contract.refresh_speckle_overlay_for_current_frame()
            labels = [item.toPlainText() for item in w.contract.speckle_overlay.segment_labels]
            assert sorted(labels) == ["АпБок", "БазБок", "БазПерг", "СрПерг"]

            # Past the tracked window the names are dropped together with the kernels.
            w.contract.current_state = _make_state(frame=n_frames - 1, total=n_frames)
            w.contract.refresh_speckle_overlay_for_current_frame()
            assert w.contract.speckle_overlay.segment_labels == []
        finally:
            set_language("en")

        w.clear_speckle_overlay()
        assert w.contract.speckle_overlay.segment_labels == []


# ═══════════════════════════════════════════════════════════════════
#  Scroll debounce
# ═══════════════════════════════════════════════════════════════════


class TestScrollDebounce:
    def test_set_scroll_debounce_ms(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.set_scroll_debounce_ms(100)
        assert w.contract.scroll_debounce_ms == 100

    def test_emit_pending_scroll(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state(total=10)
        w.set_state(state)
        received = []
        w.scroll_frame_selected.connect(lambda v: received.append(v))
        w.contract.pending_scroll_index = 5
        w.contract.syncing_state = False
        w.contract.emit_pending_scroll()
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
        before = guard_snapshot(w)
        w.contract.update_timeline_indicator(state)
        assert guard_snapshot(w) == before, "test_update_timeline_indicator: guard handler changed viewer state"
        assert w.contract.timeline_slider.toolTip() == ""
        assert w.contract.timeline_slider.styleSheet() == ""

    def test_on_timeline_changed(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state(total=10)
        w.set_state(state)
        received = []
        w.frame_selected.connect(lambda v: received.append(v))
        w.contract.on_timeline_changed(5)
        assert len(received) == 1
        assert received[0] == 5

    def test_on_timeline_changed_syncing(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state(total=10)
        w.set_state(state)
        received = []
        w.frame_selected.connect(lambda v: received.append(v))
        w.contract.syncing_state = True
        w.contract.on_timeline_changed(5)
        assert len(received) == 0
        w.contract.syncing_state = False


# ═══════════════════════════════════════════════════════════════════
#  Debug overlay deep
# ═══════════════════════════════════════════════════════════════════


class TestDebugOverlayDeep:
    def test_toggle_debug_overlay_on(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.contract.debug_overlay_visible = False
        w.toggle_debug_overlay()
        assert w.is_debug_overlay_visible is True

    def test_toggle_debug_overlay_off(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.contract.debug_overlay_visible = True
        w.toggle_debug_overlay()
        assert w.is_debug_overlay_visible is False

    def test_update_debug_overlay_visible(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.toggle_debug_overlay()
        w.contract.update_debug_overlay()

        text = w.debug_overlay_text()
        assert "Native: 64x64" in text
        assert "Viewport:" in text
        assert "Scale:" in text
        # Should not raise

    def test_update_debug_overlay_hidden(self, qtbot) -> None:
        from unittest.mock import patch

        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        assert not w.is_debug_overlay_visible

        with patch.object(w.contract.debug_overlay_label, "setText") as set_text:
            w.contract.update_debug_overlay()

        set_text.assert_not_called()  # a switched-off overlay is not rebuilt
        # Should not raise


# ═══════════════════════════════════════════════════════════════════
#  Contour pen
# ═══════════════════════════════════════════════════════════════════


class TestContourPen:
    def test_contour_pen_for_manual(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from echo_personal_tool.domain.models import Contour

        c = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10)], source="manual")
        pen = w.contract.contour_pen_for(c)
        assert pen is not None

    def test_contour_pen_for_ai(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from echo_personal_tool.domain.models import Contour

        c = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10)], source="ai")
        pen = w.contract.contour_pen_for(c)
        assert pen is not None

    def test_contour_pen_for_model(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from echo_personal_tool.domain.models import Contour

        c = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10)], source="model")
        pen = w.contract.contour_pen_for(c)
        assert pen is not None


# ═══════════════════════════════════════════════════════════════════
#  Contour xy
# ═══════════════════════════════════════════════════════════════════


class TestContourXY:
    def test_contour_xy_closed(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from echo_personal_tool.domain.models import Contour

        c = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10), (20, 10), (20, 20)])
        x, y = w.contract.contour_xy(c, closed=True)
        # Returns resampled points (DEFAULT_NODE_COUNT=128)
        assert len(x) > 0
        assert len(y) > 0
        assert len(x) == len(y)

    def test_contour_xy_open(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from echo_personal_tool.domain.models import Contour

        c = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10), (20, 10), (20, 20)])
        x, y = w.contract.contour_xy(c, closed=False)
        assert len(x) > 0
        assert len(y) > 0

    def test_contour_xy_open_arc(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from echo_personal_tool.domain.models import Contour

        c = Contour(
            phase="ED",
            view="A4C",
            chamber="LV",
            points=[(10, 10), (20, 10), (20, 20)],
            mitral_annulus=((5, 5), (25, 5)),
        )
        x, y = w.contract.contour_xy(c, closed=False)
        assert len(x) > 0


# ═══════════════════════════════════════════════════════════════════
#  Resize event
# ═══════════════════════════════════════════════════════════════════


class TestResizeEvent:
    def test_resize_event(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        from PySide6.QtCore import QSize
        from PySide6.QtGui import QResizeEvent

        event = QResizeEvent(QSize(640, 480), QSize(320, 240))
        before = guard_snapshot(w)
        w.resizeEvent(event)
        assert guard_snapshot(w) == before, "test_resize_event: guard handler changed viewer state"
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
        w.contract.update_measurement_crosshair(32.0, 32.0)
        # The cursor is remembered even though nothing is drawn: a plain 2D frame has no Doppler panel.
        assert w.contract.last_view_cursor_xy == (32.0, 32.0)
        assert w.contract.crosshair_h_item is None
        assert w.contract.crosshair_v_item is None

    def test_clear_crosshair(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        state = _make_state()
        w.set_state(state)
        w.contract.update_measurement_crosshair(32.0, 32.0)
        w.contract.clear_crosshair()
        assert w.contract.crosshair_h_item is None
        assert w.contract.crosshair_v_item is None


# ═══════════════════════════════════════════════════════════════════
#  Measurement label
# ═══════════════════════════════════════════════════════════════════


class TestMeasurementLabel:
    def test_current_caliper_label(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        label = w.contract.current_caliper_label()
        assert isinstance(label, str)
        assert len(label) > 0

    def test_set_caliper_label(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.contract.set_caliper_label("CustomLabel")
        assert w.contract.current_caliper_label() == "CustomLabel"

    def test_set_caliper_label_new(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.contract.set_caliper_label("NewLabel")
        assert "NewLabel" in w.contract.caliper_labels


# ═══════════════════════════════════════════════════════════════════
#  Frame panel layout
# ═══════════════════════════════════════════════════════════════════


class TestFramePanelLayout:
    def test_refresh_frame_panel_layout(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.contract.frame_panels_from_dicom = True
        w.contract.frame_panel_layout = object()
        # Should not raise
        w.contract.refresh_frame_panel_layout()
        assert w.contract.frame_panels_from_dicom is False
        assert w.contract.frame_panel_layout is None, "the layout must be recomputed, not inherited"

    def test_resolve_frame_panels(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        result = w.contract.resolve_frame_panels()
        # May return None or a layout
        assert result is None or hasattr(result, "panels")


# ═══════════════════════════════════════════════════════════════════
#  Reload text
# ═══════════════════════════════════════════════════════════════════


class TestReloadText:
    def test_reload_text_no_state(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Should not raise
        before = guard_snapshot(w)
        w.reload_text()
        assert guard_snapshot(w) == before, "test_reload_text_no_state: guard handler changed viewer state"
        assert w.contract.timeline_slider.toolTip(), "reload_text must localize the timeline tooltip"

    def test_reload_text_with_state(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state(total=5)
        w.set_state(state)
        # Should not raise
        before = guard_snapshot(w)
        w.reload_text()
        assert guard_snapshot(w) == before, "test_reload_text_with_state: guard handler changed viewer state"
        assert w.contract.timeline_slider.toolTip(), "reload_text must localize the timeline tooltip"
        assert w.contract.source_label.text(), "a loaded state must produce a frame counter"


# ═══════════════════════════════════════════════════════════════════
#  Contour pen rebuild
# ═══════════════════════════════════════════════════════════════════


class TestContourPenRebuild:
    def test_rebuild_contour_pens(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from echo_personal_tool.infrastructure.user_preferences import UserPreferences

        prefs = UserPreferences()
        w.contract.rebuild_contour_pens(prefs)
        # Pens should be recreated
        assert w.contract.contour_pen_manual is not None
        assert w.contract.contour_pen_ai is not None
        assert w.contract.contour_pen_model is not None
        assert w.contract.contour_pen_ma is not None

    def test_refresh_rendered_contour_pens(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        # Should not raise even with no contours
        before = guard_snapshot(w)
        w.contract.refresh_rendered_contour_pens()
        assert guard_snapshot(w) == before, "test_refresh_rendered_contour_pens: guard handler changed viewer state"

    def test_caliper_pen(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        pen = w.contract.caliper_pen("#ffb300")
        assert pen is not None

    def test_caliper_pen_dashed(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        pen = w.contract.caliper_pen("#ffb300", style=Qt.PenStyle.DashLine)
        assert pen is not None

    def test_refresh_caliper_line_pens(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Should not raise even with no items
        before = guard_snapshot(w)
        w.contract.refresh_caliper_line_pens()
        assert guard_snapshot(w) == before, "test_refresh_caliper_line_pens: guard handler changed viewer state"


# ═══════════════════════════════════════════════════════════════════
#  Display mode resolution
# ═══════════════════════════════════════════════════════════════════


class TestDisplayMode:
    def test_resolve_display_mode_grayscale(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        frame = np.zeros((64, 64), dtype=np.uint8)
        color, wl = w.contract.resolve_display_mode(frame, None)
        assert color is False
        assert wl is True

    def test_resolve_display_mode_color_dicom(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        frame = np.random.randint(0, 255, (64, 64, 3), dtype=np.uint8)
        frame[:, :, 0] = 200  # Make it clearly color
        color, wl = w.contract.resolve_display_mode(frame, "dicom")
        # Result depends on is_color_frame
        assert isinstance(color, bool)
        assert isinstance(wl, bool)

    def test_resolve_display_mode_rgb_non_dicom(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        frame = np.random.randint(0, 255, (64, 64, 3), dtype=np.uint8)
        color, wl = w.contract.resolve_display_mode(frame, "mp4")
        assert isinstance(color, bool)
        assert isinstance(wl, bool)


# ═══════════════════════════════════════════════════════════════════
#  MMode operations deep
# ═══════════════════════════════════════════════════════════════════


class TestMModeDeepExtended:
    def test_cancel_mmode_line(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.mmode.start_line()
        assert w.mmode.line_active is True
        w.mmode.cancel_line()
        assert w.mmode.line_active is False
        assert w.mmode.line_item is None

    def test_handle_mmode_line_hover_not_active(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        result = w.mmode.handle_line_hover(10.0, 10.0)
        assert result is False

    def test_handle_mmode_line_hover_active(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.mmode.start_line()
        w.mmode.handle_line_click(10.0, 10.0)
        result = w.mmode.handle_line_hover(20.0, 20.0)
        assert result is True

    def test_begin_mmode_node_drag(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Should not raise
        before = guard_snapshot(w)
        w.mmode.begin_node_drag(0)
        assert guard_snapshot(w) == before, "test_begin_mmode_node_drag: guard handler changed viewer state"

    def test_mmode_node_dragging_no_item(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Should not raise
        before = guard_snapshot(w)
        w.mmode.node_dragging(0, (10.0, 10.0))
        assert guard_snapshot(w) == before, "test_mmode_node_dragging_no_item: guard handler changed viewer state"


# ═══════════════════════════════════════════════════════════════════
#  Linear measurement emission
# ═══════════════════════════════════════════════════════════════════


class TestLinearMeasurementEmission:
    def test_emit_stored_linear_measurements(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        received = []
        w.linear_measurements_changed.connect(lambda m: received.append(m))
        w.contract.emit_stored_linear_measurements()
        assert len(received) == 1
        assert isinstance(received[0], list)


# ═══════════════════════════════════════════════════════════════════
#  Display controls
# ═══════════════════════════════════════════════════════════════════


class TestDisplayControls:
    def test_disconnect_display_controls(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Should not raise even without external sliders
        before = guard_snapshot(w)
        w.disconnect_display_controls()
        assert guard_snapshot(w) == before, "test_disconnect_display_controls: guard handler changed viewer state"

    def test_set_wl_dr_sliders(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.contract.set_wl_dr_sliders(150, 60, 40)
        assert w.contract.window_slider.value() == 150
        assert w.contract.level_slider.value() == 60
        assert w.contract.dr_slider.value() == 40

    def test_set_wl_dr_sliders_no_update(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.contract.set_wl_dr_sliders(150, 60, 40, update_display=False)
        assert w.contract.window_slider.value() == 150

    def test_save_current_wl_dr(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        state = _make_state()
        w.set_state(state)
        before = guard_snapshot(w)
        w.contract.save_current_wl_dr()
        assert guard_snapshot(w) == before, "test_save_current_wl_dr: guard handler changed viewer state"
        # Should not raise

        # Should not raise

    def test_update_levels_no_frame(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Should not raise even without frame
        before = guard_snapshot(w)
        w.contract.update_levels()
        assert guard_snapshot(w) == before, "test_update_levels_no_frame: guard handler changed viewer state"

    def test_update_levels_empty_frame(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.contract.current_frame = np.array([], dtype=np.uint8)
        # Should not raise
        before = guard_snapshot(w)
        w.contract.update_levels()
        assert guard_snapshot(w) == before, "test_update_levels_empty_frame: guard handler changed viewer state"


# ═══════════════════════════════════════════════════════════════════
#  Contour node operations
# ═══════════════════════════════════════════════════════════════════


class TestContourNodeOps:
    def test_set_contour_nodes_pickable_true(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        before = guard_snapshot(w)
        w.contract.set_contour_nodes_pickable(True)
        assert guard_snapshot(w) == before, "test_set_contour_nodes_pickable_true: guard handler changed viewer state"
        # Should not raise

    def test_set_contour_nodes_pickable_false(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        before = guard_snapshot(w)
        w.contract.set_contour_nodes_pickable(False)
        assert guard_snapshot(w) == before, "test_set_contour_nodes_pickable_false: guard handler changed viewer state"
        # Should not raise

    def test_reindex_contour_nodes(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Should not raise
        before = guard_snapshot(w)
        w.contract.reindex_contour_nodes()
        assert guard_snapshot(w) == before, "test_reindex_contour_nodes: guard handler changed viewer state"


# ═══════════════════════════════════════════════════════════════════
#  Effective display levels
# ═══════════════════════════════════════════════════════════════════


class TestEffectiveDisplayLevels:
    def test_effective_display_levels(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        result = w.contract.effective_display_levels()
        assert isinstance(result, tuple)
        assert len(result) == 2


# ═══════════════════════════════════════════════════════════════════
#  Contour drag session
# ═══════════════════════════════════════════════════════════════════


class TestContourDragSession:
    def test_clear_drag_session(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.contract.drag_session = (0, 10.0, 10.0, 0, 1)
        w.contract.zone_drag_active = True
        w.contract.last_drag_apply_pos = (5.0, 5.0)
        w.contract.clear_drag_session()
        assert w.contract.drag_session is None

        assert w.contract.zone_drag_active is False
        assert w.contract.last_drag_apply_pos is None


# ═══════════════════════════════════════════════════════════════════
#  Contour zone press/drag/release
# ═══════════════════════════════════════════════════════════════════


class TestContourZoneOps:
    def test_handle_contour_zone_press_no_contours(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QMouseEvent

        event = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(10, 10),
            QPointF(10, 10),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        result = w.contract.handle_contour_zone_press(event)
        assert result is False

    def test_handle_contour_zone_release(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QMouseEvent

        event = QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            QPointF(10, 10),
            QPointF(10, 10),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        result = w.contract.handle_contour_zone_release(event)
        assert result is False


# ═══════════════════════════════════════════════════════════════════
#  Doppler trace press/drag/release
# ═══════════════════════════════════════════════════════════════════


class TestDopplerTraceOps:
    def test_handle_doppler_trace_press_no_mode(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QMouseEvent

        event = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(10, 10),
            QPointF(10, 10),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        result = w.doppler.handle_trace_press(event)
        assert result is False

    def test_handle_doppler_trace_release(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QMouseEvent

        event = QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            QPointF(10, 10),
            QPointF(10, 10),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        result = w.doppler.handle_trace_release(event)
        assert result is False


# ═══════════════════════════════════════════════════════════════════
#  Caliper drag release
# ═══════════════════════════════════════════════════════════════════


class TestCaliperDragRelease:
    def test_handle_caliper_drag_release_no_drag(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QMouseEvent

        event = QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            QPointF(10, 10),
            QPointF(10, 10),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        result = w.contract.handle_caliper_drag_release(event)
        assert result is False


# ═══════════════════════════════════════════════════════════════════
#  Contour drag release
# ═══════════════════════════════════════════════════════════════════


class TestContourDragRelease:
    def test_handle_contour_drag_release_no_session(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QMouseEvent

        event = QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            QPointF(10, 10),
            QPointF(10, 10),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        result = w.contract.handle_contour_drag_release(event)
        assert result is False

    def test_handle_contour_drag_release_from_global(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Should not raise even without session
        from PySide6.QtCore import QPointF

        before = guard_snapshot(w)
        w.contract.handle_contour_drag_release_from_global(QPointF(10, 10))
        assert guard_snapshot(w) == before, (
            "test_handle_contour_drag_release_from_global: guard handler changed viewer state"
        )


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
        before = guard_snapshot(w)
        w.contract.auto_snap_new_contour(contour)
        assert guard_snapshot(w) == before, "test_auto_snap_new_contour: guard handler changed viewer state"


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
        before = guard_snapshot(w)
        w.contract.apply_magnetic_snap_to_contour(0, weights, grab_index=None)
        assert guard_snapshot(w) == before, "test_apply_magnetic_snap_to_contour: guard handler changed viewer state"

    def test_apply_magnetic_snap_to_contour_closed_polygon(self, qtbot) -> None:
        """Test that closed polygons also get magnetic snap."""
        from unittest.mock import MagicMock, patch

        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        from echo_personal_tool.domain.models import Contour

        # Create a closed polygon contour (mitral_annulus=None)
        contour = Contour(phase="GEN", view="A4C", chamber="AREA", points=[(10, 10), (30, 10), (30, 30), (10, 30)])
        w.set_contour_from_domain(contour)
        weights = np.ones(len(contour.points))

        # Mock dependencies
        with (
            patch.object(w, "get_edge_map", return_value=MagicMock()),
            patch("echo_personal_tool.domain.services.contour_edge_snap.snap_closed_polygon") as mock_snap,
        ):
            w.contract.apply_magnetic_snap_to_contour(0, weights, grab_index=None)
            # snap_closed_polygon should be called for closed polygons
            mock_snap.assert_called_once()


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
        before = guard_snapshot(w)
        w.reposition_overlays()
        assert guard_snapshot(w) == before, "test_reposition_overlays: guard handler changed viewer state"

    def test_mark_results_overlay_custom_position(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.contract.mark_results_overlay_custom_position()
        assert w.results_overlay_custom_position() is True

    def test_reset_results_overlay_to_default(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.results_overlay_controller.mark_custom_position()
        w.reset_results_overlay_to_default()
        assert w.results_overlay_custom_position() is False

    def test_on_results_overlay_clear(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.set_results_overlay("Test")
        w.contract.on_results_overlay_clear()
        # After clear, set_results_overlay("") resets the flag
        assert w.results_overlay_controller.is_cleared() is False

    def test_on_results_overlay_reset_position(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.results_overlay_controller.mark_custom_position()
        w.contract.on_results_overlay_reset_position()
        assert w.results_overlay_custom_position() is False

    def test_on_results_overlay_pin_toggled(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.contract.on_results_overlay_pin_toggled(True)
        # Should not raise
        before = guard_snapshot(w)
        w.contract.on_results_overlay_pin_toggled(False)
        assert guard_snapshot(w) == before, "test_on_results_overlay_pin_toggled: guard handler changed viewer state"
        from PySide6.QtCore import Qt

        assert w.contract.results_overlay_label.cursor().shape() == Qt.CursorShape.OpenHandCursor
        # Should not raise


# ═══════════════════════════════════════════════════════════════════
#  Debug overlay deep
# ═══════════════════════════════════════════════════════════════════


class TestDebugOverlayDeepExtended:
    def test_get_last_segment_roi(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        result = w.contract.get_last_segment_roi()
        assert result is None

    def test_draw_debug_roi_rect_none(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.contract.debug_overlay_visible = True
        before = guard_snapshot(w)
        w.contract.draw_debug_roi_rect(None)
        assert guard_snapshot(w) == before, "test_draw_debug_roi_rect_none: guard handler changed viewer state"
        assert getattr(w.contract, "debug_roi_item", None) is None

        # Should not raise

    def test_draw_debug_roi_rect_with_roi(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.contract.debug_overlay_visible = True
        w.contract.draw_debug_roi_rect((10, 10, 50, 50))
        assert w.contract.debug_roi_item is not None

    def test_draw_debug_roi_rect_not_visible(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.contract.debug_overlay_visible = False
        before = guard_snapshot(w)
        w.contract.draw_debug_roi_rect((10, 10, 50, 50))
        assert guard_snapshot(w) == before, "test_draw_debug_roi_rect_not_visible: guard handler changed viewer state"
        assert getattr(w.contract, "debug_roi_item", None) is None  # Should not create item when not visible


# ═══════════════════════════════════════════════════════════════════
#  DICOM tags overlay
# ═══════════════════════════════════════════════════════════════════


class TestDicomTagsOverlay:
    def test_refresh_dicom_tags_overlay_no_instance(self, qtbot) -> None:
        from echo_personal_tool.infrastructure.user_preferences import UserPreferences

        w = _make_viewer(qtbot)
        w.apply_user_preferences(UserPreferences(interesting_dicom_tags="Modality"))
        # Should not raise
        w.tags_overlay.refresh()

        assert w.tags_overlay.text() == "", "no instance, nothing to read the tags from"

    def test_refresh_dicom_tags_overlay_with_state(self, qtbot) -> None:
        from echo_personal_tool.infrastructure.user_preferences import UserPreferences

        w = _make_viewer(qtbot)
        w.apply_user_preferences(UserPreferences(interesting_dicom_tags="Modality"))
        state = _make_state()
        w.set_state(state)
        # Should not raise
        w.tags_overlay.refresh()

        assert w.tags_overlay.text() == "", "an instance without a file has no tags to show"

    def test_current_instance_metadata(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w.contract.current_instance_metadata() is None

    def test_current_instance_metadata_with_state(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        state = _make_state()
        w.set_state(state)
        assert w.contract.current_instance_metadata() is not None


# ═══════════════════════════════════════════════════════════════════
#  Position overlay labels
# ═══════════════════════════════════════════════════════════════════


class TestPositionOverlayLabels:
    def test_position_overlay_labels(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        # Should not raise
        before = guard_snapshot(w)
        w.contract.position_overlay_labels()
        assert guard_snapshot(w) == before, "test_position_overlay_labels: guard handler changed viewer state"

    def test_position_overlay_labels_with_results(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.set_results_overlay("Test overlay")
        # Should not raise
        before = guard_snapshot(w)
        w.contract.position_overlay_labels(reposition_results=True)
        assert guard_snapshot(w) == before, (
            "test_position_overlay_labels_with_results: guard handler changed viewer state"
        )

    def test_position_overlay_labels_no_reposition(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.set_results_overlay("Test overlay")
        # Should not raise
        before = guard_snapshot(w)
        w.contract.position_overlay_labels(reposition_results=False)
        assert guard_snapshot(w) == before, (
            "test_position_overlay_labels_no_reposition: guard handler changed viewer state"
        )


# ═══════════════════════════════════════════════════════════════════
#  Panel frame graphics
# ═══════════════════════════════════════════════════════════════════


class TestPanelFrameGraphics:
    def test_refresh_panel_frame_graphics(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        # Should not raise
        before = guard_snapshot(w)
        w.contract.refresh_panel_frame_graphics()
        assert guard_snapshot(w) == before, "test_refresh_panel_frame_graphics: guard handler changed viewer state"

    def test_clear_panel_frame_graphics(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Items are empty by default, just verify clearing works
        w.contract.clear_panel_frame_graphics()
        assert len(w.contract.panel_frame_items) == 0


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
        before = guard_snapshot(w)
        w.contract.render_contours_for_current_frame()
        assert guard_snapshot(w) == before, "test_render_contours_for_current_frame: guard handler changed viewer state"
        assert len(w.contract.contour_items) == 1, "the current frame contour must be rendered"

    def test_clear_rendered_contours(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        from echo_personal_tool.domain.models import Contour

        c = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10), (20, 20)])
        w.set_contour_from_domain(c)
        assert len(w.contract.contour_items) > 0
        w.contract.clear_rendered_contours()
        assert len(w.contract.contour_items) == 0

    def test_append_rendered_contour(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        from echo_personal_tool.domain.models import Contour

        c = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10), (20, 20)])
        initial_count = len(w.contract.contour_items)
        w.contract.append_rendered_contour(c)
        assert len(w.contract.contour_items) == initial_count + 1

    def test_create_contour_render(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        from echo_personal_tool.domain.models import Contour

        c = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10), (20, 20)])
        line_item, ma_item, node_items = w.contract.create_contour_render(c, 0)
        assert line_item is not None
        assert ma_item is None  # No mitral annulus
        assert isinstance(node_items, list)

    def test_create_contour_render_open_arc(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        from echo_personal_tool.domain.models import Contour

        c = Contour(
            phase="ED",
            view="A4C",
            chamber="LV",
            points=[(10, 10), (20, 20), (30, 30)],
            mitral_annulus=((5, 5), (35, 5)),
        )
        line_item, ma_item, node_items = w.contract.create_contour_render(c, 0)
        assert line_item is not None
        assert ma_item is not None  # Has mitral annulus


# ═══════════════════════════════════════════════════════════════════
#  Crosshair panel bounds
# ═══════════════════════════════════════════════════════════════════


class TestCrosshairPanelBounds:
    def test_crosshair_panel_bounds_no_state(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        result = w.contract.crosshair_panel_bounds()
        assert result is None

    def test_crosshair_panel_bounds_with_doppler(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        state = _make_state()
        w.set_state(state)
        result = w.contract.crosshair_panel_bounds()
        # May return None or a bounds object
        assert result is None or hasattr(result, "x0")

    def test_measurement_crosshair_active(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        result = w.contract.measurement_crosshair_active()
        assert isinstance(result, bool)

    def test_ensure_crosshair_graphics(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.contract.ensure_crosshair_graphics()
        assert w.contract.crosshair_h_item is not None
        assert w.contract.crosshair_v_item is not None

    def test_ensure_crosshair_graphics_idempotent(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.contract.ensure_crosshair_graphics()
        first_h = w.contract.crosshair_h_item
        first_v = w.contract.crosshair_v_item
        w.contract.ensure_crosshair_graphics()
        assert w.contract.crosshair_h_item is first_h
        assert w.contract.crosshair_v_item is first_v


# ═══════════════════════════════════════════════════════════════════
#  Doppler calibration state
# ═══════════════════════════════════════════════════════════════════


class TestDopplerCalibrationState:
    def test_apply_doppler_calibration_state(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        from echo_personal_tool.domain.models.doppler_roi import (
            DopplerCalibrationState,
            DopplerSpectrogramRoi,
        )

        roi = DopplerSpectrogramRoi(x0=10, y0=10, width=50, height=30)
        state = DopplerCalibrationState(
            roi=roi,
            baseline_y_px=25.0,
            velocity_span_cm_s=200.0,
        )
        w.doppler.apply_calibration_state(state, persist=False)
        assert w.doppler.get_calibration_state() is not None
        assert w.doppler.get_calibration_state().roi == roi

    def test_apply_doppler_calibration_keeps_baseline_above_roi(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((200, 200), dtype=np.uint8))
        from echo_personal_tool.domain.models.doppler_roi import (
            DopplerCalibrationState,
            DopplerSpectrogramRoi,
        )

        state = DopplerCalibrationState(
            roi=DopplerSpectrogramRoi(x0=10.0, y0=80.0, width=180.0, height=100.0),
            baseline_y_px=20.0,
            velocity_span_cm_s=400.0,
        )

        w.doppler.apply_calibration_state(state, persist=False)

        result = w.doppler.get_calibration_state()
        assert result is not None
        assert result.baseline_y_px == 20.0
        assert w.doppler.overlay.axis_mapping().baseline_plot_y() == 20.0

    def test_apply_doppler_calibration_state_persist(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        from echo_personal_tool.domain.models.doppler_roi import (
            DopplerCalibrationState,
            DopplerSpectrogramRoi,
        )

        roi = DopplerSpectrogramRoi(x0=10, y0=10, width=50, height=30)
        state = DopplerCalibrationState(
            roi=roi,
            baseline_y_px=25.0,
            velocity_span_cm_s=200.0,
        )
        w.doppler.apply_calibration_state(state, persist=True)
        assert w.doppler.get_calibration_state() is not None
        assert w.doppler.axis_calibrated is True

    def test_doppler_calibration_matches_instance(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        state = _make_state()
        w.set_state(state)
        result = w.doppler.calibration_matches_instance()
        assert isinstance(result, bool)


# ═══════════════════════════════════════════════════════════════════
#  MMode calibration state
# ═══════════════════════════════════════════════════════════════════


class TestMModeCalibrationState:
    def test_apply_mmode_calibration_state(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi
        from echo_personal_tool.domain.models.frame_panels import MmodeCalibrationState

        roi = DopplerSpectrogramRoi(x0=10, y0=10, width=50, height=30)
        state = MmodeCalibrationState(
            roi=roi,
            vertical_mm_per_pixel=0.5,
        )
        w.mmode.apply_calibration_state(state)
        assert w.mmode.calibration_state is not None
        assert w.mmode.calibration_state.vertical_mm_per_pixel == 0.5


# ═══════════════════════════════════════════════════════════════════
#  Linear measurement creation
# ═══════════════════════════════════════════════════════════════════


class TestLinearMeasurementCreation:
    def test_linear_measurement_from_endpoints(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        state = _make_state()
        w.set_state(state)
        m = w.contract.linear_measurement_from_endpoints((10.0, 10.0), (50.0, 10.0), "IVSd")
        assert m is not None
        assert m.label == "IVSd"

    def test_linear_measurement_key(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement

        m = LinearMeasurement(
            label="IVSd",
            pixel_length=10.0,
            millimeter_length=5.0,
            frame_index=0,
        )
        key = w.contract.linear_measurement_key(m)
        assert isinstance(key, tuple)
        assert len(key) >= 2

    def test_constrain_linear_endpoint(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        result = w.contract.constrain_linear_endpoint((10.0, 10.0), (50.0, 10.0), label="IVSd")
        assert isinstance(result, tuple)
        assert len(result) == 2


# ═══════════════════════════════════════════════════════════════════
#  User preferences
# ═══════════════════════════════════════════════════════════════════


class TestUserPreferences:
    def test_apply_user_preferences(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        from echo_personal_tool.infrastructure.user_preferences import UserPreferences

        prefs = UserPreferences()
        w.set_despeckle_enabled(True)
        w.set_results_overlay_position(0.2, 0.4)  # a custom place the preferences do not keep
        w.apply_user_preferences(prefs)
        # Should not raise

        assert w.despeckle_enabled() is prefs.despeckle_enabled
        assert w.results_overlay_custom_position() is prefs.results_overlay_custom_position

    def test_apply_user_preferences_doppler_cal_roi(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        from echo_personal_tool.infrastructure.user_preferences import UserPreferences

        prefs = UserPreferences(show_doppler_calibration_roi=True)
        w.apply_user_preferences(prefs)
        assert w.doppler.overlay.show_calibration_roi is True

        prefs = UserPreferences(show_doppler_calibration_roi=False)
        w.apply_user_preferences(prefs)
        assert w.doppler.overlay.show_calibration_roi is False

    def test_apply_user_preferences_with_contours(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        from echo_personal_tool.domain.models import Contour

        c = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10), (20, 20)])
        w.set_contour_from_domain(c)
        from echo_personal_tool.infrastructure.user_preferences import UserPreferences

        prefs = UserPreferences()
        w.apply_user_preferences(prefs)
        # Should not raise

        assert w.contours() == [c], "restyling the pens keeps the contours as they were"


# ═══════════════════════════════════════════════════════════════════
#  Auto detect doppler calibration
# ═══════════════════════════════════════════════════════════════════


class TestAutoDetectDoppler:
    def test_try_auto_detect_no_frame(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        result = w.doppler.try_auto_detect_calibration()
        assert result is False

    def test_try_auto_detect_disabled(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.doppler.auto_calibration_enabled = False
        result = w.doppler.try_auto_detect_calibration()
        assert result is False

    def test_try_auto_detect_no_dicom(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        state = _make_state()
        w.set_state(state)
        result = w.doppler.try_auto_detect_calibration()
        # May return True or False depending on DICOM tags
        assert isinstance(result, bool)


# ═══════════════════════════════════════════════════════════════════
#  Configure doppler axis
# ═══════════════════════════════════════════════════════════════════


class TestConfigureDopplerAxis:
    def test_configure_doppler_axis_no_frame(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Should not raise
        before = guard_snapshot(w)
        w.doppler.configure_axis_for_frame()
        assert guard_snapshot(w) == before, "test_configure_doppler_axis_no_frame: guard handler changed viewer state"
        assert bool(getattr(w.doppler, "axis_calibrated", False)) is False

    def test_configure_doppler_axis_with_frame(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        state = _make_state()
        w.set_state(state)
        # Should not raise
        before = guard_snapshot(w)
        w.doppler.configure_axis_for_frame()
        assert guard_snapshot(w) == before, "test_configure_doppler_axis_with_frame: guard handler changed viewer state"

    def test_configure_doppler_axis_with_calibration(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        from echo_personal_tool.domain.models.doppler_roi import (
            DopplerCalibrationState,
            DopplerSpectrogramRoi,
        )

        roi = DopplerSpectrogramRoi(x0=10, y0=10, width=50, height=30)
        state = DopplerCalibrationState(
            roi=roi,
            baseline_y_px=25.0,
            velocity_span_cm_s=200.0,
        )
        w.doppler.apply_calibration_state(state, persist=False)
        # Should not raise
        w.doppler.configure_axis_for_frame()
        assert w.doppler.calibration_state is None, (
            "a calibration tied to another clip must not survive the heuristic pass"
        )


# ═══════════════════════════════════════════════════════════════════
#  Begin doppler velocity calibration
# ═══════════════════════════════════════════════════════════════════


class TestBeginDopplerVelocityCalibration:
    def test_begin_velocity_calibration_no_frame(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Should not raise
        before = guard_snapshot(w)
        w.doppler.begin_velocity_calibration()
        assert guard_snapshot(w) == before, (
            "test_begin_velocity_calibration_no_frame: guard handler changed viewer state"
        )
        assert w.contract.calibration_active is False

    def test_begin_velocity_calibration_with_frame(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.doppler.begin_velocity_calibration()
        assert w.contract.calibration_kind == "doppler_velocity"
        assert w.is_calibration_active is True

    def test_begin_velocity_calibration_with_roi(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi

        w.doppler.pending_roi = DopplerSpectrogramRoi(x0=10, y0=10, width=50, height=30)
        w.doppler.begin_velocity_calibration()
        assert w.contract.calibration_kind == "doppler_velocity"
        assert w.is_calibration_active is True

    def test_velocity_span_preserves_prior_time_scale(self, qtbot) -> None:
        """Manual velocity calibration keeps an auto-detected time span."""
        from unittest.mock import patch

        from echo_personal_tool.domain.models.doppler_roi import (
            DopplerCalibrationState,
            DopplerSpectrogramRoi,
        )

        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))

        roi = DopplerSpectrogramRoi(x0=0, y0=0, width=64, height=64)
        prior = DopplerCalibrationState(
            roi=roi,
            baseline_y_px=32.0,
            time_span_ms=5600.0,
            time_from_dicom_tags=True,
            from_dicom_tags=True,
        )
        w.doppler.apply_calibration_state(prior, persist=False)

        with patch(
            "echo_personal_tool.presentation.viewer_widget.QInputDialog.getDouble",
            return_value=(200.0, True),
        ):
            w.doppler.prompt_spectral_velocity_span(64.0)

        result = w.doppler.get_calibration_state()
        assert result is not None
        assert result.time_span_ms == 5600.0
        assert result.has_time_scale()

    def test_velocity_span_keeps_auto_time_scale_calibrated(self, qtbot) -> None:
        """Manual velocity calibration must not drop the DICOM/tick time flag.

        When the time scale came from auto-detection (DICOM tags or the tick
        fallback) a manual baseline/velocity recalibration must keep the time
        axis auto-calibrated, otherwise time-based tools and results overlay
        are disabled (perceived as "time scale reset").
        """
        from unittest.mock import patch

        from echo_personal_tool.domain.models.doppler_roi import (
            DopplerCalibrationState,
            DopplerSpectrogramRoi,
        )

        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))

        roi = DopplerSpectrogramRoi(x0=0, y0=0, width=64, height=64)
        prior = DopplerCalibrationState(
            roi=roi,
            baseline_y_px=32.0,
            time_span_ms=5600.0,
            time_from_dicom_tags=True,
            from_dicom_tags=True,
        )
        w.doppler.apply_calibration_state(prior, persist=False)

        with patch(
            "echo_personal_tool.presentation.viewer_widget.QInputDialog.getDouble",
            return_value=(200.0, True),
        ):
            w.doppler.prompt_spectral_velocity_span(64.0)

        result = w.doppler.get_calibration_state()
        assert result is not None
        assert result.has_time_scale_from_dicom()
        assert w.doppler.is_time_calibrated()

    def test_clear_doppler_calibration_keeps_time_scale(self, qtbot) -> None:
        """Reset flow must not wipe the auto-detected time scale."""
        from echo_personal_tool.domain.models.doppler_roi import (
            DopplerCalibrationState,
            DopplerSpectrogramRoi,
        )

        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))

        roi = DopplerSpectrogramRoi(x0=0, y0=0, width=64, height=64)
        prior = DopplerCalibrationState(
            roi=roi,
            baseline_y_px=32.0,
            time_span_ms=5600.0,
            time_from_dicom_tags=True,
            from_dicom_tags=True,
        )
        w.doppler.apply_calibration_state(prior, persist=False)

        w.doppler.clear_calibration_display(keep_time_scale=True)

        assert w.doppler.get_calibration_state() is not None
        assert w.doppler.get_calibration_state().time_span_ms == 5600.0
        assert w.doppler.is_time_calibrated()
        assert not w.doppler.is_velocity_calibrated()
        assert not w.doppler.axis_calibrated

    def test_manual_velocity_after_time_preserving_reset_keeps_time(self, qtbot) -> None:
        """Manual velocity calibration after a time-preserving reset keeps time."""
        from unittest.mock import patch

        from echo_personal_tool.domain.models.doppler_roi import (
            DopplerCalibrationState,
            DopplerSpectrogramRoi,
        )

        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))

        roi = DopplerSpectrogramRoi(x0=0, y0=0, width=64, height=64)
        prior = DopplerCalibrationState(
            roi=roi,
            baseline_y_px=32.0,
            time_span_ms=5600.0,
            time_from_dicom_tags=True,
            from_dicom_tags=True,
        )
        w.doppler.apply_calibration_state(prior, persist=False)
        w.doppler.clear_calibration_display(keep_time_scale=True)

        with patch(
            "echo_personal_tool.presentation.viewer_widget.QInputDialog.getDouble",
            return_value=(200.0, True),
        ):
            w.doppler.prompt_spectral_velocity_span(64.0)

        result = w.doppler.get_calibration_state()
        assert result is not None
        assert result.time_span_ms == 5600.0
        assert result.has_time_scale_from_dicom()
        assert w.doppler.is_time_calibrated()


class TestDopplerTimeProvenance:
    """Item 2 of the 2026-11-06 list: a tick-derived time axis is a real one.

    The predicate required ``has_time_scale_from_dicom()`` — DICOM tags only —
    while the automatic path happily derived the window from the tick lattice.
    Such a clip was calibrated on screen and «not calibrated» for VTI, DT and
    Doppler HR at the same time.  The owner decision of 2026-11-06: the tags and
    the ticks both count; the manual dialog never asks for the window, because a
    spectrum carries no time ruler the user could click.
    """

    def test_tick_time_counts_as_a_calibrated_time_axis(self, qtbot) -> None:
        from echo_personal_tool.domain.models.doppler_roi import (
            DopplerCalibrationState,
            DopplerSpectrogramRoi,
        )

        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        roi = DopplerSpectrogramRoi(x0=0, y0=0, width=64, height=64)
        state = DopplerCalibrationState(
            roi=roi,
            baseline_y_px=32.0,
            time_span_ms=5600.0,
            # The ticks are not DICOM tags: this is exactly the clip that used
            # to fall through the old predicate.
            time_from_dicom_tags=False,
        )
        w.doppler.apply_calibration_state(state, persist=False)

        assert w.doppler.is_time_calibrated() is True

    def test_a_zero_window_is_not_a_calibrated_time_axis(self, qtbot) -> None:
        from echo_personal_tool.domain.models.doppler_roi import (
            DopplerCalibrationState,
            DopplerSpectrogramRoi,
        )

        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        roi = DopplerSpectrogramRoi(x0=0, y0=0, width=64, height=64)
        state = DopplerCalibrationState(roi=roi, baseline_y_px=32.0, time_span_ms=0.0)
        w.doppler.apply_calibration_state(state, persist=False)

        assert w.doppler.is_time_calibrated() is False

    def test_a_tagged_axis_still_matches_the_old_predicate(self, qtbot) -> None:
        """Nothing regressed for clips that do carry the tags."""
        from echo_personal_tool.domain.models.doppler_roi import (
            DopplerCalibrationState,
            DopplerSpectrogramRoi,
        )

        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        roi = DopplerSpectrogramRoi(x0=0, y0=0, width=64, height=64)
        state = DopplerCalibrationState(
            roi=roi,
            baseline_y_px=32.0,
            time_span_ms=5600.0,
            time_from_dicom_tags=True,
            from_dicom_tags=True,
        )
        w.doppler.apply_calibration_state(state, persist=False)

        assert state.has_time_scale_from_dicom() is True
        assert w.doppler.is_time_calibrated() is True


# ═══════════════════════════════════════════════════════════════════
#  Handle doppler mouse click
# ═══════════════════════════════════════════════════════════════════


class TestHandleDopplerMouseClick:
    def test_handle_doppler_click_no_mode(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QMouseEvent

        event = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(10, 10),
            QPointF(10, 10),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        result = w.doppler.handle_mouse_click(event)
        assert result is False

    def test_handle_doppler_click_with_mode(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        state = _make_state()
        w.set_state(state)
        w.doppler.set_tool_mode("peak")
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QMouseEvent

        event = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(32, 32),
            QPointF(32, 32),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        result = w.doppler.handle_mouse_click(event)
        assert isinstance(result, bool)


# ═══════════════════════════════════════════════════════════════════
#  Doppler trace press/release
# ═══════════════════════════════════════════════════════════════════


class TestDopplerTracePressRelease:
    def test_handle_doppler_trace_press_with_mode(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        state = _make_state()
        w.set_state(state)
        w.doppler.set_tool_mode("trace")
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QMouseEvent

        event = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(32, 32),
            QPointF(32, 32),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        result = w.doppler.handle_trace_press(event)
        assert isinstance(result, bool)

    def test_handle_doppler_trace_drag(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QMouseEvent

        event = QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(32, 32),
            QPointF(32, 32),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        result = w.doppler.handle_trace_drag(event)
        assert result is False

    def test_handle_doppler_trace_release(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QMouseEvent

        event = QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            QPointF(32, 32),
            QPointF(32, 32),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        result = w.doppler.handle_trace_release(event)
        assert result is False


# ═══════════════════════════════════════════════════════════════════
#  Doppler calibration click
# ═══════════════════════════════════════════════════════════════════


class TestDopplerCalibrationClick:
    def test_handle_doppler_calibration_click_no_step(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QMouseEvent

        event = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(10, 10),
            QPointF(10, 10),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        result = w.doppler.handle_calibration_click(event)
        assert result is False

    def test_handle_doppler_calibration_click_baseline_step(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.doppler.cal_step = "baseline"
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QMouseEvent

        event = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(32, 32),
            QPointF(32, 32),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        result = w.doppler.handle_calibration_click(event)
        assert result is True
        assert w.doppler.cal_step is None

    def test_doppler_calibration_starts_at_baseline(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        assert w.doppler.start_calibration()
        assert w.doppler.cal_step == "baseline"
        assert w.doppler.pending_roi is None

    def test_baseline_sets_velocity_segment_origin(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((200, 200), dtype=np.uint8))
        assert w.doppler.start_calibration()
        assert w.doppler.cal_step == "baseline"
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QMouseEvent

        event = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(100, 80),
            QPointF(100, 80),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        result = w.doppler.handle_calibration_click(event)
        assert result is True
        assert w.doppler.cal_step is None
        assert w.doppler.pending_baseline_y is not None
        assert w.contract.calibration_start_y == w.doppler.pending_baseline_y

    def test_velocity_click_after_baseline_prompts_span(self, qtbot, monkeypatch) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((200, 200), dtype=np.uint8))
        assert w.doppler.start_calibration()
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QMouseEvent

        def click(x, y):
            return QMouseEvent(
                QEvent.Type.MouseButtonPress,
                QPointF(x, y),
                QPointF(x, y),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )

        w.doppler.handle_calibration_click(click(100, 80))
        assert w.doppler.cal_step is None
        assert w.doppler.pending_baseline_y is not None
        baseline = w.doppler.pending_baseline_y
        # The baseline doubles as the first velocity point, so a single
        # further click must open the velocity span dialog.
        assert w.contract.calibration_start_y == baseline

        promoted = []
        monkeypatch.setattr(
            w.doppler,
            "prompt_spectral_velocity_span",
            lambda length_px: promoted.append(length_px),
        )
        result = w.contract.handle_calibration_mouse_press(click(100, 30))
        assert result is True
        mapped_y = w.contract.map_view_event(click(100, 30))[1]
        assert promoted == [abs(mapped_y - baseline)]


# ═══════════════════════════════════════════════════════════════════
#  Linear caliper sequence
# ═══════════════════════════════════════════════════════════════════


class TestLinearCaliperSequence:
    def test_linear_caliper_sequence_flow(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        state = _make_state()
        w.set_state(state)
        # Start sequence
        w.start_linear_caliper_sequence(("IVSd", "LVEDD"))
        assert w.is_linear_caliper_active is True
        assert len(w.contract.caliper_sequence) == 1
        # First click
        m = w.contract.linear_measurement_from_endpoints((10.0, 10.0), (50.0, 10.0), "IVSd")
        w.contract.stored_linear_measurements[w.contract.linear_measurement_key(m)] = m
        # Should chain to next label
        assert w.is_linear_caliper_active is True


# ═══════════════════════════════════════════════════════════════════
#  Contour zone drag
# ═══════════════════════════════════════════════════════════════════


class TestContourZoneDrag:
    def test_handle_contour_zone_drag_no_session(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QMouseEvent

        event = QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(32, 32),
            QPointF(32, 32),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        result = w.contract.handle_contour_zone_drag(event)
        assert result is False

    def test_handle_contour_zone_release_no_session(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QMouseEvent

        event = QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            QPointF(32, 32),
            QPointF(32, 32),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        result = w.contract.handle_contour_zone_release(event)
        assert result is False


# ═══════════════════════════════════════════════════════════════════
#  Caliper node drag
# ═══════════════════════════════════════════════════════════════════


class TestCaliperNodeDrag:
    def test_begin_caliper_node_drag_no_linear(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.contract.begin_caliper_node_drag(("IVSd", 0), 0, 10.0, 10.0)
        # Should not set drag active when linear caliper is active
        assert w.contract.caliper_drag_active is False

    def test_apply_caliper_node_drag_no_active(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.contract.apply_caliper_node_drag(10.0, 10.0)
        # Without an active node drag the call is a no-op: nothing is stored or started.
        assert w.contract.stored_linear_measurements == {}
        assert w.contract.caliper_drag_active is False

    def test_finish_caliper_node_drag(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.contract.finish_caliper_node_drag(cancel=True)
        # Should not raise
        assert w.contract.caliper_drag_active is False


# ═══════════════════════════════════════════════════════════════════
#  MMode calibration click
# ═══════════════════════════════════════════════════════════════════


class TestMModeCalibrationClick:
    def test_handle_mmode_calibration_click_no_step(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QMouseEvent

        event = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(10, 10),
            QPointF(10, 10),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        result = w.mmode.handle_calibration_click(event)
        assert result is False

    def test_handle_mmode_calibration_click_roi_step(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        assert w.mmode.start_panel_calibration() is True
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QMouseEvent

        event = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(32, 32),
            QPointF(32, 32),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        result = w.mmode.handle_calibration_click(event)
        assert result is True
        assert w.mmode.roi_corner1 is not None


# ═══════════════════════════════════════════════════════════════════
#  MMode line click from event
# ═══════════════════════════════════════════════════════════════════


class TestMModeLineClickFromEvent:
    def test_handle_mmode_line_click_from_event_no_active(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QMouseEvent

        event = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(10, 10),
            QPointF(10, 10),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        result = w.mmode.handle_line_click_from_event(event)
        assert result is False


# ═══════════════════════════════════════════════════════════════════
#  Contour hover
# ═══════════════════════════════════════════════════════════════════


class TestContourHover:
    def test_handle_contour_hover_no_contours(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QMouseEvent

        event = QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(32, 32),
            QPointF(32, 32),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        result = w.contract.handle_contour_hover(event)
        assert result is False

    def test_clear_contour_hover(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.contract.hover_contour_index = 0
        w.contract.hover_grab_index = 1
        w.contract.clear_contour_hover()
        assert w.contract.hover_contour_index is None
        assert w.contract.hover_grab_index is None

    def test_clear_contour_node_highlights(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Should not raise
        before = guard_snapshot(w)
        w.contract.clear_contour_node_highlights(0)
        assert guard_snapshot(w) == before, "test_clear_contour_node_highlights: guard handler changed viewer state"


# ═══════════════════════════════════════════════════════════════════
#  RBF drag
# ═══════════════════════════════════════════════════════════════════


class TestRBFDrag:
    def test_apply_rbf_drag_step_no_session(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        # Should not raise
        before = guard_snapshot(w)
        w.contract.apply_rbf_drag_step(0, 10.0, 10.0, grab_index=0)
        assert guard_snapshot(w) == before, "test_apply_rbf_drag_step_no_session: guard handler changed viewer state"
        assert w.contract.drag_session is None


# ═══════════════════════════════════════════════════════════════════
#  Contour editing blocked
# ═══════════════════════════════════════════════════════════════════


class TestContourEditingBlocked:
    def test_contour_editing_blocked_all_false(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w.contract.contour_editing_blocked() is False

    def test_contour_editing_blocked_contour_active(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.contract.contour_mode_active = True
        assert w.contract.contour_editing_blocked() is True

    def test_contour_editing_blocked_linear_active(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.contract.linear_caliper_active = True
        assert w.contract.contour_editing_blocked() is True

    def test_contour_editing_blocked_calibration_active(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.contract.calibration_active = True
        assert w.contract.contour_editing_blocked() is True


# ═══════════════════════════════════════════════════════════════════
#  Contour zone press
# ═══════════════════════════════════════════════════════════════════


class TestContourZonePress:
    def test_handle_contour_zone_press_no_contours(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QMouseEvent

        event = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(32, 32),
            QPointF(32, 32),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        result = w.contract.handle_contour_zone_press(event)
        assert result is False


# ═══════════════════════════════════════════════════════════════════
#  Caliper label item
# ═══════════════════════════════════════════════════════════════════


class TestCaliperLabelItem:
    def test_update_caliper_label_graphics(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        # Should not raise
        w.contract.update_caliper_label_graphics(
            (10.0, 10.0),
            (50.0, 10.0),
            color="#ffb300",
            is_preview=True,
        )
        assert w.contract.active_caliper_label_item is not None, "a preview label must be created on the scene"


# ═══════════════════════════════════════════════════════════════════
#  Contour click flow (ma_septal, ma_lateral, apex)
# ═══════════════════════════════════════════════════════════════════


class TestContourClickFlow:
    def test_ma_septal_click(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.start_contour(phase="ED", view="A4C", chamber="LV")
        w.contract.contour_stage = "ma_septal"
        result = w.handle_contour_click((10.0, 10.0))
        assert result is True
        assert w.contract.active_mitral_septal == (10.0, 10.0)
        assert w.contract.contour_stage == "ma_lateral"

    def test_ma_lateral_click(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.start_contour(phase="ED", view="A4C", chamber="LV")
        w.contract.contour_stage = "ma_lateral"
        w.contract.active_mitral_septal = (10.0, 10.0)
        result = w.handle_contour_click((50.0, 10.0))
        assert result is True
        assert w.contract.active_mitral_annulus == ((10.0, 10.0), (50.0, 10.0))
        assert w.contract.contour_stage == "apex"

    def test_apex_click_model(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.start_model_contour(phase="ED", view="A4C", chamber="LV")
        w.contract.contour_stage = "apex"
        w.contract.active_mitral_septal = (10.0, 10.0)
        w.contract.active_mitral_annulus = ((10.0, 10.0), (50.0, 10.0))
        result = w.handle_contour_click((30.0, 50.0))
        assert result is True

    def test_apex_click_manual(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.start_contour(phase="ED", view="A4C", chamber="LV")
        w.contract.contour_stage = "apex"
        w.contract.active_mitral_septal = (10.0, 10.0)
        w.contract.active_mitral_annulus = ((10.0, 10.0), (50.0, 10.0))
        result = w.handle_contour_click((30.0, 50.0))
        assert result is True

    def test_arc_click(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.start_contour(phase="ED", view="A4C", chamber="LV")
        w.contract.contour_stage = "arc"
        result = w.handle_contour_click((20.0, 20.0))
        assert result is True
        assert len(w.contract.active_arc_points) == 1

    def test_polygon_click(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.start_closed_contour(chamber="LA")
        w.contract.contour_stage = "polygon"
        result = w.handle_contour_click((10.0, 10.0))
        assert result is True
        assert len(w.contract.active_arc_points) == 1


# ═══════════════════════════════════════════════════════════════════
#  Finish contour flow
# ═══════════════════════════════════════════════════════════════════


class TestFinishContourFlow:
    def test_finish_contour_polygon_flow(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.start_closed_contour(chamber="LA")
        w.contract.contour_stage = "polygon"
        # Add 4 points to form a closed polygon
        for pt in [(10, 10), (50, 10), (50, 50), (10, 50)]:
            w.handle_contour_click(pt)
        result = w.finish_contour()
        assert result is True
        assert len(w.contours()) == 1

    def test_finish_contour_arc_insufficient_points(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.start_contour(phase="ED", view="A4C", chamber="LV")
        w.contract.contour_stage = "arc"
        w.contract.active_mitral_septal = (10.0, 10.0)
        w.contract.active_mitral_annulus = ((10.0, 10.0), (50.0, 10.0))
        # No arc points added
        result = w.finish_contour()
        assert result is False

    def test_finish_contour_arc_with_points(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.start_contour(phase="ED", view="A4C", chamber="LV")
        w.contract.contour_stage = "arc"
        w.contract.active_mitral_septal = (10.0, 10.0)
        w.contract.active_mitral_annulus = ((10.0, 10.0), (50.0, 10.0))
        w.contract.active_arc_points = [(20.0, 20.0), (30.0, 30.0), (40.0, 20.0)]
        result = w.finish_contour()
        assert result is True
        assert len(w.contours()) == 1


# ═══════════════════════════════════════════════════════════════════
#  Refine active contour
# ═══════════════════════════════════════════════════════════════════


class TestRefineContour:
    def test_refine_active_open_contour_no_frame(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        result = w.refine_active_open_contour()
        assert result == (False, "")

    def test_refine_active_model_contour(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        result = w.refine_active_model_contour()
        assert result == (False, "")


# ═══════════════════════════════════════════════════════════════════
#  LA assist contour ready
# ═══════════════════════════════════════════════════════════════════


class TestLaAssistContourReady:
    def test_on_la_assist_contour_ready_wrong_chamber(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.set_state(_make_state(frame=0))
        from echo_personal_tool.domain.models import Contour

        w.set_contour_from_domain(_la_contour())
        changed = []
        w.contours_changed.connect(changed.append)
        # Same phase and view as the LA contour on screen, but another chamber
        contour = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10)], frame_index=0)
        # Should not raise
        w.contract.on_la_assist_contour_ready(contour)

        assert changed == [], "the assist only answers for an LA contour"
        assert [c.chamber for c in w.contours()] == ["LA"]
        assert w.contours()[0].points == [(10, 10), (20, 20), (30, 30)]

    def test_on_la_assist_contour_ready_wrong_frame(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        state = _make_state(frame=0)
        w.set_state(state)

        w.set_contour_from_domain(_la_contour())
        changed = []
        w.contours_changed.connect(changed.append)
        contour = _la_contour(points=[(11, 11), (12, 12), (13, 13)], frame_index=5)
        # Should not raise (stale result)
        w.contract.on_la_assist_contour_ready(contour)

        assert changed == [], "a result computed for another frame is stale"
        assert w.contours()[0].points == [(10, 10), (20, 20), (30, 30)]

    def test_on_la_assist_contour_ready_replaces_the_contour_of_the_current_frame(self, qtbot) -> None:
        from unittest.mock import patch

        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.set_state(_make_state(frame=0))
        w.set_contour_from_domain(_la_contour())
        changed = []
        w.contours_changed.connect(changed.append)
        assisted = _la_contour(points=[(11, 11), (12, 12), (13, 13)], uid="1.2.3.4.5.6")

        with patch("PySide6.QtCore.QThreadPool.globalInstance"):  # the background refinement is not the point here
            w.contract.on_la_assist_contour_ready(assisted)

        assert len(changed) == 1
        assert [c.points for c in w.contours()] == [[(11, 11), (12, 12), (13, 13)]]


# ═══════════════════════════════════════════════════════════════════
#  Optical flow refinement
# ═══════════════════════════════════════════════════════════════════


class TestOpticalFlowRefinement:
    def test_apply_optical_flow_refinement_no_contours(self, qtbot) -> None:
        from unittest.mock import patch

        w = _make_viewer(qtbot)
        with patch("PySide6.QtCore.QThreadPool.globalInstance") as pool:
            # Should not raise
            w.contract.apply_optical_flow_refinement(0)

        pool.return_value.start.assert_not_called()

    def test_apply_optical_flow_refinement_out_of_bounds(self, qtbot) -> None:
        from pathlib import Path
        from unittest.mock import patch

        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.set_state(_make_state(path=Path("/tmp/refine.dcm")))
        w.set_contour_from_domain(_open_arc_contour())  # index 0 would be refined

        with (
            patch("PySide6.QtCore.QThreadPool.globalInstance") as pool,
            patch("echo_personal_tool.application.workers.optical_flow_refine_worker.OpticalFlowRefineWorker"),
        ):
            # Should not raise; 1 is the first index past the only contour
            for index in (-1, 1, 100):
                w.contract.apply_optical_flow_refinement(index)

        pool.return_value.start.assert_not_called()

    def test_apply_optical_flow_refinement_starts_a_worker_for_an_open_arc(self, qtbot) -> None:
        from pathlib import Path
        from unittest.mock import patch

        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        path = Path("/tmp/refine.dcm")
        w.set_state(_make_state(path=path))
        w.set_contour_from_domain(_open_arc_contour())

        with (
            patch("PySide6.QtCore.QThreadPool.globalInstance") as pool,
            patch(
                "echo_personal_tool.application.workers.optical_flow_refine_worker.OpticalFlowRefineWorker"
            ) as worker,
        ):
            w.contract.apply_optical_flow_refinement(0)

        pool.return_value.start.assert_called_once_with(worker.return_value)
        assert worker.call_args.kwargs["source_path"] == path
        assert worker.call_args.kwargs["contour_points"] == [(10, 10), (20, 20), (30, 30), (40, 40)]

    def test_on_optical_flow_refined_wrong_length(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.set_state(_make_state())
        w.set_contour_from_domain(_open_arc_contour())
        changed = []
        w.contours_changed.connect(changed.append)
        # Should not raise
        w.contract.on_optical_flow_refined(0, [(1.0, 1.0), (2.0, 2.0)])

        assert changed == [], "points for a different number of nodes are discarded"
        assert w.contours()[0].points == [(10, 10), (20, 20), (30, 30), (40, 40)]

    def test_on_optical_flow_refined_replaces_the_points_and_announces_it(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.set_state(_make_state())
        w.set_contour_from_domain(_open_arc_contour())
        changed = []
        w.contours_changed.connect(changed.append)
        refined = [(11.0, 11.0), (21.0, 21.0), (31.0, 31.0), (41.0, 41.0)]

        w.contract.on_optical_flow_refined(0, refined)

        assert len(changed) == 1
        assert w.contours()[0].points == refined


# ═══════════════════════════════════════════════════════════════════
#  Contour pen for
# ═══════════════════════════════════════════════════════════════════


class TestContourPenFor:
    def test_contour_pen_for_ai_pending(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from echo_personal_tool.domain.models import Contour

        c = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10)], source="ai", review_pending=True)
        pen = w.contract.contour_pen_for(c)
        assert pen is not None

    def test_contour_pen_for_unknown_source(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from echo_personal_tool.domain.models import Contour

        c = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10)], source="unknown")
        pen = w.contract.contour_pen_for(c)
        assert pen is not None


# ═══════════════════════════════════════════════════════════════════
#  Contour node highlight
# ═══════════════════════════════════════════════════════════════════


class TestContourNodeHighlight:
    def test_update_contour_node_highlights(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        from echo_personal_tool.domain.models import Contour

        c = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10), (20, 20)])
        w.set_contour_from_domain(c)
        weights = np.ones(len(c.points))
        before = guard_snapshot(w)
        w.contract.update_contour_node_highlights(0, weights, color="#4caf50")
        assert guard_snapshot(w) == before, "test_update_contour_node_highlights: guard handler changed viewer state"
        # Should not raise


# ═══════════════════════════════════════════════════════════════════
#  RBF highlight color
# ═══════════════════════════════════════════════════════════════════


class TestRBFHighlightColor:
    def test_rbf_highlight_color_manual(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from echo_personal_tool.domain.models import Contour

        c = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10)], source="manual")
        color = w.contract.rbf_highlight_color(c)
        assert isinstance(color, str)

    def test_rbf_highlight_color_ai(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from echo_personal_tool.domain.models import Contour

        c = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10)], source="ai")
        color = w.contract.rbf_highlight_color(c)
        assert isinstance(color, str)


# ═══════════════════════════════════════════════════════════════════
#  Pinned indices for contour
# ═══════════════════════════════════════════════════════════════════


class TestPinnedIndices:
    def test_pinned_indices_for_contour(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        from echo_personal_tool.domain.models import Contour

        c = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10), (20, 20), (30, 30)])
        indices = w.contract.pinned_indices_for_contour(c)
        assert hasattr(indices, "__iter__")


# ═══════════════════════════════════════════════════════════════════
#  View metrics for RBF
# ═══════════════════════════════════════════════════════════════════


class TestViewMetricsForRBF:
    def test_view_metrics_for_rbf(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        result = w.contract.view_metrics_for_rbf()
        assert isinstance(result, tuple)
        assert len(result) == 2


# ═══════════════════════════════════════════════════════════════════
#  Compute hover target
# ═══════════════════════════════════════════════════════════════════


class TestComputeHoverTarget:
    def test_compute_hover_target_no_contours(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        result = w.contract.compute_hover_target((32.0, 32.0))
        assert result is None

    def test_compute_hover_target_with_contours(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        from echo_personal_tool.domain.models import Contour

        c = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10), (20, 20), (30, 30)])
        w.set_contour_from_domain(c)
        result = w.contract.compute_hover_target((15.0, 15.0))
        # May return None or a tuple
        assert result is None or isinstance(result, tuple)


# ═══════════════════════════════════════════════════════════════════
#  Update contour hover
# ═══════════════════════════════════════════════════════════════════


class TestUpdateContourHover:
    def test_update_contour_hover_no_target(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        result = w.contract.update_contour_hover((32.0, 32.0))
        assert result is False


# ═══════════════════════════════════════════════════════════════════
#  Contour zone drag with session
# ═══════════════════════════════════════════════════════════════════


class TestContourZoneDragWithSession:
    def test_handle_contour_zone_drag_with_session(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.contract.drag_session = (0, 10.0, 10.0, 0, 1)
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QMouseEvent

        event = QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(32, 32),
            QPointF(32, 32),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        result = w.contract.handle_contour_zone_drag(event)
        # May return True or False depending on conditions
        assert isinstance(result, bool)


# ═══════════════════════════════════════════════════════════════════
#  Apply RBF drag step
# ═══════════════════════════════════════════════════════════════════


class TestApplyRBFDragStep:
    def test_apply_rbf_drag_step_with_session(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        from echo_personal_tool.domain.models import Contour

        c = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10), (20, 20), (30, 30)])
        w.set_contour_from_domain(c)
        w.contract.drag_session = (0, 10.0, 10.0, 0, 1)
        # Should not raise
        w.contract.apply_rbf_drag_step(0, 15.0, 15.0, grab_index=0)
        assert w.contract.drag_session is not None
        assert w.contract.drag_session[1:3] == (15.0, 15.0), "the drag session must follow the applied point"


class TestMmodeManualWizard:
    def test_the_time_step_is_armed_after_the_depth_answer(self, qtbot, monkeypatch) -> None:
        """ROI -> depth -> time by mouse: the depth answer must leave the time step clickable."""
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QMouseEvent

        def click(x, y):
            return QMouseEvent(
                QEvent.Type.MouseButtonPress,
                QPointF(x, y),
                QPointF(x, y),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )

        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((200, 300), dtype=np.uint8))
        answers = iter([(2.0, True), (1000.0, True)])  # depth in cm, then time span in ms
        monkeypatch.setattr(
            "echo_personal_tool.presentation.viewer_widget.QInputDialog.getDouble",
            lambda *args, **kwargs: next(answers),
        )
        applied = []
        w.mmode_calibration_changed.connect(applied.append)

        assert w.mmode.start_panel_calibration() is True
        assert w.mmode.handle_calibration_click(click(20, 20)) is True
        assert w.mmode.handle_calibration_click(click(250, 180)) is True
        assert w.contract.calibration_kind == "mmode_depth"

        assert w.contract.handle_calibration_mouse_press(click(100, 40)) is True
        assert w.contract.handle_calibration_mouse_press(click(100, 120)) is True
        assert w.mmode.pending_depth_mm_per_pixel is not None
        assert w.contract.calibration_kind == "mmode_time"
        assert w.contract.calibration_active is True, "the time step must accept clicks"

        assert w.contract.handle_calibration_mouse_press(click(40, 100)) is True
        assert w.mmode.time_start_x is not None
        assert w.contract.handle_calibration_mouse_press(click(200, 100)) is True
        assert len(applied) == 1
        assert applied[0].is_complete()
        assert w.mmode.is_calibrated() is True


class TestMmodeTimeAutoScale:
    def _make_mmode_state(self):
        from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi
        from echo_personal_tool.domain.models.frame_panels import (
            MmodeCalibrationState,
        )

        return MmodeCalibrationState(
            roi=DopplerSpectrogramRoi(x0=4.0, y0=341.0, width=1236.0, height=459.0),
            vertical_mm_per_pixel=0.355,
            horizontal_ms_per_pixel=4.167,
            from_dicom_tags=True,
            depth_from_dicom_tags=True,
            time_from_dicom_tags=True,
        )

    def test_time_scale_skips_dialog_when_present(self, qtbot, monkeypatch) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((800, 1240), dtype=np.uint8))
        w.mmode.apply_calibration_state(self._make_mmode_state())
        emitted = []

        def fake_emit(value):
            emitted.append(value)

        w.mmode_time_calibration_completed.connect(fake_emit)

        def fail_dialog(*args, **kwargs):
            raise AssertionError("QInputDialog must not be called when scale exists")

        monkeypatch.setattr(
            "echo_personal_tool.presentation.viewer_widget.QInputDialog.getDouble",
            fail_dialog,
        )
        # Standalone time-only flow (no pending ROI/depth)
        w.mmode.prompt_time_span(length_px=100.0)
        assert emitted == [4.167]

    def test_time_scale_still_prompts_when_absent(self, qtbot, monkeypatch) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((800, 1240), dtype=np.uint8))
        w.contract.calibration_start_y = 50.0
        calls = []

        def fake_dialog(parent, title, prompt, value, mn, mx, dec):
            calls.append((value, mn, mx))
            return 1000.0, True

        monkeypatch.setattr(
            "echo_personal_tool.presentation.viewer_widget.QInputDialog.getDouble",
            fake_dialog,
        )
        w.mmode.prompt_time_span(length_px=100.0)
        assert len(calls) == 1

    def test_full_calibration_uses_dicom_time_when_trusted(self, qtbot, monkeypatch) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((800, 1240), dtype=np.uint8))
        from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi

        w.mmode.apply_calibration_state(self._make_mmode_state())
        # Pending ROI + depth the way the user makes them: the depth caliper
        # spans 1000 px and the answer is 35.5 cm -> 0.355 mm/px.
        monkeypatch.setattr(
            "echo_personal_tool.presentation.viewer_widget.QInputDialog.getDouble",
            lambda *args, **kwargs: (35.5, True),
        )
        w.mmode.start_depth_step(DopplerSpectrogramRoi(x0=4.0, y0=341.0, width=1236.0, height=459.0))
        w.mmode.prompt_depth_calibration(1000.0)
        assert w.mmode.pending_depth_mm_per_pixel == pytest.approx(0.355)

        def fail_dialog(*args, **kwargs):
            raise AssertionError("QInputDialog must not be called when DICOM time is trusted")

        monkeypatch.setattr(
            "echo_personal_tool.presentation.viewer_widget.QInputDialog.getDouble",
            fail_dialog,
        )
        applied = []
        monkeypatch.setattr(
            w.mmode,
            "apply_calibration_state",
            lambda state: applied.append(state),
        )
        w.mmode.prompt_time_span(length_px=100.0)
        assert len(applied) == 1
        assert applied[0].horizontal_ms_per_pixel == 4.167

    def test_time_scale_prompts_when_present_but_not_from_dicom(self, qtbot, monkeypatch) -> None:
        from dataclasses import replace

        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((800, 1240), dtype=np.uint8))
        w.mmode.apply_calibration_state(replace(self._make_mmode_state(), time_from_dicom_tags=False))
        calls = []

        def fake_dialog(parent, title, prompt, value, mn, mx, dec):
            calls.append((value, mn, mx))
            return 1000.0, True

        monkeypatch.setattr(
            "echo_personal_tool.presentation.viewer_widget.QInputDialog.getDouble",
            fake_dialog,
        )
        w.mmode.prompt_time_span(length_px=100.0)
        assert len(calls) == 1


class TestDopplerManualCalibrationHint:
    def test_placeholder_span_shows_hint_until_scale_is_real(self, qtbot) -> None:
        from dataclasses import replace

        from echo_personal_tool.domain.models.doppler_roi import DopplerCalibrationState, DopplerSpectrogramRoi

        viewer = _make_viewer(qtbot)
        viewer.contract.current_frame = np.zeros((240, 480), dtype=np.uint8)
        roi = DopplerSpectrogramRoi(x0=20.0, y0=140.0, width=440.0, height=80.0)
        placeholder = DopplerCalibrationState(
            roi=roi,
            baseline_y_px=180.0,
            velocity_span_cm_s=200.0,
            time_span_ms=0.0,
        )
        viewer.doppler.velocity_confirmed = False
        viewer.doppler.apply_calibration_state(placeholder, persist=False)
        assert placeholder.has_velocity_scale()
        assert viewer.doppler.overlay.manual_calibration_hint_visible()
        hint = viewer.doppler.overlay.manual_calibration_hint
        assert hint is not None
        assert hint.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        tagged = replace(placeholder, velocity_from_dicom_tags=True)
        viewer.doppler.apply_calibration_state(tagged, persist=False)
        assert not viewer.doppler.overlay.manual_calibration_hint_visible()

        # Velocity without time is enough: the time axis is out of scope.
        viewer.doppler.velocity_confirmed = True
        viewer.doppler.apply_calibration_state(placeholder, persist=False)
        assert not viewer.doppler.is_time_calibrated()
        assert not viewer.doppler.overlay.manual_calibration_hint_visible()

        time_only = replace(placeholder, velocity_span_cm_s=0.0, time_span_ms=800.0, time_from_dicom_tags=True)
        viewer.doppler.apply_calibration_state(time_only, persist=False)
        assert not time_only.has_velocity_scale()
        assert viewer.doppler.overlay.manual_calibration_hint_visible()

    def test_hint_hides_during_calibration_and_returns_if_cancelled(self, qtbot) -> None:
        from echo_personal_tool.domain.models.doppler_roi import DopplerCalibrationState, DopplerSpectrogramRoi

        viewer = _make_viewer(qtbot)
        viewer.contract.current_frame = np.zeros((240, 480), dtype=np.uint8)
        viewer.doppler.velocity_confirmed = False
        viewer.doppler.apply_calibration_state(
            DopplerCalibrationState(
                roi=DopplerSpectrogramRoi(x0=10.0, y0=120.0, width=400.0, height=90.0),
                baseline_y_px=160.0,
                velocity_span_cm_s=200.0,
            ),
            persist=False,
        )
        assert viewer.doppler.overlay.manual_calibration_hint_visible()

        assert viewer.doppler.start_calibration() is True
        assert not viewer.doppler.overlay.manual_calibration_hint_visible()

        viewer.cancel_active_tool()
        assert viewer.doppler.overlay.manual_calibration_hint_visible()

    def test_heuristic_panel_alone_does_not_show_hint(self, qtbot) -> None:
        from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi
        from echo_personal_tool.domain.models.frame_panels import FramePanelLayout, PanelKind, UltrasoundPanel

        viewer = _make_viewer(qtbot)
        viewer.contract.current_frame = np.zeros((240, 480), dtype=np.uint8)
        viewer.doppler.clear_calibration_display()
        roi = DopplerSpectrogramRoi(x0=0.0, y0=150.0, width=480.0, height=90.0)
        viewer.contract.frame_panels_from_dicom = False
        viewer.contract.frame_panel_layout = FramePanelLayout(
            panels=(UltrasoundPanel(kind=PanelKind.DOPPLER, bounds=roi),)
        )
        viewer.doppler.sync_manual_calibration_hint()
        assert not viewer.doppler.overlay.manual_calibration_hint_visible()

        viewer.contract.frame_panels_from_dicom = True
        viewer.doppler.sync_manual_calibration_hint()
        assert viewer.doppler.overlay.manual_calibration_hint_visible()


class TestHintStripOverlay:
    """The tool prompt lives in the viewport's black strip, not a separate row."""

    def test_hint_overlay_is_child_of_viewport(self, qtbot) -> None:
        viewer = _make_viewer(qtbot)
        assert viewer.contract.hint_bar.parent() is viewer.contract.graphics.viewport()

    def test_set_hint_toggles_overlay(self, qtbot) -> None:
        viewer = _make_viewer(qtbot)
        viewer.set_hint("Do the thing")
        assert viewer.contract.hint_bar.isVisible()
        assert viewer.contract.hint_bar.text() == "Do the thing"
        viewer.set_hint("")
        assert not viewer.contract.hint_bar.isVisible()

    def test_cancel_active_tool_clears_hint(self, qtbot) -> None:
        viewer = _make_viewer(qtbot)
        viewer.set_hint("AV VTI: draw along the envelope…")
        viewer.cancel_active_tool()
        assert not viewer.contract.hint_bar.isVisible()


class TestFreehandUndo:
    """A+B: Backspace / right-click rolls back the last freehand segment."""

    def test_rollback_drops_last_segment(self, qtbot) -> None:
        viewer = _make_viewer(qtbot)
        viewer.contract.contour_mode_active = True
        viewer.contract.freehand_recording = True
        viewer.contract.freehand_open_arc = True
        viewer.contract.freehand_points = [(float(i), 10.0) for i in range(40)]
        assert viewer.rollback_freehand_segment() is True
        assert len(viewer.contract.freehand_points) == 32

    def test_rollback_inactive_tool_is_noop(self, qtbot) -> None:
        viewer = _make_viewer(qtbot)
        viewer.contract.freehand_recording = False
        assert viewer.rollback_freehand_segment() is False

    def test_rollback_tiny_stroke_cancels(self, qtbot) -> None:
        viewer = _make_viewer(qtbot)
        viewer.contract.contour_mode_active = True
        viewer.contract.freehand_recording = True
        viewer.contract.freehand_open_arc = True
        viewer.contract.freehand_points = [(0.0, 0.0), (1.0, 0.0)]
        assert viewer.rollback_freehand_segment() is True
        assert viewer.contract.freehand_recording is False


@pytest.mark.parametrize("finish_method", ["_finish_model_contour", "_finish_manual_contour"])
def test_landmark_rejection_emits_only_static_code_without_committing(finish_method, qtbot, monkeypatch):
    import echo_personal_tool.presentation.viewer_widget as viewer_module

    viewer = _make_viewer(qtbot)
    viewer.contract.active_mitral_annulus = ((10.0, 20.0), (40.0, 20.0))
    viewer.contract.active_contour_phase = "ED"
    viewer.contract.active_contour_view = "A4C"
    viewer.contract.active_contour_chamber = "LV"
    rejected = []
    completed = []
    viewer.contour_landmark_rejected.connect(rejected.append)
    viewer.contour_completed.connect(completed.append)

    def fail_with_private_detail(**_kwargs):
        raise ValueError("PHI_QH4A_PRIVATE /private/patient-study.dcm")

    monkeypatch.setattr(viewer_module, "fit_contour_from_landmarks", fail_with_private_detail)

    assert getattr(viewer, finish_method)(apex=(25.0, 80.0)) is False
    assert rejected == ["invalid"]
    assert completed == []
    assert viewer.contours() == []
    assert "PHI_QH4A_PRIVATE" not in "".join(rejected)
