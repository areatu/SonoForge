"""Qt-free logic of the A2 study browser (UI-7, redesign spec §4.10).

The start page of an empty tab is a study browser over the rows the app
already knows without loading anything: the current run's folder/server
history and the saved-measurement records.  What those rows may carry is
fixed by the privacy contracts N-01/S-09 — no patient identifiers and no
study UIDs are displayed — so the browser columns are description, study
date, clip count, saved-measurement count, draft status and source, even
though the approved A2 mockup (drawn from de-identified fixtures) labels
its first column with a patient name.

Everything here is pure: filtering, period matching, sidebar counters and
the status classification.  The widget in :mod:`.start_page` only renders
what this module computes.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

#: Period filter ids of the header segment control, in display order.
PERIOD_ALL = "all"
PERIOD_TODAY = "today"
PERIOD_WEEK = "7d"
PERIOD_MONTH = "30d"
PERIODS: tuple[str, ...] = (PERIOD_ALL, PERIOD_TODAY, PERIOD_WEEK, PERIOD_MONTH)

#: Source filter ids of the sidebar.  ``folder``/``server``/``stored`` are
#: the origins the summary builders already write; ``all`` adds «Недавние».
SOURCE_ALL = "all"
SOURCE_FOLDER = "folder"
SOURCE_SERVER = "server"
SOURCE_STORED = "stored"
SOURCES: tuple[str, ...] = (SOURCE_ALL, SOURCE_FOLDER, SOURCE_SERVER, SOURCE_STORED)

#: Status kinds of a browser row.  A row with saved measurements is a draft,
#: whatever its origin; a reopenable row without them is new; anything else
#: cannot be opened from the browser and says so.
STATUS_DRAFT = "draft"
STATUS_NEW = "new"
STATUS_UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class RecentStudySummary:
    """Safe display data for a recent study; patient identifiers are omitted.

    ``origin`` is ``"folder"``, ``"server"`` or ``"stored"`` (a saved-measurement
    record whose folder the current run does not know). ``folder`` is the local
    root to reopen for folder rows; ``study_uid`` lets the server loader
    preselect the study. Rows with ``available=False`` render greyed out and do
    not emit ``recent_study_requested`` (same pattern as missing places).

    ``study_date`` (ISO ``YYYY-MM-DD``), ``clip_count`` and
    ``measurement_count`` are the structured facts the A2 table columns and
    filters need; builders that do not know them leave the defaults and the
    browser shows «—» instead of inventing a value. ``measurement_count``
    counts the saved measurements matched to the study — for a folder/server
    row it is what turns the row into a draft.
    """

    key: str
    title: str
    details: str = ""
    origin: str = ""
    folder: str = ""
    study_uid: str = ""
    available: bool = True
    study_date: str = ""
    clip_count: int = 0
    measurement_count: int = 0
    #: Optional RAM-only name, rendered/searched only with explicit privacy opt-in.
    patient_surname: str = field(default="", repr=False)


def parse_study_date(value: str) -> date | None:
    """Parse the ISO date prefix of ``value``; ``None`` when there is none."""
    text = str(value or "").strip()[:10]
    if len(text) != 10:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def matches_period(study_date: date | None, period: str, today: date) -> bool:
    """Whether a study date falls inside a period filter.

    Undated rows pass every period: the browser cannot prove them old, and
    hiding notice rows (unreadable/failed records carry no date) behind a
    date filter would hide exactly the rows that need attention.  Future
    dates (scanner clock skew) pass the window they overshoot.
    """
    if period == PERIOD_ALL or study_date is None:
        return True
    if period == PERIOD_TODAY:
        return study_date >= today
    if period == PERIOD_WEEK:
        return study_date >= today - timedelta(days=6)
    if period == PERIOD_MONTH:
        return study_date >= today - timedelta(days=29)
    return True


def study_status(summary: RecentStudySummary) -> str:
    """Classify a row for the status column (draft / new / unavailable)."""
    if summary.measurement_count > 0:
        return STATUS_DRAFT
    if summary.available:
        return STATUS_NEW
    return STATUS_UNAVAILABLE


def display_title(summary: RecentStudySummary, *, show_patient_data: bool = False) -> str:
    """Title for the study column, without repeating the date column.

    The builders compose ``title`` as «дата · описание» (the Э5 row format,
    kept as the data contract).  The table has a date column of its own, so
    the leading date is dropped when it is the structured ``study_date``;
    a title whose date is not structured keeps it — it is the only copy.
    """
    if show_patient_data and summary.patient_surname:
        return summary.patient_surname
    title = str(summary.title or "")
    prefix = f"{summary.study_date} · " if summary.study_date else ""
    if prefix and title.startswith(prefix):
        return title[len(prefix) :] or title
    return title


def _search_haystack(summary: RecentStudySummary, *, show_patient_data: bool = False) -> str:
    folder_name = Path(summary.folder).name if summary.folder else ""
    return " ".join(
        part
        for part in (
            summary.patient_surname if show_patient_data else "",
            summary.title,
            summary.details,
            summary.study_date,
            folder_name,
            summary.folder,
        )
        if part
    ).casefold()


def matches_query(summary: RecentStudySummary, query: str, *, show_patient_data: bool = False) -> bool:
    """Case-insensitive text filter; every whitespace term must match."""
    terms = str(query or "").casefold().split()
    if not terms:
        return True
    haystack = _search_haystack(summary, show_patient_data=show_patient_data)
    return all(term in haystack for term in terms)


def filter_summaries(
    summaries: Iterable[RecentStudySummary],
    *,
    query: str = "",
    period: str = PERIOD_ALL,
    source: str = SOURCE_ALL,
    drafts_only: bool = False,
    available_only: bool = False,
    today: date | None = None,
    show_patient_data: bool = False,
) -> list[RecentStudySummary]:
    """Apply the browser filters in one pass, preserving builder order."""
    reference = today if today is not None else date.today()
    rows: list[RecentStudySummary] = []
    for summary in summaries:
        if source != SOURCE_ALL and summary.origin != source:
            continue
        if not matches_period(parse_study_date(summary.study_date), period, reference):
            continue
        if drafts_only and study_status(summary) != STATUS_DRAFT:
            continue
        if available_only and not summary.available:
            continue
        if not matches_query(summary, query, show_patient_data=show_patient_data):
            continue
        rows.append(summary)
    return rows


def source_counts(summaries: Iterable[RecentStudySummary]) -> dict[str, int]:
    """Sidebar counters over the unfiltered set.

    Keys: the four source ids (``all`` counts every row, including origins
    a future builder might add), plus ``drafts`` and ``available`` for the
    two quick filters.
    """
    counts = {SOURCE_ALL: 0, SOURCE_FOLDER: 0, SOURCE_SERVER: 0, SOURCE_STORED: 0, "drafts": 0, "available": 0}
    for summary in summaries:
        counts[SOURCE_ALL] += 1
        if summary.origin in counts:
            counts[summary.origin] += 1
        if study_status(summary) == STATUS_DRAFT:
            counts["drafts"] += 1
        if summary.available:
            counts["available"] += 1
    return counts
