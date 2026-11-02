"""Migration tests for backup creation and restore after repair."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from echo_personal_tool.domain.services.gold_store import (
    load_gold,
    repair_gold_from_backup,
    save_gold,
    try_load_gold,
)


class TestBackupCreation:
    """Repair creates proper backups."""

    def test_backup_file_is_exact_copy(self, tmp_path: Path) -> None:
        gold_path = tmp_path / "lv_1.2.3.json"
        data = {
            "study_id": "1.2.3",
            "instance_path": "/data/test.dcm",
            "chamber": "LV",
            "frames": [
                {"frame_index": 10, "phase": "ED", "points": [[0, 0], [5, 0], [5, 5]]},
            ],
        }
        save_gold(gold_path, data)

        backup_path = gold_path.with_suffix(gold_path.suffix + ".bak")
        shutil.copy2(gold_path, backup_path)

        assert backup_path.exists()
        assert backup_path.read_text(encoding="utf-8") == gold_path.read_text(encoding="utf-8")

    def test_backup_is_valid_json(self, tmp_path: Path) -> None:
        gold_path = tmp_path / "lv_1.2.3.json"
        data = {
            "study_id": "1.2.3",
            "frames": [{"frame_index": 10, "phase": "ED", "points": [[0, 0], [5, 0], [5, 5]]}],
        }
        save_gold(gold_path, data)

        backup_path = gold_path.with_suffix(gold_path.suffix + ".bak")
        shutil.copy2(gold_path, backup_path)

        backup_json = json.loads(backup_path.read_text(encoding="utf-8"))
        assert backup_json["study_id"] == "1.2.3"

    def test_backup_preserves_all_frames(self, tmp_path: Path) -> None:
        gold_path = tmp_path / "lv_1.2.3.json"
        data = {
            "study_id": "1.2.3",
            "frames": [
                {"frame_index": 10, "phase": "ED", "points": [[0, 0], [5, 0], [5, 5]]},
                {"frame_index": 20, "phase": "ES", "points": [[0, 0], [4, 0], [4, 4]]},
            ],
        }
        save_gold(gold_path, data)

        backup_path = gold_path.with_suffix(gold_path.suffix + ".bak")
        shutil.copy2(gold_path, backup_path)

        backup = load_gold(backup_path)
        assert len(backup["frames"]) == 2

    def test_pre_repair_backup_created(self, tmp_path: Path) -> None:
        gold_path = tmp_path / "lv_1.2.3.json"
        data = {
            "study_id": "1.2.3",
            "frames": [{"frame_index": 10, "phase": "ED", "points": [[0, 0], [5, 0], [5, 5]]}],
        }
        save_gold(gold_path, data)

        # Simulate pre-repair backup
        stamp = gold_path.with_suffix(gold_path.suffix + ".pre-repair.bak")
        shutil.copy2(gold_path, stamp)

        assert stamp.exists()
        original_data = load_gold(stamp)
        assert original_data["study_id"] == "1.2.3"


class TestBackupRestore:
    """Backups can be properly restored."""

    def test_restore_from_backup(self, tmp_path: Path) -> None:
        backup_data = {
            "study_id": "1.2.3",
            "instance_path": "/data/test.dcm",
            "chamber": "LV",
            "frames": [
                {"frame_index": 10, "phase": "ED", "points": [[0, 0], [5, 0], [5, 5]]},
                {"frame_index": 20, "phase": "ES", "points": [[0, 0], [4, 0], [4, 4]]},
            ],
        }
        backup_path = tmp_path / "lv_1.2.3.json.bak"
        save_gold(backup_path, backup_data)

        # Current state is missing ES
        current_data = {
            "study_id": "1.2.3",
            "instance_path": "/data/test.dcm",
            "chamber": "LV",
            "frames": [
                {"frame_index": 10, "phase": "ED", "points": [[0, 0], [5, 0], [5, 5]]},
            ],
        }

        repaired, recovered = repair_gold_from_backup(current_data, backup_data)
        assert len(recovered) == 1
        assert recovered[0]["phase"] == "ES"

        # Save repaired version
        repaired_path = tmp_path / "lv_1.2.3.json"
        save_gold(repaired_path, repaired)

        # Verify restored file has both frames
        restored = load_gold(repaired_path)
        phases = {f["phase"] for f in restored["frames"]}
        assert phases == {"ED", "ES"}

    def test_restore_preserves_original_data(self, tmp_path: Path) -> None:
        backup_data = {
            "study_id": "1.2.3",
            "frames": [
                {"frame_index": 10, "phase": "ED", "points": [[0, 0], [5, 0], [5, 5]]},
            ],
        }
        current_data = {
            "study_id": "1.2.3",
            "frames": [
                {"frame_index": 10, "phase": "ED", "points": [[0, 0], [5, 0], [5, 5]]},
            ],
        }

        repaired, recovered = repair_gold_from_backup(current_data, backup_data)
        assert len(recovered) == 0
        assert len(repaired["frames"]) == 1
        assert repaired["frames"][0]["points"] == [[0, 0], [5, 0], [5, 5]]

    def test_full_backup_restore_cycle(self, tmp_path: Path) -> None:
        gold_path = tmp_path / "lv_1.2.3.json"
        original = {
            "study_id": "1.2.3",
            "instance_path": "/data/test.dcm",
            "chamber": "LV",
            "frames": [
                {"frame_index": 10, "phase": "ED", "points": [[0, 0], [5, 0], [5, 5]]},
                {"frame_index": 20, "phase": "ES", "points": [[0, 0], [4, 0], [4, 4]]},
            ],
        }
        save_gold(gold_path, original)

        # Create backup
        backup_path = gold_path.with_suffix(gold_path.suffix + ".bak")
        shutil.copy2(gold_path, backup_path)

        # Simulate data loss (remove ES frame)
        corrupted = {
            "study_id": "1.2.3",
            "instance_path": "/data/test.dcm",
            "chamber": "LV",
            "frames": [
                {"frame_index": 10, "phase": "ED", "points": [[0, 0], [5, 0], [5, 5]]},
            ],
        }
        save_gold(gold_path, corrupted)

        # Restore from backup
        backup = load_gold(backup_path)
        current = load_gold(gold_path)
        repaired, recovered = repair_gold_from_backup(current, backup)

        assert len(recovered) == 1
        save_gold(gold_path, repaired)

        # Verify full restoration
        restored = load_gold(gold_path)
        assert len(restored["frames"]) == 2


class TestMultipleBackupFormats:
    """Different backup naming conventions."""

    def test_bak_extension(self, tmp_path: Path) -> None:
        gold_path = tmp_path / "lv_1.2.3.json"
        bak_path = tmp_path / "lv_1.2.3.json.bak"
        data = {
            "study_id": "1.2.3",
            "frames": [{"frame_index": 0, "phase": "ED", "points": [[0, 0], [1, 0], [0, 1]]}],
        }
        save_gold(gold_path, data)
        shutil.copy2(gold_path, bak_path)
        assert bak_path.exists()
        assert try_load_gold(bak_path) is not None

    def test_tilde_backup(self, tmp_path: Path) -> None:
        gold_path = tmp_path / "lv_1.2.3.json"
        tilde_path = tmp_path / "lv_1.2.3.json~"
        data = {
            "study_id": "1.2.3",
            "frames": [{"frame_index": 0, "phase": "ED", "points": [[0, 0], [1, 0], [0, 1]]}],
        }
        save_gold(gold_path, data)
        shutil.copy2(gold_path, tilde_path)
        assert tilde_path.exists()
        assert try_load_gold(tilde_path) is not None

    def test_pre_repair_backup(self, tmp_path: Path) -> None:
        gold_path = tmp_path / "lv_1.2.3.json"
        pre_repair = tmp_path / "lv_1.2.3.json.pre-repair.bak"
        data = {
            "study_id": "1.2.3",
            "frames": [{"frame_index": 0, "phase": "ED", "points": [[0, 0], [1, 0], [0, 1]]}],
        }
        save_gold(gold_path, data)
        shutil.copy2(gold_path, pre_repair)
        assert pre_repair.exists()
        assert try_load_gold(pre_repair) is not None
