"""Migration tests for generate_manifest_from_gold.py."""

from __future__ import annotations

import json
from pathlib import Path

from echo_personal_tool.domain.services.gold_store import (
    rebuild_manifest_from_gold_dir,
    save_gold,
)


class TestManifestGeneration:
    """Test manifest generation from gold JSON files."""

    def _make_gold_dir(self, tmp_path: Path) -> Path:
        gold_dir = tmp_path / "gold"
        gold_dir.mkdir()
        return gold_dir

    def test_manifest_single_study(self, tmp_path: Path) -> None:
        gold_dir = self._make_gold_dir(tmp_path)
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
        save_gold(gold_dir / "lv_1.2.3.json", lv)

        manifest = rebuild_manifest_from_gold_dir(tmp_path)
        assert len(manifest["studies"]) == 1
        entry = manifest["studies"][0]
        assert entry["study_id"] == "1.2.3"
        assert entry["ed_frame"] == 10
        assert entry["es_frame"] == 20

    def test_manifest_lv_and_la_gold(self, tmp_path: Path) -> None:
        gold_dir = self._make_gold_dir(tmp_path)
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

    def test_manifest_empty_gold_dir(self, tmp_path: Path) -> None:
        gold_dir = tmp_path / "gold"
        gold_dir.mkdir()
        manifest = rebuild_manifest_from_gold_dir(tmp_path)
        assert manifest["studies"] == []

    def test_manifest_missing_gold_dir(self, tmp_path: Path) -> None:
        manifest = rebuild_manifest_from_gold_dir(tmp_path)
        assert manifest["studies"] == []
        # manifest.json should be created
        assert (tmp_path / "manifest.json").exists()

    def test_manifest_sorted_by_study_id(self, tmp_path: Path) -> None:
        gold_dir = self._make_gold_dir(tmp_path)
        for uid in ["3.2.1", "1.2.3", "2.2.3"]:
            lv = {
                "study_id": uid,
                "instance_path": f"/dicom/{uid}.dcm",
                "pixel_spacing_mm": [0.2, 0.2],
                "chamber": "LV",
                "frames": [
                    {"frame_index": 10, "phase": "ED", "points": [[0, 0], [1, 0], [0, 1]]},
                ],
            }
            save_gold(gold_dir / f"lv_{uid}.json", lv)

        manifest = rebuild_manifest_from_gold_dir(tmp_path)
        ids = [s["study_id"] for s in manifest["studies"]]
        assert ids == sorted(ids)

    def test_manifest_writes_file(self, tmp_path: Path) -> None:
        gold_dir = self._make_gold_dir(tmp_path)
        lv = {
            "study_id": "test",
            "instance_path": "/dicom/test.dcm",
            "pixel_spacing_mm": [0.15, 0.15],
            "chamber": "LV",
            "frames": [
                {"frame_index": 10, "phase": "ED", "points": [[0, 0], [1, 0], [0, 1]]},
            ],
        }
        save_gold(gold_dir / "lv_test.json", lv)
        rebuild_manifest_from_gold_dir(tmp_path)
        manifest_path = tmp_path / "manifest.json"
        assert manifest_path.exists()
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert len(data["studies"]) == 1

    def test_manifest_only_lv_frames_set_ed_es(self, tmp_path: Path) -> None:
        gold_dir = self._make_gold_dir(tmp_path)
        lv = {
            "study_id": "1.2.3",
            "instance_path": "/dicom/test.dcm",
            "chamber": "LV",
            "frames": [
                {"frame_index": 10, "phase": "ED", "points": [[0, 0], [1, 0], [0, 1]]},
                {"frame_index": 20, "phase": "ES", "points": [[0, 0], [1, 0], [0, 1]]},
            ],
        }
        save_gold(gold_dir / "lv_1.2.3.json", lv)
        manifest = rebuild_manifest_from_gold_dir(tmp_path)
        entry = manifest["studies"][0]
        assert entry["ed_frame"] == 10
        assert entry["es_frame"] == 20


class TestGenerateManifestScript:
    """Test generate_manifest_from_gold.py script logic directly."""

    def test_generate_manifest_from_gold_dir(self, tmp_path: Path) -> None:
        gold_dir = tmp_path / "gold"
        gold_dir.mkdir()
        lv = {
            "study_id": "1.2.3",
            "instance_path": "/dicom/lv.dcm",
            "pixel_spacing_mm": [0.2, 0.2],
            "chamber": "LV",
            "frames": [
                {
                    "frame_index": 10,
                    "phase": "ED",
                    "instance_path": "/dicom/lv.dcm",
                    "points": [[0, 0], [1, 0], [0, 1]],
                },
                {
                    "frame_index": 20,
                    "phase": "ES",
                    "instance_path": "/dicom/lv.dcm",
                    "points": [[0, 0], [1, 0], [0, 1]],
                },
            ],
        }
        save_gold(gold_dir / "lv_1.2.3.json", lv)

        output = tmp_path / "manifest.json"
        from scripts.generate_manifest_from_gold import generate_manifest

        manifest = generate_manifest(gold_dir, output)

        assert len(manifest["studies"]) == 1
        assert output.exists()

    def test_generate_manifest_excludes_instances(self, tmp_path: Path) -> None:
        gold_dir = tmp_path / "gold"
        gold_dir.mkdir()
        lv = {
            "study_id": "1.2.3",
            "instance_path": "/dicom/lv.dcm",
            "chamber": "LV",
            "frames": [
                {"frame_index": 10, "phase": "ED", "points": [[0, 0], [1, 0], [0, 1]]},
            ],
        }
        save_gold(gold_dir / "lv_1.2.3.json", lv)

        output = tmp_path / "manifest.json"
        from scripts.generate_manifest_from_gold import generate_manifest

        manifest = generate_manifest(gold_dir, output, exclude_instances={"lv.dcm"})

        assert len(manifest["studies"]) == 0

    def test_generate_manifest_only_lv_gold(self, tmp_path: Path) -> None:
        gold_dir = tmp_path / "gold"
        gold_dir.mkdir()
        # Create a la gold file (should be ignored by generate_manifest)
        la = {
            "study_id": "1.2.3",
            "instance_path": "/dicom/la.dcm",
            "chamber": "LA",
            "frames": [
                {"frame_index": 21, "phase": "ES", "points": [[0, 0], [1, 0], [0, 1]]},
            ],
        }
        save_gold(gold_dir / "la_1.2.3.json", la)

        output = tmp_path / "manifest.json"
        from scripts.generate_manifest_from_gold import generate_manifest

        manifest = generate_manifest(gold_dir, output)

        # Only lv_*.json files are processed
        assert len(manifest["studies"]) == 0
