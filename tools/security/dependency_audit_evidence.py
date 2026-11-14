#!/usr/bin/env python3
"""Write reproducible evidence for a locked dependency advisory scan (#563).

The CI gate already runs ``pip-audit`` against the runtime and dev contours of
``uv.lock``. A green log is not evidence a reviewer can inspect later, and it
does not say which lock, which tool version or which command produced it. This
tool folds the two machine-readable pip-audit reports into one small JSON file:

* the SHA-256 of ``uv.lock`` and of each exported requirements file;
* the ``pip-audit`` version and the exact commands (with artifact placeholders,
  never local paths);
* the UTC date of the scan and the findings, reduced to package/version/advisory
  identifiers and fix versions — no advisory prose, environment or host data;
* the reviewed exception register, validated so an exception without a reason
  or with an expired review date fails instead of silently aging.

The report is an artifact, not a substitute for ``pip-audit``: the blocking
runtime contour is still decided by ``pip-audit`` itself.

CLI::

    python tools/security/dependency_audit_evidence.py \
        --runtime-report pip-audit-runtime.json \
        --dev-report pip-audit-dev.json \
        --output dependency-audit-evidence.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import sys
from datetime import date, datetime, timezone
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Any

import tomllib

SCHEMA = "sonoforge.dependency-audit/1"
EXCEPTIONS_SCHEMA = "sonoforge.dependency-exceptions/1"
DEFAULT_EXCEPTIONS = Path("docs/security/dependency-exceptions.json")

RUNTIME_COMMAND = (
    "pip-audit -r <runtime-requirements> --no-deps --progress-spinner off --format json --output <runtime-report>"
)
DEV_COMMAND = "pip-audit -r <dev-requirements> --no-deps --progress-spinner off --format json --output <dev-report>"

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


class EvidenceError(RuntimeError):
    """The evidence inputs or the exception register cannot be trusted."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise EvidenceError(f"cannot read {Path(path).name}") from exc
    return digest.hexdigest()


def _read_json(path: Path, what: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"cannot read {what}: {Path(path).name}") from exc


def _parse_date(value: object, field: str) -> date:
    if not isinstance(value, str) or _ISO_DATE.fullmatch(value) is None:
        raise EvidenceError(f"{field} must be an ISO date (YYYY-MM-DD)")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise EvidenceError(f"{field} is not a valid date") from exc


def _finding(entry: dict[str, Any]) -> dict[str, Any]:
    vulnerability = entry.get("vulns") or ()
    if not isinstance(vulnerability, list):
        raise EvidenceError("pip-audit findings must be a list")
    findings: list[dict[str, Any]] = []
    for vuln in vulnerability:
        if not isinstance(vuln, dict) or not vuln.get("id"):
            raise EvidenceError("a pip-audit finding has no advisory id")
        findings.append(
            {
                "id": str(vuln["id"]),
                "aliases": sorted(str(alias) for alias in vuln.get("aliases") or ()),
                "fix_versions": sorted(str(fix) for fix in vuln.get("fix_versions") or ()),
            }
        )
    return {
        "package": str(entry.get("name") or ""),
        "version": str(entry.get("version") or ""),
        "findings": findings,
    }


def summarise_report(report: object) -> dict[str, Any]:
    """Reduce a pip-audit JSON report to stable, non-identifying facts."""
    if not isinstance(report, dict) or not isinstance(report.get("dependencies"), list):
        raise EvidenceError("pip-audit report has no dependencies list")
    dependencies = report["dependencies"]
    vulnerable = [_finding(entry) for entry in dependencies if entry.get("vulns")]
    vulnerable = [entry for entry in vulnerable if entry["findings"]]
    return {
        "scanned_packages": len(dependencies),
        "finding_count": sum(len(entry["findings"]) for entry in vulnerable),
        "vulnerable_packages": vulnerable,
    }


def _validate_entries(entries: object, *, kind: str, today: date) -> list[dict[str, Any]]:
    if not isinstance(entries, list):
        raise EvidenceError(f"exceptions.{kind} must be a list")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise EvidenceError(f"an exceptions.{kind} entry is not an object")
        identifier = str(entry.get("id") or "").strip()
        reason = str(entry.get("reason") or "").strip()
        if not identifier or identifier in seen:
            raise EvidenceError(f"exceptions.{kind} needs a unique id")
        if not reason:
            raise EvidenceError(f"exception {identifier} has no reason")
        review_by = _parse_date(entry.get("review_by"), f"exception {identifier} review_by")
        if review_by < today:
            raise EvidenceError(f"exception {identifier} is due for review ({review_by.isoformat()})")
        seen.add(identifier)
        result.append(
            {
                "id": identifier,
                "packages": sorted(str(package) for package in entry.get("packages") or ()),
                "scope": str(entry.get("scope") or ""),
                "reason": reason,
                "review_by": review_by.isoformat(),
            }
        )
    return result


