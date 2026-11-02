#!/usr/bin/env python3
"""Ratchet the spec-ID references in ``src`` (issue #329).

``# QH-1b.2 slice 2``, ``# UI-5 PR-2``, ``# S-02`` — the numbers mean something
only next to the spec that issued them, so a reader of the code has to leave the
code to learn *why* it is the way it is. The issue asks to say the reason in a
sentence instead and to keep an ID only where it leads to a document. This
script makes the way there one-directional:

* **the count only goes down** — IDs of the families the audit counted
  (``QH-``, ``TP-``, ``UI-``, ``UD-``, ``UQ-``, ``UA-``, ``S-nn``, ``A-nn``,
  ``D-nn``) in the ``.py`` files under ``src`` are summed and compared with
  ``scripts/id_references_baseline.json``. Growth fails the check;
* **progress is recorded** — a lower count than the baseline fails too, until
  ``--fix`` lowers it, so an improvement cannot be spent again later;
* **where they live is reported** — separately for comments (the cheap ones to
  turn into a reason) and for docstrings and strings, and per file, so a
  cleanup can start where the references are densest. Moving code between files
  changes nothing: the limit is the total.

Run ``python scripts/check_id_references.py --fix`` after rewording references
into reasons; ``--list`` prints the worklist. ``--fix`` creates the baseline when
it is missing and otherwise only lowers it. Standard library only.

Exit codes: 0 — within the baseline, 1 — violations, 2 — usage/parse/baseline
errors.
"""

from __future__ import annotations

import argparse
import ast
import collections
import io
import json
import os
import re
import sys
import tokenize
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = "src"
DEFAULT_BASELINE = REPO_ROOT / "scripts" / "id_references_baseline.json"

BASELINE_VERSION = 1
BASELINE_COMMENT = (
    "Ratchet for issue #329 (python scripts/check_id_references.py). 'total' is the number of spec-ID references "
    "(QH-, TP-, UI-, UD-, UQ-, UA-, S-nn, A-nn, D-nn) in the .py files under src; it only goes down - run --fix after "
    "turning references into a reason. 'comments' and 'strings' (docstrings and string literals) split the total and "
    "'files' shows where the references live (both informational)."
)

#: The families the audit counted (the grep of the issue).
ID_PATTERN = re.compile(
    r"\b(QH-[0-9][a-z0-9.]*|TP-[0-9]|UI-[0-9]|UD-[0-9]+|UQ-[0-9]+|UA-[0-9]+|S-[0-9]{2}|A-[0-9]{2}|D-[0-9]{2})\b"
)


@dataclass(frozen=True)
class Counts:
    comments: int = 0
    strings: int = 0

    @property
    def total(self) -> int:
        return self.comments + self.strings


@dataclass(frozen=True)
class Baseline:
    total: int
    comments: int
    strings: int
    files: dict[str, int]


def count_references(text: str) -> Counts:
    """References in the comments and in the string constants (docstrings included) of one module.

    Comments come from the tokenizer. Strings come from the syntax tree rather than from tokens:
    from Python 3.12 an f-string is no longer a single ``STRING`` token, while its constant parts are
    ``ast.Constant`` nodes on every version, so the count is the same everywhere. Code holds none.
    """
    comments = sum(
        len(ID_PATTERN.findall(token.string))
        for token in tokenize.generate_tokens(io.StringIO(text).readline)
        if token.type == tokenize.COMMENT
    )
    strings = sum(
        len(ID_PATTERN.findall(node.value))
        for node in ast.walk(ast.parse(text))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    )
    return Counts(comments, strings)


