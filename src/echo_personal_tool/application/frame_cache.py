"""In-memory frame store for the active DICOM instance.

Supports sparse storage with LRU eviction: frames far from the current
playback position are dropped to reduce RAM usage. The full frame array
can be reconstructed via the ``frames`` property when needed (e.g.
speckle tracking).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from echo_personal_tool.domain.exceptions import IncompleteCineError

_DEFAULT_EVICT_WINDOW = 40


class FrameCache:
    def __init__(self, *, evict_window: int = _DEFAULT_EVICT_WINDOW) -> None:
        self.source_path: Path | None = None
        self._frame_store: dict[int, np.ndarray] = {}
        self._total_frames: int = 0
        self._current_index: int = 0
        self._evict_window: int = evict_window

    @property
    def frames(self) -> np.ndarray | None:
        if not self._frame_store:
            return None
        if len(self._frame_store) == self._total_frames:
            return np.stack([self._frame_store[i] for i in range(self._total_frames)])
        return np.stack([self._frame_store[i] for i in sorted(self._frame_store)])

    def is_ready(self, path: Path) -> bool:
        return (
            self.source_path is not None
            and self._total_frames > 0
            and self.source_path.resolve() == Path(path).resolve()
        )

    def load(self, path: Path, frames: np.ndarray) -> None:
        arr = np.ascontiguousarray(frames)
        if arr.ndim == 3:
            pass
        elif arr.ndim == 4 and arr.shape[-1] in (3, 4):
            pass
        else:
            raise ValueError(f"Expected frames shape (N,H,W) or (N,H,W,C), got {arr.shape}")
        self.source_path = Path(path).resolve()
        self._frame_store = {i: arr[i] for i in range(arr.shape[0])}
        self._total_frames = arr.shape[0]
        self._current_index = 0

    def get(self, index: int) -> np.ndarray:
        if self._total_frames == 0:
            raise RuntimeError("Frame cache is empty")
        if index < 0 or index >= self._total_frames:
            raise IndexError(f"Frame index {index} out of range [0, {self._total_frames})")
        frame = self._frame_store.get(index)
        if frame is None:
            raise RuntimeError(
                f"Frame {index} was evicted; reload or set_current() within range"
            )
        return frame

    def set_total_frames(self, path: Path, total: int) -> None:
        self.source_path = Path(path).resolve()
        self._total_frames = total

    def put(self, index: int, frame: np.ndarray) -> None:
        self._frame_store[index] = frame

    def clear(self) -> None:
        self.source_path = None
        self._frame_store.clear()
        self._total_frames = 0
        self._current_index = 0

    def frame_count(self) -> int:
        return self._total_frames

    def memory_bytes(self) -> int:
        return sum(f.nbytes for f in self._frame_store.values())

    def is_loaded(self, index: int) -> bool:
        return index in self._frame_store

    def set_current(self, index: int) -> None:
        self._current_index = index
        self._evict()

    def prefetch(self, center: int, near: int = 5) -> None:
        self._current_index = center
        self._evict()

    def require_full_cine(self) -> np.ndarray:
        if not self._frame_store or self._total_frames == 0:
            raise IncompleteCineError("Frame cache is empty")
        if len(self._frame_store) != self._total_frames:
            raise IncompleteCineError(
                f"Only {len(self._frame_store)}/{self._total_frames} frames loaded. "
                "Reload full cine before speckle tracking."
            )
        return np.stack([self._frame_store[i] for i in range(self._total_frames)])

    def loaded_ahead(self, center: int) -> int:
        """Count loaded frames strictly after center (no wrap)."""
        if self._total_frames == 0:
            return 0
        return sum(1 for i in range(center + 1, self._total_frames) if i in self._frame_store)

    def nearest_loaded_ahead(self, center: int) -> int | None:
        """Return the smallest loaded index > center, wrapping to 0 at end; None if none."""
        if self._total_frames == 0:
            return None
        for idx in range(center + 1, self._total_frames):
            if idx in self._frame_store:
                return idx
        for idx in range(0, center):
            if idx in self._frame_store:
                return idx
        return None

    def _evict(self) -> None:
        lo = self._current_index - self._evict_window
        hi = self._current_index + self._evict_window
        to_drop = [i for i in self._frame_store if i < lo or i > hi]
        for i in to_drop:
            del self._frame_store[i]
