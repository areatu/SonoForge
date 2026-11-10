"""Regression tests for the base-relative test-inventory gate (issue #473, stdlib only)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / ".github" / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


gate = _load("check_test_inventory")


def _inventory(total: int, gui: int, gui_files: int, nodeids: list[str]):
    return gate.Inventory(
        counts={"total": total, "gui": gui, "not_gui": total - gui, "gui_files": gui_files},
        nodeids=frozenset(nodeids),
    )


BASE = _inventory(3, 1, 1, ["t.py::a", "t.py::b", "g.py::c"])


class DecideTests(unittest.TestCase):
    def test_equal_inventory_passes_without_declaration(self):
        verdict = gate.decide(gate.Comparison(base=BASE, head=BASE), [])
        self.assertEqual(verdict.exit_code, 0)
        self.assertIn("no counter decreased", "\n".join(verdict.lines))

    def test_growth_passes_and_needs_no_bookkeeping(self):
        head = _inventory(5, 2, 2, ["t.py::a", "t.py::b", "g.py::c", "t.py::d", "h.py::e"])
        verdict = gate.decide(gate.Comparison(base=BASE, head=head), [])
        self.assertEqual(verdict.exit_code, 0)
        self.assertIn("2 added, 0 removed", "\n".join(verdict.lines))

    def test_undeclared_decrease_fails_and_names_the_vanished_test(self):
        head = _inventory(2, 1, 1, ["t.py::a", "g.py::c"])
        verdict = gate.decide(gate.Comparison(base=BASE, head=head), [])
        report = "\n".join(verdict.lines)
        self.assertEqual(verdict.exit_code, 1)
        self.assertIn("t.py::b", report)
        self.assertIn("total 3 -> 2", report)
        self.assertIn(gate.TRAILER, report)

    def test_gui_marker_loss_is_a_decrease_too(self):
        # Same total, one test lost its gui marker: gui and gui_files go down.
        head = _inventory(3, 0, 0, ["t.py::a", "t.py::b", "g.py::c"])
        verdict = gate.decide(gate.Comparison(base=BASE, head=head), [])
        self.assertEqual(verdict.exit_code, 1)
        self.assertIn("gui 1 -> 0", "\n".join(verdict.lines))

    def test_declared_decrease_passes_and_keeps_the_reason_visible(self):
        head = _inventory(2, 1, 1, ["t.py::a", "g.py::c"])
        reason = "t.py::b duplicated t.py::a after the parser merge"
        verdict = gate.decide(gate.Comparison(base=BASE, head=head), [reason])
        report = "\n".join(verdict.lines)
        self.assertEqual(verdict.exit_code, 0)
        self.assertIn("declared decrease", report)
        self.assertIn(reason, report)
        self.assertIn("t.py::b", report)

    def test_rename_keeps_counters_and_lists_the_old_id(self):
        head = _inventory(3, 1, 1, ["t.py::a", "t.py::b_renamed", "g.py::c"])
        verdict = gate.decide(gate.Comparison(base=BASE, head=head), [])
        self.assertEqual(verdict.exit_code, 0)
        self.assertIn("t.py::b", "\n".join(verdict.lines))

    def test_long_removal_lists_are_truncated(self):
        many = [f"t.py::case_{index:03d}" for index in range(gate.MAX_LISTED + 5)]
        base = _inventory(len(many), 0, 0, many)
        head = _inventory(0, 0, 0, [])
        verdict = gate.decide(gate.Comparison(base=base, head=head), [])
        self.assertIn("… and 5 more", "\n".join(verdict.lines))


class TrailerTests(unittest.TestCase):
    def test_trailer_is_found_in_any_commit_and_case_insensitive(self):
        messages = [
            "feat: x\n\nbody",
            "chore: y\n\ntest-inventory-decrease: removed the duplicated parser cases",
        ]
        self.assertEqual(gate.declared_reasons(messages), ["removed the duplicated parser cases"])

    def test_short_or_empty_reason_does_not_count(self):
        messages = ["fix\n\nTest-Inventory-Decrease: x", "fix\n\nTest-Inventory-Decrease:   "]
        self.assertEqual(gate.declared_reasons(messages), [])

    def test_trailer_must_start_a_line(self):
        messages = ["docs: mention Test-Inventory-Decrease: in the guide for contributors"]
        self.assertEqual(gate.declared_reasons(messages), [])


class InventoryParsingTests(unittest.TestCase):
    def test_metrics_payload_is_parsed(self):
        payload = {
            "eligible_not_interactive": {"total": 2, "gui": 1, "not_gui": 1, "gui_files": 1, "interactive": 0},
            "eligible_nodeids": ["a::b", "c::d"],
        }
        inventory = gate.parse_inventory(payload)
        self.assertEqual(inventory.counts["total"], 2)
        self.assertEqual(inventory.nodeids, frozenset({"a::b", "c::d"}))

    def test_missing_counter_is_a_gate_error(self):
        with self.assertRaises(gate.GateError):
            gate.parse_inventory({"eligible_not_interactive": {"total": 2}})

    def test_annotation_escapes_percent_and_newlines(self):
        line = gate._annotation("error", ["t.py::case[50%]", "second"])
        self.assertIn("t.py::case[50%25]%0Asecond", line)
        self.assertNotIn("\n", line)


class GitTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)

        def git(*args: str) -> str:
            return subprocess.run(
                ["git", *args], cwd=self.repo, check=True, text=True, capture_output=True
            ).stdout.strip()

        self.git = git
        git("init", "-q")
        git("config", "user.name", "test")
        git("config", "user.email", "test@example.invalid")
        git("commit", "-q", "--allow-empty", "-m", "base")
        self.base = git("rev-parse", "HEAD")
        git("commit", "-q", "--allow-empty", "-m", "drop\n\nTest-Inventory-Decrease: the fixture moved to bench/")
        git("commit", "-q", "--allow-empty", "-m", "unrelated")

    def tearDown(self):
        self._tmp.cleanup()

    def test_messages_of_the_change_carry_the_trailer(self):
        messages = gate.commit_messages(self.base, repo=self.repo)
        self.assertEqual(len(messages), 2)
        self.assertEqual(gate.declared_reasons(messages), ["the fixture moved to bench/"])

    def test_base_trailer_outside_the_range_is_ignored(self):
        head_parent = self.git("rev-parse", "HEAD^1")
        self.assertEqual(gate.declared_reasons(gate.commit_messages(head_parent, repo=self.repo)), [])

    def test_auto_base_without_origin_main_is_the_first_parent(self):
        self.assertEqual(gate.resolve_base("auto", repo=self.repo), self.git("rev-parse", "HEAD^1"))

    def test_explicit_base_is_resolved_to_a_sha(self):
        self.assertEqual(gate.resolve_base("HEAD~2", repo=self.repo), self.base)

    def test_unknown_base_is_a_gate_error(self):
        with self.assertRaises(gate.GateError):
            gate.resolve_base("no-such-ref", repo=self.repo)


class PartitionExpectedTests(unittest.TestCase):
    """verify_pytest_partition.py --expected ties the test jobs to the gate inventory."""

    COUNTS = {"total": 3, "gui": 1, "not_gui": 2, "interactive": 0, "gui_files": 1, "not_gui_files": 1}

    def _write(self, directory: Path, expected_total: int) -> list[str]:
        zero = dict.fromkeys(self.COUNTS, 0)
        logic = {
            "collected": self.COUNTS,
            "eligible_not_interactive": self.COUNTS,
            "selected": {**zero, "total": 2, "not_gui": 2, "not_gui_files": 1},
        }
        # One GUI test runs in isolation, so the single shard selects nothing.
        shard = {"collected": self.COUNTS, "eligible_not_interactive": self.COUNTS, "selected": zero}
        expected = {"eligible_not_interactive": {**self.COUNTS, "total": expected_total}}
        paths = {}
        for name, payload in (("logic", logic), ("shard", shard), ("expected", expected)):
            paths[name] = directory / f"{name}.json"
            paths[name].write_text(json.dumps(payload), encoding="utf-8")
        return [
            sys.executable,
            str(SCRIPTS / "verify_pytest_partition.py"),
            "--logic",
            str(paths["logic"]),
            "--gui",
            str(paths["shard"]),
            "--expected",
            str(paths["expected"]),
        ]

    def test_matching_inventory_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(self._write(Path(tmp), 3), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Verified pytest partition", result.stdout)

    def test_jobs_running_a_different_suite_than_the_gate_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(self._write(Path(tmp), 4), capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("inventory gate collected", result.stderr)


class WiringTests(unittest.TestCase):
    def test_the_audited_literal_and_its_updater_are_gone(self):
        partition = (SCRIPTS / "verify_pytest_partition.py").read_text(encoding="utf-8")
        self.assertNotRegex(partition, r"(?m)^_BASELINE\s*=")
        self.assertFalse((SCRIPTS / "update_pytest_baseline.py").exists())

    def test_ci_runs_the_gate_against_the_base_and_feeds_the_coverage_job(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        job = workflow.split("  test_inventory:\n", 1)[1].split("\n  test_logic:\n", 1)[0]
        self.assertIn("fetch-depth: 0", job)
        self.assertIn("check_test_inventory.py", job)
        self.assertIn("--output /tmp/pytest-inventory.json", job)
        self.assertIn('base="HEAD^1"', job)
        coverage = workflow.split("  coverage:\n", 1)[1]
        self.assertIn("--expected coverage-input/inventory/pytest-inventory.json", coverage)
        self.assertNotIn("update_pytest_baseline", workflow)

    def test_the_drift_healer_no_longer_rewrites_a_baseline(self):
        healer = (ROOT / ".github" / "workflows" / "drift-healer.yml").read_text(encoding="utf-8")
        self.assertNotIn("update_pytest_baseline", healer)
        self.assertNotIn("_BASELINE", healer)


if __name__ == "__main__":
    unittest.main()
