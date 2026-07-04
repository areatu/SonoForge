"""Background Orthanc instance downloader with parallel downloads."""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from threading import Lock

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

logger = logging.getLogger(__name__)

from echo_personal_tool.application.services.dicom_retrieve_service import (
    DicomRetrieveService,
)
from echo_personal_tool.domain.models import InstanceMetadata, SeriesMetadata, StudyMetadata
from echo_personal_tool.domain.ports import DicomWebClient
from echo_personal_tool.infrastructure.dicom_metadata_mapper import (
    map_instance_metadata,
    parse_study_datetime,
)
from echo_personal_tool.infrastructure.orthanc_cache import OrthancSessionCache
from echo_personal_tool.infrastructure.orthanc_client import (
    DownloadCancelled,
    OrthancDicomWebClient,
)
from echo_personal_tool.infrastructure.server_settings import ServerSettings

_MAX_CONCURRENT_DOWNLOADS = 4


class OrthancDownloadSignals(QObject):
    progress = Signal(int, int, str)  # overall_current, overall_total, series_uid
    status = Signal(str)
    series_done = Signal(str, str)  # series_uid, status "ok"|"failed"|"cancelled"
    done = Signal(str, str)  # session_id, study_uid
    failed = Signal(str, str)  # study_uid or series_uid, message
    cancelled = Signal(str)  # session_id
    studies_ready = Signal(list)  # list[StudyMetadata]


