"""Fail a CI gate unless every required test was collected and passed.

A test file in the repository, a green job with nothing selected, or a suite
that skipped itself are not evidence (QH-2a.1, S-12).  This check reads the
run evidence written by ``pytest_ci_metrics.py`` and enforces:

* the run produced outcomes at all and at least one test passed
  (an empty or fully skipped selection fails);
* no collection errors;
* every entry of the required-tests manifest matched at least one executed
  node (a renamed or deleted required test fails instead of vanishing);
* every node matched by a required entry passed — ``skipped``, ``xfailed``,
  ``xpassed``, ``failed`` and ``error`` all fail, unless the exact node id is
  listed in the allowed-skips manifest *with a reason*, in which case a skip
  (and only a skip) is tolerated and reported.

Manifest format (both files): one entry per line, ``#`` starts a comment,
blank lines are ignored.  An entry is a node-id prefix at file, class, test or
parametrised-case granularity::

    tests/security/test_no_credentials_in_settings.py
    tests/security/test_https_enforcement.py::TestDimseTlsContext
    tests/security/test_dicom_fuzzing.py::TestDicomUidFuzzing::test_invalid_uids_rejected

Allowed-skips entries must carry their reason after ``#`` on the same line.

Usage::

    python .github/scripts/check_required_tests.py \
        --metrics /tmp/pytest-metrics.json \
        --required .github/required-tests/security.txt \
        [--allowed-skips .github/required-tests/security-allowed-skips.txt]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PASSED = "passed"
_FAILING = ("failed", "error", "xpassed")


@dataclass
class GateResult:
    errors: list[str] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)
    satisfied: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors


def parse_manifest(text: str) -> list[str]:
    """Return the entries of a required-tests manifest (comments stripped)."""
    entries: list[str] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            entries.append(line)
    return entries


def parse_allowed_skips(text: str) -> dict[str, str]:
    """Return ``{nodeid: reason}``; an entry without a reason is a manifest error."""
    allowed: dict[str, str] = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        nodeid, _, reason = stripped.partition("#")
        nodeid = nodeid.strip()
        reason = reason.strip()
        if not reason:
            raise ValueError(f"allowed-skips line {number} has no reason: {stripped!r}")
        allowed[nodeid] = reason
    return allowed


def matches(entry: str, nodeid: str) -> bool:
    """A manifest entry matches itself, its members (``::``) and its parametrisations (``[``)."""
    return nodeid == entry or nodeid.startswith(entry + "::") or nodeid.startswith(entry + "[")


def evaluate(
    outcomes: dict[str, str],
    required: Iterable[str],
    *,
    allowed_skips: dict[str, str] | None = None,
    collection_errors: Iterable[str] = (),
) -> GateResult:
    """Pure gate decision; ``outcomes`` maps node ids to their final outcome."""
    result = GateResult()
    allowed = dict(allowed_skips or {})
    required = list(required)

    for nodeid in collection_errors:
        result.errors.append(f"collection error: {nodeid}")
    if not outcomes:
        result.errors.append("no tests were executed: the selection is empty or the run produced no evidence")
        return result
    passed = sum(1 for outcome in outcomes.values() if outcome == PASSED)
    if passed == 0:
        result.errors.append(
            f"no test passed ({len(outcomes)} executed, all skipped/failed): a fully skipped set is not a PASS"
        )
    if not required:
        result.errors.append("the required-tests manifest is empty")
        return result

    for entry in required:
        matched = {nodeid: outcome for nodeid, outcome in outcomes.items() if matches(entry, nodeid)}
        if not matched:
            result.errors.append(f"required test was not collected or not executed: {entry}")
            continue
        entry_ok = True
        for nodeid, outcome in sorted(matched.items()):
            if outcome == PASSED:
                continue
            if outcome == "skipped" and nodeid in allowed:
                result.notices.append(f"allowed skip: {nodeid} — {allowed[nodeid]}")
                continue
            entry_ok = False
            result.errors.append(f"required test did not pass: {nodeid} ({outcome})")
        if entry_ok:
            result.satisfied += 1

    unused = sorted(set(allowed) - set(outcomes))
    for nodeid in unused:
        result.notices.append(f"allowed-skips entry did not match any executed test: {nodeid}")
    return result


def _load_metrics(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"::error title=required tests::cannot read run evidence {path}: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--metrics", required=True, type=Path, help="pytest_ci_metrics.py JSON with outcomes")
    parser.add_argument("--required", required=True, type=Path, help="required-tests manifest")
    parser.add_argument("--allowed-skips", type=Path, default=None, help="allowed-skips manifest (nodeid # reason)")
    args = parser.parse_args(argv)

    metrics = _load_metrics(args.metrics)
    outcomes = metrics.get("outcomes")
    if not isinstance(outcomes, dict):
        print(
            f"::error title=required tests::{args.metrics} carries no run outcomes (plugin not loaded or run aborted)"
        )
        return 1
    try:
        required = parse_manifest(args.required.read_text(encoding="utf-8"))
        allowed = parse_allowed_skips(args.allowed_skips.read_text(encoding="utf-8")) if args.allowed_skips else {}
    except (OSError, ValueError) as exc:
        print(f"::error title=required tests::cannot read manifest: {exc}")
        return 1

    result = evaluate(
        outcomes,
        required,
        allowed_skips=allowed,
        collection_errors=metrics.get("collection_errors", ()),
    )
    counts: dict[str, int] = {}
    for outcome in outcomes.values():
        counts[outcome] = counts.get(outcome, 0) + 1
    summary = ", ".join(f"{name}={counts[name]}" for name in sorted(counts))
    for notice in result.notices:
        print(f"::notice title=required tests::{notice}")
    skipped = sorted(nodeid for nodeid, outcome in outcomes.items() if outcome in ("skipped", "xfailed"))
    reasons = metrics.get("skip_reasons", {})
    for nodeid in skipped:
        print(f"skipped: {nodeid} — {reasons.get(nodeid, '') or 'no reason recorded'}")
    for error in result.errors:
        print(f"::error title=required tests::{error}")
    if not result.ok:
        print(f"required tests gate FAILED: {result.satisfied}/{len(required)} entries satisfied; outcomes: {summary}")
        return 1
    print(
        f"required tests gate: {result.satisfied}/{len(required)} manifest entries satisfied "
        f"by {len(outcomes)} executed tests ({summary})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
