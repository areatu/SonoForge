"""Unit tests for presentation/main_window.py."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

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


@pytest.fixture(autouse=True)
def _isolate_qsettings(isolated_qsettings):
    """Layout rebuilds persist to QSettings — keep them out of the real store."""
    return isolated_qsettings


@pytest.fixture()
def mock_controller():
    from echo_personal_tool.domain.models.viewer_state import ViewerState

    snapshot = ViewerState(
        instance=None,
        current_frame_index=0,
        total_frames=0,
        frame_time_ms=None,
        is_playing=False,
        contours=(),
        linear_measurements=(),
        measurement_snapshot=None,
        decode_in_progress=False,
        manual_pixel_spacing=None,
        scroll_navigation=False,
    )
    c = MagicMock()
    c.state_manager = MagicMock()
    c.state_manager.snapshot = snapshot
    # A MagicMock controller would leave measurement_persistence as a truthy
    # auto-mock: MainWindow._sync_measurement_persistence would then open a
    # modal QMessageBox.exec() during construction and hang the test forever.
    # Behave like the real disabled persistence (plain bools, successful ops).
    c.measurement_persistence.enabled = False
    c.measurement_persistence.has_pending_edits = False
    c.measurement_persistence.flush.return_value = True
    c.measurement_persistence.discard_pending.return_value = True
    c.playback_config = MagicMock(scroll_debounce_ms=100)
    c.studies = []
    c.get_cached_frames.return_value = []
    c._frame_cache = None
    c._current_study_uid = None
    c._measurement_session = {}
    return c


@pytest.fixture()
def main_window(mock_controller, tmp_path):
    from echo_personal_tool.infrastructure.user_preferences import UserPreferences
    from echo_personal_tool.presentation.main_window import MainWindow

    prefs = UserPreferences(
        theme_mode="dark",
        ui_font_size=13,
        layout_state_json="",
        confirm_reset=False,
        auto_play=False,
        magnetic_snap_enabled=False,
        despeckle_enabled=False,
        length_display_unit="mm",
        pdf_font_size=11,
        results_overlay_custom_position=False,
        language="ru",
    )
    with (
        patch(
            "echo_personal_tool.infrastructure.profile.orthanc_cache_root",
            return_value=tmp_path / "orthanc-cache",
        ),
        patch("echo_personal_tool.presentation.main_window.apply_clinical_theme"),
        patch("echo_personal_tool.presentation.main_window.load_user_preferences", return_value=prefs),
        patch("echo_personal_tool.presentation.main_window.format_results_overlay_html", return_value=""),
        patch.object(mock_controller, "compute_overlay_snapshot", return_value=None),
    ):
        w = MainWindow(controller=mock_controller)
    yield w
    w.close()


class TestLayoutConfig:
    def test_defaults(self):
        from echo_personal_tool.presentation.main_window import LayoutConfig

        cfg = LayoutConfig()
        assert cfg.swap_places is False
        assert cfg.gallery_horizontal is False
        assert cfg.activity_bar is False
        assert cfg.status_bar_visible is True
        assert cfg.multiview is False

    def test_from_json(self):
        from echo_personal_tool.presentation.main_window import LayoutConfig

        raw = json.dumps({"swap_places": True, "gallery_horizontal": True})
        cfg = LayoutConfig(**json.loads(raw))
        assert cfg.swap_places is True
        assert cfg.gallery_horizontal is True

    def test_invalid_json(self):
        from echo_personal_tool.presentation.main_window import LayoutConfig

        cfg = LayoutConfig(**json.loads("{}"))
        assert cfg == LayoutConfig()


class TestLoadedFileLabel:
    def test_with_path(self):
        from echo_personal_tool.presentation.main_window import _loaded_file_label

        inst = MagicMock()
        inst.path = MagicMock()
        inst.path.name = "test.dcm"
        inst.sop_instance_uid = "uid"
        assert _loaded_file_label(inst) == "test.dcm"

    def test_without_path(self):
        from echo_personal_tool.presentation.main_window import _loaded_file_label

        inst = MagicMock()
        inst.path = None
        inst.sop_instance_uid = "uid-123"
        assert _loaded_file_label(inst) == "uid-123"


class TestMainWindow:
    def test_creates(self, main_window):
        assert main_window is not None

    def test_initial_layout_config(self, main_window):
        from echo_personal_tool.presentation.main_window import LayoutConfig

        assert isinstance(main_window._layout_config, LayoutConfig)

    def test_reset_layout_to_default(self, main_window):
        from echo_personal_tool.presentation.main_window import LayoutConfig

        main_window._layout_config = replace(main_window._layout_config, swap_places=True)
        main_window.reset_layout_to_default()
        assert main_window._layout_config == LayoutConfig()

    def test_show_status(self, main_window):
        main_window._show_status("test message")
        assert main_window._system_bar._status_label.text() != ""

    def test_on_instance_selected_non_instance(self, main_window):
        main_window._on_instance_selected("not an instance")

    def test_on_instance_selected_clears_ste_results(self, main_window):
        """Switching to another file must drop the previous clip's STE overlay
        and close its strain window, so kernels/contours don't leak onto the
        new cine (issue: dots visible on every frame of every clip).

        The reset is armed on click (old frame + overlays stay on screen while
        the new file decodes) and runs atomically with the swap: speckle
        kernels drop in set_state, strain/manuals drop on first frame.
        """
        from PySide6.QtWidgets import QWidget

        from echo_personal_tool.domain.models.metadata import InstanceMetadata
        from echo_personal_tool.domain.models.viewer_state import ViewerState

        instance = InstanceMetadata(
            sop_instance_uid="1.2.3.4",
            series_uid="series-1",
            modality="US",
            number_of_frames=10,
            pixel_spacing=None,
            frame_time_ms=None,
            series_description="",
            media_format="dicom",
            path=None,
        )
        viewer = main_window._viewer
        viewer._speckle_result = object()  # simulate a finished STE run
        strain_win = QWidget()
        main_window._strain_window = strain_win
        main_window._manual_ed_frame = 3
        main_window._manual_es_frame = 8

        main_window._on_instance_selected(instance)

        # Click only arms the swap: nothing pops off the still-visible frame.
        assert viewer._speckle_result is not None
        assert main_window._strain_window is strain_win
        assert main_window._manual_ed_frame == 3
        assert main_window._manual_es_frame == 8
        assert main_window._pending_swap_uid == "1.2.3.4"
        main_window._controller.load_instance.assert_called_once_with(instance)

        # Swap, phase 1 — new instance state arrives: kernels drop.
        viewer.set_state(
            ViewerState(
                instance=instance,
                current_frame_index=0,
                total_frames=10,
                frame_time_ms=33.3,
                is_playing=False,
            )
        )
        assert viewer._speckle_result is None  # overlay state fully dropped

        # Swap, phase 2 — first frame paints: strain window + manuals reset.
        main_window._controller.is_scroll_active.return_value = False
        main_window._controller.needs_manual_calibration.return_value = False
        main_window._on_frame_loaded(np.zeros((32, 32), dtype=np.uint8))
        assert main_window._strain_window is None  # results window closed
        # Manual ED/ES frames belong to the old clip and must not leak onto the
        # new one (issue #5: STE kept the previous file's frames).
        assert main_window._manual_ed_frame is None
        assert main_window._manual_es_frame is None

    def test_on_instance_selected_same_instance_keeps_manual_frames(self, main_window):
        """Re-selecting the same clip must NOT reset manual ED/ES frames."""
        from echo_personal_tool.domain.models.metadata import InstanceMetadata

        instance = InstanceMetadata(
            sop_instance_uid="1.2.3.4",
            series_uid="series-1",
            modality="US",
            number_of_frames=10,
            pixel_spacing=None,
            frame_time_ms=None,
            series_description="",
            media_format="dicom",
            path=None,
        )
        main_window._manual_ed_frame = 3
        main_window._manual_es_frame = 8
        # the currently loaded clip IS this instance → no switch
        from dataclasses import replace as dc_replace

        main_window._controller.state_manager.snapshot = dc_replace(
            main_window._controller.state_manager.snapshot,
            instance=instance,
        )
        main_window._on_instance_selected(instance)
        assert main_window._manual_ed_frame == 3
        assert main_window._manual_es_frame == 8

    def test_studies_loaded_autoloads_first_clip(self, main_window):
        """A newly opened study must show its first clip at once instead of
        keeping the previous study's frame until a manual click."""
        from datetime import datetime

        from echo_personal_tool.domain.models.metadata import (
            InstanceMetadata,
            SeriesMetadata,
            StudyMetadata,
        )

        first = InstanceMetadata(
            sop_instance_uid="1.2.3.first",
            series_uid="series-1",
            modality="US",
            number_of_frames=10,
            pixel_spacing=None,
            frame_time_ms=None,
            series_description="",
            media_format="dicom",
            path=None,
        )
        second = InstanceMetadata(
            sop_instance_uid="1.2.3.second",
            series_uid="series-1",
            modality="US",
            number_of_frames=10,
            pixel_spacing=None,
            frame_time_ms=None,
            series_description="",
            media_format="dicom",
            path=None,
        )
        studies = [
            StudyMetadata(
                study_uid="study-1",
                study_datetime=datetime(2026, 10, 1),
                series=(
                    SeriesMetadata(
                        series_uid="series-1",
                        study_uid="study-1",
                        modality="US",
                        description="",
                        instances=(first, second),
                    ),
                ),
            )
        ]
        main_window._on_studies_loaded(studies)
        main_window._controller.load_instance.assert_called_once_with(first)
        assert main_window._pending_swap_uid == "1.2.3.first"

    def test_studies_loaded_empty_loads_nothing(self, main_window):
        main_window._on_studies_loaded([])
        main_window._controller.load_instance.assert_not_called()

    def test_on_strain_window_closed_hides_smoothing_overlay(self, main_window):
        """Closing the strain window must hide the viewer's smoothing slider
        (issue #1: the slider stayed at bottom-left after closing STE)."""
        main_window._strain_window = object()
        main_window._on_strain_window_closed()
        assert main_window._strain_window is None
        assert not main_window._viewer._ste_sensitivity.isVisible()

    def test_speckle_result_carries_cine_frames_into_strain_window(self, main_window):
        """The cine frames the worker tracked on must reach the STE window via
        ``StrainResult.cine_frames`` even when the viewer's frame cache has
        dropped the clip (evicted under the memory budget) — otherwise the
        contour/kernel animation has no background and never shows motion."""
        from echo_personal_tool.domain.models.speckle import StrainResult

        cine = np.zeros((6, 200, 200), dtype=np.uint8)
        result = StrainResult(
            longitudinal=np.zeros(6),
            radial=np.zeros(6),
            gls=-18.0,
            ed_index=1,
            es_index=4,
            cine_frames=cine,
        )
        # Cache claims it does NOT hold the full cine — the result itself must
        # provide the frames.
        main_window._controller._frame_cache = MagicMock()
        main_window._controller._frame_cache.require_full_cine.side_effect = RuntimeError("incomplete")

        main_window._on_speckle_result_ready(result)

        win = main_window._strain_window
        assert win is not None
        panel_frames = win._panel_a4c._frames
        assert panel_frames is cine
        assert win._panel_a4c._frame_slider.maximum() == 5
        assert main_window._strain_frames_for_window is cine

    def test_ste_view_buttons_set_analysis_position(self, main_window):
        """The Стрейн toolbar A4C/A2C/A3C buttons record the active view; the
        next Speckle Tracking launch prefers contours of that view."""
        from echo_personal_tool.presentation.measurement_action import MeasurementAction

        main_window._on_measure_action(MeasurementAction.STE_VIEW_A2C, "A4C", "ED")
        assert main_window._ste_position == "A2C"

        main_window._on_measure_action(MeasurementAction.STE_VIEW_A3C, "A4C", "ED")
        assert main_window._ste_position == "A3C"

        main_window._on_measure_action(MeasurementAction.STE_VIEW_A4C, "A4C", "ED")
        assert main_window._ste_position == "A4C"

    def test_strain_curves_action_reopens_window_in_curves_mode(self, main_window):
        """The 'Strain curves' button reopens the results window on the curves
        page (issue #6: no entry point from the main window to the graph)."""
        from echo_personal_tool.domain.models.speckle import StrainResult

        result = StrainResult(longitudinal=np.zeros(5), radial=np.zeros(5), gls=-15.0)
        main_window._strain_result_for_window = result
        main_window._on_strain_curves_requested()
        assert main_window._strain_window is not None
        assert main_window._strain_window._stacked.currentIndex() == 1

    def test_strain_curves_action_no_result_shows_status(self, main_window):
        main_window._strain_result_for_window = None
        main_window._on_strain_curves_requested()
        assert main_window._strain_window is None

    def test_on_frame_load_failed(self, main_window):
        with patch("echo_personal_tool.presentation.main_window.QMessageBox"):
            main_window._on_frame_load_failed("error msg")
        assert main_window._click_to_frame_started_at is None

    def test_on_slider_frame_selected(self, main_window):
        main_window._on_slider_frame_selected(5)
        main_window._controller.state_manager.set_frame.assert_called_once_with(5)

    def test_toggle_fullscreen_shortcut_from_normal(self, main_window):
        main_window.showNormal()
        main_window._gallery.show()
        main_window._tool_panel.show()
        main_window._toggle_fullscreen_shortcut()
        assert not main_window._gallery.isVisible()

    def test_toggle_gallery_shortcut(self, main_window):
        main_window._toggle_gallery_shortcut()

    def test_on_activity_action_caliper(self, main_window):
        with patch.object(main_window, "_on_caliper_requested") as mock:
            main_window._on_activity_action("caliper")
            mock.assert_called_once()

    def test_on_activity_action_lv2d(self, main_window):
        with patch.object(main_window, "_on_lv2d_all_diastole") as mock:
            main_window._on_activity_action("lv2d")
            mock.assert_called_once()

    def test_on_activity_action_esv(self, main_window):
        with patch.object(main_window, "_on_lv2d_es") as mock:
            main_window._on_activity_action("esv")
            mock.assert_called_once()


