"""Unit tests for presentation/main_window.py."""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from echo_personal_tool.infrastructure.i18n import tr

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
    c.state_manager.loop_state.return_value = (None, None, False)
    # A MagicMock controller would leave measurement_persistence as a truthy
    # auto-mock: MainWindow._sync_measurement_persistence would then open a
    # modal QMessageBox.exec() during construction and hang the test forever.
    # Behave like the real disabled persistence (plain bools, successful ops).
    c.measurement_persistence.enabled = False
    c.measurement_persistence.has_pending_edits = False
    c.measurement_persistence.flush.return_value = True
    c.measurement_persistence.discard_pending.return_value = True
    c.measurement_persistence.discard_unsaved.return_value = True
    c.playback_config = MagicMock(scroll_debounce_ms=100)
    c.studies = []
    c.get_cached_frames.return_value = []
    c._frame_cache = None
    c._current_study_uid = None
    c._measurement_session = {}
    return c


@pytest.fixture()
def main_window(mock_controller, tmp_path, qtbot):
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
            "echo_personal_tool.infrastructure.paths.orthanc_cache_root",
            return_value=tmp_path / "orthanc-cache",
        ),
        patch("echo_personal_tool.presentation.main_window.apply_clinical_theme"),
        patch("echo_personal_tool.presentation.main_window.format_results_overlay_html", return_value=""),
        patch.object(mock_controller, "compute_overlay_snapshot", return_value=None),
    ):
        w = MainWindow(controller=mock_controller, user_preferences=prefs)
    # close() alone retains the C++ tree through signal cycles. A subsequent
    # app-wide theme change then repolishes every old window and can time out.
    qtbot.addWidget(w)
    return w


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

    def test_initial_layout_document(self, main_window):
        from echo_personal_tool.presentation.layout.presets import LayoutConfigV2

        assert isinstance(main_window._layout_document, LayoutConfigV2)
        assert main_window._multiview_mode is False

    def test_reset_layout_to_default(self, main_window):
        from echo_personal_tool.presentation.layout.presets import PRESET_FILMSTRIP, LayoutConfigV2

        main_window._on_layout_preset_selected(PRESET_FILMSTRIP)
        main_window.reset_layout_to_default()
        assert main_window._layout_document == LayoutConfigV2()
        assert main_window._multiview_mode is False

    def test_show_status(self, main_window):
        main_window._show_status("test message")
        assert main_window._system_bar._status_label.text() != ""

    def test_on_instance_selected_non_instance(self, main_window):
        main_window._controller.reset_mock()
        with patch.object(main_window, "_multiview_route_gallery_click") as route:
            main_window._on_instance_selected("not an instance")

        route.assert_not_called()
        assert main_window._controller.mock_calls == [], "something that is not a clip selects nothing"

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

    def test_fps_double_click_retimes_the_current_clip(self, main_window):
        """Double-click on «FPS: …» asks for a value and forwards 1000/fps to the controller."""
        from echo_personal_tool.domain.models.metadata import InstanceMetadata

        instance = InstanceMetadata(
            sop_instance_uid="1.2.3.fps",
            series_uid="series-1",
            modality="US",
            number_of_frames=10,
            pixel_spacing=None,
            frame_time_ms=33.3,
            series_description="",
            path=Path("/tmp/clip.dcm"),
            media_format="dicom",
        )
        main_window._controller.state_manager.snapshot = replace(
            main_window._controller.state_manager.snapshot,
            instance=instance,
            frame_time_ms=33.3,
        )
        with patch("PySide6.QtWidgets.QInputDialog.getDouble", return_value=(60.0, True)) as get_double:
            main_window._on_fps_override_requested()

        get_double.assert_called_once()
        main_window._controller.set_frame_time_override.assert_called_once()
        assert main_window._controller.set_frame_time_override.call_args.args[0] == pytest.approx(16.667, rel=1e-3)

    def test_fps_dialog_cancel_does_nothing(self, main_window):
        with patch("PySide6.QtWidgets.QInputDialog.getDouble", return_value=(60.0, False)):
            main_window._on_fps_override_requested()
        main_window._controller.set_frame_time_override.assert_not_called()

    def test_fps_override_without_a_clip_is_silent(self, main_window):
        main_window._controller.state_manager.snapshot = replace(
            main_window._controller.state_manager.snapshot,
            instance=None,
        )
        with patch("PySide6.QtWidgets.QInputDialog.getDouble") as get_double:
            main_window._on_fps_override_requested()
        get_double.assert_not_called()
        main_window._controller.set_frame_time_override.assert_not_called()

    def test_toggle_fullscreen_shortcut_from_normal(self, main_window):
        main_window.showNormal()
        main_window._gallery.show()
        main_window._tool_panel.show()
        main_window._toggle_fullscreen_shortcut()
        assert not main_window._gallery.isVisible()

    def test_toggle_gallery_shortcut(self, main_window):
        with patch.object(main_window._gallery, "toggle_collapse") as toggle:
            main_window._toggle_gallery_shortcut()

        toggle.assert_called_once_with()

    def test_on_tool_button_requested_catalog_caliper(self, main_window):
        with patch.object(main_window, "_on_measure_action") as mock:
            main_window._on_tool_button_requested("caliper")
            assert mock.call_count == 1
            action, view, phase, extra = mock.call_args.args
            assert view and phase

    def test_on_tool_button_requested_mode_vti_trace(self, main_window):
        calls = []
        main_window._shortcut_handlers["vti_trace"] = lambda: calls.append("vti_trace")
        main_window._on_tool_button_requested("vti_trace")
        assert calls == ["vti_trace"]

    def test_on_tool_button_requested_unknown_button(self, main_window):
        calls = []
        main_window._shortcut_handlers["zoom_fit"] = lambda: calls.append("zoom_fit")
        main_window._on_tool_button_requested("no_such_button")
        assert calls == []


class TestSlotAssembly:
    """The side slots of each preset, read from the table (UI-2 PR-1)."""

    @staticmethod
    def _sides(main_window, document, *, multiview=False):
        from echo_personal_tool.presentation.layout.presets import slot_plan

        plan = slot_plan(document, multiview=multiview)
        return main_window._slot_widget(plan.left), main_window._slot_widget(plan.right)

    def test_default_left_is_gallery(self, main_window):
        from echo_personal_tool.presentation.layout.presets import LayoutConfigV2

        left, right = self._sides(main_window, LayoutConfigV2())
        assert left is main_window._gallery
        assert right is None

    def test_mirrored_preset(self, main_window):
        from echo_personal_tool.presentation.layout.presets import PRESET_MIRRORED, LayoutConfigV2

        left, right = self._sides(main_window, LayoutConfigV2(preset=PRESET_MIRRORED))
        assert left is main_window._tool_panel
        assert right is main_window._gallery

    def test_mirrored_gallery_is_vertical_and_viewer_column_expands(self, main_window):
        from PySide6.QtWidgets import QSizePolicy

        from echo_personal_tool.presentation.layout.presets import PRESET_MIRRORED

        main_window._on_layout_preset_selected(PRESET_MIRRORED)

        gallery = main_window._gallery
        from echo_personal_tool.presentation.thumbnail_gallery import _gallery_width

        expected_gallery_width = _gallery_width(gallery.cell_width())
        assert gallery.isWrapping()
        assert gallery.horizontalScrollBarPolicy().name == "ScrollBarAlwaysOff"
        assert gallery.verticalScrollBarPolicy().name == "ScrollBarAsNeeded"
        assert gallery.minimumWidth() == gallery.maximumWidth() == expected_gallery_width

        column = main_window._viewer_column
        assert column is not None
        assert column.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Expanding
        assert main_window._viewer_stack.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Expanding
        assert main_window._viewer.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Expanding
        viewer_layout = main_window._viewer.layout()
        assert viewer_layout is not None
        assert viewer_layout.stretch(0) == 1
        column_index = main_window._content_layout.indexOf(column)
        assert column_index >= 0
        assert main_window._content_layout.stretch(column_index) == 1

    def test_classic_left_gallery_compacts_at_1366_physical_pixels(self, main_window, monkeypatch):
        """The classic grid yields width on 1366 px displays at 100 % and 150 % DPI."""
        from PySide6.QtWidgets import QApplication

        from echo_personal_tool.presentation.layout.presets import PRESET_CLASSIC

        main_window._layout_document = replace(main_window._layout_document, preset=PRESET_CLASSIC)
        main_window._rebuild_layout()
        gallery = main_window._gallery

        for logical_width, dpr, compact in ((1366, 1.0, True), (911, 1.5, True), (1920, 1.0, False)):
            monkeypatch.setattr(main_window, "devicePixelRatioF", lambda value=dpr: value, raising=False)
            main_window.resize(logical_width, round(768 / dpr))
            main_window.show()
            QApplication.instance().processEvents()

            assert main_window.width() == logical_width
            assert gallery._horizontal_mode is compact
            assert gallery._compact_horizontal_mode is compact
            if compact:
                expected_width = gallery.cell_width() + 2 * gallery.spacing() + 2 * gallery.frameWidth()
                assert gallery.minimumWidth() == gallery.maximumWidth() == expected_width

    def test_tool_buttons_rail_takes_no_side_slot(self, main_window):
        """UI-2 PR-2: the rail is a button placement, not a slot — it never
        steals the right slot the way the version-1 activity bar did."""
        from echo_personal_tool.presentation.layout.presets import LayoutConfigV2

        left, right = self._sides(main_window, LayoutConfigV2(tool_buttons="rail"))
        assert left is main_window._gallery
        assert right is None

    def test_filmstrip_preset(self, main_window):
        from echo_personal_tool.presentation.layout.presets import PRESET_FILMSTRIP, LayoutConfigV2

        left, right = self._sides(main_window, LayoutConfigV2(preset=PRESET_FILMSTRIP))
        assert left is None
        assert right is main_window._tool_panel

    def test_multiview_right(self, main_window):
        from echo_personal_tool.presentation.layout.presets import LayoutConfigV2

        _left, right = self._sides(main_window, LayoutConfigV2(), multiview=True)
        assert right is main_window._tool_panel


