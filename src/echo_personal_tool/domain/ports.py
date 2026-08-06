"""Domain ports (protocols implemented by infrastructure)."""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import Protocol

import numpy as np

from echo_personal_tool.domain.models import InstanceMetadata, StudyMetadata
from echo_personal_tool.domain.models.orthanc import (
    InstanceInfo,
    SeriesInfo,
    StowResult,
    StudyInfo,
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
    ) -> CMoveResult:
        """Download all instances in a series via C-MOVE (series-level query)."""
        ...


class DicomUploadClient(Protocol):
    """Unified upload contract (DIMSE or STOW-RS)."""

    def upload_instance(self, dicom_bytes: bytes) -> bool: ...