class TestDecideLeftRight:
    def test_default_left_is_gallery(self, main_window):
        from echo_personal_tool.presentation.main_window import LayoutConfig

        cfg = LayoutConfig()
        assert main_window._decide_left(cfg) is main_window._gallery
        assert main_window._decide_right(cfg) is None

    def test_swap_places(self, main_window):
        from echo_personal_tool.presentation.main_window import LayoutConfig

        cfg = LayoutConfig(swap_places=True)
        assert main_window._decide_left(cfg) is main_window._tool_panel
        assert main_window._decide_right(cfg) is main_window._gallery

    def test_activity_bar(self, main_window):
        from echo_personal_tool.presentation.main_window import LayoutConfig

        cfg = LayoutConfig(activity_bar=True)
        assert main_window._decide_left(cfg) is main_window._gallery
        assert main_window._decide_right(cfg) is main_window._activity_bar

    def test_gallery_horizontal(self, main_window):
        from echo_personal_tool.presentation.main_window import LayoutConfig

        cfg = LayoutConfig(gallery_horizontal=True)
        assert main_window._decide_left(cfg) is None
        assert main_window._decide_right(cfg) is main_window._tool_panel

    def test_multiview_right(self, main_window):
        from echo_personal_tool.presentation.main_window import LayoutConfig

        cfg = LayoutConfig(multiview=True)
        assert main_window._decide_right(cfg) is main_window._tool_panel


