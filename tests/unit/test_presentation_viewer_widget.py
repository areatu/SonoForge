"""Unit tests for presentation/viewer_widget.py."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from tests.unit.viewer_guard_helpers import guard_snapshot

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


def _calibrated_vessel_viewer(viewer, *, height=80, width=120, baseline=50, edge_row=20):
    from echo_personal_tool.domain.models.doppler_roi import (
        DopplerCalibrationState,
        DopplerSpectrogramRoi,
    )
    from echo_personal_tool.domain.services.doppler_calibration import build_axis_mapping

    gray = np.zeros((height, width), dtype=np.uint8)
    for col in range(10, width - 10):
        gray[edge_row:baseline, col] = 180
    viewer.contract.current_frame = gray
    state = DopplerCalibrationState(
        roi=DopplerSpectrogramRoi(x0=0.0, y0=0.0, width=float(width), height=float(height)),
        baseline_y_px=float(baseline),
        velocity_span_cm_s=200.0,
    )
    viewer.contract.doppler_calibration_state = state
    viewer.contract.doppler.set_axis_mapping(build_axis_mapping(state))
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
        assert viewer.contract.graphics is not None

    def test_has_view(self, viewer):
        assert viewer.contract.view is not None

    def test_has_image_item(self, viewer):
        assert viewer.contract.image_item is not None

    def test_initial_state(self, viewer):
        assert not viewer.has_frame
        assert viewer.is_calibration_active is False
        assert viewer.is_linear_caliper_active is False
        assert viewer.zoom_mode == "fit"

    def test_has_timeline_slider(self, viewer):
        assert viewer.contract.timeline_slider is not None

    def test_has_play_button(self, viewer):
        assert viewer.contract.play_button is not None


class TestContourViewBox:
    def test_init(self):
        from echo_personal_tool.presentation.viewer_widget import ContourViewBox

        vb = ContourViewBox()
        assert vb.viewer_widget is None
        vb.close()

    def test_set_viewer_widget(self):
        from echo_personal_tool.presentation.viewer_widget import ContourViewBox

        vb = ContourViewBox()
        mock_viewer = MagicMock()
        vb.set_viewer_widget(mock_viewer)
        assert vb.viewer_widget is mock_viewer
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
        assert label.pinned is False
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
        label.on_link_activated("param-id")
        spy.assert_called_once_with("param-id")
        viewer.close()

    def test_link_activated_empty(self):
        from echo_personal_tool.presentation.viewer_widget import ResultsOverlayLabel, ViewerWidget

        viewer = ViewerWidget()
        label = ResultsOverlayLabel(viewer)
        spy = MagicMock()
        label.parameter_clicked.connect(spy)
        label.on_link_activated("")
        spy.assert_not_called()
        viewer.close()


class TestViewerWidgetState:
    def test_set_state(self, viewer):
        state = _empty_state()

        viewer.set_state(state)

        assert viewer.current_state() is state

    def test_contours_empty(self, viewer):
        assert viewer.contours() == []

    def test_show_frame(self, viewer):
        image = np.zeros((100, 100), dtype=np.uint8)
        viewer.show_frame(image)
        assert viewer.has_frame

    def test_show_frame_fast(self, viewer):
        image = np.zeros((100, 100), dtype=np.uint8)
        viewer.show_frame_fast(image)
        assert viewer.has_frame

    def test_clear_frame_overlay(self, viewer):
        viewer.clear_frame_overlay()
        assert viewer.frame_overlay_lines() == ()

    def test_append_frame_overlay(self, viewer):
        viewer.append_frame_overlay("Test overlay")
        assert "Test overlay" in viewer.frame_overlay_lines()


class TestCalibration:
    def test_is_calibration_active(self, viewer):
        assert viewer.is_calibration_active is False

    def test_toggle_calibration_caliper(self, viewer):
        viewer.contract.current_frame = np.zeros((100, 100), dtype=np.uint8)
        viewer.toggle_calibration_caliper()
        assert viewer.is_calibration_active is True
        viewer.toggle_calibration_caliper()
        assert viewer.is_calibration_active is False

    def test_start_calibration_caliper(self, viewer):
        viewer.contract.current_frame = np.zeros((100, 100), dtype=np.uint8)
        result = viewer.start_calibration_caliper()
        assert result is True

    def test_start_calibration_no_frame(self, viewer):
        viewer.contract.current_frame = None
        result = viewer.start_calibration_caliper()
        assert result is False


class TestLinearCaliper:
    def test_toggle_linear_caliper(self, viewer):
        viewer.contract.current_frame = np.zeros((100, 100), dtype=np.uint8)
        viewer.toggle_linear_caliper()
        assert viewer.is_linear_caliper_active is True
        viewer.toggle_linear_caliper()
        assert viewer.is_linear_caliper_active is False

    def test_activate_generic_dist_caliper(self, viewer):
        viewer.contract.current_frame = np.zeros((100, 100), dtype=np.uint8)
        result = viewer.activate_generic_dist_caliper()
        assert result is not None

    def test_cancel_active_tool(self, viewer):
        viewer.contract.current_frame = np.zeros((100, 100), dtype=np.uint8)
        viewer.toggle_linear_caliper()
        viewer.cancel_active_tool()
        assert viewer.is_linear_caliper_active is False


class TestResultsOverlay:
    def test_set_results_overlay(self, viewer):
        viewer.set_results_overlay("<b>Test</b>")
        assert viewer.contract.results_overlay_label.text() != ""

    def test_clear_results_overlay(self, viewer):
        viewer.set_results_overlay("<b>Test</b>")
        viewer.set_results_overlay("")
        assert viewer.contract.results_overlay_label.isHidden()

    def test_results_overlay_text(self, viewer):
        viewer.set_results_overlay("<b>Hello</b>")
        assert viewer.results_overlay_text() != ""


class TestOverlayPosition:
    def test_mark_custom_position(self, viewer):
        viewer.contract.mark_results_overlay_custom_position()
        assert viewer.results_overlay_custom_position() is True

    def test_results_overlay_custom_position(self, viewer):
        assert viewer.results_overlay_custom_position() is False

    def test_set_and_get_position(self, viewer):
        viewer.set_results_overlay_position(0.5, 0.3)
        x, y = viewer.results_overlay_position()
        assert abs(x - 0.5) < 0.01

    def test_reset_results_overlay_to_default(self, viewer):
        viewer.set_results_overlay_position(0.5, 0.3)
        assert viewer.results_overlay_custom_position() is True

        viewer.reset_results_overlay_to_default()

        assert viewer.results_overlay_custom_position() is False


class TestMagneticSnap:
    def test_set_enabled(self, viewer):
        viewer.set_magnetic_snap_enabled(True)
        assert viewer.magnetic_snap_enabled() is True
        viewer.set_magnetic_snap_enabled(False)
        assert viewer.magnetic_snap_enabled() is False


class TestDespeckle:
    def test_set_enabled(self, viewer):
        viewer.set_despeckle_enabled(True)
        assert viewer.despeckle_enabled() is True
        viewer.set_despeckle_enabled(False)
        assert viewer.despeckle_enabled() is False


class TestDoppler:
    def test_get_doppler_tool_mode(self, viewer):
        assert viewer.get_doppler_tool_mode() == "none"

    def test_restore_doppler_state(self, viewer):
        viewer.apply_doppler_calibration_state(_doppler_state(), persist=False)
        assert viewer.is_doppler_velocity_calibrated()

        viewer.restore_doppler_state(None, None)  # nothing was saved for this study

        assert viewer.get_doppler_calibration_state() is None, "the previous study's calibration is dropped"
        assert not viewer.is_doppler_velocity_calibrated()

    def test_restore_doppler_state_applies_the_calibration_and_the_measurements(self, viewer):
        state = _doppler_state()

        viewer.restore_doppler_state(state, _one_peak_dto())

        assert viewer.get_doppler_calibration_state() is state
        assert viewer.is_doppler_velocity_calibrated()
        assert [marker.label for marker in viewer.get_doppler_dto().peaks] == ["E"]

    def test_clear_doppler_calibration_display(self, viewer):
        viewer.apply_doppler_calibration_state(_doppler_state(), persist=False)
        assert viewer.is_doppler_velocity_calibrated()

        viewer.clear_doppler_calibration_display()

        assert viewer.get_doppler_calibration_state() is None
        assert not viewer.is_doppler_velocity_calibrated()

    def test_clear_doppler_measurements(self, viewer):
        viewer.restore_doppler_measurements(_one_peak_dto())
        assert len(viewer.get_doppler_dto().peaks) == 1

        viewer.clear_doppler_measurements()

        dto = viewer.get_doppler_dto()
        assert (dto.peaks, dto.intervals, dto.traces) == ((), (), ())

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
        changed = []
        viewer.mmode_calibration_changed.connect(changed.append)

        viewer.restore_mmode_state(None)  # nothing saved and no frame to read the panel from

        assert viewer.get_mmode_calibration_state() is None
        assert not viewer.is_mmode_calibrated()
        assert changed == []

    def test_restore_mmode_state_applies_the_saved_calibration_and_notifies(self, viewer):
        from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi
        from echo_personal_tool.domain.models.frame_panels import MmodeCalibrationState

        state = MmodeCalibrationState(
            roi=DopplerSpectrogramRoi(x0=10, y0=10, width=50, height=30),
            vertical_mm_per_pixel=0.5,
        )
        changed = []
        viewer.mmode_calibration_changed.connect(changed.append)

        viewer.restore_mmode_state(state)

        assert viewer.get_mmode_calibration_state() is state
        assert changed == [state]

    def test_is_mmode_calibrated(self, viewer):
        assert viewer.is_mmode_calibrated() is False


class TestSpeckle:
    def test_clear_speckle_overlay(self, viewer):
        from echo_personal_tool.domain.models.speckle import StrainResult

        result = StrainResult(
            longitudinal=np.zeros(5),
            radial=np.zeros(5),
            gls=0.0,
            kernels=[],
            raw_tracked_positions=None,
        )
        viewer.show_speckle_result(result)
        assert viewer.speckle_result() is result

        viewer.clear_speckle_overlay()

        assert viewer.speckle_result() is None

    def test_get_lv_contour(self, viewer):
        assert viewer.get_lv_contour() is None


class TestPlayback:
    def test_set_scroll_debounce_ms(self, viewer):
        viewer.set_scroll_debounce_ms(100)
        assert viewer.contract.scroll_debounce_ms == 100


class TestWindowLevel:
    def test_bind_and_disconnect(self, viewer):
        from PySide6.QtWidgets import QSlider

        ws = QSlider()
        ls = QSlider()
        drs = QSlider()
        viewer.bind_display_controls(ws, ls, drs)
        assert viewer.contract.external_wl_dr_sliders is not None
        viewer.disconnect_display_controls()
        ws.close()
        ls.close()
        drs.close()


class TestDicomTagsOverlay:
    def test_refresh_dicom_tags_overlay(self, viewer, tmp_path):
        from echo_personal_tool.infrastructure.user_preferences import UserPreferences
        from tests.fixtures.generate_synthetic_dicom import write_synthetic_dicom

        viewer.apply_user_preferences(UserPreferences(interesting_dicom_tags="Modality"))
        viewer.set_state(_state_for(write_synthetic_dicom(tmp_path / "tags.dcm")))
        viewer.refresh_dicom_tags_overlay()
        assert viewer.dicom_tags_overlay_text() == "Modality: US"

        viewer.set_state(_empty_state())
        viewer.refresh_dicom_tags_overlay()

        assert viewer.dicom_tags_overlay_text() == "", "without an instance there is no file to read the tags from"

    def test_clear_dicom_tags(self, viewer, tmp_path):
        from echo_personal_tool.infrastructure.user_preferences import UserPreferences
        from tests.fixtures.generate_synthetic_dicom import write_synthetic_dicom

        viewer.set_state(_state_for(write_synthetic_dicom(tmp_path / "tags.dcm")))
        viewer.apply_user_preferences(UserPreferences(interesting_dicom_tags="Modality"))
        assert viewer.dicom_tags_overlay_text() == "Modality: US"

        viewer.apply_user_preferences(UserPreferences(interesting_dicom_tags="tag1, tag2"))
        viewer.refresh_dicom_tags_overlay()

        assert viewer.dicom_tags_overlay_text() == "", "tags the file does not carry leave nothing to show"


class TestUserPreferences:
    def test_apply_user_preferences(self, viewer):
        from echo_personal_tool.infrastructure.user_preferences import UserPreferences

        prefs = UserPreferences(
            results_overlay_custom_position=False,
            magnetic_snap_enabled=True,
            despeckle_enabled=False,
            caliper_line_width=2.0,
        )
        viewer.set_magnetic_snap_enabled(False)  # the default is on, so start from the opposite
        viewer.apply_user_preferences(prefs)
        assert viewer.magnetic_snap_enabled() is True

    def test_apply_user_preferences_applies_magnetic_snap_both_ways(self, viewer):
        from echo_personal_tool.infrastructure.user_preferences import UserPreferences

        viewer.apply_user_preferences(UserPreferences(magnetic_snap_enabled=False))
        assert viewer.magnetic_snap_enabled() is False

        viewer.apply_user_preferences(UserPreferences(magnetic_snap_enabled=True))
        assert viewer.magnetic_snap_enabled() is True

    def test_reload_text(self, viewer):
        before = guard_snapshot(viewer)
        viewer.reload_text()
        assert guard_snapshot(viewer) == before, "test_reload_text: guard handler changed viewer state"
        assert viewer.contract.timeline_slider.toolTip(), "reload_text must localize the timeline tooltip"


class TestRepositionOverlays:
    def test_reposition(self, viewer):
        before = guard_snapshot(viewer)
        viewer.reposition_overlays()
        assert guard_snapshot(viewer) == before, "test_reposition: guard handler changed viewer state"

    def test_refresh_after_scroll(self, viewer):
        before = guard_snapshot(viewer)
        viewer.refresh_after_scroll()
        assert guard_snapshot(viewer) == before, "test_refresh_after_scroll: guard handler changed viewer state"


class TestFrameOverlays:
    def test_refresh_frame_overlays(self, viewer):
        viewer.append_frame_overlay("stale line")

        viewer.contract.refresh_frame_overlays()

        assert viewer.frame_overlay_lines() == (), "a refresh rebuilds the overlay: nothing here asks for a line"

    def test_refresh_with_extra_lines(self, viewer):
        viewer.append_frame_overlay("stale line")

        viewer.contract.refresh_frame_overlays(extra_lines=("line1",))

        assert viewer.frame_overlay_lines() == ("line1",), "the extra lines replace what was there"


class TestCaliperLabels:
    def test_current_caliper_label(self, viewer):
        label = viewer.contract.current_caliper_label()
        assert isinstance(label, str)

    def test_reset_dist_caliper_serial(self, viewer):
        viewer.show_frame(np.zeros((64, 64), dtype=np.uint8))
        assert viewer.activate_generic_dist_caliper() == "Dist1"
        assert viewer.activate_generic_dist_caliper() == "Dist2"
        assert viewer.dist_caliper_serial == 3

        viewer.reset_dist_caliper_serial()

        assert viewer.dist_caliper_serial == 1, "the next generic caliper starts again at Dist1"


class TestDeleteCaliper:
    def test_no_caliper_to_delete(self, viewer):
        assert viewer.contract.delete_selected_caliper() is False


class TestDeleteContour:
    def test_no_contour_to_delete(self, viewer):
        assert viewer.delete_contour_for_current_phase() is False


class TestFinishContour:
    def test_no_contour_to_finish(self, viewer):
        assert viewer.finish_contour() is False


class TestStartContour:
    def test_no_frame(self, viewer):
        viewer.contract.current_frame = None
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
        _ev = MagicMock()
        # ContourViewBox.leavesEvent will check _viewer_widget is None and skip cleanup
        assert vb.viewer_widget is None
        vb.close()


class TestSaveViewerImage:
    def test_creates_file_from_grab(self, viewer, tmp_path):
        from unittest.mock import patch

        viewer.contract.current_frame = np.zeros((100, 100), dtype=np.uint8)
        out = tmp_path / "frame.png"
        with patch(
            "echo_personal_tool.presentation.styled_dialogs.styled_save_file",
            return_value=(str(out), "PNG (*.png)"),
        ):
            viewer.contract.save_viewer_image()
        assert out.exists()

    def test_returns_early_when_no_frame(self, viewer):
        from unittest.mock import patch

        viewer.contract.current_frame = None
        with patch(
            "echo_personal_tool.presentation.styled_dialogs.styled_save_file",
        ) as mock_save:
            viewer.contract.save_viewer_image()
        mock_save.assert_not_called()

    def test_offers_png_only_and_rewrites_jpg_name(self, viewer, tmp_path):
        from unittest.mock import patch

        viewer.contract.current_frame = np.zeros((100, 100), dtype=np.uint8)
        typed = tmp_path / "frame.jpg"
        with patch(
            "echo_personal_tool.presentation.styled_dialogs.styled_save_file",
            return_value=(str(typed), "PNG (*.png)"),
        ) as mock_dialog:
            viewer.contract.save_viewer_image()
        assert mock_dialog.call_args[0][3] == "PNG (*.png)"
        assert (tmp_path / "frame.png").exists()
        assert not typed.exists()

    def test_renders_scene_when_grab_is_blank(self, viewer, tmp_path):
        """GL viewport: an ancestor grab() is blank, the scene must still be painted."""
        from unittest.mock import patch

        import cv2
        from PySide6.QtCore import QRectF, Qt
        from PySide6.QtGui import QPixmap

        viewer.contract.current_frame = np.zeros((16, 32), dtype=np.uint8)
        gradient = np.tile(np.linspace(0, 255, 32, dtype=np.uint8), (16, 1))
        viewer.contract.image_item.setImage(gradient, autoLevels=False)
        viewer.contract.view.setRange(QRectF(0, 0, 32, 16), padding=0)

        geo = viewer.contract.graphics.geometry()
        blank = QPixmap(geo.width(), geo.height())
        blank.fill(Qt.GlobalColor.black)
        out = tmp_path / "frame.png"
        with (
            patch(
                "echo_personal_tool.presentation.styled_dialogs.styled_save_file",
                return_value=(str(out), "PNG (*.png)"),
            ),
            patch.object(viewer, "grab", return_value=blank),
        ):
            viewer.contract.save_viewer_image()

        img = cv2.imread(str(out), cv2.IMREAD_GRAYSCALE)
        assert img is not None
        assert img.std() > 10

    def test_shows_error_when_pixmap_save_fails(self, viewer, tmp_path):
        from unittest.mock import patch

        from echo_personal_tool.presentation.viewer_widget import QMessageBox

        viewer.contract.current_frame = np.zeros((100, 100), dtype=np.uint8)
        out = tmp_path / "frame.png"
        warnings = []
        with (
            patch(
                "echo_personal_tool.presentation.styled_dialogs.styled_save_file",
                return_value=(str(out), "PNG (*.png)"),
            ),
            patch.object(viewer, "composite_frame_export"),
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
            viewer.contract.save_viewer_image()
        assert not out.exists()
        assert len(warnings) == 1
        assert str(out) in warnings[0][2]


class TestVesselAutoTrace:
    def test_success_sets_vessel_done(self, viewer):
        _calibrated_vessel_viewer(viewer)
        assert viewer.start_vessel_auto_trace("normal") is True
        assert viewer.contract.doppler.vessel_status() == "done"
        assert viewer.contract.doppler.get_vessel_values() is not None
        assert viewer.contract.doppler.auto_envelope_item is not None

    def test_preset_propagated(self, viewer):
        _calibrated_vessel_viewer(viewer)
        assert viewer.start_vessel_auto_trace("high") is True
        assert viewer.contract.doppler.vessel_status() == "done"

    def test_not_calibrated_returns_false(self, viewer):
        viewer.contract.current_frame = np.zeros((80, 120), dtype=np.uint8)
        assert viewer.start_vessel_auto_trace() is False

    def test_no_signal_returns_false(self, viewer):
        _calibrated_vessel_viewer(viewer)
        viewer.contract.current_frame = np.zeros((80, 120), dtype=np.uint8)
        assert viewer.start_vessel_auto_trace() is False
        assert viewer.contract.doppler.vessel_status() == "none"

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

        viewer.contract.current_frame = np.zeros((200, 1000), dtype=np.uint8)
        state = DopplerCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0.0, y0=0.0, width=1000.0, height=200.0),
            baseline_y_px=100.0,
            velocity_span_cm_s=200.0,
            time_span_ms=2000.0,
        )
        viewer.contract.doppler_calibration_state = state
        viewer.contract.doppler.set_axis_mapping(build_axis_mapping(state))
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
            patch.object(viewer, "extract_doppler_envelope", return_value=envelope),
            patch.object(viewer, "doppler_cardiac_cycles", return_value=self._cycles()),
        ):
            assert viewer.average_vessel_cycles() is True

    def _key(self, key):
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QKeyEvent

        return QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)

    def test_average_activates_selection(self, viewer):
        self._averaged(viewer)
        assert viewer.contract.doppler.vessel_cycle_selection_active() is True
        assert viewer.contract.doppler.vessel_cycle_count() == 2
        from echo_personal_tool.infrastructure.i18n import tr
        from echo_personal_tool.keyboard_shortcuts import shortcut_label

        candidate = viewer.contract.doppler.vessel_cycle_candidate()
        index = viewer.contract.doppler.vessel_cycle_index()
        count = viewer.contract.doppler.vessel_cycle_count()
        expected = tr(
            "viewer.vessel_cycle_candidate",
            value=candidate,
            index=index + 1,
            count=count,
            left_key=shortcut_label("vessel_previous_cycle"),
            right_key=shortcut_label("vessel_next_cycle"),
            accept_key=shortcut_label("finish_tool"),
            cancel_key=shortcut_label("cancel_tool"),
        )
        assert viewer.contract.measurement_label.text() == expected

    def test_left_right_moves_selection(self, viewer):
        from PySide6.QtCore import Qt

        self._averaged(viewer)
        viewer.keyPressEvent(self._key(Qt.Key.Key_Right))
        assert viewer.contract.doppler.vessel_cycle_index() == 1
        viewer.keyPressEvent(self._key(Qt.Key.Key_Left))
        assert viewer.contract.doppler.vessel_cycle_index() == 0

    def test_enter_assigns_candidate_and_accepts(self, viewer):
        from PySide6.QtCore import Qt

        self._averaged(viewer)
        viewer.keyPressEvent(self._key(Qt.Key.Key_Right))
        candidate = viewer.contract.doppler.vessel_cycle_candidate()
        accepted = []
        viewer.vessel_accept_requested.connect(accepted.append)
        from unittest.mock import patch

        with patch.object(viewer, "current_instance_uid", return_value="uid"):
            viewer.keyPressEvent(self._key(Qt.Key.Key_Return))
        assert len(accepted) == 1
        assert accepted[0].psv_cm_s == pytest.approx(candidate)
        assert viewer.contract.doppler.vessel_status() == "none"

    def test_escape_cancels_keeps_median(self, viewer):
        from PySide6.QtCore import Qt

        self._averaged(viewer)
        median_psv, _ = viewer.contract.doppler.get_vessel_values()
        viewer.keyPressEvent(self._key(Qt.Key.Key_Right))
        viewer.keyPressEvent(self._key(Qt.Key.Key_Escape))
        assert viewer.contract.doppler.vessel_cycle_selection_active() is False
        psv, _ = viewer.contract.doppler.get_vessel_values()
        assert psv == pytest.approx(median_psv)
        assert viewer.contract.doppler.vessel_status() == "done"


def test_vessel_sensitivity_overlay_stays_on_viewer_screen(viewer, monkeypatch):
    """Regression: a maximised/fullscreen host window pushed the smoothing
    strip (High/Normal/Low) past the right monitor edge onto the second screen."""
    from PySide6.QtCore import QRect

    avail = QRect(0, 0, 1920, 1080)
    screen = MagicMock()
    screen.availableGeometry.return_value = avail
    monkeypatch.setattr(viewer.contract.graphics, "screen", lambda: screen)
    monkeypatch.setattr(viewer.contract.graphics, "geometry", lambda: QRect(0, 0, 5000, 2000))

    viewer.contract.position_vessel_sensitivity_overlay()

    overlay = viewer.contract.vessel_sensitivity
    assert overlay.x() >= avail.x()
    assert overlay.y() >= avail.y()
    assert overlay.x() + overlay.width() <= avail.x() + avail.width()
    assert overlay.y() + overlay.height() <= avail.y() + avail.height()


def _empty_state():
    from echo_personal_tool.domain.models.viewer_state import ViewerState

    return ViewerState(
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


def _state_for(path, *, frame: int = 0, total: int = 1):
    from echo_personal_tool.domain.models import InstanceMetadata, ViewerState

    instance = InstanceMetadata(
        sop_instance_uid="1.2.3",
        series_uid="1.2.4",
        modality="US",
        number_of_frames=total,
        pixel_spacing=(0.3, 0.3),
        frame_time_ms=None,
        series_description="Synthetic",
        path=path,
        media_format="dicom",
    )
    return ViewerState(
        instance=instance,
        current_frame_index=frame,
        total_frames=total,
        frame_time_ms=None,
        is_playing=False,
    )


class TestReadOnlyStateGetters:
    """The state a caller may read without reaching into the widget (each getter against its public mutator)."""

    def test_has_frame_and_frame_shape_follow_show_frame(self, viewer):
        assert viewer.has_frame is False
        assert viewer.frame_shape is None

        viewer.show_frame(np.zeros((64, 96), dtype=np.uint8))

        assert viewer.has_frame is True
        assert viewer.frame_shape == (64, 96)

        viewer.show_frame(np.zeros((32, 48, 3), dtype=np.uint8))
        assert viewer.frame_shape == (32, 48), "a colour frame is reported by its height and width, without channels"

    def test_zoom_factor_follows_the_manual_zoom_and_resets_with_a_zoom_mode(self, viewer):
        viewer.show_frame(np.zeros((64, 64), dtype=np.uint8))
        assert viewer.zoom_factor == 1.0

        assert viewer.zoom_around(10.0, 10.0, 2.0) is True
        assert viewer.zoom_factor == pytest.approx(2.0)
        assert viewer.zoom_mode == "custom"

        viewer.set_zoom_mode("fit")
        assert viewer.zoom_factor == 1.0

    def test_debug_overlay_getters_follow_the_toggle(self, viewer):
        assert viewer.is_debug_overlay_visible is False
        assert viewer.debug_overlay_text() == ""

        viewer.toggle_debug_overlay()
        assert viewer.is_debug_overlay_visible is True
        assert "Viewport:" in viewer.debug_overlay_text()

        viewer.toggle_debug_overlay()
        assert viewer.is_debug_overlay_visible is False
        assert viewer.debug_overlay_text() == "", "a hidden overlay shows nothing"

    def test_dicom_tags_overlay_text_lists_the_configured_tags(self, viewer, tmp_path):
        from echo_personal_tool.infrastructure.user_preferences import UserPreferences
        from tests.fixtures.generate_synthetic_dicom import write_synthetic_dicom

        path = write_synthetic_dicom(tmp_path / "tags.dcm")
        viewer.set_state(_state_for(path))
        assert viewer.dicom_tags_overlay_text() == "", "no tag is configured yet"

        viewer.apply_user_preferences(UserPreferences(interesting_dicom_tags="Modality, Rows"))
        assert viewer.dicom_tags_overlay_text() == "Modality: US\nRows: 64"

        viewer.apply_user_preferences(UserPreferences(interesting_dicom_tags=""))
        assert viewer.dicom_tags_overlay_text() == ""

    def test_current_state_is_the_last_one_set(self, viewer):
        assert viewer.current_state() is None
        state = _empty_state()

        viewer.set_state(state)

        assert viewer.current_state() is state

    def test_frame_overlay_lines_are_an_ordered_snapshot(self, viewer):
        assert viewer.frame_overlay_lines() == ()

        viewer.append_frame_overlay("first")
        viewer.append_frame_overlay("second")
        snapshot = viewer.frame_overlay_lines()
        viewer.clear_frame_overlay()

        assert snapshot == ("first", "second")
        assert viewer.frame_overlay_lines() == ()

    def test_speckle_result_is_the_one_on_display(self, viewer):
        from echo_personal_tool.domain.models.speckle import StrainResult

        result = StrainResult(
            longitudinal=np.zeros(5),
            radial=np.zeros(5),
            gls=0.0,
            kernels=[],
            raw_tracked_positions=None,
        )
        assert viewer.speckle_result() is None

        viewer.show_speckle_result("not a result")
        assert viewer.speckle_result() is None

        viewer.show_speckle_result(result)
        assert viewer.speckle_result() is result

        viewer.clear_speckle_overlay()
        assert viewer.speckle_result() is None

    def test_window_level_is_on_for_a_grayscale_frame(self, viewer):
        viewer.show_frame(np.zeros((16, 16), dtype=np.uint8))

        assert viewer.is_window_level_enabled is True

    def test_mmode_line_getters_follow_the_scan_line_tools(self, viewer):
        viewer.show_frame(np.zeros((64, 64), dtype=np.uint8))
        assert viewer.is_mmode_line_active is False

        viewer.start_mmode_line()
        assert viewer.is_mmode_line_active is True
        viewer.cancel_mmode_line()
        assert viewer.is_mmode_line_active is False

        viewer.set_mmode_vertical_lock(True)
        assert viewer.mmode_vertical_lock() is True
        viewer.set_mmode_vertical_lock(False)
        assert viewer.mmode_vertical_lock() is False

    def test_mmode_line_crosshair_is_scoped_to_the_2d_cine(self, viewer):
        """Anatomical M-mode must not put a crosshair on playback controls."""
        from PySide6.QtCore import Qt

        viewport = viewer._graphics.viewport()
        controls = (viewer, viewer._play_button, viewer._first_frame_button, viewer._timeline_slider)
        viewer.show_frame(np.zeros((64, 64), dtype=np.uint8))

        viewer.start_mmode_line()
        assert viewport.testAttribute(Qt.WidgetAttribute.WA_SetCursor)
        assert viewport.cursor().shape() == Qt.CursorShape.CrossCursor
        for widget in controls:
            assert not widget.testAttribute(Qt.WidgetAttribute.WA_SetCursor)
            assert widget.cursor().shape() == Qt.CursorShape.ArrowCursor

        viewer.cancel_mmode_line()
        assert not viewport.testAttribute(Qt.WidgetAttribute.WA_SetCursor)
        assert viewport.cursor().shape() == Qt.CursorShape.ArrowCursor
