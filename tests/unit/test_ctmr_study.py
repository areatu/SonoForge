"""Routing a loaded study set to the CT/MR stack index (#557)."""

from dataclasses import replace
from datetime import datetime
from pathlib import Path

from echo_personal_tool.application.ctmr_study import build_ctmr_index, ct_mr_instance_paths
from echo_personal_tool.domain.models.metadata import InstanceMetadata, SeriesMetadata, StudyMetadata

pytest_plugins = ("tests.unit.test_ctmr_stacks",)


def _instance(path: Path, modality: str = "CT", sop: str | None = None) -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid=sop or f"1.2.{abs(hash(str(path))) % 100000}",
        series_uid="1.2.10.1",
        modality=modality,
        number_of_frames=1,
        pixel_spacing=(0.7, 0.4),
        frame_time_ms=None,
        series_description="",
        path=path,
    )


def _study(instances) -> StudyMetadata:
    return StudyMetadata(
        study_uid="1.2.10",
        study_datetime=datetime(2026, 1, 1),
        series=(SeriesMetadata("1.2.10.1", "1.2.10", "CT", "", tuple(instances)),),
    )


def test_builds_index_from_ct_mr_instances(make_file):
    a = make_file("z9.dcm", z=3)
    b = make_file("a1.dcm", z=-2)
    c = make_file("m5.dcm", z=0)
    studies = [_study([_instance(a), _instance(b), _instance(c)])]
    index = build_ctmr_index(studies)
    assert index is not None and len(index.stacks) == 1
    assert [frame.path.name for frame in index.stacks[0].frames] == ["a1.dcm", "m5.dcm", "z9.dcm"]


def test_ultrasound_study_returns_none(make_file):
    us = make_file("us.dcm")
    studies = [_study([replace(_instance(us), modality="US")])]
    assert build_ctmr_index(studies) is None


def test_ct_mr_paths_skip_us_and_duplicates(make_file):
    a = make_file("ct.dcm", z=0)
    us = make_file("us.dcm")
    studies = [_study([_instance(a), replace(_instance(us), modality="US"), _instance(a)])]
    assert ct_mr_instance_paths(studies) == [a]


def test_empty_study_returns_none():
    assert build_ctmr_index([]) is None


def test_no_paths_returns_none():
    studies = [_study([replace(_instance(Path("/nonexistent/a.dcm")), path=None)])]
    assert build_ctmr_index(studies) is None