class TestReleaseContentLayout:
    def test_clears_layout(self, main_window):
        main_window._release_content_layout()
        assert main_window._content_layout.count() == 0


class TestTeardownBottomGallery:
    def test_noop_when_none(self, main_window):
        main_window._bottom_container = None
        main_window._teardown_bottom_gallery()  # Should not crash


class TestLoadLayoutState:
    def test_empty_string(self, main_window):
        from echo_personal_tool.presentation.main_window import LayoutConfig

        main_window._user_preferences.layout_state_json = ""
        assert main_window._load_layout_state() == LayoutConfig()

    def test_invalid_json(self, main_window):
        from echo_personal_tool.presentation.main_window import LayoutConfig

        main_window._user_preferences.layout_state_json = "not json"
        assert main_window._load_layout_state() == LayoutConfig()


class TestOnLayoutToggle:
    def test_toggles_swap(self, main_window):
        old = main_window._layout_config.swap_places
        main_window._on_layout_toggle("swap_places", not old)
        assert main_window._layout_config.swap_places == (not old)


class TestOnMagneticSnapChanged:
    def test_updates_viewer(self, main_window):
        with (
            patch("echo_personal_tool.presentation.main_window.save_user_preferences"),
            patch.object(main_window._viewer, "set_magnetic_snap_enabled") as mock,
        ):
            main_window._on_magnetic_snap_changed(True)
            mock.assert_called_with(True)


