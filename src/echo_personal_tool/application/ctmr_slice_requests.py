"""Bounded, lazy CT/MR slice requests, independent of the GUI event loop."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from threading import Event, Lock

import numpy as np

from echo_personal_tool.domain.models.ctmr_stack import CtMrStack, StackFrameRef


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
    """One running read, one latest pending request and at most one result.

    select_stack/request/cancel/poll/claim must be serialized by the owning
    UI/event thread. Poll on that thread, then claim immediately before publishing
    success or error, without yielding. No callback runs UI code on a worker.
    Native decode cannot be interrupted; cancellation revokes publication.
    """

    def __init__(
        self,
        read: Callable[[StackFrameRef, Callable[[], bool]], np.ndarray],
        is_current: Callable[[StackFrameRef], bool],
    ) -> None:
        self._read, self._is_current = read, is_current
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ctmr-slice")
        self._lock = Lock()
        self._stack: CtMrStack | None = None
        self._active: SliceTicket | None = None
        self._pending: SliceTicket | None = None
        self._result: SliceResult | None = None
        self._running = False
        self._closed = False

    def _cancel_locked(self) -> None:
        if self._active is not None:
            self._active.cancelled.set()
        self._active = None
        self._pending = None
        self._result = None

    def select_stack(self, stack: CtMrStack | None) -> None:
        """Every selection, including reselecting the same stack, revokes old work."""
        with self._lock:
            if self._closed:
                raise RuntimeError("slice_requests_closed")
            self._cancel_locked()
            self._stack = stack

    def _start_locked(self) -> tuple[SliceTicket, Future[np.ndarray]] | None:
        if self._pending is None or self._running or self._closed:
            return None
        ticket = self._pending
        self._pending = None
        self._running = True
        return ticket, self._executor.submit(self._read, ticket.ref, ticket.cancelled.is_set)

    def _attach(self, task: tuple[SliceTicket, Future[np.ndarray]] | None) -> None:
        # add_done_callback may call synchronously if the future is already done.
        # Never attach while holding _lock.
        if task is not None:
            ticket, future = task
            future.add_done_callback(lambda done: self._completed(ticket, done))

    def request(self, index: int) -> SliceTicket:
        with self._lock:
            if self._closed:
                raise RuntimeError("slice_requests_closed")
            if self._stack is None or type(index) is not int or index < 0 or index >= len(self._stack.frames):
                raise IndexError("slice_index_out_of_range")
            self._cancel_locked()
            ticket = SliceTicket(self._stack.frames[index], index, Event())
            self._active = self._pending = ticket
            task = self._start_locked()
        self._attach(task)
        return ticket

    def _completed(self, ticket: SliceTicket, future: Future[np.ndarray]) -> None:
        # Future captures decoder exceptions, which may contain private file/header
        # details. Never expose/log the exception, only a stable error code.
        failed = future.cancelled() or future.exception() is not None
        result = SliceResult(ticket, None, "slice_read_failed") if failed else SliceResult(ticket, future.result())
        with self._lock:
            self._running = False
            if not self._closed and self._active is ticket and not ticket.cancelled.is_set():
                self._result = result
            task = self._start_locked()
        self._attach(task)

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
            self._stack = None
        self._executor.shutdown(wait=False, cancel_futures=True)
