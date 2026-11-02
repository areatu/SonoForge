"""Logic tests for the A2 study browser (UI-7, redesign spec §4.10).

Pure module tests: the rows carry no patient identifiers (N-01), so every
case runs on the identifier-free summaries the builders produce.
"""

from __future__ import annotations

from datetime import date

from echo_personal_tool.presentation.study_browser import (
    PERIOD_MONTH,
    PERIOD_TODAY,
    PERIOD_WEEK,
    SOURCE_FOLDER,
    SOURCE_SERVER,
    SOURCE_STORED,
    STATUS_DRAFT,
    STATUS_NEW,
    STATUS_UNAVAILABLE,
    RecentStudySummary,
    display_title,
    filter_summaries,
    matches_period,
    matches_query,
    parse_study_date,
    source_counts,
    study_status,
)

TODAY = date(2026, 10, 20)


def _summary(key: str, **overrides) -> RecentStudySummary:
    fields = {"title": "2026-10-20 · Echocardiography", "study_date": "2026-10-20"}
    fields.update(overrides)
    return RecentStudySummary(key=key, **fields)


# ── dates ──────────────────────────────────────────────────────────────


def test_parse_study_date_accepts_iso_and_datetimes() -> None:
    assert parse_study_date("2026-10-20") == date(2026, 10, 20)
    assert parse_study_date("2026-10-20T09:41:00") == date(2026, 10, 20)


def test_parse_study_date_rejects_garbage() -> None:
    assert parse_study_date("") is None
    assert parse_study_date("20.10.2026") is None
    assert parse_study_date("2026-13-40") is None


def test_period_windows_are_inclusive_of_the_last_day() -> None:
    assert matches_period(date(2026, 10, 20), PERIOD_TODAY, TODAY)
    assert not matches_period(date(2026, 10, 19), PERIOD_TODAY, TODAY)
    assert matches_period(date(2026, 10, 14), PERIOD_WEEK, TODAY)  # 7th day back
    assert not matches_period(date(2026, 10, 13), PERIOD_WEEK, TODAY)
    assert matches_period(date(2026, 9, 21), PERIOD_MONTH, TODAY)  # 30th day back
    assert not matches_period(date(2026, 9, 20), PERIOD_MONTH, TODAY)


def test_undated_rows_pass_every_period() -> None:
    """Notice rows (failed/unreadable) carry no date and must stay visible."""
    assert matches_period(None, PERIOD_TODAY, TODAY)
    assert matches_period(None, PERIOD_MONTH, TODAY)


def test_future_dates_pass_their_window() -> None:
    """A scanner clock running ahead must not hide a fresh study."""
    assert matches_period(date(2026, 10, 21), PERIOD_TODAY, TODAY)


# ── status & title ─────────────────────────────────────────────────────


def test_status_draft_wins_over_availability() -> None:
    assert study_status(_summary("a", measurement_count=3)) == STATUS_DRAFT
    assert study_status(_summary("b", measurement_count=3, available=False, origin="stored")) == STATUS_DRAFT


def test_status_new_and_unavailable() -> None:
    assert study_status(_summary("a")) == STATUS_NEW
    assert study_status(_summary("b", available=False)) == STATUS_UNAVAILABLE


def test_display_title_drops_the_repeated_date() -> None:
    assert display_title(_summary("a")) == "Echocardiography"


def test_display_title_keeps_an_unstructured_date() -> None:
    row = _summary("a", study_date="")
    assert display_title(row) == "2026-10-20 · Echocardiography"


def test_display_title_keeps_a_mismatched_date() -> None:
    row = _summary("a", study_date="2026-10-19")
    assert display_title(row) == "2026-10-20 · Echocardiography"


# ── query ──────────────────────────────────────────────────────────────


def test_query_matches_title_details_date_and_folder_name() -> None:
    row = _summary("a", details="24 clips · local folder", folder="/data/Echo cases", origin="folder")
    assert matches_query(row, "echo")
    assert matches_query(row, "ECHO CASES")
    assert matches_query(row, "2026-10")
    assert matches_query(row, "clips")
    assert matches_query(row, "")


def test_query_terms_are_conjunctive() -> None:
    row = _summary("a", folder="/data/Echo cases", origin="folder")
    assert matches_query(row, "echo 2026")
    assert not matches_query(row, "echo orthanc")


def test_query_folds_cyrillic_case() -> None:
    row = _summary("a", title="2026-10-20 · ЭхоКГ трансторакальная")
    assert matches_query(row, "эхокг")


# ── filtering ──────────────────────────────────────────────────────────


def _rows() -> list[RecentStudySummary]:
    return [
        _summary("today-folder", origin="folder", folder="/data/Echo cases", clip_count=24),
        _summary(
            "week-server",
            title="2026-10-15 · Stress echo",
            study_date="2026-10-15",
            origin="server",
            clip_count=46,
        ),
        _summary(
            "old-draft",
            title="2026-09-01 · сохранённые измерения",
            study_date="2026-09-01",
            origin="stored",
            available=False,
            measurement_count=9,
        ),
        _summary(
            "today-draft",
            title="2026-10-20 · Echocardiography",
            origin="folder",
            folder="/data/Echo cases",
            clip_count=12,
            measurement_count=4,
        ),
        _summary(
            "stored-unavailable",
            title="Saved measurements are unavailable",
            study_date="",
            origin="stored",
            available=False,
        ),
    ]


def test_filter_by_source() -> None:
    rows = _rows()
    assert [r.key for r in filter_summaries(rows, source=SOURCE_FOLDER, today=TODAY)] == [
        "today-folder",
        "today-draft",
    ]
    assert [r.key for r in filter_summaries(rows, source=SOURCE_SERVER, today=TODAY)] == ["week-server"]
    assert [r.key for r in filter_summaries(rows, source=SOURCE_STORED, today=TODAY)] == [
        "old-draft",
        "stored-unavailable",
    ]


def test_filter_by_period_keeps_the_undated_notice() -> None:
    rows = _rows()
    assert [r.key for r in filter_summaries(rows, period=PERIOD_TODAY, today=TODAY)] == [
        "today-folder",
        "today-draft",
        "stored-unavailable",
    ]
    assert [r.key for r in filter_summaries(rows, period=PERIOD_WEEK, today=TODAY)] == [
        "today-folder",
        "week-server",
        "today-draft",
        "stored-unavailable",
    ]


def test_filter_drafts_only() -> None:
    assert [r.key for r in filter_summaries(_rows(), drafts_only=True, today=TODAY)] == [
        "old-draft",
        "today-draft",
    ]


def test_filter_available_only() -> None:
    assert [r.key for r in filter_summaries(_rows(), available_only=True, today=TODAY)] == [
        "today-folder",
        "week-server",
        "today-draft",
    ]


def test_filter_combines_query_and_preserves_order() -> None:
    rows = filter_summaries(_rows(), query="echo", today=TODAY)
    assert [r.key for r in rows] == ["today-folder", "week-server", "today-draft"]


# ── counters ───────────────────────────────────────────────────────────


def test_source_counts_cover_sidebar_and_quick_filters() -> None:
    counts = source_counts(_rows())
    assert counts == {"all": 5, "folder": 2, "server": 1, "stored": 2, "drafts": 2, "available": 3}


def test_source_counts_of_an_empty_set() -> None:
    assert source_counts(()) == {"all": 0, "folder": 0, "server": 0, "stored": 0, "drafts": 0, "available": 0}
