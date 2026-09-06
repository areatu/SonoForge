"""Dialog for browsing Orthanc studies and downloading selected series."""

from __future__ import annotations

import logging
import shutil
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import shiboken6
from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.application.workers.orthanc_download_worker import OrthancDownloadWorker
from echo_personal_tool.domain.models import StudyMetadata
from echo_personal_tool.domain.models.orthanc import SeriesInfo
from echo_personal_tool.domain.ports import DicomWebClient, QuerySource
from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.infrastructure.orthanc_cache import OrthancSessionCache
from echo_personal_tool.infrastructure.orthanc_client import OrthancDicomWebClient
from echo_personal_tool.infrastructure.server_client_factory import (
    make_dicom_retrieve_service,
)
from echo_personal_tool.infrastructure.server_settings import (
    ServerSettings,
    load_server_settings,
    save_server_settings,
)

_STUDY_UID_ROLE = Qt.ItemDataRole.UserRole
_SERIES_UID_ROLE = Qt.ItemDataRole.UserRole + 1
_SORT_ROLE = Qt.ItemDataRole.UserRole + 2
_CANCEL_FORCE_CLOSE_MS = 30_000

log = logging.getLogger(__name__)


class _StudyItem(QTreeWidgetItem):
    """Sort by the raw date/string stored in _SORT_ROLE, not display text."""

    def __lt__(self, other: QTreeWidgetItem) -> bool:
        col = self.treeWidget().sortColumn() if self.treeWidget() else 0
        a = self.data(col, _SORT_ROLE)
        b = other.data(col, _SORT_ROLE)
        return str(a or "") < str(b or "")


class _StudyQuerySignals(QObject):
    finished = Signal(object, object)  # (list[StudyInfo] | None, error_message | None)


class _StudyQueryWorker(QRunnable):
    """Fetch studies from Orthanc in a background thread."""

    def __init__(self, query_fn: Callable[[], list], signals: _StudyQuerySignals) -> None:
        super().__init__()
        self._query_fn = query_fn
        self._signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:
        error = None
        try:
            studies = self._query_fn()
        except Exception as exc:  # noqa: BLE001
            log.warning("[DLG] study query failed: %s", exc)
            studies = []
            error = str(exc)
        try:
            self._signals.finished.emit(studies, error)
        except RuntimeError:
            log.debug("[DLG] study query worker: signal already deleted, skipping emit")


class _SeriesQuerySignals(QObject):
    finished = Signal(object)  # (study_uid, series_list, error_message)


class _SeriesQueryWorker(QRunnable):
    """Fetch series for a single study in a background thread."""

    def __init__(self, study_uid: str, query_fn: Callable[[str], list], signals: _SeriesQuerySignals) -> None:
        super().__init__()
        self._study_uid = study_uid
        self._query_fn = query_fn
        self._signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            series = self._query_fn(self._study_uid)
            error = None
        except Exception as exc:  # noqa: BLE001
            log.warning("[DLG] series query failed for %s: %s", self._study_uid[:16], exc)
            series = []
            error = str(exc)
        try:
            self._signals.finished.emit((self._study_uid, series, error))
        except RuntimeError:
            log.debug("[DLG] series query worker: signal already deleted, skipping emit")


