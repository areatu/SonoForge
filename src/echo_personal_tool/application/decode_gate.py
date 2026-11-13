"""Priority-aware single-flight gate for frame decode requests.

Every decode request for a cine file ends up on the same shared session
(``dicom_session.get_dicom_session()``) or the same ``VideoReader``, both guarded by a
lock: two workers decoding one file cannot make progress in parallel, they serialise on
the lock while occupying ``QThreadPool`` threads that thumbnails or segmentation could
use. Worse, an interactive request (the frame the user scrolled to) that is submitted
behind a playback prefetch batch waits for that whole batch, because the pool is FIFO.

The gate keeps at most one *running* decode per file. Any other request for the same file
parks in a priority queue, and the running worker adopts it when it finishes its own
request:

- no pool thread ever blocks on the session/reader lock;
- the frame the user is waiting for is decoded before queued prefetch batches even when
  those were submitted first;
- parked work runs on the thread that already holds the warm session.

The gate is passive on purpose: it is consulted only from ``FrameLoaderWorker.run()``, so
workers that are never started (unit tests with spy thread pools, a saturated pool) leave
no state behind and nothing can be orphaned.
"""

from __future__ import annotations

import heapq
import logging
import threading
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Any, Protocol, TypeVar, cast

logger = logging.getLogger(__name__)


class GatedRequest(Protocol):
    """What the gate needs to know about a request: the file it decodes and how urgent it is.

    ``FrameLoaderWorker`` satisfies this structurally, so the gate does not import the worker
    (the worker imports the gate; a back-reference, even for typing, would be an import cycle).
    """

    @property
    def decode_path(self) -> Path | str: ...

    @property
    def priority(self) -> int: ...


#: A concrete request type: ``next_parked``/``steal``/``release`` hand back the kind the caller passed in.
_R = TypeVar("_R", bound=GatedRequest)


class DecodePriority(IntEnum):
    """Decode order for requests parked on the same file. Lower is decoded first."""

    INTERACTIVE = 0  # the frame the user is waiting for: scroll target, explicit request
    NEIGHBORS = 10  # frames around the scroll target
    PLAYBACK = 20  # cine prefetch batches
    BACKGROUND = 30  # leading scan frames, segment neighbours


# Request classes a newer request for the same file supersedes (see _coalesce_locked).
_COALESCED_PRIORITIES = frozenset({int(DecodePriority.INTERACTIVE)})
_SPECULATIVE_PRIORITIES = frozenset(
    {int(DecodePriority.NEIGHBORS), int(DecodePriority.PLAYBACK), int(DecodePriority.BACKGROUND)}
)

# Bounds are deliberately generous compared with the controller's normal in-flight set
# (one interactive target, one neighbour batch, one playback prefetch and one leading
# scan). They stop a runaway producer or a tab-switch burst from turning the parked queue
# into an unbounded frame cache of its own, without changing steady-state playback.
_DEFAULT_MAX_PARKED_REQUESTS_PER_FILE = 8
_DEFAULT_MAX_PARKED_FRAMES_PER_FILE = 128
_DEFAULT_MAX_PARKED_REQUESTS = 32
_DEFAULT_MAX_PENDING_BYTES = 512 * 1024 * 1024


@dataclass(frozen=True)
class DecodeQueueStats:
    """Bounded parked-work counters for diagnostics and escalation tests."""

    parked_requests: int
    parked_frames: int
    pending_bytes: int
    dropped_requests: int
    files_with_parked: int


def decode_gate_key(path: Path | str) -> str:
    """File identity used by the gate; matches the session registry key."""
    return str(Path(path).resolve())


def cancel_request(worker: object) -> None:
    """Cancel any worker exposing the optional cancellation hook."""
    cancel = getattr(worker, "cancel", None)
    if callable(cancel):
        cancel()


