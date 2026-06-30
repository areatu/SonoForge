"""Dialog for browsing Orthanc studies and downloading selected series."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
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
from echo_personal_tool.domain.models.orthanc import SeriesInfo, StudyInfo
from echo_personal_tool.domain.ports import DicomWebClient
from echo_personal_tool.infrastructure.orthanc_cache import OrthancSessionCache
from echo_personal_tool.infrastructure.orthanc_client import OrthancDicomWebClient
from echo_personal_tool.infrastructure.server_settings import ServerSettings, load_server_settings

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
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._cache = cache
        self._server_settings = server_settings
        self._base_url = base_url
        self._username = username
        self._password = password
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

        self.setWindowTitle("Загрузка с сервера")
        self.resize(800, 520)

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Имя пациента")
        self._find_btn = QPushButton("Найти")
        self._find_btn.clicked.connect(self._on_find)

        search_row = QHBoxLayout()
        search_row.addWidget(self._search_edit, stretch=1)
        search_row.addWidget(self._find_btn)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Пациент", "Дата", "Исследование / Серия"])
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

        self._load_btn = QPushButton("Загрузить")
        self._load_btn.setEnabled(False)
        self._load_btn.clicked.connect(self._on_load)

        self._cancel_btn = QPushButton("Отмена")
        self._cancel_btn.clicked.connect(self._on_cancel)

        buttons_row = QHBoxLayout()
        buttons_row.addStretch()
        buttons_row.addWidget(self._load_btn)
        buttons_row.addWidget(self._cancel_btn)

        layout = QVBoxLayout(self)
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
            self._status_label.setText("Сервер доступен")
            return
        self._status_label.setText("Сервер недоступен — mock или проверьте настройки")
        QMessageBox.warning(
            self,
            "Сервер",
            "Не удалось подключиться к серверу Orthanc.\n"
            "Можно продолжить с mock-данными, если включён в настройках.",
        )

    def _load_studies(self) -> None:
        text = self._search_edit.text().strip()
        patient_name = text or None
        try:
            studies = self._client.query_studies(patient_name)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Поиск", f"Ошибка запроса исследований: {exc}")
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
            parts.append(f"{series.instance_count} инст.")
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
            series_list = self._client.query_series(str(study_uid))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Серии", f"Ошибка запроса серий: {exc}")
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
        self._cancel_btn.setText("Отменить загрузку")
        self._cancel_btn.setEnabled(True)
        self._find_btn.setEnabled(False)
        self._tree.setEnabled(False)
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.show()
        self._status_label.setText("Подготовка загрузки…")

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
                self._on_failed("", "Часть исследований не загружена")
            return

        study_uid, series_uids = self._pending_downloads.pop(0)
        self._status_label.setText(
            f"Загрузка [{self._completed_downloads + 1}/{self._total_studies}]…"
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
            self._status_label.setText("Отмена загрузки…")
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
        self._status_label.setText(f"Загрузка — {current}/{total} (серия {short_uid})")

    def _on_status(self, message: str) -> None:
        self._status_label.setText(message)

    def _on_series_done(self, series_uid: str, status: str) -> None:
        if status == "failed":
            self._status_label.setText(f"Ошибка в серии {self._short_uid(series_uid)}")

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
            f"Загрузка [{self._completed_downloads}/{self._total_studies}] завершена"
        )
        self._start_next_download()

    def _on_single_study_failed(self, _uid: str, message: str) -> None:
        log.warning("[DLG] _on_single_study_failed: uid=%s msg=%s", _uid[:16] if _uid else "?", message)
        self._completed_downloads += 1
        self._status_label.setText(
            f"Ошибка [{self._completed_downloads}/{self._total_studies}]: {message}"
        )
        self._start_next_download()

    def _on_done(self, session_id: str, study_uid: str) -> None:
        log.info("[DLG] _on_done: session=%s studies_downloaded=%d",
                 session_id[:8] if session_id else "?", len(self._downloaded_studies))
        self._reset_after_download()
        self._session_id = None
        self._result = (session_id, study_uid)
        self._progress.setValue(self._progress.maximum())
        self._status_label.setText("Загрузка завершена")
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
        self._cancel_btn.setText("Отмена")
        self._cancel_btn.setEnabled(True)
        self._update_load_button()
        QMessageBox.warning(self, "Загрузка", f"Ошибка загрузки: {message}")

    def _on_cancelled(self, _session_id: str) -> None:
        self._reset_after_download()
        self._session_id = None
        self._progress.hide()
        self._tree.setEnabled(True)
        self._find_btn.setEnabled(True)
        self._cancel_btn.setText("Отмена")
        self._cancel_btn.setEnabled(True)
        self._update_load_button()
        self._release_client()
        QTimer.singleShot(0, self.reject)
