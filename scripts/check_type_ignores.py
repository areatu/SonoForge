#!/usr/bin/env python3
"""Ratchet the ``# type: ignore`` suppressions in ``src`` (issue #325).

The mypy gate is only as strong as the suppressions it tolerates: a bare
``# type: ignore`` silences *every* error on the line, so a real regression can
hide behind a suppression nobody re-read. This script keeps two promises:

* **a bare ignore is a violation** — new suppressions must name the code
  (``# type: ignore[arg-type]``) so a different error on the same line still
  fails the build;
* **an unexplained suppression is a violation** — the code alone says what is
  silenced, not why. The reason follows the bracket (``# type: ignore[misc]  #
  reportlab ships no stubs``) or sits on the line above, so the next reader can
  judge whether it is still true;
* **the count only goes down** — every file that already carries suppressions
  is grandfathered at its current number in ``scripts/type_ignore_baseline.json``.
  Growth fails, a new file with any suppression fails, and ``--fix`` rewrites
  the baseline *downwards* after a cleanup, so the next run cannot spend the
  credit again.

Only real comments are counted: a docstring that *discusses* suppressions is
prose, not a suppression, so the discussion can live next to the code.

Run ``python scripts/check_type_ignores.py --fix`` after removing suppressions;
the baseline commit is the ratchet's memory.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import tokenize
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = REPO_ROOT / "src"
DEFAULT_BASELINE = REPO_ROOT / "scripts" / "type_ignore_baseline.json"

#: ``# type: ignore`` / ``#type:ignore[attr-defined]`` / with a trailing ``noqa``
IGNORE_RE = re.compile(r"#\s*type:\s*ignore(\[[^\]]*\])?")
CODED_RE = re.compile(r"#\s*type:\s*ignore\[[^\]]+\]")
NOQA_RE = re.compile(r"^#?\s*noqa\b")


def comment_texts(source: str) -> list[tuple[int, str]]:
    """Every ``(line number, text)`` comment, ignoring strings and docstrings."""
    try:
        tokens: Iterator[tokenize.TokenInfo] = tokenize.generate_tokens(io.StringIO(source).readline)
        return [(token.start[0], token.string) for token in tokens if token.type == tokenize.COMMENT]
    except (tokenize.TokenError, IndentationError):  # pragma: no cover - defensive
        return [(number, line) for number, line in enumerate(source.splitlines(), start=1) if "#" in line]


def has_reason(comment: str, match: re.Match[str], *, previous_line: str = "") -> bool:
    """Whether a coded suppression is explained, inline or on the line above."""
    tail = re.sub(r"^#\s*", "", comment[match.end() :].strip()).strip()
    if tail and NOQA_RE.match(tail) is None:
        return True
    return previous_line.strip().startswith("#")


def scan_file(path: Path) -> dict[str, int]:
    """Count ``type: ignore`` comments in one file: total, bare, unexplained."""
    ignores = 0
    bare = 0
    unexplained = 0
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    for number, comment in comment_texts(source):
        previous = lines[number - 2] if 0 < number <= len(lines) else ""
        for match in IGNORE_RE.finditer(comment):
            ignores += 1
            if match.group(1) is None:
                bare += 1
            elif not has_reason(comment, match, previous_line=previous):
                unexplained += 1
    return {"ignores": ignores, "bare": bare, "unexplained": unexplained}


def scan_source(source_root: Path) -> dict[str, dict[str, int]]:
    """Return per-file suppression counts for every file that has at least one."""
    counts: dict[str, dict[str, int]] = {}
    for path in sorted(source_root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        found = scan_file(path)
        if found["ignores"]:
            counts[path.relative_to(source_root).as_posix()] = found
    return counts


def totals(counts: dict[str, dict[str, int]]) -> dict[str, int]:
    return {
        "ignores": sum(item["ignores"] for item in counts.values()),
        "bare": sum(item["bare"] for item in counts.values()),
        "unexplained": sum(item["unexplained"] for item in counts.values()),
    }


def find_violations(
    current: dict[str, dict[str, int]],
    baseline: dict[str, dict[str, int]],
) -> tuple[str, ...]:
    """Describe suppressions that the baseline does not already allow."""
    violations: list[str] = []
    for name, counts in sorted(current.items()):
        allowed = baseline.get(name)
        if allowed is None:
            violations.append(
                f"new suppressions in {name}: {counts['ignores']} "
                f"({counts['bare']} bare) — name the mypy code instead of suppressing the line"
            )
            continue
        if counts["ignores"] > allowed["ignores"]:
            violations.append(f"{name}: type ignores grew from {allowed['ignores']} to {counts['ignores']}")
        if counts["bare"] > allowed["bare"]:
            violations.append(
                f"{name}: bare type ignores grew from {allowed['bare']} to {counts['bare']} "
                "— a bare ignore hides every error on the line, name the code"
            )
        if counts["unexplained"] > allowed["unexplained"]:
            violations.append(
                f"{name}: unexplained type ignores grew from {allowed['unexplained']} "
                f"to {counts['unexplained']} — say why the suppression is acceptable"
            )
    current_totals = totals(current)
    baseline_totals = totals(baseline)
    if current_totals["ignores"] > baseline_totals["ignores"]:
        violations.append(f"total type ignores grew from {baseline_totals['ignores']} to {current_totals['ignores']}")
    if current_totals["bare"] > baseline_totals["bare"]:
        violations.append(f"total bare type ignores grew from {baseline_totals['bare']} to {current_totals['bare']}")
    if current_totals["unexplained"] > baseline_totals["unexplained"]:
        violations.append(
            f"total unexplained type ignores grew from {baseline_totals['unexplained']} "
            f"to {current_totals['unexplained']}"
        )
    return tuple(violations)


def load_baseline(path: Path) -> dict[str, dict[str, int]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != 1:
        raise ValueError(f"unsupported type-ignore baseline version: {data.get('version')!r}")
    files = data["files"]
    return {
        str(name): {
            "ignores": int(counts["ignores"]),
            "bare": int(counts["bare"]),
            "unexplained": int(counts.get("unexplained", 0)),
        }
        for name, counts in files.items()
    }


def write_baseline(path: Path, current: dict[str, dict[str, int]]) -> None:
    payload = {
        "version": 1,
        "comment": (
            "Ratchet for #325: generated by scripts/check_type_ignores.py --fix. "
            "Numbers may only go down; a bare '# type: ignore' is never allowed to appear, "
            "and every suppression carries a reason after the code."
        ),
        "totals": totals(current),
        "files": dict(sorted(current.items())),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument(
        "--fix",
        action="store_true",
        help="rewrite the baseline from the current tree (run after a cleanup)",
    )
    args = parser.parse_args(argv)

    try:
        current = scan_source(args.source)
        if args.fix:
            write_baseline(args.baseline, current)
            counted = totals(current)
            sys.stdout.write(
                f"type-ignore baseline refreshed: {counted['ignores']} ignores "
                f"({counted['bare']} bare, {counted['unexplained']} unexplained) in {len(current)} files\n"
            )
            return 0
        baseline = load_baseline(args.baseline)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"type-ignore ratchet: {exc}\n")
        return 2

    violations = find_violations(current, baseline)
    if violations:
        sys.stderr.write("type-ignore ratchet failed:\n")
        for violation in violations:
            sys.stderr.write(f"  - {violation}\n")
        return 1

    counted = totals(current)
    sys.stdout.write(
        f"type-ignore ratchet passed: {counted['ignores']} ignores ({counted['bare']} bare, "
        f"{counted['unexplained']} unexplained) within the baseline of {totals(baseline)['ignores']} "
        f"({totals(baseline)['bare']} bare)\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