def scan(root: Path, source: str) -> tuple[dict[str, Counts], list[str]]:
    """Per file with at least one reference; also the files that cannot be tokenized."""
    found: dict[str, Counts] = {}
    errors: list[str] = []
    base = root / source
    for path in sorted(base.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        try:
            counts = count_references(path.read_text(encoding="utf-8"))
        except (tokenize.TokenError, SyntaxError, UnicodeDecodeError, OSError) as exc:
            errors.append(f"{relative}: cannot tokenize ({exc})")
            continue
        if counts.total:
            found[relative] = counts
    return found, errors


def totals(found: dict[str, Counts]) -> Counts:
    return Counts(sum(c.comments for c in found.values()), sum(c.strings for c in found.values()))


# ── baseline ────────────────────────────────────────────────────────────────


def load_baseline(path: Path) -> Baseline:
    """Read and validate the baseline; raises ``OSError``/``ValueError``/``KeyError``."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != BASELINE_VERSION:
        raise ValueError(f"unsupported baseline version in {path}: {data.get('version')!r}")
    numbers = {name: data[name] for name in ("total", "comments", "strings")}
    if not all(isinstance(value, int) and value >= 0 for value in numbers.values()):
        raise ValueError("'total', 'comments' and 'strings' must be non-negative integers")
    files = data["files"]
    if not (
        isinstance(files, dict)
        and all(isinstance(name, str) and isinstance(count, int) for name, count in files.items())
    ):
        raise ValueError("'files' must map file names to counts")
    return Baseline(total=numbers["total"], comments=numbers["comments"], strings=numbers["strings"], files=dict(files))


def write_baseline(path: Path, found: dict[str, Counts]) -> None:
    summed = totals(found)
    payload = {
        "version": BASELINE_VERSION,
        "comment": BASELINE_COMMENT,
        "total": summed.total,
        "comments": summed.comments,
        "strings": summed.strings,
        "files": {name: counts.total for name, counts in sorted(found.items())},
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def find_violations(found: dict[str, Counts], baseline: Baseline) -> tuple[str, ...]:
    """Growth, or a baseline that no longer matches an improvement."""
    total = totals(found).total
    violations: list[str] = []
    if total > baseline.total:
        violations.append(
            f"src carries {total} spec-ID references, the baseline allows {baseline.total} (+{total - baseline.total}) — "
            "say the reason in a sentence instead of naming the spec"
        )
        for path, counts in sorted(found.items()):
            allowed = baseline.files.get(path, 0)
            if counts.total > allowed:
                violations.append(f"{path}: {counts.total} references, baseline {allowed} (+{counts.total - allowed})")
    elif total < baseline.total:
        violations.append(
            f"src carries {total} spec-ID references but the baseline still allows {baseline.total}: "
            "run `python scripts/check_id_references.py --fix` to keep the improvement"
        )
    return tuple(violations)


def fix_baseline(path: Path, found: dict[str, Counts]) -> int:
    """Lower the baseline after a cleanup; create it when missing; never let it grow."""
    created = not path.exists()
    try:
        previous = None if created else load_baseline(path)
    except (OSError, ValueError, KeyError) as exc:
        sys.stderr.write(f"error: cannot read {path}: {exc}\n")
        return 2
    total = totals(found).total
    if previous is not None and total > previous.total:
        sys.stderr.write(
            f"refusing to raise the bar — {total} references against a baseline of {previous.total}; --fix only lowers it\n"
        )
        return 1
    write_baseline(path, found)
    verb = "created" if created else "refreshed"
    was = "" if previous is None else f" (was {previous.total})"
    sys.stdout.write(f"id-reference baseline {verb}: {total} references in {len(found)} files{was}\n")
    return 0


# ── report ──────────────────────────────────────────────────────────────────


def _share(part: int, whole: int) -> str:
    return f"{part} ({part / whole:.0%})" if whole else str(part)


def render_line(found: dict[str, Counts], baseline: Baseline | None) -> str:
    summed = totals(found)
    allowed = "" if baseline is None else f" (baseline {baseline.total})"
    return (
        f"{summed.total} spec-ID references in {len(found)} files{allowed}: "
        f"{_share(summed.comments, summed.total)} in comments, {_share(summed.strings, summed.total)} in docstrings/strings"
    )


def render_markdown(found: dict[str, Counts], baseline: Baseline, violations: tuple[str, ...]) -> str:
    """The table shown on the workflow run page (``$GITHUB_STEP_SUMMARY``)."""
    summed = totals(found)

    def delta(now: int, was: int) -> str:
        return "0" if now == was else f"{now - was:+d}"

    lines = [
        "### Spec-ID references in src (#329)",
        "",
        "| Metric | Now | Baseline | Δ |",
        "|---|---:|---:|---:|",
        f"| **References** (gated: may only go down) | {summed.total} | {baseline.total} | {delta(summed.total, baseline.total)} |",
        f"| in comments | {summed.comments} | {baseline.comments} | {delta(summed.comments, baseline.comments)} |",
        f"| in docstrings and strings | {summed.strings} | {baseline.strings} | {delta(summed.strings, baseline.strings)} |",
        f"| Files with references | {len(found)} | {len(baseline.files)} | {delta(len(found), len(baseline.files))} |",
    ]
    if violations:
        lines += ["", "**Violations**", ""]
        lines += [f"- {violation}" for violation in violations]
    return "\n".join(lines) + "\n"


def _emit_github_summary(markdown: str) -> None:
    """Append to ``$GITHUB_STEP_SUMMARY`` in CI, print locally."""
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(markdown)
    else:
        sys.stdout.write(markdown)


def render_listing(root: Path, source: str, found: dict[str, Counts], limit: int = 20) -> str:
    """The worklist: the densest files and the most used IDs."""
    summed = totals(found)
    lines = [render_line(found, None), "", "densest files (comments / docstrings+strings):"]
    for path, counts in sorted(found.items(), key=lambda item: -item[1].total)[:limit]:
        lines.append(f"{counts.total:5d}  {counts.comments:3d} / {counts.strings:3d}  {path}")
    ids: collections.Counter[str] = collections.Counter()
    for path in found:
        ids.update(ID_PATTERN.findall((root / path).read_text(encoding="utf-8")))
    lines += ["", f"{len(ids)} distinct IDs ({summed.total} references); the most used:"]
    lines += [f"{count:5d}  {identifier}" for identifier, count in ids.most_common(limit)]
    return "\n".join(lines) + "\n"


# ── command line ────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ratchet the spec-ID references in src (issue #329).")
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="repository root")
    parser.add_argument(
        "--source", default=DEFAULT_SOURCE, help="directory scanned, relative to the root (default: src)"
    )
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE, help="baseline JSON file")
    parser.add_argument(
        "--fix", action="store_true", help="lower the baseline after a cleanup (creates it when missing)"
    )
    parser.add_argument("--list", action="store_true", help="show where the references are and the most used IDs")
    parser.add_argument(
        "--github-summary", action="store_true", help="append the metrics table to $GITHUB_STEP_SUMMARY"
    )
    args = parser.parse_args(argv)

    root = args.root.resolve()
    if not (root / args.source).is_dir():
        sys.stderr.write(f"error: {root / args.source} is not a directory — wrong --root or --source?\n")
        return 2
    found, parse_errors = scan(root, args.source)
    if parse_errors:
        sys.stderr.write(
            "error: cannot analyse the sources:\n" + "\n".join(f"  {error}" for error in parse_errors) + "\n"
        )
        return 2

    if args.list:
        sys.stdout.write(render_listing(root, args.source, found))
        return 0
    if args.fix:
        return fix_baseline(args.baseline, found)
    try:
        baseline = load_baseline(args.baseline)
    except (OSError, ValueError, KeyError) as exc:
        sys.stderr.write(
            f"error: cannot read {args.baseline}: {exc}\ncreate it with `python scripts/check_id_references.py --fix`\n"
        )
        return 2

    violations = find_violations(found, baseline)
    if args.github_summary:
        _emit_github_summary(render_markdown(found, baseline, violations))
    if violations:
        sys.stderr.write(f"id-reference ratchet failed ({len(violations)} problem(s)):\n")
        sys.stderr.write("\n".join(f"  {violation}" for violation in violations) + "\n")
        return 1
    sys.stdout.write(f"id-reference ratchet passed: {render_line(found, baseline)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