class TestOnDespeckleChanged:
    def test_updates_viewer(self, main_window):
        with (
            patch("echo_personal_tool.presentation.main_window.save_user_preferences"),
            patch.object(main_window._viewer, "set_despeckle_enabled") as mock,
        ):
            main_window._on_despeckle_changed(True)
            mock.assert_called_with(True)


class TestOnAutoPlayChanged:
    def test_saves_preference(self, main_window):
        with patch("echo_personal_tool.presentation.main_window.save_user_preferences"):
            main_window._on_auto_play_changed(True)
            assert main_window._user_preferences.auto_play is True


class TestOnContourCompleted:
    def test_non_contour_ignored(self, main_window):
        main_window._on_contour_completed("not a contour")

    def test_area_chamber(self, main_window):
        from echo_personal_tool.domain.models import Contour

        contour = MagicMock(spec=Contour)
        contour.chamber = "AREA"
        contour.is_open_arc = True
        contour.source = "manual"
        # Replace snapshot with one that has contours
        new_state = replace(main_window._controller.state_manager.snapshot, contours=(contour,))
        main_window._controller.state_manager.snapshot = new_state
        with (
            patch("echo_personal_tool.presentation.main_window.format_results_overlay_html", return_value=""),
            patch.object(main_window._controller, "compute_overlay_snapshot", return_value=None),
        ):
            main_window._on_contour_completed(contour)


class TestHasChamberContour:
    def test_no_contours(self, main_window):

        new_state = replace(main_window._controller.state_manager.snapshot, contours=())
        main_window._controller.state_manager.snapshot = new_state
        assert main_window._has_chamber_contour("LV", "A4C", "ED") is False

    def test_matching_contour(self, main_window):

        c = MagicMock()
        c.chamber = "LV"
        c.view = "A4C"
        c.phase = "ED"
        new_state = replace(main_window._controller.state_manager.snapshot, contours=(c,))
        main_window._controller.state_manager.snapshot = new_state
        assert main_window._has_chamber_contour("LV", "A4C", "ED") is True

    def test_no_match(self, main_window):

        c = MagicMock()
        c.chamber = "RA"
        c.view = "A4C"
        c.phase = "ES"
        new_state = replace(main_window._controller.state_manager.snapshot, contours=(c,))
        main_window._controller.state_manager.snapshot = new_state
        assert main_window._has_chamber_contour("LV", "A4C", "ED") is False


class TestOnStateChange:
    def test_non_viewer_state_ignored(self, main_window):
        main_window._on_state_changed("not a ViewerState")


class TestUpdatePropertiesPanel:
    def test_missing_dicom_file_does_not_crash(self, main_window):
        from echo_personal_tool.domain.models.metadata import InstanceMetadata

        instance = InstanceMetadata(
            sop_instance_uid="1.2.3",
            series_uid="1.2.4",
            modality="US",
            number_of_frames=10,
            pixel_spacing=None,
            frame_time_ms=33.3,
            series_description="Test",
            path=Path("/tmp/nonexistent_test.dcm"),
        )
        state = replace(
            main_window._controller.state_manager.snapshot,
            instance=instance,
            total_frames=10,
            frame_time_ms=33.3,
        )
        main_window._update_properties_panel(state)
        assert main_window._tool_panel.properties_panel._instance_group.isHidden() is False


class TestFormatSpecklePresetName:
    def test_known_presets(self):
        from echo_personal_tool.presentation.main_window import MainWindow

        assert MainWindow._format_speckle_preset_name("standard") == "Standard"
        assert MainWindow._format_speckle_preset_name("research") == "Research"
        assert MainWindow._format_speckle_preset_name("debug") == "Debug"

    def test_unknown_preset(self):
        from echo_personal_tool.presentation.main_window import MainWindow

        assert MainWindow._format_speckle_preset_name("custom") == "custom"


class TestOnMmodeColumnReady:
    def test_no_widget(self, main_window):
        main_window._mmode_widget = None
        main_window._mmode_active = False
        main_window._on_mmode_column_ready(np.zeros(256), 0)

    def test_with_widget_active(self, main_window):
        main_window._mmode_widget = MagicMock()
        main_window._mmode_active = True
        main_window._on_mmode_column_ready(np.zeros(256), 0)
        main_window._mmode_widget.on_new_column.assert_called_once()

    def test_with_widget_inactive(self, main_window):
        main_window._mmode_widget = MagicMock()
        main_window._mmode_active = False
        main_window._on_mmode_column_ready(np.zeros(256), 0)
        main_window._mmode_widget.on_new_column.assert_not_called()


class TestOnMmodeLineCompleted:
    def test_no_widget(self, main_window):
        main_window._mmode_widget = None
        main_window._on_mmode_line_completed((10, 20), (100, 200))

    def test_with_widget_and_cached_frames(self, main_window):
        main_window._mmode_widget = MagicMock()
        main_window._mmode_active = True
        main_window._controller.get_cached_frames.return_value = [np.zeros((256, 256))]
        main_window._on_mmode_line_completed((10, 20), (100, 200))
        main_window._mmode_widget.recalculate_from_frames.assert_called_once()


class TestOnTeichholzEdComplete:
    def test_less_than_3_measurements(self, main_window):
        main_window._on_teichholz_ed_complete([MagicMock(), MagicMock()])

    def test_none_values(self, main_window):
        m1 = MagicMock(value_mm=None)
        m2 = MagicMock(value_mm=40.0)
        m3 = MagicMock(value_mm=10.0)
        main_window._on_teichholz_ed_complete([m1, m2, m3])


