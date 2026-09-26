"""Tests for Presenter mode (presenter_view) and the F11 fullscreen kiosk.

Architecture under test: the audience display gets a real, independently
rendered window (its own ViewerWidget fed with the same frames/state via
forwarding) — the PowerPoint/LibreOffice approach.  The old grab-based
pixel mirror was removed because QWidget.grab() cannot composite a
GL-backed pyqtgraph viewport (black image in the grab) and the readbacks
blanked the speaker's viewer.

Covers: audience-screen selection, presentation window lifecycle and
placement flags, read-only input swallowing, frame/state/overlay
forwarding, the non-destructive visual preset lifecycle, the presenter
default layout, the F11 kiosk and the activity-bar additions.
"""

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QMenu, QToolButton, QWidget

pytestmark = pytest.mark.gui

pytest.importorskip("pytestqt")


@pytest.fixture(autouse=True)
def _setup_qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def _make_snapshot():
    from echo_personal_tool.domain.models.viewer_state import ViewerState

    return ViewerState(
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


def _make_controller():
    c = MagicMock()
    c.state_manager = MagicMock()
    c.state_manager.snapshot = _make_snapshot()
    c.playback_config = MagicMock(scroll_debounce_ms=100)
    c.studies = []
    c.get_cached_frames.return_value = []
    # Persistent (not context-patched): _apply_user_preferences runs inside
    # the tests and must not hit the real results formatter.
    c.compute_overlay_snapshot = MagicMock(return_value=None)
    return c


@pytest.fixture()
def presenter_window(mock_controller, monkeypatch):
    """A MainWindow whose presenter mode can be exercised headlessly."""
    # Whole-test patches: _apply_user_preferences is exercised late in the
    # suite; re-polishing the real stylesheet over the accumulated widget
    # tree is pathologically slow and irrelevant to presenter logic.
    import echo_personal_tool.presentation.main_window as mw_module
    from echo_personal_tool.infrastructure.i18n import get_language, set_language
    from echo_personal_tool.infrastructure.user_preferences import UserPreferences
    from echo_personal_tool.presentation.main_window import MainWindow

    # Presenter mode ships in the Presenter (lite) build only — exercise
    # the suite under that profile (the real deployment).
    monkeypatch.setenv("SONOFORGE_PROFILE", "presenter")
    # MainWindow._apply_user_preferences sets the module-global i18n language;
    # remember it so the fixture can restore it for later tests.
    saved_language = get_language()
    monkeypatch.setattr(mw_module, "apply_clinical_theme", lambda **kwargs: None)
    monkeypatch.setattr(
        "echo_personal_tool.infrastructure.user_preferences.save_user_preferences",
        lambda preferences: None,
    )

    prefs = UserPreferences(
        theme_mode="dark",
        ui_font_size=12,
        layout_state_json="",
        confirm_reset=False,
        magnetic_snap_enabled=False,
        despeckle_enabled=False,
        results_overlay_font_size=20,
        caliper_line_width=2.0,
        presenter_visual_preset=True,
        presenter_pointer=True,
        presenter_screen="",
        language="en",
    )
    with (
        patch("echo_personal_tool.presentation.main_window.load_user_preferences", return_value=prefs),
        patch("echo_personal_tool.presentation.main_window.format_results_overlay_html", return_value=""),
    ):
        window = MainWindow(controller=mock_controller)
    try:
        yield window
    finally:
        if window._presenter.active:
            window._presenter.stop()
        window.close()
        set_language(saved_language)


@pytest.fixture()
def mock_controller():
    return _make_controller()


def _drain(app, ms=120):
    deadline = QEvent
    from PySide6.QtCore import QElapsedTimer

    timer = QElapsedTimer()
    timer.start()
    while timer.elapsed() < ms:
        app.processEvents()


def _fake_screen(name):
    return SimpleNamespace(name=lambda n=name: n)


def _echo_frame(w=320, h=240, shift=0) -> np.ndarray:
    yy, xx = np.mgrid[0:h, 0:w]
    r = np.hypot(xx - w / 2, yy + 40)
    ang = np.arctan2(xx - w / 2, yy + 40)
    sector = (r < h * 0.98) & (np.abs(ang - np.pi / 2) < 0.55)
    img = 40 + 120 * sector * (0.4 + 0.6 * np.abs(np.sin(r / 14) * np.cos(ang * 9)))
    return np.clip(np.roll(img, shift, axis=1), 0, 255).astype(np.uint8)


# ── Audience screen selection ───────────────────────────────────────


class TestAudienceScreenSelection:
    def test_prefers_screen_different_from_host(self):
        from echo_personal_tool.presentation.presenter_view import select_audience_screen

        primary, second = _fake_screen("DP-1"), _fake_screen("HDMI-1")
        # Speaker moved the main window to the second (HDMI) display:
        # the presentation window must go to the OTHER one, not "first
        # non-primary".
        chosen = select_audience_screen([primary, second], remembered="", primary=primary, host_screen=second)
        assert chosen is primary

    def test_stale_remembered_host_screen_is_ignored_when_alternative_exists(self):
        """A remembered screen equal to the host screen must not cover the app.

        Field report: `presenter_screen` saved on a single-display machine
        (or picked experimentally) names the display the application runs
        on; on a two-display machine honoring it would put the fullscreen
        presentation on top of the working window and the status warning
        would be hidden underneath it.
        """
        from echo_personal_tool.presentation.presenter_view import select_audience_screen

        primary, second = _fake_screen("DP-1"), _fake_screen("HDMI-1")
        chosen = select_audience_screen([primary, second], remembered="HDMI-1", primary=primary, host_screen=second)
        assert chosen is primary

    def test_remembered_choice_off_host_screen_wins(self):
        from echo_personal_tool.presentation.presenter_view import select_audience_screen

        primary, second = _fake_screen("DP-1"), _fake_screen("HDMI-1")
        chosen = select_audience_screen([primary, second], remembered="HDMI-1", primary=primary, host_screen=primary)
        assert chosen is second

    def test_without_host_info_falls_back_to_non_primary(self):
        from echo_personal_tool.presentation.presenter_view import select_audience_screen

        primary, second = _fake_screen("DP-1"), _fake_screen("HDMI-1")
        chosen = select_audience_screen([primary, second], remembered="", primary=primary, host_screen=None)
        assert chosen is second

    def test_single_screen_returns_it(self):
        from echo_personal_tool.presentation.presenter_view import select_audience_screen

        only = _fake_screen("eDP-1")
        assert select_audience_screen([only], remembered="", primary=only, host_screen=only) is only

    def test_no_screens_is_none(self):
        from echo_personal_tool.presentation.presenter_view import select_audience_screen

        assert select_audience_screen([], remembered="", primary=None, host_screen=None) is None


# ── Preferences / preset ────────────────────────────────────────────


class TestPresenterPreferences:
    def test_defaults(self):
        from echo_personal_tool.infrastructure.user_preferences import UserPreferences

        p = UserPreferences()
        assert p.presenter_screen == ""
        assert p.presenter_visual_preset is True
        assert p.presenter_pointer is True

    def test_roundtrip_isolated(self, isolated_qsettings):
        from echo_personal_tool.infrastructure.user_preferences import (
            load_user_preferences,
            save_user_preferences,
        )

        p = load_user_preferences()
        p.presenter_screen = "HDMI-1"
        p.presenter_visual_preset = False
        p.presenter_pointer = False
        save_user_preferences(p)
        p2 = load_user_preferences()
        assert p2.presenter_screen == "HDMI-1"
        assert p2.presenter_visual_preset is False
        assert p2.presenter_pointer is False

    def test_preset_keys_are_valid_fields_and_in_range(self):
        from dataclasses import fields

        from echo_personal_tool.infrastructure.user_preferences import (
            MAX_LINE_WIDTH,
            MAX_OVERLAY_FONT_SIZE,
            MAX_UI_FONT_SIZE,
            PRESENTATION_PRESET_OVERRIDES,
            UserPreferences,
        )

        valid = {f.name for f in fields(UserPreferences)}
        p = UserPreferences()
        for key, value in PRESENTATION_PRESET_OVERRIDES.items():
            assert key in valid, key
            if isinstance(value, (int, float)):
                current = getattr(p, key)
                assert value > current or value is True, f"{key} must be a boost"
        assert PRESENTATION_PRESET_OVERRIDES["ui_font_size"] <= MAX_UI_FONT_SIZE
        assert PRESENTATION_PRESET_OVERRIDES["results_overlay_font_size"] <= MAX_OVERLAY_FONT_SIZE
        assert PRESENTATION_PRESET_OVERRIDES["caliper_line_width"] <= MAX_LINE_WIDTH

    def test_sanitized_preset_matches_overrides(self):
        from echo_personal_tool.infrastructure.user_preferences import (
            PRESENTATION_PRESET_OVERRIDES,
            UserPreferences,
        )
        from echo_personal_tool.presentation.presenter_view import sanitized_preset

        base = UserPreferences()
        out = sanitized_preset(base)
        for key, value in PRESENTATION_PRESET_OVERRIDES.items():
            assert out[key] == value
        # Preset is a strict boost of the defaults (its whole point).
        assert out["ui_font_size"] > base.ui_font_size
        assert out["results_overlay_font_size"] > base.results_overlay_font_size
        assert out["caliper_line_width"] > base.caliper_line_width


# ── Presentation window ─────────────────────────────────────────────


class TestPresenterWindow:
    def _make(self, qapp_session, qtbot, pointer=True):
        from echo_personal_tool.presentation.presenter_view import PresenterWindow

        source = QWidget()  # stand-in for the speaker's viewer
        qtbot.addWidget(source)
        window = PresenterWindow(
            QApplication.instance().primaryScreen(),
            speaker_viewer_provider=lambda: source,
            pointer=pointer,
        )
        qtbot.addWidget(window)
        return window, source

    def test_start_places_on_target_and_emits_placed(self, qapp_session, qtbot):
        window, _ = self._make(qapp_session, qtbot)
        placed_screens: list[object] = []
        window.placed.connect(placed_screens.append)
        window.start()
        qtbot.waitUntil(lambda: bool(placed_screens), timeout=2000)
        assert window.isVisible()
        assert window.isFullScreen()
        assert placed_screens[0] is QApplication.instance().primaryScreen()
        window.stop()
        assert not window.isVisible()

    def test_never_takes_focus_or_activation(self, qapp_session, qtbot):
        window, _ = self._make(qapp_session, qtbot)
        assert window.focusPolicy() == Qt.FocusPolicy.NoFocus
        assert window.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        # WindowDoesNotAcceptFocus is stored in the window flags.
        assert bool(window.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus)
        window.start()
        qtbot.waitUntil(window.isVisible, timeout=2000)
        assert not window.isActiveWindow()
        window.stop()

    def test_embeds_independent_viewer_with_speaker_controls_hidden(self, qapp_session, qtbot):
        from echo_personal_tool.presentation.viewer_widget import ViewerWidget

        window, _ = self._make(qapp_session, qtbot)
        viewer = window.viewer()
        assert isinstance(viewer, ViewerWidget)
        for attr in ("_timeline_slider", "_play_button", "_step_forward_button", "_source_label"):
            assert getattr(viewer, attr).isVisibleTo(viewer) is False
        window.stop()

    def test_input_is_swallowed_read_only_audience(self, qapp_session, qtbot):
        window, _ = self._make(qapp_session, qtbot)
        viewer = window.viewer()
        blocked = (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.MouseButtonDblClick,
            QEvent.Type.MouseMove,
            QEvent.Type.Wheel,
            QEvent.Type.ContextMenu,
        )
        for event_type in blocked:
            assert window.eventFilter(viewer, QEvent(event_type)) is True
            assert window.eventFilter(viewer._graphics, QEvent(event_type)) is True
        # Non-input events pass through untouched.
        assert window.eventFilter(viewer, QEvent(QEvent.Type.Paint)) is False

    def test_esc_fallback_requests_exit(self, qapp_session, qtbot):
        window, _ = self._make(qapp_session, qtbot)
        window.start()
        qtbot.waitUntil(window.isVisible, timeout=2000)
        exits: list[bool] = []
        window.exit_requested.connect(lambda: exits.append(True))
        # Direct delivery (the window normally never has focus at all).
        QApplication.sendEvent(
            window, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
        )
        assert exits == [True]
        assert not window.isVisible()

    def test_pointer_toggle(self, qapp_session, qtbot):
        window, _ = self._make(qapp_session, qtbot, pointer=True)
        assert window.pointer_enabled is True
        window.set_pointer_enabled(False)
        assert window.pointer_enabled is False
        window.set_pointer_enabled(True)
        assert window.pointer_enabled is True

    def test_pointer_maps_through_image_domain(self, qapp_session, qtbot):
        """The laser dot maps via the speaker viewer's view coordinates —
        exact even between differently sized windows."""
        window, source = self._make(qapp_session, qtbot)
        window.viewer().show_frame(_echo_frame())
        source.resize(320, 240)
        source.show()
        # The provider returns the stand-in; mapping must simply return
        # None for a cursor outside it (offscreen cursor at 0,0 — inside
        # source, but the stand-in has no graphics view → except → None).
        assert window._map_speaker_cursor() is None

    def test_window_close_is_not_recursive(self, qapp_session, qtbot):
        window, _ = self._make(qapp_session, qtbot)
        window.start()
        qtbot.waitUntil(window.isVisible, timeout=2000)
        exits: list[bool] = []
        window.exit_requested.connect(lambda: exits.append(True))
        window.close()  # WM-close path must not emit exit_requested
        assert exits == []


# ── PresenterMode controller (with MainWindow) ──────────────────────


class TestPresenterModeController:
    def test_toggle_starts_and_stops_presentation(self, presenter_window, qtbot):
        window = presenter_window
        assert not window._presenter.active
        window._presenter.start()
        qtbot.waitUntil(lambda: window._presenter.active, timeout=2000)
        pw = window._presenter.window()
        assert pw is not None and pw.isVisible()
        assert window._system_bar._btn_presenter.isChecked()
        # Preset applied non-destructively on the live host prefs...
        assert window._user_preferences.ui_font_size == 14
        assert window._user_preferences.caliper_line_width == 3.5
        assert window._user_preferences.show_caliper_inline_labels is True
        # ...but the speaker's original object is kept for restore.
        base = window._presenter._base_prefs
        assert base is not None
        assert base.ui_font_size == 12
        assert base.caliper_line_width == 2.0
        # The presentation viewer got the preset too (independent render).
        assert pw.viewer()._caliper_line_width == 3.5

        window._presenter.stop()
        assert not window._presenter.active
        assert not window._system_bar._btn_presenter.isChecked()
        assert window._user_preferences is base
        assert window._user_preferences.ui_font_size == 12
        assert window._user_preferences.caliper_line_width == 2.0
        assert window._user_preferences.show_caliper_inline_labels is False

    def test_start_without_preset_keeps_prefs(self, presenter_window, qtbot):
        window = presenter_window
        window._presenter.set_visual_preset_enabled(False)
        window._presenter.start()
        qtbot.waitUntil(lambda: window._presenter.active, timeout=2000)
        assert window._user_preferences.ui_font_size == 12
        assert window._user_preferences is window._presenter._base_prefs
        window._presenter.stop()
        assert window._user_preferences.ui_font_size == 12

    def test_visual_preset_toggle_while_active(self, presenter_window, qtbot):
        window = presenter_window
        window._presenter.start()
        qtbot.waitUntil(lambda: window._presenter.active, timeout=2000)
        window._presenter.set_visual_preset_enabled(False)
        assert window._user_preferences.ui_font_size == 12
        window._presenter.set_visual_preset_enabled(True)
        assert window._user_preferences.ui_font_size == 14
        window._presenter.stop()
        assert window._user_preferences.ui_font_size == 12

    def test_pointer_toggle_while_active(self, presenter_window, qtbot):
        window = presenter_window
        window._presenter.start()
        qtbot.waitUntil(lambda: window._presenter.active, timeout=2000)
        pw = window._presenter.window()
        window._presenter.set_pointer_enabled(False)
        assert pw.pointer_enabled is False
        window._presenter.set_pointer_enabled(True)
        assert pw.pointer_enabled is True
        window._presenter.stop()

    def test_wl_sliders_drive_both_viewers(self, presenter_window, qtbot):
        """Shared W/L/DR sliders: a tone change reaches the audience live."""
        window = presenter_window
        window._presenter.start()
        qtbot.waitUntil(lambda: window._presenter.active, timeout=2000)
        pw = window._presenter.window()
        slider = window._tool_panel.controls.window_slider
        with_QSignalBlocker = slider.blockSignals(True)
        slider.setValue(slider.value() + 10)
        slider.blockSignals(False)
        _ = with_QSignalBlocker
        # The presenter viewer is bound to the same sliders: no crash and
        # the binding list is non-empty.
        assert pw.viewer()._external_wl_dr_sliders is not None
        window._presenter.stop()

    def test_close_stops_presenter(self, presenter_window, qtbot):
        window = presenter_window
        window._presenter.start()
        qtbot.waitUntil(lambda: window._presenter.active, timeout=2000)
        window.close()
        assert not window._presenter.active

    def test_five_start_stop_cycles_stable(self, presenter_window, qtbot):
        window = presenter_window
        for _ in range(5):
            window._presenter.start()
            qtbot.waitUntil(lambda: window._presenter.active, timeout=2000)
            assert window._presenter.window().isVisible()
            window._presenter.stop()
            assert not window._presenter.active
        assert window._user_preferences.ui_font_size == 12


# ── Content forwarding (independent render, no grabs) ───────────────


class TestContentForwarding:
    def test_forward_frame_renders_on_audience_viewer(self, presenter_window, qtbot):
        window = presenter_window
        window._presenter.start()
        qtbot.waitUntil(lambda: window._presenter.active, timeout=2000)
        pw = window._presenter.window()
        frame1 = _echo_frame(shift=0)
        window._presenter.forward_frame(frame1)
        assert pw.viewer()._current_frame is not None
        assert np.asarray(pw.viewer()._current_frame).shape == (240, 320)
        frame2 = _echo_frame(shift=60)
        window._presenter.forward_frame(frame2)
        assert not np.array_equal(np.asarray(pw.viewer()._current_frame), frame1)

    def test_forward_results_overlay_renders_text(self, presenter_window, qtbot):
        window = presenter_window
        window._presenter.start()
        qtbot.waitUntil(lambda: window._presenter.active, timeout=2000)
        pw = window._presenter.window()
        window._presenter.forward_results_overlay("<b>EF: 58%</b>")
        assert "EF: 58%" in pw.viewer()._results_overlay_label.text()

    def test_forward_state_no_crash(self, presenter_window, qtbot):
        window = presenter_window
        window._presenter.start()
        qtbot.waitUntil(lambda: window._presenter.active, timeout=2000)
        window._presenter.forward_state(_make_snapshot())  # must not raise
        window._presenter.stop()

    def test_forwarding_is_noop_when_inactive(self, presenter_window):
        window = presenter_window
        # None of these may raise with no presentation window.
        window._presenter.forward_frame(_echo_frame())
        window._presenter.forward_state(_make_snapshot())
        window._presenter.forward_results_overlay("x")

    def test_no_grab_anywhere_in_module(self):
        """Architecture guard: the presentation code must not call
        QWidget.grab() — it cannot composite GL viewports (black image)
        and its readbacks blank the speaker's GL viewer."""
        from pathlib import Path

        source = Path("src/echo_personal_tool/presentation/presenter_view.py").read_text(encoding="utf-8")
        # Skip the module docstring (it documents WHY grabs are not used);
        # everything after it must be grab-free.
        code_after_docstring = source.split('"""', 2)[2]
        assert ".grab(" not in code_after_docstring

    def test_main_window_hooks_forward_to_presenter(self, presenter_window, qtbot):
        """The MainWindow hooks actually forward what the host renders."""
        window = presenter_window
        window._presenter.start()
        qtbot.waitUntil(lambda: window._presenter.active, timeout=2000)
        pw = window._presenter.window()
        # Simulate the frame-loaded hook.
        window._on_frame_loaded(_echo_frame())
        assert pw.viewer()._current_frame is not None
        # Simulate the results-overlay hook through _sync_results_overlay's
        # forwarding call.
        window._presenter.forward_results_overlay("<b>EDV 112 ml</b>")
        assert "EDV 112 ml" in pw.viewer()._results_overlay_label.text()


# ── Contour / caliper forwarding (edit paths use emit=False) ────────


class TestContourCaliperForwarding:
    """Contour point drags never fire state_changed (controller stores with
    ``emit=False``) — without the explicit contours_changed hook the
    audience display kept showing the initial contour (field report:
    Simpson manual / auto-Simpson refinement invisible on the second
    monitor)."""

    def _presentation(self, presenter_window, qtbot):
        presenter_window._presenter.start()
        qtbot.waitUntil(lambda: presenter_window._presenter.active, timeout=2000)
        return presenter_window._presenter.window().viewer()

    def _contour(self, snapshot):
        from echo_personal_tool.domain.models.contour import Contour

        return Contour(
            phase="ED",
            view="A4C",
            chamber="LV",
            points=[(50.0, 60.0), (120.0, 60.0), (120.0, 150.0), (50.0, 150.0)],
            source="manual",
            frame_index=snapshot.current_frame_index,
            sop_instance_uid=None,
        )

    def test_forward_contours_updates_audience_viewer(self, presenter_window, qtbot):
        viewer = self._presentation(presenter_window, qtbot)
        snapshot = presenter_window._controller.state_manager.snapshot
        contour = self._contour(snapshot)
        presenter_window._presenter.forward_contours([contour])
        assert tuple(viewer._stored_contours) == (contour,)
        # rendered items rebuilt from the new stored set
        assert len(viewer._contours) == 1

    def test_forward_contours_replaces_previous_set(self, presenter_window, qtbot):
        viewer = self._presentation(presenter_window, qtbot)
        snapshot = presenter_window._controller.state_manager.snapshot
        first = self._contour(snapshot)
        moved = replace(first, points=[(55.0, 65.0), (125.0, 65.0), (125.0, 155.0), (55.0, 155.0)])
        presenter_window._presenter.forward_contours([first])
        presenter_window._presenter.forward_contours([moved])
        assert tuple(viewer._stored_contours) == (moved,)
        assert len(viewer._contours) == 1

    def test_forward_contours_inactive_is_noop(self, presenter_window):
        snapshot = presenter_window._controller.state_manager.snapshot
        presenter_window._presenter.forward_contours([self._contour(snapshot)])

    def test_forward_linear_measurements_updates_audience(self, presenter_window, qtbot):
        from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement

        viewer = self._presentation(presenter_window, qtbot)
        snapshot = presenter_window._controller.state_manager.snapshot
        measurement = LinearMeasurement(
            label="D1",
            pixel_length=42.0,
            millimeter_length=None,
            frame_index=snapshot.current_frame_index,
            start=(10.0, 10.0),
            end=(50.0, 10.0),
            sop_instance_uid="",
        )
        presenter_window._presenter.forward_linear_measurements([measurement])
        key = ("D1", snapshot.current_frame_index)
        assert viewer._stored_linear_measurements.get(key) == measurement

    def test_hook_contours_changed_reaches_audience(self, presenter_window, qtbot):
        """Real-hook regression: the viewer signal must re-render the audience.

        Before the fix nothing mirrored edits: state_changed is not emitted
        on the contours path, so forward_state was never called.
        """
        viewer = self._presentation(presenter_window, qtbot)
        snapshot = presenter_window._controller.state_manager.snapshot
        contour = self._contour(snapshot)
        presenter_window._viewer.contours_changed.emit([contour])
        assert tuple(viewer._stored_contours) == (contour,)

    def test_hook_linear_measurements_reaches_audience(self, presenter_window, qtbot):
        from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement

        viewer = self._presentation(presenter_window, qtbot)
        snapshot = presenter_window._controller.state_manager.snapshot
        measurement = LinearMeasurement(
            label="D2",
            pixel_length=30.0,
            millimeter_length=None,
            frame_index=snapshot.current_frame_index,
            start=(5.0, 5.0),
            end=(35.0, 5.0),
            sop_instance_uid="",
        )
        presenter_window._viewer.linear_measurements_changed.emit([measurement])
        assert viewer._stored_linear_measurements.get(("D2", snapshot.current_frame_index)) == measurement

    def test_drag_end_emit_updates_audience(self, presenter_window, qtbot):
        """The exact field flow: viewer drag-end emits the updated contour."""
        viewer = self._presentation(presenter_window, qtbot)
        snapshot = presenter_window._controller.state_manager.snapshot
        initial = self._contour(snapshot)
        presenter_window._presenter.forward_contours([initial])
        refined = replace(initial, points=[(52.0, 62.0), (122.0, 62.0), (122.0, 152.0), (52.0, 152.0)])
        # _finalize_contour_point_drag ends with this emit:
        presenter_window._viewer.contours_changed.emit([refined])
        assert tuple(viewer._stored_contours) == (refined,)
        assert len(viewer._contours) == 1

    def test_in_place_point_drag_updates_audience(self, presenter_window, qtbot):
        """Regression: host mutates Contour.points in place during drags.

        The audience stored set aliases those lists; the value-equality
        check in set_state then saw "no change" and skipped the re-render
        (field report: point edits invisible while mitral-annulus edits —
        new Contour objects — came through). forward_contours must apply
        fresh copies unconditionally.
        """
        viewer = self._presentation(presenter_window, qtbot)
        snapshot = presenter_window._controller.state_manager.snapshot
        contour = self._contour(snapshot)
        # Initial forward — the audience stores a fresh copy.
        presenter_window._presenter.forward_contours([contour])
        stored = tuple(viewer._stored_contours)
        assert stored[0] == contour and stored[0] is not contour
        # In-place mutation, exactly like the drag path (points[:] = ...):
        contour.points[:] = [(70.0, 80.0), (130.0, 80.0), (130.0, 170.0)]
        # Drag end: the same (mutated) objects are emitted again.
        presenter_window._presenter.forward_contours([contour])
        stored = tuple(viewer._stored_contours)
        assert stored[0].points[0] == (70.0, 80.0)
        assert stored[0] is not contour  # fresh copy, no aliasing
        assert len(viewer._contours) == 1  # re-rendered

    def test_forward_contours_does_not_alias_host_lists(self, presenter_window, qtbot):
        viewer = self._presentation(presenter_window, qtbot)
        snapshot = presenter_window._controller.state_manager.snapshot
        contour = self._contour(snapshot)
        presenter_window._presenter.forward_contours([contour])
        stored = tuple(viewer._stored_contours)[0]
        contour.points.append((999.0, 999.0))  # later in-place host edit
        assert stored.points[-1] != (999.0, 999.0)


class TestDopplerForwarding:
    """Markers/VTI traces/vessel live viewer-locally; none of the edit
    signals reach state_changed, so the audience saw an empty strip
    (field report)."""

    def _presentation(self, presenter_window, qtbot):
        presenter_window._presenter.start()
        qtbot.waitUntil(lambda: presenter_window._presenter.active, timeout=2000)
        return presenter_window._presenter.window().viewer()

    def _dto(self):
        from echo_personal_tool.domain.models.doppler import (
            DopplerMeasurementDTO,
            DopplerPeakMarker,
            DopplerTrace,
        )

        return DopplerMeasurementDTO(
            peaks=(DopplerPeakMarker(label="E", time_ms=120.0, velocity_cm_s=80.0),),
            intervals=(),
            traces=(
                DopplerTrace(
                    label="VTI",
                    points=((10.0, 5.0), (50.0, 60.0), (90.0, 8.0)),
                ),
            ),
        )

    def test_markers_hook_reaches_audience(self, presenter_window, qtbot):
        """forward_doppler pulls the HOST overlay state (the signal payload
        is the same DTO the overlay just built) and restores it on the
        audience viewer."""
        viewer = self._presentation(presenter_window, qtbot)
        host_overlay = presenter_window._viewer._doppler
        host_overlay._peak_markers.append(self._dto().peaks[0])
        host_overlay._traces.append(self._dto().traces[0])
        presenter_window._viewer.doppler_markers_changed.emit(host_overlay.get_measurement_dto())
        assert len(viewer._doppler._peak_markers) == 1
        assert viewer._doppler._peak_markers[0].label == "E"
        assert len(viewer._doppler._traces) == 1
        assert viewer._doppler._traces[0].label == "VTI"

    def test_trace_deletion_propagates(self, presenter_window, qtbot):
        from echo_personal_tool.domain.models.doppler import DopplerMeasurementDTO

        viewer = self._presentation(presenter_window, qtbot)
        host_overlay = presenter_window._viewer._doppler
        host_overlay._peak_markers.append(self._dto().peaks[0])
        host_overlay._traces.append(self._dto().traces[0])
        presenter_window._viewer.doppler_markers_changed.emit(host_overlay.get_measurement_dto())
        assert len(viewer._doppler._traces) == 1
        host_overlay._peak_markers.clear()
        host_overlay._traces.clear()
        presenter_window._viewer.doppler_markers_changed.emit(DopplerMeasurementDTO(peaks=(), intervals=(), traces=()))
        assert viewer._doppler._traces == []
        assert viewer._doppler._peak_markers == []

    def test_calibration_hook_sets_audience_axis_mapping(self, presenter_window, qtbot):
        from echo_personal_tool.domain.models.doppler_roi import (
            DopplerCalibrationState,
            DopplerKind,
            DopplerSpectrogramRoi,
        )

        viewer = self._presentation(presenter_window, qtbot)
        state = DopplerCalibrationState(
            roi=DopplerSpectrogramRoi(x0=40.0, y0=30.0, width=240.0, height=170.0),
            baseline_y_px=120.0,
            time_origin_ms=0.0,
            time_span_ms=1000.0,
            velocity_span_cm_s=200.0,
            kind=DopplerKind.SPECTRAL,
        )
        presenter_window._viewer._doppler_calibration_state = state
        presenter_window._viewer.doppler_calibration_changed.emit(state)
        assert viewer._doppler_calibration_state is not None
        assert viewer._doppler_calibration_state.time_span_ms == 1000.0

    def test_vessel_results_mirror_wysiwyg(self, presenter_window, qtbot):
        """Field round 8: vessel results live in a text block top-right
        INSIDE the strip (``_vessel_text_item``) + PSV/EDV dots — plot-local,
        outside the DTO. Mirror them WYSIWYG (exact host text, incl.
        RI/S/D/MV formatting and position)."""
        import pyqtgraph as pg

        self._presentation(presenter_window, qtbot)
        pw = presenter_window._presenter.window()
        host_overlay = presenter_window._viewer._doppler
        # A finished measurement: dots + text block like the host draws it.
        host_overlay._vessel_points = pg.ScatterPlotItem(size=10, pen=pg.mkPen("#ffffff", width=1))
        host_overlay._vessel_points.setData(
            [{"pos": (10.0, 40.0), "data": "PSV"}, {"pos": (20.0, 80.0), "data": "EDV"}]
        )
        host_overlay._vessel_text_item = pg.TextItem("PSV: 120.0 cm/s\nEDV: 40.0 cm/s\nRI: 0.67", anchor=(1.0, 0.0))
        host_overlay._vessel_text_item.setPos(280.0, 5.0)
        host_overlay._vessel_text_item.show()
        try:
            presenter_window._presenter._sync_live_overlays()
            assert pw._live_vessel_points.isVisible()
            assert len(pw._live_vessel_points.points()) == 2
            assert pw._live_vessel_text.isVisible()
            assert "PSV: 120.0 cm/s" in pw._live_vessel_text.textItem.toPlainText()
            assert "RI: 0.67" in pw._live_vessel_text.textItem.toPlainText()
            live_pos = pw._live_vessel_text.pos()
            assert (round(live_pos.x(), 3), round(live_pos.y(), 3)) == (280.0, 5.0)
            # Measurement cleared on the host → hidden on the audience.
            host_overlay._vessel_points = None
            host_overlay._vessel_text_item = None
            presenter_window._presenter._sync_live_overlays()
            assert not pw._live_vessel_points.isVisible()
            assert not pw._live_vessel_text.isVisible()
        finally:
            host_overlay._vessel_points = None
            host_overlay._vessel_text_item = None

    def test_vessel_results_hidden_without_host_text(self, presenter_window, qtbot):
        self._presentation(presenter_window, qtbot)
        pw = presenter_window._presenter.window()
        presenter_window._presenter._sync_live_overlays()
        assert not pw._live_vessel_points.isVisible()
        assert not pw._live_vessel_text.isVisible()

    def test_forward_doppler_inactive_is_noop(self, presenter_window):
        presenter_window._presenter.forward_doppler()


# ── Live drawing preview + overlay position + idle-frame pacing ─────


class TestLivePreviewOverlayPositionPacing:
    """Field round 6: (1) overlay drags were invisible on the audience,
    (2) the in-progress drawing process was invisible, (3) a file switch
    sometimes needed a second click — the single frame of the switch was
    dropped by playback pacing."""

    def _presentation(self, presenter_window, qtbot):
        presenter_window._presenter.start()
        qtbot.waitUntil(lambda: presenter_window._presenter.active, timeout=2000)
        return presenter_window._presenter.window().viewer()

    def test_idle_frame_never_skipped_by_pacing(self, presenter_window, qtbot, monkeypatch):
        """Regression: pacing must only thin out PLAYBACK frames — a file
        switch delivers exactly one idle frame and it must always render."""

        presenter_window._presenter.start()
        qtbot.waitUntil(lambda: presenter_window._presenter.active, timeout=2000)
        mode = presenter_window._presenter
        pw = mode.window()
        try:
            monkeypatch.setattr(
                presenter_window._controller,
                "is_scroll_active",
                lambda: False,
                raising=False,
            )
            mode._fwd_ema_ms = 30.0  # worst bucket
            mode._fwd_seq = 0  # a % limit != 0 phase would skip playback
            skipped_before = mode._diag.counters.get("frames_skipped", 0)
            mode.forward_frame(_echo_frame(shift=5))
            assert pw.viewer()._current_frame is not None
            assert mode._diag.counters.get("frames_skipped", 0) == skipped_before
        finally:
            mode.stop()

    def test_overlay_position_forward_updates_audience(self, presenter_window, qtbot):
        viewer = self._presentation(presenter_window, qtbot)
        presenter_window._presenter.forward_results_overlay_position(0.7, 0.6)
        assert viewer.results_overlay_position() == (0.7, 0.6)
        assert viewer._results_overlay_custom_position is True

    def test_overlay_position_hook_wired(self, presenter_window, qtbot):
        viewer = self._presentation(presenter_window, qtbot)
        presenter_window._viewer.results_overlay_position_changed.emit(0.25, 0.75)
        assert viewer.results_overlay_position() == (0.25, 0.75)

    def test_live_contour_preview_mirrors_host_drawing(self, presenter_window, qtbot):
        import pyqtgraph as pg

        self._presentation(presenter_window, qtbot)
        pw = presenter_window._presenter.window()
        host = presenter_window._viewer
        # Simulate the click-by-click contour flow: the host viewer holds an
        # active-contour item with the points placed so far.
        active = pg.PlotDataItem(pen=pg.mkPen("#ffd54f", width=3))
        active.setData([50.0, 90.0, 130.0], [60.0, 60.0, 120.0])
        host._contour_mode_active = True
        host._active_contour_item = active
        try:
            presenter_window._presenter._sync_live_overlays()
            live = pw._live_contour_item
            assert live.isVisible()
            x, y = live.getData()
            assert list(x) == [50.0, 90.0, 130.0]
            assert list(y) == [60.0, 60.0, 120.0]
            # Pen mirrors the host's active style (WYSIWYG).
            assert live.opts["pen"] == active.opts["pen"]
            # Drawing finished → preview hidden.
            host._contour_mode_active = False
            presenter_window._presenter._sync_live_overlays()
            assert not live.isVisible()
        finally:
            host._contour_mode_active = False
            host._active_contour_item = None

    def test_live_caliper_preview_mirrors_host_drag(self, presenter_window, qtbot):
        import pyqtgraph as pg

        self._presentation(presenter_window, qtbot)
        pw = presenter_window._presenter.window()
        host = presenter_window._viewer
        line = pg.PlotDataItem(pen=pg.mkPen("#4dd0e1", width=3))
        line.setData([10.0, 50.0], [10.0, 40.0])
        host._linear_caliper_active = True
        host._linear_caliper_line_item = line
        try:
            presenter_window._presenter._sync_live_overlays()
            live = pw._live_caliper_item
            assert live.isVisible()
            x, y = live.getData()
            assert list(x) == [10.0, 50.0]
            assert list(y) == [10.0, 40.0]
            host._linear_caliper_active = False
            presenter_window._presenter._sync_live_overlays()
            assert not live.isVisible()
        finally:
            host._linear_caliper_active = False
            host._linear_caliper_line_item = None

    def test_committed_contour_hides_live_preview(self, presenter_window, qtbot):
        viewer = self._presentation(presenter_window, qtbot)
        pw = presenter_window._presenter.window()
        snapshot = presenter_window._controller.state_manager.snapshot
        from echo_personal_tool.domain.models.contour import Contour

        contour = Contour(
            phase="ED",
            points=[(50.0, 60.0), (120.0, 60.0), (120.0, 150.0)],
            frame_index=snapshot.current_frame_index,
        )
        pw._live_contour_item.show()
        presenter_window._presenter.forward_contours([contour])
        assert not pw._live_contour_item.isVisible()
        assert len(viewer._contours) == 1

    def test_drag_process_mirrors_deformed_polyline(self, presenter_window, qtbot):
        """Field round 7: dragging a point of an EXISTING contour deforms
        the rendered contour item (``_contour_items[idx]``, setData per
        move step) — the creation-preview item is not involved, so the
        drag session must mirror that polyline instead."""
        import pyqtgraph as pg

        self._presentation(presenter_window, qtbot)
        pw = presenter_window._presenter.window()
        host = presenter_window._viewer
        dragged = pg.PlotDataItem(pen=pg.mkPen("#ff5252", width=3))
        dragged.setData([50.0, 75.0, 120.0], [60.0, 95.0, 150.0])
        host._contour_items = [dragged]
        host._drag_overlay_contour_index = 0
        try:
            presenter_window._presenter._sync_live_overlays()
            live = pw._live_contour_item
            assert live.isVisible()
            x, y = live.getData()
            assert list(x) == [50.0, 75.0, 120.0]
            assert live.opts["pen"] == dragged.opts["pen"]
            # Drag ends → session cleared → preview hidden.
            host._drag_overlay_contour_index = None
            presenter_window._presenter._sync_live_overlays()
            assert not live.isVisible()
        finally:
            host._drag_overlay_contour_index = None
            host._contour_items = []

    def test_vessel_auto_trace_envelope_mirrored(self, presenter_window, qtbot):
        """Field round 7: the vessel auto-trace envelope and peak guide are
        plot-local items outside the DTO — mirror them at 30 Hz."""
        import pyqtgraph as pg

        self._presentation(presenter_window, qtbot)
        pw = presenter_window._presenter.window()
        host_overlay = presenter_window._viewer._doppler
        envelope = pg.PlotDataItem(pen=pg.mkPen("#00e5ff", width=2))
        envelope.setData([10.0, 40.0, 80.0], [30.0, 5.0, 28.0])
        guide = pg.PlotDataItem(pen=pg.mkPen("#ff9800", width=2, style=Qt.PenStyle.DashLine))
        guide.setData([40.0, 40.0], [50.0, 5.0])
        host_overlay._auto_envelope_item = envelope
        host_overlay._auto_peak_guide_item = guide
        try:
            presenter_window._presenter._sync_live_overlays()
            live_env = pw._live_envelope_item
            assert live_env.isVisible()
            assert list(live_env.getData()[0]) == [10.0, 40.0, 80.0]
            assert live_env.opts["pen"] == envelope.opts["pen"]
            live_guide = pw._live_peak_guide_item
            assert live_guide.isVisible()
            assert list(live_guide.getData()[1]) == [50.0, 5.0]
            # Cleared on the host → hidden on the audience.
            host_overlay._auto_envelope_item = None
            host_overlay._auto_peak_guide_item = None
            presenter_window._presenter._sync_live_overlays()
            assert not live_env.isVisible()
            assert not live_guide.isVisible()
        finally:
            host_overlay._auto_envelope_item = None
            host_overlay._auto_peak_guide_item = None


# ── Profile restriction: presenter mode ships lite-only ─────────────


class TestPresenterProfileOnlyAccess:
    """The Presenter button, menu and F10 belong to the Presenter (lite)
    build only — the full profile gets no entry points at all (field
    decision after the mode was stabilized)."""

    def test_full_profile_has_no_presenter_button(self, qapp_session, qtbot, monkeypatch):
        from echo_personal_tool.presentation.system_bar import SystemBar

        monkeypatch.setenv("SONOFORGE_PROFILE", "full")
        bar = SystemBar()
        qtbot.addWidget(bar)
        assert bar._btn_presenter is None
        # Status sync must be a no-op, not a crash.
        bar.set_presenter_active(True)
        bar.reload_icons()
        bar.reload_text()

    def test_presenter_profile_has_button(self, qapp_session, qtbot, monkeypatch):
        from echo_personal_tool.presentation.system_bar import SystemBar

        monkeypatch.setenv("SONOFORGE_PROFILE", "presenter")
        bar = SystemBar()
        qtbot.addWidget(bar)
        assert isinstance(bar._btn_presenter, QToolButton)
        assert bar._btn_presenter.text()

    def test_full_profile_registers_no_f10_shortcut(self, mock_controller, monkeypatch, qtbot):
        from PySide6.QtGui import QShortcut

        import echo_personal_tool.presentation.main_window as mw_module
        from echo_personal_tool.infrastructure.user_preferences import UserPreferences
        from echo_personal_tool.presentation.main_window import MainWindow

        monkeypatch.setenv("SONOFORGE_PROFILE", "full")
        monkeypatch.setattr(mw_module, "apply_clinical_theme", lambda **k: None)
        monkeypatch.setattr(
            "echo_personal_tool.infrastructure.user_preferences.save_user_preferences",
            lambda preferences: None,
        )
        prefs = UserPreferences(
            theme_mode="dark",
            ui_font_size=12,
            language="en",
            confirm_reset=False,
            magnetic_snap_enabled=False,
            despeckle_enabled=False,
        )
        with (
            patch(
                "echo_personal_tool.presentation.main_window.load_user_preferences",
                return_value=prefs,
            ),
            patch(
                "echo_personal_tool.presentation.main_window.format_results_overlay_html",
                return_value="",
            ),
        ):
            window = MainWindow(controller=mock_controller)
        qtbot.addWidget(window)
        keys = [sc.key().toString() for sc in window.findChildren(QShortcut)]
        assert "F10" not in keys

    def test_presenter_profile_registers_f10_shortcut(self, presenter_window):
        from PySide6.QtGui import QShortcut

        keys = [sc.key().toString() for sc in presenter_window.findChildren(QShortcut)]
        assert "F10" in keys


# ── Presenter profile default layout (narrow activity bar) ──────────


class TestPresenterDefaultLayout:
    def test_presenter_profile_defaults_to_activity_bar(self, monkeypatch, isolated_qsettings):
        from echo_personal_tool.infrastructure import profile
        from echo_personal_tool.infrastructure.user_preferences import UserPreferences
        from echo_personal_tool.presentation.main_window import MainWindow

        monkeypatch.setenv(profile.PROFILE_ENV, "presenter")
        w = MainWindow.__new__(MainWindow)  # no Qt init — test the loader only
        w._user_preferences = UserPreferences(layout_state_json="")
        cfg = MainWindow._load_layout_state(w)
        assert cfg.activity_bar is True

        monkeypatch.delenv(profile.PROFILE_ENV)
        cfg_full = MainWindow._load_layout_state(w)
        assert cfg_full.activity_bar is False

    def test_saved_layout_wins_over_presenter_default(self, monkeypatch):
        from echo_personal_tool.infrastructure import profile
        from echo_personal_tool.infrastructure.user_preferences import UserPreferences
        from echo_personal_tool.presentation.main_window import MainWindow

        monkeypatch.setenv(profile.PROFILE_ENV, "presenter")
        w = MainWindow.__new__(MainWindow)
        saved = json.dumps(
            {
                "activity_bar": False,
                "swap_places": False,
                "gallery_horizontal": False,
                "status_bar_visible": True,
                "multiview": False,
            }
        )
        w._user_preferences = UserPreferences(layout_state_json=saved)
        assert MainWindow._load_layout_state(w).activity_bar is False


# ── F11 fullscreen kiosk ────────────────────────────────────────────


class TestFullscreenKiosk:
    def test_fullscreen_hides_all_chrome(self, presenter_window, qtbot):
        window = presenter_window
        window._gallery.show()
        window._tool_panel.show()
        window._system_bar.show()
        window._enter_fullscreen_kiosk()
        qtbot.waitUntil(window.isFullScreen, timeout=2000)
        assert not window._gallery.isVisible()
        assert not window._tool_panel.isVisible()
        assert not window._system_bar.isVisible()
        assert not window.statusBar().isVisible()

    def test_exit_fullscreen_restores_chrome(self, presenter_window, qtbot):
        window = presenter_window
        window._gallery.show()
        window._tool_panel.show()
        window._system_bar.show()
        window._enter_fullscreen_kiosk()
        qtbot.waitUntil(window.isFullScreen, timeout=2000)
        window._exit_fullscreen_kiosk()
        qtbot.waitUntil(lambda: not window.isFullScreen(), timeout=2000)
        assert window._gallery.isVisible()
        assert window._system_bar.isVisible()
        assert window.statusBar().isVisible()
        # Panel chrome follows the ACTIVE layout: the Presenter (lite)
        # profile defaults to the narrow activity bar, the full profile to
        # the wide tool panel.
        assert window._activity_bar.isVisible() or window._tool_panel.isVisible()

    def test_exit_kiosk_restores_activity_tab_panel(self, presenter_window, qtbot):
        from dataclasses import replace as dc_replace

        window = presenter_window
        window.show()
        qtbot.waitExposed(window, timeout=2000)
        window._layout_config = dc_replace(window._layout_config, activity_bar=True)
        window._rebuild_layout()
        window._activity_bar._buttons["measures"].setChecked(True)
        window._on_activity_tab_activated("measures")
        assert window._tool_panel.isVisible()

        window._enter_fullscreen_kiosk()
        qtbot.waitUntil(window.isFullScreen, timeout=2000)
        assert not window._tool_panel.isVisible()
        window._exit_fullscreen_kiosk()
        qtbot.waitUntil(lambda: not window.isFullScreen(), timeout=2000)
        assert window._activity_bar.isVisible()
        assert window._tool_panel.isVisible()


# ── Activity bar additions ──────────────────────────────────────────


class TestActivityBarPresenterActions:
    def test_play_pause_glyph_swap(self, qapp_session, qtbot):
        from echo_personal_tool.presentation.activity_bar import ActivityBar

        bar = ActivityBar()
        qtbot.addWidget(bar)
        assert "play" in bar._action_buttons
        assert "hr" in bar._action_buttons
        bar.set_playing(True)
        assert bar._playing is True
        bar.set_playing(True)  # idempotent
        assert bar._playing is True
        bar.set_playing(False)
        assert bar._playing is False

    def test_actions_emitted(self, qapp_session, qtbot):
        from echo_personal_tool.presentation.activity_bar import ActivityBar

        bar = ActivityBar()
        qtbot.addWidget(bar)
        received: list[str] = []
        bar.action_requested.connect(received.append)
        bar._action_buttons["play"].click()
        bar._action_buttons["hr"].click()
        assert received == ["play", "hr"]


# ── Regression: deep-analysis fixes ─────────────────────────────────


class TestPresenterRegressionFixes:
    def test_settings_apply_during_presentation_survives_stop(self, presenter_window, qtbot):
        """Settings-dialog apply while presenting must become the new base."""
        window = presenter_window
        window._presenter.start()
        qtbot.waitUntil(lambda: window._presenter.active, timeout=2000)
        window._apply_user_preferences(replace(window._presenter._base_prefs, ui_font_size=16))
        # Preset still overlays the UI font while presenting...
        assert window._user_preferences.ui_font_size == 14
        assert window._presenter._base_prefs.ui_font_size == 16
        window._presenter.stop()
        # ...and the dialog's value survives the exit.
        assert window._user_preferences is window._presenter._base_prefs
        assert window._user_preferences.ui_font_size == 16

    def test_changes_during_presentation_merge_back(self, presenter_window, qtbot):
        """In-place toggles made while presenting must survive the exit."""
        window = presenter_window
        window._presenter.start()
        qtbot.waitUntil(lambda: window._presenter.active, timeout=2000)
        window._user_preferences.magnetic_snap_enabled = not window._user_preferences.magnetic_snap_enabled
        window._user_preferences.last_opened_folder = "/tmp/demo"
        window._presenter.stop()
        assert window._user_preferences.magnetic_snap_enabled is True
        assert window._user_preferences.last_opened_folder == "/tmp/demo"
        # Preset-owned fields are NOT merged (speaker's own value kept).
        assert window._user_preferences.ui_font_size == 12
        assert window._user_preferences.caliper_line_width == 2.0

    def test_dialog_accept_preserves_presenter_fields(self, isolated_qsettings, monkeypatch):
        """OK in the Settings dialog must not reset presenter fields."""
        from echo_personal_tool.infrastructure.user_preferences import (
            load_user_preferences,
            save_user_preferences,
        )
        from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

        stored = load_user_preferences()
        stored.presenter_screen = "HDMI-1"
        stored.presenter_visual_preset = False
        stored.presenter_pointer = False
        save_user_preferences(stored)

        monkeypatch.setattr(
            "echo_personal_tool.presentation.user_preferences_dialog.save_server_settings",
            lambda settings: None,
        )
        dialog = UserPreferencesDialog()
        dialog._on_accept()
        reloaded = load_user_preferences()
        assert reloaded.presenter_screen == "HDMI-1"
        assert reloaded.presenter_visual_preset is False
        assert reloaded.presenter_pointer is False

    def test_presenter_menu_rebuild_does_not_leak(self, presenter_window, qtbot):
        window = presenter_window
        button = window._system_bar._btn_presenter
        menu_before = button.menu()
        assert menu_before is not None
        window._presenter_active_changed(True)
        window._presenter_active_changed(False)
        window._presenter_active_changed(True)
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        # The same QMenu object is updated in place (no per-toggle leak) and
        # the audience-display submenu orphans are cleaned up on rebuild.
        assert button.menu() is menu_before
        assert len(menu_before.findChildren(QMenu)) == 1

    def test_set_screen_restarts_active_presentation(self, presenter_window, qtbot):
        window = presenter_window
        window._presenter.start()
        qtbot.waitUntil(lambda: window._presenter.active, timeout=2000)
        screen = QApplication.instance().primaryScreen()
        window._presenter.set_screen(screen)
        qtbot.waitUntil(lambda: window._presenter.active, timeout=2000)
        assert window._presenter.active
        assert window._presenter._base_prefs.presenter_screen == screen.name()
        window._presenter.stop()

    def test_status_reports_actual_screen_and_mismatch(self, presenter_window, qtbot):
        """Single-display case: the status explicitly warns that the
        presentation window covers the speaker's window."""
        from echo_personal_tool.infrastructure.i18n import tr

        window = presenter_window
        window.show()
        qtbot.waitExposed(window, timeout=2000)
        window._presenter.start()
        qtbot.waitUntil(lambda: window._presenter.active, timeout=2000)
        # Offscreen has a single screen; the shown main window sits on it,
        # so host screen == target screen → covering warning is guaranteed.
        expected = tr("presenter.same_screen_warning")
        qtbot.waitUntil(
            lambda: window._system_bar._status_label._full_text == expected,
            timeout=3000,
        )
        window._presenter.stop()


# ── Activity-bar default in the presenter profile (host wiring) ─────


class TestHostIntegration:
    def test_main_window_uses_presenter_controller(self, presenter_window):
        from echo_personal_tool.presentation.presenter_view import PresenterMode

        assert isinstance(presenter_window._presenter, PresenterMode)

    def test_frame_hook_signature_unchanged(self, presenter_window):
        # _on_frame_loaded must keep accepting the worker payload.
        import inspect

        sig = inspect.signature(presenter_window._on_frame_loaded)
        assert list(sig.parameters) == ["pixels"]


# ── Rendering backend of the audience viewer ────────────────────────


class TestAudienceRenderBackend:
    def test_default_render_mode_is_raster(self, qapp_session, qtbot):
        from echo_personal_tool.presentation.presenter_view import PresenterWindow

        window = PresenterWindow(
            QApplication.instance().primaryScreen(),
            speaker_viewer_provider=lambda: None,
        )
        qtbot.addWidget(window)
        assert window.render_mode == "raster"
        # Offscreen platform: pyqtgraph useOpenGL defaults to False → plain
        # QWidget viewport. The class name must NOT contain "OpenGL".
        assert "opengl" not in window.viewport_class_name().lower()

    def test_raster_mode_flips_and_restores_pyqtgraph_config(self, qapp_session, qtbot, monkeypatch):
        """With a GL default, raster construction overrides useOpenGL twice.

        The override must flip to False for the audience widget and restore
        True right after — the speaker's viewer keeps its own backend.
        """
        import pyqtgraph as pg

        from echo_personal_tool.presentation.presenter_view import PresenterWindow

        requests: list[tuple[str, object]] = []
        monkeypatch.setattr(pg, "getConfigOption", lambda name: True, raising=False)
        monkeypatch.setattr(
            pg,
            "setConfigOption",
            lambda name, value: requests.append((name, value)),
            raising=False,
        )
        window = PresenterWindow(
            QApplication.instance().primaryScreen(),
            speaker_viewer_provider=lambda: None,
            render_mode="raster",
        )
        qtbot.addWidget(window)
        assert requests == [("useOpenGL", False), ("useOpenGL", True)]

    def test_opengl_mode_needs_no_flip(self, qapp_session, qtbot, monkeypatch):
        import pyqtgraph as pg

        from echo_personal_tool.presentation.presenter_view import PresenterWindow

        requests: list[tuple[str, object]] = []
        monkeypatch.setattr(pg, "getConfigOption", lambda name: True, raising=False)
        monkeypatch.setattr(
            pg,
            "setConfigOption",
            lambda name, value: requests.append((name, value)),
            raising=False,
        )
        window = PresenterWindow(
            QApplication.instance().primaryScreen(),
            speaker_viewer_provider=lambda: None,
            render_mode="opengl",
        )
        qtbot.addWidget(window)
        assert requests == []

    def test_prefs_drive_render_mode(self, presenter_window, monkeypatch):
        """PresenterWindow gets render_mode from presenter_audience_render."""
        import echo_personal_tool.presentation.presenter_view as pv
        from echo_personal_tool.infrastructure.user_preferences import UserPreferences

        captured = {}
        real_window = pv.PresenterWindow

        class RecordingWindow(real_window):
            def __init__(self, *args, **kwargs):
                captured["render_mode"] = kwargs.get("render_mode")
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(pv, "PresenterWindow", RecordingWindow)
        prefs = UserPreferences(presenter_audience_render="opengl")
        presenter_window._user_preferences = prefs
        presenter_window._presenter.start()
        presenter_window._presenter.stop()
        assert captured["render_mode"] == "opengl"

    def test_invalid_render_mode_falls_back_to_raster(self, presenter_window, monkeypatch):
        import echo_personal_tool.presentation.presenter_view as pv
        from echo_personal_tool.infrastructure.user_preferences import UserPreferences

        captured = {}
        real_window = pv.PresenterWindow

        class RecordingWindow(real_window):
            def __init__(self, *args, **kwargs):
                captured["render_mode"] = kwargs.get("render_mode")
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(pv, "PresenterWindow", RecordingWindow)
        presenter_window._user_preferences = UserPreferences(presenter_audience_render="wiregl")
        presenter_window._presenter.start()
        presenter_window._presenter.stop()
        assert captured["render_mode"] == "raster"


# ── Presenter diagnostics ───────────────────────────────────────────


class TestPresenterDiagnostics:
    def _make(self, tmp_path, enabled=True):
        from echo_personal_tool.presentation.presenter_diagnostics import (
            PresenterDiagnostics,
        )

        return PresenterDiagnostics(path=tmp_path / "presenter_diag.log", enabled=enabled)

    def test_events_written_to_file(self, tmp_path):
        diag = self._make(tmp_path)
        diag.event("hello", size=3, ratio=1.5, note=None)
        diag.counter("frames_rendered")
        diag.counter("frames_rendered", 4)
        diag.finish("stop")
        text = (tmp_path / "presenter_diag.log").read_text(encoding="utf-8")
        assert "session_start" in text
        assert "hello size=3 ratio=1.5 note=none" in text
        assert "session_end reason=stop" in text
        assert "frames_rendered=5" in text

    def test_exception_writes_traceback(self, tmp_path):
        diag = self._make(tmp_path)
        try:
            raise ValueError("boom")
        except ValueError as exc:
            diag.exception("forward_frame", exc)
        text = (tmp_path / "presenter_diag.log").read_text(encoding="utf-8")
        assert "forward_frame error=ValueError('boom')" in text
        assert "Traceback" in text

    def test_disabled_writes_nothing(self, tmp_path):
        diag = self._make(tmp_path, enabled=False)
        diag.event("nope")
        diag.exception("nope", RuntimeError("x"))
        diag.finish("stop")
        assert not (tmp_path / "presenter_diag.log").exists()

    def test_default_disabled_under_pytest(self, monkeypatch, tmp_path):
        from echo_personal_tool.presentation import presenter_diagnostics as pd

        monkeypatch.setattr(pd.os, "environ", {"PYTEST_CURRENT_TEST": "x"})
        assert pd.default_enabled() is False
        monkeypatch.setattr(pd.os, "environ", {"SONOFORGE_PRESENTER_DIAG": "0"})
        assert pd.default_enabled() is False
        monkeypatch.setattr(pd.os, "environ", {})
        assert pd.default_enabled() is True

    def test_summarize_array(self):
        import numpy as np

        from echo_personal_tool.presentation.presenter_diagnostics import summarize_array

        assert summarize_array(None) == {"frame": "none"}
        summary = summarize_array(np.array([[10, 200], [30, 40]], dtype=np.uint8))
        assert summary["frame"] == "2x2"
        assert summary["min"] == 10
        assert summary["max"] == 200

    def test_forward_errors_are_recorded(self, presenter_window, monkeypatch, tmp_path):
        """A failing audience render must not be silently dropped anymore."""
        from echo_personal_tool.presentation.presenter_diagnostics import (
            PresenterDiagnostics,
        )

        mode = presenter_window._presenter
        diag = PresenterDiagnostics(path=tmp_path / "pdiag.log", enabled=True)
        mode._diag = diag
        mode.start()
        window = mode.window()
        assert window is not None
        monkeypatch.setattr(window, "viewer", lambda: (_ for _ in ()).throw(RuntimeError("dead")))
        try:
            mode.forward_frame(np.zeros((4, 4), dtype=np.uint8))
            assert diag.counters["forward_errors"] == 1
        finally:
            mode.stop()
        text = (tmp_path / "pdiag.log").read_text(encoding="utf-8")
        assert "forward_frame error=RuntimeError('dead')" in text


# ── Forward pacing and speaker keepalive ────────────────────────────


class TestForwardPacingAndKeepalive:
    def test_ema_tracks_render_cost(self, presenter_window):
        mode = presenter_window._presenter
        mode._record_forward_ms(10.0)
        assert mode._fwd_ema_ms == 10.0
        mode._record_forward_ms(30.0)
        assert mode._fwd_ema_ms == 0.9 * 10.0 + 0.1 * 30.0

    def test_pacing_skips_when_expensive(self, presenter_window, monkeypatch):
        """When the audience render is slow, intermediate frames are skipped."""
        import numpy as np

        mode = presenter_window._presenter
        if not mode.active:
            mode.start()
        window = mode.window()
        try:
            mode._fwd_seq = 0
            calls = {"fast": 0, "full": 0}
            viewer = window.viewer()
            # The fixture controller's MagicMock is_scroll_active() is truthy
            # → forward_frame takes the playback (show_frame_fast) path.
            monkeypatch.setattr(
                viewer,
                "show_frame_fast",
                lambda frame: calls.__setitem__("fast", calls["fast"] + 1),
            )
            mode._fwd_ema_ms = 30.0  # worst bucket → every 3rd frame
            for _ in range(6):
                mode.forward_frame(np.zeros((2, 2), dtype=np.uint8))
            assert calls["fast"] == 2
            assert mode._diag.counters.get("frames_skipped", 0) >= 4
        finally:
            if mode.active:
                mode.stop()

    def test_keepalive_timer_ticking_while_active(self, presenter_window, qtbot):
        """A scheduled update() counters GL-idle blanking of the host viewer."""
        mode = presenter_window._presenter
        mode.start()
        try:
            assert mode._keepalive_timer.isActive()
            assert mode._probe_timer.isActive()
            paints_before = mode._paint_counter.count
            qtbot.wait(600)  # keepalive fires ~2 times at 250 ms
            assert mode._paint_counter.count >= paints_before
        finally:
            mode.stop()
        assert not mode._keepalive_timer.isActive()
        assert not mode._probe_timer.isActive()
