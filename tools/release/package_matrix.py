#!/usr/bin/env python3
"""Read and validate the release package matrix (``.github/package-matrix.yml``).

`QH-5a` (spec §9.1) makes the set of published packages an explicit, checked
declaration instead of a convention spread over four workflows: which profiles
and platforms are shipped, which job builds each asset, how deeply the shipped
bytes are smoked, and which SBOM/checksum evidence accompanies them.

The matrix is data; this module is the only reader. ``validate()`` runs on every
load, so a contradictory matrix fails immediately (in CI, in the packaging
workflows and in ``verify_release.py``) instead of producing a release with a
hole in it.

CLI::

    python tools/release/package_matrix.py            # validate, print a summary
    python tools/release/package_matrix.py --json     # machine-readable summary
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MATRIX = REPO_ROOT / ".github" / "package-matrix.yml"

VERSION_TOKEN = "{version}"
SMOKE_LEVELS = ("artifact", "payload", "none")
SBOM_SUFFIX = ".sbom.cdx.json"
REQUIRED_ASSET_KEYS = ("name", "profile", "platform", "workflow", "job", "kind", "smoke", "manifest")
REQUIRED_PLATFORM_KEYS = ("runner", "architecture")
REQUIRED_PROFILE_KEYS = ("title", "dependency_source", "install", "entry_point", "storage", "capabilities")


class MatrixError(ValueError):
    """The matrix contradicts itself or the release policy."""


def load(path: Path | str = DEFAULT_MATRIX) -> dict:
    """Load and validate the matrix file."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - CI has the file
        raise MatrixError(f"cannot read the package matrix {path}: {exc}") from exc
    try:
        matrix = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise MatrixError(f"{path} is not valid YAML: {exc}") from exc
    if not isinstance(matrix, dict):
        raise MatrixError(f"{path} must be a mapping, got {type(matrix).__name__}")
    validate(matrix, source=str(path))
    return matrix


