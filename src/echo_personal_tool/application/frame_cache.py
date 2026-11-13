"""In-memory frame store for the active DICOM instance.

Two storage modes are explicit.  A *full* cine is one immutable backing
allocation under a separate full-cine reservation; the sparse mode keeps
independent frames around the playhead under the ordinary byte budget.
``memory_stats()`` reports logical bytes, owned backing bytes, pinned bytes and
the observed peak so callers can see a view pinning a large parent instead of
trusting a shrinking sum of ``frame.nbytes``.
"""

from __future__ import annotations

import bisect
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from echo_personal_tool.domain.exceptions import IncompleteCineError

_logger = logging.getLogger(__name__)

_DEFAULT_EVICT_WINDOW = 40
_MAX_CACHE_MEMORY_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB cap
_MIN_FRAME_SIZE_BYTES = 640 * 480 * 2  # ~600 KB — at least one VGA uint8 frame
# Share of the emergency-eviction capacity kept ahead of the playhead; the rest is kept
# behind it so rewind and loop wrap-around do not always miss.
_FORWARD_ARC_FRACTION = 0.75
# Where the emergency trim stops, as a share of the budget. Half is deliberate: it leaves
# room for a whole prefetch run to land before the next trim, and the store may legally sit
# anywhere between the trim target and the budget, so a window wider than capacity_frames()
# still pays off (measured: 44 frames retained on a 720p RGB cine versus 35 at 3/4, and
# 423 decoded frames for 368 displayed versus 577).
_EMERGENCY_TRIM_FRACTION = 0.5


@dataclass(frozen=True)
class FrameProjection:
    """Loaded frames in source-index order, not necessarily a continuous cine.

    No timing is inferred: consumers must map frame_indices to source timestamps.
    """

    frame_indices: tuple[int, ...]
    frames: np.ndarray

    @property
    def nbytes(self) -> int:
        """Temporary projection size, outside the cache's owned budget."""
        return int(self.frames.nbytes)


@dataclass(frozen=True)
class FrameMemoryStats:
    """What the frame store actually holds, not just the sum of views.

    ``logical_bytes`` is the sum of the frame views; ``owned_bytes`` counts
    each backing allocation once, so views into one full cine are not counted
    N times and a view that pins a large parent is still visible after most of
    its siblings were evicted.  ``pinned_bytes`` is the logical size of the
    explicitly pinned frames.  ``peak_bytes`` is the high-water mark observed
    by the cache itself.
    """

    frame_count: int
    logical_bytes: int
    owned_bytes: int
    pinned_bytes: int
    peak_bytes: int
    budget_bytes: int
    mode: str


