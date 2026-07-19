"""DICOM pixel reader implementation."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from threading import Lock

import numpy as np
import pydicom

from echo_personal_tool.domain.models import InstanceMetadata
from echo_personal_tool.infrastructure.dicom_metadata_mapper import map_instance_metadata
from echo_personal_tool.infrastructure.dicom_session import get_thread_dicom_session
from echo_personal_tool.infrastructure.dicom_validator import validate_dicom_header

_CACHE_MAX_ENTRIES = 32


class _DecodedPixelCache:
    """Thread-safe LRU cache for decoded DICOM frames."""

    def __init__(self, max_entries: int = _CACHE_MAX_ENTRIES) -> None:
        self._max = max_entries
        self._cache: OrderedDict[tuple[str, int], np.ndarray] = OrderedDict()
        self._lock = Lock()

    def get(self, path: Path, frame_index: int) -> np.ndarray | None:
        key = (str(path), frame_index)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        return None

    def put(self, path: Path, frame_index: int, pixels: np.ndarray) -> None:
        key = (str(path), frame_index)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            else:
                if len(self._cache) >= self._max:
                    self._cache.popitem(last=False)
                self._cache[key] = pixels

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()


_pixel_cache = _DecodedPixelCache()


class DicomReaderImpl:
    """Infrastructure implementation of IDicomReader."""

    def read_metadata(self, path: Path) -> InstanceMetadata:
        validate_dicom_header(path)
        dataset = pydicom.dcmread(path, stop_before_pixels=True, force=True)
        return map_instance_metadata(dataset, path=path)

    def read_pixels(self, path: Path, frame_index: int = 0) -> np.ndarray:
        cached = _pixel_cache.get(path, frame_index)
        if cached is not None:
            return cached
        validate_dicom_header(path)
        session = get_thread_dicom_session()
        session.open(path)
        pixels = session.read_frame(frame_index)
        _pixel_cache.put(path, frame_index, pixels)
        return pixels
