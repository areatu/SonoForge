"""Tests for natural instance filename sorting."""

from __future__ import annotations

from pathlib import Path

from echo_personal_tool.domain.models import InstanceMetadata, SeriesMetadata
from echo_personal_tool.infrastructure.instance_sort import (
    instance_filename_sort_key,
    natural_sort_key,
    sort_instances,
    sort_series_list,
)


def _instance(name: str) -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid=f"uid-{name}",
        series_uid="series",
        modality="US",
        number_of_frames=1,
        pixel_spacing=None,
        frame_time_ms=None,
        series_description="",
        path=Path(name),
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
