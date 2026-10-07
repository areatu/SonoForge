"""Tests for natural instance filename sorting."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from echo_personal_tool.domain.models import InstanceMetadata, SeriesMetadata
from echo_personal_tool.infrastructure.instance_sort import (
    instance_created_sort_key,
    instance_filename_sort_key,
    natural_sort_key,
    sort_instances,
    sort_instances_by,
    sort_series_list,
)


def _instance(name: str, created_at: datetime | None = None) -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid=f"uid-{name}",
        series_uid="series",
        modality="US",
        number_of_frames=1,
        pixel_spacing=None,
        frame_time_ms=None,
        series_description="",
        path=Path(name),
        created_at=created_at,
    )


def test_natural_sort_numeric_suffix() -> None:
    names = ["010.dcm", "002.dcm", "001.dcm"]
    assert sorted(names, key=natural_sort_key) == ["001.dcm", "002.dcm", "010.dcm"]


def test_sort_instances_by_filename() -> None:
    instances = [_instance("003.dcm"), _instance("001.dcm"), _instance("002.dcm")]
    ordered = sort_instances(instances)
    assert [i.path.name for i in ordered] == ["001.dcm", "002.dcm", "003.dcm"]


def test_sort_series_by_first_instance_filename() -> None:
    series = [
        SeriesMetadata(
            series_uid="c",
            study_uid="study",
            modality="US",
            description="C",
            instances=sort_instances([_instance("030.dcm")]),
        ),
        SeriesMetadata(
            series_uid="a",
            study_uid="study",
            modality="US",
            description="A",
            instances=sort_instances([_instance("010.dcm")]),
        ),
    ]
    ordered = sort_series_list(series)
    assert [s.instances[0].path.name for s in ordered] == ["010.dcm", "030.dcm"]


def test_sort_instances_by_creation_date_is_performed_order() -> None:
    instances = [
        _instance("003.dcm", datetime(2026, 1, 3)),
        _instance("001.dcm", datetime(2026, 1, 1)),
        _instance("002.dcm", datetime(2026, 1, 2)),
    ]
    ordered = sort_instances_by(instances, "created")
    assert [i.path.name for i in ordered] == ["001.dcm", "002.dcm", "003.dcm"]


def test_sort_instances_by_filename_mode_uses_natural_order() -> None:
    instances = [
        _instance("003.dcm", datetime(2026, 1, 1)),
        _instance("001.dcm", datetime(2026, 1, 3)),
        _instance("002.dcm", datetime(2026, 1, 2)),
    ]
    ordered = sort_instances_by(instances, "filename")
    assert [i.path.name for i in ordered] == ["001.dcm", "002.dcm", "003.dcm"]


def test_created_sort_keeps_same_second_in_filename_order() -> None:
    moment = datetime(2026, 1, 1, 10, 0, 0)
    instances = [_instance("003.dcm", moment), _instance("001.dcm", moment), _instance("002.dcm", moment)]
    ordered = sort_instances_by(instances, "created")
    assert [i.path.name for i in ordered] == ["001.dcm", "002.dcm", "003.dcm"]


def test_created_sort_puts_instances_without_date_last() -> None:
    instances = [_instance("001.dcm", None), _instance("002.dcm", datetime(2026, 1, 1))]
    ordered = sort_instances_by(instances, "created")
    assert [i.path.name for i in ordered] == ["002.dcm", "001.dcm"]


def test_instance_created_sort_key_without_date_or_path() -> None:
    inst = InstanceMetadata(
        sop_instance_uid="1.2.3",
        series_uid="series",
        modality="US",
        number_of_frames=1,
        pixel_spacing=None,
        frame_time_ms=None,
        series_description="",
        path=None,
    )
    assert instance_created_sort_key(inst)[0] is True


def test_instance_sort_key_fallback_to_uid() -> None:
    inst = InstanceMetadata(
        sop_instance_uid="1.2.3",
        series_uid="series",
        modality="US",
        number_of_frames=1,
        pixel_spacing=None,
        frame_time_ms=None,
        series_description="",
        path=None,
    )
    assert instance_filename_sort_key(inst)[0] == 1