class OrthancStudyDialog(QDialog):
    def __init__(
        self,
        client: DicomWebClient,
        cache: OrthancSessionCache,
        parent: QWidget | None = None,
        *,
        server_settings: ServerSettings | None = None,
        base_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        query_service=None,  # DicomQueryService | None
        retrieve_service=None,  # DicomRetrieveService | None
    ) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self._client = client
        self._cache = cache
        self._server_settings = server_settings
        self._base_url = base_url
        self._username = username
        self._password = password
        self._query_service = query_service
        # The caller may inject a retrieve service sharing the same HTTP/DIMSE
        # clients (L4). Fall back to building one from settings for callers
        # that do not provide it (kept for backwards compatibility).
        self._retrieve_service = retrieve_service
        if self._retrieve_service is None and server_settings is not None:
            self._retrieve_service = make_dicom_retrieve_service(server_settings)
        # When services are injected (L4), the caller owns the shared client
        # and is responsible for closing it.  The dialog only closes a client
        # it created itself via the fallback retrieve-service path.
        self._owns_client = query_service is None and retrieve_service is None
        self._result: tuple[str, str] | None = None
        self._downloading = False
        self._worker: OrthancDownloadWorker | None = None
        self._session_id: str | None = None
        self._client_closed = False
        self._close_pending = False
        self._pending_downloads: list[tuple[str, list[str]]] = []
        self._completed_downloads = 0
        self._failed_downloads = 0
        self._total_studies = 0
        self._downloaded_studies: list[StudyMetadata] = []
        self._force_close_timer = QTimer(self)
        self._force_close_timer.setSingleShot(True)
        self._force_close_timer.timeout.connect(self._force_close_if_still_downloading)
        self._series_loading: set[str] = set()
        self._closed = False
        self._active_workers: list[tuple[QRunnable, QObject]] = []
        self._save_to_disk_path: str = ""
        self._init_timer = QTimer(self)
        self._init_timer.setSingleShot(True)
        self._init_timer.timeout.connect(self._init_network)
        self._reject_timer = QTimer(self)
        self._reject_timer.setSingleShot(True)
        self._reject_timer.timeout.connect(self.reject)

        self.setWindowTitle(tr("dialog.orthanc.title"))
        self.resize(800, 520)

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText(tr("orthanc.patient_name_placeholder"))
        self._find_btn = QPushButton(tr("orthanc.find"))
        self._find_btn.clicked.connect(self._on_find)

        # Source selector (DICOMweb / DIMSE / Auto)
        self._source_combo = QComboBox()
        self._source_combo.addItem(tr("server_settings.query_source_dicomweb"), "dicomweb")
        self._source_combo.addItem(tr("server_settings.query_source_dimse"), "dimse")
        self._source_combo.addItem(tr("server_settings.query_source_auto"), "auto")
        if self._query_service is not None:
            source_idx = self._source_combo.findData(self._query_service.source.value)
            self._source_combo.setCurrentIndex(max(source_idx, 0))
        self._source_combo.currentIndexChanged.connect(self._on_source_changed)

        # Date filter
        self._date_filter_combo = QComboBox()
        self._date_filter_combo.addItem(tr("orthanc.date_filter_all"), 0)
        self._date_filter_combo.addItem(tr("orthanc.date_filter_1d"), 1)
        self._date_filter_combo.addItem(tr("orthanc.date_filter_3d"), 3)
        self._date_filter_combo.addItem(tr("orthanc.date_filter_30d"), 30)
        self._date_filter_combo.currentIndexChanged.connect(self._on_date_filter_changed)

        search_row = QHBoxLayout()
        search_row.addWidget(self._search_edit, stretch=1)
        search_row.addWidget(self._source_combo)
        search_row.addWidget(self._date_filter_combo)
        search_row.addWidget(self._find_btn)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(
            [tr("orthanc.table_patient"), tr("orthanc.table_date"), tr("orthanc.table_study_series")]
        )
        self._tree.setColumnWidth(0, 200)
        self._tree.setColumnWidth(1, 100)
        self._tree.setSortingEnabled(True)
        self._tree.sortByColumn(1, Qt.SortOrder.DescendingOrder)
        self._tree.itemExpanded.connect(self._on_item_expanded)
        self._tree.itemChanged.connect(self._on_item_changed)
        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._tree.setRootIsDecorated(True)
        self._tree.itemClicked.connect(self._on_item_clicked)

        self._status_label = QLabel()
        self._progress = QProgressBar()
        self._progress.hide()

        self._load_btn = QPushButton(tr("orthanc.load"))
        self._load_btn.setEnabled(False)
        self._load_btn.clicked.connect(self._on_load)

        self._save_disk_btn = QPushButton(tr("orthanc.save_to_disk"))
        self._save_disk_btn.setEnabled(False)
        self._save_disk_btn.clicked.connect(self._on_save_to_disk)

        self._cancel_btn = QPushButton(tr("orthanc.cancel"))
        self._cancel_btn.clicked.connect(self._on_cancel)

        buttons_row = QHBoxLayout()
        buttons_row.addStretch()
        buttons_row.addWidget(self._load_btn)
        buttons_row.addWidget(self._save_disk_btn)
        buttons_row.addWidget(self._cancel_btn)

        # Custom title bar for frameless dialog
        self._drag_pos: QPoint | None = None
        title_bar = QWidget()
        title_bar.setFixedHeight(32)
        title_bar.setStyleSheet("background: #1a2332;")
        tb_layout = QHBoxLayout(title_bar)
        tb_layout.setContentsMargins(8, 0, 4, 0)
        tb_layout.setSpacing(0)
        title_label = QLabel(tr("dialog.orthanc.title"))
        title_label.setStyleSheet("color: #f1f5f9; font-weight: bold; border: none;")
        tb_layout.addWidget(title_label)
        tb_layout.addStretch(1)
        from echo_personal_tool.presentation.system_bar import _load_icon

        btn_close = QPushButton()
        btn_close.setIcon(_load_icon("close"))
        btn_close.setObjectName("closeButton")
        btn_close.setFixedSize(28, 23)
        btn_close.clicked.connect(self.reject)
        tb_layout.addWidget(btn_close)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(title_bar)
        layout.addLayout(search_row)
        layout.addWidget(self._tree, stretch=1)
        layout.addWidget(self._status_label)
        layout.addWidget(self._progress)
        layout.addLayout(buttons_row)

        self._init_timer.start(0)

    def _init_network(self) -> None:
        if not self._is_alive():
            return
        log.info("[DLG] _init_network called")
        self._status_label.setText(tr("orthanc.searching"))
        self._load_studies_async()

    def _load_studies_async(self) -> None:
        """Query studies in a background thread to avoid blocking the UI."""
        if not self._is_alive():
            return
        if not self._query_source_available():
            self._status_label.setText(tr("orthanc.dimse_disabled"))
            return
        text = self._search_edit.text().strip()
        patient_name = text or None

        def _query() -> list:
            if self._query_service is not None:
                return self._query_service.query_studies(patient_name=patient_name)
            return self._client.query_studies(patient_name=patient_name)

        signals = _StudyQuerySignals()
        signals.finished.connect(self._on_studies_loaded)
        worker = _StudyQueryWorker(_query, signals)
        self._active_workers.append((worker, signals))
        QThreadPool.globalInstance().start(worker)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < 32:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def result_data(self) -> tuple[str, str] | None:
        """Return (session_id, study_uid) after successful download, else None."""
        return self._result

    def downloaded_studies(self) -> list[StudyMetadata]:
        """Return pre-scanned StudyMetadata from download worker (P4)."""
        return self._downloaded_studies

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        log.info("[DLG] closeEvent: downloading=%s", self._downloading)
        if self._downloading:
            self._close_pending = True
            self._on_cancel()
            event.ignore()
            return
        self._shutdown()
        super().closeEvent(event)

    def reject(self) -> None:
        log.info("[DLG] reject: downloading=%s result=%s", self._downloading, self._result)
        if self._downloading:
            self._close_pending = True
            self._on_cancel()
            return
        self._shutdown()
        super().reject()

    def accept(self) -> None:
        from echo_personal_tool.presentation.ui_animations import hide_dialog_animated

        log.info("[DLG] accept: result=%s downloaded=%d", self._result, len(self._downloaded_studies))
        try:
            self._release_client()
        except Exception:  # noqa: BLE001
            pass
        self._shutdown()
        hide_dialog_animated(self, on_done=super().accept)

    def _shutdown(self) -> None:
        """Stop pending callbacks so background workers can never touch a closed dialog."""
        if not self._is_alive():
            return
        self._closed = True
        self._init_timer.stop()
        self._reject_timer.stop()
        self._force_close_timer.stop()
        self._series_loading.clear()
        for _worker, signals in self._active_workers:
            signals.finished.disconnect()
        self._active_workers.clear()
        self._release_client()

    def _is_alive(self) -> bool:
        """True while the dialog can still safely handle callbacks."""
        return not self._closed and shiboken6.isValid(self)

    def _release_client(self) -> None:
        if self._client_closed:
            return
        if not self._owns_client:
            self._client_closed = True
            return
        if isinstance(self._client, OrthancDicomWebClient):
            self._client.close()
            self._client_closed = True

    def _on_source_changed(self) -> None:
        source_val = self._source_combo.currentData()
        if self._query_service is not None and source_val:
            self._query_service.source = QuerySource(source_val)
        if source_val:
            self._persist_query_source(str(source_val))
        self._show_source_hint(str(source_val))

    @staticmethod
    def _retrieval_source_label(value: str) -> str:
        """Human-readable label of the *actual* download source in settings."""
        return {
            "wado": "WADO-RS",
            "dimse": "C-GET",
            "cmove": "C-MOVE",
            "auto": "Auto",
        }.get(value, value)

    def _show_source_hint(self, source_val: str) -> None:
        """Show an honest status hint about what the current source means.

        The combo only switches the *query* protocol; the download protocol
        is controlled separately by settings.retrieval_source, so the hint
        reports both instead of claiming "download via C-GET" unconditionally.
        """
        if self._downloading:
            return  # never clobber the download progress status
        if source_val != "dimse":
            return
        if not self._query_source_available():
            self._status_label.setText(tr("orthanc.dimse_disabled"))
            return
        retrieval = self._retrieval_source_label(
            self._server_settings.retrieval_source if self._server_settings is not None else "auto"
        )
        self._status_label.setText(tr("orthanc.dimse_info_banner", retrieval=retrieval))

    def _query_source_available(self) -> bool:
        """True when the currently selected query source can actually run.

        DIMSE requires either mock mode or DIMSE enabled in server settings;
        otherwise a search would silently return an empty list.
        """
        source_val = self._source_combo.currentData()
        if source_val != "dimse":
            return True
        if self._server_settings is None:
            return True
        return self._server_settings.use_mock or self._server_settings.dimse_enabled

    def _persist_query_source(self, source_val: str) -> None:
        if source_val not in {s.value for s in QuerySource}:
            return
        current = load_server_settings()
        if current.query_source == source_val:
            return
        updated = replace(current, query_source=source_val)
        save_server_settings(updated)
        if self._server_settings is not None:
            self._server_settings = replace(self._server_settings, query_source=source_val)

    def _on_studies_loaded(self, studies: list, error: str | None = None) -> None:
        if not self._is_alive():
            return
        log.info("[DLG] _on_studies_loaded: count=%d error=%s", len(studies), error)
        self._tree.blockSignals(True)
        self._tree.clear()
        if error and not studies:
            # Server unreachable / auth failure / DIMSE refused — surface the
            # reason instead of showing an empty "Ready" list.
            error_item = QTreeWidgetItem(["", "", tr("orthanc.find_error", message=error[:200])])
            error_item.setFlags(error_item.flags() & ~Qt.ItemFlag.ItemIsSelectable & ~Qt.ItemFlag.ItemIsUserCheckable)
            self._tree.addTopLevelItem(error_item)
            self._status_label.setText(tr("orthanc.find_error", message=error[:200]))
            self._tree.blockSignals(False)
            self._update_load_button()
            return
        self._tree.blockSignals(False)
        if studies:
            self._build_study_tree(studies)
            self._filter_studies_by_date(self._date_filter_combo.currentData())
        if error:
            self._status_label.setText(tr("orthanc.find_error", message=error[:200]))
        elif not studies:
            self._status_label.setText(tr("orthanc.ready"))
        self._update_load_button()

    def _build_study_tree(self, studies: list) -> None:
        studies = sorted(
            studies,
            key=lambda s: (s.study_date or "", s.patient_name or ""),
            reverse=True,
        )
        self._tree.blockSignals(True)
        self._tree.clear()
        for study in studies:
            patient_name = study.patient_name or ""
            study_date_raw = study.study_date or ""
            display_date = self._format_study_date(study_date_raw)
            desc = study.study_description or ""
            item = _StudyItem([patient_name, display_date, desc])
            item.setData(0, _STUDY_UID_ROLE, study.study_uid)
            item.setData(0, _SORT_ROLE, patient_name)
            item.setData(1, _SORT_ROLE, study_date_raw)
            item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
            self._tree.addTopLevelItem(item)
        self._tree.blockSignals(False)
        self._status_label.setText(tr("orthanc.ready"))

    def _load_studies(self) -> None:
        """Synchronous wrapper for _on_find button — uses async internally."""
        self._load_studies_async()

    def _format_study_date(self, raw_date: str) -> str:
        """Convert DICOM date 'YYYYMMDD' to 'DD.MM.YYYY'."""
        if len(raw_date) == 8 and raw_date.isdigit():
            return f"{raw_date[6:8]}.{raw_date[4:6]}.{raw_date[:4]}"
        return raw_date

    def _filter_studies_by_date(self, days: int) -> None:
        """Hide/show top-level study items based on the selected date filter."""
        if days <= 0:
            for i in range(self._tree.topLevelItemCount()):
                self._tree.topLevelItem(i).setHidden(False)
            return
        cutoff = datetime.now() - timedelta(days=days)
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            raw_date = item.data(1, _SORT_ROLE) or ""
            try:
                item_date = datetime.strptime(raw_date, "%Y%m%d")
            except ValueError:
                item.setHidden(False)
                continue
            item.setHidden(item_date < cutoff)

    def _on_date_filter_changed(self) -> None:
        days = self._date_filter_combo.currentData()
        self._filter_studies_by_date(days)

    def _series_label(self, series: SeriesInfo) -> str:
        parts = [series.modality, series.description]
        if series.instance_count is not None:
            parts.append(f"{series.instance_count} {tr('orthanc.instances_suffix')}")
        return " — ".join(part for part in parts if part)

    def _on_find(self) -> None:
        from echo_personal_tool.presentation.ui_animations import loading_button

        with loading_button(self._find_btn, tr("orthanc.searching")):
            self._load_studies()

    def _on_item_expanded(self, item: QTreeWidgetItem) -> None:
        if not self._is_alive():
            return
        if item.parent() is not None:
            return
        if item.childCount() > 0:
            return

        study_uid = item.data(0, _STUDY_UID_ROLE)
        if not study_uid:
            return

        study_uid = str(study_uid)
        if study_uid in self._series_loading:
            return
        self._series_loading.add(study_uid)

        loading_item = QTreeWidgetItem(["", "", tr("orthanc.searching")])
        loading_item.setFlags(loading_item.flags() & ~Qt.ItemFlag.ItemIsSelectable & ~Qt.ItemFlag.ItemIsUserCheckable)
        item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicator)
        item.addChild(loading_item)

        def _query(uid: str) -> list:
            if self._query_service is not None:
                return self._query_service.query_series(uid)
            return self._client.query_series(uid)

        signals = _SeriesQuerySignals()
        signals.finished.connect(self._on_series_loaded)
        worker = _SeriesQueryWorker(study_uid, _query, signals)
        self._active_workers.append((worker, signals))
        QThreadPool.globalInstance().start(worker)

    def _on_series_loaded(self, result: object) -> None:
        if not self._is_alive():
            return
        study_uid, series_list, error = result  # type: ignore[misc]
        log.info(
            "[DLG] _on_series_loaded: study_uid=%s count=%d error=%s",
            study_uid[:16],
            len(series_list),
            error,
        )
        self._series_loading.discard(study_uid)

        target_item: QTreeWidgetItem | None = None
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            if item.data(0, _STUDY_UID_ROLE) == study_uid:
                target_item = item
                break

        if target_item is None:
            return

        self._tree.blockSignals(True)
        target_item.takeChildren()
        target_item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)

        if error and not series_list:
            error_item = QTreeWidgetItem(["", "", tr("orthanc.series_query_error", message=error[:200])])
            error_item.setFlags(error_item.flags() & ~Qt.ItemFlag.ItemIsSelectable & ~Qt.ItemFlag.ItemIsUserCheckable)
            target_item.addChild(error_item)
        else:
            for series in series_list:
                child = QTreeWidgetItem(["", "", self._series_label(series)])
                child.setData(0, _SERIES_UID_ROLE, series.series_uid)
                child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                child.setCheckState(0, Qt.CheckState.Unchecked)
                target_item.addChild(child)
        self._tree.blockSignals(False)

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        """Single-click expands/collapses study items (top-level only)."""
        if item.parent() is not None:
            return
        if not item.data(0, _STUDY_UID_ROLE):
            return
        item.setExpanded(not item.isExpanded())

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 0 or not item.data(0, _SERIES_UID_ROLE):
            return
        self._update_load_button()

    def _update_load_button(self) -> None:
        if self._downloading:
            return
        has_checked = len(self._collect_all_checked_series()) > 0
        self._load_btn.setEnabled(has_checked)
        self._save_disk_btn.setEnabled(has_checked)

    def _collect_all_checked_series(self) -> list[tuple[str, list[str]]]:
        """Collect all (study_uid, series_uids) pairs across visible studies.

        Studies hidden by the date filter are skipped: their checked series
        are invisible to the user and must not be silently downloaded.
        """
        result: list[tuple[str, list[str]]] = []
        for index in range(self._tree.topLevelItemCount()):
            study_item = self._tree.topLevelItem(index)
            if study_item.isHidden():
                continue
            study_uid = study_item.data(0, _STUDY_UID_ROLE)
            checked: list[str] = []
            for child_index in range(study_item.childCount()):
                series_item = study_item.child(child_index)
                if series_item.checkState(0) != Qt.CheckState.Checked:
                    continue
                series_uid = series_item.data(0, _SERIES_UID_ROLE)
                if series_uid:
                    checked.append(str(series_uid))
            if checked:
                result.append((str(study_uid), checked))
        return result

    def _on_load(self) -> None:
        from echo_personal_tool.presentation.ui_animations import set_button_loading

        all_series = self._collect_all_checked_series()
        log.info("[DLG] _on_load: checked_series=%d", len(all_series))
        if not all_series:
            return

        session_id = self._cache.create_session()
        self._session_id = session_id
        self._downloading = True
        self._close_pending = False
        # A fresh download batch must not inherit StudyMetadata from a previous
        # (possibly partially failed) batch whose session files were removed.
        self._downloaded_studies = []
        self._result = None
        set_button_loading(self._load_btn, True, "…")
        self._cancel_btn.setText(tr("orthanc.cancel_download"))
        self._cancel_btn.setEnabled(True)
        self._find_btn.setEnabled(False)
        self._tree.setEnabled(False)
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.show()
        self._status_label.setText(tr("orthanc.preparing"))

        self._pending_downloads = list(all_series)
        self._completed_downloads = 0
        self._failed_downloads = 0
        self._total_studies = len(all_series)
        self._start_next_download()

    def _on_save_to_disk(self) -> None:
        """Download selected series to a user-chosen directory on disk."""
        from echo_personal_tool.presentation.ui_animations import set_button_loading

        all_series = self._collect_all_checked_series()
        log.info("[DLG] _on_save_to_disk: checked_series=%d", len(all_series))
        if not all_series:
            return

        # Ask user for directory
        directory = QFileDialog.getExistingDirectory(
            self,
            tr("orthanc.select_directory"),
            "",
            QFileDialog.Option.ShowDirsOnly,
        )
        if not directory:
            return

        # Start download to disk
        session_id = self._cache.create_session()
        self._session_id = session_id
        self._downloading = True
        self._close_pending = False
        self._downloaded_studies = []
        self._result = None
        self._save_to_disk_path = directory
        set_button_loading(self._save_disk_btn, True, "…")
        self._cancel_btn.setText(tr("orthanc.cancel_download"))
        self._cancel_btn.setEnabled(True)
        self._find_btn.setEnabled(False)
        self._tree.setEnabled(False)
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.show()
        self._status_label.setText(tr("orthanc.saving_to_disk", path=directory))

        self._pending_downloads = list(all_series)
        self._completed_downloads = 0
        self._failed_downloads = 0
        self._total_studies = len(all_series)
        self._start_next_download_to_disk()

    def _start_next_download(self) -> None:
        log.info(
            "[DLG] _start_next_download: pending=%d completed=%d total=%d",
            len(self._pending_downloads),
            self._completed_downloads,
            self._total_studies,
        )
        if not self._pending_downloads:
            if self._session_id is None:
                return
            if self._failed_downloads > 0:
                if self._completed_downloads > self._failed_downloads:
                    # Some studies succeeded: keep them (do not wipe the whole
                    # session) and let the user open the successful ones.
                    self._on_partial_done()
                else:
                    # Nothing succeeded — discard the session and report.
                    self._on_failed("", tr("orthanc.partial_failed"))
            else:
                first_study = self._downloaded_studies[0].study_uid if self._downloaded_studies else ""
                self._on_done(self._session_id, first_study)
            return

        study_uid, series_uids = self._pending_downloads.pop(0)
        self._status_label.setText(
            tr("orthanc.loading_progress", current=self._completed_downloads + 1, total=self._total_studies)
        )
        worker = OrthancDownloadWorker(
            self._client,
            self._cache,
            self._session_id,
            study_uid,
            series_uids,
            self,
            server_settings=self._server_settings,
            base_url=self._base_url,
            username=self._username,
            password=self._password,
            retrieve_service=self._retrieve_service,
        )
        self._worker = worker
        worker.signals.progress.connect(self._on_progress)
        worker.signals.status.connect(self._on_status)
        worker.signals.done.connect(self._on_single_study_done)
        worker.signals.failed.connect(self._on_single_study_failed)
        worker.signals.cancelled.connect(self._on_cancelled)
        worker.signals.series_done.connect(self._on_series_done)
        worker.signals.studies_ready.connect(self._on_studies_ready)
        QThreadPool.globalInstance().start(worker)

    def _start_next_download_to_disk(self) -> None:
        """Download next study to disk directory."""
        log.info(
            "[DLG] _start_next_download_to_disk: pending=%d completed=%d total=%d",
            len(self._pending_downloads),
            self._completed_downloads,
            self._total_studies,
        )
        if not self._pending_downloads:
            if self._session_id is None:
                return
            if self._completed_downloads > self._failed_downloads:
                # Copy whatever was downloaded successfully — a partial batch
                # must not silently discard the studies that did succeed.
                self._on_disk_download_done(partial=self._failed_downloads > 0)
            else:
                self._on_failed("", tr("orthanc.partial_failed"))
            return

        study_uid, series_uids = self._pending_downloads.pop(0)
        self._status_label.setText(
            tr("orthanc.disk_download_progress", current=self._completed_downloads + 1, total=self._total_studies)
        )
        worker = OrthancDownloadWorker(
            self._client,
            self._cache,
            self._session_id,
            study_uid,
            series_uids,
            self,
            server_settings=self._server_settings,
            base_url=self._base_url,
            username=self._username,
            password=self._password,
            retrieve_service=self._retrieve_service,
        )
        self._worker = worker
        worker.signals.progress.connect(self._on_progress)
        worker.signals.status.connect(self._on_status)
        worker.signals.done.connect(self._on_single_study_done_to_disk)
        worker.signals.failed.connect(self._on_single_study_failed)
        worker.signals.cancelled.connect(self._on_cancelled)
        worker.signals.series_done.connect(self._on_series_done)
        worker.signals.studies_ready.connect(self._on_studies_ready)
        QThreadPool.globalInstance().start(worker)

    def _on_cancel(self) -> None:
        if self._downloading and self._worker is not None:
            self._status_label.setText(tr("orthanc.download_cancelled"))
            self._cancel_btn.setEnabled(False)
            self._worker.cancel()
            self._force_close_timer.start(_CANCEL_FORCE_CLOSE_MS)
            return
        self.reject()

    def _force_close_if_still_downloading(self) -> None:
        if not self._is_alive():
            return
        if not self._downloading:
            return
        self._downloading = False
        self._worker = None
        if self._session_id is not None:
            self._cache.clear_session(self._session_id)
            self._session_id = None
        self._progress.hide()
        self._shutdown()
        super().reject()

    def _short_uid(self, series_uid: str) -> str:
        return series_uid[:12] + "…" if len(series_uid) > 12 else series_uid

    def _on_progress(self, current: int, total: int, series_uid: str) -> None:
        if not self._is_alive():
            return
        if total > 0:
            self._progress.setRange(0, total)
            self._progress.setValue(min(current, total))
        short_uid = self._short_uid(series_uid)
        self._status_label.setText(tr("orthanc.loading_detail", current=current, total=total, uid=short_uid))

    def _on_status(self, message: str) -> None:
        if not self._is_alive():
            return
        self._status_label.setText(message)

    def _on_series_done(self, series_uid: str, status: str) -> None:
        if not self._is_alive():
            return
        if status == "failed":
            self._status_label.setText(tr("orthanc.series_error_status", uid=self._short_uid(series_uid)))

    def _on_studies_ready(self, studies: list[StudyMetadata]) -> None:
        if not self._is_alive():
            return
        log.info("[DLG] _on_studies_ready: %d studies", len(studies))
        for s in studies:
            total_inst = sum(len(sr.instances) for sr in s.series)
            log.info("[DLG]   study_uid=%s series=%d instances=%d", s.study_uid[:16], len(s.series), total_inst)
        self._downloaded_studies.extend(studies)

    def _reset_after_download(self) -> None:
        from echo_personal_tool.presentation.ui_animations import set_button_loading

        self._downloading = False
        self._worker = None
        self._force_close_timer.stop()
        set_button_loading(self._load_btn, False)
        set_button_loading(self._save_disk_btn, False)

    def _on_single_study_done(self, session_id: str, study_uid: str) -> None:
        if not self._is_alive():
            return
        log.info("[DLG] _on_single_study_done: uid=%s", study_uid[:16])
        self._completed_downloads += 1
        self._status_label.setText(
            tr("orthanc.series_done", current=self._completed_downloads, total=self._total_studies)
        )
        self._start_next_download()

    def _on_single_study_done_to_disk(self, session_id: str, study_uid: str) -> None:
        """Handle single study download completion when saving to disk."""
        if not self._is_alive():
            return
        log.info("[DLG] _on_single_study_done_to_disk: uid=%s", study_uid[:16])
        self._completed_downloads += 1
        self._status_label.setText(
            tr("orthanc.disk_download_progress", current=self._completed_downloads, total=self._total_studies)
        )
        self._start_next_download_to_disk()

    def _on_disk_download_done(self, *, partial: bool = False) -> None:
        """Handle completion of all downloads to disk — copy files from cache to target."""
        if not self._is_alive():
            return
        log.info(
            "[DLG] _on_disk_download_done: path=%s partial=%s",
            self._save_to_disk_path,
            partial,
        )

        # Copy files from cache to user-selected directory (whatever succeeded)
        copied_count = 0
        if self._session_id is not None:
            session_dir = self._cache.session_path(self._session_id)
            if session_dir.is_dir():
                target_dir = Path(self._save_to_disk_path)
                for study_dir in session_dir.iterdir():
                    if not study_dir.is_dir():
                        continue
                    study_target = target_dir / study_dir.name
                    study_target.mkdir(parents=True, exist_ok=True)
                    for series_dir in study_dir.iterdir():
                        if not series_dir.is_dir():
                            continue
                        series_target = study_target / series_dir.name
                        series_target.mkdir(parents=True, exist_ok=True)
                        for dcm_file in series_dir.glob("*.dcm"):
                            shutil.copy2(dcm_file, series_target / dcm_file.name)
                            copied_count += 1
                log.info("[DLG] Copied %d files to %s", copied_count, self._save_to_disk_path)

        self._reset_after_download()
        self._session_id = None
        self._progress.setValue(self._progress.maximum())
        if partial:
            saved = self._completed_downloads - self._failed_downloads
            message = tr(
                "orthanc.disk_download_partial",
                path=self._save_to_disk_path,
                saved=str(saved),
                total=str(self._total_studies),
            )
            self._status_label.setText(message)
            QMessageBox.warning(
                self,
                tr("orthanc.download_error.title"),
                message,
            )
        else:
            message = tr("orthanc.disk_download_complete", path=self._save_to_disk_path)
            self._status_label.setText(message)
            QMessageBox.information(
                self,
                tr("orthanc.download_complete"),
                message,
            )
        self.accept()

    def _on_single_study_failed(self, _uid: str, message: str) -> None:
        if not self._is_alive():
            return
        log.warning("[DLG] _on_single_study_failed: uid=%s msg=%s", _uid[:16] if _uid else "?", message)
        self._completed_downloads += 1
        self._failed_downloads += 1
        self._status_label.setText(
            tr(
                "orthanc.series_error",
                current=self._completed_downloads,
                total=self._total_studies,
                message=message,
            )
        )
        self._start_next_download()

    def _on_partial_done(self) -> None:
        """Some queued studies failed but at least one succeeded.

        Keep the session (and the parsed StudyMetadata) so the successfully
        downloaded studies can be opened, and clearly warn about the rest.
        """
        if not self._is_alive():
            return
        saved = self._completed_downloads - self._failed_downloads
        log.warning(
            "[DLG] _on_partial_done: saved=%d failed=%d total=%d",
            saved,
            self._failed_downloads,
            self._total_studies,
        )
        self._reset_after_download()
        if self._session_id is None:
            return
        session_id = self._session_id
        self._session_id = None
        first_study = self._downloaded_studies[0].study_uid if self._downloaded_studies else ""
        self._result = (session_id, first_study)
        self._progress.setValue(self._progress.maximum())
        message = tr(
            "orthanc.partial_done",
            saved=str(saved),
            total=str(self._total_studies),
        )
        self._status_label.setText(message)
        QMessageBox.warning(
            self,
            tr("orthanc.download_error.title"),
            message,
        )
        self.accept()

    def _on_done(self, session_id: str, study_uid: str) -> None:
        if not self._is_alive():
            return
        log.info(
            "[DLG] _on_done: session=%s studies_downloaded=%d",
            session_id[:8] if session_id else "?",
            len(self._downloaded_studies),
        )
        self._reset_after_download()
        self._session_id = None
        self._result = (session_id, study_uid)
        self._progress.setValue(self._progress.maximum())
        self._status_label.setText(tr("orthanc.download_complete"))
        self.accept()

    def _on_failed(self, _uid: str, message: str) -> None:
        if not self._is_alive():
            return
        log.warning("[DLG] _on_failed: uid=%s msg=%s", _uid[:16] if _uid else "?", message)
        self._reset_after_download()
        if self._pending_downloads and self._session_id is not None:
            self._start_next_download()
            return
        if self._session_id is not None:
            self._cache.clear_session(self._session_id)
            self._session_id = None
        self._downloaded_studies = []
        self._progress.hide()
        self._tree.setEnabled(True)
        self._find_btn.setEnabled(True)
        self._cancel_btn.setText(tr("orthanc.cancel"))
        self._cancel_btn.setEnabled(True)
        self._update_load_button()
        QMessageBox.warning(
            self, tr("orthanc.download_error.title"), tr("orthanc.download_error.body", message=message)
        )

    def _on_cancelled(self, _session_id: str) -> None:
        if not self._is_alive():
            return
        self._reset_after_download()
        self._session_id = None
        self._progress.hide()
        self._tree.setEnabled(True)
        self._find_btn.setEnabled(True)
        self._cancel_btn.setText(tr("orthanc.cancel"))
        self._cancel_btn.setEnabled(True)
        self._update_load_button()
        self._shutdown()
        self._reject_timer.start(0)