def load_exceptions(path: Path, *, today: date) -> dict[str, Any]:
    """Validate the reviewed exception register and return its safe subset."""
    data = _read_json(path, "dependency exceptions")
    if not isinstance(data, dict) or data.get("schema") != EXCEPTIONS_SCHEMA:
        raise EvidenceError("dependency exceptions schema is not recognised")
    reviewed_on = _parse_date(data.get("reviewed_on"), "exceptions.reviewed_on")
    next_review_on = _parse_date(data.get("next_review_on"), "exceptions.next_review_on")
    if next_review_on < today:
        raise EvidenceError("the dependency exception register is due for review")
    if next_review_on < reviewed_on:
        raise EvidenceError("exceptions.next_review_on predates reviewed_on")
    return {
        "reviewed_on": reviewed_on.isoformat(),
        "next_review_on": next_review_on.isoformat(),
        "vulnerabilities": _validate_entries(data.get("vulnerabilities", []), kind="vulnerabilities", today=today),
        "licenses": _validate_entries(data.get("licenses", []), kind="licenses", today=today),
    }


def _lock_facts(lock_path: Path) -> dict[str, Any]:
    try:
        lock = tomllib.loads(Path(lock_path).read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise EvidenceError("cannot read uv.lock") from exc
    packages = lock.get("package")
    if not isinstance(packages, list) or not packages:
        raise EvidenceError("uv.lock has no package entries")
    return {"sha256": sha256_file(lock_path), "packages": len(packages)}


def _timestamp(value: str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvidenceError("generated_at is not an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise EvidenceError("generated_at must carry a timezone")
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_evidence(
    *,
    lock_path: Path,
    runtime_report: Path,
    dev_report: Path,
    runtime_requirements: Path | None = None,
    dev_requirements: Path | None = None,
    exceptions_path: Path = DEFAULT_EXCEPTIONS,
    generated_at: str | None = None,
    pip_audit_version: str | None = None,
) -> dict[str, Any]:
    """Compose the evidence document; raises :class:`EvidenceError` on doubt."""
    timestamp = _timestamp(generated_at)
    today = date.fromisoformat(timestamp[:10])
    if pip_audit_version is None:
        try:
            pip_audit_version = package_version("pip-audit")
        except PackageNotFoundError as exc:
            raise EvidenceError("pip-audit is not installed") from exc
    runtime = summarise_report(_read_json(runtime_report, "runtime audit report"))
    dev = summarise_report(_read_json(dev_report, "dev audit report"))
    return {
        "schema": SCHEMA,
        "generated_at": timestamp,
        "python": platform.python_version(),
        "pip_audit": pip_audit_version,
        "commands": {"runtime": RUNTIME_COMMAND, "dev": DEV_COMMAND},
        "lock": _lock_facts(lock_path),
        "contours": {
            "runtime": {
                "blocking": True,
                "requirements_sha256": sha256_file(runtime_requirements) if runtime_requirements else None,
                **runtime,
            },
            "dev": {
                "blocking": False,
                "requirements_sha256": sha256_file(dev_requirements) if dev_requirements else None,
                **dev,
            },
        },
        "exceptions": load_exceptions(exceptions_path, today=today),
    }


def write_evidence(document: dict[str, Any], output: Path) -> Path:
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(output)
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lock", type=Path, default=Path("uv.lock"))
    parser.add_argument("--runtime-report", type=Path, required=True)
    parser.add_argument("--dev-report", type=Path, required=True)
    parser.add_argument("--runtime-requirements", type=Path, required=True)
    parser.add_argument("--dev-requirements", type=Path, required=True)
    parser.add_argument("--exceptions", type=Path, default=DEFAULT_EXCEPTIONS)
    parser.add_argument("--generated-at", default=None)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        document = build_evidence(
            lock_path=args.lock,
            runtime_report=args.runtime_report,
            dev_report=args.dev_report,
            runtime_requirements=args.runtime_requirements,
            dev_requirements=args.dev_requirements,
            exceptions_path=args.exceptions,
            generated_at=args.generated_at,
        )
        write_evidence(document, args.output)
    except EvidenceError as exc:
        sys.stderr.write(f"dependency-audit evidence: {exc}\n")
        return 1
    summary = (
        f"dependency-audit evidence: {document['contours']['runtime']['finding_count']} runtime / "
        f"{document['contours']['dev']['finding_count']} dev finding(s), "
        f"{document['contours']['runtime']['scanned_packages']} runtime package(s), "
        f"lock {document['lock']['sha256'][:12]}…, {document['generated_at']}"
    )
    sys.stdout.write(summary + "\n")
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with Path(summary_file).open("a", encoding="utf-8") as handle:
            handle.write(summary + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
