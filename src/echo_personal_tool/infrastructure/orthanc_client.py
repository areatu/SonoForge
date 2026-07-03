"""Orthanc DICOMweb client (QIDO-RS + WADO-RS + STOW-RS over httpx)."""

from __future__ import annotations

import logging
import threading
import uuid

import httpx

logger = logging.getLogger(__name__)

from echo_personal_tool.domain.models.orthanc import (
    InstanceInfo,
    SeriesInfo,
    StowResult,
    StudyInfo,
)
from echo_personal_tool.infrastructure.orthanc_dicom_json import (
    parse_instances,
    parse_series,
    parse_studies,
)
from echo_personal_tool.infrastructure.server_settings import (
    ServerSettings,
    parse_http_headers,
    split_orthanc_urls,
)

_STUDY_INCLUDE_FIELDS = (
    "0020000D",  # StudyInstanceUID
    "00100010",  # PatientName
    "00100020",  # PatientID
    "00080020",  # StudyDate
    "00081030",  # StudyDescription
)

_SERIES_INCLUDE_FIELDS = (
    "0020000E",  # SeriesInstanceUID
    "00080060",  # Modality
    "0008103E",  # SeriesDescription
    "00201209",  # NumberOfSeriesRelatedInstances
)

_INSTANCE_INCLUDE_FIELDS = (
    "00080018",  # SOPInstanceUID
)


def _include_params(tags: tuple[str, ...]) -> list[tuple[str, str]]:
    return [("includefield", tag) for tag in tags]


class DownloadCancelled(Exception):
    """Raised when an in-flight WADO-RS download is aborted."""


