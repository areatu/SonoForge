#!/usr/bin/env python3
"""Check or refresh the audited ``_BASELINE`` of ``verify_pytest_partition.py``.

Usage:

    uv run python .github/scripts/update_pytest_baseline.py --check  # CI gate, runs before the test jobs
    uv run python .github/scripts/update_pytest_baseline.py --fix    # after adding/removing/renaming tests

``--check`` collects ``tests/unit/`` once (no test execution) and fails when
the eligible inventory no longer matches the recorded baseline — the same
comparison the coverage job performs, but minutes earlier. ``--fix`` rewrites
the LAST ``_BASELINE`` assignment (Python keeps only the final binding, so an
assignment inserted above it is shadowed) and prints the delta; commit that
file together with the test change.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PARTITION_SCRIPT = REPO_ROOT / ".github" / "scripts" / "verify_pytest_partition.py"
_BASELINE_RE = re.compile(r"^_BASELINE = \{[^\n]*\}$", re.MULTILINE)
_FIELDS = ("total", "gui", "not_gui", "gui_files")


def collect_inventory() -> dict[str, int]:
    """Collect ``tests/unit/`` once and return the eligible inventory."""
    scripts_dir = REPO_ROOT / ".github" / "scripts"
    with tempfile.TemporaryDirectory(prefix="pytest-baseline-") as tmp:
        metrics_file = Path(tmp) / "pytest-metrics.json"
        env = os.environ.copy()
        env["PYTEST_CI_METRICS_FILE"] = str(metrics_file)
        env["PYTHONPATH"] = os.pathsep.join(part for part in (str(scripts_dir), env.get("PYTHONPATH", "")) if part)
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
            ],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        if process.returncode != 0 or not metrics_file.is_file():
            tail = "\n".join((process.stdout + process.stderr).splitlines()[-30:])
            raise SystemExit(
                "::error title=pytest baseline gate::test collection failed before the baseline check\n" + tail
            )
        payload = json.loads(metrics_file.read_text(encoding="utf-8"))
    return {field: int(payload["eligible_not_interactive"][field]) for field in _FIELDS}


def _last_baseline(text: str) -> tuple[re.Match[str], dict[str, int], int]:
    matches = list(_BASELINE_RE.finditer(text))
    if not matches:
        raise SystemExit(f"no _BASELINE assignment found in {PARTITION_SCRIPT}")
    last = matches[-1]
    recorded = ast.literal_eval(last.group(0).split("=", 1)[1].strip())
    return last, recorded, len(matches)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="verify the recorded baseline (default; CI gate)")
    mode.add_argument("--fix", action="store_true", help="rewrite the LAST _BASELINE assignment with fresh counts")
    args = parser.parse_args(argv)

    collected = collect_inventory()
    text = PARTITION_SCRIPT.read_text(encoding="utf-8")
    last, recorded, assignments = _last_baseline(text)

    if recorded == collected:
        print(f"pytest baseline matches the audited inventory: {collected}")
        return 0

    diff = ", ".join(
        f"{field} {recorded[field]} -> {collected[field]}" for field in _FIELDS if recorded[field] != collected[field]
    )
    if not args.fix:
        print(
            "::error title=pytest baseline gate::eligible suite inventory changed from the audited baseline "
            f"{recorded} to {collected} ({diff}); run "
            "`uv run python .github/scripts/update_pytest_baseline.py --fix` and commit "
            ".github/scripts/verify_pytest_partition.py together with the test change"
        )
        return 1

    comment = f"# auto-refresh {date.today().isoformat()} (update_pytest_baseline.py --fix): {diff}."
    new_line = "_BASELINE = {" + ", ".join(f'"{field}": {collected[field]}' for field in _FIELDS) + "}"
    PARTITION_SCRIPT.write_text(text[: last.start()] + comment + "\n" + new_line + text[last.end() :], encoding="utf-8")
    print(f"refreshed the last of {assignments} _BASELINE assignments (earlier ones stay as history): {diff}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
