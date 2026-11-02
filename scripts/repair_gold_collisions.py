#!/usr/bin/env python3
"""Audit and repair LV/LA gold JSON files after (frame_index, phase) collisions.

Before the fix, ``merge_frame_into_gold`` deduplicated globally by
``(frame_index, phase)``, so multiple DICOM cines in one study could overwrite
each other. This script:

1. Reports per-DICOM ED/ES completeness.
2. Optionally deduplicates frames by ``(instance, phase)``.
3. Optionally merges missing frames from a backup JSON (copy made before edits).

Usage:
  PYTHONPATH=src python3 scripts/repair_gold_collisions.py gold/lv_*.json
  PYTHONPATH=src python3 scripts/repair_gold_collisions.py --apply --dedupe gold/lv_*.json
  PYTHONPATH=src python3 scripts/repair_gold_collisions.py --backup gold/lv_*.json.bak --apply gold/lv_*.json
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from echo_personal_tool.domain.services.gold_store import (  # noqa: E402
    audit_gold_instance_completeness,
    dedupe_gold_frames,
    frame_instance_key,
    frame_merge_key,
    load_gold,
    rebuild_manifest_from_gold_dir,
    repair_gold_from_backup,
    save_gold,
    try_load_gold,
)


def _default_backup_path(gold_path: Path) -> Path | None:
    candidates = [
        gold_path.with_suffix(gold_path.suffix + ".bak"),
        gold_path.with_name(gold_path.name + ".bak"),
        gold_path.with_suffix(".json~"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _display_instance(row: dict) -> str:
    have = row.get("have") or {}
    for meta in have.values():
        path = meta.get("instance_path")
        if path:
            return Path(str(path)).stem
    inst = str(row.get("instance", ""))
    if inst.endswith(".dcm"):
        return inst.replace(".dcm", "")
    return inst[:48] + ("…" if len(inst) > 48 else "")


def _print_audit(path: Path, gold: dict) -> None:
    report = audit_gold_instance_completeness(gold)
    print(f"\n{path}")
    print(
        f"  instances: {report['total_instances']}  "
        f"complete: {report['complete_count']}  incomplete: {report['incomplete_count']}"
    )
    if report["incomplete"]:
        print("  missing:")
        for row in report["incomplete"]:
            inst = _display_instance(row)
            missing = ",".join(row["missing"])
            have = row["have"]
            detail = []
            for phase, meta in sorted(have.items()):
                detail.append(f"{phase}@{meta.get('frame_index')}")
            print(f"    {inst}: need {missing}  (have {' '.join(detail)})")


def _detect_legacy_collisions(gold: dict) -> list[dict]:
    """Frames that share (frame_index, phase) but belong to different DICOMs."""
    buckets: dict[tuple[int, str], list[dict]] = {}
    for frame in gold.get("frames", []):
        key = (int(frame["frame_index"]), str(frame["phase"]).upper())
        buckets.setdefault(key, []).append(frame)

    collisions = []
    for (frame_index, phase), frames in sorted(buckets.items()):
        identities = {frame_instance_key(f, study=gold) for f in frames}
        if len(identities) > 1:
            collisions.append(
                {
                    "frame_index": frame_index,
                    "phase": phase,
                    "instances": sorted(identities),
                }
            )
    return collisions


def repair_file(
    gold_path: Path,
    *,
    apply: bool,
    dedupe: bool,
    backup_path: Path | None,
    rebuild_manifest: bool,
) -> int:
    gold = try_load_gold(gold_path)
    if gold is None:
        print(f"skip (missing/invalid): {gold_path}", file=sys.stderr)
        return 1

    _print_audit(gold_path, gold)
    collisions = _detect_legacy_collisions(gold)
    if collisions:
        print(f"  legacy (frame_index, phase) buckets with >1 instance: {len(collisions)}")
    else:
        print("  legacy collisions in file: 0 (already one row per bucket)")

    changed = False
    repaired = gold
    recovered: list[dict] = []

    if backup_path is not None:
        backup = try_load_gold(backup_path)
        if backup is None:
            print(f"  backup invalid: {backup_path}", file=sys.stderr)
            return 1
        repaired, recovered = repair_gold_from_backup(repaired, backup)
        if recovered:
            changed = True
            print(f"  recovered from backup: {len(recovered)} frame(s)")
            for frame in recovered:
                inst = frame_instance_key(frame, study=backup)
                print(f"    + {inst} {frame.get('phase')} frame={frame.get('frame_index')}")

    if dedupe:
        before = len(repaired.get("frames", []))
        deduped = dedupe_gold_frames(repaired.get("frames", []), study=repaired)
        if len(deduped) != before:
            changed = True
            print(f"  dedupe: {before} -> {len(deduped)} frames")
        repaired = {**repaired, "frames": deduped}

    after_report = audit_gold_instance_completeness(repaired)
    if after_report["incomplete_count"]:
        print("  still incomplete after repair (likely overwritten — re-annotate in UI):")
        for row in after_report["incomplete"]:
            inst = _display_instance(row)
            print(f"    {inst}: need {','.join(row['missing'])}")

    if not changed:
        print("  no file changes")
        return 0

    if not apply:
        print("  dry-run: pass --apply to write")
        return 0

    stamp = gold_path.with_suffix(gold_path.suffix + ".pre-repair.bak")
    shutil.copy2(gold_path, stamp)
    save_gold(gold_path, repaired)
    print(f"  saved {gold_path}  (backup -> {stamp.name})")

    if rebuild_manifest:
        rebuild_manifest_from_gold_dir(gold_path.parent.parent)
        print("  manifest.json rebuilt")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gold_files", nargs="+", type=Path, help="gold/lv_*.json paths")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write repaired JSON (default: audit only)",
    )
    parser.add_argument(
        "--dedupe",
        action="store_true",
        help="collapse duplicate (instance, phase) rows, keep latest annotated_at",
    )
    parser.add_argument(
        "--backup",
        type=Path,
        default=None,
        help="older JSON to merge missing (instance, phase) frames from",
    )
    parser.add_argument(
        "--auto-backup",
        action="store_true",
        help="use <file>.json.bak if --backup not set",
    )
    parser.add_argument(
        "--rebuild-manifest",
        action="store_true",
        help="rebuild manifest.json under gold root after --apply",
    )
    args = parser.parse_args()

    exit_code = 0
    for gold_path in args.gold_files:
        backup_path = args.backup
        if backup_path is None and args.auto_backup:
            backup_path = _default_backup_path(gold_path)
            if backup_path:
                print(f"auto-backup: {backup_path}")
        code = repair_file(
            gold_path,
            apply=args.apply,
            dedupe=args.dedupe,
            backup_path=backup_path,
            rebuild_manifest=args.rebuild_manifest,
        )
        exit_code = max(exit_code, code)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
