#!/usr/bin/env python3
"""Write the build record of one packaged release artifact (QH-5a, spec §9.1).

A release asset without a record is an assertion; the record is what makes it
checkable afterwards. For every packaged artifact the record captures:

* **what** — release tag/version, profile, platform/architecture, asset names,
  SHA-256 and size of the exact bytes that get uploaded;
* **from where** — source commit, ref, repository and the workflow run
  (id/attempt) that produced them;
* **with what** — Python, Qt, NumPy, ONNX Runtime and PyMuPDF versions, the
  SHA-256 of ``uv.lock`` plus its package count, and the hash of the packaged
  model manifest (``null`` when the profile ships no models);
* **how it was proven** — the packaged-artifact smoke evidence: its status
  (``pass``/``failed``/``not-recorded``) and its own hash.

The record deliberately refuses to be written when the tag does not match the
package version (a release whose name lies), when no artifact is given, or when
a named artifact does not exist — a record that describes nothing is worse than
no record.

CLI::

    python tools/release/build_record.py \\
        --profile full --platform linux-amd64 --tag v0.3.3 \\
        --artifact dist/sonoforge_0.3.3_amd64.deb \\
        --sbom dist/SonoForge-0.3.3-linux-amd64.sbom.cdx.json \\
        --smoke-evidence dist/package-smoke-full-linux-amd64.json \\
        --output dist/build-record-full-linux-amd64-0.3.3.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform as plat
import re
import sys
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = 1
KIND = "sonoforge.build-record"
SMOKE_PASS = "pass"
SMOKE_FAILED = "failed"
SMOKE_NOT_RECORDED = "not-recorded"
_TAG_RE = re.compile(r"^v\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.\-]+)?$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class BuildRecordError(RuntimeError):
    """The inputs cannot describe a release build."""


def sha256_of(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_version(root: Path | str = REPO_ROOT) -> str:
    """Read ``__version__`` from the single source (``src/echo_personal_tool/__init__.py``)."""
    source = Path(root) / "src" / "echo_personal_tool" / "__init__.py"
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', source.read_text(encoding="utf-8"), re.MULTILINE)
    if not match:
        raise BuildRecordError(f"no __version__ in {source}")
    return match.group(1)


def lock_info(lock_path: Path | str) -> dict:
    path = Path(lock_path)
    if not path.is_file():
        raise BuildRecordError(f"lock file {path} does not exist")
    text = path.read_text(encoding="utf-8")
    packages = len(re.findall(r"^\[\[package\]\]$", text, re.MULTILINE))
    return {"path": path.name, "sha256": sha256_of(path), "packages": packages}


def model_manifest(root: Path | str = REPO_ROOT) -> Path | None:
    """The packaged model manifest, if this checkout has one."""
    candidate = Path(root) / "models" / "model_manifest.json"
    return candidate if candidate.is_file() else None


def runtime_versions() -> dict:
    """Versions of the components whose behaviour the packaged app depends on."""
    versions = {}
    for label, distribution in (
        ("python", None),
        ("qt", "PySide6"),
        ("numpy", "numpy"),
        ("onnxruntime", "onnxruntime"),
        ("pymupdf", "PyMuPDF"),
    ):
        if distribution is None:
            versions[label] = plat.python_version()
            continue
        try:
            versions[label] = metadata.version(distribution)
        except metadata.PackageNotFoundError:
            versions[label] = None
    return versions


def _file_entry(path: Path) -> dict:
    return {"name": Path(path).name, "sha256": sha256_of(path), "size": Path(path).stat().st_size}


def smoke_status(smoke_evidence: Path | None) -> dict:
    """``pass`` only when the evidence exists and says so."""
    if smoke_evidence is None:
        return {"status": SMOKE_NOT_RECORDED, "evidence": None, "sha256": None}
    path = Path(smoke_evidence)
    if not path.is_file():
        raise BuildRecordError(f"smoke evidence does not exist: {path}")
    status = SMOKE_PASS
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        status = SMOKE_FAILED
    else:
        if not isinstance(payload, dict) or not payload.get("ok"):
            status = SMOKE_FAILED
    return {"status": status, "evidence": path.name, "sha256": sha256_of(path)}


def collect(
    *,
    profile: str,
    platform: str,
    artifacts: list[Path],
    sboms: list[Path] | None = None,
    smoke_evidence: Path | None = None,
    tag: str | None = None,
    version: str | None = None,
    root: Path | str = REPO_ROOT,
    lock_path: Path | str | None = None,
    created_at: str | None = None,
    environ: dict | None = None,
) -> dict:
    """Build the record dict. Raises :class:`BuildRecordError` on unusable input."""
    root = Path(root)
    if not platform:
        raise BuildRecordError("a build record needs a platform")
    if not artifacts:
        raise BuildRecordError("a build record must describe at least one artifact")
    env = dict(os.environ if environ is None else environ)
    version = version or package_version(root)
    tag = tag or env.get("GITHUB_REF_NAME") or f"v{version}"
    if not _TAG_RE.match(tag):
        raise BuildRecordError(f"tag must look like v<version>, got {tag!r}")
    if tag.split("-")[0].lstrip("v") != version:
        raise BuildRecordError(f"tag {tag!r} does not match package version {version!r}")

    artifact_entries = []
    for artifact in artifacts:
        path = Path(artifact)
        if not path.is_file():
            raise BuildRecordError(f"artifact does not exist: {path}")
        artifact_entries.append(_file_entry(path))
    artifact_entries.sort(key=lambda entry: entry["name"])

    sbom_entries = []
    for sbom in sboms or []:
        path = Path(sbom)
        if not path.is_file():
            raise BuildRecordError(f"SBOM does not exist: {path}")
        sbom_entries.append(_file_entry(path))
    sbom_entries.sort(key=lambda entry: entry["name"])

    models = model_manifest(root)
    lock = lock_info(lock_path or root / "uv.lock")
    return {
        "schema": SCHEMA,
        "kind": KIND,
        "created_at": created_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "release": {"tag": tag, "version": version},
        "source": {
            "repository": env.get("GITHUB_REPOSITORY"),
            "commit": env.get("GITHUB_SHA"),
            "ref": env.get("GITHUB_REF"),
            "ref_name": env.get("GITHUB_REF_NAME"),
            "workflow": env.get("GITHUB_WORKFLOW"),
            "run_id": env.get("GITHUB_RUN_ID"),
            "run_attempt": env.get("GITHUB_RUN_ATTEMPT"),
            "runner_os": env.get("RUNNER_OS"),
            "runner_arch": env.get("RUNNER_ARCH"),
        },
        "profile": profile,
        "platform": platform,
        "architecture": plat.machine(),
        "runtime": runtime_versions(),
        "lock": lock,
        "models": {
            "manifest": models.name if models else None,
            "manifest_sha256": sha256_of(models) if models else None,
        },
        "artifacts": artifact_entries,
        "sboms": sbom_entries,
        "smoke": smoke_status(smoke_evidence),
    }


def validate_record(record: dict) -> list[str]:
    """Return the problems that make a record unusable as release evidence."""
    problems: list[str] = []
    if record.get("schema") != SCHEMA:
        problems.append(f"schema is {record.get('schema')!r}, expected {SCHEMA}")
    if record.get("kind") != KIND:
        problems.append(f"kind is {record.get('kind')!r}, expected {KIND!r}")
    release = record.get("release") or {}
    if not release.get("tag") or not release.get("version"):
        problems.append("release.tag/version are missing")
    elif release["tag"].split("-")[0].lstrip("v") != release["version"]:
        problems.append(f"tag {release['tag']!r} does not match version {release['version']!r}")
    if not record.get("profile"):
        problems.append("profile is missing")
    if not record.get("platform"):
        problems.append("platform is missing")
    lock = record.get("lock") or {}
    if not _SHA256_RE.match(str(lock.get("sha256") or "")):
        problems.append("lock.sha256 is not a SHA-256 digest")
    if not isinstance(lock.get("packages"), int) or lock.get("packages", 0) <= 0:
        problems.append("lock.packages must be a positive count")
    if not record.get("artifacts"):
        problems.append("no artifacts described")
    for entry in record.get("artifacts") or []:
        if not entry.get("name"):
            problems.append("artifact without a name")
        if not _SHA256_RE.match(str(entry.get("sha256") or "")):
            problems.append(f"artifact {entry.get('name')!r} has no SHA-256")
        if not isinstance(entry.get("size"), int) or entry.get("size", 0) <= 0:
            problems.append(f"artifact {entry.get('name')!r} has no size")
    smoke = record.get("smoke") or {}
    if smoke.get("status") not in (SMOKE_PASS, SMOKE_FAILED, SMOKE_NOT_RECORDED):
        problems.append(f"smoke.status is {smoke.get('status')!r}")
    return problems


def write(record: dict, output: Path | str) -> Path:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--profile", required=True, help="full | presenter")
    parser.add_argument("--platform", required=True, help="matrix platform, e.g. linux-amd64")
    parser.add_argument("--tag", default=None, help="release tag; must equal v<version> (default: GITHUB_REF_NAME)")
    parser.add_argument("--version", default=None, help="package version (default: from src)")
    parser.add_argument("--artifact", action="append", default=[], help="published artifact (repeatable)")
    parser.add_argument("--sbom", action="append", default=[], help="published SBOM (repeatable)")
    parser.add_argument("--smoke-evidence", default=None, help="package smoke evidence JSON")
    parser.add_argument("--lock", default=str(REPO_ROOT / "uv.lock"))
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    try:
        record = collect(
            profile=args.profile,
            platform=args.platform,
            artifacts=[Path(path) for path in args.artifact],
            sboms=[Path(path) for path in args.sbom],
            smoke_evidence=Path(args.smoke_evidence) if args.smoke_evidence else None,
            tag=args.tag,
            version=args.version,
            lock_path=Path(args.lock),
            root=Path(args.root),
        )
    except BuildRecordError as exc:
        print(f"build record: {exc}", file=sys.stderr)
        return 1
    problems = validate_record(record)
    if problems:
        print("build record: " + "; ".join(problems), file=sys.stderr)
        return 1
    path = write(record, args.output)
    print(
        f"build record {path}: {record['profile']}/{record['platform']} {record['release']['version']} "
        f"{len(record['artifacts'])} artifact(s), smoke={record['smoke']['status']}, lock={record['lock']['sha256'][:12]}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
