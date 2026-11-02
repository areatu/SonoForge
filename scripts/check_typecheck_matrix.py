#!/usr/bin/env python3
"""Guard the mypy-matrix gate itself (issue #417).

A green CI job is only evidence when the job really runs mypy for every
supported interpreter and the aggregate required gate cannot succeed without
it. This script checks that wiring statically, so removing a matrix cell,
dropping the interpreter check, or forgetting ``typecheck`` in the ``test``
gate fails in ``lint`` instead of silently turning the matrix into a no-op.

Standard library only: the lint job installs no YAML parser. The workflow is
read as text and split into job blocks by their two-space headings.

Usage:  python scripts/check_typecheck_matrix.py [--workflow PATH] [--github-summary]
Exit:   0 — wiring complete, 1 — problems, 2 — usage/IO error.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
SUPPORTED = ("3.11", "3.12", "3.13")
_JOB_HEADING = re.compile(r"^  ([A-Za-z_][A-Za-z0-9_-]*):\s*$", re.MULTILINE)


def job_blocks(text: str) -> dict[str, str]:
    """Split ci.yml into ``job name -> body`` by two-space job headings."""
    matches = list(_JOB_HEADING.finditer(text))
    blocks: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        blocks[match.group(1)] = text[match.start() : end]
    return blocks


def matrix_versions(block: str) -> list[str]:
    """Versions in the ``python-version: [...]`` line of a job's matrix."""
    match = re.search(r"python-version:\s*\[([^\]]*)\]", block)
    if not match:
        return []
    return re.findall(r"[\"']([0-9]+\.[0-9]+)[\"']", match.group(1))


def inspect(text: str) -> list[str]:
    """Return the wiring problems found in a ci.yml text."""
    problems: list[str] = []
    blocks = job_blocks(text)
    for job in ("typecheck", "lint", "test", "build"):
        if job not in blocks:
            problems.append(f"job {job!r} is missing")
    if problems:
        return problems

    typecheck, lint, test, build = (blocks[job] for job in ("typecheck", "lint", "test", "build"))

    versions = matrix_versions(typecheck)
    if versions != list(SUPPORTED):
        problems.append(f"typecheck matrix is {versions}; expected exactly {list(SUPPORTED)}")
    if "fail-fast: false" not in typecheck:
        problems.append("typecheck matrix must set fail-fast: false so one cell cannot mask another")
    if "python-version: ${{ matrix.python-version }}" not in typecheck:
        problems.append("typecheck must install the matrix interpreter with actions/setup-python")
    if "scripts/typecheck_matrix.sh ${{ matrix.python-version }}" not in typecheck:
        problems.append("typecheck must call the shared scripts/typecheck_matrix.sh with the matrix cell")
    if "UV_PYTHON_DOWNLOADS: never" not in text:
        problems.append("the locked-toolchain env guard UV_PYTHON_DOWNLOADS: never is gone")

    # The shared script must really pin the marker-dependent numpy and guard
    # against a zero-file run; this is what makes each cell non-vacuous.
    script_path = REPO_ROOT / "scripts" / "typecheck_matrix.sh"
    if not script_path.is_file():
        problems.append("scripts/typecheck_matrix.sh is missing")
    else:
        script = script_path.read_text(encoding="utf-8")
        for fragment in (
            "locked numpy --python-version",
            'python -m mypy --python-version "$PY_VERSION"',
            "no checked source files",
        ):
            if fragment not in script:
                problems.append(f"scripts/typecheck_matrix.sh lacks {fragment!r}")
        if "numpy==$(locked numpy)" in script:
            problems.append("numpy must be selected with --python-version, not the running interpreter's pin")

    if "python scripts/check_typecheck_matrix.py" not in lint:
        problems.append("lint must run this wiring guard")
    if "mypy" not in lint:
        problems.append("lint must still run the 3.11 mypy baseline")

    needs = re.search(r"^\s+needs:\s*\[([^\]]*)\]", test, re.MULTILINE)
    if not needs or "typecheck" not in [item.strip() for item in needs.group(1).split(",")]:
        problems.append("aggregate test gate does not list typecheck in needs")
    if "TYPECHECK_RESULT: ${{ needs.typecheck.result }}" not in test:
        problems.append("aggregate test gate does not export needs.typecheck.result")
    if '|| "$TYPECHECK_RESULT" != "success"' not in test:
        problems.append("aggregate test gate does not check TYPECHECK_RESULT in its condition")

    build_needs = re.search(r"^\s+needs:\s*\[([^\]]*)\]", build, re.MULTILINE)
    if not build_needs or "test" not in [item.strip() for item in build_needs.group(1).split(",")]:
        problems.append("build does not wait for the aggregate test gate")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workflow", type=Path, default=DEFAULT_WORKFLOW)
    parser.add_argument("--github-summary", action="store_true", help="append a short report to GITHUB_STEP_SUMMARY")
    args = parser.parse_args(argv)
    try:
        text = args.workflow.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"check_typecheck_matrix: cannot read {args.workflow}: {exc}", file=sys.stderr)
        return 2

    problems = inspect(text)
    summary = (
        f"typecheck matrix wiring: {', '.join(SUPPORTED)} + aggregate gate + no-op guard — OK"
        if not problems
        else "typecheck matrix wiring BROKEN:\n" + "\n".join(f"- {item}" for item in problems)
    )
    print(summary)
    if args.github_summary and os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as handle:
            handle.write("### mypy matrix gate\n\n" + summary.replace("\n", "\n\n") + "\n")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
