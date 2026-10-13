"""Server download coordination for the main window (N-08, Э9/PR-C).

A slice of ``MainWindow`` moved into its own module: the PACS download dialog
and everything that outlives it — the Z3 cache of a run, the download history
of the session (``DownloadHistory``), the upload dialog, and the rule that a
closed tab's cache session is deleted only once nothing on screen uses it
(D-27).

The window keeps the widgets and the session preferences; this module owns the
cache and the queue. ``DownloadWindow`` below is the contract — the names are
the window's own, because the coordinator is a slice of the window in a
separate file, and tests steer the flow by replacing ``_active_orthanc_cache_sessions``
or ``_open_server_batch`` on the window.

See docs/superpowers/specs/2026-10-07-tabs-start-page-spec-ru.md §3–§5 and the
roadmap row N-08.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol, cast

from PySide6.QtWidgets import QMessageBox, QWidget

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.application.download_history import DownloadHistory
from echo_personal_tool.application.tab_session import TAB_ORIGIN_FOLDER, TAB_ORIGIN_SERVER
from echo_personal_tool.domain.models.metadata import StudyMetadata
from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.infrastructure.orthanc_cache import OrthancSessionCache
from echo_personal_tool.infrastructure.server_client_factory import (
    make_dicom_query_service,
    make_dicom_retrieve_service,
    make_dicom_web_client,
    make_dimse_client,
)
from echo_personal_tool.infrastructure.server_settings import load_server_settings
from echo_personal_tool.infrastructure.user_preferences import SESSION_SOURCE_FOLDER, SESSION_SOURCE_SERVER
from echo_personal_tool.presentation.orthanc_study_dialog import OrthancStudyDialog
from echo_personal_tool.presentation.tab_coordinator import TabCoordinator
from echo_personal_tool.presentation.viewer_widget import ViewerWidget

logger = logging.getLogger(__name__)


class DownloadWindow(Protocol):
    """Window surface the download coordinator drives (implemented by ``MainWindow``)."""

    _controller: AppController
    _viewer: ViewerWidget
    _tab_coordinator: TabCoordinator

    def _show_status(self, message: str) -> None: ...

    def _active_orthanc_cache_sessions(self) -> set[str]: ...

    def _open_server_batch(self, studies: list[StudyMetadata], session_id: str) -> bool: ...

    def _remember_session_source(self, source: str, folder: str | None = None) -> None: ...

    def open_folder_path(
        self,
        directory: Path,
        *,
        origin: str = TAB_ORIGIN_FOLDER,
        cache_session_id: str = "",
    ) -> None: ...


class DownloadCoordinator:
    """PACS downloads: dialog, batch hand-off, cache lifetime, upload.

    The cache (Z3) belongs to the coordinator so the queue that deletes closed
    tabs' sessions and the code that reads them live together; the window asks
    for the cache through ``cache`` and hands the protection predicate back in
    (``_active_orthanc_cache_sessions``), which the measurement-storage dialog
    also uses.
    """

    def __init__(
        self,
        window: DownloadWindow,
        *,
        cache: OrthancSessionCache,
        history: DownloadHistory | None = None,
    ) -> None:
        self._window = window
        self._cache = cache
        self._history = history if history is not None else DownloadHistory()
        #: Cache sessions of closed tabs; deleted once nothing uses them (D-27).
        self._pending_purges: set[str] = set()

    # ── resources ───────────────────────────────────────────────────

    @property
    def cache(self) -> OrthancSessionCache:
        return self._cache

    @property
    def history(self) -> DownloadHistory:
        return self._history

    def prepare(self) -> None:
        """Drop cache sessions left behind by an earlier run (startup)."""
        try:
            stale_sessions = self._cache.clear_stale()
        except OSError:
            # Cache recovery must not prevent opening the application.
            logger.warning("Could not inspect stale Orthanc cache sessions")
            return
        if stale_sessions:
            logger.info("Removed %d stale Orthanc cache session(s) at startup", stale_sessions)

    def clear_all(self) -> None:
        """Delete the whole cache; used on exit when the preference asks for it."""
        try:
            self._cache.clear_all()
        except OSError:
            # Best effort only: filesystem deletion is not a secure wipe,
            # and a cache I/O error should not block closing the viewer.
            logger.warning("Could not clear the Orthanc cache on exit")

    # ── cache session lifetime ──────────────────────────────────────

    def active_cache_sessions(self) -> set[str]:
        """Cache sessions backing the currently loaded PACS studies.

        During an asynchronous restore the controller already knows the incoming
        study set, while the viewer may still reference the old one: protect
        BOTH sets until the new selection is published. Every open tab's session
        counts as well — one batch can feed several tabs (spec §3).
        """
        window = self._window
        active: set[str] = set()
        protected_studies = list(window._controller.studies)
        protected_studies.extend(getattr(window._controller, "retained_studies_for_cache", ()))
        for study in protected_studies:
            for series in getattr(study, "series", ()):
                for instance in getattr(series, "instances", ()):
                    path = getattr(instance, "path", None)
                    if path is None:
                        continue
                    session_id = self._cache.session_id_for_path(Path(path))
                    if session_id is not None:
                        active.add(session_id)
        active.update(tab.cache_session_id for tab in window._tab_coordinator.tabs.tabs if tab.cache_session_id)
        return active

    def queue_purge(self, session_id: str) -> None:
        if session_id:
            self._pending_purges.add(session_id)

    def process_pending_purges(self) -> None:
        """Delete a closed tab's PACS cache once nothing on screen still uses it (D-27)."""
        if not self._pending_purges:
            return
        protected = self._window._active_orthanc_cache_sessions()
        for session_id in sorted(self._pending_purges - protected):
            try:
                self._cache.clear_session(session_id)
            except OSError:
                logger.warning("Could not clear a closed tab's Orthanc cache session")
            self._pending_purges.discard(session_id)

    # ── server dialog ───────────────────────────────────────────────

    def open_dialog(self, *, preselect_study_uid: str | None = None) -> None:
        """Open the «load from server» dialog and route its result (D-27/D-29).

        ``preselect_study_uid`` marks the study a «Недавние исследования» row
        pointed at (Э5 §7.3), so the dialog opens with it already selected.
        """
        from echo_personal_tool.presentation.ui_animations import exec_animated

        window = self._window
        settings = load_server_settings()
        # Build ONE DICOMweb client and ONE DIMSE client and share them across
        # the query service, the retrieve service and the dialog (L4): avoids
        # duplicating HTTP connection pools per component.  The caller owns the
        # shared client and closes it after the dialog is dismissed.
        client = make_dicom_web_client(settings)
        dimse_client = make_dimse_client(settings)
        query_service = make_dicom_query_service(settings, web=client, dimse=dimse_client)
        retrieve_service = make_dicom_retrieve_service(
            settings,
            web_client=client,
            dimse_client=dimse_client,
        )
        dialog = OrthancStudyDialog(
            client,
            self._cache,
            _dialog_parent(window),
            server_settings=settings,
            query_service=query_service,
            retrieve_service=retrieve_service,
            preselect_study_uid=preselect_study_uid,
        )
        exec_animated(dialog)
        try:
            client.close()
        except Exception:  # noqa: BLE001
            logger.debug("Could not close the Orthanc dialog client", exc_info=True)
        result = dialog.result_data()
        downloaded = dialog.downloaded_studies()
        disk_path = dialog.completed_disk_download_path()
        logger.info(
            "[MW] dialog closed: result=%s disk_path=%s downloaded_count=%d total_instances=%d",
            result,
            disk_path,
            len(downloaded),
            sum(len(s.instances) for st in downloaded for s in st.series),
        )
        if disk_path is not None:
            # Re-scan the exported short paths so the active StudyMetadata also
            # points at files that persist after the Orthanc cache is cleaned.
            # True Study/Series/SOP UIDs are reconstructed from DICOM headers.
            # A disk export survives the cache cleanup, so "Last session" can
            # reopen the folder itself (D-27).
            window._remember_session_source(SESSION_SOURCE_FOLDER, str(disk_path))
            window.open_folder_path(disk_path)
        elif result:
            # Cache-only download: the images are deleted on exit, so the next
            # "Last session" has to go through the server dialog again (Q-05).
            window._remember_session_source(SESSION_SOURCE_SERVER)
            session_id, _study_uid = result
            if downloaded:
                window._open_server_batch(downloaded, session_id)
            else:
                path = self._cache.session_path(session_id)
                logger.info("[MW] scan fallback: session=%s directory_exists=%s", session_id[:8], path.exists())
                window.open_folder_path(path, origin=TAB_ORIGIN_SERVER, cache_session_id=session_id)
        else:
            logger.warning("[MW] dialog closed with no result (user cancelled or error)")

    # ── upload (send to server) ─────────────────────────────────────

    def send_to_server(self) -> None:
        """Upload the loaded study with the annotations drawn in the viewer."""
        from echo_personal_tool.presentation.dicom_upload_dialog import run_dicom_upload_dialog

        window = self._window
        studies = window._controller.studies
        if not studies:
            QMessageBox.information(
                _dialog_parent(window),
                tr("dialog.dicom_upload.title"),
                tr("dialog.dicom_upload.no_files"),
            )
            return
        annotations = _collect_annotations(window._viewer)
        run_dicom_upload_dialog(
            _dialog_parent(window),
            studies,
            load_server_settings(),
            annotations=annotations,
        )


def _dialog_parent(window: object) -> QWidget:
    """Modal dialogs are parented to the window (always a QWidget at runtime)."""
    return cast(QWidget, window)


def _collect_annotations(viewer: ViewerWidget | None) -> dict:
    """Contours and calipers of the current study, grouped by SOP Instance UID."""
    annotations: dict = {}
    if viewer is None:
        return annotations
    try:
        contours = viewer.contours()
        if hasattr(viewer, "_stored_linear_measurements"):
            linear = list(viewer._stored_linear_measurements.values())
        else:
            linear = []
        for shape in (*contours, *linear):
            uid = shape.sop_instance_uid or ""
            if uid:
                annotations.setdefault(uid, []).append(shape)
    except Exception:
        logger.warning("Could not collect annotations; uploading without them", exc_info=True)
    return annotations
