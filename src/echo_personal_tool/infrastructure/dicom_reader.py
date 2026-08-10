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
_CACHE_MAX_BYTES = 64 * 1024 * 1024  # 64 MB


class _DecodedPixelCache:
    """Thread-safe LRU cache for decoded DICOM frames with byte-based limit.
    get() returns zero-copy reference.
    put() stores an OWNED WRITABLE copy — never a view — to survive release_heavy()."""

    def __init__(self, max_bytes: int = _CACHE_MAX_BYTES) -> None:
        self._max_bytes = max_bytes
        self._cache: OrderedDict[tuple[str, int], np.ndarray] = OrderedDict()
        self._current_bytes = 0
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
                return

            # BOUNDARY COPY: Cache must own writable memory
            owned = np.array(pixels, copy=True)
            entry_bytes = owned.nbytes

            while self._current_bytes + entry_bytes > self._max_bytes and self._cache:
                _, evicted = self._cache.popitem(last=False)
                self._current_bytes -= evicted.nbytes

            self._cache[key] = owned
            self._current_bytes += entry_bytes

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
        return _pixel_cache.get(path, frame_index)
