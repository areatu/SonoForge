"""Bounded, lazy CT/MR slice requests, independent of the GUI event loop."""

from __future__ import annotations

import logging
from collections import OrderedDict, deque
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from threading import Event, Lock

import numpy as np

from echo_personal_tool.domain.models.ctmr_stack import CtMrStack, StackFrameRef

logger = logging.getLogger(__name__)
_PREFETCH_RESULT_MAX = 24


@dataclass(frozen=True, eq=False)
class SliceTicket:
    """Unique request; identity equality prevents cross-owner admission."""

    ref: StackFrameRef
    stack_index: int
    cancelled: Event


@dataclass(frozen=True)
class SliceResult:
    ticket: SliceTicket
    pixels: np.ndarray | None
    error: str | None = None


class CtMrSliceRequests:
    """One running read, one latest pending request and optional lookahead prefetch.

    select_stack/request/cancel/poll/claim must be serialized by the owning
    UI/event thread. Poll on that thread, then claim immediately before publishing
    success or error, without yielding. No callback runs UI code on a worker.
    Native decode cannot be interrupted; cancellation revokes publication.
    """

    def __init__(
        self,
        read: Callable[[StackFrameRef, Callable[[], bool]], np.ndarray],
        is_current: Callable[[StackFrameRef], bool],
        *,
        on_ready: Callable[[], None] | None = None,
    ) -> None:
        self._read, self._is_current = read, is_current
        self._on_ready = on_ready
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ctmr-slice")
        self._lock = Lock()
        self._stack: CtMrStack | None = None
        self._active: SliceTicket | None = None
        self._pending: SliceTicket | None = None
        self._result: SliceResult | None = None
        self._prefetch_queue: deque[int] = deque()
        self._prefetch_active: SliceTicket | None = None
        self._prefetched: OrderedDict[int, tuple[StackFrameRef, np.ndarray]] = OrderedDict()
        self._running = False
        self._closed = False

    def set_on_ready(self, callback: Callable[[], None] | None) -> None:
        """Attach a thread-safe wake callback (e.g. a Qt Signal.emit)."""
        with self._lock:
            self._on_ready = callback

    def _notify_ready(self) -> None:
        callback = self._on_ready
        if callback is not None:
            try:
                callback()
            except RuntimeError as exc:
                logger.debug("ctmr ready callback skipped: %s", type(exc).__name__)

    def _cancel_prefetch_locked(self) -> None:
        if self._prefetch_active is not None:
            self._prefetch_active.cancelled.set()
            self._prefetch_active = None
        self._prefetch_queue.clear()

    def _cancel_locked(self) -> None:
        if self._active is not None:
            self._active.cancelled.set()
        self._active = None
        self._pending = None
        self._result = None
        self._cancel_prefetch_locked()

    def select_stack(self, stack: CtMrStack | None) -> None:
        """Every selection, including reselecting the same stack, revokes old work."""
        with self._lock:
            if self._closed:
                raise RuntimeError("slice_requests_closed")
            self._cancel_locked()
            self._prefetched.clear()
            self._stack = stack

    def _start_locked(self) -> tuple[SliceTicket, Future[np.ndarray], bool] | None:
        if self._running or self._closed:
            return None
        if self._pending is not None:
            ticket = self._pending
            self._pending = None
            self._running = True
            return ticket, self._executor.submit(self._read, ticket.ref, ticket.cancelled.is_set), False
        while self._prefetch_queue and self._stack is not None:
            idx = self._prefetch_queue.popleft()
            if 0 <= idx < len(self._stack.frames) and idx not in self._prefetched:
                ticket = SliceTicket(self._stack.frames[idx], idx, Event())
                self._prefetch_active = ticket
                self._running = True
                return ticket, self._executor.submit(self._read, ticket.ref, ticket.cancelled.is_set), True
        return None

    def _attach(self, task: tuple[SliceTicket, Future[np.ndarray], bool] | None) -> None:
        # add_done_callback may call synchronously if the future is already done.
        # Never attach while holding _lock.
        if task is not None:
            ticket, future, is_prefetch = task
            if is_prefetch:
                future.add_done_callback(lambda done: self._completed_prefetch(ticket, done))
            else:
                future.add_done_callback(lambda done: self._completed(ticket, done))

    def request(self, index: int) -> SliceTicket:
        notify = False
        with self._lock:
            if self._closed:
                raise RuntimeError("slice_requests_closed")
            if self._stack is None or type(index) is not int or index < 0 or index >= len(self._stack.frames):
                raise IndexError("slice_index_out_of_range")
            self._cancel_locked()
            ref = self._stack.frames[index]
            prefetched = self._prefetched.pop(index, None)
            if prefetched is not None and prefetched[0] == ref and self._is_current(ref):
                ticket = SliceTicket(ref, index, Event())
                self._active = ticket
                self._result = SliceResult(ticket, prefetched[1])
                task = None
                notify = True
            else:
                ticket = SliceTicket(ref, index, Event())
                self._active = self._pending = ticket
                task = self._start_locked()
        self._attach(task)
        if notify:
            self._notify_ready()
        return ticket

    def prefetch(self, indices: Sequence[int]) -> None:
        """Queue directional neighbor slice indices for idle background decoding."""
        with self._lock:
            if self._closed or self._stack is None:
                return
            total = len(self._stack.frames)
            self._prefetch_queue.clear()
            seen: set[int] = set()
            for idx in indices:
                if type(idx) is int and 0 <= idx < total and idx not in seen and idx not in self._prefetched:
                    if self._active is not None and self._active.stack_index == idx:
                        continue
                    seen.add(idx)
                    self._prefetch_queue.append(idx)
            task = self._start_locked()
        self._attach(task)

    def drain_prefetched(self) -> list[tuple[int, StackFrameRef, np.ndarray]]:
        """Drain ready prefetched slices whose underlying file stamp is still current."""
        ready: list[tuple[int, StackFrameRef, np.ndarray]] = []
        with self._lock:
            items = list(self._prefetched.items())
            self._prefetched.clear()
        for idx, (ref, pixels) in items:
            if self._is_current(ref):
                ready.append((idx, ref, pixels))
        return ready

    def _completed(self, ticket: SliceTicket, future: Future[np.ndarray]) -> None:
        # Future captures decoder exceptions, which may contain private file/header
        # details. Never expose/log the exception, only a stable error code.
        failed = future.cancelled() or future.exception() is not None
        result = SliceResult(ticket, None, "slice_read_failed") if failed else SliceResult(ticket, future.result())
        notify = False
        with self._lock:
            self._running = False
            if not self._closed and self._active is ticket and not ticket.cancelled.is_set():
                self._result = result
                notify = True
            task = self._start_locked()
        self._attach(task)
        if notify:
            self._notify_ready()

    def _completed_prefetch(self, ticket: SliceTicket, future: Future[np.ndarray]) -> None:
        failed = future.cancelled() or future.exception() is not None
        pixels = None if failed else future.result()
        notify = False
        with self._lock:
            self._running = False
            if self._prefetch_active is ticket:
                self._prefetch_active = None
            if (
                pixels is not None
                and not self._closed
                and not ticket.cancelled.is_set()
                and self._stack is not None
                and 0 <= ticket.stack_index < len(self._stack.frames)
                and self._stack.frames[ticket.stack_index] == ticket.ref
            ):
                self._prefetched[ticket.stack_index] = (ticket.ref, pixels)
                self._prefetched.move_to_end(ticket.stack_index)
                while len(self._prefetched) > _PREFETCH_RESULT_MAX:
                    self._prefetched.popitem(last=False)
                notify = True
            task = self._start_locked()
        self._attach(task)
        if notify:
            self._notify_ready()

    def cancel(self) -> None:
        with self._lock:
            self._cancel_locked()

    def poll(self) -> SliceResult | None:
        """Take one result on the owner thread; a later request can still revoke it."""
        with self._lock:
            result, self._result = self._result, None
            return result

    def claim(self, result: SliceResult) -> bool:
        """Consume terminal result once; publish without yielding the owner thread."""
        with self._lock:
            if self._closed or self._active is not result.ticket or result.ticket.cancelled.is_set():
                return False
            self._active = None
            return result.error is not None or self._is_current(result.ticket.ref)

    def close(self) -> None:
        """Revoke all work without waiting for an uninterruptible native decode."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._cancel_locked()
            self._prefetched.clear()
            self._stack = None
            self._on_ready = None
        self._executor.shutdown(wait=False, cancel_futures=True)