class TestOnTeichholzEsComplete:
    def test_none_value(self, main_window):
        m = MagicMock(value_mm=None)
        main_window._on_teichholz_es_complete(m)

    def test_no_widget(self, main_window):
        main_window._mmode_widget = None
        m = MagicMock(value_mm=25.0)
        main_window._on_teichholz_es_complete(m)


class TestCloseEvent:
    def test_closes_when_mmode_inactive(self, main_window):
        from PySide6.QtGui import QCloseEvent

        main_window._mmode_active = False
        event = QCloseEvent()
        main_window.closeEvent(event)

    def test_closes_mmode_when_active(self, main_window):
        from PySide6.QtGui import QCloseEvent

        main_window._mmode_active = True
        event = QCloseEvent()
        main_window.closeEvent(event)
        assert not main_window._mmode_active
        main_window._controller.measurement_persistence.close.assert_not_called()

    def test_cache_clears_on_exit_by_default(self, main_window):
        from PySide6.QtGui import QCloseEvent

        with patch.object(main_window._orthanc_cache, "clear_all") as clear_all:
            main_window._user_preferences.orthanc_cache_clear_on_exit = True
            main_window.closeEvent(QCloseEvent())
            clear_all.assert_called_once_with()

    def test_cache_can_be_kept_on_exit(self, main_window):
        from PySide6.QtGui import QCloseEvent

        with patch.object(main_window._orthanc_cache, "clear_all") as clear_all:
            main_window._user_preferences.orthanc_cache_clear_on_exit = False
            main_window.closeEvent(QCloseEvent())
            clear_all.assert_not_called()

    def test_failed_measurement_flush_cancels_close_without_deleting_cache(self, main_window):
        from PySide6.QtGui import QCloseEvent

        session = main_window._orthanc_cache.create_session()
        source = main_window._orthanc_cache.save_instance(session, "1.2.3", "1.2.3.1", "1.2.3.2", b"DICM")
        persistence = main_window._controller.measurement_persistence
        persistence.close.return_value = False
        main_window._user_preferences.orthanc_cache_clear_on_exit = True
        try:
            with patch("echo_personal_tool.presentation.main_window.QMessageBox.warning"):
                event = QCloseEvent()
                main_window.closeEvent(event)
            assert not event.isAccepted()
            assert source.exists()
        finally:
            persistence.close.return_value = True

    def test_successful_measurement_flush_precedes_cache_deletion(self, main_window):
        from PySide6.QtGui import QCloseEvent

        order = []
        persistence = main_window._controller.measurement_persistence
        persistence.close.side_effect = lambda: order.append("measurements") or True
        try:
            with patch.object(main_window._orthanc_cache, "clear_all", side_effect=lambda: order.append("cache")):
                main_window._user_preferences.orthanc_cache_clear_on_exit = True
                main_window.closeEvent(QCloseEvent())
            assert order == ["measurements", "cache"]
        finally:
            persistence.close.side_effect = None


class TestOrthancCacheStartupCleanup:
    def test_removes_stale_cache_sessions_at_startup(self, mock_controller, tmp_path):
        import os
        import time

        from echo_personal_tool.infrastructure.orthanc_cache import OrthancSessionCache
        from echo_personal_tool.infrastructure.user_preferences import UserPreferences
        from echo_personal_tool.presentation.main_window import MainWindow

        root = tmp_path / "orthanc-cache"
        cache = OrthancSessionCache(root)
        stale_session = cache.create_session()
        stale_dir = cache.session_path(stale_session)
        old_time = time.time() - (8 * 86400)
        os.utime(stale_dir, (old_time, old_time))
        prefs = UserPreferences(orthanc_cache_clear_on_exit=False)
        with (
            patch("echo_personal_tool.infrastructure.profile.orthanc_cache_root", return_value=root),
            patch("echo_personal_tool.presentation.main_window.apply_clinical_theme"),
            patch("echo_personal_tool.presentation.main_window.load_user_preferences", return_value=prefs),
            patch("echo_personal_tool.presentation.main_window.format_results_overlay_html", return_value=""),
            patch.object(mock_controller, "compute_overlay_snapshot", return_value=None),
        ):
            window = MainWindow(controller=mock_controller)

        assert not stale_dir.exists()
        window.close()


class TestActiveOrthancCacheSessions:
    def test_tracks_cache_sessions_backing_open_studies(self, main_window):
        from types import SimpleNamespace

        session = main_window._orthanc_cache.create_session()
        instance_path = main_window._orthanc_cache.save_instance(
            session,
            "1.2.3.4",
            "1.2.3.5",
            "1.2.3.6",
            b"DICM",
        )
        main_window._controller.studies = [
            SimpleNamespace(series=[SimpleNamespace(instances=[SimpleNamespace(path=instance_path)])])
        ]

        assert main_window._active_orthanc_cache_sessions() == {session}

    def test_ignores_local_files_outside_cache(self, main_window, tmp_path):
        from types import SimpleNamespace

        external_file = tmp_path / "local-study.dcm"
        external_file.write_bytes(b"DICM")
        main_window._controller.studies = [
            SimpleNamespace(series=[SimpleNamespace(instances=[SimpleNamespace(path=external_file)])])
        ]

        assert main_window._active_orthanc_cache_sessions() == set()


class TestOpenFolderPath:
    def test_calls_controller(self, main_window):
        main_window.open_folder_path(Path("/tmp/test"))
        main_window._controller.open_folder.assert_called_once()


class TestOnGoldExportRequested:
    def test_calls_controller(self, main_window):
        main_window._on_gold_export_requested("ED", 0, "LV")
        main_window._controller.save_gold_annotation.assert_called_once_with(phase="ED", frame_index=0, chamber="LV")


