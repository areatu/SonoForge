"""Background Orthanc series downloader."""

from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from echo_personal_tool.domain.ports.dicom_web import DicomWebClient
from echo_personal_tool.infrastructure.orthanc_cache import OrthancSessionCache


class OrthancDownloadSignals(QObject):
    progress = Signal(str, int, int)  # series_uid, current_instance, total_instances
    series_done = Signal(str, str)  # series_uid, status "ok"|"failed"
    done = Signal(str, str)  # session_id, study_uid
    failed = Signal(str, str)  # study_uid or series_uid, message


class OrthancDownloadWorker(QRunnable):
    """Download study series from Orthanc into session cache."""

    def __init__(
        self,
        client: DicomWebClient,
        cache: OrthancSessionCache,
        session_id: str,
        study_uid: str,
        series_uids: list[str],
        parent: QObject | None = None,
    ) -> None:
        super().__init__()
        self._client = client
        self._cache = cache
        self._session_id = session_id
        self._study_uid = study_uid
        self._series_uids = series_uids
        self.signals = OrthancDownloadSignals(parent)
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        try:
            all_ok = True
            for series_uid in self._series_uids:
                if not self._download_series(series_uid):
                    all_ok = False
            if all_ok:
                self.signals.done.emit(self._session_id, self._study_uid)
        except Exception as exc:  # noqa: BLE001
            self.signals.failed.emit(self._study_uid, str(exc))

    def _download_series(self, series_uid: str) -> bool:
        instances = self._client.query_instances(self._study_uid, series_uid)
        total = len(instances)
        series_failed = False
        for index, instance in enumerate(instances, start=1):
            data = self._download_instance(series_uid, instance.sop_instance_uid)
            if data is None:
                series_failed = True
            else:
                self._cache.save_instance(
                    self._session_id,
                    self._study_uid,
                    series_uid,
                    instance.sop_instance_uid,
                    data,
                )
            self.signals.progress.emit(series_uid, index, total)
        status = "failed" if series_failed else "ok"
        self.signals.series_done.emit(series_uid, status)
        return not series_failed

    def _download_instance(self, series_uid: str, instance_uid: str) -> bytes | None:
        for attempt in range(2):
            try:
                return self._client.download_instance(
                    self._study_uid, series_uid, instance_uid
                )
            except Exception:
                if attempt == 1:
                    return None
        return None
