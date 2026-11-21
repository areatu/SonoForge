#!/usr/bin/env python3
"""Validate a view-recognition corpus manifest.

Loads a manifest JSON and runs the pure corpus checks plus an optional
reachability pass over the referenced source paths: every referenced DICOM
file must exist on disk (and — with ``--check-dicom`` — parse as a valid
DICOM header), so a corrupted or relocated corpus is caught before training.

Exit codes: 0 — valid, 1 — problems found, 2 — usage / load errors.

Usage:
    python scripts/validate_view_recognition_corpus.py corpus/manifest.json
    python scripts/validate_view_recognition_corpus.py corpus/manifest.json \
        --check-dicom
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure the project root is importable when the script runs from a checkout.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from echo_personal_tool.domain.models.view_recognition import (  # noqa: E402
    KNOWN_VIEWS,
    ViewRecognitionManifest,
)
from echo_personal_tool.domain.services.view_recognition_corpus import (  # noqa: E402
    summarize_corpus,
    validate_corpus,
)


def _check_dicom_sources(samples) -> list[str]:
    """Return per-sample problems for missing / unreadable source files."""
    import pydicom

    from echo_personal_tool.infrastructure.dicom_validator import (
        InvalidDicomError,
        validate_dicom_header,
    )

    problems: list[str] = []
    for sample in samples:
        path = Path(sample.source_path)
        if not path.is_file():
            problems.append(f"{sample.sample_id}: source file missing: {sample.source_path}")
            continue
        try:
            validate_dicom_header(path)
            pydicom.dcmread(path, stop_before_pixels=True, force=True)
        except (InvalidDicomError, OSError, EOFError) as exc:
            problems.append(f"{sample.sample_id}: unreadable DICOM: {exc}")
    return problems


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a view-recognition corpus manifest")
    parser.add_argument("manifest", type=Path, help="Path to the manifest JSON")
    parser.add_argument(
        "--check-dicom",
        action="store_true",
        help="Also verify each source file exists and parses as DICOM",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        with args.manifest.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        print(f"error: cannot load manifest {args.manifest}: {exc}", file=sys.stderr)
        return 2

    try:
        manifest = ViewRecognitionManifest.from_dict(data)
    except (KeyError, TypeError, ValueError) as exc:
        print(f"error: manifest schema invalid: {exc}", file=sys.stderr)
        return 2

    problems = validate_corpus(manifest.samples, class_names=manifest.class_names or KNOWN_VIEWS)
    if args.check_dicom:
        problems.extend(_check_dicom_sources(manifest.samples))

    summary = summarize_corpus(manifest.samples, class_names=manifest.class_names or KNOWN_VIEWS)
    print(f"manifest: {args.manifest}")
    print(f"samples: {len(manifest.samples)}")
    for view, counts in summary.items():
        print(f"  {view}: " + ", ".join(f"{k}={v}" for k, v in counts.items() if v))

    if problems:
        print(f"error: corpus invalid ({len(problems)} problems):", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("corpus valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
