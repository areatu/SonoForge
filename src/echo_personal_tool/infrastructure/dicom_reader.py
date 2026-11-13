"""DICOM pixel reader implementation."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from threading import Lock

import numpy as np
import pydicom

from echo_personal_tool.domain.models import InstanceMetadata
from echo_personal_tool.infrastructure.dicom_metadata_mapper import map_instance_metadata
from echo_personal_tool.infrastructure.dicom_session import DicomSession, get_thread_dicom_session
from echo_personal_tool.infrastructure.dicom_validator import validate_dicom_header
from echo_personal_tool.infrastructure.file_identity import FileIdentity

_CACHE_MAX_ENTRIES = 32
_CACHE_MAX_BYTES = 64 * 1024 * 1024  # 64 MB


class _DecodedPixelCache:
    """Thread-safe LRU cache for decoded DICOM frames with byte-based limit.
    get() returns zero-copy reference.
    put() stores an OWNED WRITABLE copy — never a view — to survive release_heavy()."""

    def __init__(self, max_bytes: int = _CACHE_MAX_BYTES) -> None:
        self._max_bytes = max_bytes
        self._cache: OrderedDict[tuple[FileIdentity, int], np.ndarray] = OrderedDict()
        self._current_bytes = 0
        self._lock = Lock()

    def _discard_stale(self, path: Path, identity: FileIdentity | None) -> None:
        for key in list(self._cache):
            if key[0].path == path and key[0] != identity:
                self._current_bytes -= self._cache.pop(key).nbytes

    def get(self, path: Path, frame_index: int, *, identity: FileIdentity | None = None) -> np.ndarray | None:
        resolved = path.resolve()
        if identity is None:
            try:
                identity = FileIdentity.capture(resolved)
            except OSError:
                identity = None
        with self._lock:
            self._discard_stale(resolved, identity)
            key = (identity, frame_index)
            if identity is not None and key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        return None

    def put(self, path: Path, frame_index: int, pixels: np.ndarray, *, identity: FileIdentity | None = None) -> None:
        try:
            current = FileIdentity.capture(path)
        except OSError:
            return
        if identity is not None and identity != current:
            return  # Decode belonged to an older generation: never tag it as current.
        key = (current, frame_index)
        with self._lock:
            self._discard_stale(current.path, current)
            if key in self._cache:
                self._cache.move_to_end(key)
                return

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
            self._current_bytes = 0


_pixel_cache = _DecodedPixelCache()


class DicomReaderImpl:
    """Infrastructure implementation of IDicomReader."""

    def __init__(self, *, isolated: bool = False) -> None:
        self._isolated = isolated

    def read_metadata(self, path: Path) -> InstanceMetadata:
        validate_dicom_header(path)
        dataset = pydicom.dcmread(path, stop_before_pixels=True, force=True)
        return map_instance_metadata(dataset, path=path)

    def read_pixels(self, path: Path, frame_index: int = 0) -> np.ndarray:
        if self._isolated:
            # A preview must not evict or wait on an interactive cine's shared session.
            # Its compressed buffers live for this one request only, not for the folder.
            validate_dicom_header(path)
            session = DicomSession(isolated=True)
            try:
                session.open(path)
                return session.read_frame(frame_index)
            finally:
                session.release()
        resolved = path.resolve()
        for _attempt in range(2):
            identity = FileIdentity.capture(resolved)
            cached = _pixel_cache.get(resolved, frame_index, identity=identity)
            if cached is not None:
                if FileIdentity.capture(resolved) == identity:
                    return cached
                continue
            validate_dicom_header(resolved)
            session = get_thread_dicom_session(resolved)
            session.open(resolved)
            pixels = session.read_frame(frame_index)
            if FileIdentity.capture(resolved) != identity:
                continue
            _pixel_cache.put(resolved, frame_index, pixels, identity=identity)
            owned = _pixel_cache.get(resolved, frame_index, identity=identity)
            if FileIdentity.capture(resolved) != identity:
                continue
            return pixels if owned is None else owned
        raise OSError("DICOM source changed during pixel read; retry after the file is stable")
