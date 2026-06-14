"""Priority scheduler for preview thumbnail generation tasks."""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from enum import IntEnum
from itertools import count
from threading import RLock


class ThumbnailPriority(IntEnum):
    """Lower numeric value means higher scheduling priority."""

    P0_VISIBLE_SELECTED = 0
    P1_NEAR_VISIBLE = 1
    P2_BACKGROUND = 2


@dataclass(frozen=True, slots=True)
class ThumbnailTask:
    sop_instance_uid: str
    priority: ThumbnailPriority
    generation: int


class ThumbnailScheduler:
    """Maintains a deduplicated and bounded-dispatch task queue."""

    def __init__(self, *, max_in_flight: int = 2) -> None:
        if max_in_flight < 1:
            raise ValueError("max_in_flight must be >= 1")
        self._max_in_flight = max_in_flight
        self._heap: list[tuple[int, int, str, int]] = []
        self._queued_by_uid: dict[str, ThumbnailTask] = {}
        self._in_flight: set[str] = set()
        self._generation_by_uid: dict[str, int] = {}
        self._sequence = count()
        self._lock = RLock()

    def enqueue(self, uid: str, priority: ThumbnailPriority) -> bool:
        with self._lock:
            if not uid:
                raise ValueError("uid must be non-empty")
            if uid in self._in_flight:
                return False

            existing = self._queued_by_uid.get(uid)
            if existing is not None:
                if priority < existing.priority:
                    self._set_queued(uid, priority)
                    return True
                return False

            self._set_queued(uid, priority)
            return True

    def next_batch(self, limit: int) -> list[ThumbnailTask]:
        with self._lock:
            if limit <= 0:
                return []
            available_slots = self._max_in_flight - len(self._in_flight)
            if available_slots <= 0:
                return []

            to_take = min(limit, available_slots)
            dispatched: list[ThumbnailTask] = []
            while self._heap and len(dispatched) < to_take:
                _, _, uid, generation = heapq.heappop(self._heap)
                task = self._queued_by_uid.get(uid)
                if task is None or task.generation != generation:
                    continue
                del self._queued_by_uid[uid]
                self._in_flight.add(uid)
                dispatched.append(task)
            return dispatched

    def mark_done(self, uid: str) -> None:
        with self._lock:
            self._release_in_flight(uid)

    def mark_failed(self, uid: str) -> None:
        """Release in-flight state after a failed attempt without auto-retry."""
        with self._lock:
            self._release_in_flight(uid)

    def reprioritize(self, uids: list[str], priority: ThumbnailPriority) -> None:
        """Reprioritize queued UIDs and enqueue UIDs that are currently missing."""
        with self._lock:
            for uid in uids:
                if not uid or uid in self._in_flight:
                    continue
                existing = self._queued_by_uid.get(uid)
                if existing is None:
                    self._set_queued(uid, priority)
                    continue
                if existing.priority != priority:
                    self._set_queued(uid, priority)

    def _set_queued(self, uid: str, priority: ThumbnailPriority) -> None:
        generation = self._generation_by_uid.get(uid, 0) + 1
        self._generation_by_uid[uid] = generation
        task = ThumbnailTask(
            sop_instance_uid=uid,
            priority=priority,
            generation=generation,
        )
        self._queued_by_uid[uid] = task
        heapq.heappush(
            self._heap,
            (int(priority), next(self._sequence), uid, generation),
        )

    def _release_in_flight(self, uid: str) -> None:
        self._in_flight.discard(uid)
        self._prune_generation(uid)

    def _prune_generation(self, uid: str) -> None:
        if uid not in self._queued_by_uid and uid not in self._in_flight:
            self._generation_by_uid.pop(uid, None)
