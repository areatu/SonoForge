#!/usr/bin/env python3
"""Verify the *published* release bytes against the matrix, manifests and records.

`QH-5a` slice 3 (spec §9.1, A-17) requires that "SHA256SUMS, versioned asset
names, manifests and SBOM agree with the **final published bytes**", and that
the SBOM "is bound to a concrete binary hash and to the actual packaged
composition". The workflows run this script **after publishing**, on the assets
downloaded back from the release, so what is checked is what a user downloads —
not a build directory that could differ from it.

Checks (each reported as PASS/FAIL, exit code 1 if any failed):

``matrix``        every asset the package matrix declares for the selected
                  profiles is published, and every name carries the version;
``checksums``     each checksum manifest lists exactly its binaries and every
                  digest matches the downloaded file;
``sboms``         one CycloneDX 1.6 SBOM per packaged artifact, bound to the
                  version and to a serialNumber derived from the tag, with a
                  non-empty component list;
``records``       a build record for every profile/platform: valid structure,
                  the same tag/version, the same ``uv.lock`` hash as this
                  checkout, artifact digests equal to the published bytes, and a
                  passed packaged smoke;
``latest_json``   the download manifest lists only published, checksum-verified
                  files, with the right digest and size, and misses none;
``attestations``  (``--attestations``) ``gh attestation verify`` succeeds for
                  every published asset and for the CycloneDX SBOM of each one.

Nothing here writes to the release. Exit code 0 means the published set is
internally consistent; it does not mean the binaries are OS-signed (Gate G5b).

CLI::

    python tools/release/verify_release.py --dir published --tag v0.3.3 \\
        --version 0.3.3 --profile full --latest-json published/latest.json \\
        --attestations --json-out release-verification.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_record  # noqa: E402
import package_matrix  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
REPO_DEFAULT = "areatu/SonoForge"
SBOM_PREDICATE_TYPE = "https://cyclonedx.org/bom"
CHECK_ORDER = ("matrix", "checksums", "sboms", "records", "latest_json", "attestations")


class Report:
    """Collected check results — one flat list so CI can print it verbatim."""

    def __init__(self) -> None:
        self.entries: list[dict] = []

    def add(self, check: str, ok: bool, detail: str) -> None:
        self.entries.append({"check": check, "ok": bool(ok), "detail": detail})

    @property
    def ok(self) -> bool:
        return all(entry["ok"] for entry in self.entries)

    def as_dict(self) -> dict:
        return {
            "schema": 1,
            "kind": "sonoforge.release-verification",
            "ok": self.ok,
            "checks": self.entries,
            "failed": [entry["check"] for entry in self.entries if not entry["ok"]],
        }

    def render(self) -> str:
        lines = [f"[{'PASS' if entry['ok'] else 'FAIL'}] {entry['check']}: {entry['detail']}" for entry in self.entries]
        lines.append("RESULT: " + ("PASS" if self.ok else "FAIL"))
        return "\n".join(lines)


def parse_sums(text: str) -> dict[str, str]:
    """``sha256sum`` output → ``{file name: digest}`` (bare base names)."""
    sums: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        digest, _, name = line.partition("  ")
        if not name:
            digest, _, name = line.partition(" ")
        name = name.strip().lstrip("*")
        if not name or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            continue
        sums[Path(name).name] = digest.lower()
    return sums


def file_digest_and_size(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def expected_sbom_serial(repo: str, version: str) -> str:
    """The serialNumber the release SBOMs carry.

    ``uuid5(NAMESPACE_URL, "https://github.com/<repo>/releases/tag/v<version>")``
    is injected by the packaging workflows because ``cyclonedx-py
    --output-reproducible`` omits the serial. It is derived from the *version*,
    not from the ref, so a Presenter release published from ``presenter-v*``
    carries the same binding. Change this formula only together with the
    workflows (``release.yml``, ``presenter.yml``).
    """
    return "urn:uuid:" + str(uuid.uuid5(uuid.NAMESPACE_URL, f"https://github.com/{repo}/releases/tag/v{version}"))


def _check_matrix(
    report: Report, matrix: dict, version: str, profiles: list[str] | None, directory: Path
) -> list[dict]:
    declared = package_matrix.assets_for(matrix, version, profiles or ())
    missing = [asset["name"] for asset in declared if not (directory / asset["name"]).is_file()]
    unversioned = [asset["name"] for asset in declared if version not in asset["name"]]
    problems = [f"missing {name}" for name in missing] + [f"name without the version: {name}" for name in unversioned]
    selected = ", ".join(profiles or sorted(matrix["profiles"]))
    report.add(
        "matrix",
        not problems,
        f"{len(declared)} declared asset(s) for {selected}" + ("" if not problems else "; " + "; ".join(problems)),
    )
    return declared


def _check_checksums(report: Report, matrix: dict, version: str, profiles: list[str] | None, directory: Path) -> None:
    expectations = package_matrix.checksum_expectations(matrix, version, profiles or ())
    problems: list[str] = []
    for manifest_name, names in sorted(expectations.items()):
        path = directory / manifest_name
        if not path.is_file():
            problems.append(f"{manifest_name} is missing")
            continue
        sums = parse_sums(path.read_text(encoding="utf-8"))
        for name in sorted(names):
            if name not in sums:
                problems.append(f"{manifest_name} does not list {name}")
                continue
            file_path = directory / name
            if not file_path.is_file():
                problems.append(f"{manifest_name} lists {name}, which was not downloaded")
                continue
            digest, _ = file_digest_and_size(file_path)
            if digest != sums[name]:
                problems.append(f"{manifest_name}: digest mismatch for {name}")
        for listed in sorted(set(sums) - set(names)):
            problems.append(f"{manifest_name} lists unexpected {listed}")
    report.add("checksums", not problems, "digests and coverage match" if not problems else "; ".join(problems))


def _check_sboms(
    report: Report,
    matrix: dict,
    version: str,
    repo: str,
    profiles: list[str] | None,
    directory: Path,
) -> None:
    names = package_matrix.sbom_names(matrix, version, profiles or ())
    if not names:
        report.add("sboms", True, "selected assets are source-only")
        return
    problems: list[str] = []
    expected_serial = expected_sbom_serial(repo, version)
    for name in names:
        path = directory / name
        if not path.is_file():
            problems.append(f"{name} is missing")
            continue
        try:
            sbom = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            problems.append(f"{name} is not readable JSON ({type(exc).__name__})")
            continue
        if sbom.get("bomFormat") != "CycloneDX":
            problems.append(f"{name}: bomFormat is {sbom.get('bomFormat')!r}")
        if sbom.get("specVersion") != "1.6":
            problems.append(f"{name}: specVersion is {sbom.get('specVersion')!r}, expected 1.6")
        component = (sbom.get("metadata") or {}).get("component") or {}
        if str(component.get("version") or "") != version:
            problems.append(f"{name}: metadata.component.version is {component.get('version')!r}, expected {version!r}")
        if str(sbom.get("serialNumber") or "") != expected_serial:
            problems.append(f"{name}: serialNumber does not bind to v{version}")
        if not sbom.get("components"):
            problems.append(f"{name}: no components")
    report.add("sboms", not problems, f"{len(names)} SBOM(s)" + ("" if not problems else "; " + "; ".join(problems)))


def _check_records(
    report: Report,
    matrix: dict,
    version: str,
    tag: str,
    profiles: list[str] | None,
    directory: Path,
    lock_path: Path | None,
) -> None:
    declared = package_matrix.assets_for(matrix, version, profiles or ())
    combos = sorted({(asset["profile"], asset["platform"]) for asset in declared})
    lock_sha = None
    if lock_path is not None and Path(lock_path).is_file():
        lock_sha = build_record.sha256_of(lock_path)
    problems: list[str] = []
    for profile, platform in combos:
        name = package_matrix.record_name(matrix, profile, platform, version)
        path = directory / name
        if not path.is_file():
            problems.append(f"{name} is missing")
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            problems.append(f"{name} is not readable JSON ({type(exc).__name__})")
            continue
        problems.extend(f"{name}: {item}" for item in build_record.validate_record(record))
        if record.get("profile") != profile or record.get("platform") != platform:
            problems.append(f"{name}: profile/platform do not match the file name")
        release = record.get("release") or {}
        if release.get("tag") != tag or release.get("version") != version:
            problems.append(f"{name}: release {release.get('tag')!r}/{release.get('version')!r} != {tag}/{version}")
        if lock_sha and (record.get("lock") or {}).get("sha256") != lock_sha:
            problems.append(f"{name}: uv.lock hash differs from this checkout")
        described = {item.get("name"): item for item in record.get("artifacts") or []}
        for asset in [a for a in declared if (a["profile"], a["platform"]) == (profile, platform)]:
            entry = described.get(asset["name"])
            if entry is None:
                problems.append(f"{name}: does not describe published {asset['name']}")
                continue
            file_path = directory / asset["name"]
            if not file_path.is_file():
                continue
            digest, size = file_digest_and_size(file_path)
            if entry.get("sha256") != digest or entry.get("size") != size:
                problems.append(f"{name}: {asset['name']} digest/size differ from the record")
            if asset["smoke"] != "none" and (record.get("smoke") or {}).get("status") != build_record.SMOKE_PASS:
                problems.append(f"{name}: package smoke is {(record.get('smoke') or {}).get('status')!r}")
    report.add(
        "records",
        not problems,
        f"{len(combos)} build record(s)" + ("" if not problems else "; " + "; ".join(problems)),
    )


def _check_latest_json(
    report: Report,
    matrix: dict,
    version: str,
    tag: str,
    profiles: list[str] | None,
    directory: Path,
    latest_json: Path | None,
) -> None:
    if latest_json is None:
        report.add("latest_json", True, "not verified (no latest.json for this profile set)")
        return
    path = Path(latest_json)
    if not path.is_file():
        report.add("latest_json", False, f"{path.name} is missing")
        return
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        report.add("latest_json", False, f"{path.name} is not readable JSON ({type(exc).__name__})")
        return
    problems: list[str] = []
    if manifest.get("tag") != tag:
        problems.append(f"tag is {manifest.get('tag')!r}, expected {tag!r}")
    assets = manifest.get("assets") or []
    listed = {entry.get("name") for entry in assets}
    expectations = package_matrix.checksum_expectations(matrix, version, profiles or ())
    required = {name for names in expectations.values() for name in names}
    for entry in assets:
        name = entry.get("name") or ""
        file_path = directory / name
        if not file_path.is_file():
            problems.append(f"lists {name!r}, which is not published")
            continue
        digest, size = file_digest_and_size(file_path)
        if entry.get("sha256") != digest or entry.get("size") != size:
            problems.append(f"{name}: digest/size differ from the published file")
        if version not in name:
            problems.append(f"{name}: name does not carry the version")
    for name in sorted(required - listed):
        problems.append(f"does not list {name}")
    report.add(
        "latest_json",
        not problems,
        f"{len(listed)} entries" + ("" if not problems else "; " + "; ".join(problems)),
    )


def _gh_verify(path: Path, repo: str, predicate_type: str | None) -> tuple[bool, str]:
    command = ["gh", "attestation", "verify", str(path), "--repo", repo]
    if predicate_type:
        command += ["--predicate-type", predicate_type]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return False, "gh is not installed"
    if result.returncode == 0:
        return True, "ok"
    tail = (result.stderr or result.stdout or "").strip().splitlines()
    return False, (tail[-1] if tail else f"gh exited with {result.returncode}")


def _check_attestations(
    report: Report,
    matrix: dict,
    version: str,
    repo: str,
    profiles: list[str] | None,
    directory: Path,
    verify=_gh_verify,
) -> None:
    problems: list[str] = []
    checked = 0
    for asset in package_matrix.assets_for(matrix, version, profiles or ()):
        path = directory / asset["name"]
        if not path.is_file():
            problems.append(f"{asset['name']}: not published")
            continue
        # Provenance is checked for every published asset, including the source
        # tarball: release.yml attests it too.
        ok, detail = verify(path, repo, None)
        checked += 1
        if not ok:
            problems.append(f"{asset['name']}: provenance attestation — {detail}")
        # An SBOM attestation exists only where the matrix declares an SBOM.
        if asset["sbom"]:
            ok, detail = verify(path, repo, SBOM_PREDICATE_TYPE)
            if not ok:
                problems.append(f"{asset['name']}: SBOM attestation — {detail}")
    report.add(
        "attestations", not problems, f"{checked} artifact(s)" + ("" if not problems else "; " + "; ".join(problems))
    )


def verify(
    directory: Path,
    *,
    tag: str,
    version: str,
    repo: str = REPO_DEFAULT,
    matrix_path: Path = package_matrix.DEFAULT_MATRIX,
    profiles: list[str] | None = None,
    latest_json: Path | None = None,
    lock_path: Path | None = None,
    attestations: bool = False,
    gh_verify=_gh_verify,
) -> Report:
    directory = Path(directory)
    if not directory.is_dir():
        raise FileNotFoundError(f"{directory} is not a directory")
    matrix = package_matrix.load(matrix_path)
    report = Report()
    _check_matrix(report, matrix, version, profiles, directory)
    _check_checksums(report, matrix, version, profiles, directory)
    _check_sboms(report, matrix, version, repo, profiles, directory)
    _check_records(report, matrix, version, tag, profiles, directory, lock_path)
    _check_latest_json(report, matrix, version, tag, profiles, directory, latest_json)
    if attestations:
        _check_attestations(report, matrix, version, repo, profiles, directory, gh_verify)
    return report


def _profiles_argument(value: str | None) -> list[str] | None:
    if not value or value == "all":
        return None
    return [part.strip() for part in value.split(",") if part.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", type=Path, default=Path("."), help="directory with the downloaded published assets")
    parser.add_argument("--tag", required=True, help="release tag, e.g. v0.3.3")
    parser.add_argument("--version", required=True, help="package version, e.g. 0.3.3")
    parser.add_argument("--repo", default=REPO_DEFAULT)
    parser.add_argument("--matrix", type=Path, default=package_matrix.DEFAULT_MATRIX)
    parser.add_argument("--profile", default="all", help="all | full | presenter | comma-separated")
    parser.add_argument("--latest-json", type=Path, default=None, help="published latest.json (optional)")
    parser.add_argument("--lock", type=Path, default=REPO_ROOT / "uv.lock", help="uv.lock of this checkout")
    parser.add_argument("--attestations", action="store_true", help="run `gh attestation verify` per artifact")
    parser.add_argument("--json-out", type=Path, default=None, help="write the report as JSON (CI evidence)")
    args = parser.parse_args(argv)

    try:
        report = verify(
            args.dir,
            tag=args.tag,
            version=args.version,
            repo=args.repo,
            matrix_path=args.matrix,
            profiles=_profiles_argument(args.profile),
            latest_json=args.latest_json,
            lock_path=args.lock,
            attestations=args.attestations,
        )
    except (OSError, package_matrix.MatrixError) as exc:
        print(f"verify_release: {exc}", file=sys.stderr)
        return 1
    print(report.render())
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report.as_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
