"""Regression and real-pytest tests for lossless, file-preserving CI sharding."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / ".github/scripts"
sys.path.insert(0, str(SCRIPTS))
import merge_logic_shards as merger  # noqa: E402


def evidence(index: int, count: int = 3) -> dict:
    eligible = [f"test_{i}.py::test_ok" for i in range(count)]
    counts = {"total": count, "not_gui": count, "gui": 0, "interactive": 0, "gui_files": 0, "not_gui_files": count}
    selected = {**dict.fromkeys(counts, 0), "total": 1, "not_gui": 1, "not_gui_files": 1}
    return {
        "shard": {"index": index, "count": count},
        "collected": counts,
        "eligible_not_interactive": counts,
        "eligible_nodeids": eligible,
        "eligible_logic_nodeids": eligible,
        "selected": selected,
        "selected_nodeids": [eligible[index]],
        "outcomes": {eligible[index]: "passed"},
        "collection_errors": [],
        "exit_status": 0,
        "durations": {eligible[index]: {"setup": 0.1, "call": 0.2, "teardown": 0.3}},
    }


class MergeTests(unittest.TestCase):
    def setUp(self):
        self.shards = [evidence(i) for i in range(3)]

    def test_disjoint_complete_run_merges_outcomes_and_phase_timings(self):
        merged = merger.merge(self.shards, 3)
        self.assertEqual(merged["selected"]["total"], 3)
        self.assertEqual(set(merged["outcomes"]), set(merged["eligible_logic_nodeids"]))
        self.assertEqual(len(merged["durations"]), 3)
        summary = merger.timing_summary(merged, "Linux")
        self.assertIn("Setup, s", summary)
        self.assertIn("test_0.py", summary)
        self.assertIn("0.30", summary)

    def test_missing_extra_or_duplicate_shards_fail(self):
        for shards in (self.shards[:2], self.shards + self.shards[:1], [self.shards[0]] * 3):
            with self.subTest(shards=len(shards)), self.assertRaises(ValueError):
                merger.merge(shards, 3)

    def test_failed_crashed_empty_inconsistent_or_lost_runs_fail(self):
        changes = [
            ("exit_status", 1),
            ("exit_status", None),
            ("collection_errors", ["bad.py"]),
            ("collection_errors", None),
            ("selected_nodeids", []),
            ("selected_nodeids", ["unexpected.py::test_ok"]),
            ("selected_nodeids", ["test_1.py::test_ok"]),
            ("selected_nodeids", ["test_0.py::test_ok"] * 2),
            ("eligible_logic_nodeids", ["different.py::test_ok"]),
            ("eligible_nodeids", []),
            ("outcomes", {}),
            ("outcomes", {"test_0.py::test_ok": "failed"}),
            ("outcomes", {"test_0.py::test_ok": "error"}),
            ("outcomes", {"test_0.py::test_ok": "xpassed"}),
            ("shard", {"index": 0, "count": 2}),
            ("shard", {"index": 9, "count": 3}),
        ]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                shards = copy.deepcopy(self.shards)
                shards[0][key] = value
                with self.assertRaises(ValueError):
                    merger.merge(shards, 3)

    def test_duplicate_selection_cannot_be_hidden_by_equal_counts(self):
        shards = copy.deepcopy(self.shards)
        shards[1]["selected_nodeids"] = shards[0]["selected_nodeids"]
        shards[1]["outcomes"] = shards[0]["outcomes"]
        with self.assertRaisesRegex(ValueError, "duplicated"):
            merger.merge(shards, 3)

    def test_one_file_must_not_be_split_between_shards(self):
        shards = copy.deepcopy(self.shards)
        names = [f"same.py::test_{i}" for i in range(3)]
        for i, shard in enumerate(shards):
            shard.update(
                eligible_nodeids=names,
                eligible_logic_nodeids=names,
                selected_nodeids=[names[i]],
                outcomes={names[i]: "passed"},
            )
        with self.assertRaisesRegex(ValueError, "file was split"):
            merger.merge(shards, 3)

    def test_missing_test_and_counter_drift_fail(self):
        for field in ("eligible_not_interactive", "collected", "selected"):
            shards = copy.deepcopy(self.shards)
            shards[0][field]["total"] += 1
            with self.subTest(field=field), self.assertRaises(ValueError):
                merger.merge(shards, 3)
        shards = copy.deepcopy(self.shards)
        for shard in shards:
            shard["eligible_logic_nodeids"] = [*shard["eligible_logic_nodeids"], "missing.py::test_ok"]
            shard["eligible_nodeids"] = [*shard["eligible_nodeids"], "missing.py::test_ok"]
        with self.assertRaisesRegex(ValueError, "missing"):
            merger.merge(shards, 3)

    def test_skip_is_preserved_for_required_gate_not_promoted_to_pass(self):
        self.shards[0]["outcomes"]["test_0.py::test_ok"] = "skipped"
        self.shards[0]["skip_reasons"] = {"test_0.py::test_ok": "missing dependency"}
        merged = merger.merge(self.shards, 3)
        self.assertEqual(merged["outcomes"]["test_0.py::test_ok"], "skipped")
        self.assertIn("missing dependency", merged["skip_reasons"].values())


class RealPytestTests(unittest.TestCase):
    def setUp(self):
        # These tools are installed at locked versions in the lint job too.
        self.assertIsNotNone(importlib.util.find_spec("pytest"))
        self.assertIsNotNone(importlib.util.find_spec("xdist"))
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "pytest.ini").write_text("[pytest]\nmarkers =\n gui: Qt\n interactive: manual\n")
        for i in range(1, 7):
            (self.root / f"test_{i}.py").write_text(
                f"import pytest\n@pytest.mark.parametrize('n', range({i}))\ndef test_ok(n):\n    assert n >= 0\n"
            )
        (self.root / "test_excluded.py").write_text(
            "import pytest\n@pytest.mark.gui\ndef test_gui():\n    assert False\n"
            "@pytest.mark.interactive\ndef test_manual():\n    assert False\n"
        )

    def run_shard(self, index, workers):
        metrics = self.root / f"metrics-{index}.json"
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTEST_", "COV_CORE_"))}
        env.update(PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONPATH=str(SCRIPTS), PYTEST_CI_METRICS_FILE=str(metrics))
        command = [
            sys.executable,
            "-m",
            "pytest",
            "--noconftest",
            "-p",
            "pytest_ci_metrics",
            "-m",
            "not gui and not interactive",
            "--ci-shard-index",
            str(index),
            "--ci-shard-count",
            "3",
            "-q",
        ]
        if workers:
            command += ["-p", "xdist.plugin", "-n", str(workers), "--dist", "loadfile"]
        result = subprocess.run(command, cwd=self.root, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(metrics.read_text())

    def test_serial_and_xdist_shards_preserve_exact_inventory_and_outcomes(self):
        plans = []
        for workers in (0, 2):
            shards = [self.run_shard(i, workers) for i in range(3)]
            merged = merger.merge(shards, 3)
            self.assertEqual(len(merged["outcomes"]), 21)
            self.assertEqual(merged["eligible_not_interactive"]["total"], 22)
            self.assertEqual(merged["collected"]["total"], 23)
            self.assertTrue(all(value == "passed" for value in merged["outcomes"].values()))
            self.assertTrue(
                all(set(phases) == {"setup", "call", "teardown"} for phases in merged["durations"].values())
            )
            # Weights 1..6 distribute exactly 7 items per shard, with no file split.
            self.assertEqual([s["selected"]["total"] for s in shards], [7, 7, 7])
            plans.append([s["selected_nodeids"] for s in shards])
        self.assertEqual(plans[0], plans[1])

    def test_invalid_shard_options_fail_closed(self):
        env = {**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONPATH": str(SCRIPTS)}
        for options in (
            ["--ci-shard-index", "0"],
            ["--ci-shard-count", "3"],
            ["--ci-shard-index", "0", "--ci-shard-count", "0"],
            ["--ci-shard-index", "3", "--ci-shard-count", "3"],
        ):
            with self.subTest(options=options):
                result = subprocess.run(
                    [sys.executable, "-m", "pytest", "--noconftest", "-p", "pytest_ci_metrics", *options],
                    cwd=self.root,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("require 0 <=", result.stdout + result.stderr)

    def test_cli_merge_and_required_formulas_consume_complete_run(self):
        for i in range(3):
            self.run_shard(i, 0)
        output = self.root / "merged.json"
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "merge_logic_shards.py"),
                "--inputs",
                *[str(self.root / f"metrics-{i}.json") for i in range(3)],
                "--shards",
                "3",
                "--output",
                str(output),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        manifest = self.root / "required.txt"
        manifest.write_text("test_1.py\ntest_6.py\n")
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "check_required_tests.py"),
                "--metrics",
                str(output),
                "--required",
                str(manifest),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        manifest.write_text("test_1.py::test_missing\n")
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "check_required_tests.py"),
                "--metrics",
                str(output),
                "--required",
                str(manifest),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertNotEqual(result.returncode, 0)


class WorkflowWiringTests(unittest.TestCase):
    def test_documentation_contracts_run_in_fast_lint_without_qt(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()
        lint = workflow.split("  lint:\n", 1)[1].split("  typecheck:\n", 1)[0]
        self.assertIn('"pytest-timeout==$(python .github/scripts/locked_version.py pytest-timeout)"', lint)
        self.assertIn('PYTEST_DISABLE_PLUGIN_AUTOLOAD: "1"', lint)
        self.assertIn("--noconftest -p pytest_timeout -o addopts= tests/unit/test_docs_links.py -q", lint)

    def test_all_five_cells_have_three_required_shards(self):
        import re

        workflow = (ROOT / ".github/workflows/ci.yml").read_text()
        logic = workflow.split("  test_logic:\n", 1)[1].split("  test_compat:\n", 1)[0]
        compat = workflow.split("  test_compat:\n", 1)[1].split("  logic_evidence:\n", 1)[0]
        self.assertIn("shard: [0, 1, 2]", logic)
        entries = re.findall(r'- os: (\S+)\n\s+python-version: "([^"]+)"\n\s+shard: (\d+)', compat)
        self.assertEqual(
            set(entries),
            {
                (os_name, python, str(i))
                for os_name, python in [
                    ("macos-latest", "3.11"),
                    ("windows-latest", "3.11"),
                    ("ubuntu-latest", "3.12"),
                    ("ubuntu-latest", "3.13"),
                ]
                for i in range(3)
            },
        )
        self.assertEqual(len(entries), 12)
        for section in (logic, compat):
            self.assertIn("fail-fast: false", section)
            self.assertIn("--ci-shard-index ${{ matrix.shard }} --ci-shard-count 3", section)
            self.assertIn("check_pytest_counts.py", section)
            self.assertIn("--dist loadfile --max-worker-restart=2", section)
        self.assertIn("if: runner.os == 'Windows' && matrix.shard == 0", compat)

    def test_evidence_coverage_and_final_gate_require_every_shard(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()
        evidence_job = workflow.split("  logic_evidence:\n", 1)[1].split("  test_regression:\n", 1)[0]
        self.assertIn("needs: [test_inventory, test_logic, test_compat]", evidence_job)
        self.assertIn("--shards 3", evidence_job)
        self.assertIn("check_required_tests.py", evidence_job)
        self.assertIn(".github/required-tests/formulas.txt", evidence_job)
        self.assertIn(
            "ubuntu-latest-py3.11 ubuntu-latest-py3.12 ubuntu-latest-py3.13 windows-latest-py3.11 macos-latest-py3.11",
            evidence_job,
        )
        coverage = workflow.split("  coverage:\n", 1)[1].split("  test:\n", 1)[0]
        self.assertIn("logic_evidence", coverage)
        self.assertIn("pattern: coverage-data-logic-shard-*", coverage)
        self.assertIn("for shard in 0 1 2; do", coverage)
        self.assertIn("coverage-input/data/.coverage.logic$shard", coverage)
        self.assertIn("verify_pytest_partition.py --require-nodeids", coverage)
        for floor in ("--fail-under=80", "--fail-under=88", "--fail-under=82", "--fail-under=50", "--fail-under=68"):
            self.assertIn(floor, coverage)
        aggregate = workflow.split("  test:\n", 1)[1].split("  build:\n", 1)[0]
        self.assertIn("LOGIC_EVIDENCE_RESULT: ${{ needs.logic_evidence.result }}", aggregate)
        self.assertIn('"$LOGIC_EVIDENCE_RESULT" != "success"', aggregate)


class ExactPartitionTests(unittest.TestCase):
    def run_partition(self, mutate):
        isolated = "tests/unit/test_layout_v2_window.py::test_preset_switch_fits_the_300ms_budget"
        nodes = ["a.py::test_a", "b.py::test_b", "c.py::test_c", isolated]
        counts = {"total": 4, "gui": 2, "not_gui": 2, "interactive": 0, "gui_files": 2, "not_gui_files": 2}
        logic = {
            "collected": counts,
            "eligible_not_interactive": counts,
            "eligible_nodeids": nodes,
            "selected_nodeids": nodes[:2],
            "selected": {**dict.fromkeys(counts, 0), "total": 2, "not_gui": 2, "not_gui_files": 2},
        }
        gui = {
            "collected": counts,
            "eligible_not_interactive": counts,
            "selected_nodeids": nodes[2:3],
            "selected": {**dict.fromkeys(counts, 0), "total": 1, "gui": 1, "gui_files": 1},
        }
        expected = {"eligible_nodeids": nodes, "eligible_not_interactive": counts}
        mutate(logic, gui, expected)
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for name, payload in [("logic", logic), ("gui", gui), ("expected", expected)]:
                (directory / f"{name}.json").write_text(json.dumps(payload))
            return subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "verify_pytest_partition.py"),
                    "--require-nodeids",
                    "--logic",
                    str(directory / "logic.json"),
                    "--gui",
                    str(directory / "gui.json"),
                    "--expected",
                    str(directory / "expected.json"),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )

    def test_exact_node_partition_passes(self):
        result = self.run_partition(lambda *args: None)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_equal_counts_cannot_hide_wrong_missing_or_duplicated_nodeids(self):
        for replacement in (["a.py::test_a"], ["unexpected.py::test_c"], [], None):
            with self.subTest(replacement=replacement):
                result = self.run_partition(lambda logic, gui, expected: gui.update(selected_nodeids=replacement))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("partition", result.stderr)


if __name__ == "__main__":
    unittest.main()
