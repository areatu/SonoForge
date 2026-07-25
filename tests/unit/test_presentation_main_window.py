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
    c.playback_config = MagicMock(scroll_debounce_ms=100)
    c.studies = []
    c.get_cached_frames.return_value = []
    c._frame_cache = None
    c._current_study_uid = None
    c._measurement_session = {}
    return c


@pytest.fixture()
def main_window(mock_controller):
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
    with patch("echo_personal_tool.presentation.main_window.apply_clinical_theme"), \
         patch("echo_personal_tool.presentation.main_window.load_user_preferences", return_value=prefs), \
         patch("echo_personal_tool.presentation.main_window.format_results_overlay_html", return_value=""), \
         patch.object(mock_controller, "compute_overlay_snapshot", return_value=None):
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
        with patch("echo_personal_tool.presentation.main_window.save_user_preferences"), \
             patch.object(main_window._viewer, "set_magnetic_snap_enabled") as mock:
            main_window._on_magnetic_snap_changed(True)
            mock.assert_called_with(True)


class TestOnDespeckleChanged:
    def test_updates_viewer(self, main_window):
        with patch("echo_personal_tool.presentation.main_window.save_user_preferences"), \
             patch.object(main_window._viewer, "set_despeckle_enabled") as mock:
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
        with patch("echo_personal_tool.presentation.main_window.format_results_overlay_html", return_value=""), \
             patch.object(main_window._controller, "compute_overlay_snapshot", return_value=None):
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


class TestOpenFolderPath:
    def test_calls_controller(self, main_window):
        main_window.open_folder_path(Path("/tmp/test"))
        main_window._controller.open_folder.assert_called_once()


class TestOnGoldExportRequested:
    def test_calls_controller(self, main_window):
        main_window._on_gold_export_requested("ED", 0, "LV")
        main_window._controller.save_gold_annotation.assert_called_once_with(
            phase="ED", frame_index=0, chamber="LV"
        )


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