class TestOnExportMp4Requested:
    """The exported MP4 has to be anonymized like the preview (PR #120 follow-up)."""

    def _instance(self, tmp_path, *, name="clip.dcm", media_format="dicom"):
        from echo_personal_tool.domain.models import InstanceMetadata

        path = tmp_path / name
        path.write_bytes(b"DICM")
        return InstanceMetadata(
            sop_instance_uid="1.2.3",
            series_uid="1.2",
            modality="US",
            number_of_frames=2,
            pixel_spacing=None,
            frame_time_ms=33.3,
            series_description="Cine",
            path=path,
            media_format=media_format,
        )

    def test_dicom_export_carries_a_masker_for_the_exported_file(self, main_window, tmp_path):
        instance = self._instance(tmp_path)
        dest = tmp_path / "out.mp4"
        with (
            patch(
                "echo_personal_tool.presentation.styled_dialogs.styled_save_file",
                return_value=(str(dest), ""),
            ),
            patch("echo_personal_tool.application.workers.mp4_export_worker.Mp4ExportWorker") as worker_cls,
        ):
            main_window._on_export_mp4_requested(instance)

        mask = worker_cls.call_args.kwargs["mask"]
        assert callable(mask)
        frame = np.full((200, 120), 20, dtype=np.uint8)
        frame[0:20, 10:40] = 250  # a burned-in header line
        assert mask(frame)[0:20].max() == 20

    def test_export_without_masking_leaves_the_dicom_pixels_alone(self, main_window, tmp_path):
        instance = self._instance(tmp_path)
        main_window._viewer._phi_filter.set_enabled(False)
        with (
            patch(
                "echo_personal_tool.presentation.styled_dialogs.styled_save_file",
                return_value=(str(tmp_path / "out.mp4"), ""),
            ),
            patch("echo_personal_tool.application.workers.mp4_export_worker.Mp4ExportWorker") as worker_cls,
        ):
            main_window._on_export_mp4_requested(instance)

        assert worker_cls.call_args.kwargs["mask"] is None

    def test_mp4_source_is_copied_when_nothing_is_masked(self, main_window, tmp_path):
        instance = self._instance(tmp_path, name="clip.mp4", media_format="mp4")
        dest = tmp_path / "copy.mp4"
        main_window._viewer._phi_filter.set_enabled(False)
        with (
            patch(
                "echo_personal_tool.presentation.styled_dialogs.styled_save_file",
                return_value=(str(dest), ""),
            ),
            patch("echo_personal_tool.application.workers.mp4_export_worker.Mp4ExportWorker") as worker_cls,
        ):
            main_window._on_export_mp4_requested(instance)

        worker_cls.assert_not_called()
        assert dest.read_bytes() == (tmp_path / "clip.mp4").read_bytes()

    def test_mp4_source_is_re_encoded_when_masking_is_on(self, main_window, tmp_path):
        instance = self._instance(tmp_path, name="clip.mp4", media_format="mp4")
        with (
            patch(
                "echo_personal_tool.presentation.styled_dialogs.styled_save_file",
                return_value=(str(tmp_path / "out.mp4"), ""),
            ),
            patch("echo_personal_tool.application.workers.mp4_export_worker.Mp4ExportWorker") as worker_cls,
        ):
            main_window._on_export_mp4_requested(instance)

        # Masking pixels requires decoding them: the copy shortcut cannot apply.
        assert worker_cls.call_args.kwargs["media_format"] == "mp4"
        assert callable(worker_cls.call_args.kwargs["mask"])


class TestOnHeartRateResult:
    def test_updates_status(self, main_window):
        main_window._on_heart_rate_result(72.0, 0.95, "optical_flow")
        # Should not crash


class TestOnHeartRateFailed:
    def test_updates_status(self, main_window):
        main_window._on_heart_rate_failed("error")


class TestGetCurrentFrameIndex:
    def test_no_instance(self, main_window):
        new_state = replace(main_window._controller.state_manager.snapshot, instance=None)
        main_window._controller.state_manager.snapshot = new_state
        assert main_window._get_current_frame_index() is None

    def test_with_instance(self, main_window):

        mock_inst = MagicMock()
        mock_inst.sop_instance_uid = "test"
        new_state = replace(
            main_window._controller.state_manager.snapshot,
            instance=mock_inst,
            current_frame_index=5,
        )
        main_window._controller.state_manager.snapshot = new_state
        assert main_window._get_current_frame_index() == 5


class TestEnsureDopplerReady:
    def test_no_frame(self, main_window):
        main_window._viewer._current_frame = None
        assert main_window._ensure_doppler_ready() is False

    def test_with_frame(self, main_window):
        main_window._viewer._current_frame = np.zeros((100, 100))
        assert main_window._ensure_doppler_ready() is True


class TestOnSyncDopplerToolAvailability:
    def test_calls_tool_panel(self, main_window):
        with patch.object(main_window._tool_panel, "set_doppler_tool_availability") as mock:
            main_window._sync_doppler_tool_availability()
            mock.assert_called_once()


class TestPersistWindowLevelPreferences:
    def test_saves_preferences(self, main_window):
        with patch("echo_personal_tool.presentation.main_window.save_user_preferences"):
            main_window._persist_window_level_preferences()
            assert main_window._user_preferences.wl_preset == "last_used"


