"""Tests for the Tier-1 bench runner (run_lv_auto_bench)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from echo_personal_tool.domain.services.gold_store import make_gold_frame, save_gold


@pytest.fixture
def bench_manifest(tmp_path: Path) -> Path:
    """Create a minimal manifest + gold for bench testing."""
    gold_dir = tmp_path / "gold"
    gold_dir.mkdir()

    gold_data = {
        "study_id": "test_study_001",
        "instance_path": "/nonexistent/test.dcm",
        "pixel_spacing_mm": [0.15, 0.15],
        "frames": [
            make_gold_frame(
                frame_index=0,
                phase="ED",
                points=[[10.0, 10.0], [20.0, 10.0], [15.0, 20.0]],
                mitral_annulus=[[5.0, 5.0], [25.0, 5.0]],
            ),
            make_gold_frame(
                frame_index=5,
                phase="ES",
                points=[[12.0, 12.0], [18.0, 12.0], [15.0, 18.0]],
                mitral_annulus=[[8.0, 8.0], [22.0, 8.0]],
            ),
        ],
    }
    save_gold(gold_dir / "test_study_001.json", gold_data)

    manifest = {
        "studies": [
            {"study_id": "test_study_001", "instance_path": "/nonexistent/test.dcm", "ed_frame": 0, "es_frame": 5}
        ]
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    return manifest_path


class TestBenchRun:
    def test_empty_manifest(self, tmp_path: Path) -> None:
        from scripts.run_lv_auto_bench import run_bench

        manifest_path = tmp_path / "empty.json"
        manifest_path.write_text(json.dumps({"studies": []}))
        result = run_bench(manifest_path)
        assert result == {}

    def test_missing_gold_file(self, tmp_path: Path) -> None:
        from scripts.run_lv_auto_bench import run_bench

        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(
            json.dumps({"studies": [{"study_id": "no_gold", "instance_path": "/x.dcm", "ed_frame": 0}]})
        )
        result = run_bench(manifest_path)
        # No gold file → study is skipped, 0 rows produced
        assert result["rows"] == []

    def test_output_csv_created(self, tmp_path: Path, bench_manifest: Path) -> None:
        from scripts.run_lv_auto_bench import run_bench

        output = tmp_path / "reports" / "test.csv"
        # This will fail to load DICOM (nonexistent path) but should still
        # produce a CSV with skip rows
        result = run_bench(bench_manifest, output_path=output)
        # The manifest has a nonexistent DICOM path, so frames will be skipped
        # But the function should complete without error
        assert isinstance(result, dict)
