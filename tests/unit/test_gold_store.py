"""Tests for gold annotation I/O (gold_store)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from echo_personal_tool.domain.services.gold_store import (
    audit_gold_instance_completeness,
    dedupe_gold_frames,
    frame_instance_key,
    frame_merge_key,
    gold_filename,
    load_gold,
    make_gold_frame,
    make_gold_study,
    merge_frame_into_gold,
    parse_chamber_from_gold_path,
    rebuild_manifest_from_gold_dir,
    remove_gold_frame,
    repair_gold_from_backup,
    save_gold,
    try_load_gold,
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

    def test_merge_updates_instance_path_from_different_file(self, sample_gold: dict) -> None:
        """When frame comes from a different file, top-level instance_path updates."""
        new_frame = make_gold_frame(
            frame_index=28,
            phase="ES",
            points=[[50.0, 60.0], [70.0, 80.0], [90.0, 100.0]],
            mitral_annulus=[[40.0, 50.0], [100.0, 50.0]],
            instance_path="/path/to/other.dcm",
        )
        merged = merge_frame_into_gold(sample_gold, new_frame)
        assert merged["instance_path"] == "/path/to/other.dcm"

    def test_merge_keeps_instance_path_from_same_file(self, sample_gold: dict) -> None:
        """When frame comes from same file, top-level instance_path unchanged."""
        new_frame = make_gold_frame(
            frame_index=28,
            phase="ES",
            points=[[50.0, 60.0], [70.0, 80.0], [90.0, 100.0]],
            mitral_annulus=[[40.0, 50.0], [100.0, 50.0]],
            instance_path="/path/to/dicom.dcm",
        )
        merged = merge_frame_into_gold(sample_gold, new_frame)
        assert merged["instance_path"] == "/path/to/dicom.dcm"

    def test_merge_same_frame_index_different_instances(self, sample_gold: dict) -> None:
        """Different DICOM files may share frame_index+phase without overwriting."""
        other_ed = make_gold_frame(
            frame_index=12,
            phase="ED",
            points=[[10.0, 20.0], [30.0, 40.0], [50.0, 60.0]],
            mitral_annulus=[[0.0, 0.0], [10.0, 0.0]],
            instance_path="/path/to/other.dcm",
        )
        merged = merge_frame_into_gold(sample_gold, other_ed)
        assert len(merged["frames"]) == 2
        keys = {frame_merge_key(f, study=merged) for f in merged["frames"]}
        assert keys == {("dicom.dcm", "ED"), ("other.dcm", "ED")}

    def test_merge_replaces_same_instance_phase(self, sample_gold: dict) -> None:
        """Re-saving ED on the same DICOM replaces the previous ED frame."""
        updated_ed = make_gold_frame(
            frame_index=99,
            phase="ED",
            points=[[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]],
            mitral_annulus=[[0.0, 0.0], [10.0, 0.0]],
            instance_path="/path/to/dicom.dcm",
        )
        merged = merge_frame_into_gold(sample_gold, updated_ed)
        assert len(merged["frames"]) == 1
        assert merged["frames"][0]["frame_index"] == 99

    def test_make_gold_frame_includes_instance_path(self) -> None:
        frame = make_gold_frame(
            frame_index=0,
            phase="ED",
            points=[[0, 0], [1, 1], [2, 2]],
            mitral_annulus=[[0, 0], [2, 0]],
            instance_path="/path/to/file.dcm",
        )
        assert frame["instance_path"] == "/path/to/file.dcm"


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


class TestGoldFilename:
    def test_lv_filename(self) -> None:
        assert gold_filename("1.2.3", "LV") == "lv_1.2.3.json"

    def test_la_filename(self) -> None:
        assert gold_filename("1.2.3", "LA") == "la_1.2.3.json"

    def test_la_lowercase_input(self) -> None:
        assert gold_filename("1.2.3", "la") == "la_1.2.3.json"


class TestParseChamberFromGoldPath:
    def test_la_prefix(self) -> None:
        assert parse_chamber_from_gold_path(Path("la_1.2.3.json")) == "LA"

    def test_lv_prefix(self) -> None:
        assert parse_chamber_from_gold_path(Path("lv_1.2.3.json")) == "LV"

    def test_no_prefix_defaults_lv(self) -> None:
        assert parse_chamber_from_gold_path(Path("1.2.3.json")) == "LV"


class TestMakeGoldFrameChamber:
    def test_default_chamber_lv(self) -> None:
        frame = make_gold_frame(
            frame_index=0,
            phase="ED",
            points=[[0, 0], [1, 1], [2, 2]],
            mitral_annulus=[[0, 0], [2, 0]],
        )
        assert frame["chamber"] == "LV"

    def test_explicit_chamber_la(self) -> None:
        frame = make_gold_frame(
            frame_index=0,
            phase="ES",
            points=[[0, 0], [1, 1], [2, 2]],
            mitral_annulus=[[0, 0], [2, 0]],
            chamber="LA",
        )
        assert frame["chamber"] == "LA"

    def test_chamber_uppercased(self) -> None:
        frame = make_gold_frame(
            frame_index=0,
            phase="ED",
            points=[[0, 0], [1, 1], [2, 2]],
            mitral_annulus=[[0, 0], [2, 0]],
            chamber="la",
        )
        assert frame["chamber"] == "LA"


class TestMakeGoldStudyChamber:
    def test_default_chamber_lv(self) -> None:
        study = make_gold_study(
            study_id="test",
            instance_path="/path/to.dcm",
            pixel_spacing_mm=[0.1, 0.1],
        )
        assert study["chamber"] == "LV"

    def test_explicit_chamber_la(self) -> None:
        study = make_gold_study(
            study_id="test",
            instance_path="/path/to.dcm",
            pixel_spacing_mm=[0.1, 0.1],
            chamber="LA",
        )
        assert study["chamber"] == "LA"


class TestValidateFrameChamber:
    def test_valid_chamber_la(self, tmp_path: Path) -> None:
        data = {
            "study_id": "x",
            "chamber": "LA",
            "frames": [
                {
                    "frame_index": 0,
                    "phase": "ES",
                    "chamber": "LA",
                    "points": [[0, 0], [1, 1], [2, 2]],
                }
            ],
        }
        path = tmp_path / "la.json"
        save_gold(path, data)
        loaded = load_gold(path)
        assert loaded["chamber"] == "LA"

    def test_invalid_chamber_rejected(self, tmp_path: Path) -> None:
        data = {
            "study_id": "x",
            "frames": [
                {
                    "frame_index": 0,
                    "phase": "ED",
                    "chamber": "XY",
                    "points": [[0, 0], [1, 1], [2, 2]],
                }
            ],
        }
        path = tmp_path / "bad_chamber.json"
        with pytest.raises(ValueError, match="chamber must be"):
            save_gold(path, data)


class TestTryLoadGold:
    def test_empty_file_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.json"
        path.write_text("", encoding="utf-8")
        assert try_load_gold(path) is None

    def test_invalid_json_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        assert try_load_gold(path) is None


class TestRebuildManifest:
    def test_rebuild_from_lv_and_la_gold(self, tmp_path: Path) -> None:
        gold_dir = tmp_path / "gold"
        gold_dir.mkdir()
        lv = {
            "study_id": "1.2.3",
            "instance_path": "/dicom/lv.dcm",
            "pixel_spacing_mm": [0.2, 0.2],
            "chamber": "LV",
            "frames": [
                {"frame_index": 10, "phase": "ED", "points": [[0, 0], [1, 0], [0, 1]]},
                {"frame_index": 20, "phase": "ES", "points": [[0, 0], [1, 0], [0, 1]]},
            ],
        }
        la = {
            "study_id": "1.2.3",
            "instance_path": "/dicom/la.dcm",
            "pixel_spacing_mm": [0.2, 0.2],
            "chamber": "LA",
            "frames": [
                {"frame_index": 21, "phase": "ES", "points": [[0, 0], [1, 0], [0, 1]]},
            ],
        }
        save_gold(gold_dir / "lv_1.2.3.json", lv)
        save_gold(gold_dir / "la_1.2.3.json", la)

        manifest = rebuild_manifest_from_gold_dir(tmp_path)
        assert len(manifest["studies"]) == 1
        entry = manifest["studies"][0]
        assert entry["study_id"] == "1.2.3"
        assert entry["ed_frame"] == 10
        assert entry["es_frame"] == 20


class TestRemoveGoldFrame:
    def test_remove_frame_updates_json(self, tmp_path: Path) -> None:
        gold_dir = tmp_path / "gold"
        gold_dir.mkdir()
        path = gold_dir / "lv_1.2.3.json"
        save_gold(
            path,
            {
                "study_id": "1.2.3",
                "instance_path": "/dicom/x.dcm",
                "pixel_spacing_mm": [0.2, 0.2],
                "chamber": "LV",
                "frames": [
                    {"frame_index": 10, "phase": "ED", "points": [[0, 0], [1, 0], [0, 1]]},
                    {"frame_index": 20, "phase": "ES", "points": [[0, 0], [1, 0], [0, 1]]},
                ],
            },
        )
        assert remove_gold_frame(path, frame_index=20, phase="ES") is True
        loaded = load_gold(path)
        assert len(loaded["frames"]) == 1
        assert loaded["frames"][0]["phase"] == "ED"

    def test_remove_last_frame_deletes_file(self, tmp_path: Path) -> None:
        path = tmp_path / "lv_1.2.3.json"
        save_gold(
            path,
            {
                "study_id": "1.2.3",
                "instance_path": "/dicom/x.dcm",
                "pixel_spacing_mm": [0.2, 0.2],
                "frames": [
                    {"frame_index": 10, "phase": "ED", "points": [[0, 0], [1, 0], [0, 1]]},
                ],
            },
        )
        assert remove_gold_frame(path, frame_index=10, phase="ED") is True
        assert not path.exists()


class TestDedupeAndAudit:
    def test_dedupe_keeps_latest_per_instance_phase(self) -> None:
        frames = [
            {
                "frame_index": 10,
                "phase": "ED",
                "instance_path": "/a/gold1.dcm",
                "points": [[0, 0], [1, 0], [0, 1]],
                "annotated_at": "2026-07-07T10:00:00Z",
            },
            {
                "frame_index": 20,
                "phase": "ED",
                "instance_path": "/a/gold1.dcm",
                "points": [[0, 0], [1, 0], [0, 1]],
                "annotated_at": "2026-07-07T11:00:00Z",
            },
            {
                "frame_index": 10,
                "phase": "ED",
                "instance_path": "/a/gold2.dcm",
                "points": [[0, 0], [1, 0], [0, 1]],
                "annotated_at": "2026-07-07T09:00:00Z",
            },
        ]
        out = dedupe_gold_frames(frames)
        assert len(out) == 2
        by_inst = {frame_instance_key(f): f for f in out}
        assert by_inst["gold1.dcm"]["frame_index"] == 20

    def test_audit_incomplete_instances(self) -> None:
        gold = {
            "study_id": "x",
            "instance_path": "/a/gold1.dcm",
            "frames": [
                {
                    "frame_index": 1,
                    "phase": "ED",
                    "instance_path": "/a/gold1.dcm",
                    "points": [[0, 0], [1, 0], [0, 1]],
                },
                {
                    "frame_index": 2,
                    "phase": "ES",
                    "instance_path": "/a/gold2.dcm",
                    "points": [[0, 0], [1, 0], [0, 1]],
                },
            ],
        }
        report = audit_gold_instance_completeness(gold)
        assert report["complete_count"] == 0
        assert report["incomplete_count"] == 2

    def test_repair_from_backup_recovers_missing_phase(self) -> None:
        current = {
            "study_id": "x",
            "instance_path": "/a/gold1.dcm",
            "frames": [
                {
                    "frame_index": 5,
                    "phase": "ES",
                    "instance_path": "/a/gold1.dcm",
                    "points": [[0, 0], [1, 0], [0, 1]],
                },
            ],
        }
        backup = {
            "study_id": "x",
            "instance_path": "/a/gold1.dcm",
            "frames": [
                {
                    "frame_index": 12,
                    "phase": "ED",
                    "instance_path": "/a/gold1.dcm",
                    "points": [[0, 0], [1, 0], [0, 1]],
                },
                {
                    "frame_index": 5,
                    "phase": "ES",
                    "instance_path": "/a/gold1.dcm",
                    "points": [[0, 0], [1, 0], [0, 1]],
                },
            ],
        }
        repaired, recovered = repair_gold_from_backup(current, backup)
        assert len(recovered) == 1
        assert recovered[0]["phase"] == "ED"
        assert audit_gold_instance_completeness(repaired)["complete_count"] == 1
