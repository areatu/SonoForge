"""Unit tests for thumbnail task scheduling."""

from __future__ import annotations

import pytest

from echo_personal_tool.application.thumbnail_scheduler import (
    ThumbnailPriority,
    ThumbnailScheduler,
)


def test_scheduler_dispatches_p0_before_p1_and_p2() -> None:
    scheduler = ThumbnailScheduler(max_in_flight=4)
    scheduler.enqueue("uid-p2", ThumbnailPriority.P2_BACKGROUND)
    scheduler.enqueue("uid-p1", ThumbnailPriority.P1_NEAR_VISIBLE)
    scheduler.enqueue("uid-p0", ThumbnailPriority.P0_VISIBLE_SELECTED)

    batch = scheduler.next_batch(limit=3)

    assert [task.sop_instance_uid for task in batch] == ["uid-p0", "uid-p1", "uid-p2"]


def test_scheduler_deduplicates_same_uid() -> None:
    scheduler = ThumbnailScheduler(max_in_flight=2)

    first = scheduler.enqueue("uid-1", ThumbnailPriority.P2_BACKGROUND)
    duplicate_same_priority = scheduler.enqueue("uid-1", ThumbnailPriority.P2_BACKGROUND)
    upgraded_priority = scheduler.enqueue("uid-1", ThumbnailPriority.P0_VISIBLE_SELECTED)
    duplicate_while_in_flight: bool

    batch = scheduler.next_batch(limit=2)
    duplicate_while_in_flight = scheduler.enqueue(
        "uid-1", ThumbnailPriority.P0_VISIBLE_SELECTED
    )

    assert first is True
    assert duplicate_same_priority is False
    assert upgraded_priority is True
    assert len(batch) == 1
    assert batch[0].sop_instance_uid == "uid-1"
    assert batch[0].priority == ThumbnailPriority.P0_VISIBLE_SELECTED
    assert duplicate_while_in_flight is False


def test_scheduler_respects_max_in_flight_limit() -> None:
    scheduler = ThumbnailScheduler(max_in_flight=2)
    scheduler.enqueue("uid-1", ThumbnailPriority.P2_BACKGROUND)
    scheduler.enqueue("uid-2", ThumbnailPriority.P2_BACKGROUND)
    scheduler.enqueue("uid-3", ThumbnailPriority.P2_BACKGROUND)

    first_batch = scheduler.next_batch(limit=10)
    second_batch = scheduler.next_batch(limit=10)

    assert len(first_batch) == 2
    assert second_batch == []


def test_scheduler_marks_done_and_dispatches_next() -> None:
    scheduler = ThumbnailScheduler(max_in_flight=1)
    scheduler.enqueue("uid-1", ThumbnailPriority.P1_NEAR_VISIBLE)
    scheduler.enqueue("uid-2", ThumbnailPriority.P1_NEAR_VISIBLE)

    first_batch = scheduler.next_batch(limit=2)
    blocked_batch = scheduler.next_batch(limit=2)
    scheduler.mark_done("uid-1")
    next_batch = scheduler.next_batch(limit=2)

    assert [task.sop_instance_uid for task in first_batch] == ["uid-1"]
    assert blocked_batch == []
    assert [task.sop_instance_uid for task in next_batch] == ["uid-2"]


def test_scheduler_reprioritize_upgrades_existing_queued_uid() -> None:
    scheduler = ThumbnailScheduler(max_in_flight=3)
    scheduler.enqueue("uid-low", ThumbnailPriority.P2_BACKGROUND)
    scheduler.enqueue("uid-mid", ThumbnailPriority.P1_NEAR_VISIBLE)

    scheduler.reprioritize(
        ["uid-low"],
        ThumbnailPriority.P0_VISIBLE_SELECTED,
    )
    batch = scheduler.next_batch(limit=2)

    assert [task.sop_instance_uid for task in batch] == ["uid-low", "uid-mid"]
    assert batch[0].priority == ThumbnailPriority.P0_VISIBLE_SELECTED


def test_scheduler_rejects_invalid_max_in_flight() -> None:
    with pytest.raises(ValueError, match="max_in_flight must be >= 1"):
        ThumbnailScheduler(max_in_flight=0)


def test_scheduler_enqueue_rejects_empty_uid() -> None:
    scheduler = ThumbnailScheduler(max_in_flight=1)

    with pytest.raises(ValueError, match="uid must be non-empty"):
        scheduler.enqueue("", ThumbnailPriority.P0_VISIBLE_SELECTED)


def test_scheduler_mark_failed_releases_slot_without_auto_retry() -> None:
    scheduler = ThumbnailScheduler(max_in_flight=1)
    scheduler.enqueue("uid-fail", ThumbnailPriority.P0_VISIBLE_SELECTED)
    scheduler.enqueue("uid-next", ThumbnailPriority.P1_NEAR_VISIBLE)

    first_batch = scheduler.next_batch(limit=1)
    blocked_batch = scheduler.next_batch(limit=1)
    scheduler.mark_failed("uid-fail")
    next_batch = scheduler.next_batch(limit=1)
    final_batch = scheduler.next_batch(limit=1)

    assert [task.sop_instance_uid for task in first_batch] == ["uid-fail"]
    assert blocked_batch == []
    assert [task.sop_instance_uid for task in next_batch] == ["uid-next"]
    assert final_batch == []


def test_scheduler_reprioritize_unknown_uid_enqueues_it() -> None:
    scheduler = ThumbnailScheduler(max_in_flight=2)

    scheduler.reprioritize(["uid-new"], ThumbnailPriority.P0_VISIBLE_SELECTED)
    batch = scheduler.next_batch(limit=2)

    assert len(batch) == 1
    assert batch[0].sop_instance_uid == "uid-new"
    assert batch[0].priority == ThumbnailPriority.P0_VISIBLE_SELECTED


def test_scheduler_repeated_reprioritize_does_not_dispatch_duplicates() -> None:
    scheduler = ThumbnailScheduler(max_in_flight=3)
    scheduler.enqueue("uid-dup", ThumbnailPriority.P2_BACKGROUND)

    scheduler.reprioritize(["uid-dup"], ThumbnailPriority.P0_VISIBLE_SELECTED)
    scheduler.reprioritize(["uid-dup"], ThumbnailPriority.P0_VISIBLE_SELECTED)
    scheduler.reprioritize(["uid-dup"], ThumbnailPriority.P0_VISIBLE_SELECTED)
    batch = scheduler.next_batch(limit=3)
    second_batch = scheduler.next_batch(limit=3)

    assert len(batch) == 1
    assert batch[0].sop_instance_uid == "uid-dup"
    assert batch[0].priority == ThumbnailPriority.P0_VISIBLE_SELECTED
    assert second_batch == []
