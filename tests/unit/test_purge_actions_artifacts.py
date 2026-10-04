"""Tests for the Actions artifact housekeeping policy (`scripts/purge_actions_artifacts.py`)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from scripts.purge_actions_artifacts import Artifact, parse_timestamp, select_for_deletion

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)


def make_artifact(artifact_id: int, name: str, days_ago: float, size_mb: float) -> Artifact:
    """Build an artifact created `days_ago` before NOW."""
    return Artifact(
        id=artifact_id,
        name=name,
        created_at=NOW - timedelta(days=days_ago),
        size_in_bytes=int(size_mb * 1024 * 1024),
    )


def select(artifacts: list[Artifact], **overrides: object) -> list[Artifact]:
    kwargs: dict[str, object] = {"older_than_days": 14, "keep_latest": 2, "max_deletes": 900, "now": NOW}
    kwargs.update(overrides)
    return select_for_deletion(artifacts, **kwargs)  # type: ignore[arg-type]


def test_keeps_the_newest_copies_of_every_name() -> None:
    artifacts = [
        make_artifact(1, "sonoforge-windows", 1, 300),
        make_artifact(2, "sonoforge-windows", 2, 300),
        make_artifact(3, "sonoforge-windows", 20, 300),
        make_artifact(4, "sonoforge-windows", 40, 300),
    ]

    selected = select(artifacts, keep_latest=2)

    assert [a.id for a in selected] == [4, 3]


def test_names_are_grouped_independently() -> None:
    artifacts = [
        make_artifact(1, "sonoforge-linux", 1, 40),
        make_artifact(2, "sonoforge-linux", 30, 40),
        make_artifact(3, "coverage-report", 3, 3),
        make_artifact(4, "coverage-report", 30, 3),
    ]

    selected = select(artifacts, keep_latest=1, older_than_days=7)

    assert {a.id for a in selected} == {2, 4}


def test_young_artifacts_survive_even_without_protected_copies() -> None:
    artifacts = [
        make_artifact(1, "dist", 1, 75),
        make_artifact(2, "dist", 30, 75),
    ]

    selected = select(artifacts, keep_latest=0, older_than_days=14)

    assert [a.id for a in selected] == [2]


def test_pages_artifact_is_never_touched() -> None:
    artifacts = [
        make_artifact(1, "github-pages", 400, 10),
        make_artifact(2, "dist", 400, 10),
    ]

    selected = select(artifacts, keep_latest=0, older_than_days=14)

    assert [a.id for a in selected] == [2]


def test_cap_deletes_the_biggest_artifacts_first() -> None:
    artifacts = [
        make_artifact(1, "sonoforge-linux", 30, 36),
        make_artifact(2, "sonoforge-macos-arm64", 30, 357),
        make_artifact(3, "sonoforge-windows", 30, 369),
        make_artifact(4, "dist", 30, 75),
    ]

    selected = select(artifacts, keep_latest=0, max_deletes=2)

    assert [a.id for a in selected] == [3, 2]


def test_parse_timestamp_reads_the_api_format() -> None:
    moment = parse_timestamp("2026-10-03T14:39:04Z")

    assert moment == datetime(2026, 10, 3, 14, 39, 4, tzinfo=UTC)
    assert parse_timestamp("2026-10-03T14:39:04.512Z").microsecond == 512000


def test_nothing_is_selected_when_nothing_ages_out() -> None:
    artifacts = [make_artifact(1, "dist", 2, 75), make_artifact(2, "dist", 1, 75)]

    assert select(artifacts, older_than_days=14) == []


def test_naive_timestamp_is_rejected() -> None:
    with pytest.raises(ValueError, match="Invalid isoformat"):
        parse_timestamp("yesterday")
