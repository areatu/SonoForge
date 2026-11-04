"""Exercise the actual capacity-healer shell with a fake GitHub API."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

FAKE_GH = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["CALLS"], "a", encoding="utf-8") as f:
    f.write(json.dumps(args) + "\n")
scenario = os.environ["SCENARIO"]
query = args[args.index("--jq") + 1] if "--jq" in args else ""
if "POST" in args:
    print("{}")
elif query == ".run_attempt":
    print("3" if scenario == "cap" else "2" if scenario == "attempt" else "1")
elif query == ".status":
    print("in_progress" if scenario == "running" else "completed")
elif query == ".sha":
    if scenario == "missing_branch":
        sys.exit(1)
    print("new-sha" if scenario == "stale" else "head-sha")
elif "workflow_runs[0]" in query:
    print("101" if scenario == "newer_run" else "100")
elif "select(.conclusion" in query:
    print("11\n12")
elif query == ".[].message":
    print("The operation was canceled." if scenario == "no_capacity" else
          "The job was not acquired by Runner of type hosted even after multiple attempts")
else:
    raise SystemExit("unexpected gh call: " + repr(args))
'''


class CapacityHealerTests(unittest.TestCase):
    def run_step(self, scenario: str, repository: str = "owner/repo"):
        workflow = (ROOT / ".github/workflows/capacity-healer.yml").read_text(encoding="utf-8")
        script = textwrap.dedent(workflow.split("        run: |\n", 1)[1])
        with tempfile.TemporaryDirectory() as temporary:
            temp = Path(temporary)
            gh = temp / "gh"
            gh.write_text(FAKE_GH, encoding="utf-8")
            gh.chmod(0o755)
            calls = temp / "calls"
            env = {
                **os.environ,
                "PATH": f"{temp}{os.pathsep}{os.environ['PATH']}",
                "CALLS": str(calls),
                "SCENARIO": scenario,
                "GITHUB_REPOSITORY": "owner/repo",
                "RUN_REPOSITORY": repository,
                "RUN_ID": "100",
                "RUN_ATTEMPT": "1",
                "RUN_BRANCH": "feature/branch",
                "RUN_SHA": "head-sha",
                "WORKFLOW_ID": "42",
            }
            result = subprocess.run(["bash", "-c", script], env=env, text=True, capture_output=True)
            invocations = [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []
            posts = [args for args in invocations if "POST" in args]
            return result, posts

    def test_retries_all_failed_jobs_only_once_when_runner_was_not_acquired(self):
        result, posts = self.run_step("capacity")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(posts), 1)
        self.assertIn("repos/owner/repo/actions/runs/100/rerun-failed-jobs", posts[0])

    def test_stale_superseded_or_ineligible_runs_are_not_retried(self):
        for scenario in ("stale", "newer_run", "running", "attempt", "cap", "no_capacity"):
            with self.subTest(scenario=scenario):
                result, posts = self.run_step(scenario)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(posts, [])
        result, posts = self.run_step("capacity", repository="fork/repo")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(posts, [])

    def test_failure_to_check_branch_fails_closed(self):
        result, posts = self.run_step("missing_branch")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(posts, [])

    def test_macos_checks_keep_arm64_and_aggregate_does_not_require_macos(self):
        ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        compat = ci.split("  test_compat:\n", 1)[1].split("\n  test_regression", 1)[0]
        smoke = ci.split("  test_gui_smoke:\n", 1)[1].split("\n  test_gui:\n", 1)[0]
        for job in (compat, smoke):
            self.assertIn("name: test-", job)
            self.assertIn("matrix.os == 'macos-latest' && 'macos-15' || matrix.os", job)
            self.assertIn('test "$(uname -m)" = arm64', job)
        aggregate = ci.split("  test:\n", 1)[1].split("\n  build:\n", 1)[0]
        self.assertIn("name: test (${{ matrix.os }}, ${{ matrix.python-version }})", aggregate)
        self.assertIn("runs-on: ubuntu-latest", aggregate)
        self.assertIn("needs: [test_logic, test_compat, test_gui", aggregate)
        for workflow in ("build.yml", "release.yml"):
            text = (ROOT / ".github/workflows" / workflow).read_text(encoding="utf-8")
            job = text.split("  build-macos-apple-silicon:\n", 1)[1]
            self.assertIn("runs-on: macos-15", job)
            self.assertIn('test "$(uname -m)" = arm64', job)

    def test_concurrency_separates_heads_but_unifies_pr_and_dispatch(self):
        group = "${{ github.workflow }}-${{ github.head_ref || github.ref_name }}-${{ github.event.pull_request.head.sha || github.sha }}"
        for workflow in ("ci.yml", "build.yml"):
            with self.subTest(workflow=workflow):
                text = (ROOT / ".github/workflows" / workflow).read_text(encoding="utf-8")
                self.assertIn("  group: " + group, text)
                self.assertIn("  cancel-in-progress: true", text)


if __name__ == "__main__":
    unittest.main()