def validate(matrix: dict, source: str = "package-matrix.yml") -> None:
    """Raise :class:`MatrixError` for anything that would make a release ambiguous."""

    def fail(message: str) -> None:
        raise MatrixError(f"{source}: {message}")

    if matrix.get("schema") != 1:
        fail(f"unsupported schema {matrix.get('schema')!r} (expected 1)")

    profiles = matrix.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        fail("`profiles` must be a non-empty mapping")
    for name, profile in profiles.items():
        if not isinstance(profile, dict):
            fail(f"profile {name!r} must be a mapping")
        missing = [key for key in REQUIRED_PROFILE_KEYS if not profile.get(key)]
        if missing:
            fail(f"profile {name!r} is missing {', '.join(missing)}")
        capabilities = profile.get("capabilities")
        if not isinstance(capabilities, dict):
            fail(f"profile {name!r}: `capabilities` must be a mapping")

    platforms = matrix.get("platforms")
    if not isinstance(platforms, dict) or not platforms:
        fail("`platforms` must be a non-empty mapping")
    for name, platform in platforms.items():
        if not isinstance(platform, dict):
            fail(f"platform {name!r} must be a mapping")
        missing = [key for key in REQUIRED_PLATFORM_KEYS if not platform.get(key)]
        if missing:
            fail(f"platform {name!r} is missing {', '.join(missing)}")

    assets = matrix.get("assets")
    if not isinstance(assets, list) or not assets:
        fail("`assets` must be a non-empty list")

    seen: set[str] = set()
    sbom_owner: dict[str, str] = {}
    for index, asset in enumerate(assets, start=1):
        if not isinstance(asset, dict):
            fail(f"asset #{index} must be a mapping")
        missing = [key for key in REQUIRED_ASSET_KEYS if not asset.get(key)]
        if missing:
            fail(f"asset #{index} ({asset.get('name', '?')}) is missing {', '.join(missing)}")
        name = asset["name"]
        if name in seen:
            fail(f"duplicate asset name {name!r}")
        seen.add(name)
        if VERSION_TOKEN not in name:
            fail(f"asset {name!r} must carry {VERSION_TOKEN} so a download identifies its build")
        if asset["profile"] not in profiles:
            fail(f"asset {name!r} names unknown profile {asset['profile']!r}")
        if asset["platform"] not in platforms:
            fail(f"asset {name!r} names unknown platform {asset['platform']!r}")
        if asset["smoke"] not in SMOKE_LEVELS:
            fail(f"asset {name!r}: smoke must be one of {', '.join(SMOKE_LEVELS)}")
        workflow = asset["workflow"]
        if not str(workflow).endswith(".yml"):
            fail(f"asset {name!r}: workflow must be a .yml file name")
        if asset["profile"] == "presenter" and workflow != "presenter.yml":
            fail(f"Presenter asset {name!r} must be produced by presenter.yml, not {workflow!r}")
        if asset["profile"] != "presenter" and workflow == "presenter.yml":
            fail(f"asset {name!r} is not a Presenter asset but is built by presenter.yml")

        manifest = asset["manifest"]
        if manifest not in _manifest_names(matrix):
            fail(f"asset {name!r} names unknown checksum manifest {manifest!r}")

        sbom = asset.get("sbom")
        if asset["smoke"] == "none":
            if sbom:
                fail(f"source-only asset {name!r} cannot declare an SBOM")
        else:
            if not sbom:
                fail(f"packaged asset {name!r} must declare an SBOM")
            if not sbom.endswith(SBOM_SUFFIX):
                fail(f"asset {name!r}: SBOM name must end with {SBOM_SUFFIX}")
            if VERSION_TOKEN not in sbom:
                fail(f"asset {name!r}: SBOM name {sbom!r} must carry {VERSION_TOKEN}")
            owner = sbom_owner.get(sbom)
            if owner is not None and owner.split(":")[0] != asset["platform"]:
                fail(f"SBOM {sbom!r} is shared across platforms ({owner} and {name})")
            sbom_owner.setdefault(sbom, f"{asset['platform']}:{name}")

    for manifest in matrix.get("manifests") or []:
        if not isinstance(manifest, dict) or not manifest.get("name"):
            fail("every `manifests` entry needs a name")
        for profile in manifest.get("profiles") or []:
            if profile not in profiles:
                fail(f"manifest {manifest['name']!r} names unknown profile {profile!r}")

    records = matrix.get("records")
    if not isinstance(records, dict) or VERSION_TOKEN not in records.get("name", ""):
        fail("`records.name` must be a file-name pattern containing {version}")
    if "{profile}" not in records["name"] or "{platform}" not in records["name"]:
        fail("`records.name` must distinguish profile and platform")
    if not records.get("fields"):
        fail("`records.fields` must not be empty")

    smoke = matrix.get("smoke")
    if not isinstance(smoke, dict):
        fail("`smoke` must be a mapping")
    if not smoke.get("module") or not smoke.get("entry_flag"):
        fail("`smoke` must name the module and the frozen-build entry flag")
    if sorted(smoke.get("stages") or []) != ["restart", "save"]:
        fail("`smoke.stages` must be the save -> restart pair")
    for mode in smoke.get("modes") or []:
        if mode not in ("artifact", "payload", "module"):
            fail(f"smoke mode {mode!r} is not recognised")
    if not smoke.get("checks"):
        fail("`smoke.checks` must list what the packaged run proves")

    policy = matrix.get("policy")
    if not isinstance(policy, dict) or policy.get("dependency_lock") != "uv.lock":
        fail("`policy.dependency_lock` must be uv.lock")
    if not policy.get("forbidden"):
        fail("`policy.forbidden` must list the install shortcuts that are not allowed")

    checklist = matrix.get("release_checklist")
    if not isinstance(checklist, list) or not checklist:
        fail("`release_checklist` must not be empty")

    gaps = matrix.get("gaps")
    if not isinstance(gaps, list) or not gaps:
        fail("`gaps` must not be empty: an unqualified matrix claims evidence it does not have")
    for gap in gaps:
        if not isinstance(gap, dict) or not gap.get("id") or not gap.get("text"):
            fail("every gap needs an `id` and a `text`")