class OrthancDownloadWorker(QRunnable):
    """Download DICOM instances from Orthanc with parallel per-instance WADO-RS.

    Downloads each instance individually (not series-level multipart),
    using a thread pool for parallelism. This is more reliable than
    series-level multipart which can lose data on large responses.
    """

    def __init__(
        self,
        client: DicomWebClient,
        cache: OrthancSessionCache,
        session_id: str,
        study_uid: str,
        series_uids: list[str],
        parent: QObject | None = None,
        *,
        server_settings: ServerSettings | None = None,
        base_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        retrieve_service: DicomRetrieveService | None = None,
    ) -> None:
        super().__init__()
        self._client = client
        self._cache = cache
        self._session_id = session_id
        self._study_uid = study_uid
        self._series_uids = series_uids
        self._server_settings = server_settings
        self._base_url = base_url
        self._username = username
        self._password = password
        self._retrieve_service = retrieve_service
        self._cancelled = False
        self._thread_client: OrthancDicomWebClient | None = None
        self._lock = Lock()
        self.signals = OrthancDownloadSignals(parent)
        self.setAutoDelete(True)

    def cancel(self) -> None:
        self._cancelled = True
        thread_client = self._thread_client
        if thread_client is not None:
            thread_client.cancel_inflight()

    @Slot()
    def run(self) -> None:
        _client: DicomWebClient = self._client
        if self._server_settings is not None or self._base_url:
            _client = self._make_thread_client()

        logger.info(
            "[DIAG] worker run study=%s series_uids=%s client_type=%s",
            self._study_uid[:16],
            [s[:16] for s in self._series_uids],
            type(_client).__name__,
        )

        try:
            if self._retrieve_service is not None:
                self._retrieve_service.set_cancel_check(lambda: self._cancelled)

            t_start = time.monotonic()
            all_instances: list[tuple[str, str]] = []

            for series_uid in self._series_uids:
                if self._cancelled:
                    self._finish_cancelled()
                    return
                from echo_personal_tool.infrastructure.i18n import tr
                self.signals.status.emit(tr("orthanc.querying_instances", uid=series_uid[:12]))
                t_q = time.monotonic()
                instances = _client.query_instances(self._study_uid, series_uid)
                logger.info(
                    "[DIAG] worker query series=%s found=%d elapsed_s=%.2f",
                    series_uid[:16],
                    len(instances),
                    time.monotonic() - t_q,
                )
                for inst in instances:
                    all_instances.append((series_uid, inst.sop_instance_uid))

            total = len(all_instances)
            if total == 0:
                self.signals.studies_ready.emit([])
                self.signals.done.emit(self._session_id, self._study_uid)
                return

            if (
                self._retrieve_service is not None
                and self._retrieve_service.default_source == "cmove"
            ):
                for series_uid in self._series_uids:
                    if self._cancelled:
                        self._finish_cancelled()
                        return
                    self.signals.status.emit(
                        f"C-MOVE prefetch series {series_uid[:12]}…"
                    )
                    try:
                        self._retrieve_service.prefetch_series(
                            self._study_uid, series_uid
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "C-MOVE series prefetch failed series=%s: %s",
                            series_uid[:16],
                            exc,
                        )

            logger.info(
                "[DIAG] worker start download study=%s total_instances=%d concurrency=%d",
                self._study_uid[:16],
                total,
                _MAX_CONCURRENT_DOWNLOADS,
            )

            self.signals.progress.emit(0, total, self._series_uids[0])
            from echo_personal_tool.infrastructure.i18n import tr
            self.signals.status.emit(tr("orthanc.downloading_count", count=total))

            saved_count = 0
            failed_count = 0
            errors: list[str] = []

            with ThreadPoolExecutor(max_workers=_MAX_CONCURRENT_DOWNLOADS) as pool:
                futures = {}
                for series_uid, instance_uid in all_instances:
                    if self._cancelled:
                        pool.shutdown(wait=False, cancel_futures=True)
                        self._finish_cancelled()
                        return
                    future = pool.submit(
                        self._download_one,
                        self._study_uid,
                        series_uid,
                        instance_uid,
                    )
                    futures[future] = (series_uid, instance_uid)

                for future in as_completed(futures):
                    if self._cancelled:
                        pool.shutdown(wait=False, cancel_futures=True)
                        self._finish_cancelled()
                        return

                    series_uid, instance_uid = futures[future]
                    try:
                        result = future.result()
                        if result is not None:
                            with self._lock:
                                saved_count += 1
                        else:
                            with self._lock:
                                failed_count += 1
                                errors.append(f"instance {instance_uid[:16]}: empty data")
                    except DownloadCancelled:
                        pool.shutdown(wait=False, cancel_futures=True)
                        self._finish_cancelled()
                        return
                    except Exception as exc:
                        with self._lock:
                            failed_count += 1
                            errors.append(f"instance {instance_uid[:16]}: {exc}")

                    with self._lock:
                        done = saved_count + failed_count
                    self.signals.progress.emit(done, total, series_uid)
                    self.signals.status.emit(f"Загружено {done}/{total}")

            elapsed_total = time.monotonic() - t_start
            logger.info(
                "[DIAG] worker finished study=%s saved=%d failed=%d elapsed_s=%.1f",
                self._study_uid[:16],
                saved_count,
                failed_count,
                elapsed_total,
            )

            if failed_count == 0:
                self.signals.progress.emit(total, total, self._series_uids[-1])
                self.signals.studies_ready.emit(self._build_studies_metadata())
                self.signals.done.emit(self._session_id, self._study_uid)
            else:
                detail = "; ".join(errors[:5]) if errors else ""
                message = f"Загружено {saved_count}/{total}"
                if detail:
                    message += f". Ошибки: {detail}"
                if saved_count > 0:
                    self.signals.studies_ready.emit(self._build_studies_metadata())
                    self.signals.done.emit(self._session_id, self._study_uid)
                else:
                    self.signals.failed.emit(self._study_uid, message)

        except DownloadCancelled:
            self._finish_cancelled()
        except Exception as exc:  # noqa: BLE001
            if self._cancelled:
                self._finish_cancelled()
                return
            self.signals.failed.emit(self._study_uid, str(exc))
        finally:
            if self._thread_client is not None:
                self._thread_client.close()
                self._thread_client = None

    def _make_thread_client(self) -> OrthancDicomWebClient:
        if self._server_settings is not None:
            return OrthancDicomWebClient.from_settings(
                self._server_settings, timeout=300.0
            )
        return OrthancDicomWebClient(
            self._base_url or "",
            self._username or "",
            self._password or "",
            timeout=300.0,
        )

    def _download_one(
        self,
        study_uid: str,
        series_uid: str,
        instance_uid: str,
    ) -> bytes | None:
        """Download single instance. Returns bytes or None on failure."""
        if self._cancelled:
            return None

        # Use retrieve service if available (supports DIMSE/C-GET/C-MOVE)
        if self._retrieve_service is not None:
            try:
                data = self._retrieve_service.retrieve_instance(
                    study_uid, series_uid, instance_uid
                )
                if not data:
                    return None
                self._cache.save_instance(
                    self._session_id,
                    study_uid,
                    series_uid,
                    instance_uid,
                    data,
                )
                return data
            except DownloadCancelled:
                raise
            except Exception as exc:
                logger.warning(
                    "[DIAG] download failed instance=%s error=%s",
                    instance_uid[:16],
                    exc,
                )
                return None

        # Fallback to legacy client
        if self._server_settings is not None or self._base_url:
            client = self._make_thread_client()
        else:
            client = self._client
        try:
            data = client.download_instance(study_uid, series_uid, instance_uid)
            if not data:
                return None
            self._cache.save_instance(
                self._session_id,
                study_uid,
                series_uid,
                instance_uid,
                data,
            )
            return data
        except DownloadCancelled:
            raise
        except Exception as exc:
            logger.warning(
                "[DIAG] download failed instance=%s error=%s",
                instance_uid[:16],
                exc,
            )
            return None
        finally:
            if self._server_settings is not None or self._base_url:
                client.close()

    def _finish_cancelled(self) -> None:
        self._cache.clear_session(self._session_id)
        self.signals.cancelled.emit(self._session_id)

    def _build_studies_metadata(self) -> list[StudyMetadata]:
        """Parse DICOM headers from saved files to build StudyMetadata."""
        import pydicom

        study_dir = self._cache.study_path(self._session_id, self._study_uid)
        if not study_dir.is_dir():
            return []

        instances_by_series: dict[str, list[InstanceMetadata]] = defaultdict(list)
        study_datetime: datetime | None = None

        for series_dir in sorted(study_dir.iterdir()):
            if not series_dir.is_dir():
                continue
            for dcm_path in sorted(series_dir.glob("*.dcm")):
                try:
                    ds = pydicom.dcmread(str(dcm_path), stop_before_pixels=True, force=True)
                except Exception:
                    logger.warning("Failed to parse DICOM header: %s", dcm_path)
                    continue
                instance = map_instance_metadata(ds, path=dcm_path)
                instances_by_series[instance.series_uid].append(instance)
                if study_datetime is None:
                    try:
                        study_datetime = parse_study_datetime(ds)
                    except Exception:
                        pass

        if not instances_by_series:
            return []

        if study_datetime is None:
            study_datetime = datetime.fromtimestamp(study_dir.stat().st_mtime)

        series_list: list[SeriesMetadata] = []
        for series_uid, instances in instances_by_series.items():
            instances_sorted = tuple(sorted(instances, key=lambda i: i.sop_instance_uid))
            first = instances_sorted[0]
            series_list.append(
                SeriesMetadata(
                    series_uid=series_uid,
                    study_uid=self._study_uid,
                    modality=first.modality,
                    description=first.series_description,
                    instances=instances_sorted,
                )
            )
        series_list.sort(key=lambda s: (s.modality, s.description))

        return [
            StudyMetadata(
                study_uid=self._study_uid,
                study_datetime=study_datetime,
                series=tuple(series_list),
            )
        ]