class DecodeGate:
    """Single-flight, priority-ordered hand-off between frame loader workers."""

    def __init__(
        self,
        *,
        max_parked_requests_per_file: int = _DEFAULT_MAX_PARKED_REQUESTS_PER_FILE,
        max_parked_frames_per_file: int = _DEFAULT_MAX_PARKED_FRAMES_PER_FILE,
        max_parked_requests: int = _DEFAULT_MAX_PARKED_REQUESTS,
        max_pending_bytes: int = _DEFAULT_MAX_PENDING_BYTES,
    ) -> None:
        self._lock = threading.Lock()
        self._owner: dict[str, GatedRequest] = {}
        self._parked: dict[str, list[tuple[int, int, GatedRequest]]] = {}
        self._seq = 0
        self._dropped_requests = 0
        self._max_parked_requests_per_file = max(1, int(max_parked_requests_per_file))
        self._max_parked_frames_per_file = max(1, int(max_parked_frames_per_file))
        self._max_parked_requests = max(1, int(max_parked_requests))
        self._max_pending_bytes = max(0, int(max_pending_bytes))

    @staticmethod
    def _requested_frames(worker: Any) -> int:
        value = getattr(worker, "requested_frames", None)
        return max(1, int(value)) if isinstance(value, int) else 1

    @classmethod
    def _request_bytes(cls, worker: Any) -> int:
        frame_bytes = getattr(worker, "estimated_frame_bytes", 0)
        return cls._requested_frames(worker) * max(0, int(frame_bytes or 0))

    @staticmethod
    def _request_range(worker: Any) -> tuple[int, int] | None:
        value = getattr(worker, "frame_range", None)
        if isinstance(value, tuple) and len(value) == 2 and all(isinstance(item, int) for item in value):
            return value
        return None

    @staticmethod
    def _ranges_overlap(first: tuple[int, int], second: tuple[int, int]) -> bool:
        return first[0] < second[1] and second[0] < first[1]

    def enter(self, worker: GatedRequest) -> bool:
        """Claim the file for *worker*, or park it under the speculative bounds.

        Returns ``True`` when the caller may decode immediately, ``False`` when the worker
        was parked (or dropped as redundant/over-budget) and will be adopted by whoever owns
        the file.  A dropped worker receives ``cancelled`` so retained-worker bookkeeping
        stays balanced.
        """
        key = decode_gate_key(worker.decode_path)
        dropped: list[Any] = []
        owns = False
        with self._lock:
            if key in self._owner:
                self._seq += 1
                queue = self._parked.setdefault(key, [])
                heapq.heappush(queue, (int(worker.priority), self._seq, worker))
                dropped.extend(self._coalesce_locked(queue, worker))
                if self._is_parked_locked(key, worker):
                    dropped.extend(self._enforce_bounds_locked(protected=worker))
                self._dropped_requests += len(dropped)
            else:
                self._owner[key] = worker
                owns = True
        for stale in dropped:
            self._cancel(stale)
        return owns

    def _is_parked_locked(self, key: str, worker: Any) -> bool:
        return any(item[2] is worker for item in self._parked.get(key, ()))

    def _coalesce_locked(self, queue: list[tuple[int, int, Any]], worker: Any) -> list[Any]:
        """Drop parked requests of the same class that the new one supersedes.

        A newer INTERACTIVE request (scroll target, explicit frame request) supersedes the
        parked previous one. Without coalescing, scrubbing faster than the file decodes
        grows the queue without bound: every stale target is decoded in full and the latency
        of the frame actually on screen rises with each step.

        Speculative classes are not coalesced wholesale: neighbour and playback batches
        cover frames the next requests will need, and dropping them in general measured
        slower (MJPEG 720p MP4 scroll: 45 -> 50 ms over 12 seeks). They are deduplicated
        only when one requested range contains the other, so a repeated tab/prefetch
        submission cannot park the same frames twice.

        The controller ignores responses whose request id has been superseded, and
        cancelled workers emit ``cancelled`` so retained-worker bookkeeping stays balanced.
        """
        priority = int(worker.priority)
        if len(queue) < 2:
            return []
        if priority in _COALESCED_PRIORITIES:
            dropped = [item[2] for item in queue if item[0] == priority and item[2] is not worker]
        elif priority in _SPECULATIVE_PRIORITIES:
            dropped = []
            incoming_range = self._request_range(worker)
            if incoming_range is not None:
                for item in queue:
                    other = item[2]
                    if item[0] != priority or other is worker:
                        continue
                    other_range = self._request_range(other)
                    if other_range is None or not self._ranges_overlap(incoming_range, other_range):
                        continue
                    if (other_range[0] >= incoming_range[0] and other_range[1] <= incoming_range[1]) or (
                        incoming_range[0] >= other_range[0] and incoming_range[1] <= other_range[1]
                    ):
                        # Keep the request the controller just submitted; the older
                        # overlapping batch is the one whose generation is stale.
                        dropped.append(other)
        else:
            return []
        if not dropped:
            return []
        dropped_ids = {id(item) for item in dropped}
        queue[:] = [item for item in queue if id(item[2]) not in dropped_ids]
        heapq.heapify(queue)
        return dropped

    def _enforce_bounds_locked(self, *, protected: Any) -> list[Any]:
        """Evict the oldest lowest-priority speculative request until every bound holds.

        Interactive requests are never speculative victims: a user-visible frame must not
        disappear because an unrelated prefetch filled the queue.  If only interactive work
        remains, exceeding the soft bound is the correct choice.
        """
        dropped: list[Any] = []
        for key, queue in list(self._parked.items()):
            while self._over_file_bounds(queue):
                victim = self._speculative_victim(queue, protected)
                if victim is None:
                    break
                self._remove_locked(key, victim)
                dropped.append(victim)
        while self._over_global_bounds():
            victim = self._speculative_victim_global(protected)
            if victim is None:
                break
            self._remove_locked(decode_gate_key(victim.decode_path), victim)
            dropped.append(victim)
        return dropped

    def _over_file_bounds(self, queue: list[tuple[int, int, Any]]) -> bool:
        if len(queue) > self._max_parked_requests_per_file:
            return True
        return sum(self._requested_frames(item[2]) for item in queue) > self._max_parked_frames_per_file

    def _over_global_bounds(self) -> bool:
        queues = [item for queue in self._parked.values() for item in queue]
        if len(queues) > self._max_parked_requests:
            return True
        return sum(self._request_bytes(item[2]) for item in queues) > self._max_pending_bytes

    @staticmethod
    def _speculative_victim(queue: list[tuple[int, int, Any]], protected: Any) -> Any | None:
        candidates = [item for item in queue if item[0] in _SPECULATIVE_PRIORITIES and item[2] is not protected]
        if not candidates:
            return None
        # Highest enum value = least urgent; oldest sequence first within a class.
        return max(candidates, key=lambda item: (item[0], -item[1]))[2]

    def _speculative_victim_global(self, protected: Any) -> Any | None:
        candidates = [
            (item[0], item[1], item[2])
            for queue in self._parked.values()
            for item in queue
            if item[0] in _SPECULATIVE_PRIORITIES and item[2] is not protected
        ]
        return max(candidates, key=lambda item: (item[0], -item[1]))[2] if candidates else None

    def _remove_locked(self, key: str, worker: Any) -> None:
        queue = self._parked.get(key)
        if queue is None:
            return
        queue[:] = [item for item in queue if item[2] is not worker]
        if not queue:
            self._parked.pop(key, None)
        else:
            heapq.heapify(queue)

    @staticmethod
    def _cancel(worker: Any) -> None:
        cancel = getattr(worker, "cancel_parked", None)
        if callable(cancel):
            cancel()

    def next_parked(self, owner: _R) -> _R | None:
        """Hand the file to the next parked worker, or release it.

        Returns ``None`` when nothing is parked; ownership is then dropped so a later
        ``enter()`` can claim the file again.
        """
        key = decode_gate_key(owner.decode_path)
        with self._lock:
            if self._owner.get(key) is not owner:
                return None
            queue = self._parked.get(key)
            if queue:
                nxt = heapq.heappop(queue)[2]
                self._owner[key] = nxt
                return cast(_R, nxt)
            self._owner.pop(key, None)
            self._parked.pop(key, None)
            return None

    def steal(self, owner: _R) -> _R | None:
        """Take the best parked request for *owner*'s file if it outranks *owner*.

        Called between the frames of a batch: the shared session lock only ever serialised
        single frames, so a batch that holds the file until its last frame would make an
        interactive scroll target wait for the whole batch - longer than the lock ever made
        it wait. Ownership stays with *owner*, which resumes its batch afterwards.
        """
        key = decode_gate_key(owner.decode_path)
        with self._lock:
            if self._owner.get(key) is not owner:
                return None
            queue = self._parked.get(key)
            if not queue or queue[0][0] >= int(owner.priority):
                return None
            return cast(_R, heapq.heappop(queue)[2])

    def release(self, owner: _R) -> list[_R]:
        """Drop *owner*'s claim; return parked workers nobody would pick up anymore.

        The returned list is empty on the normal path (``next_parked()`` drains the queue
        before the owner goes away). It is non-empty only if the decode loop broke early,
        and the caller must run those workers so no request is ever left unserved.
        """
        key = decode_gate_key(owner.decode_path)
        with self._lock:
            if self._owner.get(key) is not owner:
                return []
            self._owner.pop(key, None)
            queue = self._parked.pop(key, None) or []
        if queue:
            logger.warning("decode gate: releasing %s with %d parked request(s)", key, len(queue))
        return [cast(_R, item[2]) for item in sorted(queue)]

    def discard(self, worker: GatedRequest) -> bool:
        """Remove a cancelled parked request; an owner is released by its run loop."""
        key = decode_gate_key(worker.decode_path)
        with self._lock:
            if not self._is_parked_locked(key, worker):
                return False
            self._remove_locked(key, worker)
            return True

    def stats(self) -> DecodeQueueStats:
        """Bounded-queue counters: depth, pending frames/bytes and drops."""
        with self._lock:
            queues = [item for queue in self._parked.values() for item in queue]
            return DecodeQueueStats(
                parked_requests=len(queues),
                parked_frames=sum(self._requested_frames(item[2]) for item in queues),
                pending_bytes=sum(self._request_bytes(item[2]) for item in queues),
                dropped_requests=self._dropped_requests,
                files_with_parked=len(self._parked),
            )

    def parked_count(self, path: Path | str) -> int:
        """Number of requests waiting for *path* (diagnostics and tests)."""
        key = decode_gate_key(path)
        with self._lock:
            return len(self._parked.get(key, ()))

    def is_busy(self, path: Path | str) -> bool:
        """True while a worker owns the decode slot for *path*."""
        key = decode_gate_key(path)
        with self._lock:
            return key in self._owner
