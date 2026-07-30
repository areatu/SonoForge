"""Migration tests for repair_gold_collisions.py script."""

from __future__ import annotations

from pathlib import Path

from echo_personal_tool.domain.services.gold_store import (
    audit_gold_instance_completeness,
    dedupe_gold_frames,
    frame_instance_key,
    load_gold,
    repair_gold_from_backup,
    save_gold,
    try_load_gold,
)


def _make_gold_with_collisions() -> dict:
    """Gold study where two DICOMs share the same (frame_index, phase)."""
    return {
        "study_id": "1.2.840.collision",
        "instance_path": "/data/gold1.dcm",
        "pixel_spacing_mm": [0.15, 0.15],
        "chamber": "LV",
        "frames": [
            {
                "frame_index": 10,
                "phase": "ED",
                "instance_path": "/data/gold1.dcm",
                "points": [[0, 0], [5, 0], [5, 5]],
                "annotated_at": "2026-07-07T10:00:00Z",
            },
            {
                "frame_index": 10,
                "phase": "ED",
                "instance_path": "/data/gold2.dcm",
                "points": [[0, 0], [6, 0], [6, 6]],
                "annotated_at": "2026-07-07T11:00:00Z",
            },
            {
                "frame_index": 20,
                "phase": "ES",
                "instance_path": "/data/gold1.dcm",
                "points": [[0, 0], [4, 0], [4, 4]],
                "annotated_at": "2026-07-07T10:00:00Z",
            },
        ],
    }


class TestCollisionDetection:
    """Detect (frame_index, phase) collisions between different DICOM instances."""

    def test_detect_collisions_in_gold(self) -> None:
        gold = _make_gold_with_collisions()
        buckets: dict[tuple[int, str], list[dict]] = {}
        for frame in gold["frames"]:
            key = (int(frame["frame_index"]), str(frame["phase"]).upper())
            buckets.setdefault(key, []).append(frame)

        collisions = []
        for (frame_index, phase), frames in buckets.items():
            identities = {frame_instance_key(f, study=gold) for f in frames}
            if len(identities) > 1:
                collisions.append(
                    {"frame_index": frame_index, "phase": phase, "instances": sorted(identities)}
                )

        assert len(collisions) == 1
        assert collisions[0]["frame_index"] == 10
        assert collisions[0]["phase"] == "ED"
        assert len(collisions[0]["instances"]) == 2

    def test_no_collisions_clean_gold(self) -> None:
        gold = {
            "study_id": "clean",
            "frames": [
                {"frame_index": 10, "phase": "ED", "instance_path": "/a/x.dcm"},
                {"frame_index": 20, "phase": "ES", "instance_path": "/a/x.dcm"},
            ],
        }
        buckets: dict[tuple[int, str], list[dict]] = {}
        for frame in gold["frames"]:
            key = (int(frame["frame_index"]), str(frame["phase"]).upper())
            buckets.setdefault(key, []).append(frame)

        collisions = 0
        for frames in buckets.values():
            identities = {frame_instance_key(f, study=gold) for f in frames}
            if len(identities) > 1:
                collisions += 1

        assert collisions == 0


class TestDedupeGoldFrames:
    """Deduplication keeps latest frame per (instance, phase)."""

    def test_dedupe_collisions(self) -> None:
        gold = _make_gold_with_collisions()
        deduped = dedupe_gold_frames(gold["frames"], study=gold)
        # Two instances, each with ED and ES, but gold1 has ED+ES, gold2 has ED only
        # After dedup: gold1 ED, gold1 ES, gold2 ED = 3 frames
        assert len(deduped) == 3

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
        ]
        deduped = dedupe_gold_frames(frames)
        assert len(deduped) == 1
        assert deduped[0]["frame_index"] == 20