def _manifest_names(matrix: dict) -> set[str]:
    return {entry["name"] for entry in matrix.get("manifests") or [] if isinstance(entry, dict) and entry.get("name")}


def expand(template: str, version: str) -> str:
    """``"SonoForge-{version}.exe"`` + ``"0.3.3"`` → ``"SonoForge-0.3.3.exe"``."""
    return template.replace(VERSION_TOKEN, version)


def assets_for(matrix: dict, version: str, profiles: tuple[str, ...] | list[str] = tuple()) -> list[dict]:
    """Asset rows for the selected profiles, with ``{version}`` substituted.

    The returned rows are copies: ``name``/``sbom`` hold the published file
    names, ``template`` keeps the pattern for diagnostics.
    """
    wanted = set(profiles) if profiles else set(matrix["profiles"])
    unknown = wanted - set(matrix["profiles"])
    if unknown:
        raise MatrixError(f"unknown profile(s): {', '.join(sorted(unknown))}")
    rows = []
    for asset in matrix["assets"]:
        if asset["profile"] not in wanted:
            continue
        rows.append(
            {
                **asset,
                "template": asset["name"],
                "name": expand(asset["name"], version),
                "sbom": expand(asset["sbom"], version) if asset.get("sbom") else None,
            }
        )
    return rows


def asset_names(matrix: dict, version: str, profiles: tuple[str, ...] | list[str] = tuple()) -> list[str]:
    return [asset["name"] for asset in assets_for(matrix, version, profiles)]


def sbom_names(matrix: dict, version: str, profiles: tuple[str, ...] | list[str] = tuple()) -> list[str]:
    return sorted({asset["sbom"] for asset in assets_for(matrix, version, profiles) if asset.get("sbom")})


def checksum_expectations(
    matrix: dict, version: str, profiles: tuple[str, ...] | list[str] = tuple()
) -> dict[str, list[str]]:
    """``{manifest name: [file names it must list]}`` for the selected profiles."""
    expected: dict[str, list[str]] = {}
    for asset in assets_for(matrix, version, profiles):
        expected.setdefault(asset["manifest"], []).append(asset["name"])
    return expected


def record_name(matrix: dict, profile: str, platform: str, version: str) -> str:
    """Build-record file name for one profile/platform/version triple."""
    pattern = matrix["records"]["name"]
    return (
        pattern.replace(VERSION_TOKEN, version).replace("{profile}", str(profile)).replace("{platform}", str(platform))
    )


def smoke_evidence_name(profile: str, platform: str) -> str:
    """Workflow-artifact name of the packaged smoke evidence."""
    return f"package-smoke-{profile}-{platform}.json"


def summary(matrix: dict) -> dict:
    return {
        "schema": matrix["schema"],
        "profiles": sorted(matrix["profiles"]),
        "platforms": sorted(matrix["platforms"]),
        "assets": [
            {
                "name": asset["name"],
                "profile": asset["profile"],
                "platform": asset["platform"],
                "workflow": asset["workflow"],
                "smoke": asset["smoke"],
                "sbom": asset.get("sbom"),
            }
            for asset in matrix["assets"]
        ],
        "manifests": sorted(_manifest_names(matrix)),
        "gaps": [gap["id"] for gap in matrix["gaps"]],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--json", action="store_true", help="print the summary as JSON")
    args = parser.parse_args(argv)
    try:
        matrix = load(args.matrix)
    except MatrixError as exc:
        print(f"package matrix: {exc}", file=sys.stderr)
        return 1
    data = summary(matrix)
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0
    print(f"package matrix OK: {len(data['assets'])} asset(s), profiles {', '.join(data['profiles'])}")
    for asset in data["assets"]:
        print(
            f"  {asset['name']:<46} {asset['profile']:<9} {asset['platform']:<13} smoke={asset['smoke']:<8} {asset['workflow']}"
        )
    print(f"  manifests: {', '.join(data['manifests'])}")
    print(f"  declared gaps: {', '.join(data['gaps'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
