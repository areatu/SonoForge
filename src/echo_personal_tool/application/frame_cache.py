"""In-memory frame store for the active DICOM instance.

Supports sparse storage with LRU eviction: frames far from the current
playback position are dropped to reduce RAM usage. The full frame array
can be reconstructed via the ``frames`` property when needed (e.g.
speckle tracking).
"""

from __future__ import annotations

import bisect
import logging
from pathlib import Path

import numpy as np

from echo_personal_tool.domain.exceptions import IncompleteCineError

_logger = logging.getLogger(__name__)

_DEFAULT_EVICT_WINDOW = 40
_MAX_CACHE_MEMORY_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB cap
_MIN_FRAME_SIZE_BYTES = 640 * 480 * 2  # ~600 KB — at least one VGA uint8 frame


class FrameCache:
    def __init__(
        self,
        *,
        evict_window: int = _DEFAULT_EVICT_WINDOW,
        max_cache_bytes: int = _MAX_CACHE_MEMORY_BYTES,
    ) -> None:
        effective = max(max_cache_bytes, _MIN_FRAME_SIZE_BYTES)
        if effective != max_cache_bytes:
            _logger.warning(
                "FrameCache max_cache_bytes=%d below minimum %d; raising to minimum",
                max_cache_bytes,
                _MIN_FRAME_SIZE_BYTES,
            )
        self.source_path: Path | None = None
        self._frame_store: dict[int, np.ndarray] = {}
        self._total_frames: int = 0
        self._current_index: int = 0
        self._evict_window: int = evict_window
        self._max_cache_bytes: int = effective
        self._pinned: set[int] = set()
        self._sorted_keys: list[int] = []
        self._cached_frames: np.ndarray | None = None
        self._memory_bytes: int = 0

    @property
    def frames(self) -> np.ndarray | None:
        if self._cached_frames is not None:
            return self._cached_frames
        if not self._frame_store:
            return None
        if len(self._frame_store) == self._total_frames:
            self._cached_frames = np.stack([self._frame_store[i] for i in range(self._total_frames)])
        else:
            self._cached_frames = np.stack([self._frame_store[i] for i in self._sorted_keys])
        return self._cached_frames

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
        self._sorted_keys = sorted(self._frame_store.keys())
        self._cached_frames = None
        self._pinned.clear()
        self._memory_bytes = sum(f.nbytes for f in self._frame_store.values())

    def get(self, index: int) -> np.ndarray:
        if self._total_frames == 0:
            raise RuntimeError("Frame cache is empty")
        if index < 0 or index >= self._total_frames:
            raise IndexError(f"Frame index {index} out of range [0, {self._total_frames})")
        frame = self._frame_store.get(index)
        if frame is None:
            raise RuntimeError(f"Frame {index} was evicted; reload or set_current() within range")
        return frame

    def set_total_frames(self, path: Path, total: int) -> None:
        self.source_path = Path(path).resolve()
        self._total_frames = total

    def put(self, index: int, frame: np.ndarray) -> None:
        frame_bytes = frame.nbytes
        if index not in self._frame_store:
            bisect.insort(self._sorted_keys, index)
        else:
            self._memory_bytes -= self._frame_store[index].nbytes
        self._frame_store[index] = frame
        self._memory_bytes += frame_bytes
        self._cached_frames = None
        # Evict frames outside the window to prevent unbounded growth
        # from stale prefetch loads or scroll overshoot.
        if len(self._sorted_keys) > self._evict_window * 2:
            self._evict()
        # Enforce memory cap: evict oldest frames if over limit.
        if self._memory_bytes > self._max_cache_bytes:
            self._evict_to_memory_limit()

    def _forward_arc(self, length: int) -> set[int]:
        """Indexes of the next `length` frames from the current playhead,
        wrapping at the end of the cine so loop playback never hits a gap."""
        total = self._total_frames
        if total <= 0 or length <= 0:
            return set()
        base = self._current_index % total
        n = min(length, total)
        return {(base + i) % total for i in range(n)}

    def _evict_to_memory_limit(self) -> None:
        """Evict frames until memory is under the cap.

        Keeps a contiguous forward arc from the current playback index (the
        frames the decoder is producing and the playhead is about to show).
        Any other eviction order leaves a gap right in front of the playhead
        for large cines (e.g. an RGB clip that exceeds the cap), which makes
        the skip-ahead logic jump to the loaded tail (gold7/gold11/gold12).
        """
        if not self._sorted_keys:
            return
        target = self._max_cache_bytes // 2
        avg = self._memory_bytes / len(self._sorted_keys)
        capacity = max(2, int(target // avg) + 1) if avg > 0 else 2
        keep = self._forward_arc(capacity)
        for k in list(self._sorted_keys):
            if self._memory_bytes <= target:
                break
            if k in keep or k in self._pinned:
                continue
            frame = self._frame_store.pop(k, None)
            if frame is not None:
                self._memory_bytes -= frame.nbytes
            try:
                self._sorted_keys.remove(k)
            except ValueError:
                pass
        self._cached_frames = None

    def clear(self) -> None:
        self.source_path = None
        self._frame_store.clear()
        self._total_frames = 0
        self._current_index = 0
        self._pinned.clear()
        self._sorted_keys.clear()
        self._cached_frames = None
        self._memory_bytes = 0

    def frame_count(self) -> int:
        return self._total_frames

    def memory_bytes(self) -> int:
        return sum(f.nbytes for f in self._frame_store.values())

    def can_fit_full_cine(self) -> bool:
        """True if the whole cine at the observed (or minimum) frame size fits
        under the memory cap, so a full-cine prefetch won't trigger eviction.

        Uses the average size of already-loaded frames; falls back to
        ``_MIN_FRAME_SIZE_BYTES`` when nothing is loaded yet.
        """
        if self._total_frames <= 0:
            return False
        if self._frame_store:
            avg = self._memory_bytes / len(self._frame_store)
        else:
            avg = _MIN_FRAME_SIZE_BYTES
        return self._total_frames * avg <= self._max_cache_bytes

    def is_loaded(self, index: int) -> bool:
        return index in self._frame_store

    def set_current(self, index: int) -> None:
        self._current_index = index
        self._evict()

    def pin(self, index: int) -> None:
        self._pinned.add(index)

    def unpin(self, index: int) -> None:
        self._pinned.discard(index)

    def prefetch(self, center: int, near: int = 5) -> None:
        self._current_index = center
        self._evict()

    def require_full_cine(self) -> np.ndarray:
        if self._cached_frames is not None:
            return self._cached_frames
        if not self._frame_store or self._total_frames == 0:
            raise IncompleteCineError("Frame cache is empty")
        if len(self._frame_store) != self._total_frames:
            raise IncompleteCineError(
                f"Only {len(self._frame_store)}/{self._total_frames} frames loaded. "
                "Reload full cine before speckle tracking."
            )
        self._cached_frames = np.stack([self._frame_store[i] for i in range(self._total_frames)])
        return self._cached_frames

    def load_all_frames(self) -> np.ndarray:
        """Load all frames from source if not already cached.

        Returns the full frame array. Raises IncompleteCineError if source
        is not set or cannot provide frames.
        """
        if self._total_frames == 0:
            raise IncompleteCineError("No frames available")

        # Already fully loaded
        if self._cached_frames is not None and len(self._frame_store) == self._total_frames:
            return self._cached_frames
        if len(self._frame_store) == self._total_frames:
            self._cached_frames = np.stack([self._frame_store[i] for i in range(self._total_frames)])
            return self._cached_frames

        # Need to load missing frames from source
        if self.source_path is None:
            raise IncompleteCineError("No source path set")

        source = self.source_path
        suffix = source.suffix.lower()

        if suffix in (".mp4", ".avi", ".mov"):
            # Video file — use existing video reader
            from echo_personal_tool.infrastructure.video_reader import get_thread_video_reader

            reader = get_thread_video_reader()
            reader.open(source)
            frames = []
            for i in range(self._total_frames):
                frames.append(reader.read_frame(i))
            result = np.stack(frames)
        else:
            # DICOM — load frame by frame
            from echo_personal_tool.infrastructure.dicom_session import get_thread_dicom_session

            session = get_thread_dicom_session()
            session.open(source)
            frames = []
            for i in range(self._total_frames):
                frames.append(session.decode_single_frame(i))
            result = np.stack(frames)

        # Cache all frames — store only in _cached_frames to avoid duplication
        self._cached_frames = result
        self._frame_store = {i: result[i] for i in range(result.shape[0])}
        self._sorted_keys = sorted(self._frame_store.keys())
        self._memory_bytes = sum(f.nbytes for f in self._frame_store.values())

        return result

    def loaded_ahead(self, center: int) -> int:
        """Count loaded frames forming a contiguous run starting right after
        ``center`` (wrapping at the end of the cine).

        Frames cached further ahead but with a gap in between (e.g. the loop
        tail kept by eviction) are deliberately not counted: a prefetch that
        adds ``start = center + 1 + ahead`` would otherwise skip over the gap
        and leave the playhead with holes (gold7/gold11/gold12 skip bug).
        """
        total = self._total_frames
        if total == 0:
            return 0
        store = self._frame_store
        count = 0
        idx = (center + 1) % total
        while idx in store and count < total:
            count += 1
            idx = (idx + 1) % total
        return count

    def loaded_before(self, center: int) -> int:
        """Count loaded frames strictly before center (no wrap)."""
        if self._total_frames == 0:
            return 0
        return bisect.bisect_left(self._sorted_keys, center)

    def nearest_loaded_before(self, center: int) -> int | None:
        """Return the largest loaded index < center; None if none."""
        if self._total_frames == 0:
            return None
        keys = self._sorted_keys
        idx = bisect.bisect_left(keys, center)
        return keys[idx - 1] if idx > 0 else None

    def nearest_loaded_ahead(self, center: int) -> int | None:
        """Return the smallest loaded index > center, wrapping to 0 at end; None if none."""
        if self._total_frames == 0:
            return None
        keys = self._sorted_keys
        idx = bisect.bisect_right(keys, center)
        if idx < len(keys):
            return keys[idx]
        return keys[0] if keys and keys[0] < center else None

    def _evict(self) -> None:
        lo = self._current_index - self._evict_window
        hi = self._current_index + self._evict_window
        keys = self._sorted_keys
        if not keys:
            return
        # Keep the whole cine when it could fit under the memory cap even at
        # the minimum frame size. Window-based eviction would otherwise drop
        # frames needed for loop wrap-around (e.g. a 55-frame clip with a
        # 20-frame window evicts the tail on the first step and the head near
        # the end), stalling playback at ~3/4 and at the end without looping.
        if self._total_frames * _MIN_FRAME_SIZE_BYTES <= self._max_cache_bytes:
            return
        # Frames outside [lo, hi] are evicted, except the wrap-around head
        # frames (0..wrap_head) that playback needs when looping past the end.
        wrap_head = hi - self._total_frames + 1 if hi >= self._total_frames else -1
        left_drop = [k for k in keys[: bisect.bisect_left(keys, lo)] if k > wrap_head]
        right_drop = keys[bisect.bisect_right(keys, hi) :]
        to_drop = [k for k in left_drop + right_drop if k not in self._pinned]
        if not to_drop:
            return
        to_drop_set = set(to_drop)
        for k in to_drop:
            frame = self._frame_store.pop(k, None)
            if frame is not None:
                self._memory_bytes -= frame.nbytes
        self._sorted_keys = [k for k in keys if k not in to_drop_set]
        self._cached_frames = None
