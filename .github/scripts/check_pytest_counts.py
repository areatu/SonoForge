"""Fail loudly when pytest executed fewer tests than it selected.

Under pytest-xdist a crashed worker can silently drop its pending queue
(observed: 31 of 3252 GUI tests vanished with --max-worker-restart=0 and a
green-looking summary). The JUnit report written by the controller counts
every executed item; the metrics plugin counts every selected item. Any
mismatch means lost tests and must fail the job instead of passing quietly.

Usage:
    python .github/scripts/check_pytest_counts.py \
        --junit /tmp/pytest-junit.xml --metrics /tmp/pytest-metrics.json
"""

from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET


def _junit_total(path: str) -> int:
    tree = ET.parse(path)
    root = tree.getroot()
    suites = root.findall("testsuite") or [root]
    return sum(int(suite.get("tests", "0")) for suite in suites)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junit", required=True, help="JUnit XML written by pytest --junitxml")
    parser.add_argument("--metrics", required=True, help="pytest_ci_metrics.py inventory JSON")
    args = parser.parse_args()

    try:
        executed = _junit_total(args.junit)
    except (OSError, ET.ParseError) as exc:
        print(f"::error title=pytest count gate::cannot read JUnit report {args.junit}: {exc}")
        return 1
    try:
        with open(args.metrics, encoding="utf-8") as handle:
            selected = json.load(handle)["selected"]["total"]
    except (OSError, KeyError, ValueError) as exc:
        print(f"::error title=pytest count gate::cannot read metrics {args.metrics}: {exc}")
        return 1

    if executed != selected:
        print(
            "::error title=pytest count gate::"
            f"executed {executed} tests but selected {selected}; "
            + (
                "a worker likely died and dropped its queue"
                if executed < selected
                else "JUnit includes extra reports (for example a worker crash followed by rerun); "
                "the selected/executed inventory still does not match"
            )
        )
        return 1
    print(f"pytest count gate: executed {executed} of {selected} selected tests, none lost")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