class TestApplyAreaToolMode:
    def test_applies_freehand_mode(self, main_window):
        from echo_personal_tool.infrastructure.user_preferences import UserPreferences

        prefs = UserPreferences(
            theme_mode="dark",
            ui_font_size=13,
            layout_state_json="",
            confirm_reset=False,
            auto_play=False,
            magnetic_snap_enabled=False,
            despeckle_enabled=False,
            length_display_unit="mm",
            pdf_font_size=11,
            results_overlay_custom_position=False,
            language="ru",
            area_tool_mode="freehand",
        )
        with (
            patch("echo_personal_tool.presentation.main_window.apply_clinical_theme"),
            patch("echo_personal_tool.infrastructure.i18n.set_language"),
            patch("echo_personal_tool.presentation.main_window.format_results_overlay_html", return_value=""),
            patch.object(main_window._controller, "compute_overlay_snapshot", return_value=None),
            patch.object(main_window._viewer, "set_area_tool_mode") as mock_set,
        ):
            main_window._apply_user_preferences(prefs)
            mock_set.assert_called_with("freehand")

    def test_applies_click_mode(self, main_window):
        from echo_personal_tool.infrastructure.user_preferences import UserPreferences

        prefs = UserPreferences(
            theme_mode="dark",
            ui_font_size=13,
            layout_state_json="",
            confirm_reset=False,
            auto_play=False,
            magnetic_snap_enabled=False,
            despeckle_enabled=False,
            length_display_unit="mm",
            pdf_font_size=11,
            results_overlay_custom_position=False,
            language="ru",
            area_tool_mode="click",
        )
        with (
            patch("echo_personal_tool.presentation.main_window.apply_clinical_theme"),
            patch("echo_personal_tool.infrastructure.i18n.set_language"),
            patch("echo_personal_tool.presentation.main_window.format_results_overlay_html", return_value=""),
            patch.object(main_window._controller, "compute_overlay_snapshot", return_value=None),
            patch.object(main_window._viewer, "set_area_tool_mode") as mock_set,
        ):
            main_window._apply_user_preferences(prefs)
            mock_set.assert_called_with("click")


class TestPersistenceStatusBlocking:
    def _widgets(self, main_window):
        return (main_window._viewer, main_window._gallery, main_window._tool_panel)

    def test_error_codes_disable_editing_widgets(self, main_window):
        for code in ("io", "conflict", "quota", "identity", "source", "busy", "blocked", "load", "scan", "unsafe_path"):
            main_window._on_persistence_status(code)
            for widget in self._widgets(main_window):
                assert not widget.isEnabled(), code

    def test_ready_and_restored_reenable_editing_widgets(self, main_window):
        main_window._on_persistence_status("io")
        main_window._on_persistence_status("ready")
        for widget in self._widgets(main_window):
            assert widget.isEnabled()
        main_window._on_persistence_status("blocked")
        main_window._on_persistence_status("restored")
        for widget in self._widgets(main_window):
            assert widget.isEnabled()

    def test_loading_disables_editing_widgets(self, main_window):
        main_window._on_persistence_status("loading")
        for widget in self._widgets(main_window):
            assert not widget.isEnabled()

    def test_persistence_blocked_signal_shows_warning(self, main_window):
        connect = main_window._controller.persistence_blocked.connect
        assert connect.called
        slot = connect.call_args[0][0]
        with patch("echo_personal_tool.presentation.main_window.QMessageBox.warning") as warning:
            slot()
        warning.assert_called_once()


class TestOpenFolderRemembersRecents:
    """Э3: the folder dialog starts where the user was and remembers the choice."""

    def test_dialog_starts_at_the_last_recent_folder(self, main_window, tmp_path, monkeypatch):
        from echo_personal_tool.infrastructure.recent_store import RecentStore

        folder = tmp_path / "study"
        folder.mkdir()
        RecentStore().record(folder)

        seen: dict[str, str] = {}

        def fake_dialog(parent=None, title="", directory="", **kwargs):
            seen["directory"] = directory
            return ""

        monkeypatch.setattr(
            "echo_personal_tool.presentation.styled_dialogs.styled_select_directory",
            fake_dialog,
        )
        main_window._open_folder()

        assert seen["directory"] == str(folder)

    def test_missing_recent_folder_falls_back_to_the_startup_preference(self, main_window, tmp_path, monkeypatch):
        from echo_personal_tool.infrastructure.recent_store import RecentStore

        RecentStore().record(tmp_path / "gone")  # does not exist
        seen: dict[str, str] = {}

        def fake_dialog(parent=None, title="", directory="", **kwargs):
            seen["directory"] = directory
            return ""

        monkeypatch.setattr(
            "echo_personal_tool.presentation.styled_dialogs.styled_select_directory",
            fake_dialog,
        )
        main_window._user_preferences.last_opened_folder = str(tmp_path / "fallback")

        main_window._open_folder()

        assert seen["directory"] == str(tmp_path / "fallback")

    def test_chosen_folder_is_recorded_for_next_time(self, main_window, tmp_path, monkeypatch):
        from echo_personal_tool.infrastructure.recent_store import RecentStore

        chosen = tmp_path / "study"
        chosen.mkdir()
        opened: list[Path] = []

        monkeypatch.setattr(
            "echo_personal_tool.presentation.styled_dialogs.styled_select_directory",
            lambda *args, **kwargs: str(chosen),
        )
        monkeypatch.setattr(main_window, "open_folder_path", lambda path: opened.append(path))

        main_window._open_folder()

        assert opened == [chosen]
        assert RecentStore().paths() == [str(chosen)]
        assert main_window._user_preferences.last_opened_folder == str(chosen)

    def test_cancelled_dialog_records_nothing(self, main_window, tmp_path, monkeypatch):
        from echo_personal_tool.infrastructure.recent_store import RecentStore

        called: list = []
        monkeypatch.setattr(
            "echo_personal_tool.presentation.styled_dialogs.styled_select_directory",
            lambda *args, **kwargs: "",
        )
        monkeypatch.setattr(main_window, "open_folder_path", lambda path: called.append(path))

        main_window._open_folder()

        assert called == []
        assert RecentStore().paths() == []


