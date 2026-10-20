"""Tab coordination for the main window (N-08, Э9).

A slice of ``MainWindow`` moved into its own module: everything between «the
user opened something» and «the viewer shows the right tab» — which tab a load
goes to, what happens when the tab limit is reached, what is parked before the
viewer leaves a tab, and how the stack shows the placeholder while a tab loads.

The window keeps the widgets; this module owns the sequence and the tab state
(``TabSessionManager`` plus the pending-load and pending-view bookkeeping).
A parked tab remembers the frame, the window/level sliders and the results
overlay position (Э9 §3/§5), and a finished folder load feeds «Недавние
исследования» on the welcome page (Э5 §7.3). Window attribute
names stay the window's own on purpose: the ``TabWindow`` protocol below is the
contract, and tests steer the flow by replacing ``_tab_flush_or_block`` or
``_queue_cache_purge`` on the window.

See docs/superpowers/specs/2026-10-07-tabs-start-page-spec-ru.md §3–§5 and the
roadmap row N-08 (new code must not grow ``main_window.py``).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import AbstractContextManager
from typing import Protocol

from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QMessageBox, QStackedWidget, QWidget

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.application.download_history import DownloadHistory
from echo_personal_tool.application.tab_session import (
    TAB_ORIGIN_EMPTY,
    TAB_ORIGIN_FOLDER,
    TAB_ORIGIN_SERVER,
    TabSession,
    TabSessionManager,
    UnknownTabError,
    decode_viewer_state,
    park_tab,
    tab_title,
)
from echo_personal_tool.domain.models import InstanceMetadata
from echo_personal_tool.domain.models.metadata import StudyMetadata
from echo_personal_tool.domain.models.viewer_state import ViewerState
from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.infrastructure.user_preferences import UserPreferences
from echo_personal_tool.presentation.study_loading_overlay import StudyLoadingOverlay
from echo_personal_tool.presentation.tab_bar import EmptyTabPlaceholder, TabStrip
from echo_personal_tool.presentation.thumbnail_gallery import ThumbnailGalleryWidget
from echo_personal_tool.presentation.tool_panel import ToolPanel
from echo_personal_tool.presentation.viewer_widget import ViewerWidget

logger = logging.getLogger(__name__)


class TabWindow(Protocol):
    """Window surface the tab coordinator drives (implemented by ``MainWindow``).

    The names are the window's own: the coordinator is a slice of the window in
    a separate file, not a new abstraction layer on top of it. Only what the
    moved code really touches is listed here.
    """

    _controller: AppController
    _user_preferences: UserPreferences
    _viewer: ViewerWidget
    _gallery: ThumbnailGalleryWidget
    _tab_strip: TabStrip
    _main_stack: QStackedWidget
    _empty_tab_page: EmptyTabPlaceholder
    _study_loading_overlay: StudyLoadingOverlay
    _content_widget: QWidget
    _tool_panel: ToolPanel
    _download_history: DownloadHistory
    _has_loaded_study: bool

    def _show_status(self, message: str) -> None: ...

    def _set_start_page_visible(self, visible: bool) -> None: ...

    def _refresh_start_page_recents(self) -> None: ...

    def _update_last_session_clip_count(self, clip_count: int) -> None: ...

    def _tab_flush_or_block(self) -> bool: ...

    def _queue_cache_purge(self, session_id: str) -> None: ...

    def _process_pending_cache_purges(self) -> None: ...

    def _special_layout_active(self) -> bool: ...

    def _leave_special_layouts(self) -> None: ...

    def _report_mode_page(self) -> QWidget | None: ...

    def _reset_doppler_mode_override(self) -> None: ...

    def _batch_study_surface_updates(self) -> AbstractContextManager[Iterator[None]]: ...

    def _on_instance_selected(self, selected: object) -> None: ...


class TabCoordinator:
    """Load lifecycle of the open tabs: acquire → park → load → finish/abort.

    Owns the :class:`TabSessionManager`, so the tab bar, the tab list and the
    active tab all have a single owner. The window delegates its tab methods
    here and keeps only the policies that need the window itself (flush before
    leaving a study, cache purge queue, multiview/M-mode teardown).
    """

    def __init__(self, window: TabWindow, *, manager: TabSessionManager | None = None) -> None:
        self._window = window
        self._tabs = manager if manager is not None else TabSessionManager()
        #: Tab whose studies the controller is loading right now ("" when idle).
        self.loading_tab_id: str | None = None
        #: True while the previous study should stay on screen during a switch.
        self.keep_content_visible = False
        #: Tab the viewer came from; used to roll back a refused switch.
        self.previous_tab_id: str | None = None
        #: ``(tab_id, instance_uid, frame_index)`` to restore after the load.
        self.restore_target: tuple[str, str, int] | None = None
        #: ``(tab_id, instance_uid, frame_index, viewer_state)`` applied once the
        #: tab's own instance is active again (Э9 §3/§5: frame and view state
        #: survive a tab switch).
        self.pending_view: tuple[str, str, int, dict] | None = None
        #: Folder studies of this run, for «Недавние исследования» (Э5 §7.3).
        self.folder_history = DownloadHistory()
        self.folder_roots: dict[str, str] = {}

    # ── state ───────────────────────────────────────────────────────

    @property
    def tabs(self) -> TabSessionManager:
        return self._tabs

    def open_empty_tab(self) -> TabSession:
        """The tab an empty window starts with; the first load fills it (D-29)."""
        return self._tabs.open_tab(origin=TAB_ORIGIN_EMPTY)

    def busy(self) -> bool:
        if self.loading_tab_id is None:
            return False
        self._window._show_status(tr("tabs.busy"))
        return True

    # ── opening ─────────────────────────────────────────────────────

    def acquire_for_load(self, origin: str, root: str, cache_session_id: str) -> bool:
        """Pick a new/empty tab, or replace the active source with tabs disabled."""
        window = self._window
        if self.busy() or not window._tab_flush_or_block():
            return False
        active = self._tabs.active
        if active is not None and not window._user_preferences.tabs_enabled:
            purge = self._tabs.replace_active(origin=origin, root=root, cache_session_id=cache_session_id)
            window._queue_cache_purge(purge)
        elif active is not None and not active.studies:
            self._tabs.retarget_empty(active.tab_id, origin=origin, root=root, cache_session_id=cache_session_id)
        else:
            if not self.ensure_capacity():
                return False
            self.park_active()
            self._tabs.open_tab(
                origin=origin,
                root=root,
                cache_session_id=cache_session_id,
                activate=True,
            )
        if window._special_layout_active():
            window._leave_special_layouts()
        self.keep_content_visible = False
        self.previous_tab_id = None
        self.loading_tab_id = self._tabs.active_tab_id
        self.restore_target = None
        self.refresh_strip()
        self.update_main_stack()
        return True

    def ensure_capacity(self) -> bool:
        """At the limit, ask before closing the oldest inactive tab (spec §4, no silent LRU)."""
        if not self._tabs.is_full:
            return True
        return self.make_room(1)

    def make_room(self, count: int) -> bool:
        """Ask once, then close the ``count`` oldest inactive tabs. Never closes the active one."""
        active_id = self._tabs.active_tab_id
        inactive = sorted(
            (tab for tab in self._tabs.tabs if tab.tab_id != active_id),
            key=lambda tab: tab.created_at,
        )
        if len(inactive) < count:
            return False
        victims = inactive[:count]
        titles = "\n".join(f"• {self.caption(tab)}" for tab in victims)
        answer = QMessageBox.question(
            self._window,
            tr("tabs.limit.title"),
            tr("tabs.limit.body", max=self._tabs.max_tabs, count=count, titles=titles),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False
        for tab in victims:
            self.close_inactive(tab.tab_id)
        return True

    def open_batch(self, studies: list[StudyMetadata], session_id: str) -> bool:
        """Open every study of one PACS download batch in its own tab (D-29, PR-C).

        The batch shares one cache session; the session is deleted only when the
        last tab using it closes. The first study loads now, the others wait in
        their tabs and load when they are activated.
        """
        window = self._window
        if not studies:
            return False
        for study in studies:
            window._download_history.record(study)
        # The block «Недавние исследования» shows the batch right away (Э5 §7.3).
        window._refresh_start_page_recents()
        if not window._user_preferences.tabs_enabled:
            if not self.acquire_for_load(TAB_ORIGIN_SERVER, "", session_id):
                return False
            window._reset_doppler_mode_override()
            window._controller.load_pre_scanned_studies(studies)
            return True
        if self.busy() or not window._tab_flush_or_block():
            return False
        active = self._tabs.active
        reuse_active = active is not None and not active.studies
        wanted_new = len(studies) - (1 if reuse_active else 0)
        free = self._tabs.max_tabs - len(self._tabs)
        allowed = len(studies)
        if wanted_new > free and not self.make_room(wanted_new - free):
            # Declined: open only what fits without closing anything.
            allowed = min(len(studies), free + (1 if reuse_active else 0))
            if allowed < 1:
                window._show_status(tr("tabs.limit.nothing_opened"))
                return False
        to_open = studies[:allowed]
        if not self.acquire_for_load(TAB_ORIGIN_SERVER, "", session_id):
            return False
        window._reset_doppler_mode_override()
        for study in to_open[1:]:
            self._tabs.open_tab(
                origin=TAB_ORIGIN_SERVER,
                cache_session_id=session_id,
                studies=[study],
                activate=False,
            )
        self.refresh_strip()
        if allowed < len(studies):
            window._show_status(tr("tabs.batch.partial", opened=allowed, total=len(studies)))
        window._controller.load_pre_scanned_studies([to_open[0]])
        return True

    # ── switching and closing ───────────────────────────────────────

    def park_active(self) -> None:
        """Save what the viewer shows into the tab before it is left (spec §5)."""
        window = self._window
        tab = self._tabs.active
        if tab is None or not tab.studies:
            return
        tab.has_measurements = self.has_live_measurements(tab)
        snapshot = window._controller.state_manager.snapshot
        instance = snapshot.instance
        park_tab(
            self._tabs,
            tab.tab_id,
            viewer_state=self.capture_view_state(),
            frame_index=snapshot.current_frame_index,
            active_instance_uid=instance.sop_instance_uid if instance is not None else "",
        )

    def capture_view_state(self) -> dict:
        """Overlay position and W/L/DR of the main viewer, for the parked tab."""
        window = self._window
        overlay_x, overlay_y = window._viewer.results_overlay_position()
        viewer_state: dict = {"overlay": [float(overlay_x), float(overlay_y)]}
        try:
            controls = window._tool_panel.controls
            viewer_state["window"] = int(controls.window_slider.slider().value())
            viewer_state["level"] = int(controls.level_slider.slider().value())
            viewer_state["dr"] = int(controls.dr_slider.slider().value())
        except Exception:  # noqa: BLE001 - view state is best effort, never blocks a switch
            logger.debug("Could not capture W/L for the parked tab", exc_info=True)
        return viewer_state

    def apply_pending_view(self, state: ViewerState) -> None:
        """Seek the parked frame and restore W/L/overlay once the tab's clip is active."""
        pending = self.pending_view
        if pending is None or state.instance is None:
            return
        _tab_id, instance_uid, frame_index, viewer_state = pending
        if state.instance.sop_instance_uid != instance_uid:
            return
        self.pending_view = None
        window = self._window
        overlay = viewer_state.get("overlay")
        if isinstance(overlay, (list, tuple)) and len(overlay) == 2:
            try:
                window._viewer.set_results_overlay_position(float(overlay[0]), float(overlay[1]))
            except Exception:  # noqa: BLE001 - never block the restore on overlay math
                logger.debug("Could not restore the results-overlay position", exc_info=True)
        if all(key in viewer_state for key in ("window", "level", "dr")):
            try:
                controls = window._tool_panel.controls
                controls.window_slider.slider().setValue(int(viewer_state["window"]))
                controls.level_slider.slider().setValue(int(viewer_state["level"]))
                controls.dr_slider.slider().setValue(int(viewer_state["dr"]))
            except Exception:  # noqa: BLE001 - never block the restore on W/L
                logger.debug("Could not restore W/L for the tab", exc_info=True)
        if frame_index and frame_index != state.current_frame_index and 0 <= frame_index < state.total_frames:
            try:
                window._controller.state_manager.set_frame(frame_index)
            except (RuntimeError, IndexError):
                logger.debug("Could not seek the parked frame %s", frame_index, exc_info=True)

    def load_content(self, tab: TabSession) -> None:
        """Make ``tab`` the content of the viewer (switch, close of the active tab)."""
        window = self._window
        self.keep_content_visible = bool(tab.studies and window._main_stack.currentWidget() is window._content_widget)
        try:
            with window._batch_study_surface_updates():
                if window._special_layout_active():
                    window._leave_special_layouts()
                window._reset_doppler_mode_override()
                self.loading_tab_id = tab.tab_id
                self.restore_target = (
                    (tab.tab_id, tab.active_instance_uid, tab.frame_index)
                    if tab.studies and tab.active_instance_uid
                    else None
                )
                self.refresh_strip()
                self.update_main_stack()
                window._controller.load_pre_scanned_studies(list(tab.studies))
        except Exception:
            self.abort_load()
            raise

    def switch_to(self, tab_id: str) -> bool:
        if tab_id == self._tabs.active_tab_id:
            return True
        if self.busy() or not self._window._tab_flush_or_block():
            self.refresh_strip()
            return False
        self.park_active()
        self.previous_tab_id = self._tabs.active_tab_id
        self._tabs.activate(tab_id)
        self.load_content(self._tabs.get(tab_id))
        # A synchronous controller-side refusal can already have rolled back.
        return self._tabs.active_tab_id == tab_id

    def has_live_measurements(self, tab: TabSession) -> bool:
        store = self._window._controller.measurement_persistence.store
        return any(study.study_uid in store and store.get(study.study_uid).has_measurements for study in tab.studies)

    def close_extra_tabs_for_single_mode(self) -> bool:
        """Keep the first tab; ask once before closing tabs with measurements."""
        window = self._window
        if len(self._tabs) <= 1:
            return True
        if self.busy() or not window._tab_flush_or_block():
            return False
        first, *victims = self._tabs.tabs
        measured = [
            tab
            for tab in victims
            if (self.has_live_measurements(tab) if tab is self._tabs.active else tab.has_measurements)
        ]
        if measured:
            titles = "\n".join(f"• {self.caption(tab)}" for tab in victims)
            answer = QMessageBox.question(
                window,
                tr("tabs.disable.title"),
                tr("tabs.disable.body", titles=titles),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
        if not self.switch_to(first.tab_id):
            return False
        for tab in victims:
            self.close_inactive(tab.tab_id)
        return True

    def on_selected(self, tab_id: str) -> None:
        if self._window._user_preferences.tabs_enabled and tab_id in self._tabs:
            self.switch_to(tab_id)

    def on_close_requested(self, tab_id: str) -> None:
        if not self._window._user_preferences.tabs_enabled or tab_id not in self._tabs:
            return
        if self.busy():
            self.refresh_strip()
            return
        if tab_id == self._tabs.active_tab_id:
            if not self._window._tab_flush_or_block():
                return
            tab = self._tabs.get(tab_id)
            owned = tab is not None and self._comparison_owns_tab_source(tab)
            result = self._tabs.close_tab(tab_id)
            if not owned:
                self._window._queue_cache_purge(result.purge_cache_session_id)
            if self._tabs.active is None:
                self._tabs.open_tab(origin=TAB_ORIGIN_EMPTY, activate=True)
            self.load_content(self._tabs.active)
            return
        self.close_inactive(tab_id)

    def _comparison_owns_tab_source(self, tab: TabSession) -> bool:
        """True when the open comparison pair still references a source of ``tab``.

        Lets a tab close skip the source purge so a clip still shown in the
        comparison window is never deleted underneath it (QH-1a.2 / Э10 §5.1).
        """
        comparison = getattr(self._window, "_comparison", None)
        owns_source = getattr(comparison, "owns_source", None)
        if owns_source is None:
            return False
        return any(
            owns_source(study_uid)
            for study_uid in (getattr(study, "study_uid", None) for study in tab.studies)
            if study_uid
        )

    def close_inactive(self, tab_id: str) -> None:
        window = self._window
        tab = self._tabs.get(tab_id)
        owned = tab is not None and self._comparison_owns_tab_source(tab)
        result = self._tabs.close_tab(tab_id)
        if not owned:
            window._queue_cache_purge(result.purge_cache_session_id)
        self.refresh_strip()
        window._process_pending_cache_purges()

    def close_others(self, keep_tab_id: str) -> None:
        """«Закрыть другие» (Э9 §4): keep this tab, close the rest.

        Every other tab goes through the usual per-tab guards — unsaved
        measurements still prompt, a refused flush still aborts the close.
        """
        if not self._window._user_preferences.tabs_enabled or keep_tab_id not in self._tabs:
            return
        for tab_id in [tab.tab_id for tab in self._tabs.tabs if tab.tab_id != keep_tab_id]:
            self.on_close_requested(tab_id)

    def move_tab(self, from_index: int, to_index: int) -> None:
        """Drag-reorder the tab strip (Э9 §4); an unknown position is ignored."""
        if not self._window._user_preferences.tabs_enabled:
            self.refresh_strip()
            return
        try:
            self._tabs.move_tab(from_index, to_index)
        except UnknownTabError:
            self.refresh_strip()
            return
        self.refresh_strip()

    def cycle(self, step: int) -> None:
        if not self._window._user_preferences.tabs_enabled:
            return
        tabs = self._tabs.tabs
        active_id = self._tabs.active_tab_id
        if len(tabs) < 2 or active_id is None:
            return
        position = self._tabs.index_of(active_id)
        self.switch_to(tabs[(position + step) % len(tabs)].tab_id)

    def close_active(self) -> None:
        if self._tabs.active_tab_id is not None:
            self.on_close_requested(self._tabs.active_tab_id)

    # ── captions and surfaces ───────────────────────────────────────

    def caption(self, tab: TabSession) -> str:
        position = self._tabs.index_of(tab.tab_id)
        return tab_title(
            tab,
            position,
            empty_label=tr("tabs.loading") if tab.tab_id == self.loading_tab_id else tr("tabs.empty"),
            untitled_label=tr("tabs.untitled"),
        )

    def refresh_strip(self) -> None:
        self._window._tab_strip.set_tabs(
            [(tab.tab_id, self.caption(tab)) for tab in self._tabs.tabs],
            self._tabs.active_tab_id,
        )

    def update_main_stack(self) -> None:
        """Studies in the active tab show the viewer; an empty tab shows the welcome page."""
        window = self._window
        if self.loading_tab_id is not None and self.keep_content_visible:
            window._study_loading_overlay.start(tr("tabs.loading_overlay"))
            return
        window._study_loading_overlay.stop()
        if self.loading_tab_id is not None:
            window._empty_tab_page.show_message(tr("tabs.loading"), "")
            window._main_stack.setCurrentIndex(1)
            return
        tab = self._tabs.active
        if tab is not None and tab.studies:
            self._show_active_surface()
            return
        # Э5 (spec 2026-10-07 §7): the empty tab carries the welcome page, not
        # the plain placeholder — that one is reserved for the loading state of
        # a fresh load above.
        window._has_loaded_study = False
        window._set_start_page_visible(True)
        self._show_active_surface()

    def _show_active_surface(self) -> None:
        """The content page — unless the active tab is in «Отчёт» mode (UI-4).

        The mode belongs to the tab (S-02); the window answers with its report
        page or with ``None`` for the images. Loading states above never reach
        here, so a tab being loaded always shows its loading surface first.
        A host without the hook (test doubles) simply has no report mode —
        the same tolerance ``_comparison_owns_tab_source`` keeps.
        """
        window = self._window
        hook = getattr(window, "_report_mode_page", None)
        page = hook() if callable(hook) else None
        if page is not None:
            window._main_stack.setCurrentWidget(page)
        else:
            window._main_stack.setCurrentIndex(0)
        # UI-6 (S-02): the focus view belongs to the tab like the report switch,
        # so it is restored at the same moment the surface changes.  The hook is
        # optional for the same reason as the report one: test doubles have none.
        focus_hook = getattr(window, "_sync_focus_from_tab", None)
        if callable(focus_hook):
            focus_hook()

    # ── load result ─────────────────────────────────────────────────

    def finish_load(self, studies: list[StudyMetadata]) -> str | None:
        """The controller published a study set: it belongs to the loading tab."""
        window = self._window
        # The controller only ever holds the active tab's studies, so a set that
        # arrives without a pending load still belongs to the active tab.
        loading_id = self.loading_tab_id or self._tabs.active_tab_id
        is_switch = self.previous_tab_id is not None
        self.loading_tab_id = None
        self.previous_tab_id = None
        if loading_id is not None and loading_id in self._tabs:
            self._tabs.set_studies(loading_id, studies)
        if not is_switch and loading_id is not None and loading_id in self._tabs:
            tab = self._tabs.get(loading_id)
            if tab.origin == TAB_ORIGIN_FOLDER and tab.root:
                for study in studies:
                    self.folder_history.record(study)
                    self.folder_roots[study.study_uid] = tab.root
                window._refresh_start_page_recents()
            window._update_last_session_clip_count(
                sum(len(series.instances) for study in studies for series in study.series)
            )
        self.refresh_strip()
        return loading_id

    def abort_load(self) -> None:
        self.loading_tab_id = None
        self.restore_target = None
        self.pending_view = None
        previous = self.previous_tab_id
        self.previous_tab_id = None
        self.keep_content_visible = False
        if previous is not None and previous in self._tabs:
            self._tabs.activate(previous)
        self.refresh_strip()
        self.update_main_stack()

    def after_loaded(self, loaded_tab_id: str | None, studies: list[StudyMetadata]) -> bool:
        """Finish a tab load. Returns True when the tab's parked view was
        restored (the caller must not autoload the first clip on top)."""
        window = self._window
        if self.keep_content_visible and self.restore_target is None:
            # A never-visited tab has no clip to restore. Do not present the
            # previous study's image as its content, or write a UI-only clear
            # back into the new study's measurement store.
            with QSignalBlocker(window._viewer):
                window._viewer.clear()
        self.keep_content_visible = False
        self.update_main_stack()
        target = self.restore_target
        self.restore_target = None
        if target is not None and loaded_tab_id is not None and target[0] == loaded_tab_id:
            tab = self._tabs.get(loaded_tab_id) if loaded_tab_id in self._tabs else None
            viewer_state = decode_viewer_state(tab.viewer_state_json) if tab is not None else {}
            self.restore_view(studies, target[1], target[2], viewer_state)
            window._process_pending_cache_purges()
            return True
        window._process_pending_cache_purges()
        return False

    def restore_view(
        self,
        studies: list[StudyMetadata],
        instance_uid: str,
        frame_index: int = 0,
        viewer_state: dict | None = None,
    ) -> None:
        """Re-select the instance the tab was showing and re-apply its view state.

        The clip loads asynchronously at its first frame; ``apply_pending_view``
        seeks to the parked frame and restores W/L and the results-overlay
        position once the instance is active (Э9 §3/§5).
        """
        if instance_uid:
            self.pending_view = (
                self._tabs.active_tab_id or "",
                instance_uid,
                int(frame_index or 0),
                dict(viewer_state or {}),
            )
        for study in studies:
            for series in study.series:
                for instance in series.instances:
                    if instance.sop_instance_uid == instance_uid:
                        self._select_instance(instance)
                        return

    def _select_instance(self, instance: InstanceMetadata) -> None:
        self._window._gallery.select_instance(instance)
        self._window._on_instance_selected(instance)
