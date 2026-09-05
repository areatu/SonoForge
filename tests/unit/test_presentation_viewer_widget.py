"""Unit tests for presentation/viewer_widget.py."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def _setup_qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture()
def viewer():
    from echo_personal_tool.presentation.viewer_widget import ViewerWidget

    w = ViewerWidget()
    yield w
    w.close()


def _calibrated_vessel_viewer(viewer, *, height=80, width=120, baseline=50, edge_row=20):
    from echo_personal_tool.domain.models.doppler_roi import (
        DopplerCalibrationState,
        DopplerSpectrogramRoi,
    )
    from echo_personal_tool.domain.services.doppler_calibration import build_axis_mapping

    gray = np.zeros((height, width), dtype=np.uint8)
    for col in range(10, width - 10):
        gray[edge_row:baseline, col] = 180
    viewer._current_frame = gray
    state = DopplerCalibrationState(
        roi=DopplerSpectrogramRoi(x0=0.0, y0=0.0, width=float(width), height=float(height)),
        baseline_y_px=float(baseline),
        velocity_span_cm_s=200.0,
    )
    viewer._doppler_calibration_state = state
    viewer._doppler.set_axis_mapping(build_axis_mapping(state))
    return state


class TestResultsOverlayStyle:
    def test_returns_string(self):
        from echo_personal_tool.presentation.viewer_widget import _results_overlay_style

        css = _results_overlay_style(16)
        assert isinstance(css, str)
        assert "16px" in css

    def test_opacity(self):
        from echo_personal_tool.presentation.viewer_widget import _results_overlay_style

        css = _results_overlay_style(14, opacity=0.5)
        assert isinstance(css, str)

    def test_clamps_opacity(self):
        from echo_personal_tool.presentation.viewer_widget import _results_overlay_style

        css = _results_overlay_style(14, opacity=1.5)
        assert "255" in css

    def test_zero_opacity(self):
        from echo_personal_tool.presentation.viewer_widget import _results_overlay_style

        css = _results_overlay_style(14, opacity=0.0)
        assert "0" in css


class TestViewerWidgetInit:
    def test_creates(self, viewer):
        assert viewer is not None

    def test_has_graphics(self, viewer):
        assert viewer._graphics is not None

    def test_has_view(self, viewer):
        assert viewer._view is not None

    def test_has_image_item(self, viewer):
        assert viewer._image_item is not None

    def test_initial_state(self, viewer):
        assert viewer._current_frame is None
        assert viewer._calibration_active is False
        assert viewer._linear_caliper_active is False
        assert viewer._zoom_mode == "fit"

    def test_has_timeline_slider(self, viewer):
        assert viewer._timeline_slider is not None

    def test_has_play_button(self, viewer):
        assert viewer._play_button is not None


class TestContourViewBox:
    def test_init(self):
        from echo_personal_tool.presentation.viewer_widget import ContourViewBox

        vb = ContourViewBox()
        assert vb._viewer_widget is None
        vb.close()

    def test_set_viewer_widget(self):
        from echo_personal_tool.presentation.viewer_widget import ContourViewBox

        vb = ContourViewBox()
        mock_viewer = MagicMock()
        vb.set_viewer_widget(mock_viewer)
        assert vb._viewer_widget is mock_viewer
        vb.close()

    def test_wheel_event_ignored(self):
        from echo_personal_tool.presentation.viewer_widget import ContourViewBox

        vb = ContourViewBox()
        ev = MagicMock()
        vb.wheelEvent(ev)
        ev.ignore.assert_called_once()
        vb.close()


class TestResultsOverlayLabel:
    def test_init(self):
        from echo_personal_tool.presentation.viewer_widget import ResultsOverlayLabel, ViewerWidget

        viewer = ViewerWidget()
        label = ResultsOverlayLabel(viewer)
        assert label is not None
        assert label._pinned is False
        viewer.close()

    def test_position_ratios(self):
        from echo_personal_tool.presentation.viewer_widget import ResultsOverlayLabel, ViewerWidget

        viewer = ViewerWidget()
        label = ResultsOverlayLabel(viewer)
        label.set_position_ratios(0.5, 0.3)
        x, y = label.position_ratios()
        assert abs(x - 0.5) < 0.01
        assert abs(y - 0.3) < 0.01
        viewer.close()

    def test_clamps_position(self):
        from echo_personal_tool.presentation.viewer_widget import ResultsOverlayLabel, ViewerWidget

        viewer = ViewerWidget()
        label = ResultsOverlayLabel(viewer)
        label.set_position_ratios(2.0, -1.0)
        x, y = label.position_ratios()
        assert x == 1.0
        assert y == 0.0
        viewer.close()

    def test_link_activated_signal(self):
        from echo_personal_tool.presentation.viewer_widget import ResultsOverlayLabel, ViewerWidget

        viewer = ViewerWidget()
        label = ResultsOverlayLabel(viewer)
        spy = MagicMock()
        label.parameter_clicked.connect(spy)
        label._on_link_activated("param-id")
        spy.assert_called_once_with("param-id")
        viewer.close()

    def test_link_activated_empty(self):
        from echo_personal_tool.presentation.viewer_widget import ResultsOverlayLabel, ViewerWidget

        viewer = ViewerWidget()
        label = ResultsOverlayLabel(viewer)
        spy = MagicMock()
        label.parameter_clicked.connect(spy)
        label._on_link_activated("")
        spy.assert_not_called()
        viewer.close()


class TestViewerWidgetState:
    def test_set_state(self, viewer):
        from echo_personal_tool.domain.models.viewer_state import ViewerState

        state = ViewerState(
            instance=None,
            contours=(),
            linear_measurements=(),
            measurement_snapshot=None,
            is_playing=False,
            current_frame_index=0,
            total_frames=0,
            frame_time_ms=None,
            decode_in_progress=False,
        )
        viewer.set_state(state)

    def test_contours_empty(self, viewer):
        assert viewer.contours() == []

    def test_show_frame(self, viewer):
        image = np.zeros((100, 100), dtype=np.uint8)
        viewer.show_frame(image)
        assert viewer._current_frame is not None

    def test_show_frame_fast(self, viewer):
        image = np.zeros((100, 100), dtype=np.uint8)
        viewer.show_frame_fast(image)
        assert viewer._current_frame is not None

    def test_clear_frame_overlay(self, viewer):
        viewer.clear_frame_overlay()
        assert viewer._frame_overlay_lines == []

    def test_append_frame_overlay(self, viewer):
        viewer.append_frame_overlay("Test overlay")
        assert "Test overlay" in viewer._frame_overlay_lines


class TestCalibration:
    def test_is_calibration_active(self, viewer):
        assert viewer.is_calibration_active is False

    def test_toggle_calibration_caliper(self, viewer):
        viewer._current_frame = np.zeros((100, 100), dtype=np.uint8)
        viewer.toggle_calibration_caliper()
        assert viewer._calibration_active is True
        viewer.toggle_calibration_caliper()
        assert viewer._calibration_active is False

    def test_start_calibration_caliper(self, viewer):
        viewer._current_frame = np.zeros((100, 100), dtype=np.uint8)
        result = viewer.start_calibration_caliper()
        assert result is True

    def test_start_calibration_no_frame(self, viewer):
        viewer._current_frame = None
        result = viewer.start_calibration_caliper()
        assert result is False


class TestLinearCaliper:
    def test_toggle_linear_caliper(self, viewer):
        viewer._current_frame = np.zeros((100, 100), dtype=np.uint8)
        viewer.toggle_linear_caliper()
        assert viewer._linear_caliper_active is True
        viewer.toggle_linear_caliper()
        assert viewer._linear_caliper_active is False

    def test_activate_generic_dist_caliper(self, viewer):
        viewer._current_frame = np.zeros((100, 100), dtype=np.uint8)
        result = viewer.activate_generic_dist_caliper()
        assert result is not None

    def test_cancel_active_tool(self, viewer):
        viewer._current_frame = np.zeros((100, 100), dtype=np.uint8)
        viewer.toggle_linear_caliper()
        viewer.cancel_active_tool()
        assert viewer._linear_caliper_active is False


class TestResultsOverlay:
    def test_set_results_overlay(self, viewer):
        viewer.set_results_overlay("<b>Test</b>")
        assert viewer._results_overlay_label.text() != ""

    def test_clear_results_overlay(self, viewer):
        viewer.set_results_overlay("<b>Test</b>")
        viewer.set_results_overlay("")
        assert viewer._results_overlay_label.isHidden()

    def test_results_overlay_text(self, viewer):
        viewer.set_results_overlay("<b>Hello</b>")
        assert viewer.results_overlay_text() != ""


class TestOverlayPosition:
    def test_mark_custom_position(self, viewer):
        viewer._mark_results_overlay_custom_position()
        assert viewer._results_overlay_custom_position is True

    def test_results_overlay_custom_position(self, viewer):
        assert viewer.results_overlay_custom_position() is False

    def test_set_and_get_position(self, viewer):
        viewer.set_results_overlay_position(0.5, 0.3)
        x, y = viewer.results_overlay_position()
        assert abs(x - 0.5) < 0.01

    def test_reset_results_overlay_to_default(self, viewer):
        viewer.set_results_overlay_position(0.5, 0.3)
        viewer.reset_results_overlay_to_default()


class TestMagneticSnap:
    def test_set_enabled(self, viewer):
        viewer.set_magnetic_snap_enabled(True)
        assert viewer._magnetic_snap_enabled is True
        viewer.set_magnetic_snap_enabled(False)
        assert viewer._magnetic_snap_enabled is False


class TestDespeckle:
    def test_set_enabled(self, viewer):
        viewer.set_despeckle_enabled(True)
        assert viewer._despeckle_enabled is True
        viewer.set_despeckle_enabled(False)
        assert viewer._despeckle_enabled is False


class TestDoppler:
    def test_get_doppler_tool_mode(self, viewer):
        assert viewer.get_doppler_tool_mode() == "none"

    def test_restore_doppler_state(self, viewer):
        viewer.restore_doppler_state(None, None)

    def test_clear_doppler_calibration_display(self, viewer):
        viewer.clear_doppler_calibration_display()

    def test_clear_doppler_measurements(self, viewer):
        viewer.clear_doppler_measurements()

    def test_is_doppler_context(self, viewer):
        assert viewer.is_doppler_context() is False

    def test_get_doppler_dto(self, viewer):
        result = viewer.get_doppler_dto()
        # Returns a DopplerMeasurementDTO with empty fields when no measurements
        assert result is not None

    def test_get_doppler_calibration_state(self, viewer):
        assert viewer.get_doppler_calibration_state() is None


class TestMMode:
    def test_get_mmode_calibration_state(self, viewer):
        assert viewer.get_mmode_calibration_state() is None

    def test_restore_mmode_state(self, viewer):
        viewer.restore_mmode_state(None)

    def test_is_mmode_calibrated(self, viewer):
        assert viewer.is_mmode_calibrated() is False


class TestSpeckle:
    def test_clear_speckle_overlay(self, viewer):
        viewer.clear_speckle_overlay()

    def test_get_lv_contour(self, viewer):
        assert viewer.get_lv_contour() is None


class TestPlayback:
    def test_set_scroll_debounce_ms(self, viewer):
        viewer.set_scroll_debounce_ms(100)
        assert viewer._scroll_debounce_ms == 100


class TestWindowLevel:
    def test_bind_and_disconnect(self, viewer):
        from PySide6.QtWidgets import QSlider

        ws = QSlider()
        ls = QSlider()
        drs = QSlider()
        viewer.bind_display_controls(ws, ls, drs)
        assert viewer._external_wl_dr_sliders is not None
        viewer.disconnect_display_controls()
        ws.close()
        ls.close()
        drs.close()


class TestDicomTagsOverlay:
    def test_refresh_dicom_tags_overlay(self, viewer):
        viewer.refresh_dicom_tags_overlay()

    def test_clear_dicom_tags(self, viewer):
        viewer._interesting_dicom_tags = ("tag1", "tag2")
        viewer.refresh_dicom_tags_overlay()


class TestUserPreferences:
    def test_apply_user_preferences(self, viewer):
        from echo_personal_tool.infrastructure.user_preferences import UserPreferences

        prefs = UserPreferences(
            results_overlay_custom_position=False,
            magnetic_snap_enabled=True,
            despeckle_enabled=False,
            caliper_line_width=2.0,
        )
        viewer.apply_user_preferences(prefs)
        assert viewer._magnetic_snap_enabled is True

    def test_reload_text(self, viewer):
        viewer.reload_text()


class TestRepositionOverlays:
    def test_reposition(self, viewer):
        viewer.reposition_overlays()

    def test_refresh_after_scroll(self, viewer):
        viewer.refresh_after_scroll()


class TestFrameOverlays:
    def test_refresh_frame_overlays(self, viewer):
        viewer._refresh_frame_overlays()

    def test_refresh_with_extra_lines(self, viewer):
        viewer._refresh_frame_overlays(extra_lines=("line1",))


class TestCaliperLabels:
    def test_current_caliper_label(self, viewer):
        label = viewer._current_caliper_label()
        assert isinstance(label, str)

    def test_reset_dist_caliper_serial(self, viewer):
        viewer.reset_dist_caliper_serial()


class TestDeleteCaliper:
    def test_no_caliper_to_delete(self, viewer):
        assert viewer._delete_selected_caliper() is False


class TestDeleteContour:
    def test_no_contour_to_delete(self, viewer):
        assert viewer.delete_contour_for_current_phase() is False


class TestFinishContour:
    def test_no_contour_to_finish(self, viewer):
        assert viewer.finish_contour() is False


class TestStartContour:
    def test_no_frame(self, viewer):
        viewer._current_frame = None
        assert viewer.start_contour() is False


class TestContourViewBoxMouseEvents:
    def test_mouse_click_right_button(self):
        from PySide6.QtCore import Qt

        from echo_personal_tool.presentation.viewer_widget import ContourViewBox

        vb = ContourViewBox()
        ev = MagicMock()
        ev.button.return_value = Qt.MouseButton.RightButton
        vb.mouseClickEvent(ev)
        ev.accept.assert_called_once()
        vb.close()

    def test_mouse_press_right_button(self):
        from PySide6.QtCore import Qt

        from echo_personal_tool.presentation.viewer_widget import ContourViewBox

        vb = ContourViewBox()
        ev = MagicMock()
        ev.button.return_value = Qt.MouseButton.RightButton
        vb.mousePressEvent(ev)
        ev.accept.assert_called_once()
        vb.close()

    def test_mouse_drag_right_button(self):
        from PySide6.QtCore import Qt

        from echo_personal_tool.presentation.viewer_widget import ContourViewBox

        vb = ContourViewBox()
        ev = MagicMock()
        ev.button.return_value = Qt.MouseButton.RightButton
        vb.mouseDragEvent(ev)
        ev.accept.assert_called_once()
        vb.close()

    def test_leave_event_no_viewer(self):
        from echo_personal_tool.presentation.viewer_widget import ContourViewBox

        vb = ContourViewBox()
        ev = MagicMock()
        # ContourViewBox.leavesEvent will check _viewer_widget is None and skip cleanup
        assert vb._viewer_widget is None
        vb.close()


class TestSaveViewerImage:
    def test_creates_file_from_grab(self, viewer, tmp_path):
        from unittest.mock import patch

        viewer._current_frame = np.zeros((100, 100), dtype=np.uint8)
        out = tmp_path / "frame.png"
        with patch(
            "echo_personal_tool.presentation.styled_dialogs.styled_save_file",
            return_value=(str(out), "PNG (*.png)"),
        ):
            viewer._save_viewer_image()
        assert out.exists()

    def test_returns_early_when_no_frame(self, viewer):
        from unittest.mock import patch

        viewer._current_frame = None
        with patch(
            "echo_personal_tool.presentation.styled_dialogs.styled_save_file",
        ) as mock_save:
            viewer._save_viewer_image()
        mock_save.assert_not_called()

    def test_shows_error_when_pixmap_save_fails(self, viewer, tmp_path):
        from unittest.mock import patch

        from echo_personal_tool.presentation.viewer_widget import QMessageBox

        viewer._current_frame = np.zeros((100, 100), dtype=np.uint8)
        out = tmp_path / "frame.png"
        warnings = []
        with (
            patch(
                "echo_personal_tool.presentation.styled_dialogs.styled_save_file",
                return_value=(str(out), "PNG (*.png)"),
            ),
            patch.object(
                viewer,
                "grab",
                return_value=MagicMock(
                    isNull=lambda: False,
                    copy=lambda *a, **k: MagicMock(
                        isNull=lambda: False,
                        save=lambda *a, **k: False,
                    ),
                ),
            ),
            patch.object(QMessageBox, "warning", side_effect=lambda *a, **k: warnings.append(a)),
        ):
            viewer._save_viewer_image()
        assert not out.exists()
        assert len(warnings) == 1
        assert str(out) in warnings[0][2]


class TestVesselAutoTrace:
    def test_success_sets_vessel_done(self, viewer):
        _calibrated_vessel_viewer(viewer)
        assert viewer.start_vessel_auto_trace("normal") is True
        assert viewer._doppler.vessel_status() == "done"
        assert viewer._doppler.get_vessel_values() is not None
        assert viewer._doppler._auto_envelope_item is not None

    def test_preset_propagated(self, viewer):
        _calibrated_vessel_viewer(viewer)
        assert viewer.start_vessel_auto_trace("high") is True
        assert viewer._doppler.vessel_status() == "done"

    def test_not_calibrated_returns_false(self, viewer):
        viewer._current_frame = np.zeros((80, 120), dtype=np.uint8)
        assert viewer.start_vessel_auto_trace() is False

    def test_no_signal_returns_false(self, viewer):
        _calibrated_vessel_viewer(viewer)
        viewer._current_frame = np.zeros((80, 120), dtype=np.uint8)
        assert viewer.start_vessel_auto_trace() is False
        assert viewer._doppler.vessel_status() == "none"

    def test_no_frame_returns_false(self, viewer):
        assert viewer.start_vessel_auto_trace() is False


class TestVesselCycleCorrection:
    def _cycles(self):
        from echo_personal_tool.domain.services.cardiac_cycle_service import CardiacCycle

        return (
            CardiacCycle(0.0, 1000.0, 0.0, 0.0, 1000.0, "envelope", 1.0),
            CardiacCycle(1000.0, 2000.0, 1000.0, 1000.0, 2000.0, "envelope", 1.0),
        )

    def _averaged(self, viewer):
        from echo_personal_tool.domain.models.doppler_roi import DopplerCalibrationState, DopplerSpectrogramRoi
        from echo_personal_tool.domain.services.doppler_calibration import build_axis_mapping

        viewer._current_frame = np.zeros((200, 1000), dtype=np.uint8)
        state = DopplerCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0.0, y0=0.0, width=1000.0, height=200.0),
            baseline_y_px=100.0,
            velocity_span_cm_s=200.0,
            time_span_ms=2000.0,
        )
        viewer._doppler_calibration_state = state
        viewer._doppler.set_axis_mapping(build_axis_mapping(state))
        envelope = (
            (100.0, 70.0),
            (200.0, 40.0),
            (300.0, 30.0),
            (400.0, 55.0),
            (500.0, 65.0),
            (600.0, 35.0),
            (700.0, 25.0),
            (800.0, 50.0),
            (900.0, 60.0),
            (1000.0, 70.0),
        )
        from unittest.mock import patch

        with (
            patch.object(viewer, "_extract_doppler_envelope", return_value=envelope),
            patch.object(viewer, "_doppler_cardiac_cycles", return_value=self._cycles()),
        ):
            assert viewer.average_vessel_cycles() is True

    def _key(self, key):
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QKeyEvent

        return QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)

    def test_average_activates_selection(self, viewer):
        self._averaged(viewer)
        assert viewer._doppler.vessel_cycle_selection_active() is True
        assert viewer._doppler.vessel_cycle_count() == 2
        from echo_personal_tool.infrastructure.i18n import tr

        candidate = viewer._doppler.vessel_cycle_candidate()
        index = viewer._doppler.vessel_cycle_index()
        count = viewer._doppler.vessel_cycle_count()
        expected = tr("viewer.vessel_cycle_candidate", value=candidate, index=index + 1, count=count)
        assert viewer._measurement_label.text() == expected

    def test_left_right_moves_selection(self, viewer):
        from PySide6.QtCore import Qt

        self._averaged(viewer)
        viewer.keyPressEvent(self._key(Qt.Key.Key_Right))
        assert viewer._doppler.vessel_cycle_index() == 1
        viewer.keyPressEvent(self._key(Qt.Key.Key_Left))
        assert viewer._doppler.vessel_cycle_index() == 0

    def test_enter_assigns_candidate_and_accepts(self, viewer):
        from PySide6.QtCore import Qt

        self._averaged(viewer)
        viewer.keyPressEvent(self._key(Qt.Key.Key_Right))
        candidate = viewer._doppler.vessel_cycle_candidate()
        accepted = []
        viewer.vessel_accept_requested.connect(accepted.append)
        from unittest.mock import patch

        with patch.object(viewer, "_current_instance_uid", return_value="uid"):
            viewer.keyPressEvent(self._key(Qt.Key.Key_Return))
        assert len(accepted) == 1
        assert accepted[0].psv_cm_s == pytest.approx(candidate)
        assert viewer._doppler.vessel_status() == "none"

    def test_escape_cancels_keeps_median(self, viewer):
        from PySide6.QtCore import Qt

        self._averaged(viewer)
        median_psv, _ = viewer._doppler.get_vessel_values()
        viewer.keyPressEvent(self._key(Qt.Key.Key_Right))
        viewer.keyPressEvent(self._key(Qt.Key.Key_Escape))
        assert viewer._doppler.vessel_cycle_selection_active() is False
        psv, _ = viewer._doppler.get_vessel_values()
        assert psv == pytest.approx(median_psv)
        assert viewer._doppler.vessel_status() == "done"


class TestGetLvContourFilters:
    def test_returns_lv_contour(self, viewer):
        from echo_personal_tool.domain.models.contour import Contour

        c = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10), (20, 20)])
        viewer._stored_contours.append(c)
        result = viewer.get_lv_contour()
        assert result is c

    def test_filters_by_phase(self, viewer):
        from echo_personal_tool.domain.models.contour import Contour

        ed = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10)])
        es = Contour(phase="ES", view="A4C", chamber="LV", points=[(20, 20)])
        viewer._stored_contours.extend([ed, es])
        result = viewer.get_lv_contour(phase="ES")
        assert result is es

    def test_filters_by_view(self, viewer):
        from echo_personal_tool.domain.models.contour import Contour

        a4c = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10)])
        a2c = Contour(phase="ED", view="A2C", chamber="LV", points=[(20, 20)])
        viewer._stored_contours.extend([a4c, a2c])
        result = viewer.get_lv_contour(view="A2C")
        assert result is a2c

    def test_filters_by_phase_and_view(self, viewer):
        from echo_personal_tool.domain.models.contour import Contour

        ed_a4c = Contour(phase="ED", view="A4C", chamber="LV", points=[(10, 10)])
        es_a4c = Contour(phase="ES", view="A4C", chamber="LV", points=[(20, 20)])
        ed_a2c = Contour(phase="ED", view="A2C", chamber="LV", points=[(30, 30)])
        viewer._stored_contours.extend([ed_a4c, es_a4c, ed_a2c])
        result = viewer.get_lv_contour(phase="ED", view="A2C")
        assert result is ed_a2c

    def test_returns_none_when_no_match(self, viewer):
        from echo_personal_tool.domain.models.contour import Contour

        viewer._stored_contours.append(Contour(phase="ED", view="A4C", chamber="LA"))
        assert viewer.get_lv_contour(phase="ED", view="A4C") is None

    def test_case_insensitive_phase(self, viewer):
        from echo_personal_tool.domain.models.contour import Contour

        c = Contour(phase="ed", view="A4C", chamber="LV", points=[(10, 10)])
        viewer._stored_contours.append(c)
        result = viewer.get_lv_contour(phase="ED")
        assert result is c


class TestEnsureLvEpicardialContours:
    def test_creates_lv_epi_from_lv(self, viewer):
        from echo_personal_tool.domain.models.contour import Contour

        ed = Contour(phase="ED", view="A4C", chamber="LV", points=[(50, 50), (60, 50), (60, 60), (50, 60)])
        viewer._stored_contours.append(ed)
        created = viewer.ensure_lv_epicardial_contours(view="A4C")
        assert len(created) == 1
        assert created[0].chamber == "LV_EPI"
        assert created[0].phase == "ED"

    def test_skips_if_epi_already_exists(self, viewer):
        from echo_personal_tool.domain.models.contour import Contour

        ed = Contour(phase="ED", view="A4C", chamber="LV", points=[(50, 50), (60, 50), (60, 60), (50, 60)])
        epi = Contour(phase="ED", view="A4C", chamber="LV_EPI", points=[(48, 48), (62, 48), (62, 62), (48, 62)])
        viewer._stored_contours.extend([ed, epi])
        created = viewer.ensure_lv_epicardial_contours(view="A4C")
        assert len(created) == 0

    def test_skips_contour_with_few_points(self, viewer):
        from echo_personal_tool.domain.models.contour import Contour

        ed = Contour(phase="ED", view="A4C", chamber="LV", points=[(50, 50), (60, 50)])
        viewer._stored_contours.append(ed)
        created = viewer.ensure_lv_epicardial_contours(view="A4C")
        assert len(created) == 0

    def test_adds_to_stored_contours(self, viewer):
        from echo_personal_tool.domain.models.contour import Contour

        ed = Contour(phase="ED", view="A4C", chamber="LV", points=[(50, 50), (60, 50), (60, 60), (50, 60)])
        viewer._stored_contours.append(ed)
        viewer.ensure_lv_epicardial_contours(view="A4C")
        epi = viewer.get_lv_epicardial_contour(phase="ED", view="A4C")
        assert epi is not None
        assert epi.chamber == "LV_EPI"


class TestContourPenFor:
    def test_lv_epi_returns_purple_dashed(self, viewer):
        from PySide6.QtCore import Qt

        from echo_personal_tool.domain.models.contour import Contour

        c = Contour(phase="ED", view="A4C", chamber="LV_EPI", points=[(10, 10)])
        pen = viewer._contour_pen_for(c)
        assert pen.color().name() == "#ab47bc"
        assert pen.style() == Qt.PenStyle.DashLine

    def test_manual_returns_default_pen(self, viewer):
        from echo_personal_tool.domain.models.contour import Contour

        c = Contour(phase="ED", view="A4C", chamber="LV", source="manual", points=[(10, 10)])
        pen = viewer._contour_pen_for(c)
        assert pen is not None

    def test_ai_returns_ai_pen(self, viewer):
        from echo_personal_tool.domain.models.contour import Contour

        c = Contour(phase="ED", view="A4C", chamber="LV", source="ai", points=[(10, 10)])
        pen = viewer._contour_pen_for(c)
        assert pen is not None
