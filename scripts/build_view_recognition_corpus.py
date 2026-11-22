#!/usr/bin/env python3
"""Build a view-recognition corpus manifest from a directory of DICOM files.

Scans a DICOM directory (recursively), reads each instance's header, and
derives one :class:`ViewRecognitionSample` per instance:

* ``sample_id``  — the SOP Instance UID (falling back to the file stem);
* ``source_path`` — the DICOM path;
* ``view`` — canonical view from the DICOM ``ProtocolName`` (0018,1140) via
  :func:`canonicalize_view`, or from an annotations JSON when given;
* ``metadata`` — the raw ``ProtocolName`` and the scanner ``Manufacturer``
  (0008,0070), captured for stratification and provenance.

Instances whose view cannot be determined are recorded with the reserved
``UNKNOWN`` label instead of being silently dropped, so the manifest keeps an
auditable count. The manifest is written with a deterministic, view-stratified
train/val split (see :func:`split_corpus`).

Usage:
    python scripts/build_view_recognition_corpus.py --dicom-dir /path/to/dicoms \
        --output corpus/manifest.json --val-ratio 0.2 --seed 42
    python scripts/build_view_recognition_corpus.py --dicom-dir ./dicoms \
        --annotations gold/annotations.json --output manifest.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path

import pydicom

# Ensure the project root is importable when the script runs from a checkout.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from echo_personal_tool.domain.models.view_recognition import (  # noqa: E402
    KNOWN_VIEWS,
    UNKNOWN_VIEW,
    ViewRecognitionSample,
    ViewSampleMetadata,
    canonicalize_view,
)
from echo_personal_tool.domain.services.view_recognition_corpus import (  # noqa: E402
    build_manifest,
    split_corpus,
    summarize_corpus,
    validate_corpus,
)
from echo_personal_tool.infrastructure.dicom_validator import (  # noqa: E402
    InvalidDicomError,
    validate_dicom_header,
)

#: DICOM tags used for corpus metadata.
_TAG_PROTOCOL_NAME = "ProtocolName"
_TAG_MANUFACTURER = "Manufacturer"


def _iter_dicom_files(dicom_dir: Path) -> list[Path]:
    """Return DICOM files under ``dicom_dir`` (case-insensitive suffixes)."""
    files: list[Path] = []
    for path in sorted(dicom_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() in {".dcm", ".dicom"}:
            files.append(path)
    return files


def _read_view_from_annotations(
    annotations_path: Path,
    sop_instance_uid: str,
    source_path: Path,
) -> str | None:
    """Look up the view for one instance in an annotations JSON.

    The JSON is the consolidated gold format: a list of records with
    ``instance_path`` / ``sop_instance_uid`` and a per-frame ``view``; the
    dominant view across the instance's frames wins. A record may instead carry
    one clip-level ``view`` (used when ``frames`` has no view labels). Returns
    ``None`` when the instance is not covered.
    """
    with annotations_path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    records = data.get("records", data if isinstance(data, list) else [])
    counts: Counter[str] = Counter()
    for record in records:
        rid = str(record.get("sop_instance_uid", ""))
        rpath = str(record.get("instance_path", ""))
        if rid and rid != sop_instance_uid:
            continue
        if rpath and rpath != str(source_path):
            continue
        frame_views = [
            str(frame.get("view", "")).strip()
            for frame in record.get("frames", [])
            if str(frame.get("view", "")).strip()
        ]
        if frame_views:
            counts.update(frame_views)
            continue
        # A record may carry a single clip-level view instead of per-frame
        # labels (the consolidated gold file seeded from the manifest).
        view = str(record.get("view", "")).strip()
        if view:
            counts[view] += 1
    if not counts:
        return None
    return counts.most_common(1)[0][0]


def collect_samples(
    dicom_dir: Path,
    *,
    annotations_path: Path | None = None,
) -> tuple[list[ViewRecognitionSample], list[str]]:
    """Scan ``dicom_dir`` and return ``(samples, diagnostics)``.

    ``diagnostics`` lists per-file notes (unreadable files, undetermined views)
    for the report; unreadable files are skipped, undetermined views become
    :data:`UNKNOWN_VIEW` samples.
    """
    samples: list[ViewRecognitionSample] = []
    problems: list[str] = []
    for path in _iter_dicom_files(dicom_dir):
        try:
            validate_dicom_header(path)
            dataset = pydicom.dcmread(path, stop_before_pixels=True, force=True)
        except (InvalidDicomError, OSError, EOFError) as exc:
            problems.append(f"skipped {path.name}: {exc}")
            continue

        protocol_name = str(dataset.get(_TAG_PROTOCOL_NAME, "") or "")
        manufacturer = str(dataset.get(_TAG_MANUFACTURER, "") or "")
        raw_view: str | None = None
        if annotations_path is not None:
            try:
                raw_view = _read_view_from_annotations(
                    annotations_path,
                    str(dataset.get("SOPInstanceUID", "") or ""),
                    path,
                )
            except (OSError, ValueError, KeyError, TypeError) as exc:
                problems.append(f"annotations error for {path.name}: {exc}")
        view = canonicalize_view(raw_view or protocol_name)
        if view == UNKNOWN_VIEW:
            problems.append(
                f"undetermined view for {path.name} "
                f"(protocol_name={protocol_name!r}, annotations={raw_view!r}); labelled UNKNOWN"
            )
        sop_uid = str(dataset.get("SOPInstanceUID", "") or "")
        sample_id = sop_uid or path.stem
        metadata = ViewSampleMetadata(protocol_name=protocol_name, vendor=manufacturer)
        samples.append(
            ViewRecognitionSample(
                sample_id=sample_id,
                source_path=str(path),
                view=view,
                metadata=metadata,
            )
        )
    return samples, problems


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a view-recognition corpus manifest from DICOM files")
    parser.add_argument("--dicom-dir", type=Path, required=True, help="DICOM directory to scan")
    parser.add_argument("--output", type=Path, required=True, help="Output manifest JSON path")
    parser.add_argument(
        "--annotations",
        type=Path,
        default=None,
        help="Optional annotations JSON (gold format) providing per-instance views",
    )
    parser.add_argument("--val-ratio", type=float, default=0.2, help="Validation ratio (default 0.2)")
    parser.add_argument("--seed", type=int, default=42, help="Split seed (default 42)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.dicom_dir.is_dir():
        print(f"error: DICOM directory not found: {args.dicom_dir}", file=sys.stderr)
        return 2

    samples, diagnostics = collect_samples(args.dicom_dir, annotations_path=args.annotations)
    if not samples:
        print("error: no DICOM instances found under the given directory", file=sys.stderr)
        return 2

    for diagnostic in diagnostics:
        print(f"warning: {diagnostic}", file=sys.stderr)

    train_samples, val_samples = split_corpus(samples, val_ratio=args.val_ratio, seed=args.seed)
    samples = [*(replace(s, split="train") for s in train_samples), *(replace(s, split="val") for s in val_samples)]

    manifest = build_manifest(samples, class_names=KNOWN_VIEWS)
    problems = validate_corpus(samples, class_names=KNOWN_VIEWS)
    if problems:
        print(f"error: corpus validation failed ({len(problems)} problems):", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    summary = summarize_corpus(samples, class_names=KNOWN_VIEWS)
    print(f"manifest written: {args.output}")
    print(f"samples: {len(samples)} (train={len(train_samples)}, val={len(val_samples)})")
    for view, counts in summary.items():
        print(f"  {view}: " + ", ".join(f"{k}={v}" for k, v in counts.items() if v))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