class TestReleaseContentLayout:
    def test_clears_layout(self, main_window):
        main_window._release_content_layout()
        assert main_window._content_layout.count() == 0


class TestTeardownBottomGallery:
    def test_noop_when_none(self, main_window):
        main_window._bottom_container = None
        widgets_before = main_window._root_layout.count()

        main_window._teardown_bottom_gallery()  # Should not crash

        assert main_window._bottom_container is None
        assert main_window._root_layout.count() == widgets_before, "nothing was removed from the layout"


class TestLoadLayoutDocument:
    def test_empty_string(self, main_window):
        from echo_personal_tool.presentation.layout.presets import LayoutConfigV2

        main_window._user_preferences.layout_state_v2_json = ""
        main_window._user_preferences.layout_state_json = ""
        assert main_window._load_layout_document() == LayoutConfigV2()

    def test_invalid_json(self, main_window):
        from echo_personal_tool.presentation.layout.presets import LayoutConfigV2

        main_window._user_preferences.layout_state_v2_json = ""
        main_window._user_preferences.layout_state_json = "not json"
        assert main_window._load_layout_document() == LayoutConfigV2()


class TestLayoutSelection:
    def test_selects_preset(self, main_window):
        from echo_personal_tool.presentation.layout.presets import PRESET_MIRRORED

        main_window._on_layout_preset_selected(PRESET_MIRRORED)
        assert main_window._layout_document.preset == PRESET_MIRRORED


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
        with (
            patch.object(main_window, "_show_status") as show_status,
            patch.object(main_window, "_sync_results_overlay") as sync_overlay,
            patch.object(main_window._viewer, "_refresh_frame_overlays") as refresh_overlays,
        ):
            main_window._on_contour_completed("not a contour")

        show_status.assert_not_called()
        sync_overlay.assert_not_called()
        refresh_overlays.assert_not_called()

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
            patch(
                "echo_personal_tool.domain.services.planimeter_formatter.format_planimeter_overlay_line",
                return_value="Area 4.2 cm²",
            ) as format_line,
            patch.object(main_window, "_show_status") as show_status,
            patch.object(main_window, "_sync_results_overlay") as sync_overlay,
            patch.object(main_window._viewer, "_refresh_frame_overlays") as refresh_overlays,
        ):
            main_window._on_contour_completed(contour)

        format_line.assert_called_once_with(contour, None, spacing_calibrated=False)
        show_status.assert_called_once_with(tr("status.ready_done", line="Area 4.2 cm²"))
        refresh_overlays.assert_called_once_with()
        sync_overlay.assert_called_once()


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
        with (
            patch.object(main_window._presenter, "forward_state") as forward_state,
            patch.object(main_window, "_sync_results_overlay") as sync_overlay,
            patch.object(main_window, "_update_properties_panel") as update_panel,
        ):
            main_window._on_state_changed("not a ViewerState")

        forward_state.assert_not_called()
        sync_overlay.assert_not_called()
        update_panel.assert_not_called()


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

        assert main_window._mmode_widget is None, "a column without a widget must not create one"

    def test_the_column_goes_to_the_widget_only_while_mmode_is_active(self, main_window):
        widget = MagicMock()
        main_window._mmode_widget = widget
        column = np.zeros(256)

        main_window._mmode_active = False
        main_window._on_mmode_column_ready(column, 0)
        widget.on_new_column.assert_not_called()

        main_window._mmode_active = True
        main_window._on_mmode_column_ready(column, 1)
        widget.on_new_column.assert_called_once_with(column)

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
        main_window._controller.get_cached_frames.reset_mock()

        main_window._on_mmode_line_completed((10, 20), (100, 200))

        main_window._controller.get_cached_frames.assert_not_called()  # nothing to recalculate without a widget

    def test_with_widget_and_cached_frames(self, main_window):
        main_window._mmode_widget = MagicMock()
        main_window._mmode_active = True
        main_window._controller.get_cached_frames.return_value = [np.zeros((256, 256))]
        main_window._on_mmode_line_completed((10, 20), (100, 200))
        main_window._mmode_widget.recalculate_from_frames.assert_called_once()


class TestOnTeichholzEdComplete:
    def test_less_than_3_measurements(self, main_window):
        with patch.object(main_window, "_show_status") as show_status:
            main_window._on_teichholz_ed_complete([MagicMock(), MagicMock()])

        show_status.assert_not_called()

    def test_none_values(self, main_window):
        m1 = MagicMock(value_mm=None)
        m2 = MagicMock(value_mm=40.0)
        m3 = MagicMock(value_mm=10.0)
        with patch.object(main_window, "_show_status") as show_status:
            main_window._on_teichholz_ed_complete([m1, m2, m3])

        show_status.assert_not_called()

    def test_three_measurements_report_the_ed_volume_and_wall_ratio(self, main_window):
        from echo_personal_tool.domain.calculations.teichholz_mmode import compute_teichholz_from_mmode

        calipers = [MagicMock(value_mm=10.0), MagicMock(value_mm=50.0), MagicMock(value_mm=10.0)]
        expected = compute_teichholz_from_mmode(
            ivsd_mm=10.0, lvidd_mm=50.0, lvpwd_mm=10.0, height_cm=None, weight_kg=None
        )
        with patch.object(main_window, "_show_status") as show_status:
            main_window._on_teichholz_ed_complete(calipers)

        show_status.assert_called_once()
        message = show_status.call_args.args[0]
        assert f"{expected.edv_ml:.0f}" in message
        assert f"{expected.rwt:.2f}" in message


class TestOnTeichholzEsComplete:
    def test_none_value(self, main_window):
        m = MagicMock(value_mm=None)
        with patch.object(main_window, "_show_status") as show_status:
            main_window._on_teichholz_es_complete(m)

        show_status.assert_not_called()

    def test_no_widget(self, main_window):
        main_window._mmode_widget = None
        m = MagicMock(value_mm=25.0)
        with patch.object(main_window, "_show_status") as show_status:
            main_window._on_teichholz_es_complete(m)

        show_status.assert_not_called()