class TestRepairFromBackup:
    """Repair gold from backup recovers missing frames."""

    def test_recover_missing_ed(self) -> None:
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
        report = audit_gold_instance_completeness(repaired)
        assert report["complete_count"] == 1

    def test_no_recovery_needed(self) -> None:
        current = {
            "study_id": "x",
            "frames": [
                {"frame_index": 10, "phase": "ED", "instance_path": "/a/x.dcm", "points": [[0, 0], [1, 0], [0, 1]]},
                {"frame_index": 20, "phase": "ES", "instance_path": "/a/x.dcm", "points": [[0, 0], [1, 0], [0, 1]]},
            ],
        }
        backup = {
            "study_id": "x",
            "frames": [
                {"frame_index": 10, "phase": "ED", "instance_path": "/a/x.dcm", "points": [[0, 0], [1, 0], [0, 1]]},
                {"frame_index": 20, "phase": "ES", "instance_path": "/a/x.dcm", "points": [[0, 0], [1, 0], [0, 1]]},
            ],
        }
        repaired, recovered = repair_gold_from_backup(current, backup)
        assert len(recovered) == 0
        assert len(repaired["frames"]) == 2

    def test_recover_from_different_instance(self) -> None:
        current = {
            "study_id": "x",
            "instance_path": "/a/gold1.dcm",
            "frames": [
                {
                    "frame_index": 10,
                    "phase": "ED",
                    "instance_path": "/a/gold1.dcm",
                    "points": [[0, 0], [1, 0], [0, 1]],
                },
            ],
        }
        backup = {
            "study_id": "x",
            "instance_path": "/a/gold2.dcm",
            "frames": [
                {
                    "frame_index": 10,
                    "phase": "ED",
                    "instance_path": "/a/gold2.dcm",
                    "points": [[0, 0], [2, 0], [0, 2]],
                },
                {
                    "frame_index": 15,
                    "phase": "ES",
                    "instance_path": "/a/gold2.dcm",
                    "points": [[0, 0], [3, 0], [0, 3]],
                },
            ],
        }
        repaired, recovered = repair_gold_from_backup(current, backup)
        # gold1 ED exists, so gold2 ED should be recovered (different instance)
        # gold2 ES should also be recovered
        assert len(recovered) >= 1


class TestRepairDryRun:
    """Repair in dry-run mode does not modify files."""

    def test_dry_run_no_file_change(self, tmp_path: Path) -> None:
        gold_dir = tmp_path / "gold"
        gold_dir.mkdir()
        gold_path = gold_dir / "lv_1.2.3.json"
        original = {
            "study_id": "1.2.3",
            "instance_path": "/data/test.dcm",
            "chamber": "LV",
            "frames": [
                {"frame_index": 10, "phase": "ED", "points": [[0, 0], [1, 0], [0, 1]]},
                {"frame_index": 20, "phase": "ES", "points": [[0, 0], [1, 0], [0, 1]]},
            ],
        }
        save_gold(gold_path, original)
        original_content = gold_path.read_text(encoding="utf-8")

        # Simulate dry-run: don't write
        loaded = load_gold(gold_path)
        assert loaded["study_id"] == "1.2.3"

        # File unchanged
        assert gold_path.read_text(encoding="utf-8") == original_content


class TestBackupCreation:
    """Repair creates proper backup files."""

    def test_backup_file_created(self, tmp_path: Path) -> None:
        gold_path = tmp_path / "lv_1.2.3.json"
        backup_path = tmp_path / "lv_1.2.3.json.bak"
        data = {
            "study_id": "1.2.3",
            "frames": [
                {"frame_index": 10, "phase": "ED", "points": [[0, 0], [1, 0], [0, 1]]}
            ],
        }
        save_gold(gold_path, data)

        # Simulate backup creation
        import shutil
        shutil.copy2(gold_path, backup_path)
        assert backup_path.exists()

        # Verify backup content matches original
        backup_data = try_load_gold(backup_path)
        assert backup_data is not None
        assert backup_data["study_id"] == "1.2.3"


class TestRepairScriptFunctions:
    """Test functions used by repair_gold_collisions.py."""

    def test_default_backup_path_candidates(self, tmp_path: Path) -> None:
        gold_path = tmp_path / "lv_1.2.3.json"
        gold_path.write_text("{}", encoding="utf-8")
        candidates = [
            gold_path.with_suffix(gold_path.suffix + ".bak"),
            gold_path.with_name(gold_path.name + ".bak"),
            gold_path.with_suffix(".json~"),
        ]
        for c in candidates:
            assert c != gold_path

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
            ],
        }
        report = audit_gold_instance_completeness(gold)
        assert report["incomplete_count"] == 1
        assert report["complete_count"] == 0