class TestLastSessionSource:
    """Q-05/D-27: "Last session" reopens a folder or the server dialog."""

    def test_folder_open_records_the_disk_source(self, main_window, tmp_path, monkeypatch):
        from echo_personal_tool.infrastructure.user_preferences import (
            SESSION_SOURCE_FOLDER,
            load_user_preferences,
        )

        chosen = tmp_path / "study"
        chosen.mkdir()
        monkeypatch.setattr(
            "echo_personal_tool.presentation.styled_dialogs.styled_select_directory",
            lambda *args, **kwargs: str(chosen),
        )
        monkeypatch.setattr(main_window, "open_folder_path", lambda path: None)

        main_window._open_folder()

        assert main_window._user_preferences.last_session_source == SESSION_SOURCE_FOLDER
        # Persisted, not just in memory: startup reads it back from the store.
        assert load_user_preferences().last_session_source == SESSION_SOURCE_FOLDER

    def test_cancelled_dialog_keeps_the_previous_source(self, main_window, monkeypatch):
        main_window._user_preferences.last_session_source = "server"
        monkeypatch.setattr(
            "echo_personal_tool.presentation.styled_dialogs.styled_select_directory",
            lambda *args, **kwargs: "",
        )

        main_window._open_folder()

        assert main_window._user_preferences.last_session_source == "server"

    def _run_server_dialog(self, main_window, monkeypatch, tmp_path, *, disk_path, result, downloaded):
        """Drive `_open_orthanc_dialog` with a stubbed dialog and clients."""
        dialog = MagicMock()
        dialog.result_data.return_value = result
        dialog.downloaded_studies.return_value = downloaded
        dialog.completed_disk_download_path.return_value = disk_path
        for name in (
            "load_server_settings",
            "make_dicom_web_client",
            "make_dimse_client",
            "make_dicom_query_service",
            "make_dicom_retrieve_service",
            "OrthancStudyDialog",
        ):
            monkeypatch.setattr(f"echo_personal_tool.presentation.main_window.{name}", MagicMock(return_value=dialog))
        monkeypatch.setattr("echo_personal_tool.presentation.ui_animations.exec_animated", lambda *a, **k: 0)
        opened: list = []
        monkeypatch.setattr(main_window, "open_folder_path", lambda path: opened.append(path))
        main_window._open_orthanc_dialog()
        return opened

    def test_cache_download_records_the_server_source(self, main_window, monkeypatch, tmp_path):
        from echo_personal_tool.infrastructure.user_preferences import (
            SESSION_SOURCE_SERVER,
            load_user_preferences,
        )

        self._run_server_dialog(
            main_window,
            monkeypatch,
            tmp_path,
            disk_path=None,
            result=("session-1", "1.2.3"),
            downloaded=[MagicMock(series=[])],
        )

        assert main_window._user_preferences.last_session_source == SESSION_SOURCE_SERVER
        assert load_user_preferences().last_session_source == SESSION_SOURCE_SERVER
        main_window._controller.load_pre_scanned_studies.assert_called_once()

    def test_disk_export_records_the_folder_source(self, main_window, monkeypatch, tmp_path):
        from echo_personal_tool.infrastructure.user_preferences import SESSION_SOURCE_FOLDER

        exported = tmp_path / "exported-study"
        exported.mkdir()
        opened = self._run_server_dialog(
            main_window,
            monkeypatch,
            tmp_path,
            disk_path=exported,
            result=("session-1", "1.2.3"),
            downloaded=[],
        )

        assert opened == [exported]
        assert main_window._user_preferences.last_session_source == SESSION_SOURCE_FOLDER
        assert main_window._user_preferences.last_opened_folder == str(exported)

    def test_cancelled_server_dialog_records_nothing(self, main_window, monkeypatch, tmp_path):
        main_window._user_preferences.last_session_source = "folder"
        self._run_server_dialog(
            main_window,
            monkeypatch,
            tmp_path,
            disk_path=None,
            result=None,
            downloaded=[],
        )

        assert main_window._user_preferences.last_session_source == "folder"

    def test_open_server_dialog_is_the_public_entry_point(self, main_window, monkeypatch):
        calls: list = []
        monkeypatch.setattr(main_window, "_open_orthanc_dialog", lambda: calls.append(True))

        main_window.open_server_dialog()

        assert calls == [True]

    def test_continue_button_reopens_the_last_local_folder(self, main_window, monkeypatch, tmp_path):
        from echo_personal_tool.infrastructure.user_preferences import SESSION_SOURCE_FOLDER

        folder = tmp_path / "last-study"
        folder.mkdir()
        main_window._user_preferences.last_session_source = SESSION_SOURCE_FOLDER
        main_window._user_preferences.last_opened_folder = str(folder)
        main_window._start_page.set_continue_target(SESSION_SOURCE_FOLDER, str(folder))
        opened: list[Path] = []
        monkeypatch.setattr(main_window, "open_folder_path", lambda path: opened.append(path))

        main_window._start_page.continue_button.click()

        assert opened == [folder]
        assert main_window._start_page.continue_button.isEnabled()

    def test_continue_button_reopens_server_loader(self, main_window, monkeypatch):
        from echo_personal_tool.infrastructure.user_preferences import SESSION_SOURCE_SERVER

        main_window._user_preferences.last_session_source = SESSION_SOURCE_SERVER
        main_window._start_page.set_continue_target(SESSION_SOURCE_SERVER)
        calls: list[bool] = []
        monkeypatch.setattr(main_window, "open_server_dialog", lambda: calls.append(True))

        main_window._start_page.continue_button.click()

        assert calls == [True]
