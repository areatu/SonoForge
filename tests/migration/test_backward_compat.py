"""Migration tests for backward compatibility with old gold annotation files."""

from __future__ import annotations

import json
from pathlib import Path

from echo_personal_tool.domain.services.gold_store import (
    load_gold,
    make_gold_frame,
    make_gold_study,
    save_gold,
    try_load_gold,
)


class TestOldFormatLoading:
    """Old gold annotation files can be loaded by current code."""

    def _write_old_gold(self, tmp_path: Path, data: dict) -> Path:
        path = tmp_path / "lv_old.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_minimal_old_format(self, tmp_path: Path) -> None:
        old = {
            "study_id": "1.2.3",
            "frames": [
                {
                    "frame_index": 10,
                    "phase": "ED",
                    "points": [[0, 0], [5, 0], [5, 5]],
                }
            ],
        }
        path = self._write_old_gold(tmp_path, old)
        loaded = load_gold(path)
        assert loaded["study_id"] == "1.2.3"
        assert len(loaded["frames"]) == 1
        assert loaded["frames"][0]["phase"] == "ED"

    def test_old_format_with_extra_fields(self, tmp_path: Path) -> None:
        old = {
            "study_id": "1.2.3",
            "version": "0.1",
            "legacy_field": True,
            "frames": [
                {
                    "frame_index": 10,
                    "phase": "ED",
                    "points": [[0, 0], [5, 0], [5, 5]],
                    "old_tag": "keep_me",
                }
            ],
        }
        path = self._write_old_gold(tmp_path, old)
        loaded = load_gold(path)
        assert loaded.get("version") == "0.1"
        assert loaded.get("legacy_field") is True
        assert loaded["frames"][0].get("old_tag") == "keep_me"

    def test_old_format_no_instance_path(self, tmp_path: Path) -> None:
        old = {
            "study_id": "1.2.3",
            "frames": [
                {"frame_index": 10, "phase": "ED", "points": [[0, 0], [5, 0], [5, 5]]}
            ],
        }
        path = self._write_old_gold(tmp_path, old)
        loaded = load_gold(path)
        assert loaded.get("instance_path") is None

    def test_try_load_old_format(self, tmp_path: Path) -> None:
        old = {
            "study_id": "1.2.3",
            "frames": [
                {"frame_index": 10, "phase": "ED", "points": [[0, 0], [5, 0], [5, 5]]}
            ],
        }
        path = self._write_old_gold(tmp_path, old)
        result = try_load_gold(path)
        assert result is not None
        assert result["study_id"] == "1.2.3"

    def test_old_format_with_frame_index_zero(self, tmp_path: Path) -> None:
        old = {
            "study_id": "1.2.3",
            "frames": [
                {"frame_index": 0, "phase": "ED", "points": [[0, 0], [5, 0], [5, 5]]}
            ],
        }
        path = self._write_old_gold(tmp_path, old)
        loaded = load_gold(path)
        assert loaded["frames"][0]["frame_index"] == 0


class TestNewAnnotationRequiredFields:
    """New annotations have all required fields."""

    def test_make_gold_frame_has_all_fields(self) -> None:
        frame = make_gold_frame(
            frame_index=10,
            phase="ED",
            points=[[0, 0], [5, 0], [5, 5]],
            mitral_annulus=[[0, 0], [5, 0]],
        )
        assert "frame_index" in frame
        assert "phase" in frame
        assert "points" in frame
        assert "mitral_annulus" in frame
        assert "chamber" in frame
        assert "source" in frame
        assert "annotated_at" in frame
        assert frame["chamber"] == "LV"

    def test_make_gold_frame_explicit_chamber(self) -> None:
        frame = make_gold_frame(
            frame_index=10,
            phase="ED",
            points=[[0, 0], [5, 0], [5, 5]],
            mitral_annulus=[[0, 0], [5, 0]],
            chamber="LA",
        )
        assert frame["chamber"] == "LA"

    def test_make_gold_study_has_all_fields(self) -> None:
        study = make_gold_study(
            study_id="1.2.3",
            instance_path="/data/test.dcm",
            pixel_spacing_mm=[0.15, 0.15],
        )
        assert "study_id" in study
        assert "instance_path" in study
        assert "pixel_spacing_mm" in study
        assert "chamber" in study
        assert "frames" in study
        assert study["chamber"] == "LV"
        assert study["frames"] == []

    def test_make_gold_study_explicit_chamber(self) -> None:
        study = make_gold_study(
            study_id="1.2.3",
            instance_path="/data/test.dcm",
            pixel_spacing_mm=[0.15, 0.15],
            chamber="RA",
        )
        assert study["chamber"] == "RA"

    def test_make_gold_study_with_optional(self) -> None:
        study = make_gold_study(
            study_id="1.2.3",
            instance_path="/data/test.dcm",
            pixel_spacing_mm=[0.15, 0.15],
            scanner_vendor="GE",
        )
        assert study.get("optional", {}).get("scanner_vendor") == "GE"

    def test_new_frame_validates_phase(self) -> None:
        frame = make_gold_frame(
            frame_index=0,
            phase="ED",
            points=[[0, 0], [1, 0], [0, 1]],
            mitral_annulus=[[0, 0], [1, 0]],
        )
        assert frame["phase"] in ("ED", "ES")

    def test_new_frame_has_timestamp(self) -> None:
        frame = make_gold_frame(
            frame_index=0,
            phase="ED",
            points=[[0, 0], [1, 0], [0, 1]],
            mitral_annulus=[[0, 0], [1, 0]],
        )
        assert frame["annotated_at"] is not None
        assert "T" in frame["annotated_at"]


class TestBackwardCompatRoundTrip:
    """Old format → load → save → load produces consistent results."""

    def test_old_format_round_trip(self, tmp_path: Path) -> None:
        old = {
            "study_id": "1.2.3",
            "frames": [
                {
                    "frame_index": 10,
                    "phase": "ED",
                    "points": [[0, 0], [5, 0], [5, 5]],
                    "old_field": "preserved",
                }
            ],
        }
        path = tmp_path / "lv_1.2.3.json"
        path.write_text(json.dumps(old), encoding="utf-8")

        # Load old format
        loaded = load_gold(path)
        assert loaded["frames"][0].get("old_field") == "preserved"

        # Save (with current code)
        path2 = tmp_path / "lv_1.2.3_v2.json"
        save_gold(path2, loaded)

        # Reload
        reloaded = load_gold(path2)
        assert reloaded["study_id"] == "1.2.3"
        assert reloaded["frames"][0].get("old_field") == "preserved"

    def test_new_format_survives_round_trip(self, tmp_path: Path) -> None:
        frame = make_gold_frame(
            frame_index=10,
            phase="ED",
            points=[[0, 0], [5, 0], [5, 5]],
            mitral_annulus=[[0, 0], [5, 0]],
        )
        study = make_gold_study(
            study_id="1.2.3",
            instance_path="/data/test.dcm",
            pixel_spacing_mm=[0.15, 0.15],
        )
        study["frames"].append(frame)

        path = tmp_path / "lv_1.2.3.json"
        save_gold(path, study)
        loaded = load_gold(path)
        assert loaded["study_id"] == "1.2.3"
        assert len(loaded["frames"]) == 1
        assert loaded["frames"][0]["chamber"] == "LV"
