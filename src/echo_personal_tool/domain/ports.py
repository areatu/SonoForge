"""Domain ports (protocols implemented by infrastructure)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

import numpy as np

from echo_personal_tool.domain.models import InstanceMetadata, StudyMetadata
from echo_personal_tool.domain.models.orthanc import (
    InstanceInfo,
    SeriesInfo,
    StowResult,
    StudyEnrichment,
    StudyInfo,
    StudyStatistics,
)


class IDicomReader(Protocol):
    def read_pixels(self, path: Path, frame_index: int = 0) -> np.ndarray: ...

    def read_metadata(self, path: Path) -> InstanceMetadata: ...


class IStudyScanner(Protocol):
    def scan(self, root: Path) -> list[StudyMetadata]: ...


class IImageReader(Protocol):
    def read_pixels(self, path: Path) -> np.ndarray: ...


class IVideoReader(Protocol):
    @property
    def frame_count(self) -> int: ...

    @property
    def fps(self) -> float: ...

    def open(self, path: Path) -> None: ...

    def read_frame(self, index: int) -> np.ndarray: ...

    def get_buffered_frame(self, index: int) -> np.ndarray: ...

    def release(self) -> None: ...


class IOnnxSegmenter(Protocol):
    def segment(self, frame: np.ndarray) -> np.ndarray: ...

    def is_available(self) -> bool: ...


class QuerySource(Enum):
    DICOMWEB = "dicomweb"
    DIMSE = "dimse"
    AUTO = "auto"


class RetrievalSource(Enum):
    """Source for downloading DICOM instances."""

    WADO = "wado"
    DIMSE = "dimse"
    CMOVE = "cmove"
    AUTO = "auto"


class DicomWebClient(Protocol):
    def ping(self) -> bool: ...

    def query_studies(
        self,
        *,
        patient_name: str | None = None,
        patient_id: str | None = None,
        study_date: str | None = None,
    ) -> list[StudyInfo]: ...

    def query_series(self, study_uid: str) -> list[SeriesInfo]: ...

    def query_instances(self, study_uid: str, series_uid: str) -> list[InstanceInfo]: ...

    def download_instance(self, study_uid: str, series_uid: str, instance_uid: str) -> bytes: ...

    def stow_instances(self, dicom_files: list[bytes]) -> StowResult: ...

    # ── Optional enrichment (implementations may raise NotImplementedError
    # or return an empty value; the loader degrades gracefully) ─────────
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
        """Rendered JPEG/PNG preview of a series (empty bytes when unavailable).

        ``middle_frame`` asks for a frame from the middle of a loop instead of
        the first one — the caller uses it when the first attempt came back
        blank.  Implementations may ignore the hint.
        """
        ...

    def study_statistics(self, study_uid: str) -> StudyStatistics:
        """Sizes/status of a study (empty StudyStatistics when unavailable)."""
        ...

    def query_study_enrichments(
        self, *, on_batch: Callable[[dict[str, StudyEnrichment]], None] | None = None
    ) -> dict[str, StudyEnrichment]:
        """Instance-level tags aggregated per study (modes, stress, device).

        Optional: implementations may return an empty dict when the protocol
        cannot carry instance-level tags (DIMSE).  ``on_batch`` reports each
        processed page so callers can render progressively.
        """
        ...


class CMoveResult:
    """Result of a C-MOVE operation."""

    def __init__(self, completed: int, failed: int, warning: int):
        self.completed = completed
        self.failed = failed
        self.warning = warning


class DimseClient(Protocol):
    """DIMSE-native DICOM communication (blocking — worker threads only)."""

    def c_echo(self) -> bool: ...

    def c_find_studies(
        self,
        *,
        patient_name: str | None = None,
        patient_id: str | None = None,
        study_date: str | None = None,
    ) -> list[StudyInfo]: ...

    def c_find_series(self, study_uid: str) -> list[SeriesInfo]: ...

    def c_find_instances(self, study_uid: str, series_uid: str) -> list[InstanceInfo]: ...

    def c_store(self, dicom_bytes: bytes) -> bool: ...

    def c_get_instance(
        self,
        study_uid: str,
        series_uid: str,
        instance_uid: str,
        *,
        tls_args: tuple | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> bytes:
        """Download a single instance via C-GET."""
        ...

    def c_move_instances(
        self,
        study_uid: str,
        series_uid: str,
        instance_uids: list[str],
        *,
        move_destination_ae: str,
        scp_host: str,
        scp_port: int,
        received: dict[str, bytes],
        tls_args: tuple | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> CMoveResult:
        """Download instances via C-MOVE to embedded Storage SCP."""
        ...

    def c_move_series(
        self,
        study_uid: str,
        series_uid: str,
        *,
        move_destination_ae: str,
        scp_host: str,
        scp_port: int,
        received: dict[str, bytes],
        tls_args: tuple | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> CMoveResult:
        """Download all instances in a series via C-MOVE (series-level query)."""
        ...


class DicomUploadClient(Protocol):
    """Unified upload contract (DIMSE or STOW-RS)."""

    def upload_instance(self, dicom_bytes: bytes) -> bool: ...


@dataclass(frozen=True)
class ReportSignature:
    """Raw Ed25519 signature over a canonical report snapshot.

    ``signature`` is the 64-byte Ed25519 signature; the base64 receipt form is
    built by the domain receipt layer, never by the signer itself.
    """

    key_id: str
    algorithm: str
    public_key_b64: str
    signature: bytes


class Hl7MllpPort(Protocol):
    """MLLP / MLLP+TLS transport for HL7 v2 messages (#625).

    Sends one framed message and returns the parsed ACK.  The endpoint has
    already been judged by :mod:`transport_policy`; implementations must not
    log message payloads (PHI) or credentials.
    """

    def send_oru(self, payload: bytes, *, encoding: str = "utf-8") -> object:
        """Send one ORU payload; return an ``AckResult``-like object with ``accepted``/``code``/``control_id``."""
        ...


class FhirHttpPort(Protocol):
    """HTTPS transport for FHIR R4 Bundles (#625)."""

    def post_bundle(self, bundle_json: bytes) -> object:
        """POST a Bundle; return a result with ``status_code`` and ``accepted`` (2xx)."""
        ...


class SignerPort(Protocol):
    """Local Ed25519 signer for report protocols (#624).

    The private key is unwrapped with the signer's password/PIN only for the
    duration of :meth:`sign` and never persisted in plaintext. Implementations
    must wipe key material from memory after use and must not log secrets,
    payloads or signatures.
    """

    def sign(self, payload: bytes, *, secret: str) -> ReportSignature:
        """Sign *payload* with the bound user's Ed25519 key.

        *secret* is the user's password or PIN, re-entered at signing time.
        Raises :class:`~echo_personal_tool.domain.exceptions.UserAuthError`
        on authentication failure and
        :class:`~echo_personal_tool.domain.exceptions.ReportSignatureError`
        on signing failure.
        """
        ...

    def verify(self, payload: bytes, signature: ReportSignature) -> bool:
        """Return True if *signature* is valid for *payload* (offline check)."""
        ...