class FrameCache:
    def __init__(
        self,
        *,
        evict_window: int = _DEFAULT_EVICT_WINDOW,
        max_cache_bytes: int = _MAX_CACHE_MEMORY_BYTES,
        max_full_cine_bytes: int | None = None,
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
        # A full immutable cine is a separate reservation from the sparse
        # window budget: analysing a whole clip is a deliberate operation,
        # not another prefetch that can be silently evicted.
        self._max_full_cine_bytes: int = (
            _MAX_CACHE_MEMORY_BYTES if max_full_cine_bytes is None else max(1, int(max_full_cine_bytes))
        )
        self._pinned: set[int] = set()
        self._sorted_keys: list[int] = []
        self._cached_frames: np.ndarray | None = None
        self._memory_bytes: int = 0
        self._logical_bytes: int = 0
        #: Strong references to each distinct backing allocation, keyed by id.
        #: The value is (root array, number of stored views that reference it).
        self._owners: dict[int, tuple[np.ndarray, int]] = {}
        self._peak_memory_bytes: int = 0

    def _has_full_cine(self) -> bool:
        return (
            self._total_frames > 0
            and len(self._frame_store) == self._total_frames
            and all(0 <= index < self._total_frames for index in self._frame_store)
        )

    @property
    def sparse_projection(self) -> FrameProjection | None:
        """Return loaded pixels with their original indices; never cache a partial stack."""
        if not self._frame_store:
            return None
        indices = tuple(self._sorted_keys)
        if self._has_full_cine():
            pixels = self.require_full_cine()
        else:
            pixels = np.stack([self._frame_store[i] for i in indices])
            # The caller owns this temporary projection until it drops it; it
            # is not cache-owned memory, but the peak must not hide it.
            self._note_peak(self._memory_bytes + pixels.nbytes)
        return FrameProjection(indices, pixels)

    @property
    def frames(self) -> np.ndarray | None:
        """Legacy loaded-frame projection. Use require_full_cine for temporal analysis.

        Partial results are not memoized as a full cine. New sparse consumers should
        use sparse_projection to retain the source-index mapping.
        """
        projection = self.sparse_projection
        return None if projection is None else projection.frames

    def _stack_full_cine(self) -> np.ndarray:
        """Stack every frame and rebind the store to views into that stack.

        Keeping the per-frame arrays *and* the stack doubles residency - 166 MB twice for a
        60-frame 720p cine - while M-mode and speckle tracking ask for the stack and
        playback keeps reading single frames. Views make it one copy with two shapes.
        """
        stacked = np.stack([self._frame_store[i] for i in range(self._total_frames)])
        self._note_peak(self._memory_bytes + stacked.nbytes)
        self._frame_store = {i: stacked[i] for i in range(self._total_frames)}
        self._reset_owners_from_store()
        return stacked

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
        owned_bytes = self._root_array(arr).nbytes
        if owned_bytes > self._max_full_cine_bytes:
            raise ValueError(
                f"Full cine needs {owned_bytes} owned bytes, above the full-cine reservation "
                f"of {self._max_full_cine_bytes}; decode a frame range instead"
            )
        self.source_path = Path(path).resolve()
        self._frame_store = {i: arr[i] for i in range(arr.shape[0])}
        self._total_frames = arr.shape[0]
        self._current_index = 0
        self._sorted_keys = sorted(self._frame_store.keys())
        self._cached_frames = None
        self._pinned.clear()
        self._peak_memory_bytes = 0
        self._reset_owners_from_store()

    def load_sparse(self, path: Path, frames: np.ndarray, *, indices: Iterable[int] | None = None) -> None:
        """Admit only selected independent frames, never the whole cine.

        This is the sparse counterpart of :meth:`load`: the caller may still
        have decoded a full array (the source API is the caller's business),
        but the cache keeps copies of only the requested cycles and the large
        parent is not retained.  ``indices`` defaults to the first evict
        window's worth of frames.
        """
        arr = np.ascontiguousarray(frames)
        if arr.ndim not in (3, 4) or (arr.ndim == 4 and arr.shape[-1] not in (3, 4)):
            raise ValueError(f"Expected frames shape (N,H,W) or (N,H,W,C), got {arr.shape}")
        total = arr.shape[0]
        requested: Iterable[int] = range(min(total, max(1, self._evict_window))) if indices is None else indices
        selected = sorted({int(index) for index in requested if 0 <= int(index) < total})
        self.source_path = Path(path).resolve()
        self._total_frames = total
        self._current_index = 0
        self._frame_store = {}
        self._sorted_keys = []
        self._cached_frames = None
        self._pinned.clear()
        self._owners.clear()
        self._memory_bytes = 0
        self._logical_bytes = 0
        self._peak_memory_bytes = 0
        for index in selected:
            self._store_frame(index, np.array(arr[index], copy=True, order="C"))
        if self._memory_bytes > self._max_cache_bytes:
            self._evict_to_memory_limit()

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
        if total < 0:
            raise ValueError("total frames must not be negative")
        resolved = Path(path).resolve()
        if resolved != self.source_path or total != self._total_frames:
            self.clear()
        self.source_path = resolved
        self._total_frames = total

    def put(self, index: int, frame: np.ndarray) -> None:
        if index not in self._frame_store:
            bisect.insort(self._sorted_keys, index)
        self._store_frame(index, frame)
        self._cached_frames = None
        # Evict frames outside the window to prevent unbounded growth
        # from stale prefetch loads or scroll overshoot.
        if len(self._sorted_keys) > self._evict_window * 2:
            self._evict()
        # Enforce memory cap: evict oldest frames if over limit.
        if self._memory_bytes > self._max_cache_bytes:
            self._evict_to_memory_limit()

    @staticmethod
    def _root_array(frame: np.ndarray) -> np.ndarray:
        """The allocation that owns *frame*, not the view itself."""
        root = frame
        while isinstance(root.base, np.ndarray) and root.base is not root:
            root = root.base
        return root

    def _note_peak(self, value: int | None = None) -> None:
        candidate = self._memory_bytes if value is None else value
        if candidate > self._peak_memory_bytes:
            self._peak_memory_bytes = candidate

    def _register_owner(self, frame: np.ndarray) -> None:
        root = self._root_array(frame)
        key = id(root)
        existing = self._owners.get(key)
        if existing is None:
            self._owners[key] = (root, 1)
            self._memory_bytes += root.nbytes
            self._note_peak()
            return
        self._owners[key] = (existing[0], existing[1] + 1)

    def _unregister_owner(self, frame: np.ndarray) -> None:
        root = self._root_array(frame)
        key = id(root)
        existing = self._owners.get(key)
        if existing is None:
            return
        count = existing[1] - 1
        if count > 0:
            self._owners[key] = (existing[0], count)
            return
        del self._owners[key]
        self._memory_bytes = max(0, self._memory_bytes - root.nbytes)

    def _reset_owners_from_store(self) -> None:
        self._owners.clear()
        self._memory_bytes = 0
        self._logical_bytes = 0
        for frame in self._frame_store.values():
            self._logical_bytes += frame.nbytes
            self._register_owner(frame)
        self._note_peak()

    def _store_frame(self, index: int, frame: np.ndarray) -> None:
        previous = self._frame_store.get(index)
        if previous is not None:
            self._unregister_owner(previous)
            self._logical_bytes -= previous.nbytes
        self._frame_store[index] = frame
        self._register_owner(frame)
        self._logical_bytes += frame.nbytes
        self._note_peak()

    def _drop_frame(self, index: int, *, remove_key: bool) -> None:
        frame = self._frame_store.pop(index, None)
        if frame is None:
            return
        self._unregister_owner(frame)
        self._logical_bytes = max(0, self._logical_bytes - frame.nbytes)
        if remove_key:
            try:
                self._sorted_keys.remove(index)
            except ValueError:
                pass

    def _compact_shared_backing(self) -> None:
        """Turn the remaining views into independent frames when a shared parent is pinned.

        Evicting most views of a full cine leaves one allocation alive as long
        as *one* view survives.  Copying the survivors is the only way to let
        the large parent go; the full→sparse transition therefore pays this
        bounded copy once instead of reporting a falling logical size while RSS
        stays flat.
        """
        if not self._frame_store or self._memory_bytes <= self._logical_bytes:
            return
        self._note_peak(self._memory_bytes + self._logical_bytes)
        copies = {index: np.array(frame, copy=True, order="C") for index, frame in self._frame_store.items()}
        self._cached_frames = None
        self._frame_store = copies
        self._reset_owners_from_store()

    def _forward_arc(self, length: int) -> set[int]:
        """Indexes of the next `length` frames from the current playhead,
        wrapping at the end of the cine so loop playback never hits a gap."""
        total = self._total_frames
        if total <= 0 or length <= 0:
            return set()
        base = self._current_index % total
        n = min(length, total)
        return {(base + i) % total for i in range(n)}

    def _backward_arc(self, length: int) -> set[int]:
        """Indexes of the `length` frames behind the playhead, wrapping at the start.

        Rewind, backward scrubbing and the loop wrap-around read these; an eviction that
        keeps only the forward arc guarantees a miss the moment the user goes back.
        """
        total = self._total_frames
        if total <= 0 or length <= 0:
            return set()
        base = self._current_index % total
        n = min(length, total)
        return {(base - i) % total for i in range(1, n + 1)}

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
        target = int(self._max_cache_bytes * _EMERGENCY_TRIM_FRACTION)  # half the budget
        avg = self._memory_bytes / len(self._sorted_keys)
        capacity = max(2, int(target // avg) + 1) if avg > 0 else 2
        forward = max(1, int(capacity * _FORWARD_ARC_FRACTION))
        keep = self._forward_arc(forward) | self._backward_arc(capacity - forward)
        for k in list(self._sorted_keys):
            if self._memory_bytes <= target:
                break
            if k in keep or k in self._pinned:
                continue
            self._drop_frame(k, remove_key=True)
        self._cached_frames = None
        self._compact_shared_backing()

    def clear(self) -> None:
        self.source_path = None
        self._frame_store.clear()
        self._total_frames = 0
        self._current_index = 0
        self._pinned.clear()
        self._sorted_keys.clear()
        self._cached_frames = None
        self._memory_bytes = 0
        self._logical_bytes = 0
        self._owners.clear()
        self._peak_memory_bytes = 0

    def frame_count(self) -> int:
        return self._total_frames

    def memory_bytes(self) -> int:
        """Owned backing bytes, counting each shared parent allocation once.

        This is deliberately not ``sum(frame.nbytes)``: N views into one full
        cine are one allocation, and after eviction a remaining view can still
        pin that allocation.  The counter is maintained by every mutation, so
        this is O(1).
        """
        return self._memory_bytes

    def logical_bytes(self) -> int:
        """Sum of the stored frame views (may be smaller than owned bytes)."""
        return self._logical_bytes

    def peak_memory_bytes(self) -> int:
        """High-water mark of owned bytes observed by this cache."""
        return self._peak_memory_bytes

    def memory_stats(self) -> FrameMemoryStats:
        """Snapshot for diagnostics: logical vs owned vs pinned bytes and mode."""
        pinned = sum(frame.nbytes for index, frame in self._frame_store.items() if index in self._pinned)
        return FrameMemoryStats(
            frame_count=len(self._frame_store),
            logical_bytes=self._logical_bytes,
            owned_bytes=self._memory_bytes,
            pinned_bytes=pinned,
            peak_bytes=self._peak_memory_bytes,
            budget_bytes=self._max_cache_bytes,
            mode="full" if self._has_full_cine() else "sparse",
        )

    @property
    def memory_budget(self) -> int:
        """Byte ceiling for the cached frames (see set_memory_budget)."""
        return self._max_cache_bytes

    @property
    def full_cine_reservation_bytes(self) -> int:
        """Separate ceiling for one immutable full cine (load/require_full_cine)."""
        return self._max_full_cine_bytes

    def set_memory_budget(self, budget_bytes: int) -> None:
        """Raise or lower the byte ceiling.

        Growing is what lets a 720p cine buffer a second of playback instead of a third;
        the caller is responsible for staying inside the machine's RAM share. Shrinking
        below what is already held is left to the next put(), which trims as before.
        """
        self._max_cache_bytes = max(budget_bytes, _MIN_FRAME_SIZE_BYTES)

    def set_evict_window(self, window: int) -> None:
        """Set the LRU half-width around the playhead.

        The window must not undercut the prefetch target: frames decoded further ahead than
        it are evicted before the playhead can reach them, so a deep buffer would decode
        the same frames over and over.
        """
        self._evict_window = max(1, int(window))

    @property
    def evict_window(self) -> int:
        """Half-width of the LRU window around the playhead.

        Frames decoded further ahead than this are dropped again before the playhead can
        reach them, so it is a hard limit on how deep a prefetch may aim.
        """
        return self._evict_window

    def average_frame_bytes(self) -> float:
        """Observed mean size of one cached frame.

        Falls back to the VGA constant while nothing is loaded, which is the conservative
        answer: it assumes big frames, so sizing decisions do not over-commit the budget.
        """
        if self._frame_store:
            return self._memory_bytes / len(self._frame_store)
        return float(_MIN_FRAME_SIZE_BYTES)

    def capacity_frames(self) -> int:
        """Frames the budget can hold at the observed size without an emergency trim.

        Measured against the trim target rather than the full budget: a prefetch aimed past
        it decodes frames that are dropped again before the playhead reaches them (measured
        as 26 decoded frames per displayed frame on a 720p RGB cine).
        """
        avg = self.average_frame_bytes()
        if avg <= 0:
            return 0
        return max(1, int((self._max_cache_bytes * _EMERGENCY_TRIM_FRACTION) // avg))

    def budget_for_frames(self, frames: int) -> int:
        """Byte budget that retains `frames` of the current average size.

        The inverse of capacity_frames(): callers sizing the cache for a buffer depth in
        seconds ask this instead of re-deriving the trim fraction.
        """
        if frames <= 0:
            return 0
        return int(frames * self.average_frame_bytes() / _EMERGENCY_TRIM_FRACTION)

    def can_fit_full_cine(self) -> bool:
        """True if the whole cine at the observed (or minimum) frame size fits
        under the memory cap, so a full-cine prefetch won't trigger eviction.

        Uses the average size of already-loaded frames; falls back to
        ``_MIN_FRAME_SIZE_BYTES`` when nothing is loaded yet.
        """
        if self._total_frames <= 0:
            return False
        return self._total_frames * self.average_frame_bytes() <= self._max_cache_bytes

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
        if not self._frame_store or self._total_frames == 0:
            raise IncompleteCineError("Frame cache is empty")
        if not self._has_full_cine():
            raise IncompleteCineError(
                f"Only {len(self._frame_store)}/{self._total_frames} frames loaded. "
                "Reload full cine before speckle tracking."
            )
        if self._cached_frames is None:
            shared = self._single_shared_backing()
            self._cached_frames = shared if shared is not None else self._stack_full_cine()
        return self._cached_frames

    def _single_shared_backing(self) -> np.ndarray | None:
        """The one parent array when every stored frame is already its view."""
        if len(self._owners) != 1 or len(self._frame_store) != self._total_frames:
            return None
        root = next(iter(self._owners.values()))[0]
        if root.ndim >= 3 and root.shape[0] == self._total_frames and root.nbytes == self._logical_bytes:
            return root
        return None

    def _decode_into_full_buffer(self, decode_frame: Callable[[int], np.ndarray]) -> np.ndarray:
        """Fill one preallocated cine buffer instead of list + np.stack.

        ``np.stack(frames)`` holds every decoded frame *and* the stacked copy
        at the same time, so the peak is twice the cine.  Preallocation keeps
        the decoded frame count at one while still producing one owned array.
        """
        first = np.asarray(decode_frame(0))
        result = np.empty((self._total_frames,) + first.shape, dtype=first.dtype)
        result[0] = first
        for index in range(1, self._total_frames):
            result[index] = np.asarray(decode_frame(index))
        return result

    def load_all_frames(self) -> np.ndarray:
        """Load all frames from source if not already cached.

        Returns the full frame array. Raises IncompleteCineError if source
        is not set or cannot provide frames.
        """
        if self._total_frames == 0:
            raise IncompleteCineError("No frames available")

        # Check completeness before consulting any memoized full stack.
        if self._has_full_cine():
            return self.require_full_cine()

        # Need to load missing frames from source
        if self.source_path is None:
            raise IncompleteCineError("No source path set")

        source = self.source_path
        suffix = source.suffix.lower()

        if suffix in (".mp4", ".avi", ".mov"):
            # Video file — use existing video reader
            from echo_personal_tool.infrastructure.video_reader import get_thread_video_reader

            reader = get_thread_video_reader(source)
            reader.open(source)
            result = self._decode_into_full_buffer(reader.read_frame)
        else:
            # DICOM — load frame by frame
            from echo_personal_tool.infrastructure.dicom_session import get_thread_dicom_session

            session = get_thread_dicom_session(source)
            session.open(source)
            result = self._decode_into_full_buffer(session.decode_single_frame)

        # Cache all frames — store only in _cached_frames to avoid duplication
        self._note_peak(self._memory_bytes + result.nbytes)
        self._cached_frames = result
        self._frame_store = {i: result[i] for i in range(result.shape[0])}
        self._sorted_keys = sorted(self._frame_store.keys())
        self._reset_owners_from_store()

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
        # Keep the whole cine when it fits under the memory cap at the observed frame
        # size. Window-based eviction would otherwise drop frames needed for loop
        # wrap-around (e.g. a 55-frame clip with a 20-frame window evicts the tail on the
        # first step and the head near the end), stalling playback at ~3/4 and at the end
        # without looping.
        #
        # The estimate has to be the observed frame size: with the VGA constant a 720p cine
        # (2.76 MB per frame, 4.6x larger) always looked like it fitted - 60 frames
        # "weighed" 36.9 MB against a 64 MB budget - so window eviction never ran, the
        # cache grew until _evict_to_memory_limit() dumped half of it, and the store
        # oscillated 33 <-> 66 MB while every wrap and rewind missed.
        if self._total_frames * self.average_frame_bytes() <= self._max_cache_bytes:
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
            self._drop_frame(k, remove_key=False)
        self._sorted_keys = [k for k in keys if k not in to_drop_set]
        self._cached_frames = None
        self._compact_shared_backing()
