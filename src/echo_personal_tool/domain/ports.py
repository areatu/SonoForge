"""Domain ports (protocols implemented by infrastructure)."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import numpy as np

from echo_personal_tool.domain.models import InstanceMetadata, StudyMetadata
from echo_personal_tool.domain.models.orthanc import InstanceInfo, SeriesInfo, StudyInfo


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


class DicomWebClient(Protocol):
    def ping(self) -> bool: ...

    def query_studies(self, patient_name: str | None = None) -> list[StudyInfo]: ...

    def query_series(self, study_uid: str) -> list[SeriesInfo]: ...

    def query_instances(self, study_uid: str, series_uid: str) -> list[InstanceInfo]: ...

    def download_instance(
        self, study_uid: str, series_uid: str, instance_uid: str
    ) -> bytes: ...

    def download_series(
        self,
        study_uid: str,
        series_uid: str,
        **kwargs: object,
    ) -> list[tuple[str, bytes]]: ...
