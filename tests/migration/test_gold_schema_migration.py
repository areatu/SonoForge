"""Migration tests for gold annotation schema versioning."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from echo_personal_tool.domain.services.gold_store import load_gold, save_gold, try_load_gold


class TestGoldSchemaVersioning:
    """Gold annotations can be created with and without version fields."""

    def test_gold_with_version_field(self, tmp_path: Path) -> None:
        data = {
            "study_id": "1.2.840.versioned",
            "schema_version": "1.0",
            "instance_path": "/data/test.dcm",
            "pixel_spacing_mm": [0.15, 0.15],
            "chamber": "LV",
            "frames": [
                {
                    "frame_index": 10,
                    "phase": "ED",
                    "chamber": "LV",
                    "points": [[0, 0], [1, 0], [0, 1]],
                    "annotated_at": "2026-07-06T00:00:00Z",
                }
            ],
        }
        path = tmp_path / "lv_versioned.json"
        save_gold(path, data)
        loaded = load_gold(path)
        assert loaded["schema_version"] == "1.0"

    def test_gold_without_version_field(self, tmp_path: Path) -> None:
        data = {
            "study_id": "1.2.840.unversioned",
            "instance_path": "/data/test.dcm",
            "pixel_spacing_mm": [0.15, 0.15],
            "chamber": "LV",
            "frames": [
                {
                    "frame_index": 10,
                    "phase": "ED",
                    "chamber": "LV",
                    "points": [[0, 0], [1, 0], [0, 1]],
                    "annotated_at": "2026-07-06T00:00:00Z",
                }
            ],
        }
        path = tmp_path / "lv_unversioned.json"
        save_gold(path, data)
        loaded = load_gold(path)
        assert "schema_version" not in loaded

    def test_old_format_file_loads_correctly(self, tmp_path: Path) -> None:
        """Old-format files (no schema_version, no chamber) load correctly."""
        old_data = {
            "study_id": "1.2.840.old",
            "instance_path": "/data/old.dcm",
            "pixel_spacing_mm": [0.2, 0.2],
            "frames": [
                {
                    "frame_index": 5,
                    "phase": "ED",
                    "points": [[0, 0], [5, 0], [5, 5]],
                },
                {
                    "frame_index": 20,
                    "phase": "ES",
                    "points": [[0, 0], [4, 0], [4, 4]],
                },
            ],
        }
        path = tmp_path / "lv_1.2.840.old.json"
        path.write_text(json.dumps(old_data), encoding="utf-8")
        loaded = load_gold(path)
        assert loaded["study_id"] == "1.2.840.old"
        assert len(loaded["frames"]) == 2

    def test_extra_fields_preserved(self, tmp_path: Path) -> None:
        data = {
            "study_id": "1.2.840.extra",
            "instance_path": "/data/test.dcm",
            "schema_version": "2.0",
            "custom_field": "hello",
            "nested": {"key": "value"},
            "frames": [
                {
                    "frame_index": 1,
                    "phase": "ED",
                    "points": [[0, 0], [1, 0], [0, 1]],
                    "custom_tag": 42,
                }
            ],
        }
        path = tmp_path / "lv_extra.json"
        save_gold(path, data)
        loaded = load_gold(path)
        assert loaded["custom_field"] == "hello"
        assert loaded["nested"] == {"key": "value"}
        assert loaded["frames"][0]["custom_tag"] == 42

    def test_try_load_old_format(self, tmp_path: Path) -> None:
        old_data = {
            "study_id": "1.2.840.try_old",
            "frames": [
                {"frame_index": 0, "phase": "ED", "points": [[0, 0], [1, 0], [0, 1]]}
            ],
        }
        path = tmp_path / "lv_try_old.json"
        path.write_text(json.dumps(old_data), encoding="utf-8")
        result = try_load_gold(path)
        assert result is not None
        assert result["study_id"] == "1.2.840.try_old"


class TestSchemaMigrationEdgeCases:
    """Edge cases for schema migration scenarios."""

    def test_empty_frames_list(self, tmp_path: Path) -> None:
        data = {
            "study_id": "test",
            "schema_version": "1.0",
            "frames": [],
        }
        path = tmp_path / "empty_frames.json"
        save_gold(path, data)
        loaded = load_gold(path)
        assert loaded["frames"] == []

    def test_schema_version_survives_round_trip(self, tmp_path: Path) -> None:
        data = {
            "study_id": "test",
            "schema_version": "3.1",
            "frames": [
                {"frame_index": 0, "phase": "ED", "points": [[0, 0], [1, 0], [0, 1]]}
            ],
        }
        path = tmp_path / "version_roundtrip.json"
        save_gold(path, data)
        loaded = load_gold(path)
        assert loaded["schema_version"] == "3.1"

    def test_chamber_and_version_coexist(self, tmp_path: Path) -> None:
        data = {
            "study_id": "test",
            "schema_version": "1.2",
            "chamber": "LA",
            "frames": [
                {
                    "frame_index": 0,
                    "phase": "ES",
                    "chamber": "LA",
                    "points": [[0, 0], [1, 0], [0, 1]],
                }
            ],
        }
        path = tmp_path / "la_versioned.json"
        save_gold(path, data)
        loaded = load_gold(path)
        assert loaded["schema_version"] == "1.2"
        assert loaded["chamber"] == "LA"
