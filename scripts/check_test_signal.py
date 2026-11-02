#!/usr/bin/env python3
"""Ratchet the tests that cannot fail (issue #327).

A test count measures volume, not protection. A test that never asserts, never
expects an exception and never compares anything passes whatever the code does,
so a green suite says nothing about it. This script keeps four promises:

* **a test needs a verifying signal** — an ``assert`` that can fail, a
  ``pytest.raises`` / ``warns`` / ``fail`` (a tripwire inside a callback is a
  real negative check), a Qt ``waitSignal`` / ``waitUntil`` (they raise on
  timeout), ``jsonschema.validate`` / ``check_schema`` (they raise on a
  mismatch) or a call whose name starts with ``assert``
  (``mock.assert_called_once_with``, ``np.testing.assert_allclose``,
  ``self.assertEqual``, a local ``_assert_valid`` helper). ``assert True``,
  ``assert (cond, "msg")`` and ``assert cond or True`` are always true and do
  not count; ``approx`` and a variable called ``snapshot`` verify nothing on
  their own, and neither does a bare ``validate()`` — the project's own
  validators return their findings instead of raising. The check is static
  and deliberately simple: when a test delegates its checks to a helper, name
  the helper ``assert_*`` so the intent is visible to the next reader;
* **a measurement is not a verification** — a test that takes the
  pytest-benchmark ``benchmark`` fixture exists to produce a timing. It is
  reported on its own line and never counted as debt; so is a manual
  diagnostic marked ``@pytest.mark.interactive``, which ``addopts`` keeps out of
  every default and CI run and which prints a report for a human;
* **the debt only goes down** — tests that already lack a signal are listed by
  node id in ``scripts/test_signal_baseline.json``. A new one fails the check;
  one that was fixed, removed or renamed has to leave the list (``--fix``), so
  the list is always exactly the debt and a repaired test cannot silently
  regress;
* **an intentional no-assert test is explicit** — ``@pytest.mark.smoke`` *and*
  an entry with a reason under ``"smoke"`` in the baseline, so every such test
  is a reviewed decision and not a free pass.

Also reported, never gated: the share of tests with at most one ``assert`` and
of tests without any ``assert`` statement. A creation test such as
``assert widget is not None`` still passes the gate; strengthening those is the
slice-by-slice work this ratchet protects. They are not gated on purpose — a
limit on them would only teach people to append empty assertions.

Run ``python scripts/check_test_signal.py --fix`` after strengthening or
removing a test; the baseline commit is the ratchet's memory. ``--fix`` creates
the file when it is missing and otherwise only removes entries — it never lets
the debt grow. Standard library only: the CI lint job installs nothing else.

Exit codes: 0 — within the baseline, 1 — violations, 2 — usage/parse/baseline
errors.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = REPO_ROOT / "tests"
DEFAULT_BASELINE = REPO_ROOT / "scripts" / "test_signal_baseline.json"

BASELINE_VERSION = 1
BASELINE_COMMENT = (
    "Ratchet for issue #327 (python scripts/check_test_signal.py). 'no_signal' is the debt: tests with nothing that "
    "can fail them, by node id. It only shrinks - run --fix after strengthening or removing a test. 'smoke' maps the "
    "node id of every @pytest.mark.smoke test to the reason it has no assertion. 'metrics' is the reference the PR "
    "report compares against."
)

#: File names pytest collects by default.
TEST_FILE_PATTERNS = ("test_*.py", "*_test.py")

#: Calls that make a test fail when the behaviour is wrong. On top of these any
#: call whose name starts with ``assert`` (leading underscores ignored) counts.
SIGNAL_CALLS = frozenset(
    {
        "deprecated_call",
        "fail",
        "raises",
        "waitCallback",
        "waitSignal",
        "waitSignals",
        "waitUntil",
        "warns",
        "check_schema",
    }
)

#: Library calls recognised only under their full name: the bare name would also match the project's own
#: ``validate()`` methods, which return findings instead of raising.
QUALIFIED_SIGNAL_CALLS = frozenset({"jsonschema.validate"})

#: Fixtures whose job is to measure, not to verify.
MEASUREMENT_FIXTURES = frozenset({"benchmark"})

#: Marker for a test that is intentionally "does not raise" only.
SMOKE_MARKER = "smoke"

#: Marker for a manual diagnostic: never part of a default or CI run.
MANUAL_MARKER = "interactive"

FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


@dataclass(frozen=True)
class CollectedTest:
    """One test function as seen by a static scan (parametrization is not expanded)."""

    node_id: str
    line: int
    asserts: int
    has_signal: bool
    measurement: bool
    smoke: bool
    manual: bool = False

    @property
    def is_debt(self) -> bool:
        """True when nothing can fail the test and nobody declared that on purpose."""
        return not (self.has_signal or self.measurement or self.smoke or self.manual)


@dataclass(frozen=True)
class Baseline:
    """What the repository has agreed to carry."""

    no_signal: frozenset[str]
    smoke: dict[str, str]
    metrics: dict[str, int]


# ── static analysis ─────────────────────────────────────────────────────────


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _is_always_false(test: ast.expr) -> bool:
    return isinstance(test, ast.Constant) and not test.value


def _is_always_true(test: ast.expr) -> bool:
    """``assert True`` / ``assert 1`` / ``assert (cond, "msg")`` / ``assert cond or True`` never fail.

    The operands of an ``or`` are not a check on their own: ``cond or True`` is
    true whatever ``cond`` says, so it is the same as the bare call ``cond``.
    """
    if isinstance(test, ast.Constant):
        return bool(test.value)
    if isinstance(test, ast.Tuple):
        return bool(test.elts)
    if isinstance(test, ast.BoolOp):
        verdicts = [_is_always_true(operand) for operand in test.values]
        return any(verdicts) if isinstance(test.op, ast.Or) else all(verdicts)
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        return _is_always_false(test.operand)
    return False


def _dotted_name(expr: ast.expr) -> str:
    """``a.b.c`` for a chain of attribute accesses on a plain name, ``""`` otherwise."""
    parts: list[str] = []
    while isinstance(expr, ast.Attribute):
        parts.append(expr.attr)
        expr = expr.value
    if not isinstance(expr, ast.Name):
        return ""
    parts.append(expr.id)
    return ".".join(reversed(parts))


def _is_signal_call(node: ast.Call) -> bool:
    name = _call_name(node)
    return (
        name in SIGNAL_CALLS
        or name.lstrip("_").lower().startswith("assert")
        or _dotted_name(node.func) in QUALIFIED_SIGNAL_CALLS
    )


def analyze_body(function: FunctionNode) -> tuple[int, bool]:
    """Return ``(assert statements, whether anything can fail the test)``.

    Nested functions count: a callback defined inside the test and asserting on
    the data it receives is still part of what the test verifies.
    """
    asserts = 0
    signal = False
    for node in ast.walk(function):
        if isinstance(node, ast.Assert):
            asserts += 1
            signal = signal or not _is_always_true(node.test)
        elif isinstance(node, ast.Call):
            signal = signal or _is_signal_call(node)
    return asserts, signal


def _marker_name(expr: ast.expr) -> str | None:
    """``pytest.mark.smoke`` / ``pytest.mark.smoke(...)`` / ``mark.smoke`` → ``"smoke"``."""
    if isinstance(expr, ast.Call):
        expr = expr.func
    if not isinstance(expr, ast.Attribute):
        return None
    owner = expr.value
    if isinstance(owner, ast.Attribute) and owner.attr == "mark":
        return expr.attr
    if isinstance(owner, ast.Name) and owner.id == "mark":
        return expr.attr
    return None


def _marker_names(expressions: Iterable[ast.expr]) -> frozenset[str]:
    return frozenset(name for name in map(_marker_name, expressions) if name)


def _assigned_markers(body: list[ast.stmt]) -> frozenset[str]:
    """Markers applied through ``pytestmark = ...`` in a module or class body."""
    names: frozenset[str] = frozenset()
    for node in body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "pytestmark" for target in node.targets):
            continue
        value = node.value
        items = value.elts if isinstance(value, ast.List | ast.Tuple) else [value]
        names |= _marker_names(items)
    return names


def _base_name(base: ast.expr) -> str:
    if isinstance(base, ast.Attribute):
        return base.attr
    if isinstance(base, ast.Name):
        return base.id
    return ""


def _is_test_class(node: ast.ClassDef) -> bool:
    """pytest collects ``Test*`` classes and every ``unittest.TestCase`` subclass."""
    return node.name.startswith("Test") or any(_base_name(base).endswith("TestCase") for base in node.bases)


def _argument_names(function: FunctionNode) -> frozenset[str]:
    arguments = function.args
    return frozenset(arg.arg for arg in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs))


def _iter_tests(
    body: list[ast.stmt], prefix: str, inherited: frozenset[str]
) -> Iterator[tuple[str, FunctionNode, frozenset[str]]]:
    """Yield ``(qualified name, function, markers in effect)`` the way pytest collects them."""
    for node in body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith("test"):
            yield f"{prefix}{node.name}", node, inherited | _marker_names(node.decorator_list)
        elif isinstance(node, ast.ClassDef) and _is_test_class(node):
            markers = inherited | _marker_names(node.decorator_list) | _assigned_markers(node.body)
            yield from _iter_tests(node.body, f"{prefix}{node.name}::", markers)


def iter_test_files(root: Path) -> list[Path]:
    found = {path for pattern in TEST_FILE_PATTERNS for path in root.rglob(pattern) if "__pycache__" not in path.parts}
    return sorted(found)


def scan_tests(root: Path, *, relative_to: Path) -> tuple[dict[str, CollectedTest], list[str]]:
    """Scan every test module under ``root``; node ids are relative to ``relative_to``.

    Returns the tests keyed by node id and the files that could not be parsed.
    A name defined twice is collected once by pytest (the last definition wins),
    so it is recorded once here too.
    """
    tests: dict[str, CollectedTest] = {}
    errors: list[str] = []
    for path in iter_test_files(root):
        relative = path.relative_to(relative_to).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError, OSError) as exc:
            errors.append(f"{relative}: cannot parse ({exc})")
            continue
        for qualified, function, markers in _iter_tests(tree.body, "", _assigned_markers(tree.body)):
            asserts, signal = analyze_body(function)
            node_id = f"{relative}::{qualified}"
            tests[node_id] = CollectedTest(
                node_id=node_id,
                line=function.lineno,
                asserts=asserts,
                has_signal=signal,
                measurement=bool(_argument_names(function) & MEASUREMENT_FIXTURES),
                smoke=SMOKE_MARKER in markers,
                manual=MANUAL_MARKER in markers,
            )
    return tests, errors


# ── metrics and report ──────────────────────────────────────────────────────


def summarize(tests: dict[str, CollectedTest]) -> dict[str, int]:
    """Counts for the report and for the reference numbers stored in the baseline."""
    values = list(tests.values())
    return {
        "tests": len(values),
        "no_signal": sum(test.is_debt for test in values),
        "measurement": sum(test.measurement and not test.has_signal and not test.smoke for test in values),
        "manual": sum(
            test.manual and not test.has_signal and not test.smoke and not test.measurement for test in values
        ),
        "smoke": sum(test.smoke for test in values),
        "le1_assert": sum(test.asserts <= 1 for test in values),
        "no_assert_statement": sum(test.asserts == 0 for test in values),
    }


def _share(count: int, total: int) -> str:
    return f"{count} ({count / total:.1%})" if total else str(count)


def render_line(metrics: dict[str, int], baseline: Baseline) -> str:
    """One line for the job log."""
    total = metrics["tests"]
    return (
        f"{total} tests: {metrics['no_signal']} without a verifying signal (baseline {len(baseline.no_signal)}), "
        f"{metrics['measurement']} measurements (benchmark fixture), {metrics['manual']} manual (interactive), "
        f"{metrics['smoke']} smoke; "
        f"<=1 assert in {_share(metrics['le1_assert'], total)}, "
        f"no assert statement in {_share(metrics['no_assert_statement'], total)}"
    )


def _delta(now: int, recorded: int | None) -> str:
    if recorded is None:
        return "—"
    return "0" if now == recorded else f"{now - recorded:+d}"


def _metric_rows(metrics: dict[str, int], baseline: Baseline) -> list[tuple[str, str, int, int | None]]:
    """``(label, text for "Now", value now, value in the baseline)`` per table row."""
    total = metrics["tests"]
    recorded = baseline.metrics
    return [
        ("Tests", str(total), total, recorded.get("tests")),
        (
            "**Without a verifying signal** (debt, gated: may only go down)",
            str(metrics["no_signal"]),
            metrics["no_signal"],
            len(baseline.no_signal),
        ),
        (
            "Measurements (`benchmark` fixture, not debt)",
            str(metrics["measurement"]),
            metrics["measurement"],
            recorded.get("measurement"),
        ),
        (
            "Manual diagnostics (`interactive`, never run in CI)",
            str(metrics["manual"]),
            metrics["manual"],
            recorded.get("manual"),
        ),
        (
            "Explicit `smoke` tests (reason in the baseline)",
            str(metrics["smoke"]),
            metrics["smoke"],
            len(baseline.smoke),
        ),
        (
            "With ≤1 `assert` (informational)",
            _share(metrics["le1_assert"], total),
            metrics["le1_assert"],
            recorded.get("le1_assert"),
        ),
        (
            "Without any `assert` statement (informational)",
            _share(metrics["no_assert_statement"], total),
            metrics["no_assert_statement"],
            recorded.get("no_assert_statement"),
        ),
    ]


def render_markdown(metrics: dict[str, int], baseline: Baseline, violations: tuple[str, ...]) -> str:
    """The table shown on the workflow run page (``$GITHUB_STEP_SUMMARY``)."""
    lines = ["### Test signal (#327)", "", "| Metric | Now | Baseline | Δ |", "|---|---:|---:|---:|"]
    for label, now_text, now_value, recorded_value in _metric_rows(metrics, baseline):
        baseline_text = "—" if recorded_value is None else str(recorded_value)
        lines.append(f"| {label} | {now_text} | {baseline_text} | {_delta(now_value, recorded_value)} |")
    if violations:
        lines += ["", "**Violations**", ""]
        lines += [f"- `{violation}`" for violation in violations]
    return "\n".join(lines) + "\n"


def _emit_github_summary(markdown: str) -> None:
    """Append to ``$GITHUB_STEP_SUMMARY`` in CI, print locally."""
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(markdown)
    else:
        sys.stdout.write(markdown)


# ── baseline ────────────────────────────────────────────────────────────────


def load_baseline(path: Path) -> Baseline:
    """Read and validate the baseline; raises ``OSError``/``ValueError``/``KeyError``."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != BASELINE_VERSION:
        raise ValueError(f"unsupported baseline version in {path}: {data.get('version')!r}")
    no_signal = data["no_signal"]
    smoke = data["smoke"]
    if not (isinstance(no_signal, list) and all(isinstance(node_id, str) for node_id in no_signal)):
        raise ValueError("'no_signal' must be a list of node ids")
    if not isinstance(smoke, dict) or not all(
        isinstance(node_id, str) and isinstance(reason, str) and reason.strip() for node_id, reason in smoke.items()
    ):
        raise ValueError("'smoke' must map node ids to a non-empty reason")
    metrics = {str(name): int(value) for name, value in data.get("metrics", {}).items()}
    return Baseline(no_signal=frozenset(no_signal), smoke=dict(smoke), metrics=metrics)


