#!/usr/bin/env python3
"""Explicit offline LOCAL export. Source pixels may contain PHI. No network/training."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402

from echo_personal_tool.domain.models.training_archive import ArchiveWriteError  # noqa: E402
from echo_personal_tool.domain.services.training_archive_export import (  # noqa: E402
    reviewed_atlas_record,
    split_archive_records,
)
from echo_personal_tool.infrastructure.training_archive import SqliteMeasurementArchive  # noqa: E402


def export_archive(source: Path, output: Path, reviewed: dict[str, int], seed: str) -> dict[str, int]:
    output = output.resolve()
    if output.exists() or any((root / ".git").exists() for root in (output, *output.parents)):
        raise ValueError("export requires a new external directory")
    archive = SqliteMeasurementArchive(source, read_only=True)
    records = split_archive_records(archive.records(), seed=seed)
    output.parent.mkdir(parents=True, exist_ok=True)
    reasons: Counter[str] = Counter()
    # Stage outside the repo and publish only a complete export.
    with tempfile.TemporaryDirectory(prefix=".archive-export-", dir=output.parent) as temporary:
        stage = Path(temporary) / "corpus"
        stage.mkdir(mode=0o700)
        atlas_by_view = {}
        for record in records:
            sid = record["sample_id"]
            if not isinstance(sid, str) or re.fullmatch(r"[0-9a-f]{64}", sid) is None:
                raise ValueError("invalid archive sample identity")
            np.save(stage / f"{sid}.npy", archive.frame(record["frame_hash"]), allow_pickle=False)
            record["image"] = f"{sid}.npy"
            record["reviewed"] = reviewed.get(sid) == record["revision"]
            record["strong_label"] = record["reviewed"] and record["geometry_kind"] == "trace"
            try:
                sample = reviewed_atlas_record(record, reviewed)
            except ValueError as exc:
                reason = str(exc)
                # Adapter errors are fixed codes, not input values/PHI.
                record["atlas_status"] = reason
                reasons[reason] += 1
            else:
                record["atlas_status"] = "reviewed_train_only"
                atlas_by_view.setdefault(record["view"], []).append(sample)
        # View-specific atlas_samples is consumed directly by fit_cardiac_atlas_pca.py.
        for view, samples in atlas_by_view.items():
            # Never use source view text as a filesystem path.
            from echo_personal_tool.domain.services.cardiac_atlas import ATLAS_VIEWS

            if view not in ATLAS_VIEWS:
                reasons["unsupported_atlas_view"] += len(samples)
                continue
            (stage / f"atlas-{view}-train.json").write_text(json.dumps({"atlas_samples": samples}, allow_nan=False))
        manifest = {
            "schema_version": 1,
            "format": "local_measurement_segmentation_corpus",
            "privacy": "LOCAL_NOT_ANONYMISED",
            "split_seed": seed,
            "missing_chambers": "UNKNOWN_NOT_NEGATIVE",
            "records": records,
            "atlas_exclusions": dict(reasons),
        }
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False))
        stage.rename(output)
    return {"exported": len(records), "reviewed": sum(r["reviewed"] for r in records), **dict(reasons)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--review", type=Path, help="JSON object: sample_id -> reviewed revision")
    parser.add_argument("--split-seed", default="sonoforge-local-v1")
    parser.add_argument("--acknowledge-local-phi", action="store_true", required=True)
    args = parser.parse_args(argv)
    try:
        reviewed = json.loads(args.review.read_text()) if args.review else {}
        if not isinstance(reviewed, dict) or any(
            not isinstance(k, str) or type(v) is not int or v < 1 for k, v in reviewed.items()
        ):
            raise ValueError("invalid review map")
        summary = export_archive(args.archive, args.output, reviewed, args.split_seed)
    except (OSError, ValueError, KeyError, TypeError, ArchiveWriteError) as exc:
        sys.stderr.write(f"Local archive export failed ({type(exc).__name__}); inspect local configuration\n")
        return 2
    print(json.dumps(summary, sort_keys=True))  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
