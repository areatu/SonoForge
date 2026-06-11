"""Domain ports (protocols implemented by infrastructure)."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import numpy as np

from echo_personal_tool.domain.models import InstanceMetadata, StudyMetadata


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
