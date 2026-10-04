"""Orthanc DICOMweb client (QIDO-RS + WADO-RS + STOW-RS over httpx)."""

from __future__ import annotations

import logging
import threading
import time
import uuid

import httpx

logger = logging.getLogger(__name__)

_RETRYABLE_ERRORS = (
    httpx.TimeoutException,
    httpx.RemoteProtocolError,
    httpx.ConnectError,
    httpx.NetworkError,
)


def _interruptible_sleep(seconds: float, cancel_event: threading.Event) -> None:
    """Sleep in small increments so cancellation is responsive."""
    end = time.monotonic() + seconds
    while not cancel_event.is_set() and time.monotonic() < end:
        time.sleep(min(0.2, max(0, end - time.monotonic())))


# Retry settings for QIDO-RS query operations
_QUERY_RETRIES = 3
_QUERY_RETRY_DELAY = 0.5  # linear backoff: 0.5s, 1.0s

from echo_personal_tool.domain.models.orthanc import (
    InstanceInfo,
    SeriesInfo,
    StowResult,
    StudyInfo,
    StudyStatistics,
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

# Minimal set that every QIDO-RS implementation must be able to answer.  Used
# as a fallback when a server rejects the extended field list (some PACS return
# HTTP 400 for unknown includefield values instead of ignoring them).
_STUDY_BASE_FIELDS = (
    "0020000D",  # StudyInstanceUID
    "00100010",  # PatientName
    "00100020",  # PatientID
    "00080020",  # StudyDate
    "00081030",  # StudyDescription
)

# Extended set: gives the load dialog the patient context (age/sex), the study
# counts and the accession number without a second round trip.  Servers that do
# not store a tag simply leave it empty in the answer.
_STUDY_INCLUDE_FIELDS = _STUDY_BASE_FIELDS + (
    "00080030",  # StudyTime
    "00080050",  # AccessionNumber
    "00080061",  # ModalitiesInStudy
    "00080080",  # InstitutionName
    "00100030",  # PatientBirthDate
    "00100040",  # PatientSex
    "00201206",  # NumberOfStudyRelatedSeries
    "00201208",  # NumberOfStudyRelatedInstances
)

_SERIES_INCLUDE_FIELDS = (
    "0020000E",  # SeriesInstanceUID
    "00080060",  # Modality
    "0008103E",  # SeriesDescription
    "00201209",  # NumberOfSeriesRelatedInstances
    "00200011",  # SeriesNumber
    "00180015",  # BodyPartExamined
)

_INSTANCE_INCLUDE_FIELDS = (
    "00080018",  # SOPInstanceUID
)


def _include_params(tags: tuple[str, ...]) -> list[tuple[str, str]]:
    return [("includefield", tag) for tag in tags]


def _as_int_or_none(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _as_float_or_none(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _extract_image_payload(response: httpx.Response) -> bytes:
    """Return raw image bytes from a WADO-RS rendered/thumbnail response.

    DICOM PS3.18 allows both a plain image body and a ``multipart/related``
    wrapper with a single part; Orthanc uses the former for instances but other
    servers may use the latter, so both are unwrapped here.
    """
    content_type = response.headers.get("Content-Type", "")
    content = response.content
    if not content_type.lower().startswith("multipart/related"):
        return content
    boundary = ""
    for chunk in content_type.split(";"):
        chunk = chunk.strip()
        if chunk.lower().startswith("boundary="):
            boundary = chunk.split("=", 1)[1].strip().strip('"')
            break
    if not boundary:
        return b""
    marker = f"--{boundary}".encode()
    parts = content.split(marker)
    for part in parts[1:]:
        if part.startswith(b"--"):
            break
        _, _, body = part.partition(b"\r\n\r\n")
        if body:
            return body.rstrip(b"\r\n")
    return b""


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
        timeout: float = 10.0,
        stow_dicom_web_url: str = "",
        tls_verify: bool = True,
        tls_ca_path: str = "",
    ):
        self._timeout = timeout
        self._orthanc_root, self._dicom_web_root = split_orthanc_urls(base_url)
        # A CA bundle keeps verification *on* (self-signed PACS certificates);
        # ``tls_verify=False`` is the blunt fallback and is logged loudly.
        ca_bundle = tls_ca_path.strip()
        verify: bool | str = ca_bundle or tls_verify
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
            verify=verify,
        )
        self._client = httpx.Client(
            base_url=f"{self._dicom_web_root}/",
            auth=auth,
            headers=headers,
            timeout=self._timeout,
            verify=verify,
        )
        if not ca_bundle and not tls_verify:
            # Deliberate opt-out for servers with self-signed certificates, but
            # it must never happen silently (see the CodeQL
            # py/request-without-cert-validation alerts).
            logger.warning(
                "TLS certificate verification is DISABLED for %s — the connection can be intercepted; "
                "set a CA bundle in the server settings instead",
                self._orthanc_root,
            )
        stow_root = stow_dicom_web_url.strip()
        if stow_root:
            _, stow_web = split_orthanc_urls(stow_root)
            self._stow_client: httpx.Client | None = httpx.Client(
                base_url=f"{stow_web}/",
                auth=auth,
                headers=headers,
                timeout=self._timeout,
                verify=verify,
            )
        else:
            self._stow_client = None
        self._cancel_event = threading.Event()
        #: First instance UID per (study, series): the preview path asks for it
        #: once per series instead of once per attempt (e.g. the middle-frame
        #: retry).  Instance UIDs of a series never change, so this is safe for
        #: the lifetime of the client.
        self._first_instance_uids: dict[tuple[str, str], str] = {}

    @classmethod
    def from_settings(cls, settings: ServerSettings, *, timeout: float | None = None) -> OrthancDicomWebClient:
        return cls(
            settings.url,
            settings.username,
            settings.password,
            auth_mode=settings.auth_mode,
            http_headers=parse_http_headers(settings.http_headers),
            timeout=timeout if timeout is not None else settings.network_timeout,
            stow_dicom_web_url=settings.stow_dicom_web_url,
            tls_verify=settings.tls_verify,
            tls_ca_path=settings.tls_ca_path,
        )

    def _build_client(self) -> httpx.Client:
        return self._client

    def _get_with_retry(
        self,
        url: str,
        *,
        params: list[tuple[str, str]] | None = None,
        headers: dict[str, str] | None = None,
        attempts: int = _QUERY_RETRIES,
        delay: float = _QUERY_RETRY_DELAY,
    ) -> httpx.Response:
        """GET with retry on transient errors (timeouts, connection resets, 5xx)."""
        last_exc: Exception | None = None
        for attempt in range(attempts):
            try:
                r = self._client.get(url, params=params, headers=headers)
                if r.status_code < 500 or attempt >= attempts - 1:
                    return r
                last_exc = httpx.HTTPStatusError(
                    f"Server error {r.status_code} for {url}",
                    response=r,
                    request=r.request,
                )
            except _RETRYABLE_ERRORS as exc:
                last_exc = exc
            if attempt < attempts - 1:
                wait = delay * (attempt + 1)
                logger.debug(
                    "Retrying GET %s (attempt %d/%d) after %.1fs: %s",
                    url,
                    attempt + 2,
                    attempts,
                    wait,
                    last_exc,
                )
                _interruptible_sleep(wait, self._cancel_event)
        if last_exc is not None:
            raise last_exc

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
        filters: list[tuple[str, str]] = []
        if patient_name:
            filters.append(("PatientName", f"*{patient_name}*"))
        if patient_id:
            filters.append(("PatientID", f"*{patient_id}*"))
        if study_date:
            filters.append(("StudyDate", study_date))

        r = self._get_with_retry(
            "studies",
            params=_include_params(_STUDY_INCLUDE_FIELDS) + filters,
            headers={"Accept": "application/dicom+json"},
        )
        if r.status_code == 400:
            # Strict server: repeat the query with the mandatory fields only so
            # the study list still loads (without the optional patient context).
            logger.info("QIDO-RS rejected the extended study fields, retrying with the minimal set")
            r = self._get_with_retry(
                "studies",
                params=_include_params(_STUDY_BASE_FIELDS) + filters,
                headers={"Accept": "application/dicom+json"},
            )
        r.raise_for_status()
        return parse_studies(r.json())

    def query_series(self, study_uid: str) -> list[SeriesInfo]:
        r = self._get_with_retry(
            f"studies/{study_uid}/series",
            params=_include_params(_SERIES_INCLUDE_FIELDS),
            headers={"Accept": "application/dicom+json"},
        )
        r.raise_for_status()
        return parse_series(r.json(), study_uid)

    def query_instances(self, study_uid: str, series_uid: str) -> list[InstanceInfo]:
        r = self._get_with_retry(
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

    # ── Preview thumbnails (study/series browser) ───────────────────

    def fetch_preview(
        self,
        study_uid: str,
        series_uid: str,
        instance_uid: str = "",
        *,
        width: int = 0,
        height: int = 0,
        middle_frame: bool = False,
    ) -> bytes:
        """Return a rendered JPEG/PNG preview for a series (never raises).

        Tries, in order:

        1. WADO-RS ``thumbnail`` for a known instance (cheapest, Orthanc ≥ 1.12);
        2. WADO-RS ``rendered`` for a known instance;
        3. one QIDO-RS instance lookup to learn the first instance UID, then (1)/(2);
        4. the Orthanc REST ``/instances/{id}/preview`` route (works when the
           DICOMweb plugin has rendering disabled).

        With ``middle_frame=True`` (used when the first frame came back blank)
        the frame count of the instance is looked up once and the middle frame
        is requested instead (``/frames/{n}/preview``, WADO-RS
        ``/frames/{n}/rendered``), falling back to the routes above.

        An empty ``bytes`` means "no preview available" — the caller shows a
        placeholder instead of an error, because a missing thumbnail must never
        degrade the study list itself.
        """
        viewport = f"{width},{height}" if width and height else ""
        if not instance_uid:
            instance_uid = self._first_instance_uid(study_uid, series_uid)
        orthanc_id = ""
        if middle_frame and instance_uid:
            orthanc_id = self._orthanc_instance_id(instance_uid)
            frame = self._middle_frame_number(orthanc_id)
            if frame:
                payload = self._fetch_middle_frame(study_uid, series_uid, instance_uid, orthanc_id, frame, viewport)
                if payload:
                    return payload
        if instance_uid:
            base = f"studies/{study_uid}/series/{series_uid}/instances/{instance_uid}"
            for route in ("thumbnail", "rendered"):
                params = [("viewport", viewport)] if viewport else None
                try:
                    r = self._client.get(f"{base}/{route}", params=params, headers={"Accept": "image/jpeg"})
                    if r.status_code == 200 and r.content:
                        return _extract_image_payload(r)
                except httpx.HTTPError as exc:
                    logger.debug("Preview %s failed for %s: %s", route, series_uid[:16], exc)
        return self._orthanc_preview_fallback(series_uid, instance_uid)

    def _orthanc_instance_id(self, instance_uid: str) -> str:
        """Orthanc's own resource id for an instance (empty when unknown)."""
        try:
            lookup = self._orthanc_client.post(
                "tools/lookup",
                content=instance_uid.encode(),
                headers={"Content-Type": "text/plain"},
            )
            if lookup.status_code != 200:
                return ""
            results = lookup.json()
            entries = results if isinstance(results, list) else [results]
            for entry in entries:
                if isinstance(entry, dict) and entry.get("Type") == "Instance":
                    return str(entry.get("ID") or "")
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            logger.debug("Instance lookup for middle frame failed: %s", exc)
        return ""

    def _middle_frame_number(self, orthanc_id: str) -> int:
        """Middle frame index of a multiframe instance (0 for single frames).

        ``NumberOfFrames`` comes from the instance's simplified tags: one small
        request, and only on the rare blank-thumbnail path.
        """
        if not orthanc_id:
            return 0
        try:
            r = self._orthanc_client.get(f"instances/{orthanc_id}/simplified-tags")
            if r.status_code != 200:
                return 0
            tags = r.json()
            frames = int(str(tags.get("NumberOfFrames") or "1"))
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            logger.debug("NumberOfFrames lookup failed for %s: %s", orthanc_id[:8], exc)
            return 0
        return frames // 2 if frames > 1 else 0

    def _fetch_middle_frame(
        self,
        study_uid: str,
        series_uid: str,
        instance_uid: str,
        orthanc_id: str,
        frame: int,
        viewport: str,
    ) -> bytes:
        """Image of one frame: Orthanc REST first, then WADO-RS ``rendered``."""
        try:
            r = self._orthanc_client.get(f"instances/{orthanc_id}/frames/{frame}/preview")
            if r.status_code == 200 and r.content:
                return r.content
        except httpx.HTTPError as exc:
            logger.debug("Orthanc frame preview failed for %s: %s", series_uid[:16], exc)
        params = [("viewport", viewport)] if viewport else None
        try:
            r = self._client.get(
                f"studies/{study_uid}/series/{series_uid}/instances/{instance_uid}/frames/{frame}/rendered",
                params=params,
                headers={"Accept": "image/jpeg"},
            )
            if r.status_code == 200 and r.content:
                return _extract_image_payload(r)
        except httpx.HTTPError as exc:
            logger.debug("WADO-RS frame render failed for %s: %s", series_uid[:16], exc)
        return b""

    def _first_instance_uid(self, study_uid: str, series_uid: str) -> str:
        """One QIDO-RS call for a single instance UID (empty string on failure)."""
        key = (study_uid, series_uid)
        cached = self._first_instance_uids.get(key)
        if cached:
            return cached
        try:
            r = self._client.get(
                f"studies/{study_uid}/series/{series_uid}/instances",
                params=[("limit", "1"), ("includefield", "00080018")],
                headers={"Accept": "application/dicom+json"},
            )
            if r.status_code == 400:
                r = self._client.get(
                    f"studies/{study_uid}/series/{series_uid}/instances",
                    params=[("includefield", "00080018")],
                    headers={"Accept": "application/dicom+json"},
                )
            if r.status_code != 200:
                return ""
            payload = r.json()
            if isinstance(payload, list) and payload:
                instance_uid = str(payload[0].get("00080018", {}).get("Value", [""])[0] or "")
                if instance_uid:
                    self._first_instance_uids[key] = instance_uid
                return instance_uid
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            logger.debug("Instance lookup for preview failed (%s): %s", series_uid[:16], exc)
        return ""

    def _orthanc_preview_fallback(self, series_uid: str, instance_uid: str) -> bytes:
        """Orthanc REST ``/preview`` for a series or instance (empty on failure)."""
        for uid in (instance_uid, series_uid):
            if not uid:
                continue
            try:
                lookup = self._orthanc_client.post(
                    "tools/lookup",
                    content=uid.encode(),
                    headers={"Content-Type": "text/plain"},
                )
                if lookup.status_code != 200:
                    continue
                results = lookup.json()
                entries = results if isinstance(results, list) else [results]
                for entry in entries:
                    if not isinstance(entry, dict) or entry.get("Type") != "Instance":
                        continue
                    r = self._orthanc_client.get(f"instances/{entry.get('ID')}/preview")
                    if r.status_code == 200 and r.content:
                        return r.content
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                logger.debug("Orthanc preview fallback failed for %s: %s", uid[:16], exc)
        return b""

    def study_statistics(self, study_uid: str) -> StudyStatistics:
        """Sizes/status of a study from Orthanc (empty result on any failure)."""
        try:
            lookup = self._orthanc_client.post(
                "tools/lookup",
                content=study_uid.encode(),
                headers={"Content-Type": "text/plain"},
            )
            if lookup.status_code != 200:
                return StudyStatistics()
            entries = lookup.json()
            entries = entries if isinstance(entries, list) else [entries]
            study_id = ""
            for entry in entries:
                if isinstance(entry, dict) and entry.get("Type") == "Study":
                    study_id = str(entry.get("ID") or "")
                    break
            if not study_id:
                return StudyStatistics()
            stats_response = self._orthanc_client.get(f"studies/{study_id}/statistics")
            detail_response = self._orthanc_client.get(f"studies/{study_id}")
            stats = stats_response.json() if stats_response.status_code == 200 else {}
            detail = detail_response.json() if detail_response.status_code == 200 else {}
            if not isinstance(stats, dict):
                stats = {}
            if not isinstance(detail, dict):
                detail = {}
            return StudyStatistics(
                instances=_as_int_or_none(stats.get("CountInstances")),
                series=_as_int_or_none(stats.get("CountSeries")),
                size_mb=_as_float_or_none(stats.get("DicomDiskSizeMB") or stats.get("DiskSizeMB")),
                is_stable=detail.get("IsStable") if isinstance(detail.get("IsStable"), bool) else None,
                last_update=str(detail.get("LastUpdate") or ""),
            )
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            logger.debug("Study statistics unavailable for %s: %s", study_uid[:16], exc)
            return StudyStatistics()

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
            elif isinstance(results, dict) and "ID" in results:
                orthanc_id = results["ID"]
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
        parts.append(f"--{boundary}\r\nContent-Type: application/dicom\r\n\r\n".encode() + f + b"\r\n")
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
