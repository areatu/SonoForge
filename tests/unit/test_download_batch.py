"""Unit tests for the Qt-free download batch owner (S-03a, #530)."""

from __future__ import annotations

from datetime import datetime

from echo_personal_tool.application.download_batch import (
    DownloadBatch,
    DownloadBatchAttribute,
    DownloadBatchSnapshot,
)
from echo_personal_tool.domain.models import StudyMetadata


def _study(uid: str) -> StudyMetadata:
    return StudyMetadata(study_uid=uid, study_datetime=datetime(2024, 1, 1), series=())


def test_start_resets_a_previous_batch() -> None:
    batch = DownloadBatch()
    batch.start([("old", ["s"])])
    batch.record_completed()
    batch.add_studies([_study("old")])
    batch.add_warning("old warning")
    batch.set_result("old-session", "old")
    batch.finish()

    batch.start([("new", ["s1"]), ("other", ["s2"])])

    assert batch.active is True
    assert batch.queue == [("new", ["s1"]), ("other", ["s2"])]
    assert batch.completed == 0
    assert batch.failed == 0
    assert batch.total == 2
    assert batch.warnings == []
    assert batch.downloaded_studies == []
    assert batch.result is None


def test_background_flag_survives_start_and_finish() -> None:
    batch = DownloadBatch()
    batch.start([("study", ["s"])])
    batch.request_background()
    batch.finish()

    assert batch.background_requested is True

    batch.start([("next", ["s"])])

    assert batch.background_requested is True


def test_failed_study_consumes_a_slot_and_is_not_saved() -> None:
    batch = DownloadBatch()
    batch.start([("one", ["s"]), ("two", ["s"])])
    batch.record_completed()
    batch.record_failed()

    assert batch.completed == 2
    assert batch.failed == 1
    assert batch.saved == 1
    assert batch.pending == 2  # start() keeps the queue until next_item()


def test_next_item_drains_the_queue() -> None:
    batch = DownloadBatch()
    batch.start([("one", ["s"]), ("two", ["s"])])

    assert batch.next_item() == ("one", ["s"])
    assert batch.pending == 1
    assert batch.next_item() == ("two", ["s"])
    assert batch.pending == 0


def test_snapshot_is_read_only_and_complete() -> None:
    batch = DownloadBatch()
    batch.start([("study", ["s"])])
    batch.record_completed()
    batch.add_studies([_study("study")])
    batch.add_warning("one series failed")
    batch.set_result("session", "study")
    batch.finish()

    snapshot = batch.snapshot()

    assert isinstance(snapshot, DownloadBatchSnapshot)
    assert snapshot.active is False
    assert snapshot.pending == 1
    assert snapshot.completed == 1
    assert snapshot.failed == 0
    assert snapshot.total == 1
    assert snapshot.saved == 1
    assert snapshot.downloaded_studies == (_study("study"),)
    assert snapshot.warnings == ("one series failed",)
    assert snapshot.result == ("session", "study")
    assert isinstance(snapshot.downloaded_studies, tuple)
    assert isinstance(snapshot.warnings, tuple)


def test_compatibility_attribute_reads_and_writes_the_owner() -> None:
    class Owner:
        downloading = DownloadBatchAttribute("active")

        def __init__(self) -> None:
            self.download_batch = DownloadBatch()

    owner = Owner()

    assert owner.downloading is False
    owner.downloading = True
    assert owner.downloading is True
    assert owner.download_batch.active is True
