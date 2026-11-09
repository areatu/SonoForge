#!/usr/bin/env python3
"""Prepare, but never publish, audited metadata corrections for v0.4.0.

Inputs must be the original workflow artifacts and a fresh download of the
published full release. Original binaries and original attestations are never
changed. Amended records retain the original source and lock hash; a recovery
entry explicitly links them to the preserved original metadata. The caller must
attest the new SBOMs and verify the staged and published release before use.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

import build_record
import finalize_sbom
import package_matrix
import verify_release

VERSION = "0.4.0"
TAG = "v0.4.0"
COMMIT = "e91a770f3a9d4aefc08835b53ff8092a45e193a3"
RUNS = {"full": "42609751029", "presenter": "42609751136"}
BACKUP = "v0.4.0-original-release-evidence.zip"


def _check_file(path: Path, entry: dict) -> None:
    if not path.is_file():
        raise ValueError(f"missing {path}")
    digest, size = verify_release.file_digest_and_size(path)
    if digest != entry.get("sha256") or size != entry.get("size"):
        raise ValueError(f"digest or size mismatch: {path.name}")


def _lock_matches(record: dict, original_lock: bytes) -> bool:
    expected = hashlib.sha256(original_lock).hexdigest()
    crlf = hashlib.sha256(original_lock.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")).hexdigest()
    actual = (record.get("lock") or {}).get("sha256")
    if actual == expected:
        return True
    return (
        record.get("platform") == "windows-x64"
        and (record.get("source") or {}).get("runner_os") == "Windows"
        and actual == crlf
    )


def _original_record(record: dict, profile: str, platform: str, lock: bytes) -> None:
    problems = build_record.validate_record(record)
    source = record.get("source") or {}
    if problems or record.get("profile") != profile or record.get("platform") != platform:
        raise ValueError(f"invalid original record for {profile}/{platform}: {problems}")
    if record.get("release") != {"tag": TAG, "version": VERSION}:
        raise ValueError("original record belongs to another release")
    if (
        source.get("commit") != COMMIT
        or source.get("ref") != f"refs/tags/{TAG}"
        or source.get("run_id") != RUNS[profile]
    ):
        raise ValueError(f"unexpected original source for {profile}/{platform}")
    if source.get("run_attempt") != "1":
        raise ValueError(f"unexpected original build attempt for {profile}/{platform}")
    if not _lock_matches(record, lock):
        raise ValueError(f"unexpected original lock for {profile}/{platform}")


def prepare(original: Path, published: Path, output: Path, lock: Path, matrix_path: Path) -> None:
    """Build a deterministic staging directory; reject inconsistent original evidence."""
    if output.exists() and any(output.iterdir()):
        raise ValueError("output directory must be empty")
    output.mkdir(parents=True, exist_ok=True)
    matrix = package_matrix.load(matrix_path)
    assets = package_matrix.assets_for(matrix, VERSION, ["full", "presenter"])
    combos = sorted({(asset["profile"], asset["platform"]) for asset in assets})
    original_lock = lock.read_bytes()
    old_report = (original / "release-verification.json").read_bytes()
    report_data = json.loads(old_report)
    if report_data.get("kind") != "sonoforge.release-verification" or set(report_data.get("failed", [])) != {
        "sboms",
        "records",
    }:
        raise ValueError("unexpected original release verification result")
    backup: dict[str, bytes] = {"uv.lock": original_lock, "release-verification.json": old_report}
    for profile, platform in combos:
        record_name = package_matrix.record_name(matrix, profile, platform, VERSION)
        record_path = original / record_name
        original_record = record_path.read_bytes()
        record = json.loads(original_record)
        _original_record(record, profile, platform, original_lock)
        backup[record_name] = original_record
        own = [asset for asset in assets if (asset["profile"], asset["platform"]) == (profile, platform)]
        entries = {item["name"]: item for item in record["artifacts"]}
        if set(entries) != {asset["name"] for asset in own}:
            raise ValueError(f"unexpected artifact list in {record_name}")
        for asset in own:
            filename = asset["name"]
            _check_file(original / filename, entries[filename])
            if profile == "full" or (published / filename).exists():
                _check_file(published / filename, entries[filename])
            shutil.copyfile(original / filename, output / filename)
        smoke = record.get("smoke") or {}
        if any(asset["smoke"] != "none" for asset in own):
            if smoke.get("status") != "pass":
                raise ValueError(f"original smoke failed for {record_name}")
            evidence = original / smoke["evidence"]
            if build_record.sha256_of(evidence) != smoke.get("sha256") or not json.loads(evidence.read_text())["ok"]:
                raise ValueError(f"invalid original smoke evidence for {record_name}")
            backup[evidence.name] = evidence.read_bytes()
        expected_sboms = {asset["sbom"] for asset in own if asset["sbom"]}
        sboms = record.get("sboms") or []
        if {entry["name"] for entry in sboms} != expected_sboms or len(sboms) != len(expected_sboms):
            raise ValueError(f"unexpected SBOM list in {record_name}")
        for entry in sboms:
            original_sbom = original / entry["name"]
            _check_file(original_sbom, entry)
            original_bom = json.loads(original_sbom.read_text(encoding="utf-8"))
            if original_bom.get("serialNumber") != verify_release.expected_sbom_serial("areatu/SonoForge", VERSION):
                raise ValueError(f"unexpected original SBOM serial: {original_sbom.name}")
            backup[entry["name"]] = original_sbom.read_bytes()
            shutil.copyfile(original_sbom, output / entry["name"])
            finalize_sbom.finalize(output / entry["name"], VERSION)
            entry["sha256"], entry["size"] = verify_release.file_digest_and_size(output / entry["name"])
        if sboms:
            record["evidence_amendment"] = {
                "purpose": "SBOM release metadata correction; original binaries and build facts are unchanged",
                "original_record_sha256": hashlib.sha256(original_record).hexdigest(),
                "original_evidence_archive": BACKUP,
            }
            build_record.write(record, output / record_name)
        else:
            (output / record_name).write_bytes(original_record)
        # Existing release metadata may be the original or this exact correction,
        # e.g. after an interrupted run; anything else requires human review.
        if profile == "full":
            for filename in [record_name, *expected_sboms]:
                current = published / filename
                if current.exists() and current.read_bytes() not in (
                    backup[filename],
                    (output / filename).read_bytes(),
                ):
                    raise ValueError(f"published metadata unexpectedly changed: {filename}")
    # Preserve the original checksum manifest rather than regenerating it.
    shutil.copyfile(published / "SHA256SUMS", output / "SHA256SUMS")
    expected = package_matrix.checksum_expectations(matrix, VERSION, ["presenter"])["SHA256SUMS-presenter.txt"]
    (output / "SHA256SUMS-presenter.txt").write_text(
        "".join(f"{build_record.sha256_of(output / name)}  {name}\n" for name in sorted(expected)), encoding="utf-8"
    )
    with zipfile.ZipFile(output / BACKUP, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(backup.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content)
    for filename in (BACKUP, "SHA256SUMS-presenter.txt"):
        existing = published / filename
        if existing.exists() and existing.read_bytes() != (output / filename).read_bytes():
            raise ValueError(f"published recovery evidence unexpectedly changed: {filename}")
    report = verify_release.verify(output, tag=TAG, version=VERSION, profiles=["full", "presenter"], lock_path=lock)
    if not report.ok:
        raise ValueError(report.render())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--published", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--matrix", type=Path, default=package_matrix.DEFAULT_MATRIX)
    args = parser.parse_args()
    prepare(args.original, args.published, args.output, args.lock, args.matrix)


if __name__ == "__main__":
    main()
