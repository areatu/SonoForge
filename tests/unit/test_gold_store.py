"""Tests for gold annotation I/O (gold_store)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from echo_personal_tool.domain.services.gold_store import (
    load_gold,
    make_gold_frame,
    make_gold_study,
    merge_frame_into_gold,
    save_gold,
)


@pytest.fixture
def sample_gold() -> dict:
    return {
        "study_id": "1.2.840.test",
        "instance_path": "/path/to/dicom.dcm",
        "pixel_spacing_mm": [0.15, 0.15],
        "frames": [
            {
                "frame_index": 12,
                "phase": "ED",
                "view": "A4C",
                "points": [[100.0, 200.0], [110.0, 210.0], [120.0, 220.0]],
                "mitral_annulus": [[90.0, 150.0], [200.0, 150.0]],
                "source": "manual",
                "annotator": "test",
                "annotated_at": "2026-07-06T00:00:00Z",
            }
        ],
    }


@pytest.fixture
def gold_dir(tmp_path: Path) -> Path:
    return tmp_path / "gold"


class TestSaveLoadRoundTrip:
    def test_save_and_load_gold(self, gold_dir: Path, sample_gold: dict) -> None:
        path = gold_dir / "test_study.json"
        save_gold(path, sample_gold)
        loaded = load_gold(path)
        assert loaded["study_id"] == "1.2.840.test"
        assert len(loaded["frames"]) == 1
        assert loaded["frames"][0]["phase"] == "ED"

    def test_save_creates_parent_dirs(self, gold_dir: Path, sample_gold: dict) -> None:
        path = gold_dir / "sub" / "deep" / "test.json"
        save_gold(path, sample_gold)
        assert path.exists()

    def test_load_validates_required_keys(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({"frames": []}))
        with pytest.raises(ValueError, match="missing required key"):
            load_gold(path)

    def test_load_validates_frame_phase(self, tmp_path: Path) -> None:
        data = {
            "study_id": "x",
            "frames": [{"frame_index": 0, "phase": "XX", "points": [[0, 0], [1, 1], [2, 2]]}],
        }
        path = tmp_path / "bad_phase.json"
        path.write_text(json.dumps(data))
        with pytest.raises(ValueError, match="phase must be"):
            load_gold(path)

    def test_load_validates_frame_points(self, tmp_path: Path) -> None:
        data = {
            "study_id": "x",
            "frames": [{"frame_index": 0, "phase": "ED", "points": [[0, 0], [1, 1]]}],
        }
        path = tmp_path / "bad_points.json"
        path.write_text(json.dumps(data))
        with pytest.raises(ValueError, match="at least 3"):
            load_gold(path)


class TestMergeFrame:
    def test_merge_new_frame(self, sample_gold: dict) -> None:
        new_frame = make_gold_frame(
            frame_index=28,
            phase="ES",
            points=[[50.0, 60.0], [70.0, 80.0], [90.0, 100.0]],
            mitral_annulus=[[40.0, 50.0], [100.0, 50.0]],
        )
        merged = merge_frame_into_gold(sample_gold, new_frame)
        assert len(merged["frames"]) == 2

    def test_merge_replaces_same_frame_index_phase(self, sample_gold: dict) -> None:
        new_frame = make_gold_frame(
            frame_index=12,
            phase="ED",
            points=[[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]],
            mitral_annulus=[[0.0, 0.0], [10.0, 0.0]],
        )
        merged = merge_frame_into_gold(sample_gold, new_frame)
        assert len(merged["frames"]) == 1
        assert merged["frames"][0]["points"] == [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]]


class TestMakeGoldStudy:
    def test_make_study(self) -> None:
        study = make_gold_study(
            study_id="test",
            instance_path="/path/to.dcm",
            pixel_spacing_mm=[0.1, 0.1],
        )
        assert study["study_id"] == "test"
        assert study["frames"] == []

    def test_make_study_with_optional(self) -> None:
        study = make_gold_study(
            study_id="test",
            instance_path="/path/to.dcm",
            pixel_spacing_mm=[0.1, 0.1],
            scanner_vendor="GE",
        )
        assert study["optional"]["scanner_vendor"] == "GE"
