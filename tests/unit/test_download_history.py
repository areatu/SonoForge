"""Tests for the in-memory PACS download history (Э9, PR-C). No Qt."""

from __future__ import annotations

from datetime import datetime

import pytest

from echo_personal_tool.application.download_history import DownloadHistory
from echo_personal_tool.domain.models.metadata import InstanceMetadata, SeriesMetadata, StudyMetadata


def _instance(uid: str) -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid=uid,
        series_uid="s",
        modality="US",
        number_of_frames=4,
        pixel_spacing=None,
        frame_time_ms=33.3,
        series_description="A4C",
        path=None,
    )


def _study(uid: str, clips: int = 2, *, description: str = "A4C") -> StudyMetadata:
    series = SeriesMetadata(
        series_uid=f"{uid}.s",
        study_uid=uid,
        modality="US",
        description=description,
        instances=tuple(_instance(f"{uid}.{i}") for i in range(clips)),
    )
    return StudyMetadata(study_uid=uid, study_datetime=datetime(2026, 10, 1, 9), series=(series,))


def _clock(start: float = 100.0):
    now = [start]

    def tick() -> float:
        now[0] += 1.0
        return now[0]

    return tick


def test_record_keeps_metadata_and_clip_count() -> None:
    history = DownloadHistory(clock=_clock())
    entry = history.record(_study("1.2", clips=3))
    assert entry.study_uid == "1.2"
    assert entry.modality == "US"
    assert entry.description == "A4C"
    assert entry.clip_count == 3
    assert entry.study_datetime == datetime(2026, 10, 1, 9)


def test_newest_first_and_unique_by_study_uid() -> None:
    history = DownloadHistory(clock=_clock())
    history.record(_study("a"))
    history.record(_study("b"))
    history.record(_study("a", clips=5))
    uids = [record.study_uid for record in history.records()]
    assert uids == ["a", "b"]
    assert history.records()[0].clip_count == 5


def test_limit_drops_the_oldest_records() -> None:
    history = DownloadHistory(limit=2, clock=_clock())
    for uid in ("a", "b", "c"):
        history.record(_study(uid))
    assert [record.study_uid for record in history.records()] == ["c", "b"]


def test_description_is_truncated_and_study_without_series_is_allowed() -> None:
    history = DownloadHistory(clock=_clock())
    long_entry = history.record(_study("x", description="A" * 100))
    assert len(long_entry.description) == 64
    empty = StudyMetadata(study_uid="y", study_datetime=datetime(2026, 1, 1), series=())
    entry = history.record(empty)
    assert (entry.modality, entry.description, entry.clip_count) == ("", "", 0)


def test_record_holds_no_paths_or_patient_fields() -> None:
    history = DownloadHistory(clock=_clock())
    entry = history.record(_study("z"))
    assert set(vars(entry)) == {
        "study_uid",
        "study_datetime",
        "modality",
        "description",
        "clip_count",
        "downloaded_at",
    }


def test_clear_empties_the_history() -> None:
    history = DownloadHistory(clock=_clock())
    history.record(_study("a"))
    history.clear()
    assert len(history) == 0


def test_limit_must_be_positive() -> None:
    with pytest.raises(ValueError):
        DownloadHistory(limit=0)
