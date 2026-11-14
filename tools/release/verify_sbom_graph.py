#!/usr/bin/env python3
"""Check that a release SBOM is exactly the locked runtime dependency graph.

``cyclonedx-bom`` can describe either the build environment or a requirements
file. The environment also contains PyInstaller, Hatchling, CycloneDX itself and
the dev/build extras, so an ``environment`` SBOM of a release build overstates
what the shipped package depends on (#563). Release workflows generate the SBOM
from ``uv export --locked --no-emit-project`` and run this check before the SBOM
is finalized and attested:

* every CycloneDX component must appear in the exported runtime requirements;
* every exported runtime distribution must appear in the SBOM;
* the comparison uses PEP 503 names and exact versions, so a version bump in the
  lock cannot leave a stale component behind.

CLI::

    python tools/release/verify_sbom_graph.py SBOM.json runtime-requirements.txt
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_REQUIREMENT = re.compile(r"^\s*(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)\s*==\s*(?P<version>[^;\s]+)")


class SbomGraphError(RuntimeError):
    """The SBOM and the exported runtime graph disagree."""


def normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def requirements_graph(path: Path) -> set[tuple[str, str]]:
    """``{(normalised name, version)}`` from a ``uv export`` requirements file."""
    graph: set[tuple[str, str]] = set()
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise SbomGraphError(f"cannot read requirements file: {Path(path).name}") from exc
    for line in lines:
        text = line.split(" #", 1)[0].strip()
        if not text or text.startswith(("#", "-")):
            continue
        match = _REQUIREMENT.match(text)
        if match is None:
            raise SbomGraphError(f"requirements line is not an exact pin: {text[:80]}")
        graph.add((normalise(match.group("name")), match.group("version")))
    if not graph:
        raise SbomGraphError("runtime requirements are empty")
    return graph


def bom_graph(path: Path) -> set[tuple[str, str]]:
    """``{(normalised name, version)}`` from CycloneDX JSON components."""
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SbomGraphError(f"cannot read SBOM: {Path(path).name}") from exc
    components = document.get("components") if isinstance(document, dict) else None
    if not isinstance(components, list) or not components:
        raise SbomGraphError("SBOM has no components")
    graph: set[tuple[str, str]] = set()
    for component in components:
        if not isinstance(component, dict) or not component.get("name") or not component.get("version"):
            raise SbomGraphError("an SBOM component has no name or version")
        graph.add((normalise(str(component["name"])), str(component["version"])))
    return graph


def compare(sbom: set[tuple[str, str]], requirements: set[tuple[str, str]]) -> list[str]:
    """Human-readable differences; empty means the graphs are equal."""
    extra = sorted(f"{name}=={version}" for name, version in sbom - requirements)
    missing = sorted(f"{name}=={version}" for name, version in requirements - sbom)
    problems: list[str] = []
    if extra:
        problems.append("SBOM contains components outside the runtime graph: " + ", ".join(extra))
    if missing:
        problems.append("SBOM omits runtime components: " + ", ".join(missing))
    return problems


def verify(sbom_path: Path, requirements_path: Path) -> list[str]:
    return compare(bom_graph(sbom_path), requirements_graph(requirements_path))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sbom", type=Path)
    parser.add_argument("requirements", type=Path)
    args = parser.parse_args(argv)
    try:
        problems = verify(args.sbom, args.requirements)
    except SbomGraphError as exc:
        sys.stderr.write(f"SBOM graph check: {exc}\n")
        return 1
    if problems:
        for problem in problems:
            sys.stderr.write(f"SBOM graph check: {problem}\n")
        return 1
    sys.stdout.write("SBOM graph check: components match the locked runtime graph\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
