"""Behavioural tests for the start-page stored-record helpers (spec 474).

``stored_record_summaries`` was extracted from ``MainWindow`` so the window
class stays under its size ceiling.  It formats ``SavedRecordsListing`` data
into ``RecentStudySummary`` rows and touches no window state, so it can be
tested without Qt.
"""

from __future__ import annotations

from echo_personal_tool.application.saved_records import (
    STATUS_READABLE,
    STATUS_UNREADABLE,
    SavedRecordsListing,
    SavedRecordSummary,
)
from echo_personal_tool.presentation.start_page_helpers import stored_record_summaries


def _record(key: str, *, readable: bool = True, saved_at: str = "", count: int = 1) -> SavedRecordSummary:
    status = STATUS_READABLE if readable else STATUS_UNREADABLE
    return SavedRecordSummary(
        key=key,
        status=status,
        saved_at=saved_at,
        measurement_count=count,
    )


def test_none_listing_returns_empty() -> None:
    assert stored_record_summaries(None, set()) == []


def test_readable_records_produce_rows() -> None:
    listing = SavedRecordsListing(
        records=(
            _record("rec-1", saved_at="2026-11-20T10:00:00", count=3),
            _record("rec-2", saved_at="2026-11-21T12:00:00", count=1),
        )
    )
    rows = stored_record_summaries(listing, set())
    assert len(rows) == 2
    assert rows[0].key == "rec-1"
    assert rows[0].origin == "stored"
    assert rows[0].measurement_count == 3
    assert rows[1].key == "rec-2"


def test_unreadable_records_are_aggregated_into_single_row() -> None:
    listing = SavedRecordsListing(
        records=(
            _record("rec-1"),
            _record("rec-bad-1", readable=False),
            _record("rec-bad-2", readable=False),
            _record("rec-2"),
        )
    )
    rows = stored_record_summaries(listing, set())
    readable_keys = [r.key for r in rows if r.key != "stored-unreadable"]
    assert set(readable_keys) == {"rec-1", "rec-2"}
    unreadable_rows = [r for r in rows if r.key == "stored-unreadable"]
    assert len(unreadable_rows) == 1
    assert unreadable_rows[0].available is False


def test_seen_keys_are_skipped() -> None:
    listing = SavedRecordsListing(
        records=(
            _record("rec-1"),
            _record("rec-2"),
        )
    )
    rows = stored_record_summaries(listing, {"rec-1"})
    assert len(rows) == 1
    assert rows[0].key == "rec-2"


def test_failed_listing_produces_unavailable_row() -> None:
    listing = SavedRecordsListing(
        records=(_record("rec-1"),),
        failed=True,
        error="disk error",
    )
    rows = stored_record_summaries(listing, set())
    assert len(rows) == 1
    assert rows[0].key == "stored-unavailable"
    assert rows[0].available is False


def test_study_date_is_extracted_from_saved_at() -> None:
    listing = SavedRecordsListing(
        records=(_record("rec-1", saved_at="2026-11-20T10:00:00", count=2),)
    )
    rows = stored_record_summaries(listing, set())
    assert rows[0].study_date == "2026-11-20"


def test_empty_listing_no_rows() -> None:
    listing = SavedRecordsListing()
    assert stored_record_summaries(listing, set()) == []
