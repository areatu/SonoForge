"""Unit tests for media metadata mapping."""

from __future__ import annotations

from pathlib import Path

import pytest

from echo_personal_tool.infrastructure.media_metadata_mapper import (
    map_image_instance,
    map_mp4_instance,
    synthetic_instance_uid,
    synthetic_study_uid,
)
from tests.fixtures.generate_synthetic_media import write_synthetic_mp4


def test_synthetic_uids_are_stable(tmp_path: Path) -> None:
    folder = tmp_path / "study_a"
    folder.mkdir()
    uid1 = synthetic_instance_uid(folder, "clip.mp4")
    uid2 = synthetic_instance_uid(folder, "clip.mp4")
    assert uid1 == uid2
    assert uid1 != synthetic_instance_uid(folder, "other.mp4")
    assert synthetic_study_uid(folder) == synthetic_study_uid(folder)


def test_map_mp4_instance_reads_frame_metadata(tmp_path: Path) -> None:
    study_folder = tmp_path / "study"
    study_folder.mkdir()
    mp4_path = study_folder / "loop.mp4"
    write_synthetic_mp4(mp4_path, frame_count=7, fps=20.0)
    series_uid = "2.25.test-series"

    instance = map_mp4_instance(
        mp4_path,
        study_folder=study_folder,
        study_uid="1.2.3",
        series_uid=series_uid,
    )

    assert instance.media_format == "mp4"
    assert instance.number_of_frames == 7
    assert instance.frame_time_ms == pytest.approx(50.0)
    assert instance.pixel_spacing is None
    assert instance.series_uid == series_uid
    assert instance.path == mp4_path


def test_map_image_instance_single_frame(tmp_path: Path) -> None:
    study_folder = tmp_path / "study"
    study_folder.mkdir()
    image_path = study_folder / "frame.jpg"
    image_path.write_bytes(b"not-a-real-image")

    instance = map_image_instance(
        image_path,
        study_folder=study_folder,
        study_uid="1.2.3",
        series_uid="2.25.still",
        media_format="jpeg",
    )

    assert instance.media_format == "jpeg"
    assert instance.number_of_frames == 1
    assert instance.frame_time_ms is None
