"""ComparisonCoordinator: Multiview routing and the tool gate without a window (N-08, Э10).

``test_multiview_window.py`` drives the mode through ``MainWindow``; here the
coordinator runs against a fake host, so the rules it owns — pane creation and
hand-back, gallery routing (plain click, Ctrl+click, arming, «Заменить клип»),
the study/duplicate guards and the stage-1 tool gate — stay pinned without
building the whole window.  The fake host implements the ``ComparisonWindow``
protocol from ``comparison_coordinator`` and nothing else.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.gui

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QMessageBox, QSlider, QSplitter, QStackedWidget, QStatusBar, QVBoxLayout, QWidget

from echo_personal_tool.domain.models.metadata import InstanceMetadata
from echo_personal_tool.domain.models.multiview import PaneId, PlaybackMode
from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.presentation import comparison_coordinator as cc
from echo_personal_tool.presentation.comparison_coordinator import ComparisonCoordinator

# ── fake host ───────────────────────────────────────────────────────


class FakeViewer(QWidget):
    """Just enough viewer for ``MultiViewPaneWidget`` and the header refresh."""

    play_pause_requested = Signal()
    frame_selected = Signal(int)
    scroll_frame_selected = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._timeline_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.transport_states: list[dict[str, Any]] = []

    def set_transport_state(self, **kwargs: Any) -> None:
        self.transport_states.append(kwargs)


class FakeController:
    """The slice of ``AppController`` the coordinator talks to."""

    def __init__(self) -> None:
        self.studies: list[object] = []
        self.retained_studies_for_cache: list[object] = []
        self.study_uid_by_sop: dict[str, str] = {}
        self.resolve_raises = False
        self.toggled = 0
        self.state_manager = SimpleNamespace(
            snapshot=SimpleNamespace(instance=None, current_frame_index=0, is_playing=False),
            set_frame=MagicMock(),
        )

    def resolve_study_uid(self, instance: InstanceMetadata) -> str | None:
        if self.resolve_raises:
            raise RuntimeError("study unknown")
        return self.study_uid_by_sop.get(instance.sop_instance_uid, "study.1")

    def toggle_playback(self) -> None:
        self.toggled += 1


class _FakeTabs:
    """``TabSessionManager`` as far as the pane badges care."""

    def __init__(self, tabs: tuple = (), active_tab_id: str | None = None) -> None:
        self.tabs = tabs
        self.active_tab_id = active_tab_id


class _FakeTabCoordinator:
    def __init__(self, tabs: _FakeTabs | None = None) -> None:
        self.tabs = tabs if tabs is not None else _FakeTabs()


class FakeGallery:
    def __init__(self) -> None:
        self.hint: bool | None = None

    def set_multiview_start_hint(self, visible: bool) -> None:
        self.hint = visible


class FakeWindow(QWidget):
    """``ComparisonWindow`` as ``MainWindow`` implements it, plus call counters."""

    def __init__(self) -> None:
        super().__init__()
        self._controller = FakeController()
        self._gallery = FakeGallery()
        self._tab_coordinator = _FakeTabCoordinator()
        self._layout_config = SimpleNamespace(multiview=False)
        self._viewer = FakeViewer()
        self._viewer2: FakeViewer | None = None
        self._start_page = QWidget()
        self._viewer_stack = QStackedWidget(self)
        self._viewer_stack.addWidget(self._viewer)
        self._viewer_stack.addWidget(self._start_page)
        self._content_widget = QWidget(self)
        self._content_splitter = QSplitter(self)
        self._has_loaded_study = False
        self._status_bar = QStatusBar(self)
        self._root_layout = QVBoxLayout(self)
        self._root_layout.addWidget(self._content_widget)
        self._root_layout.addWidget(self._status_bar)
        self.statuses: list[str] = []
        self.selected: list[object] = []
        self.pane_badges: list[tuple[str, str]] = []
        self.enable_calls = 0
        self.rebuild_calls = 0
        self._comparison: ComparisonCoordinator = None  # type: ignore[assignment]

    # ── host hooks ──────────────────────────────────────────────────

    def statusBar(self) -> QStatusBar:  # noqa: N802 - Qt naming
        return self._status_bar

    def _show_status(self, message: str) -> None:
        self.statuses.append(message)

    def _rebuild_layout(self) -> None:
        self.rebuild_calls += 1

    def _ensure_viewer2(self) -> None:
        if self._viewer2 is None:
            self._viewer2 = FakeViewer()
            self._comparison.attach_right_viewer(self._viewer2)

    def _enable_multiview_mode(self) -> None:
        self.enable_calls += 1
        self._layout_config.multiview = True
        self._ensure_viewer2()
        self._comparison.ensure_panes()
        self._comparison.ensure_transport()

    def _on_instance_selected(self, selected: object) -> None:
        self.selected.append(selected)

    def _forward_pane_badges(self, left: str, right: str) -> None:
        self.pane_badges.append((left, right))


@pytest.fixture()
def host(qapp) -> FakeWindow:
    window = FakeWindow()
    window._comparison = ComparisonCoordinator(window)
    return window


@pytest.fixture()
def coordinator(host: FakeWindow) -> ComparisonCoordinator:
    return host._comparison


@pytest.fixture()
def ctrl_modifiers(monkeypatch):
    """The gallery click handlers read the live keyboard; the tests set it."""

    def _set(ctrl: bool) -> None:
        modifiers = Qt.KeyboardModifier.ControlModifier if ctrl else Qt.KeyboardModifier.NoModifier
        monkeypatch.setattr(cc, "QApplication", SimpleNamespace(keyboardModifiers=lambda: modifiers))

    return _set


# ── helpers ─────────────────────────────────────────────────────────


def _instance(uid: str, *, study: str = "study.1", frames: int = 30) -> InstanceMetadata:
    """A clip without a path: nothing is ever read from disk in these tests."""
    return InstanceMetadata(
        sop_instance_uid=uid,
        series_uid=study,
        modality="US",
        number_of_frames=frames,
        pixel_spacing=None,
        frame_time_ms=33.3,
        series_description="A4C",
        path=None,
    )


def _enter(host: FakeWindow) -> ComparisonCoordinator:
    """Take the Multiview path the toolbar/layout menu takes."""
    host._enable_multiview_mode()
    return host._comparison


def _two_clips(host: FakeWindow) -> ComparisonCoordinator:
    coordinator = _enter(host)
    assert coordinator.load_into_pane(PaneId.LEFT, _instance("sop.left"))
    assert coordinator.load_into_pane(PaneId.RIGHT, _instance("sop.right"))
    return coordinator


def _right(coordinator: ComparisonCoordinator):
    return coordinator.session.session.pane(PaneId.RIGHT)


def _left(coordinator: ComparisonCoordinator):
    return coordinator.session.session.pane(PaneId.LEFT)


# ── state ───────────────────────────────────────────────────────────


def test_the_mode_flag_comes_from_the_layout_config(host, coordinator) -> None:
    assert coordinator.enabled() is False
    host._layout_config.multiview = True
    assert coordinator.enabled() is True


def test_pane_lookup_maps_the_pane_ids(coordinator) -> None:
    assert coordinator.pane(PaneId.LEFT) is None, "no panes before Multiview is entered"
    assert coordinator.pane(PaneId.RIGHT) is None


def test_the_start_hint_flags_the_gallery(host, coordinator) -> None:
    coordinator.set_start_hint("sop.1")
    assert coordinator.start_hint_uid == "sop.1"
    assert host._gallery.hint is True

    coordinator.set_start_hint(None)
    assert coordinator.start_hint_uid is None
    assert host._gallery.hint is False


# ── stage-1 tool gate ───────────────────────────────────────────────


def test_tools_stay_available_outside_multiview(host, coordinator) -> None:
    assert coordinator.tool_blocked("caliper") is False
    assert host.statuses == []


def test_tools_are_refused_with_an_explanation_inside_multiview(host, coordinator) -> None:
    host._layout_config.multiview = True
    assert coordinator.tool_blocked("caliper") is True
    assert host.statuses == [tr("multiview.blocked.tools")]


# ── panes ───────────────────────────────────────────────────────────


def test_entering_multiview_wraps_the_main_viewer_once(host, coordinator) -> None:
    _enter(host)
    assert coordinator.pane_left is not None
    assert coordinator.pane_left.viewer is host._viewer, "the left pane is the main viewer"
    assert host._viewer2 is not None and coordinator.pane_right is not None
    assert coordinator.pane_right.viewer is host._viewer2

    left = coordinator.pane_left
    coordinator.ensure_panes()
    assert coordinator.pane_left is left, "entering twice must not rebuild the panes"


def test_the_left_pane_adopts_the_clip_the_controller_shows(host, coordinator) -> None:
    instance = _instance("sop.left")
    host._controller.state_manager.snapshot = SimpleNamespace(
        instance=instance, current_frame_index=7, is_playing=False
    )
    _enter(host)

    assert _left(coordinator).instance is instance
    assert _left(coordinator).current_frame == 7
    assert _left(coordinator).study_uid == "study.1"
    assert coordinator.session.session.active_pane is PaneId.LEFT


def test_resyncing_keeps_the_frame_the_user_moved_to(host, coordinator) -> None:
    host._controller.state_manager.snapshot = SimpleNamespace(
        instance=_instance("sop.left"), current_frame_index=7, is_playing=False
    )
    _enter(host)
    host._controller.state_manager.snapshot = SimpleNamespace(
        instance=_instance("sop.left"), current_frame_index=3, is_playing=False
    )

    coordinator.ensure_panes()

    assert _left(coordinator).current_frame == 7, "the same clip is not reloaded under the user"


def test_leaving_multiview_removes_the_transport_and_returns_the_viewer(host, coordinator) -> None:
    _enter(host)
    transport = coordinator.transport
    assert transport is not None and host._root_layout.indexOf(transport) >= 0

    host._layout_config.multiview = False
    coordinator.teardown()

    assert host._root_layout.indexOf(transport) < 0
    assert host._viewer_stack.indexOf(host._viewer) >= 0, "the main viewer goes back to its stack"
    assert host._viewer_stack.currentWidget() is host._start_page, "no study was loaded"
    assert coordinator.pane_left is not None and coordinator.pane_left.parent() is host._content_widget


def test_leaving_multiview_keeps_a_loaded_study_on_screen(host, coordinator) -> None:
    _enter(host)
    host._has_loaded_study = True
    host._layout_config.multiview = False

    coordinator.teardown()

    assert host._viewer_stack.currentWidget() is host._viewer


def test_teardown_is_a_noop_while_multiview_is_on(host, coordinator) -> None:
    _enter(host)

    coordinator.teardown()

    transport = coordinator.transport
    assert transport is not None and host._root_layout.indexOf(transport) >= 0


def test_re_entering_reattaches_the_main_viewer(host, coordinator) -> None:
    _enter(host)
    host._layout_config.multiview = False
    coordinator.teardown()

    _enter(host)

    assert coordinator.pane_left is not None
    assert coordinator.pane_left.layout().indexOf(host._viewer) >= 0


def test_the_transport_sits_above_the_status_bar(host, coordinator) -> None:
    _enter(host)
    transport = coordinator.transport
    assert transport is not None
    assert host._root_layout.indexOf(transport) == host._root_layout.indexOf(host._status_bar) - 1

    coordinator.ensure_transport()
    assert coordinator.transport is transport, "the bar is built once"
    assert host._root_layout.indexOf(transport) >= 0


def test_refreshing_without_a_transport_bar_is_harmless(coordinator) -> None:
    coordinator.transport = None
    coordinator.refresh_transport()  # must not raise


# ── arming flow (spec §6.1) ─────────────────────────────────────────


def test_ctrl_click_off_mode_only_arms_the_hint(host, coordinator) -> None:
    assert coordinator.route_start(_instance("sop.a"), ctrl=True) is False

    assert coordinator.start_hint_uid == "sop.a"
    assert host.enable_calls == 0, "the first Ctrl+click asks for a second clip"
    assert host._gallery.hint is True


def test_a_plain_click_off_mode_arms_nothing(host, coordinator) -> None:
    assert coordinator.route_start(_instance("sop.a"), ctrl=False) is False

    assert coordinator.start_hint_uid is None
    assert host._gallery.hint is None


def test_clicking_the_armed_clip_again_dismisses_the_hint(host, coordinator) -> None:
    coordinator.route_start(_instance("sop.a"), ctrl=True)

    assert coordinator.route_start(_instance("sop.a"), ctrl=False) is False
    assert coordinator.start_hint_uid is None
    assert host._gallery.hint is False
    assert host.enable_calls == 0


def test_the_next_different_clip_launches_multiview(host, coordinator) -> None:
    coordinator.route_start(_instance("sop.a"), ctrl=True)

    consumed = coordinator.route_start(_instance("sop.b"), ctrl=False)

    assert consumed is True
    assert host.enable_calls == 1
    assert _right(coordinator).instance is not None
    assert _right(coordinator).instance.sop_instance_uid == "sop.b"
    assert coordinator.session.session.active_pane is PaneId.RIGHT
    assert coordinator.active_viewer is host._viewer2
    assert coordinator.start_hint_uid is None


# ── gallery → pane routing (spec §6) ────────────────────────────────


def test_a_plain_click_fills_the_empty_right_pane(host, coordinator, ctrl_modifiers) -> None:
    ctrl_modifiers(False)
    _enter(host)
    coordinator.load_into_pane(PaneId.LEFT, _instance("sop.left"))

    assert coordinator.route_gallery_click(_instance("sop.right")) is True

    assert _right(coordinator).instance.sop_instance_uid == "sop.right"
    assert _left(coordinator).instance.sop_instance_uid == "sop.left", "A is not replaced by the click"


def test_a_plain_click_on_the_active_left_pane_stays_with_the_controller(host, coordinator, ctrl_modifiers) -> None:
    ctrl_modifiers(False)
    _two_clips(host)
    coordinator.session.activate(PaneId.LEFT)

    assert coordinator.route_gallery_click(_instance("sop.third")) is False

    assert coordinator.session.session.active_pane is PaneId.LEFT
    assert _right(coordinator).instance.sop_instance_uid == "sop.right"
    assert host.selected == [], "the window routes this click through AppController"


def test_a_ctrl_click_loads_the_right_pane(host, coordinator, ctrl_modifiers) -> None:
    ctrl_modifiers(True)
    _two_clips(host)

    assert coordinator.route_gallery_click(_instance("sop.third")) is True

    assert _right(coordinator).instance.sop_instance_uid == "sop.third"
    assert coordinator.session.session.active_pane is PaneId.RIGHT
    assert coordinator.active_viewer is host._viewer2


def test_an_armed_left_pane_keeps_ctrl_from_stealing_the_click(host, coordinator, ctrl_modifiers) -> None:
    ctrl_modifiers(True)
    _two_clips(host)
    coordinator.on_replace_requested(PaneId.LEFT)

    # Pane A *is* the main viewer, so an armed A hands the click back to the
    # controller (``False``) instead of loading it here — but Ctrl must not
    # divert the same click into B.
    assert coordinator.route_gallery_click(_instance("sop.replacement")) is False

    assert _right(coordinator).instance.sop_instance_uid == "sop.right"
    assert coordinator.session.session.active_pane is PaneId.LEFT
    assert coordinator.pending_pane is None, "the armed pane is consumed by the next click"


def test_an_armed_right_pane_receives_the_click(host, coordinator, ctrl_modifiers) -> None:
    ctrl_modifiers(False)
    _two_clips(host)
    coordinator.session.activate(PaneId.LEFT)
    coordinator.on_replace_requested(PaneId.RIGHT)

    assert coordinator.route_gallery_click(_instance("sop.replacement")) is True

    assert _right(coordinator).instance.sop_instance_uid == "sop.replacement"
    assert _left(coordinator).instance.sop_instance_uid == "sop.left"


def test_off_mode_ctrl_click_reaches_the_arming_flow(host, coordinator, ctrl_modifiers) -> None:
    ctrl_modifiers(True)

    assert coordinator.route_gallery_click(_instance("sop.a")) is False

    assert coordinator.start_hint_uid == "sop.a"
    assert host.enable_calls == 0


# ── loading guards ──────────────────────────────────────────────────


def test_a_clip_already_in_the_other_pane_is_refused(host, coordinator) -> None:
    _two_clips(host)

    assert coordinator.load_into_pane(PaneId.RIGHT, _instance("sop.left")) is False

    assert host.statuses[-1] == tr("multiview.duplicate", pane="A")
    assert coordinator.session.session.active_pane is PaneId.LEFT, "the existing pane is activated"
    assert _right(coordinator).instance.sop_instance_uid == "sop.right"


def test_the_same_clip_in_the_target_pane_only_activates_it(host, coordinator) -> None:
    _two_clips(host)
    coordinator.session.activate(PaneId.LEFT)

    assert coordinator.load_into_pane(PaneId.RIGHT, _instance("sop.right")) is False

    assert coordinator.session.session.active_pane is PaneId.RIGHT
    assert host.statuses == [], "re-selecting the clip needs no warning"


def test_a_clip_from_another_study_is_allowed(host, coordinator) -> None:
    """Э10 §6.1: comparability is the frame geometry, not the study UID."""
    _two_clips(host)
    host._controller.study_uid_by_sop["sop.other"] = "study.2"

    assert coordinator.load_into_pane(PaneId.RIGHT, _instance("sop.other", study="study.2")) is True

    assert _right(coordinator).instance.sop_instance_uid == "sop.other"
    assert _right(coordinator).study_uid == "study.2"


def test_an_unresolvable_study_uid_does_not_block_the_load(host, coordinator) -> None:
    _enter(host)
    coordinator.load_into_pane(PaneId.LEFT, _instance("sop.left"))
    host._controller.resolve_raises = True

    assert coordinator.load_into_pane(PaneId.RIGHT, _instance("sop.right")) is True

    assert _right(coordinator).study_uid is None


def test_study_uid_is_none_when_the_controller_fails(host, coordinator) -> None:
    host._controller.resolve_raises = True

    assert coordinator.study_uid(_instance("sop.a")) is None


# ── context menu «Открыть слева/справа» ─────────────────────────────


def test_open_in_pane_left_reuses_the_controller_path(host, coordinator) -> None:
    _two_clips(host)
    instance = _instance("sop.third")

    coordinator.open_in_pane(instance, "left")

    assert host.selected == [instance]
    assert coordinator.session.session.active_pane is PaneId.LEFT


def test_open_in_pane_right_enables_the_mode_and_loads(host, coordinator) -> None:
    instance = _instance("sop.right")

    coordinator.open_in_pane(instance, "right")

    assert host.enable_calls == 1, "the context menu may enter Multiview on its own"
    assert _right(coordinator).instance is instance
    assert coordinator.session.session.active_pane is PaneId.RIGHT
    assert coordinator.active_viewer is host._viewer2


def test_open_in_pane_ignores_foreign_objects(host, coordinator) -> None:
    _enter(host)

    coordinator.open_in_pane("not an instance", "right")

    assert _right(coordinator).instance is None
    assert host.selected == []


# ── pane events ─────────────────────────────────────────────────────


def test_replace_arms_the_pane_and_hints(host, coordinator) -> None:
    _two_clips(host)

    coordinator.on_replace_requested(PaneId.RIGHT)

    assert coordinator.pending_pane is PaneId.RIGHT
    assert host.statuses[-1] == tr("multiview.replace.hint", pane="B")
    assert coordinator.pane_right is not None and coordinator.pane_right.is_active() is True


def test_activating_the_right_pane_switches_the_active_viewer(host, coordinator) -> None:
    _two_clips(host)

    coordinator.on_pane_activated(PaneId.RIGHT)

    assert coordinator.active_viewer is host._viewer2
    assert coordinator.session.session.active_pane is PaneId.RIGHT


def test_independent_mode_moves_only_the_clicked_pane(host, coordinator) -> None:
    _two_clips(host)

    coordinator.on_pane_frame_selected(PaneId.RIGHT, 12)

    assert _right(coordinator).current_frame == 12
    assert _left(coordinator).current_frame == 0


def test_a_frame_handed_back_to_the_controller_is_applied(host, coordinator) -> None:
    _enter(host)

    coordinator.on_left_released(9)

    host._controller.state_manager.set_frame.assert_called_once_with(9)


def test_declining_the_warning_pauses_the_session(host, coordinator, monkeypatch) -> None:
    _enter(host)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.No)

    coordinator.on_warning("title", "body")

    assert host.statuses[-1] == tr("multiview.status.independent")


def test_accepting_the_warning_keeps_the_mode(host, coordinator, monkeypatch) -> None:
    _enter(host)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)

    coordinator.on_warning("title", "body")

    assert host.statuses == [], "Yes keeps the chosen mode without a status change"


# ── playback routing ────────────────────────────────────────────────


def test_main_play_stays_with_the_controller_outside_multiview(host, coordinator) -> None:
    coordinator.on_main_play_pause_requested()

    assert host._controller.toggled == 1
    assert coordinator.session.session.is_playing is False


def test_main_play_drives_the_shared_clock_in_a_synchronised_mode(host, coordinator) -> None:
    _two_clips(host)
    coordinator.session.set_mode(PlaybackMode.COMMON_WINDOW)

    coordinator.on_main_play_pause_requested()

    assert host._controller.toggled == 0, "in sync modes the shared clock owns both clips"
    assert coordinator.session.session.is_playing is True
    coordinator.session.pause()


# ── session lifetime ────────────────────────────────────────────────


def test_owns_source_reports_only_the_open_pair(host, coordinator) -> None:
    """QH-1a.2 / Э10 §5.1: tab-close asks the pair before it deletes a source."""
    _two_clips(host)
    assert coordinator.owns_source("study.1") is True
    assert coordinator.owns_source("study.2") is False
    coordinator.reset_session()
    assert coordinator.owns_source("study.1") is False


def test_an_explicit_reset_bumps_the_pair_generation(host, coordinator) -> None:
    """A replace/clear retires the pair, so late answers for it are discarded."""
    _two_clips(host)
    session = coordinator.session.session
    before = session.generation
    coordinator.reset_session()
    assert session.generation > before
    assert session.accepts(session.generation)
    assert not session.accepts(before)


def test_reset_drops_both_panes(host, coordinator) -> None:
    _two_clips(host)

    coordinator.reset_session()

    session = coordinator.session.session
    assert session.pane(PaneId.LEFT).instance is None
    assert session.pane(PaneId.RIGHT).instance is None
    assert session.active_pane is None
    assert session.playback_mode is PlaybackMode.INDEPENDENT


def test_shutdown_detaches_the_pane_widgets(host, coordinator) -> None:
    _two_clips(host)

    coordinator.shutdown()

    assert coordinator.session.pane_widget(PaneId.LEFT) is None
    assert coordinator.session.pane_widget(PaneId.RIGHT) is None
