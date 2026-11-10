#!/usr/bin/env python3
"""Fail when the unit-test inventory shrinks against its base commit (issue #473).

The previous gate compared the collected inventory with an audited
``_BASELINE`` literal on *exact equality*. Every PR that added a test had to
edit that single line, every two parallel PRs conflicted on it, and merging
``main`` left shadowed assignments behind (20 of them by 2026-11-09, 289 edits
for 241 merged PRs). The goal of the gate was right — a test must not
disappear silently — but a global literal is the wrong place to keep it.

This gate keeps the goal and drops the hot spot:

* it collects ``tests/unit/`` twice, on ``HEAD`` and on the base commit (a
  detached ``git worktree``), with the *same* ``pytest_ci_metrics`` plugin;
* every counter (``total``, ``gui``, ``not_gui``, ``gui_files``) may stay
  equal or grow; adding tests needs no bookkeeping at all;
* a counter that goes down fails, unless a commit in ``BASE..HEAD`` carries the
  trailer ``Test-Inventory-Decrease: <reason>`` — deletion stays possible,
  but only as an explicit, reviewable statement in the PR history;
* the node ids that vanished are listed either way, so the reviewer sees
  *which* tests went, not only how many.

A deletion offset by an addition in the same PR keeps the counters equal and
passes — exactly like the old exact-equality gate, which saw only counts too.
The removed node ids are still printed for the reviewer in that case.

``--output`` writes the HEAD counts for the coverage job, which checks that the
logic job and the GUI shards ran exactly the inventory this gate collected
(``verify_pytest_partition.py --expected``).

Standard library only; pytest runs in a subprocess with the current
interpreter, so the script needs the project environment only for collection.

Usage:  python .github/scripts/check_test_inventory.py [--base REV|auto]
                                                      [--output JSON] [--github-summary]
Exit:   0 — no decrease (or a declared one), 1 — undeclared decrease,
        2 — usage, git or collection error.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / ".github" / "scripts"
FIELDS = ("total", "gui", "not_gui", "gui_files")
TRAILER = "Test-Inventory-Decrease"
_TRAILER_RE = re.compile(rf"^{TRAILER}:[ \t]*(?P<reason>\S.*?)[ \t]*$", re.MULTILINE | re.IGNORECASE)
#: A reason must say something; "x" or "-" is not a review statement.
MIN_REASON_LENGTH = 10
#: How many vanished node ids are printed before the list is truncated.
MAX_LISTED = 60
ANNOTATION_TITLE = "pytest inventory gate"


class GateError(Exception):
    """A git or collection failure: the gate cannot prove anything (exit 2)."""


@dataclass(frozen=True)
class Inventory:
    counts: Mapping[str, int]
    nodeids: frozenset[str]


@dataclass(frozen=True)
class Comparison:
    base: Inventory
    head: Inventory

    @property
    def decreases(self) -> dict[str, tuple[int, int]]:
        return {
            field: (self.base.counts[field], self.head.counts[field])
            for field in FIELDS
            if self.head.counts[field] < self.base.counts[field]
        }

    @property
    def removed(self) -> list[str]:
        return sorted(self.base.nodeids - self.head.nodeids)

    @property
    def added(self) -> list[str]:
        return sorted(self.head.nodeids - self.base.nodeids)


@dataclass(frozen=True)
class Verdict:
    exit_code: int
    lines: tuple[str, ...]


# ── pure logic (unit-tested in .github/tests/test_check_test_inventory.py) ──


def parse_inventory(payload: Mapping[str, object]) -> Inventory:
    """Build an ``Inventory`` from a ``pytest_ci_metrics`` JSON payload."""
    eligible = payload.get("eligible_not_interactive")
    if not isinstance(eligible, Mapping):
        raise GateError("metrics payload has no 'eligible_not_interactive' section")
    missing = [field for field in FIELDS if field not in eligible]
    if missing:
        raise GateError(f"metrics payload lacks counters {missing}")
    nodeids = payload.get("eligible_nodeids", [])
    if not isinstance(nodeids, list):
        raise GateError("'eligible_nodeids' must be a list")
    return Inventory(
        counts={field: int(eligible[field]) for field in FIELDS},
        nodeids=frozenset(str(nodeid) for nodeid in nodeids),
    )


def declared_reasons(messages: Iterable[str]) -> list[str]:
    """Return the ``Test-Inventory-Decrease`` reasons that are long enough to count."""
    reasons: list[str] = []
    for message in messages:
        for match in _TRAILER_RE.finditer(message):
            reason = match.group("reason").strip()
            if len(reason) >= MIN_REASON_LENGTH:
                reasons.append(reason)
    return reasons


def _listed(nodeids: Sequence[str]) -> list[str]:
    shown = [f"  - {nodeid}" for nodeid in nodeids[:MAX_LISTED]]
    if len(nodeids) > MAX_LISTED:
        shown.append(f"  … and {len(nodeids) - MAX_LISTED} more")
    return shown


def decide(comparison: Comparison, reasons: Sequence[str]) -> Verdict:
    """Turn a comparison and the declared reasons into an exit code and a report."""
    base, head = comparison.base.counts, comparison.head.counts
    delta = ", ".join(f"{field} {base[field]} -> {head[field]}" for field in FIELDS)
    lines = [f"unit-test inventory against the base: {delta}"]
    removed, added = comparison.removed, comparison.added
    if removed or added:
        lines.append(f"node ids: {len(added)} added, {len(removed)} removed or renamed")
    if removed:
        lines.append("removed or renamed node ids:")
        lines.extend(_listed(removed))

    decreases = comparison.decreases
    if not decreases:
        lines.append("no counter decreased — nothing to declare")
        return Verdict(0, tuple(lines))
    shrunk = ", ".join(f"{field} {old} -> {new}" for field, (old, new) in decreases.items())
    if reasons:
        lines.append(f"declared decrease ({shrunk}); reason(s) from {TRAILER}:")
        lines.extend(f"  - {reason}" for reason in reasons)
        return Verdict(0, tuple(lines))
    lines.append(
        f"undeclared decrease ({shrunk}): a test may not disappear silently. If the removal is "
        f"intended, add the trailer '{TRAILER}: <why these tests went>' (at least "
        f"{MIN_REASON_LENGTH} characters) to a commit of this change."
    )
    return Verdict(1, tuple(lines))


# ── git and collection ───────────────────────────────────────────────


def _git(*args: str, cwd: Path | None = None) -> str:
    process = subprocess.run(["git", *args], cwd=cwd or REPO_ROOT, capture_output=True, text=True)
    if process.returncode != 0:
        raise GateError(f"git {' '.join(args)} failed: {process.stderr.strip()}")
    return process.stdout.strip()


def resolve_base(spec: str, repo: Path | None = None) -> str:
    """Resolve ``--base`` to a commit sha.

    ``auto`` means the merge-base with ``origin/main``; when ``HEAD`` *is* that
    merge-base (a run on ``main`` itself) the first parent is used instead, so
    the gate still compares against the previous state of the branch.
    """
    if spec != "auto":
        return _git("rev-parse", "--verify", f"{spec}^{{commit}}", cwd=repo)
    head = _git("rev-parse", "HEAD", cwd=repo)
    try:
        base = _git("merge-base", "HEAD", "origin/main", cwd=repo)
    except GateError:
        base = head
    if base == head:
        base = _git("rev-parse", "--verify", "HEAD^1^{commit}", cwd=repo)
    return base


def commit_messages(base: str, repo: Path | None = None) -> list[str]:
    """Full messages of the commits in ``BASE..HEAD`` (NUL-separated to keep bodies intact)."""
    raw = _git("log", "--format=%B%x00", f"{base}..HEAD", cwd=repo)
    return [message for message in raw.split("\0") if message.strip()]


def collect(root: Path) -> Inventory:
    """Collect ``tests/unit/`` under ``root`` and return its eligible inventory.

    The plugin always comes from *this* checkout's ``.github/scripts`` so both
    sides are counted by the same code; ``tests/conftest.py`` puts the
    ``src`` of ``root`` first on ``sys.path``, so the base tests import the base
    product code, not the head one.
    """
    with tempfile.TemporaryDirectory(prefix="pytest-inventory-") as tmp:
        metrics = Path(tmp) / "metrics.json"
        env = os.environ.copy()
        env["PYTEST_CI_METRICS_FILE"] = str(metrics)
        env["PYTEST_CI_NODEIDS"] = "1"
        env["PYTHONPATH"] = os.pathsep.join(part for part in (str(SCRIPTS_DIR), env.get("PYTHONPATH", "")) if part)
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        process = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/unit/",
                "--collect-only",
                "-q",
                "-p",
                "pytest_ci_metrics",
                "-p",
                "no:cacheprovider",
            ],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
        )
        if process.returncode != 0 or not metrics.is_file():
            tail = "\n".join((process.stdout + process.stderr).splitlines()[-30:])
            raise GateError(f"test collection failed in {root}:\n{tail}")
        return parse_inventory(json.loads(metrics.read_text(encoding="utf-8")))


def collect_base(base: str) -> Inventory:
    with tempfile.TemporaryDirectory(prefix="pytest-inventory-base-") as tmp:
        worktree = Path(tmp) / "base"
        _git("worktree", "add", "--detach", "--quiet", str(worktree), base)
        try:
            return collect(worktree)
        finally:
            try:
                _git("worktree", "remove", "--force", str(worktree))
            except GateError:
                pass


# ── reporting ────────────────────────────────────────────────────────


def _out(text: str) -> None:
    sys.stdout.write(text + "\n")


def _escape(text: str) -> str:
    """Escape a workflow-command message (``%`` first, then the line breaks)."""
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _annotation(level: str, lines: Sequence[str]) -> str:
    return f"::{level} title={ANNOTATION_TITLE}::" + _escape("\n".join(lines))


def _summary(verdict: Verdict, base: str, head: str) -> str:
    status = "passed" if verdict.exit_code == 0 else "FAILED"
    body = "\n".join(verdict.lines)
    return f"### pytest inventory gate — {status}\n\nbase `{base[:12]}` → head `{head[:12]}`\n\n```text\n{body}\n```\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="auto", help="base commit, or 'auto' (merge-base with origin/main)")
    parser.add_argument("--output", type=Path, help="write the HEAD counts as JSON (for the coverage job)")
    parser.add_argument("--github-summary", action="store_true", help="append a report to $GITHUB_STEP_SUMMARY")
    args = parser.parse_args(argv)

    try:
        head_sha = _git("rev-parse", "HEAD")
        base_sha = resolve_base(args.base)
        head = collect(REPO_ROOT)
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            payload = {"eligible_not_interactive": dict(head.counts), "head": head_sha, "base": base_sha}
            args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        base = head if base_sha == head_sha else collect_base(base_sha)
        reasons = declared_reasons(commit_messages(base_sha))
    except GateError as exc:
        _out(_annotation("error", [f"cannot check the test inventory: {exc}"]))
        return 2

    verdict = decide(Comparison(base=base, head=head), reasons)
    _out("\n".join(verdict.lines))
    if verdict.exit_code != 0:
        _out(_annotation("error", verdict.lines))
    elif any(line.startswith("declared decrease") for line in verdict.lines):
        _out(_annotation("warning", verdict.lines))
    if args.github_summary and os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as handle:
            handle.write(_summary(verdict, base_sha, head_sha))
    return verdict.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
