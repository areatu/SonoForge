"""Dialog for browsing Orthanc studies and downloading selected series."""

from __future__ import annotations

import logging
from dataclasses import replace

from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
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
from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.domain.models.orthanc import SeriesInfo, StudyInfo
from echo_personal_tool.domain.ports import DicomWebClient, QuerySource
from echo_personal_tool.infrastructure.orthanc_cache import OrthancSessionCache
from echo_personal_tool.infrastructure.orthanc_client import OrthancDicomWebClient
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
        self._result: tuple[str, str] | None = None
        self._downloading = False
        self._worker: OrthancDownloadWorker | None = None
        self._session_id: str | None = None
        self._client_closed = False
        self._close_pending = False
        self._pending_downloads: list[tuple[str, list[str]]] = []
        self._completed_downloads = 0
        self._total_studies = 0
        self._downloaded_studies: list[StudyMetadata] = []
        self._force_close_timer = QTimer(self)
        self._force_close_timer.setSingleShot(True)
        self._force_close_timer.timeout.connect(self._force_close_if_still_downloading)

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

        search_row = QHBoxLayout()
        search_row.addWidget(self._search_edit, stretch=1)
        search_row.addWidget(self._source_combo)
        search_row.addWidget(self._find_btn)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels([tr("orthanc.table_patient"), tr("orthanc.table_date"), tr("orthanc.table_study_series")])
        self._tree.setColumnWidth(0, 200)
        self._tree.setColumnWidth(1, 100)
        self._tree.setSortingEnabled(True)
        self._tree.sortByColumn(1, Qt.SortOrder.DescendingOrder)
        self._tree.itemExpanded.connect(self._on_item_expanded)
        self._tree.itemChanged.connect(self._on_item_changed)
        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)

        self._status_label = QLabel()
        self._progress = QProgressBar()
        self._progress.hide()

        self._load_btn = QPushButton(tr("orthanc.load"))
        self._load_btn.setEnabled(False)
        self._load_btn.clicked.connect(self._on_load)

        self._cancel_btn = QPushButton(tr("orthanc.cancel"))
        self._cancel_btn.clicked.connect(self._on_cancel)

        buttons_row = QHBoxLayout()
        buttons_row.addStretch()
        buttons_row.addWidget(self._load_btn)
        buttons_row.addWidget(self._cancel_btn)

        # Custom title bar for frameless dialog
        from PySide6.QtWidgets import QSizePolicy
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
        btn_close = QPushButton("\u2715")
        btn_close.setFixedSize(28, 24)
        btn_close.setStyleSheet(
            "QPushButton { color: #94a3b8; border: none; font-size: 14px; }"
            "QPushButton:hover { color: #f1f5f9; background: #e74c3c; border-radius: 3px; }"
        )
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

        QTimer.singleShot(0, self._init_network)

    def _init_network(self) -> None:
        log.info("[DLG] _init_network called")
        self._check_ping()
        log.info("[DLG] _check_ping done, loading studies")
        self._load_studies()
        log.info("[DLG] _load_studies done, tree items=%d", self._tree.topLevelItemCount())

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
        self._release_client()
        super().closeEvent(event)

    def reject(self) -> None:
        log.info("[DLG] reject: downloading=%s result=%s", self._downloading, self._result)
        if self._downloading:
            self._close_pending = True
            self._on_cancel()
            return
        self._release_client()
        super().reject()

    def accept(self) -> None:
        log.info("[DLG] accept: result=%s downloaded=%d", self._result, len(self._downloaded_studies))
        try:
            self._release_client()
        except Exception:  # noqa: BLE001
            pass
        super().accept()

    def _release_client(self) -> None:
        if self._client_closed:
            return
        if isinstance(self._client, OrthancDicomWebClient):
            self._client.close()
            self._client_closed = True

    def _check_ping(self) -> None:
        if self._client.ping():
            self._status_label.setText(tr("orthanc.server_available"))
            return
        self._status_label.setText(tr("orthanc.server_unavailable"))
        QMessageBox.warning(
            self,
            tr("orthanc.connect_error.title"),
            tr("orthanc.connect_error.body"),
        )

    def _on_source_changed(self) -> None:
        source_val = self._source_combo.currentData()
        if self._query_service is not None and source_val:
            self._query_service.source = QuerySource(source_val)
        if source_val:
            self._persist_query_source(str(source_val))
        # Show warning if DIMSE selected but no DICOMweb for download
        if source_val == "dimse" and self._server_settings:
            if not self._server_settings.url or self._server_settings.use_mock:
                self._status_label.setText(
                    tr("orthanc.dimse_needs_wado_warning")
                )

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

    def _load_studies(self) -> None:
        text = self._search_edit.text().strip()
        patient_name = text or None
        try:
            if self._query_service is not None:
                studies = self._query_service.query_studies(patient_name=patient_name)
            else:
                studies = self._client.query_studies(patient_name=patient_name)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, tr("orthanc.find"), tr("orthanc.find_error", message=str(exc)))
            return

        studies = sorted(
            studies,
            key=lambda s: (s.study_date or "", s.patient_name or ""),
            reverse=True,
        )

        self._tree.blockSignals(True)
        self._tree.clear()
        for study in studies:
            patient_name = study.patient_name or ""
            study_date = study.study_date or ""
            desc = study.study_description or ""
            item = QTreeWidgetItem([patient_name, study_date, desc])
            item.setData(0, _STUDY_UID_ROLE, study.study_uid)
            item.setData(0, _SORT_ROLE, patient_name)
            item.setData(1, _SORT_ROLE, study_date)
            item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
            self._tree.addTopLevelItem(item)
        self._tree.blockSignals(False)
        self._update_load_button()

    def _series_label(self, series: SeriesInfo) -> str:
        parts = [series.modality, series.description]
        if series.instance_count is not None:
            parts.append(f"{series.instance_count} {tr('orthanc.instances_suffix')}")
        return " — ".join(part for part in parts if part)

    def _on_find(self) -> None:
        self._load_studies()

    def _on_item_expanded(self, item: QTreeWidgetItem) -> None:
        if item.parent() is not None:
            return
        if item.childCount() > 0:
            return

        study_uid = item.data(0, _STUDY_UID_ROLE)
        if not study_uid:
            return

        try:
            if self._query_service is not None:
                series_list = self._query_service.query_series(str(study_uid))
            else:
                series_list = self._client.query_series(str(study_uid))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, tr("orthanc.series"), tr("orthanc.series_error", message=str(exc)))
            return

        self._tree.blockSignals(True)
        for series in series_list:
            child = QTreeWidgetItem(["", "", self._series_label(series)])
            child.setData(0, _SERIES_UID_ROLE, series.series_uid)
            child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            child.setCheckState(0, Qt.CheckState.Unchecked)
            item.addChild(child)
        self._tree.blockSignals(False)

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 0 or not item.data(0, _SERIES_UID_ROLE):
            return
        self._update_load_button()

    def _update_load_button(self) -> None:
        if self._downloading:
            return
        self._load_btn.setEnabled(len(self._collect_all_checked_series()) > 0)

    def _collect_all_checked_series(self) -> list[tuple[str, list[str]]]:
        """Collect all (study_uid, series_uids) pairs across all studies."""
        result: list[tuple[str, list[str]]] = []
        for index in range(self._tree.topLevelItemCount()):
            study_item = self._tree.topLevelItem(index)
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
        all_series = self._collect_all_checked_series()
        log.info("[DLG] _on_load: checked_series=%d", len(all_series))
        if not all_series:
            return

        session_id = self._cache.create_session()
        self._session_id = session_id
        self._downloading = True
        self._close_pending = False
        self._load_btn.setEnabled(False)
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
        self._total_studies = len(all_series)
        self._start_next_download()

    def _start_next_download(self) -> None:
        log.info("[DLG] _start_next_download: pending=%d completed=%d total=%d",
                 len(self._pending_downloads), self._completed_downloads, self._total_studies)
        if not self._pending_downloads:
            all_ok = self._completed_downloads == self._total_studies
            if all_ok and self._session_id is not None:
                first_study = self._result[1] if self._result else ""
                self._on_done(self._session_id, first_study)
            elif self._session_id is not None:
                self._on_failed("", tr("orthanc.partial_failed"))
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

    def _on_cancel(self) -> None:
        if self._downloading and self._worker is not None:
            self._status_label.setText(tr("orthanc.download_cancelled"))
            self._cancel_btn.setEnabled(False)
            self._worker.cancel()
            self._force_close_timer.start(_CANCEL_FORCE_CLOSE_MS)
            return
        self.reject()

    def _force_close_if_still_downloading(self) -> None:
        if not self._downloading:
            return
        self._downloading = False
        self._worker = None
        if self._session_id is not None:
            self._cache.clear_session(self._session_id)
            self._session_id = None
        self._progress.hide()
        self._release_client()
        super().reject()

    def _short_uid(self, series_uid: str) -> str:
        return series_uid[:12] + "…" if len(series_uid) > 12 else series_uid

    def _on_progress(self, current: int, total: int, series_uid: str) -> None:
        if total > 0:
            self._progress.setRange(0, total)
            self._progress.setValue(min(current, total))
        short_uid = self._short_uid(series_uid)
        self._status_label.setText(tr("orthanc.loading_detail", current=current, total=total, uid=short_uid))

    def _on_status(self, message: str) -> None:
        self._status_label.setText(message)

    def _on_series_done(self, series_uid: str, status: str) -> None:
        if status == "failed":
            self._status_label.setText(tr("orthanc.series_error_status", uid=self._short_uid(series_uid)))

    def _on_studies_ready(self, studies: list[StudyMetadata]) -> None:
        log.info("[DLG] _on_studies_ready: %d studies", len(studies))
        for s in studies:
            total_inst = sum(len(sr.instances) for sr in s.series)
            log.info("[DLG]   study_uid=%s series=%d instances=%d",
                     s.study_uid[:16], len(s.series), total_inst)
        self._downloaded_studies.extend(studies)

    def _reset_after_download(self) -> None:
        self._downloading = False
        self._worker = None
        self._force_close_timer.stop()

    def _on_single_study_done(self, session_id: str, study_uid: str) -> None:
        log.info("[DLG] _on_single_study_done: uid=%s", study_uid[:16])
        self._completed_downloads += 1
        self._status_label.setText(
            tr("orthanc.series_done", current=self._completed_downloads, total=self._total_studies)
        )
        self._start_next_download()

    def _on_single_study_failed(self, _uid: str, message: str) -> None:
        log.warning("[DLG] _on_single_study_failed: uid=%s msg=%s", _uid[:16] if _uid else "?", message)
        self._completed_downloads += 1
        self._status_label.setText(
            tr("orthanc.series_error_status", current=self._completed_downloads, total=self._total_studies, message=message)
        )
        self._start_next_download()

    def _on_done(self, session_id: str, study_uid: str) -> None:
        log.info("[DLG] _on_done: session=%s studies_downloaded=%d",
                 session_id[:8] if session_id else "?", len(self._downloaded_studies))
        self._reset_after_download()
        self._session_id = None
        self._result = (session_id, study_uid)
        self._progress.setValue(self._progress.maximum())
        self._status_label.setText(tr("orthanc.download_complete"))
        self.accept()

    def _on_failed(self, _uid: str, message: str) -> None:
        log.warning("[DLG] _on_failed: uid=%s msg=%s", _uid[:16] if _uid else "?", message)
        self._reset_after_download()
        if self._pending_downloads and self._session_id is not None:
            self._start_next_download()
            return
        if self._session_id is not None:
            self._cache.clear_session(self._session_id)
            self._session_id = None
        self._progress.hide()
        self._tree.setEnabled(True)
        self._find_btn.setEnabled(True)
        self._cancel_btn.setText(tr("orthanc.cancel"))
        self._cancel_btn.setEnabled(True)
        self._update_load_button()
        QMessageBox.warning(self, tr("orthanc.download_error.title"), tr("orthanc.download_error.body", message=message))

    def _on_cancelled(self, _session_id: str) -> None:
        self._reset_after_download()
        self._session_id = None
        self._progress.hide()
        self._tree.setEnabled(True)
        self._find_btn.setEnabled(True)
        self._cancel_btn.setText(tr("orthanc.cancel"))
        self._cancel_btn.setEnabled(True)
        self._update_load_button()
        self._release_client()
        QTimer.singleShot(0, self.reject)
