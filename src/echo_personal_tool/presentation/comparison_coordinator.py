"""Comparison (Multiview) coordination for the main window (N-08, Э9/Э10).

A slice of ``MainWindow`` moved into its own module: the two-pane comparison
mode — its session controller, the pane wrappers, the shared transport bar, the
gallery→pane routing (plain click, Ctrl+click arming, «Открыть слева/справа»),
the pane badges «вкладка N · дата · модальность/вид» (Э10 §6.3, no PHI, also in
the Presenter mirror; an explicit previous-study pair adds the patient context,
because issue 562 requires the identity to be visible) and the stage-1 gate that refuses measurement tools until
pane-scoped state exists (spec §10.2).

Since Э10 the two clips may come from different studies/tabs: comparability is
geometric (frame size + frame rate ±5 %, see ``MultiViewSession.compare_clips``)
and an incompatible pair is shown side by side with the synchronised playback
banned and the reason in the transport strip.

This is the module the next stage grows into: measurements inside the panes
belong to the panes, so the pane-scoped state and the tool gate live here, not
in the window. The window keeps the layout (the v2 document, splitters, the
main viewer) and the widget factories (``_ensure_viewer2``); ``ComparisonWindow``
below is the contract, and the names are the window's own because the
coordinator is a slice of the window in a separate file.

See docs/superpowers/specs/2026-10-01-multiview-two-clips-spec-ru.md and the
roadmap row N-08.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol, cast

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QSplitter, QStackedWidget, QStatusBar, QWidget

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.application.diagnostics import log_boundary_failure
from echo_personal_tool.application.localization import tr
from echo_personal_tool.application.study_comparison import current_study_identity
from echo_personal_tool.domain.models import InstanceMetadata
from echo_personal_tool.domain.models.multiview import PaneId, PlaybackMode
from echo_personal_tool.domain.services.study_comparison import (
    ComparisonIdentity,
    ComparisonMemoryBudget,
    PatientMatch,
    StudyIdentity,
    StudyOrder,
)
from echo_personal_tool.presentation.multiview_controller import MultiViewController
from echo_personal_tool.presentation.multiview_pane import MultiViewPaneWidget
from echo_personal_tool.presentation.multiview_transport import MultiViewTransportBar
from echo_personal_tool.presentation.thumbnail_gallery import ThumbnailGalleryWidget
from echo_personal_tool.presentation.viewer_widget import ViewerWidget

if TYPE_CHECKING:  # the tab coordinator owns the tabs the badge counts
    from echo_personal_tool.presentation.tab_coordinator import TabCoordinator

logger = logging.getLogger(__name__)


class ComparisonWindow(Protocol):
    """Window surface the comparison coordinator drives (implemented by ``MainWindow``)."""

    _controller: AppController
    _gallery: ThumbnailGalleryWidget
    _viewer: ViewerWidget
    _viewer2: ViewerWidget | None
    _viewer_stack: QStackedWidget
    _start_page: QWidget
    _content_widget: QWidget
    _content_splitter: QSplitter
    _has_loaded_study: bool
    _multiview_mode: bool
    _tab_coordinator: TabCoordinator

    def _show_status(self, message: str) -> None: ...

    def _rebuild_layout(self) -> None: ...

    def _enable_multiview_mode(self) -> None: ...

    def _ensure_viewer2(self) -> None: ...

    def _on_instance_selected(self, selected: object) -> None: ...

    def _forward_pane_badges(self, left: str, right: str) -> None: ...

    def statusBar(self) -> QStatusBar: ...  # noqa: N802 - Qt naming


class ComparisonCoordinator:
    """Two clips side by side: panes, transport, routing and the tool gate.

    Owns the :class:`MultiViewController` session plus the pane wrappers and the
    shared transport bar, so one object answers «what is in the panes and what
    may the user do with them» — the question pane-scoped measurements will ask.
    """

    def __init__(self, window: ComparisonWindow) -> None:
        self._window = window
        self._session = MultiViewController(window._controller, window)
        self._session.status_message.connect(window._show_status)
        self._session.warning_requested.connect(self.on_warning)
        self._session.replace_requested.connect(self.on_replace_requested)
        self._session.session_changed.connect(self.refresh_transport)
        self._session.left_pane_released.connect(self.on_left_released)
        self._session.frame_decoded.connect(self._on_frame_decoded)
        self.pane_left: MultiViewPaneWidget | None = None
        self.pane_right: MultiViewPaneWidget | None = None
        self.transport: MultiViewTransportBar | None = None
        #: Pane armed by «Replace clip»: the next gallery click lands there.
        self.pending_pane: PaneId | None = None
        #: UID of the first Ctrl+click pick while Multiview is still off.
        self.start_hint_uid: str | None = None
        self.active_viewer: ViewerWidget | None = None
        #: Explicit current↔previous pair; ``None`` keeps ordinary Multiview.
        self._previous: ComparisonIdentity | None = None
        self._budget = ComparisonMemoryBudget()
        #: Read-only results of the previous study, applied on its first frame.
        self._pending_results: tuple[str, object] | None = None

    # ── state ───────────────────────────────────────────────────────

    @property
    def session(self) -> MultiViewController:
        return self._session

    def enabled(self) -> bool:
        return self._window._multiview_mode

    def owns_source(self, study_uid: str, instance_uid: str | None = None) -> bool:
        """Whether the open comparison pair still shows this source (QH-1a.2 / Э10 §5.1).

        Tab-close and Z3 cache-clear handlers ask before they delete: a source that
        is still in one of the panes must not disappear underneath the comparison
        window. ``instance_uid`` narrows the question to a single clip.
        """
        return self._session.session.references_source(study_uid, instance_uid)

    def pane(self, pane_id: PaneId) -> MultiViewPaneWidget | None:
        return self.pane_left if pane_id is PaneId.LEFT else self.pane_right

    def set_start_hint(self, uid: str | None) -> None:
        self.start_hint_uid = uid
        self._window._gallery.set_multiview_start_hint(uid is not None)

    # ── pane badges (Э10 §6.3) ───────────────────────────────────────

    def pane_badge(
        self,
        instance: InstanceMetadata,
        study_uid: str | None,
        *,
        view_override: str = "",
        pane_id: PaneId | None = None,
    ) -> str:
        """«вкладка N · дата · модальность/вид» for one pane.

        Normally carries no patient data (N-01): only the tab number, the
        study date and the modality/view.  An explicit previous-study pair
        replaces it with «Текущее/Прошлое: дата · пациент» (issue 562): the whole
        point of that mode is that both sides stay identifiable on screen.
        """
        window = self._window
        comparison_badge = self._comparison_badge(instance, study_uid, pane_id)
        if comparison_badge:
            return comparison_badge
        tabs = window._tab_coordinator.tabs
        tab_number = next((i for i, tab in enumerate(tabs.tabs, start=1) if tab.tab_id == tabs.active_tab_id), 1)
        study_date = ""
        for index, tab in enumerate(tabs.tabs, start=1):
            match = next((study for study in tab.studies if study_uid and study.study_uid == study_uid), None)
            if match is not None:
                tab_number = index
                if match.study_datetime is not None:
                    study_date = match.study_datetime.date().isoformat()
                break
        if not study_date:
            for study in getattr(window._controller, "studies", ()) or ():
                if study_uid and study.study_uid == study_uid and study.study_datetime is not None:
                    study_date = study.study_datetime.date().isoformat()
                    break
        view = view_override or instance.series_description or ""
        if instance.modality:
            view = f"{instance.modality}/{view}" if view else instance.modality
        return tr("multiview.pane_badge", tab=tab_number, date=study_date or "—", view=view or "—")

    def pane_badge_texts(self) -> tuple[str, str]:
        """Current pane badges for the Presenter mirror (Э10 §6.3)."""
        session = self._session.session
        return (session.pane(PaneId.LEFT).badge_text, session.pane(PaneId.RIGHT).badge_text)

    def on_view_label_changed(self, pane_id: PaneId, label: str) -> None:
        """The user-chosen view label is part of the pane badge (Э10 §6.3)."""
        pane = self._session.session.pane(pane_id)
        if pane.instance is None:
            return
        self._session.set_pane_badge(
            pane_id, self.pane_badge(pane.instance, pane.study_uid, view_override=label, pane_id=pane_id)
        )
        self.refresh_transport()

    # ── previous-study comparison (issue 562) ───────────────────────

    def current_identity(self) -> StudyIdentity | None:
        """Identity of the study in the main viewer, or None before a load."""
        state = self._window._controller.state_manager.snapshot
        instance = getattr(state, "instance", None)
        if instance is None:
            return None
        study_uid = self.study_uid(instance)
        if not study_uid:
            return None
        active_tab_id = self._window._tab_coordinator.tabs.active_tab_id
        known = current_study_identity(
            self._window._tab_coordinator.tabs.tabs,
            active_tab_id=active_tab_id,
            study_uid=study_uid,
        )
        if known is not None:
            return known
        return StudyIdentity(
            study_uid=study_uid or "",
            patient_surname=getattr(instance, "patient_surname", ""),
            patient_id=getattr(instance, "patient_id", ""),
            issuer_of_patient_id=getattr(instance, "issuer_of_patient_id", ""),
            patient_birth_date=getattr(instance, "patient_birth_date", ""),
            patient_sex=getattr(instance, "patient_sex", ""),
            modality=instance.modality,
            source="",
            tab_id=active_tab_id or "",
            clip_count=1,
        )

    def previous_identity(self) -> ComparisonIdentity | None:
        """The explicit pair currently on screen, if this is a study comparison."""
        return self._previous

    def start_previous(
        self,
        previous: StudyIdentity,
        instance: InstanceMetadata,
        *,
        measurements: object | None = None,
    ) -> bool:
        """Open *instance* beside the current study after identity checks.

        The study is chosen explicitly by the physician; this method only
        refuses an impossible pair (the same study, no current study) and asks
        for confirmation when the metadata prove different patients.  Neither
        study's measurements, calibration or playback state is copied to the
        other pane.
        """
        current = self.current_identity()
        if current is None:
            self._window._show_status(tr("comparison.status.no_current"))
            return False
        identity = ComparisonIdentity(current, previous)
        if not identity.can_start:
            self._window._show_status(tr("comparison.status.same_study"))
            return False
        if identity.needs_patient_confirmation and not self._confirm_different_patient(identity):
            return False
        if self._previous is not None:
            self.close_previous_comparison(announce=False)
        if not self.enabled():
            self._window._enable_multiview_mode()
        self._previous = identity
        self._budget = ComparisonMemoryBudget(self._budget_cap())
        self._pending_results = (instance.sop_instance_uid, measurements) if measurements is not None else None
        if not self.load_into_pane(PaneId.RIGHT, instance):
            self._previous = None
            self._pending_results = None
            self._budget.clear()
            return False
        # The current study stays the measuring side: a stale selection of the
        # right pane from an earlier session must not block its tools.
        self._session.activate(PaneId.LEFT)
        self.active_viewer = self._window._viewer
        self._refresh_left_badge()
        self.refresh_transport()
        self._window._show_status(
            tr("comparison.status.started", date=previous.date_text, patient=previous.patient_text)
        )
        return True

    def close_previous_comparison(self, *, announce: bool = True) -> bool:
        """End the study pair, invalidating late loads and releasing its frames."""
        if self._previous is None:
            return False
        self._previous = None
        self._pending_results = None
        self._budget.clear()
        self._session.cancel_pending()
        if self._session.session.pane(PaneId.RIGHT).has_clip:
            self._session.clear_pane(PaneId.RIGHT)
        self._refresh_left_badge()
        if announce:
            self._window._show_status(tr("comparison.status.closed"))
        self.refresh_transport()
        return True

    def _refresh_left_badge(self) -> None:
        """Re-label the main pane after the pair starts or ends."""
        left = self._session.session.pane(PaneId.LEFT)
        if left.instance is not None:
            self._session.set_pane_badge(
                PaneId.LEFT,
                self.pane_badge(left.instance, left.study_uid, pane_id=PaneId.LEFT),
            )

    def _comparison_badge(
        self,
        instance: InstanceMetadata,
        study_uid: str | None,
        pane_id: PaneId | None,
    ) -> str:
        pair = self._previous
        if pair is None or pane_id is None:
            return ""
        if pane_id is PaneId.LEFT and study_uid == pair.current.study_uid:
            identity = pair.current
            key = "comparison.badge.current"
        elif pane_id is PaneId.RIGHT and study_uid == pair.previous.study_uid:
            identity = pair.previous
            key = "comparison.badge.previous"
        else:
            return ""
        return tr(key, date=identity.date_text, patient=identity.patient_text)

    def _comparison_status(self) -> str:
        pair = self._previous
        if pair is None:
            return ""
        order = {
            StudyOrder.PREVIOUS: "comparison.order.previous",
            StudyOrder.SAME_DAY: "comparison.order.same_day",
            StudyOrder.NEXT: "comparison.order.next",
            StudyOrder.UNKNOWN: "comparison.order.unknown",
        }[pair.order]
        patient = {
            PatientMatch.SAME: "comparison.patient.same",
            PatientMatch.DIFFERENT: "comparison.patient.different",
            PatientMatch.UNVERIFIED: "comparison.patient.unverified",
        }[pair.patient_match]
        return " · ".join(
            (
                tr(order),
                tr(
                    patient,
                    current=pair.current.patient_text,
                    previous=pair.previous.patient_text,
                    patient=pair.previous.patient_text,
                ),
            )
        )

    def _confirm_different_patient(self, pair: ComparisonIdentity) -> bool:
        answer = QMessageBox.question(
            cast("QWidget", self._window),
            tr("comparison.confirm.title"),
            tr(
                "comparison.confirm.body",
                current=pair.current.patient_text,
                previous=pair.previous.patient_text,
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _budget_cap(self) -> int | None:
        access = getattr(self._window._controller, "frame_access", None)
        budget = getattr(access, "budget_bytes", None)
        if not callable(budget):
            return None
        try:
            cap = int(budget())
        except (TypeError, ValueError):
            return None
        return cap if cap > 0 else None

    def _on_frame_decoded(self, pane_id: str, frame_bytes: int) -> None:
        """Charge a comparison frame against the shared budget and paint results."""
        if self._previous is None:
            return
        if not self._budget.reserve(pane_id, frame_bytes):
            self._abort_for_memory()
            return
        if pane_id == PaneId.RIGHT.value and self._pending_results is not None:
            uid, data = self._pending_results
            self._pending_results = None
            self._apply_previous_results(uid, data)

    def _apply_previous_results(self, instance_uid: str, data: object) -> None:
        """Show the previous study's stored manual results read-only."""
        pane = self.pane_right
        if pane is None:
            return
        viewer = pane.viewer
        contours = [
            contour
            for contour in getattr(data, "contours", ())
            if getattr(contour, "sop_instance_uid", "") == instance_uid
        ]
        measurements = [
            measurement
            for measurement in getattr(data, "linear_measurements", ())
            if getattr(measurement, "sop_instance_uid", "") == instance_uid
        ]
        if contours:
            viewer.apply_contours(contours)
        if measurements:
            viewer.add_linear_measurements(measurements)

    def _abort_for_memory(self) -> None:
        self._budget.clear()
        self._previous = None
        self._pending_results = None
        self._session.cancel_pending()
        if self._session.session.pane(PaneId.RIGHT).has_clip:
            self._session.clear_pane(PaneId.RIGHT)
        self._window._show_status(tr("comparison.memory.body"))
        self.refresh_transport()

    # ── panes and transport ─────────────────────────────────────────

    def ensure_transport(self) -> None:
        """Place the shared transport bar under the two cine panes."""
        window = self._window
        if self.transport is None:
            transport = MultiViewTransportBar()
            transport.mode_changed.connect(self._session.set_mode)
            transport.play_pause_clicked.connect(self._session.toggle_global_play)
            transport.stop_clicked.connect(self._session.stop)
            transport.rate_changed.connect(self._session.set_rate)
            transport.cycle_count_changed.connect(self._session.set_cycle_count)
            transport.unlink_clicked.connect(lambda: self._session.set_mode(PlaybackMode.INDEPENDENT))
            self.transport = transport
        transport = self.transport
        transport.refresh_mode(self._session.session.playback_mode)
        transport.set_rate(self._session.session.global_rate)
        transport.set_cycle_count(self._session.session.selected_cycle_count)
        if window._root_layout.indexOf(transport) < 0:
            status_index = window._root_layout.indexOf(window.statusBar())
            if status_index >= 0:
                window._root_layout.insertWidget(status_index, transport)
            else:
                window._root_layout.addWidget(transport)
        transport.show()
        self.refresh_transport()

    def teardown(self) -> None:
        """Leave Multiview: hide the panes, hand the main viewer back.

        The session itself survives so re-enabling the mode restores the second
        clip, its frame and its markers (spec 4.3).  An explicit previous-study
        pair is different: leaving it cancels its loads and drops the read-only
        side, so no result is carried into the next comparison.
        """
        window = self._window
        if self.enabled():
            return
        self.close_previous_comparison(announce=False)
        self._session.pause()
        transport = self.transport
        if transport is not None and window._root_layout.indexOf(transport) >= 0:
            window._root_layout.removeWidget(transport)
            transport.hide()
        for pane_id in (PaneId.LEFT, PaneId.RIGHT):
            pane = self.pane(pane_id)
            if pane is None:
                continue
            if pane_id is PaneId.LEFT:
                # The main viewer returns to its welcome/viewer stack.
                if window._viewer_stack.indexOf(window._viewer) < 0:
                    window._viewer.setParent(None)
                    window._viewer_stack.addWidget(window._viewer)
                window._viewer_stack.setCurrentWidget(
                    window._viewer if window._has_loaded_study else window._start_page
                )
            pane.hide()
            pane.setParent(window._content_widget)

    def ensure_panes(self) -> None:
        """Create the pane wrappers (idempotent)."""
        window = self._window
        if self.pane_left is None:
            self.pane_left = MultiViewPaneWidget(PaneId.LEFT, window._viewer, window)
            self._session.attach_pane(PaneId.LEFT, self.pane_left)
            self.wire_pane(self.pane_left, owned_by_main=True)
        elif self.pane_left.layout().indexOf(window._viewer) < 0:
            # Leaving Multiview hands the main viewer back to its stack;
            # reattach it when Multiview is enabled again.
            window._viewer.setParent(None)
            self.pane_left.layout().insertWidget(1, window._viewer, 1)
        if window._viewer2 is None:
            window._ensure_viewer2()
        self.sync_left_pane_from_controller()
        self._session.refresh()

    def attach_right_viewer(self, viewer: ViewerWidget) -> None:
        """Wrap the second viewer in its pane and introduce it to the session."""
        window = self._window
        pane = MultiViewPaneWidget(PaneId.RIGHT, viewer, window)
        self.pane_right = pane
        self._session.attach_pane(PaneId.RIGHT, pane)
        self.wire_pane(pane, owned_by_main=False)

    def sync_left_pane_from_controller(self) -> None:
        """Adopt the clip the main viewer currently shows into the left pane.

        The left pane is the main viewer, so Multiview never loads a clip into
        it on its own: it mirrors whatever ``AppController`` already opened.
        """
        window = self._window
        state = window._controller.state_manager.snapshot
        instance = state.instance
        if instance is None:
            return
        pane = self._session.session.pane(PaneId.LEFT)
        if pane.instance is not None and pane.instance.sop_instance_uid == instance.sop_instance_uid:
            return
        study_uid = self.study_uid(instance)
        if self._previous is not None and study_uid != self._previous.current.study_uid:
            # The main viewer moved to another study: the explicit pair no
            # longer describes what is on screen.
            self.close_previous_comparison(announce=False)
        pane.instance = instance
        pane.study_uid = study_uid
        pane.current_frame = state.current_frame_index
        pane.load_error = None
        pane.generation += 1
        pane.clear_markers()
        self._session.set_pane_badge(PaneId.LEFT, self.pane_badge(instance, pane.study_uid, pane_id=PaneId.LEFT))
        self._session.session.common_start[PaneId.LEFT] = pane.current_frame
        if self._session.session.active_pane is None:
            self._session.activate(PaneId.LEFT)

    def wire_pane(self, pane: MultiViewPaneWidget, *, owned_by_main: bool) -> None:
        """Connect one pane to the Multiview controller.

        The left pane wraps the application's main viewer, which keeps its own
        controller wiring; only the right pane is fully owned by Multiview.
        """
        pane_id = pane.pane_id
        pane.activated.connect(self.on_pane_activated)
        pane.replace_requested.connect(self._session.request_replace)
        pane.pane_cleared.connect(self.on_pane_cleared)
        pane.marker_place_requested.connect(self._session.place_marker)
        # S2-04 (#308): marker removal has no undo stack (unlike contours and
        # calipers), so every user-initiated destructive path asks first.
        pane.marker_remove_requested.connect(self.on_marker_remove_requested)
        pane.marker_rename_requested.connect(self._session.rename_marker)
        pane.markers_cleared.connect(self.on_markers_cleared)
        pane.all_markers_cleared.connect(self.on_all_markers_cleared)
        pane.marker_seek_requested.connect(self._session.seek_marker)
        pane.view_label_changed.connect(self.on_view_label_changed)
        if owned_by_main:
            return
        viewer = pane.viewer
        viewer.play_pause_requested.connect(lambda: self._session.toggle_play(pane_id))
        viewer.frame_selected.connect(lambda index: self.on_pane_frame_selected(pane_id, index))
        viewer.scroll_frame_selected.connect(lambda index: self._session.scroll_by(pane_id, index))

    def on_main_play_pause_requested(self) -> None:
        """The main viewer is the left pane: let Multiview route its Play.

        In a synchronised mode Play must start both clips through the shared
        clock, not only the left one (spec §5.3); outside Multiview the
        regular AppController keeps the playback.
        """
        if self.enabled():
            self._session.toggle_play(PaneId.LEFT)
        else:
            self._window._controller.toggle_playback()

    # ── tool gate (stage 1) ─────────────────────────────────────────

    def tool_blocked(self, tool_name: str) -> bool:
        """Stage 1 of Multiview is view-only.

        Measurements, contours, Doppler tools and LV-auto need a pane-scoped
        state model that does not exist yet, so they are refused with an
        explanation instead of silently running on the hidden main viewer
        (spec §10.2).  Returns True when the caller must stop.
        """
        if not self.enabled():
            return False
        if self._previous is not None and self._session.session.active_pane in (None, PaneId.LEFT):
            # The current study keeps its normal tools; the previous study is
            # a read-only side and never receives the active tool.
            return False
        message = "comparison.tool.readonly" if self._previous is not None else "multiview.blocked.tools"
        self._window._show_status(tr(message))
        logger.info("[multiview] tool %s refused: pane-scoped state not ready", tool_name)
        return True

    # ── pane events ─────────────────────────────────────────────────

    def on_pane_activated(self, pane_id: PaneId) -> None:
        self._session.activate(pane_id)
        if pane_id is PaneId.RIGHT and self._window._viewer2 is not None:
            self.active_viewer = self._window._viewer2

    def on_pane_cleared(self, pane_id: PaneId) -> None:
        self._session.clear_pane(pane_id)
        if pane_id is PaneId.RIGHT and self._previous is not None:
            # The physician closed the read-only side: end the pair instead of
            # leaving a stale identity and its frame reservation behind.
            self._previous = None
            self._pending_results = None
            self._budget.clear()
            self._refresh_left_badge()
            self.refresh_transport()

    def on_pane_frame_selected(self, pane_id: PaneId, index: int) -> None:
        if self._session.session.playback_mode is PlaybackMode.INDEPENDENT:
            self._session.set_frame(pane_id, index)
            return
        # Synchronised modes: manual positioning moves the shared playhead.
        self._session.seek_marker(pane_id, index)

    def on_replace_requested(self, pane_id: PaneId) -> None:
        """Arm the pane and ask the user to pick a clip in the gallery."""
        self.pending_pane = pane_id
        pane = self.pane(pane_id)
        label = "A" if pane_id is PaneId.LEFT else "B"
        self._window._show_status(tr("multiview.replace.hint", pane=label))
        if pane is not None:
            pane.set_active(True)

    def on_warning(self, title: str, body: str) -> None:
        answer = QMessageBox.question(
            self._window,
            title,
            body,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.No:
            self._session.pause()
            self._window._show_status(tr("multiview.status.independent"))

    # ── destructive marker operations (S2-04 / #308) ───────────────
    #
    # Removing a marker is irreversible — unlike contours and calipers it has
    # no undo stack (S2-04, the marker-delete confirmation plan of 2026-10-31).
    # Every user-initiated destructive path therefore asks first; machine-driven
    # paths (loading a clip into a pane, reset_session) keep working without a
    # dialog.

    def _confirm(self, title: str, body: str) -> bool:
        answer = QMessageBox.question(
            self._window,
            title,
            body,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def on_marker_remove_requested(self, pane_id: PaneId, ordinal: int) -> None:
        if not self._confirm(
            tr("multiview.marker.remove_confirm_title"),
            tr("multiview.marker.remove_confirm_body", number=str(ordinal + 1)),
        ):
            return
        self._session.remove_marker(pane_id, ordinal)

    def on_markers_cleared(self, pane_id: PaneId) -> None:
        if not self._confirm(
            tr("multiview.marker.clear_confirm_title"),
            tr("multiview.marker.clear_confirm_body"),
        ):
            return
        self._session.clear_markers(pane_id)

    def on_all_markers_cleared(self, pane_id: PaneId) -> None:
        if not self._confirm(
            tr("multiview.marker.clear_all_confirm_title"),
            tr("multiview.marker.clear_all_confirm_body"),
        ):
            return
        self._session.clear_all_markers()

    def on_left_released(self, frame_index: int) -> None:
        """Hand the main viewer back to AppController at a given frame."""
        if frame_index > 0:
            self._window._controller.state_manager.set_frame(frame_index)
        self.refresh_transport()

    def refresh_transport(self) -> None:
        transport = self.transport
        if transport is None:
            return
        transport.refresh_mode(self._session.session.playback_mode)
        transport.set_playing(self._session.any_playback_active())
        status = self._session.status_text()
        comparison_status = self._comparison_status()
        transport.set_status(f"{comparison_status} · {status}" if comparison_status else status)
        left_rate, right_rate = self._session.pane_rate_texts()
        transport.set_pane_rates(left_rate, right_rate)
        left_badge, right_badge = self.pane_badge_texts()
        self._window._forward_pane_badges(left_badge, right_badge)
        show_markers = self.enabled() and self._session.session.playback_mode is PlaybackMode.EVENT_CYCLE
        for pane in (self.pane_left, self.pane_right):
            if pane is not None:
                pane.set_marker_bar_visible(show_markers)

    # ── gallery → pane routing (spec §6) ────────────────────────────

    def open_in_pane(self, instance: object, side: str) -> None:
        """Context menu «Открыть слева» / «Открыть справа»."""
        if not isinstance(instance, InstanceMetadata):
            return
        pane_id = PaneId.LEFT if side == "left" else PaneId.RIGHT
        if pane_id is PaneId.LEFT:
            origin = getattr(self._window._tab_coordinator, "comparison_origin_tab_id", None)
            if origin is not None and origin != self._window._tab_coordinator.tabs.active_tab_id:
                self._window._show_status(tr("multiview.left_from_origin"))
                return
            # The left pane is the main viewer: reuse the controller path.
            self._session.activate(PaneId.LEFT)
            self._window._on_instance_selected(instance)
            return
        if not self.enabled():
            self._window._enable_multiview_mode()
        if self.load_into_pane(PaneId.RIGHT, instance):
            self._session.activate(PaneId.RIGHT)
            self.active_viewer = self._window._viewer2

    def study_uid(self, instance: InstanceMetadata) -> str | None:
        for tab in self._window._tab_coordinator.tabs.tabs:
            for study in tab.studies:
                if any(
                    item.sop_instance_uid == instance.sop_instance_uid
                    for series in getattr(study, "series", ())
                    for item in series.instances
                ):
                    return study.study_uid
        try:
            return self._window._controller.resolve_study_uid(instance)
        except Exception as exc:  # noqa: BLE001 - unknown study must not break loading
            log_boundary_failure(logger, "ui.cleanup", exc, code="unexpected", level=logging.DEBUG)
            return None

    def route_start(self, selected: InstanceMetadata, ctrl: bool) -> bool:
        """Arming flow while Multiview is off (spec §6.1).

        The first Ctrl+click only asks for a second clip; the next click on a
        *different* clip launches the mode. Clicking the armed clip again
        dismisses the hint. Returns True when the click was consumed.
        """
        hint_uid = self.start_hint_uid
        if hint_uid is None:
            if ctrl:
                self.set_start_hint(selected.sop_instance_uid)
            return False
        if selected.sop_instance_uid == hint_uid:
            self.set_start_hint(None)
            return False
        self.set_start_hint(None)
        self._window._enable_multiview_mode()
        self.load_into_pane(PaneId.RIGHT, selected)
        self._session.activate(PaneId.RIGHT)
        self.active_viewer = self._window._viewer2
        return True

    def route_gallery_click(self, selected: InstanceMetadata) -> bool:
        """Return True when Multiview consumed the gallery click.

        * Multiview off → ``route_start``: Ctrl+click arms the mode with an
          overlay hint, the second clip launches it (spec §6.1);
        * plain click → the active pane; the left pane is the main viewer, so
          such a click stays on the ``AppController`` path;
        * Ctrl+click → the right pane;
        * a pane armed by «Заменить клип» receives the next click.
        """
        modifiers = QApplication.keyboardModifiers()
        ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        if not self.enabled():
            return self.route_start(selected, ctrl)
        armed = self.pending_pane
        self.pending_pane = None
        session = self._session.session
        # An explicit «Replace clip» choice always wins, even if Ctrl happens
        # to be held.  Otherwise the first ordinary gallery click fills an
        # empty B pane when A already has the current clip, so entering
        # Multiview does not silently replace A again.
        origin = getattr(self._window._tab_coordinator, "comparison_origin_tab_id", None)
        browsing_other_tab = origin is not None and origin != self._window._tab_coordinator.tabs.active_tab_id
        if browsing_other_tab:
            # The main controller still owns the originating tab's left pane.
            target = PaneId.RIGHT
        elif armed is not None:
            target = armed
        elif ctrl:
            target = PaneId.RIGHT
        elif session.pane(PaneId.LEFT).has_clip and not session.pane(PaneId.RIGHT).has_clip:
            target = PaneId.RIGHT
        else:
            target = session.active_pane or PaneId.LEFT
        if target is PaneId.LEFT:
            self._session.activate(PaneId.LEFT)
            return False
        if not self.load_into_pane(target, selected):
            return True
        self._session.activate(target)
        self.active_viewer = self._window._viewer2
        return True

    def load_into_pane(self, pane_id: PaneId, instance: InstanceMetadata) -> bool:
        """Load a clip into one pane after the duplicate guard.

        Since Э10 (spec 2026-10-07 §6) the two clips may come from different
        studies/tabs — comparability is geometric (frame size + fps ±5 %), not
        «same study»; an incompatible pair is still shown side by side and only
        the synchronised playback is banned with a reason.
        """
        session = self._session.session
        target_pane = session.pane(pane_id)
        if pane_id is PaneId.RIGHT and self._previous is not None:
            target_uid = self.study_uid(instance)
            if target_uid != self._previous.previous.study_uid:
                # Replacing the right clip by hand ends the named pair instead
                # of leaving its date/patient badge on a different study.
                self.close_previous_comparison(announce=False)
                target_pane = session.pane(pane_id)
        other_id = session.other(pane_id)
        other_pane = session.pane(other_id)
        if other_pane.instance is not None and other_pane.instance_uid == instance.sop_instance_uid:
            self._window._show_status(tr("multiview.duplicate", pane="A" if other_id is PaneId.LEFT else "B"))
            self._session.activate(other_id)
            return False
        if target_pane.instance is not None and target_pane.instance_uid == instance.sop_instance_uid:
            self._session.activate(pane_id)
            return False
        study_uid = self.study_uid(instance)
        self._session.load_instance(
            pane_id, instance, study_uid, badge=self.pane_badge(instance, study_uid, pane_id=pane_id)
        )
        reason = self._session.comparison_reason()
        if reason is not None:
            self._window._show_status(reason)
        return True

    # ── session lifetime ────────────────────────────────────────────

    def reset_session(self) -> None:
        """A new study/patient invalidates every pane (spec 4.3)."""
        self._previous = None
        self._pending_results = None
        self._budget.clear()
        self._session.reset_session()

    def shutdown(self) -> None:
        self._budget.clear()
        self._previous = None
        self._pending_results = None
        self._session.shutdown()
