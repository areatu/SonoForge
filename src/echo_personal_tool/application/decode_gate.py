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
from enum import IntEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from echo_personal_tool.application.workers.frame_loader_worker import FrameLoaderWorker

logger = logging.getLogger(__name__)


class DecodePriority(IntEnum):
    """Decode order for requests parked on the same file. Lower is decoded first."""

    INTERACTIVE = 0  # the frame the user is waiting for: scroll target, explicit request
    NEIGHBORS = 10  # frames around the scroll target
    PLAYBACK = 20  # cine prefetch batches
    BACKGROUND = 30  # leading scan frames, segment neighbours


# Request classes a newer request for the same file supersedes (see _coalesce_locked).
_COALESCED_PRIORITIES = frozenset({int(DecodePriority.INTERACTIVE)})


def decode_gate_key(path: Path | str) -> str:
    """File identity used by the gate; matches the session registry key."""
    return str(Path(path).resolve())


class DecodeGate:
    """Single-flight, priority-ordered hand-off between frame loader workers."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._owner: dict[str, Any] = {}
        self._parked: dict[str, list[tuple[int, int, Any]]] = {}
        self._seq = 0

    def enter(self, worker: FrameLoaderWorker) -> bool:
        """Claim the file for *worker*.

        Returns ``True`` when the caller may decode immediately, ``False`` when the worker
        was parked and will be adopted by whoever owns the file.
        """
        key = decode_gate_key(worker.decode_path)
        with self._lock:
            if key in self._owner:
                self._seq += 1
                queue = self._parked.setdefault(key, [])
                heapq.heappush(queue, (int(worker.priority), self._seq, worker))
                self._coalesce_locked(queue, worker)
                return False
            self._owner[key] = worker
            return True

    def _coalesce_locked(self, queue: list[tuple[int, int, Any]], worker: Any) -> None:
        """Drop parked requests of the same class that the new one supersedes.

        A newer INTERACTIVE request (scroll target, explicit frame request) supersedes the
        parked previous one. Without coalescing, scrubbing faster than the file decodes
        grows the queue without bound: every stale target is decoded in full and the latency
        of the frame actually on screen rises with each step.

        Speculative classes are deliberately NOT coalesced. Neighbour and playback prefetch
        batches cover frames the next requests will need, and they keep the decoder's file
        position where the following seek expects it; dropping parked neighbour batches
        measured slower, not faster (MJPEG 720p MP4 scroll: 45 -> 50 ms over 12 seeks).

        The controller already ignores responses whose request id has been superseded, and
        cancelled workers emit `cancelled` so retained-worker bookkeeping stays balanced.
        """
        priority = int(worker.priority)
        if priority not in _COALESCED_PRIORITIES or len(queue) < 2:
            return
        keep = [item for item in queue if item[2] is worker or item[0] != priority]
        dropped = [item[2] for item in queue if item[0] == priority and item[2] is not worker]
        if not dropped:
            return
        queue[:] = keep
        heapq.heapify(queue)
        for stale in dropped:
            cancel = getattr(stale, "cancel_parked", None)
            if callable(cancel):
                cancel()

    def next_parked(self, owner: FrameLoaderWorker) -> FrameLoaderWorker | None:
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
                return nxt
            self._owner.pop(key, None)
            self._parked.pop(key, None)
            return None

    def steal(self, owner: FrameLoaderWorker) -> FrameLoaderWorker | None:
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
            return heapq.heappop(queue)[2]

    def release(self, owner: FrameLoaderWorker) -> list[FrameLoaderWorker]:
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
        return [item[2] for item in sorted(queue)]

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
