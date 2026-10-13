"""The required-tests CI gate is non-vacuous (QH-2a.1, S-12, acceptance A-13).

Two layers are pinned down here:

* the pure decision in ``.github/scripts/check_required_tests.py`` — a
  missing, skipped, xfailed, xpassed or failed required test is never a PASS,
  an empty or fully skipped run is never a PASS, and an allowed skip needs a
  reason;
* the run evidence written by ``.github/scripts/pytest_ci_metrics.py`` —
  a real pytest subprocess with the plugin loaded produces the outcomes the
  gate consumes, so "a plugin that silently records nothing" also fails.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _ROOT / ".github" / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolve string annotations through sys.modules[module.__name__].
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


gate = _load("check_required_tests")
metrics_plugin = _load("pytest_ci_metrics")


# ── pure decision ───────────────────────────────────────────────────


def test_manifest_entries_match_file_class_test_and_parametrisation_prefixes():
    assert gate.matches("tests/security/test_a.py", "tests/security/test_a.py::TestX::test_y")
    assert gate.matches("tests/security/test_a.py::TestX", "tests/security/test_a.py::TestX::test_y[1]")
    assert gate.matches("tests/security/test_a.py::TestX::test_y", "tests/security/test_a.py::TestX::test_y[1]")
    assert gate.matches("tests/security/test_a.py::test_z", "tests/security/test_a.py::test_z")
    # A prefix must stop at a node boundary: test_ab is not test_a.
    assert not gate.matches("tests/security/test_a.py::test_z", "tests/security/test_a.py::test_zz")
    assert not gate.matches("tests/security/test_a.py", "tests/security/test_ab.py::test_z")


def test_all_required_passed_is_the_only_green_outcome():
    outcomes = {"t.py::test_a": "passed", "t.py::test_b[1]": "passed", "t.py::test_b[2]": "passed"}
    result = gate.evaluate(outcomes, ["t.py::test_a", "t.py::test_b"])
    assert result.ok
    assert result.satisfied == 2


@pytest.mark.parametrize("outcome", ["skipped", "xfailed", "xpassed", "failed", "error"])
def test_a_required_test_that_did_not_pass_fails_the_gate(outcome):
    outcomes = {"t.py::test_a": "passed", "t.py::test_b": outcome}
    result = gate.evaluate(outcomes, ["t.py::test_a", "t.py::test_b"])
    assert not result.ok
    assert any("t.py::test_b" in error and outcome in error for error in result.errors)


def test_a_missing_required_test_fails_instead_of_vanishing():
    result = gate.evaluate({"t.py::test_a": "passed"}, ["t.py::test_a", "t.py::test_renamed"])
    assert not result.ok
    assert any("not collected" in error and "test_renamed" in error for error in result.errors)


def test_a_fully_skipped_run_is_not_a_pass():
    outcomes = {"t.py::test_a": "skipped", "t.py::test_b": "skipped"}
    result = gate.evaluate(outcomes, ["t.py"])
    assert not result.ok
    assert any("fully skipped" in error for error in result.errors)


def test_an_empty_run_is_not_a_pass():
    result = gate.evaluate({}, ["t.py"])
    assert not result.ok
    assert any("no tests were executed" in error for error in result.errors)


def test_an_empty_manifest_is_not_a_pass():
    result = gate.evaluate({"t.py::test_a": "passed"}, [])
    assert not result.ok


def test_a_collection_error_fails_even_when_everything_else_passed():
    result = gate.evaluate({"t.py::test_a": "passed"}, ["t.py::test_a"], collection_errors=["broken_test.py"])
    assert not result.ok
    assert any("collection error" in error for error in result.errors)


def test_an_allowed_skip_tolerates_a_skip_but_nothing_else():
    allowed = {"t.py::test_b": "needs a live PACS (QH-2b slice 2)"}
    skipped = gate.evaluate({"t.py::test_a": "passed", "t.py::test_b": "skipped"}, ["t.py"], allowed_skips=allowed)
    assert skipped.ok
    assert any("allowed skip" in notice for notice in skipped.notices)
    failed = gate.evaluate({"t.py::test_a": "passed", "t.py::test_b": "failed"}, ["t.py"], allowed_skips=allowed)
    assert not failed.ok
    xfailed = gate.evaluate({"t.py::test_a": "passed", "t.py::test_b": "xfailed"}, ["t.py"], allowed_skips=allowed)
    assert not xfailed.ok


def test_manifests_strip_comments_and_allowed_skips_need_a_reason():
    text = "# S-09\n tests/security/test_a.py  # inline comment\n\ntests/security/test_b.py::TestX\n"
    assert gate.parse_manifest(text) == ["tests/security/test_a.py", "tests/security/test_b.py::TestX"]
    assert gate.parse_allowed_skips("t.py::test_b  # live PACS only\n") == {"t.py::test_b": "live PACS only"}
    with pytest.raises(ValueError):
        gate.parse_allowed_skips("t.py::test_b\n")


# ── run evidence from the metrics plugin ────────────────────────────


def _report(when: str, outcome: str, *, wasxfail: bool = False):
    report = SimpleNamespace(when=when, outcome=outcome, nodeid="t.py::x")
    report.passed = outcome == "passed"
    report.failed = outcome == "failed"
    report.skipped = outcome == "skipped"
    if wasxfail:
        report.wasxfail = "expected"
    return report


def test_phase_reports_classify_like_the_terminal_summary():
    classify = metrics_plugin._classify
    assert classify(_report("setup", "passed")) is None
    assert classify(_report("setup", "failed")) == "error"
    assert classify(_report("setup", "skipped")) == "skipped"
    assert classify(_report("setup", "skipped", wasxfail=True)) == "xfailed"
    assert classify(_report("call", "passed")) == "passed"
    assert classify(_report("call", "failed")) == "failed"
    assert classify(_report("call", "skipped", wasxfail=True)) == "xfailed"
    assert classify(_report("call", "passed", wasxfail=True)) == "xpassed"
    assert classify(_report("teardown", "passed")) is None
    assert classify(_report("teardown", "failed")) == "error"


_SAMPLE_SUITE = textwrap.dedent(
    """
    import pytest

    def test_passes():
        assert True

    @pytest.mark.skip(reason="prerequisite missing")
    def test_skips():
        assert False

    @pytest.mark.xfail(reason="known gap", strict=False)
    def test_xfails():
        assert False

    @pytest.mark.parametrize("n", [1, 2])
    def test_param(n):
        assert n in (1, 2)
    """
)


def _run_sample_suite(tmp_path: Path) -> dict:
    """Run a tiny suite in a clean subprocess with the metrics plugin loaded."""
    (tmp_path / "test_sample.py").write_text(_SAMPLE_SUITE, encoding="utf-8")
    (tmp_path / "pytest.ini").write_text("[pytest]\naddopts = -p no:cacheprovider\n", encoding="utf-8")
    metrics = tmp_path / "metrics.json"
    env = {key: value for key, value in os.environ.items() if not key.startswith(("PYTEST_", "COV_CORE_"))}
    env.pop("COVERAGE_PROCESS_START", None)
    env["PYTEST_CI_METRICS_FILE"] = str(metrics)
    env["PYTHONPATH"] = str(_SCRIPTS)
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(tmp_path / "test_sample.py"),
            "-q",
            "-p",
            "pytest_ci_metrics",
            "-p",
            "no:pytest-qt",
            "-p",
            "no:xdist",
            "--rootdir",
            str(tmp_path),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert metrics.is_file(), completed.stdout + completed.stderr
    return json.loads(metrics.read_text(encoding="utf-8"))


def test_the_plugin_records_every_executed_node_with_its_final_outcome(tmp_path: Path):
    payload = _run_sample_suite(tmp_path)
    outcomes = payload["outcomes"]
    assert outcomes["test_sample.py::test_passes"] == "passed"
    assert outcomes["test_sample.py::test_skips"] == "skipped"
    assert outcomes["test_sample.py::test_xfails"] == "xfailed"
    assert outcomes["test_sample.py::test_param[1]"] == "passed"
    assert outcomes["test_sample.py::test_param[2]"] == "passed"
    assert payload["collection_errors"] == []
    assert payload["exit_status"] == 0
    assert "prerequisite missing" in payload["skip_reasons"]["test_sample.py::test_skips"]
    # The inventory section written at collection time survives the merge.
    assert payload["selected"]["total"] == 5


def test_the_gate_consumes_real_run_evidence(tmp_path: Path):
    payload = _run_sample_suite(tmp_path)
    outcomes = payload["outcomes"]
    assert gate.evaluate(outcomes, ["test_sample.py::test_passes", "test_sample.py::test_param"]).ok
    # The skipped and the xfailed test cannot close a required scenario.
    assert not gate.evaluate(outcomes, ["test_sample.py::test_skips"]).ok
    assert not gate.evaluate(outcomes, ["test_sample.py::test_xfails"]).ok
    # Requiring the whole file therefore fails too, unless the skip is explicitly allowed —
    # and even then the xfail still blocks it.
    assert not gate.evaluate(outcomes, ["test_sample.py"]).ok
    allowed = {"test_sample.py::test_skips": "documented prerequisite"}
    assert not gate.evaluate(outcomes, ["test_sample.py"], allowed_skips=allowed).ok


def test_the_command_line_entry_point_reports_the_decision(tmp_path: Path):
    payload = _run_sample_suite(tmp_path)
    metrics = tmp_path / "metrics.json"
    metrics.write_text(json.dumps(payload), encoding="utf-8")
    good = tmp_path / "required-good.txt"
    good.write_text("# sample\ntest_sample.py::test_passes\ntest_sample.py::test_param\n", encoding="utf-8")
    bad = tmp_path / "required-bad.txt"
    bad.write_text("test_sample.py::test_skips\ntest_sample.py::test_missing\n", encoding="utf-8")
    assert gate.main(["--metrics", str(metrics), "--required", str(good)]) == 0
    assert gate.main(["--metrics", str(metrics), "--required", str(bad)]) == 1
    # Evidence without outcomes (plugin not loaded, run aborted) is not a PASS either.
    metrics.write_text(json.dumps({"selected": {"total": 5}}), encoding="utf-8")
    assert gate.main(["--metrics", str(metrics), "--required", str(good)]) == 1
