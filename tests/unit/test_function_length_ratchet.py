"""Tests for the >200-line function ratchet."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_function_length  # noqa: E402


def test_existing_long_functions_cannot_grow() -> None:
    current = {"module.py::Worker.run": 201}
    baseline = {"module.py::Worker.run": 202}

    assert check_function_length.find_violations(current, baseline) == ()
    assert check_function_length.find_violations({"module.py::Worker.run": 203}, baseline)


def test_new_long_functions_are_rejected_and_short_functions_are_ignored(tmp_path: Path) -> None:
    module = tmp_path / "sample.py"
    module.write_text("def too_long():\n" + "    pass\n" * 200, encoding="utf-8")
    long_functions = check_function_length.find_long_functions(tmp_path)

    assert len(long_functions) == 1
    assert check_function_length.find_violations(long_functions, {})
    assert check_function_length.find_violations({}, {}) == ()


def test_committed_ratchet_baseline_matches_the_source_tree() -> None:
    baseline = json.loads((REPO_ROOT / "scripts" / "function_length_baseline.json").read_text(encoding="utf-8"))
    current = check_function_length.find_long_functions(check_function_length.DEFAULT_SOURCE)

    assert baseline["functions"] == current
