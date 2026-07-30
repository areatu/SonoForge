#!/usr/bin/env python3
"""Generate manifest.json from consolidated gold JSON (lv_*.json).

Reads all gold/*.json files, groups frames by instance_path,
and writes manifest.json with one entry per DICOM instance.

Usage:
    python scripts/generate_manifest_from_gold.py
    python scripts/generate_manifest_from_gold.py --gold-dir /path/to/gold --output manifest.json
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path


def generate_manifest(
    gold_dir: Path,
    output: Path,
    *,
    exclude_instances: set[str] | None = None,
) -> dict:
    by_instance: dict[str, dict] = {}
    exclude = exclude_instances or set()

    for gold_path in sorted(gold_dir.glob("lv_*.json")):
        with open(gold_path, encoding="utf-8") as f:
            data = json.load(f)

        study_id = data.get("study_id", "")
        for frame in data.get("frames", []):
            instance_path = frame.get("instance_path", "")
            if not instance_path:
                continue

            instance_name = Path(instance_path).name
            if instance_name in exclude:
                continue

            if instance_path not in by_instance:
                by_instance[instance_path] = {
                    "study_id": study_id,
                    "instance_path": instance_path,
                    "tags": {},
                }

            entry = by_instance[instance_path]
            phase = frame.get("phase", "")
            frame_index = frame.get("frame_index")
            if frame_index is None:
                continue

            chamber = frame.get("chamber", "LV").upper()
            if phase == "ED" and chamber == "LV":
                entry["ed_frame"] = frame_index
            elif phase == "ES" and chamber == "LV":
                entry["es_frame"] = frame_index

    manifest = {"studies": sorted(by_instance.values(), key=lambda s: s.get("instance_path", ""))}

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description="Generate manifest.json from consolidated gold JSON")
    parser.add_argument(
        "--gold-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "gold",
        help="Directory containing lv_*.json gold files (default: <repo>/gold)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "manifest.json",
        help="Output manifest.json path (default: <repo>/manifest.json)",
    )
    parser.add_argument(
        "--exclude",
        type=str,
        default="",
        help="Comma-separated instance filenames to exclude (e.g. gold38.dcm,gold71.dcm)",
    )
    args = parser.parse_args()

    if not args.gold_dir.is_dir():
        print(f"Error: gold dir not found: {args.gold_dir}", file=sys.stderr)
        sys.exit(1)

    exclude = {name.strip() for name in args.exclude.split(",") if name.strip()}
    if exclude:
        print(f"Excluding {len(exclude)} instances: {sorted(exclude)}")

    manifest = generate_manifest(args.gold_dir, args.output, exclude_instances=exclude)

    studies = manifest["studies"]
    complete = sum(1 for s in studies if "ed_frame" in s and "es_frame" in s)
    incomplete = len(studies) - complete

    print(f"Manifest written: {args.output}")
    print(f"  Total entries: {len(studies)}")
    print(f"  Complete (ED+ES): {complete}")
    if incomplete:
        print(f"  Incomplete: {incomplete}")
        for s in studies:
            if "ed_frame" not in s or "es_frame" not in s:
                missing = []
                if "ed_frame" not in s:
                    missing.append("ED")
                if "es_frame" not in s:
                    missing.append("ES")
                print(f"    {s['instance_path'].split('/')[-1]}: missing {', '.join(missing)}")


if __name__ == "__main__":
    main()
