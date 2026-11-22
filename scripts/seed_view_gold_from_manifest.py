"""Seed a consolidated gold-annotations file from a view-recognition manifest.

Moves each sample's ``sample_id`` (the DICOM SOPInstanceUID) into the
``sop_instance_uid`` field expected by
:mod:`scripts.build_view_recognition_corpus`, and keeps ``instance_path`` so
the builder can match a specific file even when two files share a UID.

The output is the consolidated gold format consumed by ``--annotations``:

    {"records": [{"sop_instance_uid": ..., "instance_path": ...,
                  "view": "...", "frames": [...]}]}

Re-running is safe: an existing ``view`` (and any ``frames``) for the same
``(sop_instance_uid, instance_path)`` pair is preserved, so labels survive
manifest regeneration.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _key(record: dict) -> tuple[str, str]:
    return (
        str(record.get("sop_instance_uid", "")),
        str(record.get("instance_path", "")),
    )


def seed(manifest: dict, existing: dict | None) -> list[dict]:
    """Return gold records in manifest order, preserving existing labels."""
    previous = {_key(r): r for r in (existing or {}).get("records", [])}
    records: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for sample in manifest.get("samples", []):
        uid = str(sample.get("sample_id", ""))
        path = str(sample.get("source_path", ""))
        key = (uid, path)
        if key in seen:
            continue
        seen.add(key)
        prior = previous.get(key, {})
        record: dict = {
            "sop_instance_uid": uid,
            "instance_path": path,
            "file": Path(path).name,
            "view": str(prior.get("view", "")),
        }
        if "frames" in prior:
            record["frames"] = prior["frames"]
        records.append(record)
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("models/view_recognition_manifest.json"),
        help="View-recognition manifest JSON",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("models/gold.json"),
        help="Consolidated gold-annotations JSON to write",
    )
    args = parser.parse_args(argv)

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    existing = None
    if args.output.is_file():
        existing = json.loads(args.output.read_text(encoding="utf-8"))

    records = seed(manifest, existing)
    payload = {
        "schema_version": 1,
        "generated_from": str(args.manifest),
        "class_names": manifest.get("class_names", []),
        "records": records,
    }
    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    labelled = sum(1 for r in records if str(r.get("view", "")).strip())
    print(f"wrote {len(records)} records to {args.output} ({labelled} labelled)")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