class TestCloseEvent:
    def test_closes_when_mmode_inactive(self, main_window):
        from PySide6.QtGui import QCloseEvent

        main_window._mmode_active = False
        event = QCloseEvent()
        main_window.closeEvent(event)

        assert event.isAccepted(), "with M-mode off the window really closes"
        main_window._controller.measurement_persistence.close.assert_called_once_with()

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

    def test_unsaved_cancel_keeps_window_open_without_shutdown(self, main_window):
        from PySide6.QtGui import QCloseEvent

        persistence = main_window._controller.measurement_persistence
        persistence.flush.return_value = False
        buttons = [MagicMock(name="save"), MagicMock(name="discard"), MagicMock(name="cancel")]
        box = MagicMock()
        box.addButton.side_effect = buttons
        box.clickedButton.return_value = buttons[2]
        try:
            with patch("echo_personal_tool.presentation.main_window.QMessageBox", return_value=box):
                event = QCloseEvent()
                main_window.closeEvent(event)
            assert not event.isAccepted()
            persistence.close.assert_not_called()
            persistence.discard_unsaved.assert_not_called()
        finally:
            persistence.flush.return_value = True

    def test_unsaved_discard_lets_the_app_close(self, main_window):
        from PySide6.QtGui import QCloseEvent

        persistence = main_window._controller.measurement_persistence
        persistence.flush.return_value = False
        buttons = [MagicMock(name="save"), MagicMock(name="discard"), MagicMock(name="cancel")]
        box = MagicMock()
        box.addButton.side_effect = buttons
        box.clickedButton.return_value = buttons[1]
        persistence.close.side_effect = lambda: True  # dirty already discarded: shutdown succeeds
        try:
            with patch("echo_personal_tool.presentation.main_window.QMessageBox", return_value=box):
                event = QCloseEvent()
                main_window.closeEvent(event)
            assert event.isAccepted()
            persistence.discard_unsaved.assert_called_once_with()
            persistence.close.assert_called_once_with()
        finally:
            persistence.flush.return_value = True
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
            patch("echo_personal_tool.infrastructure.paths.orthanc_cache_root", return_value=root),
            patch("echo_personal_tool.presentation.main_window.apply_clinical_theme"),
            patch("echo_personal_tool.presentation.main_window.format_results_overlay_html", return_value=""),
            patch.object(mock_controller, "compute_overlay_snapshot", return_value=None),
        ):
            window = MainWindow(controller=mock_controller, user_preferences=prefs)

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

    @staticmethod
    def _whole_file_range_dialog():
        """Patch the frame-range dialog so the export covers the whole file."""
        from PySide6.QtWidgets import QDialog

        return patch(
            "echo_personal_tool.presentation.frame_range_export_dialog.FrameRangeExportDialog",
            **{
                "return_value.exec.return_value": QDialog.DialogCode.Accepted,
                "return_value.frame_range.return_value": None,
            },
        )

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
            self._whole_file_range_dialog(),
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
        assert mask(frame)[0:20].max() == 0

    def test_export_without_masking_leaves_the_dicom_pixels_alone(self, main_window, tmp_path):
        instance = self._instance(tmp_path)
        main_window._viewer._phi_filter.set_enabled(False)
        with (
            self._whole_file_range_dialog(),
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
            self._whole_file_range_dialog(),
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
            self._whole_file_range_dialog(),
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

    def test_mp4_export_failure_dialog_does_not_display_error_code_payload(self, main_window):
        with patch("echo_personal_tool.presentation.main_window.QMessageBox.warning") as warning:
            main_window._on_mp4_export_failed("PHI_SECRET /private/patient/source.mp4")

        message = warning.call_args.args[2]
        assert "PHI_SECRET" not in message
        assert "/private/patient/source.mp4" not in message
        assert "MP4" in message


class TestOnHeartRateResult:
    def test_updates_status(self, main_window):
        with (
            patch.object(main_window, "_show_status") as show_status,
            patch.object(main_window._viewer, "set_results_overlay") as set_overlay,
        ):
            main_window._on_heart_rate_result(72.0, 0.95, "optical_flow")

        show_status.assert_called_once_with("HR: 72 BPM (Optical Flow, conf 95%)")
        main_window._controller.record_heart_rate_estimate.assert_called_once_with(72.0, "optical_flow")
        assert set_overlay.call_args.args[0].endswith("HR: 72 BPM"), "the estimate joins the results overlay"
        # Should not crash


class TestOnHeartRateFailed:
    def test_updates_status(self, main_window):
        with patch.object(main_window, "_show_status") as show_status:
            main_window._on_heart_rate_failed("error")

        show_status.assert_called_once_with("HR estimation failed: error")


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
            assert not hasattr(main_window._user_preferences, "wl_preset")
            window = main_window._tool_panel.controls.window_slider.slider().value()
            assert main_window._user_preferences.wl_window == window


class TestStatusBarTokens:
    """UI-0 PR-3: the permanent status-bar labels are painted from the tokens.

    The «Только для исследований» warning and the version label used to carry
    raw colours (``#ff9800``, ``#999``) inside :meth:`MainWindow.__init__`, so
    they kept the same colour in every theme. They now follow ``state.warn``
    and ``text.3`` of the active theme, like the icons of the system bar.
    """

    def test_labels_take_the_tokens_of_the_active_theme(self, main_window, monkeypatch):
        from echo_personal_tool.presentation import dark_theme

        # The theme *mode* is switched, not the application-wide stylesheet:
        # the labels read the tokens of the mode, while a changed sheet would
        # make the suite repolish every widget it keeps alive (conftest pins
        # the sheet back for exactly that reason).
        monkeypatch.setattr(dark_theme, "_current_theme_mode", "graphite")
        main_window.apply_status_bar_tokens()

        tokens = dark_theme.get_theme_tokens()
        assert tokens["state.warn"] in main_window._research_warning.styleSheet()
        assert tokens["text.3"] in main_window._version_label.styleSheet()

    def test_a_theme_change_repaints_the_labels(self, main_window):
        """The window repaints the labels on the theme-change path.

        The neighbours of this test exercise ``_apply_user_preferences`` with
        the theme call and the language replaced by doubles; the question here
        is only the call itself — the colours follow the theme in
        ``tests/unit/test_shell_tokens.py``, where the real facade runs.
        """
        from dataclasses import replace

        with (
            patch("echo_personal_tool.presentation.main_window.apply_clinical_theme"),
            patch("echo_personal_tool.infrastructure.i18n.set_language"),
            patch("echo_personal_tool.presentation.main_window.format_results_overlay_html", return_value=""),
            patch.object(main_window._controller, "compute_overlay_snapshot", return_value=None),
            patch.object(main_window, "apply_status_bar_tokens") as repaint,
        ):
            main_window._apply_user_preferences(replace(main_window._user_preferences, theme_mode="graphite"))

        repaint.assert_called_once_with()


class TestSettingsApplyDoesNotFreeze:
    """Item 14 of the 2026-11-06 list: «Применить» must not repaint the world.

    The settings dialog applies the *whole* preferences object every time, so
    every apply used to rebuild the global stylesheet and re-polish the shell
    even when the applied values were identical to the running ones.  On Win10
    that is the half-second freeze the owner reports.
    """

    def test_an_apply_without_theme_changes_does_not_reapply_the_theme(self, main_window):
        from dataclasses import replace

        with (
            patch("echo_personal_tool.presentation.main_window.apply_clinical_theme") as theme,
            patch("echo_personal_tool.infrastructure.i18n.set_language"),
            patch("echo_personal_tool.presentation.main_window.format_results_overlay_html", return_value=""),
            patch.object(main_window._controller, "compute_overlay_snapshot", return_value=None),
            patch.object(main_window._viewer, "apply_user_preferences"),
        ):
            # The window already applied the theme for exactly these values in
            # its own ``__init__``; an apply that repeats them has nothing to do.
            preferences = replace(main_window._user_preferences)
            main_window._apply_user_preferences(preferences)
            theme.assert_not_called()
            main_window._apply_user_preferences(replace(preferences))
            theme.assert_not_called()

            changed = replace(preferences, ui_font_size=preferences.ui_font_size + 1)
            main_window._apply_user_preferences(changed)
            assert theme.call_count == 1, "a real theme change must still go through"
            main_window._apply_user_preferences(replace(changed))
            assert theme.call_count == 1, "and only once"


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


class TestApplyMagneticSnap:
    def _apply(self, main_window, enabled: bool) -> None:
        with (
            patch("echo_personal_tool.presentation.main_window.apply_clinical_theme"),
            patch("echo_personal_tool.infrastructure.i18n.set_language"),
            patch("echo_personal_tool.presentation.main_window.format_results_overlay_html", return_value=""),
            patch.object(main_window._controller, "compute_overlay_snapshot", return_value=None),
        ):
            main_window._apply_user_preferences(replace(main_window._user_preferences, magnetic_snap_enabled=enabled))

    def test_the_preference_reaches_the_viewer_both_ways(self, main_window):
        self._apply(main_window, True)
        assert main_window._viewer.magnetic_snap_enabled() is True

        self._apply(main_window, False)
        assert main_window._viewer.magnetic_snap_enabled() is False

    def test_the_tool_panel_checkbox_follows_the_preference(self, main_window):
        checkbox = main_window._tool_panel.controls._magnetic_snap_check

        self._apply(main_window, True)
        assert checkbox.isChecked()

        self._apply(main_window, False)
        assert not checkbox.isChecked()


class TestPersistenceStatusBlocking:
    def _widgets(self, main_window):
        return (main_window._viewer, main_window._gallery, main_window._tool_panel)

    def test_error_codes_keep_editing_widgets_enabled(self, main_window):
        # Office-style flow: a failed write reports itself in the status bar
        # but never locks the viewer/gallery/tools (2026-10-30).
        for code in ("io", "conflict", "quota", "identity", "source", "busy", "blocked", "load", "scan", "unsafe_path"):
            main_window._on_persistence_status(code)
            for widget in self._widgets(main_window):
                assert widget.isEnabled(), code

    def test_ready_and_restored_reenable_editing_widgets(self, main_window):
        main_window._on_persistence_status("loading")
        main_window._on_persistence_status("ready")
        for widget in self._widgets(main_window):
            assert widget.isEnabled()
        main_window._on_persistence_status("loading")
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


class TestSettleUnsavedMeasurements:
    """Office-style save/don't-save prompt replaces the hard navigation block."""

    def _prompt_click(self, main_window, button_index, flush_results):
        """Run the prompt with a scripted button click and flush outcomes."""
        buttons = [MagicMock(name=f"btn{i}") for i in range(3)]
        box = MagicMock()
        box.addButton.side_effect = buttons
        box.clickedButton.return_value = buttons[button_index]
        flush = main_window._controller.measurement_persistence.flush
        flush.side_effect = flush_results
        with patch("echo_personal_tool.presentation.main_window.QMessageBox", return_value=box):
            result = main_window._settle_unsaved_measurements()
        flush.side_effect = None
        flush.return_value = True
        return result

    def test_successful_flush_skips_prompt(self, main_window):
        with patch("echo_personal_tool.presentation.main_window.QMessageBox") as box_cls:
            assert main_window._settle_unsaved_measurements() is True
        assert not box_cls.called

    def test_save_button_retries_and_proceeds(self, main_window):
        # First flush fails (prompt shown), second succeeds after «Save».
        assert self._prompt_click(main_window, 0, [False, True]) is True
        main_window._controller.measurement_persistence.discard_unsaved.assert_not_called()

    def test_save_button_failure_stays(self, main_window):
        # Save was requested but the write still fails: keep the study put.
        assert self._prompt_click(main_window, 0, [False, False]) is False
        main_window._controller.measurement_persistence.discard_unsaved.assert_not_called()

    def test_discard_button_proceeds_without_saving(self, main_window):
        assert self._prompt_click(main_window, 1, [False]) is True
        main_window._controller.measurement_persistence.discard_unsaved.assert_called_once_with()

    def test_cancel_button_blocks_navigation(self, main_window):
        assert self._prompt_click(main_window, 2, [False]) is False
        main_window._controller.measurement_persistence.discard_unsaved.assert_not_called()


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
        """Drive `_open_orthanc_dialog` with a stubbed dialog and clients.

        The dialog and its clients are built by ``DownloadCoordinator`` (N-08);
        ``_open_orthanc_dialog`` on the window is the thin delegation.
        """
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
            monkeypatch.setattr(
                f"echo_personal_tool.presentation.download_coordinator.{name}", MagicMock(return_value=dialog)
            )
        monkeypatch.setattr(
            "echo_personal_tool.presentation.theme.dialog_outline.ensure_dialog_outline", lambda *a: None
        )
        dialog.batch_snapshot.return_value.background_requested = False
        dialog.open.side_effect = lambda: dialog.finished.connect.call_args.args[0](0)
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
        monkeypatch.setattr(main_window, "_open_orthanc_dialog", lambda **kwargs: calls.append(kwargs))

        main_window.open_server_dialog()

        assert calls == [{"preselect_study_uid": None}]

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


class TestProtocolUi:
    """TP-3 PR-3: карточка протокола, полоса шага под снимком, Esc и S."""

    @staticmethod
    def _start(main_window, protocol_id: str = "lv_linear") -> None:
        from echo_personal_tool.domain.protocols import StudyProjection

        main_window._controller.study_projection.return_value = StudyProjection()
        main_window.protocol.select(protocol_id)

    def test_protocol_start_puts_the_step_bar_under_the_snapshot(self, main_window):
        self._start(main_window)
        bar = main_window.protocol.step_bar
        assert bar is not None
        assert bar.is_active() is True
        assert main_window._viewer_column.part("bottom") is bar
        assert bar._counter.text() == "1 / 2"
        assert bar._instruction.text().startswith("ЛЖ-диастола")
        assert main_window._tool_panel.measure._protocol_card._progress.text() == "0 / 2"

    def test_palette_protocol_action_starts_the_session(self, main_window):
        """The «Протоколы» group of Ctrl+K dispatches through ``_run_command`` (TP-6)."""
        from echo_personal_tool.domain.protocols import StudyProjection

        main_window._controller.study_projection.return_value = StudyProjection()
        main_window._run_command("protocol:lv_linear")
        assert main_window.protocol.session.active is True
        assert main_window.protocol.session.active_protocol_id == "lv_linear"

    def test_escape_stops_the_protocol_and_hides_the_bar(self, main_window):
        self._start(main_window)
        bar = main_window.protocol.step_bar
        main_window._cancel_active_tool()
        assert main_window.protocol.session.active is False
        assert bar.is_active() is False
        assert main_window._tool_panel.measure._protocol_card._progress.text() == ""

    def test_escape_without_a_protocol_cancels_the_viewer_tool(self, main_window, monkeypatch):
        calls: list[bool] = []
        monkeypatch.setattr(main_window._viewer, "cancel_active_tool", lambda: calls.append(True))
        main_window._cancel_active_tool()
        assert calls == [True]

    def test_s_skips_the_armed_step_of_a_running_protocol(self, main_window):
        self._start(main_window)
        session = main_window.protocol.session
        main_window.protocol.skip()
        assert session.progress.steps[0].state.value == "skipped"

    def test_study_change_stops_the_protocol(self, main_window):
        self._start(main_window)
        main_window._on_reset_measurements_requested()
        assert main_window.protocol.session.active is False


class TestUaProtocolAcceptance:
    """UA-07 / UA-08 (спека UI-redesign §11, матрица приёмки): полоса шага.

    UA-07 — шаг Симпсона: взвести, обвести, Enter → полоса под снимком,
    уведомление автоперехода в полосе ≥ 2 с и ничего не всплывает поверх
    снимка.  UA-08 — протокол остановлен: полосы нет, изображение выросло
    на её высоту.  Обе проверки требуют показанного окна: видимость и
    геометрия детей считаются только после expose.
    """

    @staticmethod
    def _shown(main_window, qtbot) -> None:
        main_window.resize(1280, 800)
        main_window.show()
        qtbot.waitExposed(main_window)

    @staticmethod
    def _start_simpson(main_window) -> None:
        from echo_personal_tool.domain.protocols import StudyProjection

        main_window._controller.study_projection.return_value = StudyProjection()
        main_window.protocol.select("simpson_biplane")

    def test_ua07_auto_advance_notification_is_kept_in_the_bar(self, main_window, qtbot):
        from echo_personal_tool.domain.protocols import ProjectionValue, StudyProjection
        from echo_personal_tool.presentation.protocol_step_bar import NOTIFICATION_MIN_MS

        self._shown(main_window, qtbot)
        self._start_simpson(main_window)
        bar = main_window.protocol.step_bar

        # Взвести шаг 0 — как по клику в карточке протокола.
        main_window.protocol.activate_step(0)
        assert main_window.protocol.session.runner.armed_index == 0

        # «Обвести»: КДО 4-кам зафиксирован, проекция исследования закрыла шаг.
        main_window._controller.study_projection.return_value = StudyProjection(
            values={"lv.edv_a4c": ProjectionValue(value=118.0, origin="simpson_biplane")}
        )
        main_window.protocol.study_projection_changed()

        # Уведомление автоперехода живёт в полосе и держится ≥ 2 с (Q-07).
        assert bar.notification_active() is True, "уведомление должно жить в полосе, а не мигнуть"
        assert bar._notify_timer.isActive() is True
        assert bar._notify_timer.interval() >= NOTIFICATION_MIN_MS
        assert bar._notification.text().startswith("✓")

        # Уведомление живёт не меньше minimum_ms «по часам», а не «по одному
        # wait»: медленный цикл событий CI не должен обрывать проверку раньше
        # срока. 10 % запаса — Qt-таймеры грубые и могут сработать чуть раньше.
        shown_at = time.monotonic()
        qtbot.waitUntil(lambda: not bar.notification_active(), timeout=NOTIFICATION_MIN_MS + 5000)
        lived_ms = (time.monotonic() - shown_at) * 1000
        assert lived_ms >= NOTIFICATION_MIN_MS * 0.9, (
            f"уведомление не должно исчезать раньше minimum_ms (жило {lived_ms:.0f} мс)"
        )

    def test_ua07_step_bar_sits_under_the_snapshot_not_over_it(self, main_window, qtbot):
        from echo_personal_tool.presentation.protocol_step_bar import ProtocolStepBar

        self._shown(main_window, qtbot)
        self._start_simpson(main_window)
        bar = main_window.protocol.step_bar
        column = main_window._viewer_column
        center = column.part("center")

        assert column.part("bottom") is bar
        assert bar.isVisible() is True
        # Полоса занимает слот под снимком: её верх не выше низа изображения.
        assert bar.geometry().top() >= center.geometry().bottom()
        # Поверх снимка ничего не всплывает: у вьюера нет протокольных детей.
        assert main_window._viewer.findChildren(ProtocolStepBar) == []

    def test_ua08_stopping_the_protocol_returns_its_height_to_the_image(self, main_window, qtbot):

        self._shown(main_window, qtbot)
        self._start_simpson(main_window)
        bar = main_window.protocol.step_bar
        center = main_window._viewer_column.part("center")

        assert bar.isVisible() is True
        qtbot.waitUntil(lambda: bar.height() > 0)
        image_before = center.height()
        bar_height = bar.height()
        assert bar_height > 0

        main_window.protocol.stop_requested()
        assert main_window.protocol.session.active is False
        qtbot.waitUntil(lambda: not bar.isVisible())

        # Изображение вернуло себе высоту полосы.
        qtbot.waitUntil(lambda: center.height() >= image_before + bar_height - 1)
        assert center.height() > image_before


class TestReportMode:
    """UI-4 PR-1: «Изображения | Отчёт» — режим вкладки с листом A4 (UA-09)."""

    @staticmethod
    def _study(main_window) -> None:
        """An empty but well-formed study snapshot for the report provider."""
        main_window._controller.compute_study_snapshot.return_value = None
        main_window._controller.patient_metric_sources.return_value = ("unset", "unset")

    def test_report_page_is_built_lazily_and_reused(self, main_window):
        self._study(main_window)
        assert main_window.report_coordinator.page is None
        main_window.report_coordinator.set_mode(True)
        page = main_window.report_coordinator.page
        assert page is not None
        main_window.report_coordinator.set_mode(False)
        main_window.report_coordinator.set_mode(True)
        assert main_window.report_coordinator.page is page

    def test_entering_the_mode_shows_the_sheet_of_the_active_tab(self, main_window):
        self._study(main_window)
        assert main_window._main_stack.currentWidget() is main_window._content_widget
        main_window.report_coordinator.set_mode(True)
        assert main_window._tabs.active.report_mode is True
        assert main_window._system_bar.report_mode() is True
        assert main_window._main_stack.currentWidget() is main_window.report_coordinator.page
        preview = main_window.report_coordinator.page.preview
        assert preview.page_count >= 1
        assert preview.pdf_bytes[:5] == b"%PDF-"

    def test_back_to_images_restores_the_content_surface(self, main_window):
        self._study(main_window)
        viewer = main_window._viewer
        shown = main_window._viewer_stack.currentWidget()
        main_window.report_coordinator.set_mode(True)
        main_window.report_coordinator.set_mode(False)
        assert main_window._main_stack.currentWidget() is main_window._content_widget
        assert main_window._system_bar.report_mode() is False
        assert main_window._viewer is viewer
        assert main_window._viewer_stack.currentWidget() is shown

    def test_ctrl_r_shortcut_toggles_the_mode(self, main_window):
        self._study(main_window)
        assert "toggle_report_mode" in main_window._shortcut_handlers
        main_window.report_coordinator.toggle_mode()
        assert main_window.report_coordinator.mode_active() is True
        main_window.report_coordinator.toggle_mode()
        assert main_window.report_coordinator.mode_active() is False

    def test_the_patient_line_switch_drives_the_mode(self, main_window):
        self._study(main_window)
        main_window._system_bar._btn_mode_report.click()
        assert main_window._main_stack.currentWidget() is main_window.report_coordinator.page
        main_window._system_bar._btn_mode_images.click()
        assert main_window._main_stack.currentWidget() is main_window._content_widget

    def test_the_mode_belongs_to_its_tab(self, main_window):
        from echo_personal_tool.application.tab_session import TAB_ORIGIN_EMPTY

        self._study(main_window)
        first = main_window._tabs.active
        main_window.report_coordinator.set_mode(True)
        other = main_window._tabs.open_tab(origin=TAB_ORIGIN_EMPTY, activate=True)
        main_window._update_main_stack()
        assert other.report_mode is False
        assert main_window._main_stack.currentWidget() is main_window._content_widget
        assert main_window._system_bar.report_mode() is False
        main_window._tabs.activate(first.tab_id)
        main_window._update_main_stack()
        assert main_window._main_stack.currentWidget() is main_window.report_coordinator.page
        assert main_window._system_bar.report_mode() is True

    def test_measure_link_switches_to_images_and_arms_the_step(self, main_window):
        """UA-12: «измерить» у незаполненного раздела взводит шаг протокола."""
        from echo_personal_tool.domain.protocols import StudyProjection

        self._study(main_window)
        main_window._controller.study_projection.return_value = StudyProjection()
        main_window.report_coordinator.set_mode(True)
        item = main_window.report_coordinator.page.sections.sections[0].items[0]

        main_window.report_coordinator.page.sections.measure_requested.emit(item.protocol_id, item.step_index)

        assert main_window.report_coordinator.mode_active() is False
        session = main_window.protocol.session
        assert session is not None
        assert session.active_protocol_id == item.protocol_id
        assert session.progress.current_index == item.step_index

    def test_an_armed_protocol_step_survives_the_round_trip(self, main_window):
        """UA-09: клип, кадр и взведённый шаг не трогает переключение режима."""
        self._study(main_window)
        TestProtocolUi._start(main_window)
        session = main_window.protocol.session
        assert session.active is True
        armed = main_window.protocol.armed_index
        main_window.report_coordinator.set_mode(True)
        main_window.report_coordinator.set_mode(False)
        assert main_window.protocol.session is session
        assert session.active is True
        assert main_window.protocol.armed_index == armed
        assert main_window.protocol.step_bar.is_active() is True


class TestReportPhrases:
    """UI-4 PR-3: the phrases column and the per-tab conclusion draft."""

    def test_a_phrase_reaches_the_document_the_sheet_renders(self, main_window):
        from echo_personal_tool.domain.services.report_phrases import PHRASES

        TestReportMode._study(main_window)
        main_window.report_coordinator.set_mode(True)
        page = main_window.report_coordinator.page
        phrase = next(item for item in PHRASES if item.id == "builtin.lv.no_dilation")

        page.phrases.insert_phrase(phrase)

        assert main_window._tabs.active.report_conclusion == page.conclusion
        assert page.conclusion.startswith(phrase.text("ru"))
        assert page.preview.refresh_now() is True
        assert page.preview.document is not None
        assert page.preview.document.patient.conclusion == page.conclusion

    def test_the_draft_belongs_to_its_tab(self, main_window):
        from echo_personal_tool.application.tab_session import TAB_ORIGIN_EMPTY

        TestReportMode._study(main_window)
        main_window.report_coordinator.set_mode(True)
        page = main_window.report_coordinator.page
        first = main_window._tabs.active

        page.phrases._editor.setPlainText("Черновик первого исследования")
        assert first.report_conclusion == "Черновик первого исследования"

        other = main_window._tabs.open_tab(origin=TAB_ORIGIN_EMPTY, activate=True)
        main_window._update_main_stack()
        assert other.report_conclusion == ""

        main_window.report_coordinator.set_mode(True)
        assert page.conclusion == ""

        main_window._tabs.activate(first.tab_id)
        main_window._update_main_stack()
        assert page.conclusion == "Черновик первого исследования"

    def test_the_window_owns_the_phrase_store(self, main_window, monkeypatch, tmp_path):
        from echo_personal_tool.infrastructure.report_phrase_store import PhraseStore

        store = PhraseStore(tmp_path / "phrases.json")
        monkeypatch.setattr(main_window.report_coordinator, "phrase_store", lambda: store)
        TestReportMode._study(main_window)

        main_window.report_coordinator.set_mode(True)

        assert main_window.report_coordinator.page.phrases.store is store


class TestReportConclusionAutofill:
    """The conclusion button reads a fresh snapshot and keeps the managed block per tab."""

    @staticmethod
    def _study(main_window, ef: float = 60.0) -> None:
        from echo_personal_tool.domain.models.measurements import LvefResult, MeasurementSnapshot

        main_window._controller.compute_study_snapshot.return_value = MeasurementSnapshot(
            lvef=LvefResult(lvef_percent=ef, method="simpson_biplan")
        )
        main_window._controller.patient_metric_sources.return_value = ("unset", "unset")
        main_window._tabs.active.report_patient_fields.update(sex="M", age="45")

    def test_the_button_appends_a_qualitative_draft_and_remembers_the_block(self, main_window) -> None:
        self._study(main_window)
        main_window.report_coordinator.set_mode(True)
        page = main_window.report_coordinator.page
        tab = main_window._tabs.active
        page.phrases._editor.setPlainText("Ручной текст.")

        page.phrases.conclusion_autofill_button.click()

        assert page.conclusion.startswith("Ручной текст.\n\n• ")
        assert "Simpson" in page.conclusion
        assert tab.report_conclusion == page.conclusion
        assert tab.report_generated_conclusion
        assert tab.report_generated_conclusion in page.conclusion
        assert page.preview.refresh_now() is True
        assert page.preview.document.patient.conclusion == page.conclusion

        before = page.conclusion
        page.phrases.conclusion_autofill_button.click()
        assert page.conclusion == before

    def test_measurements_update_only_the_unedited_generated_block(self, main_window) -> None:
        self._study(main_window, ef=60.0)
        main_window.report_coordinator.set_mode(True)
        page = main_window.report_coordinator.page
        tab = main_window._tabs.active
        page.phrases._editor.setPlainText("Ручной текст.")
        page.phrases.conclusion_autofill_button.click()
        first_block = tab.report_generated_conclusion

        self._study(main_window, ef=25.0)
        page.phrases.conclusion_autofill_button.click()

        assert page.conclusion.startswith("Ручной текст.\n\n• ")
        assert first_block not in page.conclusion
        assert tab.report_generated_conclusion in page.conclusion
        assert "Выраженное снижение" in page.conclusion

    def test_finished_version_and_tab_switch_keep_the_autofill_state_isolated(self, main_window) -> None:
        from echo_personal_tool.application.tab_session import TAB_ORIGIN_EMPTY

        self._study(main_window)
        main_window.report_coordinator.set_mode(True)
        page = main_window.report_coordinator.page
        first = main_window._tabs.active
        page.phrases.conclusion_autofill_button.click()
        assert first.report_generated_conclusion

        main_window.report_coordinator.set_finished(True)
        frozen = page.conclusion
        assert page.phrases.conclusion_autofill_button.isEnabled() is False
        page.phrases._on_autofill_conclusion()
        assert page.conclusion == frozen

        other = main_window._tabs.open_tab(origin=TAB_ORIGIN_EMPTY, activate=True)
        main_window._update_main_stack()
        main_window.report_coordinator.set_mode(True)
        assert other.report_generated_conclusion == ""
        assert page.conclusion == ""
        assert page.phrases.conclusion_autofill_button.isEnabled() is True

        main_window._tabs.activate(first.tab_id)
        main_window._update_main_stack()
        main_window.report_coordinator.set_mode(True)
        assert page.conclusion == frozen
        assert first.report_generated_conclusion


class TestReportProvenanceAndFinish:
    """UI-4 PR-4/PR-5: «откуда значение», «Открыть кадры», печать и «Завершить»."""

    def test_a_not_evaluated_mark_reaches_the_printed_sheet(self, main_window):
        from echo_personal_tool.domain.protocols import StudyProjection

        TestReportMode._study(main_window)
        main_window._controller.study_projection.return_value = StudyProjection()
        main_window.report_coordinator.set_mode(True)
        page = main_window.report_coordinator.page
        item = page.sections.sections[0].items[0]

        page.sections._toggle_not_evaluated(item.key)
        page.refresh_now()

        document = page.document
        assert document is not None
        rows = {value.label: value for group in document.groups for value in group.values}
        assert item.label in rows
        assert rows[item.label].value == "не оценивалось"

    def test_finishing_freezes_the_version_of_the_tab(self, main_window):
        TestReportMode._study(main_window)
        main_window.report_coordinator.set_mode(True)
        page = main_window.report_coordinator.page
        tab = main_window._tabs.active
        frozen = page.pdf_bytes

        main_window.report_coordinator.set_finished(True)

        assert tab.report_finished is True
        assert tab.report_frozen_sheet is not None
        assert tab.report_frozen_sheet.pdf == frozen
        assert page.is_finished is True
        # Measurements may keep changing; the fixed version must not.
        main_window.report_coordinator.request_refresh()
        assert page.refresh_now() is False
        assert page.pdf_bytes == frozen

        main_window.report_coordinator.set_finished(False)

        assert tab.report_finished is False
        assert tab.report_frozen_sheet is None
        assert page.is_finished is False
        assert page.refresh_now() is True

    def test_the_finished_version_survives_a_tab_switch(self, main_window):
        from echo_personal_tool.application.tab_session import TAB_ORIGIN_EMPTY

        TestReportMode._study(main_window)
        main_window.report_coordinator.set_mode(True)
        page = main_window.report_coordinator.page
        first = main_window._tabs.active
        frozen = page.pdf_bytes
        main_window.report_coordinator.set_finished(True)

        other = main_window._tabs.open_tab(origin=TAB_ORIGIN_EMPTY, activate=True)
        main_window._update_main_stack()
        assert other.report_finished is False
        main_window.report_coordinator.set_mode(True)
        assert page.is_finished is False

        main_window._tabs.activate(first.tab_id)
        main_window._update_main_stack()
        main_window.report_coordinator.set_mode(True)

        assert page.is_finished is True
        assert page.pdf_bytes == frozen
        assert first.report_finished is True

    def test_open_frames_returns_to_the_recorded_frame(self, main_window):
        from dataclasses import replace as replace_dataclass

        from echo_personal_tool.domain.models.metadata import InstanceMetadata
        from echo_personal_tool.domain.models.viewer_state import ViewerState

        TestReportMode._study(main_window)
        instance = InstanceMetadata(
            sop_instance_uid="1.2.3.4",
            series_uid="9.8.7",
            modality="US",
            number_of_frames=20,
            pixel_spacing=None,
            frame_time_ms=None,
            series_description="2D",
        )
        snapshot = main_window._controller.state_manager.snapshot
        if not isinstance(snapshot, ViewerState):
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
        main_window._controller.state_manager.snapshot = replace_dataclass(snapshot, instance=instance, total_frames=20)
        main_window.report_coordinator.set_mode(True)
        main_window.report_coordinator.instance_by_uid = lambda uid: instance

        main_window.report_coordinator.open_frames("1.2.3.4", 3)

        assert main_window.report_coordinator.mode_active() is False
        main_window._controller.set_playing.assert_called_with(False)
        main_window._controller.state_manager.set_frame.assert_called_with(3)

    def test_exporting_the_sheet_writes_the_document(self, main_window, monkeypatch, tmp_path):
        TestReportMode._study(main_window)
        main_window.report_coordinator.set_mode(True)
        page = main_window.report_coordinator.page
        target = tmp_path / "study_report.pdf"
        monkeypatch.setattr(
            "echo_personal_tool.presentation.styled_dialogs.styled_save_file",
            lambda *args, **kwargs: (str(target), "PDF (*.pdf)"),
        )

        main_window.report_coordinator.export_pdf()

        assert target.exists()
        assert target.read_bytes().startswith(b"%PDF-")
        from PySide6.QtWidgets import QLabel

        status = page.export.findChild(QLabel, "reportExportStatus")
        assert status is not None
        assert "study_report.pdf" in status.text()


class TestPairedToolsContinueOnTheNextClick:
    """ТЗ 2026-10-23, п. 2: вторая половина парного инструмента из Quick."""

    def test_the_diastole_sequence_arms_lvids(self, main_window) -> None:
        viewer = main_window._viewer
        main_window._on_linear_caliper_sequence_completed()
        assert viewer.armed_next() == ("caliper", "LVESD")

    def test_the_ed_contour_arms_the_es_contour(self, main_window) -> None:
        from unittest.mock import patch

        from echo_personal_tool.domain.models.contour import Contour

        viewer = main_window._viewer
        contour = Contour(
            chamber="LV",
            view="A4C",
            phase="ED",
            points=[(0.0, 0.0), (50.0, 0.0), (50.0, 50.0)],
            # An open arc is what the ED measurement produces (annulus → apex).
            mitral_annulus=((0.0, 0.0), (50.0, 0.0)),
            apex_landmark=(25.0, 50.0),
        )
        # The window refreshes the results overlay right after the contour; the
        # fixture keeps a mock controller, so only the arming matters here.
        with patch(
            "echo_personal_tool.presentation.main_window.format_results_overlay_html",
            return_value="",
        ):
            main_window._on_contour_completed(contour)
        assert viewer.armed_next() == ("contour", "LV", "A4C", "ES", False)


class TestMainWindowEventAfterDeferredDelete:
    """GUI-shard teardown must not call Qt through a dead C++ wrapper."""

    def test_a_dead_wrapper_is_dropped_before_qt_event_dispatch(self, main_window, monkeypatch) -> None:
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QMainWindow

        from echo_personal_tool.presentation import main_window as main_window_module

        monkeypatch.setattr(main_window_module, "qobject_is_alive", lambda _obj: False)
        with patch.object(QMainWindow, "event", side_effect=AssertionError("dead wrapper reached Qt")):
            assert main_window.event(QEvent(QEvent.Type.HoverMove)) is False

    def test_a_live_wrapper_still_forwards_events_to_qt(self, main_window, monkeypatch) -> None:
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QMainWindow

        from echo_personal_tool.presentation import main_window as main_window_module

        monkeypatch.setattr(main_window_module, "qobject_is_alive", lambda _obj: True)
        with patch.object(QMainWindow, "event", return_value=True) as forwarded:
            assert main_window.event(QEvent(QEvent.Type.Paint)) is True
        forwarded.assert_called_once()


class TestReportFormat:
    """Item 7 of the 2026-11-06 list: the sheet has a report format.

    The explicit choice lives in the tab (one study, one protocol); a study
    without a choice starts from the cardiac classifier, and «Завершить»
    freezes the format together with the sheet.
    """

    def _study(self, main_window) -> None:
        """A cardiac-named instance and an empty but valid snapshot."""
        from dataclasses import replace

        from echo_personal_tool.domain.models.metadata import InstanceMetadata

        main_window._controller.state_manager.snapshot = replace(
            main_window._controller.state_manager.snapshot,
            instance=InstanceMetadata(
                sop_instance_uid="1.2.3.fmt",
                series_uid="1.2.3",
                modality="US",
                number_of_frames=20,
                pixel_spacing=(0.5, 0.5),
                frame_time_ms=33.3,
                series_description="A4C Echo",
                study_description="ЭхоКГ",
                path=None,
            ),
        )
        main_window._controller.compute_study_snapshot.return_value = None
        main_window._controller.patient_metric_sources.return_value = ("unset", "unset")

    def test_a_cardiac_study_starts_as_an_echocardiography_protocol(self, main_window):
        from echo_personal_tool.domain.services.report_profiles import PROFILE_ECHO

        self._study(main_window)
        main_window.report_coordinator.set_mode(True)
        assert main_window.report_coordinator.page.preview.profile_id == PROFILE_ECHO
        assert main_window.report_coordinator.current_document().profile_id == PROFILE_ECHO

    def test_a_non_cardiac_study_starts_as_a_generic_ultrasound_protocol(self, main_window):
        from dataclasses import replace

        from echo_personal_tool.domain.models.metadata import InstanceMetadata
        from echo_personal_tool.domain.services.report_profiles import PROFILE_ULTRASOUND

        self._study(main_window)
        main_window._controller.state_manager.snapshot = replace(
            main_window._controller.state_manager.snapshot,
            instance=InstanceMetadata(
                sop_instance_uid="1.2.3.abd",
                series_uid="1.2.3",
                modality="US",
                number_of_frames=20,
                pixel_spacing=(0.5, 0.5),
                frame_time_ms=33.3,
                series_description="Abdomen",
                study_description="УЗИ брюшной полости",
                path=None,
            ),
        )
        main_window.report_coordinator.set_mode(True)
        assert main_window.report_coordinator.page.preview.profile_id == PROFILE_ULTRASOUND

    def test_the_choice_is_remembered_per_tab(self, main_window):
        from echo_personal_tool.domain.services.report_profiles import PROFILE_ULTRASOUND

        self._study(main_window)
        main_window.report_coordinator.set_mode(True)
        main_window.report_coordinator.choose_profile(PROFILE_ULTRASOUND)
        assert main_window._tabs.active.report_profile == PROFILE_ULTRASOUND
        # Re-entering the mode keeps the physician's choice, not the guess.
        main_window.report_coordinator.set_mode(False)
        main_window.report_coordinator.set_mode(True)
        assert main_window._tabs.active.report_profile == PROFILE_ULTRASOUND
        assert main_window.report_coordinator.page.preview.profile_id == PROFILE_ULTRASOUND

    def test_a_finished_report_keeps_its_format(self, main_window):
        from echo_personal_tool.domain.services.report_profiles import PROFILE_ECHO, PROFILE_ULTRASOUND

        self._study(main_window)
        main_window.report_coordinator.set_mode(True)
        main_window._tabs.active.report_finished = True
        main_window.report_coordinator.choose_profile(PROFILE_ULTRASOUND)
        assert main_window._tabs.active.report_profile in ("", PROFILE_ECHO)
        assert main_window.report_coordinator.current_document().profile_id == PROFILE_ECHO

    def test_an_unknown_format_falls_back_to_the_default(self, main_window):
        from echo_personal_tool.domain.services.report_profiles import PROFILE_ECHO

        self._study(main_window)
        main_window.report_coordinator.set_mode(True)
        main_window.report_coordinator.choose_profile("cardio_mri")
        assert main_window._tabs.active.report_profile == PROFILE_ECHO
        assert main_window.report_coordinator.current_document().profile_id == PROFILE_ECHO

    def test_the_document_of_the_sheet_carries_the_format(self, main_window):
        from echo_personal_tool.domain.services.report_profiles import PROFILE_ULTRASOUND

        self._study(main_window)
        main_window.report_coordinator.set_mode(True)
        main_window.report_coordinator.choose_profile(PROFILE_ULTRASOUND)
        document = main_window.report_coordinator.current_document()
        assert document.profile_id == PROFILE_ULTRASOUND
        assert document.title == "Протокол ультразвукового исследования"


class TestReportInputsSwitch:
    """Item 8 of the 2026-11-06 list: the «Входные данные» footnote switch.

    The switch of the sheet header changes the document *and* is remembered:
    the choice is about how the physician likes their protocols, not about one
    study.  A finished sheet freezes it (the frozen bytes keep their footnotes).
    """

    def _study(self, main_window) -> None:
        from dataclasses import replace

        from echo_personal_tool.domain.models.metadata import InstanceMetadata

        main_window._controller.state_manager.snapshot = replace(
            main_window._controller.state_manager.snapshot,
            instance=InstanceMetadata(
                sop_instance_uid="1.2.3.inputs",
                series_uid="1.2.3",
                modality="US",
                number_of_frames=20,
                pixel_spacing=(0.5, 0.5),
                frame_time_ms=33.3,
                series_description="A4C Echo",
                study_description="ЭхоКГ",
                path=None,
            ),
        )
        main_window._controller.compute_study_snapshot.return_value = None
        main_window._controller.patient_metric_sources.return_value = ("unset", "unset")

    def _calculations(self):
        from echo_personal_tool.application.calculator_inputs import resolve_standalone_inputs
        from echo_personal_tool.domain.calculators import evaluate

        return evaluate(
            resolve_standalone_inputs({"lvot_d": 2.0, "lvot_vti": 20.0, "av_vti": 100.0, "hr": 70.0, "bsa": 1.9})
        )

    def _calc_notes(self, main_window) -> tuple[str, ...]:
        from echo_personal_tool.domain.services.report_builder import GROUP_CALCULATIONS

        document = main_window.report_coordinator.current_document()
        return next((group.notes for group in document.groups if group.key == GROUP_CALCULATIONS), ())

    def _with_calculations(self, main_window) -> None:
        """The study snapshot the window builds already carries the calculations."""
        from echo_personal_tool.domain.models.measurements import MeasurementSnapshot

        main_window._controller.compute_study_snapshot.return_value = MeasurementSnapshot(
            calculations=self._calculations()
        )

    def test_the_sheet_starts_with_the_saved_preference(self, main_window):
        from dataclasses import replace

        self._study(main_window)
        main_window._user_preferences = replace(main_window._user_preferences, report_show_inputs=True)
        main_window.report_coordinator.set_mode(True)
        assert main_window.report_coordinator.page.preview.inputs_visible() is True

    def test_the_switch_reaches_the_document(self, main_window):
        self._study(main_window)
        self._with_calculations(main_window)
        # Since 2026-11-09 the switch silences the whole machine-generated
        # footnote block; the routine sheet carries none of it.
        main_window.report_coordinator.set_mode(True)
        off = self._calc_notes(main_window)
        assert off == ()

        main_window.report_coordinator.set_inputs_visible(True)
        on = self._calc_notes(main_window)
        assert on  # the inputs line, the assumptions and the RUO statement

        main_window.report_coordinator.set_inputs_visible(False)
        assert self._calc_notes(main_window) == off
        assert main_window.report_coordinator.page.preview.inputs_visible() is False

    def test_the_choice_survives_the_settings_dialog(self, main_window):
        from dataclasses import replace

        from echo_personal_tool.application.user_preferences import load_user_preferences

        self._study(main_window)
        main_window.report_coordinator.set_mode(True)

        main_window.report_coordinator.set_inputs_visible(True)

        assert load_user_preferences().report_show_inputs is True
        # Round trip through the dialog payload keeps the choice.
        payload = replace(main_window._user_preferences, report_show_inputs=True)
        assert payload.report_show_inputs is True

    def test_a_finished_report_freezes_the_switch(self, main_window):
        self._study(main_window)
        main_window.report_coordinator.set_mode(True)

        main_window._tabs.active.report_finished = True
        main_window.report_coordinator.sync_finished(main_window._tabs.active)

        assert not main_window.report_coordinator.page.preview._inputs_button.isEnabled()


class TestHiddenReportValues:
    """Item 9 of the 2026-11-06 list: hiding a row of the sheet.

    The set lives in the tab (one study, one protocol), a fresh load clears it,
    a finished version refuses the change, and the file formats follow the
    document — so the CSV/JSON export cannot leak a hidden row.
    """

    def _study(self, main_window) -> None:
        from dataclasses import replace

        from echo_personal_tool.domain.models.metadata import InstanceMetadata

        main_window._controller.state_manager.snapshot = replace(
            main_window._controller.state_manager.snapshot,
            instance=InstanceMetadata(
                sop_instance_uid="1.2.3.hidden",
                series_uid="1.2.3",
                modality="US",
                number_of_frames=20,
                pixel_spacing=(0.5, 0.5),
                frame_time_ms=33.3,
                series_description="A4C Echo",
                study_description="ЭхоКГ",
                path=None,
            ),
        )
        main_window._controller.patient_metric_sources.return_value = ("unset", "unset")

    def _with_calculations(self, main_window):
        from echo_personal_tool.application.calculator_inputs import resolve_standalone_inputs
        from echo_personal_tool.domain.calculators import evaluate
        from echo_personal_tool.domain.models.measurements import MeasurementSnapshot

        calculations = evaluate(
            resolve_standalone_inputs({"lvot_d": 2.0, "lvot_vti": 20.0, "av_vti": 100.0, "hr": 70.0, "bsa": 1.9})
        )
        main_window._controller.compute_study_snapshot.return_value = MeasurementSnapshot(calculations=calculations)
        return calculations

    def test_hiding_a_row_reaches_the_document_and_the_tab(self, main_window):
        from echo_personal_tool.domain.services.report_builder import GROUP_CALCULATIONS

        self._study(main_window)
        self._with_calculations(main_window)
        main_window.report_coordinator.set_mode(True)
        document = main_window.report_coordinator.current_document()
        row = next(group for group in document.groups if group.key == GROUP_CALCULATIONS).values[0]

        main_window.report_coordinator.set_value_hidden(row.key, True)

        assert row.key in main_window._tabs.active.report_hidden_values
        labels = [
            value.key for group in main_window.report_coordinator.current_document().groups for value in group.values
        ]
        assert row.key not in labels

    def test_restoring_brings_the_row_back(self, main_window):
        from echo_personal_tool.domain.services.report_builder import GROUP_CALCULATIONS

        self._study(main_window)
        self._with_calculations(main_window)
        main_window.report_coordinator.set_mode(True)
        before = [
            value.key for group in main_window.report_coordinator.current_document().groups for value in group.values
        ]
        key = (
            next(
                group
                for group in main_window.report_coordinator.current_document().groups
                if group.key == GROUP_CALCULATIONS
            )
            .values[0]
            .key
        )

        main_window.report_coordinator.set_value_hidden(key, True)
        main_window.report_coordinator.set_value_hidden(key, False)

        after = [
            value.key for group in main_window.report_coordinator.current_document().groups for value in group.values
        ]
        assert after == before
        assert key not in main_window._tabs.active.report_hidden_values

    def test_the_left_column_lists_what_is_hidden(self, main_window):
        from echo_personal_tool.domain.services.report_builder import GROUP_CALCULATIONS

        self._study(main_window)
        self._with_calculations(main_window)
        main_window.report_coordinator.set_mode(True)
        row = next(
            group
            for group in main_window.report_coordinator.current_document().groups
            if group.key == GROUP_CALCULATIONS
        ).values[0]

        main_window.report_coordinator.set_value_hidden(row.key, True)

        entries = main_window.report_coordinator.page.sections.hidden_values
        assert [key for key, _label in entries] == [row.key]
        assert row.label in entries[0][1]

    def test_a_finished_version_refuses_hiding(self, main_window):
        from echo_personal_tool.domain.services.report_builder import GROUP_CALCULATIONS

        self._study(main_window)
        self._with_calculations(main_window)
        main_window.report_coordinator.set_mode(True)
        row = next(
            group
            for group in main_window.report_coordinator.current_document().groups
            if group.key == GROUP_CALCULATIONS
        ).values[0]
        main_window._tabs.active.report_finished = True

        main_window.report_coordinator.set_value_hidden(row.key, True)

        assert main_window._tabs.active.report_hidden_values == set()

    def test_the_export_document_follows_the_hidden_set(self, main_window):
        """The exports write ``page.document`` — the very sheet on screen (S-11)."""
        from echo_personal_tool.domain.services.report_builder import GROUP_CALCULATIONS

        self._study(main_window)
        self._with_calculations(main_window)
        main_window.report_coordinator.set_mode(True)
        row = next(
            group
            for group in main_window.report_coordinator.current_document().groups
            if group.key == GROUP_CALCULATIONS
        ).values[0]

        main_window.report_coordinator.set_value_hidden(row.key, True)
        main_window.report_coordinator.page.refresh_now()

        exported = main_window.report_coordinator.page.document
        assert exported is not None
        assert row.key not in [value.key for group in exported.groups for value in group.values]


class TestRenameFromTheReport:
    """Item 10 of the 2026-11-06 list: a planimetry row is named in the sheet.

    The name lives in the contour, so the window asks the viewer to change it;
    the frozen version refuses the edit like every other report edit.
    """

    def _study(self, main_window) -> None:
        from dataclasses import replace

        from echo_personal_tool.domain.models.metadata import InstanceMetadata

        main_window._controller.state_manager.snapshot = replace(
            main_window._controller.state_manager.snapshot,
            instance=InstanceMetadata(
                sop_instance_uid="1.2.3.rename",
                series_uid="1.2.3",
                modality="US",
                number_of_frames=20,
                pixel_spacing=(0.5, 0.5),
                frame_time_ms=33.3,
                series_description="A4C Echo",
                study_description="ЭхоКГ",
                path=None,
            ),
        )
        main_window._controller.patient_metric_sources.return_value = ("unset", "unset")

    def _contour(self):
        from echo_personal_tool.domain.calculations.planimeter import GENERIC_AREA_CHAMBER
        from echo_personal_tool.domain.models.contour import Contour

        return Contour(
            phase="GEN",
            view="A4C",
            chamber=GENERIC_AREA_CHAMBER,
            points=[(10.0, 10.0), (40.0, 10.0), (40.0, 40.0)],
            frame_index=0,
            measurement_id="m-10",
            measurement_label="Площадь1",
        )

    def test_the_rename_reaches_the_viewer(self, main_window, monkeypatch):
        self._study(main_window)
        calls: list[tuple[str, str]] = []

        def _rename(measurement_id: str, label: str) -> bool:
            calls.append((measurement_id, label))
            return True

        monkeypatch.setattr(main_window._viewer, "rename_contour_measurement", _rename)

        main_window.report_coordinator.rename_value("m-10", "Почка")

        assert calls == [("m-10", "Почка")]

    def test_an_unknown_measurement_reports_that_it_is_elsewhere(self, main_window, monkeypatch):
        self._study(main_window)
        statuses: list[str] = []
        monkeypatch.setattr(main_window._viewer, "rename_contour_measurement", lambda uid, label: False)
        monkeypatch.setattr(main_window, "_show_status", statuses.append)

        main_window.report_coordinator.rename_value("ghost", "Почка")

        assert statuses  # «полигон другого кадра» — the physician is told why nothing happened

    def test_a_finished_version_refuses_the_rename(self, main_window, monkeypatch):
        self._study(main_window)
        calls: list[tuple[str, str]] = []
        monkeypatch.setattr(
            main_window._viewer,
            "rename_contour_measurement",
            lambda uid, label: calls.append((uid, label)) or True,
        )
        main_window._tabs.active.report_finished = True

        main_window.report_coordinator.rename_value("m-10", "Почка")

        assert calls == []

    def test_a_blank_name_is_not_an_edit(self, main_window, monkeypatch):
        self._study(main_window)
        calls: list[tuple[str, str]] = []
        monkeypatch.setattr(
            main_window._viewer,
            "rename_contour_measurement",
            lambda uid, label: calls.append((uid, label)) or True,
        )

        main_window.report_coordinator.rename_value("m-10", "   ")

        assert calls == []


class TestStudyProfile:
    """Item 11 of the 2026-11-06 list: the study type of the workspace.

    The switch retunes the tool panel and the report format without a restart,
    is stored as a preference, refuses to fire during a protocol, and never
    touches the measurements already made.
    """

    def _study(self, main_window) -> None:
        from dataclasses import replace

        from echo_personal_tool.domain.models.metadata import InstanceMetadata

        main_window._controller.state_manager.snapshot = replace(
            main_window._controller.state_manager.snapshot,
            instance=InstanceMetadata(
                sop_instance_uid="1.2.3.profile",
                series_uid="1.2.3",
                modality="US",
                number_of_frames=20,
                pixel_spacing=(0.5, 0.5),
                frame_time_ms=33.3,
                series_description="A4C Echo",
                study_description="ЭхоКГ",
                path=None,
            ),
        )
        main_window._controller.compute_study_snapshot.return_value = None
        main_window._controller.patient_metric_sources.return_value = ("unset", "unset")

    def test_the_switch_is_stored_and_shown(self, main_window):
        from echo_personal_tool.application.user_preferences import load_user_preferences

        self._study(main_window)
        self._on_profile(main_window, "builtin.vascular")

        assert main_window._user_preferences.study_profile == "builtin.vascular"
        assert main_window._system_bar.study_profile() == "builtin.vascular"
        assert load_user_preferences().study_profile == "builtin.vascular"

    def _on_profile(self, main_window, profile_id: str) -> None:
        main_window._on_study_profile_changed(profile_id)

    def test_the_sheet_prints_only_the_measurements_of_the_selected_study(self, main_window):
        """One study, two examinations: the sheet tells the one on screen.

        The owner measured the heart, then switched the study to the thyroid
        and found the Teichholz numbers in the thyroid protocol.
        """
        from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
        from echo_personal_tool.domain.models.measurements import MeasurementSnapshot, TeichholzResult
        from echo_personal_tool.infrastructure.i18n import set_language

        set_language("ru")
        self._study(main_window)
        main_window._controller.compute_study_snapshot.return_value = MeasurementSnapshot(
            linear_measurements=(
                LinearMeasurement(label="LVEDD", pixel_length=4, millimeter_length=47.7),
                LinearMeasurement(label="TH-R-TH", pixel_length=4, millimeter_length=38.8),
            ),
            teichholz=TeichholzResult(edv_ml=106.0, esv_ml=54.0, lvef_percent=49.0, sv_ml=52.0),
        )
        main_window.report_coordinator.set_mode(True)

        self._on_profile(main_window, "builtin.thyroid")
        labels = {
            value.label for group in main_window.report_coordinator.current_document().groups for value in group.values
        }
        assert any("ЩЖ" in label for label in labels)
        assert not any("Тейхольц" in label or "КДР" in label for label in labels)

        self._on_profile(main_window, "builtin.adult_echo")
        labels = {
            value.label for group in main_window.report_coordinator.current_document().groups for value in group.values
        }
        assert any("Тейхольц" in label for label in labels)
        assert not any("ЩЖ" in label for label in labels)

    def test_the_panel_follows_the_profile(self, main_window):
        self._study(main_window)
        rebuilt: list[object] = []

        original = main_window._tool_panel.rebuild_menu_with_preferences

        def _record(prefs):
            rebuilt.append(prefs)
            original(prefs)

        main_window._tool_panel.rebuild_menu_with_preferences = _record
        try:
            main_window._on_study_profile_changed("builtin.thyroid")
        finally:
            main_window._tool_panel.rebuild_menu_with_preferences = original

        assert rebuilt and rebuilt[-1].study_profile == "builtin.thyroid"

    def test_the_report_format_follows_a_non_cardiac_profile(self, main_window):
        from echo_personal_tool.domain.services.report_profiles import PROFILE_ABDOMEN

        self._study(main_window)
        main_window.report_coordinator.set_mode(True)
        main_window._on_study_profile_changed("builtin.abdomen")

        assert main_window.report_coordinator.current_document().profile_id == PROFILE_ABDOMEN

    def test_the_cardiac_profile_still_classifies_the_study(self, main_window):
        from echo_personal_tool.domain.services.report_profiles import PROFILE_ECHO

        self._study(main_window)
        main_window.report_coordinator.set_mode(True)
        main_window._on_study_profile_changed("builtin.adult_echo")

        assert main_window.report_coordinator.current_document().profile_id == PROFILE_ECHO

    def test_a_running_protocol_keeps_the_current_profile(self, main_window, monkeypatch):
        self._study(main_window)
        statuses: list[str] = []
        monkeypatch.setattr(main_window._tool_panel, "is_protocol_running", lambda: True)
        monkeypatch.setattr(main_window, "_show_status", statuses.append)

        main_window._on_study_profile_changed("builtin.vascular")

        assert main_window._user_preferences.study_profile == "builtin.adult_echo"
        assert statuses  # the physician is told why nothing changed

    def test_the_stored_profile_returns_after_a_restart(self, main_window):
        """The first apply pass of a fresh window mirrors the saved preference."""
        from dataclasses import replace

        prefs = replace(main_window._user_preferences, study_profile="builtin.thyroid")
        main_window._system_bar.set_study_profile(prefs.study_profile)
        main_window._user_preferences = prefs

        assert main_window._system_bar.study_profile() == "builtin.thyroid"
        assert main_window._study_profile_id() == "builtin.thyroid"


class TestReportTemplate:
    """Item 12 of the 2026-11-06 list: the saved form reaches the sheet."""

    def test_an_empty_preference_means_the_full_form(self, main_window) -> None:
        from dataclasses import replace

        main_window._user_preferences = replace(main_window._user_preferences, report_template_json="")
        assert main_window.report_coordinator.template() is None

    def test_a_saved_form_is_decoded(self, main_window) -> None:
        from dataclasses import replace

        from echo_personal_tool.domain.services.report_template import FIELD_PHYSICIAN, ReportTemplate, encode_template

        stored = replace(
            main_window._user_preferences,
            report_template_json=encode_template(ReportTemplate(header_fields=(FIELD_PHYSICIAN,))),
        )
        main_window._user_preferences = stored
        template = main_window.report_coordinator.template()
        assert template is not None
        assert template.header_fields == (FIELD_PHYSICIAN,)

    def test_the_sheet_adopts_the_form(self, main_window) -> None:
        from dataclasses import replace

        from echo_personal_tool.domain.services.report_template import ReportTemplate, encode_template

        main_window._user_preferences = replace(
            main_window._user_preferences,
            report_template_json=encode_template(ReportTemplate(show_signature=False)),
        )
        page = main_window.report_coordinator.ensure_page()
        main_window.report_coordinator.refresh_template()
        assert page.template.show_signature is False

    def test_an_unreadable_preference_still_prints_the_standard_form(self, main_window) -> None:
        from dataclasses import replace

        from echo_personal_tool.domain.services.report_template import default_template

        main_window._user_preferences = replace(main_window._user_preferences, report_template_json="{{{")
        assert main_window.report_coordinator.template() == default_template()
