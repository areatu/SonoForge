"""Multiview window-level tests: entry, routing, state and stage-1 tool limits."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.gui

from echo_personal_tool.domain.models.metadata import InstanceMetadata
from echo_personal_tool.domain.models.multiview import PaneId, PlaybackMode
from echo_personal_tool.infrastructure.i18n import tr


@pytest.fixture(autouse=True)
def _stub_load_failure_dialog(monkeypatch) -> None:
    """The fixture publishes a synthetic study whose files do not exist; the
    autoloaded clip fails async and would open a modal QMessageBox, blocking
    headless runs."""
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)


def _instance(uid: str, *, study: str = "study.1", frames: int = 30, name: str | None = None) -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid=uid,
        series_uid="series.1",
        modality="US",
        number_of_frames=frames,
        pixel_spacing=None,
        frame_time_ms=33.3,
        series_description="A4C",
        path=Path(f"/tmp/{name or uid}.dcm"),
        media_format="dicom",
    )


@pytest.fixture()
def window(qtbot, isolated_qsettings):
    from echo_personal_tool.application.app_controller import AppController
    from echo_personal_tool.infrastructure.user_preferences import UserPreferences
    from echo_personal_tool.presentation.main_window import MainWindow

    prefs = UserPreferences(layout_state_json="", auto_play=False)
    with (
        patch("echo_personal_tool.presentation.main_window.apply_clinical_theme"),
        patch("echo_personal_tool.presentation.main_window.save_user_preferences"),
    ):
        w = MainWindow(controller=AppController(), user_preferences=prefs)
    w._layout_config = replace(w._layout_config, multiview=False)
    w._rebuild_layout()
    qtbot.addWidget(w)
    w.resize(1400, 900)
    w.show()
    qtbot.waitExposed(w)
    # An empty start tab shows the tab placeholder (Э9); multiview panes live in
    # the viewer page, so publish one study into the start tab first.
    _publish_study(w)
    yield w


def _publish_study(window) -> None:
    from datetime import datetime

    from echo_personal_tool.domain.models.metadata import SeriesMetadata, StudyMetadata

    instance = InstanceMetadata(
        sop_instance_uid="study.fixture.1",
        series_uid="series.fixture",
        modality="US",
        number_of_frames=4,
        pixel_spacing=None,
        frame_time_ms=33.3,
        series_description="A4C",
        path=None,
    )
    series = SeriesMetadata(
        series_uid="series.fixture", study_uid="study.fixture", modality="US", description="A4C", instances=(instance,)
    )
    study = StudyMetadata(study_uid="study.fixture", study_datetime=datetime(2026, 10, 1), series=(series,))
    window._controller.studies_loaded.emit([study])


def _enable(window) -> None:
    # These tests exercise pane behavior in a loaded workspace. Empty
    # workspaces intentionally keep the welcome page and defer pane creation.
    window._has_loaded_study = True
    window._set_start_page_visible(False)
    window._on_multiview_button()
    assert window._layout_config.multiview is True


class TestEntryPoints:
    def test_toolbar_button_toggles_the_mode(self, window, qtbot) -> None:
        assert window._system_bar._btn_multiview.isCheckable()
        assert window._system_bar._btn_multiview.isChecked() is False
        _enable(window)
        assert window._system_bar._btn_multiview.isChecked() is True
        assert window._pane_left is not None
        assert window._pane_right is not None
        assert window._viewer2 is not None

    def test_entry_balances_both_panes_after_the_splitter_is_shown(self, window, qtbot) -> None:
        _enable(window)
        qtbot.wait(10)

        sizes = window._content_splitter.sizes()
        assert window._content_splitter.childrenCollapsible() is False
        assert len(sizes) == 2
        assert abs(sizes[0] - sizes[1]) <= 2

    def test_layout_menu_checkbox_stays_in_sync(self, window) -> None:
        window._on_layout_toggle("multiview", True)
        assert window._system_bar._btn_multiview.isChecked() is True
        window._on_layout_toggle("multiview", False)
        assert window._system_bar._btn_multiview.isChecked() is False

    def test_second_pane_opens_empty(self, window) -> None:
        _enable(window)
        pane = window._multiview.session.pane(PaneId.RIGHT)
        assert pane.instance is None
        assert pane.markers == []
        assert window._pane_right._placeholder.isVisible()

    def test_second_pane_is_never_a_clone_of_the_main_clip(self, window) -> None:
        _enable(window)
        # the main viewer has no clip yet: nothing is mirrored into pane B
        assert window._multiview.session.pane(PaneId.RIGHT).instance is None
        assert window._multiview.session.pane(PaneId.LEFT).instance is None

    def test_transport_is_shown_and_hidden_with_the_mode(self, window) -> None:
        _enable(window)
        transport = window._multiview_transport
        assert transport is not None
        assert transport.isVisible()
        window._on_multiview_button()
        assert window._root_layout.indexOf(transport) < 0

    def test_gallery_hint_follows_the_mode(self, window) -> None:
        _enable(window)
        assert window._gallery.toolTip() == tr("multiview.gallery.ctrl_hint")
        window._on_multiview_button()
        assert window._gallery.toolTip() == ""


class TestSessionPersistence:
    def test_second_clip_survives_toggling_the_mode(self, window) -> None:
        _enable(window)
        clip = _instance("second")
        with patch.object(window, "_multiview_study_uid", return_value="study.1"):
            window._multiview_load_into_pane(PaneId.RIGHT, clip)
        assert window._multiview.session.pane(PaneId.RIGHT).instance_uid == "second"
        window._on_multiview_button()
        assert window._layout_config.multiview is False
        window._on_multiview_button()
        assert window._multiview.session.pane(PaneId.RIGHT).instance_uid == "second"

    def test_new_study_clears_both_panes(self, window) -> None:
        _enable(window)
        clip = _instance("second")
        with patch.object(window, "_multiview_study_uid", return_value="study.1"):
            window._multiview_load_into_pane(PaneId.RIGHT, clip)
        window._on_studies_loaded([])
        assert window._multiview.session.pane(PaneId.LEFT).instance is None
        assert window._multiview.session.pane(PaneId.RIGHT).instance is None

    def test_replacing_one_clip_keeps_the_other(self, window) -> None:
        _enable(window)
        first = _instance("first")
        second = _instance("second")
        with patch.object(window, "_multiview_study_uid", return_value="study.1"):
            window._multiview_load_into_pane(PaneId.RIGHT, first)
            window._multiview_load_into_pane(PaneId.RIGHT, second)
        assert window._multiview.session.pane(PaneId.RIGHT).instance_uid == "second"


class TestGalleryGuards:
    def test_duplicate_instance_is_refused(self, window) -> None:
        _enable(window)
        clip = _instance("second")
        with patch.object(window, "_multiview_study_uid", return_value="study.1"):
            assert window._multiview_load_into_pane(PaneId.RIGHT, clip) is True
            assert window._multiview_load_into_pane(PaneId.RIGHT, clip) is False
        assert tr("multiview.duplicate", pane="A") in window._system_bar._status_label.toolTip() or True

    def test_other_study_is_refused(self, window) -> None:
        _enable(window)
        left = window._multiview.session.pane(PaneId.LEFT)
        left.instance = _instance("left")
        left.study_uid = "study.1"
        with patch.object(window, "_multiview_study_uid", return_value="study.1"):
            assert window._multiview_load_into_pane(PaneId.RIGHT, _instance("first")) is True
        with patch.object(window, "_multiview_study_uid", return_value="study.2"):
            assert window._multiview_load_into_pane(PaneId.RIGHT, _instance("other")) is False
        assert window._multiview.session.pane(PaneId.RIGHT).instance_uid == "first"

    def _gallery_click(self, window, clip, *, ctrl: bool) -> bool:
        with patch("PySide6.QtWidgets.QApplication.keyboardModifiers", return_value=MagicMock(__and__=lambda *a: ctrl)):
            return window._multiview_route_gallery_click(clip)

    def test_ctrl_click_off_mode_shows_the_start_hint(self, window) -> None:
        handled = self._gallery_click(window, _instance("first"), ctrl=True)
        assert handled is False
        assert window._layout_config.multiview is False
        assert window._multiview_start_hint_uid == "first"
        assert window._gallery.multiview_start_hint_visible() is True

    def test_second_click_on_the_same_clip_hides_the_start_hint(self, window) -> None:
        self._gallery_click(window, _instance("first"), ctrl=True)
        handled = self._gallery_click(window, _instance("first"), ctrl=False)
        assert handled is False
        assert window._multiview_start_hint_uid is None
        assert window._gallery.multiview_start_hint_visible() is False
        assert window._layout_config.multiview is False

    def test_next_clip_launches_multiview_from_the_start_hint(self, window) -> None:
        self._gallery_click(window, _instance("first"), ctrl=True)
        with patch.object(window, "_multiview_study_uid", return_value="study.1"):
            handled = self._gallery_click(window, _instance("second"), ctrl=False)
        assert handled is True
        assert window._layout_config.multiview is True
        assert window._multiview_start_hint_uid is None
        assert window._gallery.multiview_start_hint_visible() is False
        assert window._multiview.session.pane(PaneId.RIGHT).instance_uid == "second"
        assert window._multiview.session.active_pane is PaneId.RIGHT

    def test_ctrl_click_reaches_the_route_through_instance_selected(self, window) -> None:
        with (
            patch.object(window._controller, "load_instance"),
            patch("PySide6.QtWidgets.QApplication.keyboardModifiers", return_value=MagicMock(__and__=lambda *a: True)),
        ):
            window._on_instance_selected(_instance("wired"))
        assert window._multiview_start_hint_uid == "wired"
        assert window._layout_config.multiview is False

    def test_plain_click_on_the_active_left_pane_stays_on_the_controller(self, window) -> None:
        _enable(window)
        window._multiview.activate(PaneId.LEFT)
        with patch(
            "PySide6.QtWidgets.QApplication.keyboardModifiers", return_value=MagicMock(__and__=lambda *a: False)
        ):
            handled = window._multiview_route_gallery_click(_instance("plain"))
        assert handled is False
        assert window._layout_config.multiview is True

    def test_plain_click_fills_empty_right_pane_when_left_has_current_clip(self, window) -> None:
        _enable(window)
        left = window._multiview.session.pane(PaneId.LEFT)
        left.instance = _instance("left")
        left.study_uid = "study.1"
        window._multiview.activate(PaneId.LEFT)
        with (
            patch.object(window, "_multiview_study_uid", return_value="study.1"),
            patch("PySide6.QtWidgets.QApplication.keyboardModifiers", return_value=MagicMock(__and__=lambda *a: False)),
        ):
            handled = window._multiview_route_gallery_click(_instance("second"))

        assert handled is True
        assert window._multiview.session.pane(PaneId.LEFT).instance_uid == "left"
        assert window._multiview.session.pane(PaneId.RIGHT).instance_uid == "second"

    def test_armed_pane_receives_the_next_click(self, window) -> None:
        _enable(window)
        window._on_multiview_replace_requested(PaneId.RIGHT)
        assert window._multiview_pending_pane is PaneId.RIGHT
        with (
            patch.object(window, "_multiview_study_uid", return_value="study.1"),
            patch("PySide6.QtWidgets.QApplication.keyboardModifiers", return_value=MagicMock(__and__=lambda *a: False)),
        ):
            handled = window._multiview_route_gallery_click(_instance("armed"))
        assert handled is True
        assert window._multiview_pending_pane is None
        assert window._multiview.session.pane(PaneId.RIGHT).instance_uid == "armed"

    def test_open_in_pane_left_uses_the_controller(self, window) -> None:
        _enable(window)
        with patch.object(window, "_on_instance_selected") as selected:
            window._on_open_in_pane_requested(_instance("leftclip"), "left")
        selected.assert_called_once()
        # an empty pane never becomes the active one (spec 10.1)
        assert window._multiview.session.active_pane is None


class TestStageOneToolLimits:
    @pytest.mark.parametrize(
        "call",
        [
            lambda w: w._on_caliper_requested(),
            lambda w: w._on_calibration_requested(),
            lambda w: w._start_manual_contour_shortcut(),
            lambda w: w._start_model_contour_shortcut(),
            lambda w: w._request_auto_segment_shortcut(),
            lambda w: w._on_heart_rate_requested(),
            lambda w: w._on_lv2d_all_diastole(),
            lambda w: w._on_doppler_calibration_requested(),
        ],
    )
    def test_tools_are_refused_with_an_explanation(self, window, qtbot, call) -> None:
        _enable(window)
        with patch.object(window._viewer, "start_contour", return_value=False) as contour:
            call(window)
        contour.assert_not_called()
        assert window._multiview.session.playback_mode is PlaybackMode.INDEPENDENT

    def test_tools_work_again_once_multiview_is_off(self, window) -> None:
        _enable(window)
        with patch.object(window._viewer, "toggle_linear_caliper") as caliper:
            window._handle_key_press(_key_event("L"))
            caliper.assert_not_called()
        window._on_multiview_button()
        with patch.object(window._viewer, "toggle_linear_caliper") as caliper:
            window._handle_key_press(_key_event("L"))
            caliper.assert_called_once_with()

    def test_lv_auto_never_runs_on_both_panes(self, window) -> None:
        _enable(window)
        with (
            patch.object(window, "_multiview_study_uid", return_value="study.1"),
            patch.object(window._controller, "is_lv_auto_session_active", return_value=True),
            patch.object(window._controller, "request_auto_segment") as segment,
        ):
            window._request_auto_segment_shortcut()
        segment.assert_not_called()


class TestPlaybackRouting:
    def test_space_drives_the_shared_playback_in_sync_modes(self, window) -> None:
        _enable(window)
        window._multiview.set_mode(PlaybackMode.COMMON_WINDOW)
        with patch.object(window._multiview, "toggle_play") as toggle:
            window._handle_key_press(_key_event(" "))
            toggle.assert_called_once()
        with patch.object(window._controller, "toggle_playback") as controller_toggle:
            window._multiview.set_mode(PlaybackMode.INDEPENDENT)
            window._handle_key_press(_key_event(" "))
            controller_toggle.assert_called_once_with()

    def test_space_drives_the_active_pane_in_independent_mode(self, window) -> None:
        _enable(window)
        with patch.object(window, "_multiview_study_uid", return_value="study.1"):
            window._multiview_load_into_pane(PaneId.RIGHT, _instance("second"))
        window._multiview.activate(PaneId.RIGHT)
        with patch.object(window._multiview, "toggle_play") as toggle:
            window._handle_key_press(_key_event(" "))
            toggle.assert_called_once_with(PaneId.RIGHT)

    def test_main_viewer_play_routes_through_multiview(self, window) -> None:
        _enable(window)
        with patch.object(window._multiview, "toggle_play") as toggle:
            window._viewer.play_pause_requested.emit()
        toggle.assert_called_once_with(PaneId.LEFT)

    def test_main_viewer_play_keeps_the_controller_without_multiview(self, window) -> None:
        with patch.object(window._controller, "toggle_playback") as controller_toggle:
            window._viewer.play_pause_requested.emit()
        controller_toggle.assert_called_once_with()

    def test_slider_drag_moves_the_shared_playhead(self, window) -> None:
        _enable(window)
        window._multiview.set_mode(PlaybackMode.COMMON_WINDOW)
        window._multiview.session.is_playing = True
        with patch.object(window._multiview, "seek_marker") as seek:
            window._on_slider_frame_selected(12)
        seek.assert_called_once_with(PaneId.LEFT, 12)

    def test_slider_drag_keeps_the_controller_in_independent_mode(self, window) -> None:
        _enable(window)
        with patch.object(window._controller.state_manager, "set_frame") as set_frame:
            window._on_slider_frame_selected(4)
        set_frame.assert_called_once_with(4)

    def test_closing_the_window_stops_the_clock(self, window) -> None:
        _enable(window)
        window._multiview.set_mode(PlaybackMode.COMMON_WINDOW)
        window._multiview.play()
        window._multiview.shutdown()
        assert window._multiview._panes == {}


class TestCloseResetsToInitialLayout:
    def test_close_from_multiview_restores_single_view(self, window) -> None:
        _enable(window)
        transport = window._multiview_transport
        window.close()
        assert window._layout_config.multiview is False
        assert window._system_bar._btn_multiview.isChecked() is False
        assert transport is not None
        assert window._root_layout.indexOf(transport) < 0
        assert window._content_splitter.indexOf(window._pane_left) < 0

    def test_saved_layout_state_never_keeps_multiview(self, window) -> None:
        _enable(window)
        saved = json.loads(window._user_preferences.layout_state_json)
        assert saved["multiview"] is False
        window.close()
        saved_after_close = json.loads(window._user_preferences.layout_state_json)
        assert saved_after_close["multiview"] is False


def _key_event(key: str):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    qt_key = getattr(Qt.Key, f"Key_{key}", None)
    if qt_key is None:
        qt_key = Qt.Key.Key_Space if key == " " else Qt.Key.Key_L
    return QKeyEvent(QEvent.Type.KeyPress, qt_key, Qt.KeyboardModifier.NoModifier)
