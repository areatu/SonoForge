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
