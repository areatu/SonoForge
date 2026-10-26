"""Tests for pure clip-gallery mode grouping."""

from __future__ import annotations

from datetime import datetime

from echo_personal_tool.domain.models import InstanceMetadata, SeriesMetadata, StudyMetadata
from echo_personal_tool.presentation.thumbnail_gallery_groups import (
    canonical_clip_mode,
    group_thumbnail_instances,
)


def _instance(uid: str, clip_mode: str) -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid=uid,
        series_uid=f"series-{uid}",
        modality="US",
        number_of_frames=1,
        pixel_spacing=None,
        frame_time_ms=None,
        series_description="",
        clip_mode=clip_mode,
    )


def _study(uid: str, study_date: datetime, *instances: InstanceMetadata) -> StudyMetadata:
    series = SeriesMetadata(
        series_uid=f"series-{uid}",
        study_uid=uid,
        modality="US",
        description="",
        instances=instances,
    )
    return StudyMetadata(study_uid=uid, study_datetime=study_date, series=(series,))


def test_group_thumbnail_instances_uses_stable_mode_order_and_study_order() -> None:
    older = _study(
        "older",
        datetime(2026, 1, 1),
        _instance("old-2d", "2d"),
        _instance("old-doppler", "doppler"),
        _instance("old-m", "m_mode"),
    )
    newer = _study(
        "newer",
        datetime(2026, 1, 2),
        _instance("new-doppler", "doppler"),
        _instance("new-2d", "2d"),
    )

    groups = group_thumbnail_instances([older, newer])

    assert [group.mode for group in groups] == ["2d", "doppler", "m_mode"]
    assert [[instance.sop_instance_uid for instance, _study_index in group.instances] for group in groups] == [
        ["new-2d", "old-2d"],
        ["new-doppler", "old-doppler"],
        ["old-m"],
    ]
    assert [study_index for _instance, study_index in groups[0].instances] == [0, 1]


def test_unknown_clip_mode_falls_back_to_two_dimensional_group() -> None:
    assert canonical_clip_mode("unknown") == "2d"
    groups = group_thumbnail_instances([_study("one", datetime(2026, 1, 1), _instance("unknown", "unknown"))])
    assert len(groups) == 1
    assert groups[0].mode == "2d"
    assert groups[0].instances[0][0].sop_instance_uid == "unknown"


def test_chronological_order_crosses_mode_and_series_boundaries() -> None:
    from dataclasses import replace

    from echo_personal_tool.presentation.thumbnail_gallery_groups import ordered_thumbnail_instances

    clips = [
        replace(_instance("m-first", "m_mode"), created_at=datetime(2026, 1, 1, 10, 0)),
        replace(_instance("d-second", "doppler"), created_at=datetime(2026, 1, 1, 10, 1)),
        replace(_instance("2d-third", "2d"), created_at=datetime(2026, 1, 1, 10, 2)),
    ]
    study = _study("one", datetime(2026, 1, 1), *reversed(clips))
    ordered = ordered_thumbnail_instances([study])
    assert [instance.sop_instance_uid for instance, _ in ordered] == [clip.sop_instance_uid for clip in clips]
    assert [index for _, index in ordered] == [0, 0, 0]


def test_chronological_order_keeps_newest_study_first_and_skips_empty_studies() -> None:
    from echo_personal_tool.presentation.thumbnail_gallery_groups import ordered_thumbnail_instances

    older = _study("old", datetime(2026, 1, 1), _instance("old-m", "m_mode"))
    newer = _study("new", datetime(2026, 1, 2), _instance("new-d", "doppler"))
    empty = _study("empty", datetime(2026, 1, 3))
    ordered = ordered_thumbnail_instances([older, empty, newer])
    assert [(instance.sop_instance_uid, index) for instance, index in ordered] == [("new-d", 0), ("old-m", 1)]