class OrthancDicomWebClient:
    def __init__(
        self,
        base_url: str,
        username: str = "",
        password: str = "",
        *,
        auth_mode: str = "basic",
        http_headers: dict[str, str] | None = None,
        timeout: float = 30.0,
        stow_dicom_web_url: str = "",
    ):
        self._timeout = timeout
        self._orthanc_root, self._dicom_web_root = split_orthanc_urls(base_url)
        headers = dict(http_headers or {})
        auth: tuple[str, str] | None = None
        has_auth_header = any(k.lower() == "authorization" for k in headers)
        if auth_mode == "basic" and (username or password) and not has_auth_header:
            auth = (username, password)
        self._orthanc_client = httpx.Client(
            base_url=f"{self._orthanc_root}/",
            auth=auth,
            headers=headers,
            timeout=self._timeout,
        )
        self._client = httpx.Client(
            base_url=f"{self._dicom_web_root}/",
            auth=auth,
            headers=headers,
            timeout=self._timeout,
        )
        stow_root = stow_dicom_web_url.strip()
        if stow_root:
            _, stow_web = split_orthanc_urls(stow_root)
            self._stow_client: httpx.Client | None = httpx.Client(
                base_url=f"{stow_web}/",
                auth=auth,
                headers=headers,
                timeout=self._timeout,
            )
        else:
            self._stow_client = None
        self._cancel_event = threading.Event()

    @classmethod
    def from_settings(cls, settings: ServerSettings, *, timeout: float = 30.0) -> OrthancDicomWebClient:
        return cls(
            settings.url,
            settings.username,
            settings.password,
            auth_mode=settings.auth_mode,
            http_headers=parse_http_headers(settings.http_headers),
            timeout=timeout,
            stow_dicom_web_url=settings.stow_dicom_web_url,
        )

    def _build_client(self) -> httpx.Client:
        return self._client

    def _check_cancelled(self) -> None:
        if self._cancel_event.is_set():
            raise DownloadCancelled("download cancelled")

    def cancel_inflight(self) -> None:
        self._cancel_event.set()
        try:
            self._client.close()
            self._orthanc_client.close()
            if self._stow_client is not None:
                self._stow_client.close()
        except Exception:  # noqa: BLE001
            logger.debug("Orthanc client close during cancel", exc_info=True)

    def ping(self) -> bool:
        try:
            r = self._orthanc_client.get("system")
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    def query_studies(
        self,
        *,
        patient_name: str | None = None,
        patient_id: str | None = None,
        study_date: str | None = None,
    ) -> list[StudyInfo]:
        params: list[tuple[str, str]] = _include_params(_STUDY_INCLUDE_FIELDS)
        if patient_name:
            params.append(("PatientName", f"*{patient_name}*"))
        if patient_id:
            params.append(("PatientID", f"*{patient_id}*"))
        if study_date:
            params.append(("StudyDate", study_date))
        r = self._client.get(
            "studies",
            params=params,
            headers={"Accept": "application/dicom+json"},
        )
        r.raise_for_status()
        return parse_studies(r.json())

    def query_series(self, study_uid: str) -> list[SeriesInfo]:
        r = self._client.get(
            f"studies/{study_uid}/series",
            params=_include_params(_SERIES_INCLUDE_FIELDS),
            headers={"Accept": "application/dicom+json"},
        )
        r.raise_for_status()
        return parse_series(r.json(), study_uid)

    def query_instances(self, study_uid: str, series_uid: str) -> list[InstanceInfo]:
        r = self._client.get(
            f"studies/{study_uid}/series/{series_uid}/instances",
            params=_include_params(_INSTANCE_INCLUDE_FIELDS),
            headers={"Accept": "application/dicom+json"},
        )
        r.raise_for_status()
        raw = r.json()
        instances = parse_instances(raw, study_uid, series_uid)
        logger.info(
            "[DIAG] query_instances series=%s server_returned=%d parsed=%d status=%d",
            series_uid[:16],
            len(raw) if isinstance(raw, list) else "?",
            len(instances),
            r.status_code,
        )
        return instances

    def download_instance(self, study_uid: str, series_uid: str, instance_uid: str) -> bytes:
        """Download single DICOM instance via Orthanc REST API.

        Orthanc /instances/{id}/file expects its internal UUID, not DICOM UID.
        We resolve via /tools/lookup first.
        """
        self._check_cancelled()
        try:
            lookup = self._orthanc_client.post(
                "tools/lookup",
                content=instance_uid.encode(),
                headers={"Content-Type": "text/plain"},
            )
            lookup.raise_for_status()
            results = lookup.json()
            if isinstance(results, list) and results:
                orthanc_id = results[0]["ID"]
            else:
                orthanc_id = str(results)
            r = self._orthanc_client.get(f"instances/{orthanc_id}/file")
            r.raise_for_status()
            return r.content
        except httpx.HTTPError as exc:
            if self._cancel_event.is_set():
                raise DownloadCancelled("download cancelled") from exc
            raise

    def close(self) -> None:
        try:
            self._client.close()
            self._orthanc_client.close()
            if self._stow_client is not None:
                self._stow_client.close()
        except Exception:  # noqa: BLE001
            logger.debug("Orthanc client close", exc_info=True)

    def _stow_http_client(self) -> httpx.Client:
        return self._stow_client if self._stow_client is not None else self._client

    def stow_instances(self, dicom_files: list[bytes]) -> StowResult:
        """STOW-RS: upload DICOM objects via POST /studies, batched to avoid timeouts."""
        if not dicom_files:
            return StowResult(0)

        batch_size = 10
        total_success = 0
        all_failed_uids: list[str] = []
        last_error = ""

        for start in range(0, len(dicom_files), batch_size):
            batch = dicom_files[start : start + batch_size]
            boundary = uuid.uuid4().hex
            body = _build_stow_multipart_body(boundary, batch)
            try:
                r = self._stow_http_client().post(
                    "studies",
                    content=body,
                    headers={
                        "Content-Type": f"multipart/related; type=application/dicom; boundary={boundary}",
                    },
                    timeout=120.0,
                )
                if r.status_code not in (200, 201):
                    last_error = f"HTTP {r.status_code}"
                    continue
                partial = _parse_stow_response(r.json(), len(batch))
                total_success += partial.success_count
                all_failed_uids.extend(partial.failed_uids)
            except httpx.HTTPError as exc:
                last_error = str(exc)

        if total_success == 0 and not all_failed_uids and last_error:
            return StowResult(0, [], last_error)
        return StowResult(
            success_count=total_success,
            failed_uids=all_failed_uids,
        )


def _build_stow_multipart_body(boundary: str, dicom_files: list[bytes]) -> bytes:
    """Build multipart/related body for STOW-RS per DICOMweb Part 18."""
    parts: list[bytes] = []
    for f in dicom_files:
        parts.append(
            f"--{boundary}\r\n"
            f"Content-Type: application/dicom\r\n"
            f"\r\n".encode()
            + f
            + b"\r\n"
        )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts)


def _parse_stow_response(data: object, expected_count: int) -> StowResult:
    """Parse Orthanc STOW-RS JSON response to extract success/failure counts."""
    if not isinstance(data, list):
        return StowResult(expected_count)
    failed_uids: list[str] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        # Orthanc returns {00081199: [{00081150: ..., 00081155: ...}]} for failures
        failed_seq = item.get("00081199")
        if isinstance(failed_seq, list):
            for entry in failed_seq:
                if isinstance(entry, dict):
                    uid_item = entry.get("00081155")
                    if isinstance(uid_item, dict):
                        uid = uid_item.get("Value", [""])[0] if "Value" in uid_item else ""
                        if uid:
                            failed_uids.append(str(uid))
    success = expected_count - len(failed_uids)
    return StowResult(success_count=success, failed_uids=failed_uids)