def write_baseline(
    path: Path, tests: dict[str, CollectedTest], *, no_signal: Iterable[str], smoke: dict[str, str]
) -> None:
    payload = {
        "version": BASELINE_VERSION,
        "comment": BASELINE_COMMENT,
        "metrics": summarize(tests),
        "smoke": dict(sorted(smoke.items())),
        "no_signal": sorted(no_signal),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def find_violations(tests: dict[str, CollectedTest], baseline: Baseline) -> tuple[str, ...]:
    """Everything that stops the check from passing, new problems first."""
    debt = {node_id for node_id, test in tests.items() if test.is_debt}
    marked = {node_id for node_id, test in tests.items() if test.smoke}
    violations: list[str] = []
    for node_id in sorted(debt - baseline.no_signal):
        violations.append(
            f"{node_id} (line {tests[node_id].line}): new test without a verifying signal — assert on the behaviour; "
            'a deliberate "does not raise" test needs @pytest.mark.smoke and a reason under "smoke" in the baseline'
        )
    for node_id in sorted(marked - baseline.smoke.keys()):
        violations.append(
            f'{node_id} (line {tests[node_id].line}): smoke test without a reason — add it under "smoke" in '
            "scripts/test_signal_baseline.json"
        )
    for node_id in sorted(baseline.no_signal - debt):
        violations.append(
            f"{node_id}: stale baseline entry — the test now verifies something, was removed or renamed; "
            "run `python scripts/check_test_signal.py --fix`"
        )
    for node_id in sorted(baseline.smoke.keys() - marked):
        violations.append(
            f"{node_id}: stale smoke entry — the test is gone or lost its marker; "
            "run `python scripts/check_test_signal.py --fix`"
        )
    return tuple(violations)


def fix_baseline(path: Path, tests: dict[str, CollectedTest]) -> int:
    """Lower the baseline after a cleanup; create it when missing; never let it grow."""
    debt = {node_id for node_id, test in tests.items() if test.is_debt}
    marked = {node_id for node_id, test in tests.items() if test.smoke}
    created = not path.exists()
    try:
        previous = Baseline(frozenset(debt), {}, {}) if created else load_baseline(path)
    except (OSError, ValueError, KeyError) as exc:
        sys.stderr.write(f"error: cannot read {path}: {exc}\n")
        return 2
    grown = sorted(debt - previous.no_signal)
    unexplained = sorted(marked - previous.smoke.keys())
    if grown or unexplained:
        sys.stderr.write("refusing to raise the bar — --fix only removes entries:\n")
        for node_id in grown:
            sys.stderr.write(f"  new test without a verifying signal: {node_id}\n")
        for node_id in unexplained:
            sys.stderr.write(f"  smoke test without a reason in the baseline: {node_id}\n")
        sys.stderr.write(
            "a legacy test that was only renamed or moved keeps its entry: change its node id in the baseline "
            "by hand, then run --fix again\n"
        )
        return 1
    write_baseline(
        path,
        tests,
        no_signal=debt,
        smoke={node_id: reason for node_id, reason in previous.smoke.items() if node_id in marked},
    )
    verb = "created" if created else "refreshed"
    sys.stdout.write(
        f"test-signal baseline {verb}: {len(debt)} tests without a verifying signal (was {len(previous.no_signal)})\n"
    )
    return 0


# ── command line ────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ratchet the tests that cannot fail (issue #327).")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="directory with the test modules")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE, help="baseline JSON file")
    parser.add_argument(
        "--relative-to", type=Path, default=None, help="directory node ids are relative to (default: parent of --root)"
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="lower the baseline after a cleanup (creates it when missing; never adds a test)",
    )
    parser.add_argument(
        "--github-summary",
        action="store_true",
        help="append the metrics table to $GITHUB_STEP_SUMMARY (stdout when unset)",
    )
    args = parser.parse_args(argv)

    root = args.root.resolve()
    relative_to = (args.relative_to or root.parent).resolve()
    tests, parse_errors = scan_tests(root, relative_to=relative_to)
    if parse_errors:
        sys.stderr.write(
            "error: cannot analyse the tests:\n" + "\n".join(f"  {error}" for error in parse_errors) + "\n"
        )
        return 2
    if not tests:
        sys.stderr.write(f"error: no tests found under {root} — wrong --root?\n")
        return 2
    if args.fix:
        return fix_baseline(args.baseline, tests)

    try:
        baseline = load_baseline(args.baseline)
    except (OSError, ValueError, KeyError) as exc:
        sys.stderr.write(
            f"error: cannot read {args.baseline}: {exc}\ncreate it with `python scripts/check_test_signal.py --fix`\n"
        )
        return 2

    metrics = summarize(tests)
    violations = find_violations(tests, baseline)
    if args.github_summary:
        _emit_github_summary(render_markdown(metrics, baseline, violations))
    if violations:
        sys.stderr.write(f"test-signal ratchet failed ({len(violations)} problem(s)):\n")
        sys.stderr.write("\n".join(f"  {violation}" for violation in violations) + "\n")
        sys.stderr.write(render_line(metrics, baseline) + "\n")
        return 1
    sys.stdout.write(f"test-signal ratchet passed: {render_line(metrics, baseline)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
