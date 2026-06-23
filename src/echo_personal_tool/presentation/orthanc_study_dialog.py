"""Dialog for browsing Orthanc studies and downloading selected series."""

from __future__ import annotations

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import (
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
from echo_personal_tool.domain.models.orthanc import SeriesInfo, StudyInfo
from echo_personal_tool.domain.ports.dicom_web import DicomWebClient
from echo_personal_tool.infrastructure.orthanc_cache import OrthancSessionCache

_STUDY_UID_ROLE = Qt.ItemDataRole.UserRole
_SERIES_UID_ROLE = Qt.ItemDataRole.UserRole + 1


class OrthancStudyDialog(QDialog):
    def __init__(
        self,
        client: DicomWebClient,
        cache: OrthancSessionCache,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._cache = cache
        self._result: tuple[str, str] | None = None
        self._downloading = False

        self.setWindowTitle("Загрузка с сервера")
        self.resize(640, 480)

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Имя пациента")
        self._find_btn = QPushButton("Найти")
        self._find_btn.clicked.connect(self._on_find)

        search_row = QHBoxLayout()
        search_row.addWidget(self._search_edit, stretch=1)
        search_row.addWidget(self._find_btn)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Исследование / Серия"])
        self._tree.itemExpanded.connect(self._on_item_expanded)
        self._tree.itemChanged.connect(self._on_item_changed)

        self._status_label = QLabel()
        self._progress = QProgressBar()
        self._progress.hide()

        self._load_btn = QPushButton("Загрузить")
        self._load_btn.setEnabled(False)
        self._load_btn.clicked.connect(self._on_load)

        self._cancel_btn = QPushButton("Отмена")
        self._cancel_btn.clicked.connect(self.reject)

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

        self._check_ping()
        self._load_studies()

    def result_data(self) -> tuple[str, str] | None:
        """Return (session_id, study_uid) after successful download, else None."""
        return self._result

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

        self._tree.blockSignals(True)
        self._tree.clear()
        for study in studies:
            item = QTreeWidgetItem([self._study_label(study)])
            item.setData(0, _STUDY_UID_ROLE, study.study_uid)
            item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
            self._tree.addTopLevelItem(item)
        self._tree.blockSignals(False)
        self._update_load_button()

    def _study_label(self, study: StudyInfo) -> str:
        parts = [study.patient_name, study.study_date, study.study_description]
        return " — ".join(part for part in parts if part)

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
            child = QTreeWidgetItem([self._series_label(series)])
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
        self._load_btn.setEnabled(self._collect_checked_series() is not None)

    def _collect_checked_series(self) -> tuple[str, list[str]] | None:
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
                return str(study_uid), checked
        return None

    def _on_load(self) -> None:
        selection = self._collect_checked_series()
        if selection is None:
            return
        study_uid, series_uids = selection

        session_id = self._cache.create_session()
        self._downloading = True
        self._load_btn.setEnabled(False)
        self._cancel_btn.setEnabled(False)
        self._find_btn.setEnabled(False)
        self._progress.setValue(0)
        self._progress.show()
        self._status_label.setText("Загрузка…")

        worker = OrthancDownloadWorker(
            self._client,
            self._cache,
            session_id,
            study_uid,
            series_uids,
            self,
        )
        worker.signals.progress.connect(self._on_progress)
        worker.signals.done.connect(self._on_done)
        worker.signals.failed.connect(self._on_failed)
        QThreadPool.globalInstance().start(worker)

    def _on_progress(self, series_uid: str, current: int, total: int) -> None:
        if total > 0:
            self._progress.setMaximum(total)
            self._progress.setValue(current)
        short_uid = series_uid[:12] + "…" if len(series_uid) > 12 else series_uid
        self._status_label.setText(f"Серия {short_uid} — {current}/{total}")

    def _on_done(self, session_id: str, study_uid: str) -> None:
        self._result = (session_id, study_uid)
        self.accept()

    def _on_failed(self, _uid: str, message: str) -> None:
        self._downloading = False
        self._progress.hide()
        self._find_btn.setEnabled(True)
        self._cancel_btn.setEnabled(True)
        self._update_load_button()
        QMessageBox.warning(self, "Загрузка", f"Ошибка загрузки: {message}")
