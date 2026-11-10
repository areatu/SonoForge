"""#417: the 3.11/3.12/3.13 mypy matrix must be a real required gate.

A matrix that loses a cell, skips the interpreter check, or is not wired into
the aggregate ``test`` job still looks green in the checks list. These tests
mutate a copy of ci.yml and prove the wiring guard actually fails.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).parents[2]
_WORKFLOW = _ROOT / ".github" / "workflows" / "ci.yml"

_spec = importlib.util.spec_from_file_location("check_typecheck_matrix", _ROOT / "scripts/check_typecheck_matrix.py")
assert _spec is not None and _spec.loader is not None
guard = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = guard
_spec.loader.exec_module(guard)


def _workflow() -> str:
    return _WORKFLOW.read_text(encoding="utf-8")


def test_committed_workflow_has_the_full_matrix_and_aggregate_gate() -> None:
    assert guard.inspect(_workflow()) == []


def test_matrix_version_list_is_parsed_exactly() -> None:
    assert guard.matrix_versions('  matrix:\n    python-version: ["3.11", "3.12", "3.13"]\n') == [
        "3.11",
        "3.12",
        "3.13",
    ]
    assert guard.matrix_versions("  no matrix here\n") == []


def test_dropping_a_python_cell_fails_the_guard() -> None:
    broken = _workflow().replace('python-version: ["3.11", "3.12", "3.13"]', 'python-version: ["3.11", "3.12"]')
    assert broken != _workflow()
    problems = guard.inspect(broken)
    assert any("3.13" in problem and "matrix is" in problem for problem in problems)


def test_replacing_the_job_with_a_noop_fails_the_guard() -> None:
    broken = _workflow().replace(
        "run: bash scripts/typecheck_matrix.sh ${{ matrix.python-version }}",
        'run: echo "mypy skipped"',
    )
    assert broken != _workflow()
    problems = guard.inspect(broken)
    assert any("scripts/typecheck_matrix.sh with the matrix cell" in problem for problem in problems)


def test_dropping_typecheck_from_the_aggregate_needs_fails_the_guard() -> None:
    broken = _workflow().replace("package_smoke, coverage, typecheck]", "package_smoke, coverage]")
    assert broken != _workflow()
    problems = guard.inspect(broken)
    assert any("does not list typecheck in needs" in problem for problem in problems)


def test_dropping_the_result_check_from_the_aggregate_gate_fails_the_guard() -> None:
    broken = _workflow().replace(' || "$TYPECHECK_RESULT" != "success"', "")
    assert broken != _workflow()
    problems = guard.inspect(broken)
    assert any("does not check TYPECHECK_RESULT" in problem for problem in problems)


def test_dropping_presentation_mypy_ratchet_from_lint_fails_the_guard() -> None:
    broken = _workflow().replace("run: python scripts/check_mypy_presentation.py --github-summary", 'run: echo "skip"')
    assert broken != _workflow()
    problems = guard.inspect(broken)
    assert any("presentation mypy ratchet" in problem for problem in problems)
