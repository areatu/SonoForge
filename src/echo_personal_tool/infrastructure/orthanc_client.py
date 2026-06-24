"""Orthanc DICOMweb client (QIDO-RS + WADO-RS over httpx)."""

from __future__ import annotations

import email
import logging
import threading
from collections.abc import Callable
from email import policy
from io import BytesIO

import httpx
import pydicom

logger = logging.getLogger(__name__)

from echo_personal_tool.domain.models.orthanc import InstanceInfo, SeriesInfo, StudyInfo
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
    ):
        self._timeout = timeout
        self._orthanc_root, self._dicom_web_root = split_orthanc_urls(base_url)
        headers = dict(http_headers or {})
        auth: tuple[str, str] | None = None
        if auth_mode == "basic" and (username or password):
            auth = (username, password)
        self._orthanc_client = httpx.Client(
            base_url=f"{self._orthanc_root}/",
            timeout=self._timeout,
        )
        self._client = httpx.Client(
            base_url=f"{self._dicom_web_root}/",
            auth=auth,
            headers=headers,
            timeout=self._timeout,
        )
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
        except Exception:  # noqa: BLE001
            logger.debug("Orthanc client close during cancel", exc_info=True)

    def ping(self) -> bool:
        try:
            r = self._orthanc_client.get("system")
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    def query_studies(self, patient_name: str | None = None) -> list[StudyInfo]:
        params: list[tuple[str, str]] = _include_params(_STUDY_INCLUDE_FIELDS)
        if patient_name:
            params.append(("PatientName", f"*{patient_name}*"))
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
        return parse_instances(r.json(), study_uid, series_uid)

    def download_instance(self, study_uid: str, series_uid: str, instance_uid: str) -> bytes:
        r = self._client.get(
            f"studies/{study_uid}/series/{series_uid}/instances/{instance_uid}",
            headers={"Accept": "multipart/related; type=application/dicom"},
        )
        if r.status_code != 200:
            logger.error(
                "WADO-RS retrieve failed: status=%d body=%s", r.status_code, r.text[:2000]
            )
        r.raise_for_status()
        return r.content

    def download_series(
        self,
        study_uid: str,
        series_uid: str,
        *,
        on_download_progress: Callable[[int, int | None], None] | None = None,
    ) -> list[tuple[str, bytes]]:
        self._check_cancelled()
        try:
            with self._client.stream(
                "GET",
                f"studies/{study_uid}/series/{series_uid}",
                headers={"Accept": "multipart/related; type=application/dicom"},
            ) as response:
                if response.status_code != 200:
                    body_preview = response.read()[:2000]
                    logger.error(
                        "WADO-RS series retrieve failed: status=%d body=%s",
                        response.status_code,
                        body_preview,
                    )
                response.raise_for_status()
                content_length = response.headers.get("content-length")
                total_bytes = int(content_length) if content_length else None
                chunks: list[bytes] = []
                received = 0
                for chunk in response.iter_bytes(chunk_size=65536):
                    self._check_cancelled()
                    chunks.append(chunk)
                    received += len(chunk)
                    if on_download_progress is not None:
                        on_download_progress(received, total_bytes)
                content = b"".join(chunks)
        except httpx.HTTPError as exc:
            if self._cancel_event.is_set():
                raise DownloadCancelled("download cancelled") from exc
            raise

        self._check_cancelled()
        raw_parts = _parse_multipart(content, response.headers.get("content-type", ""))
        result: list[tuple[str, bytes]] = []
        for data in raw_parts:
            try:
                ds = pydicom.dcmread(BytesIO(data))
                sop_uid = str(getattr(ds, "SOPInstanceUID", ""))
            except Exception:
                sop_uid = ""
            result.append((sop_uid, data))
        return result

    def close(self) -> None:
        try:
            self._client.close()
            self._orthanc_client.close()
        except Exception:  # noqa: BLE001
            logger.debug("Orthanc client close", exc_info=True)


def _parse_multipart(content: bytes, content_type: str) -> list[bytes]:
    """Parse multipart MIME body into list of part payloads."""
    msg = email.message_from_bytes(
        f"Content-Type: {content_type}\n\n".encode() + content,
        policy=policy.compat32,
    )
    if not msg.is_multipart():
        return [content]
    parts: list[bytes] = []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        data = part.get_payload(decode=True)
        if data:
            parts.append(data)
    return parts
