"""Verify that Linux logic and GUI jobs form a lossless marker partition."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# QH-1e: 111 synthetic cases; QH-4a: 4 crash-diagnostic cases;
# QH-1b.2 slice 1: 20 BSA-freshness cases (tests/unit/test_bsa_freshness.py);
# QH-1b.2 slice 2: 53 cases for the single manual BSA and the persisted BSA
# provenance (tests/unit/test_bsa_provenance.py plus controller/panel/report/PDF
# and persistence additions); tracker: 23 cases for the plan-driven Projects
# sync engine (tests/unit/test_project_sync.py, logic). No file changed its gui marker.
_BASELINE = {"total": 6995, "gui": 3294, "not_gui": 3701, "gui_files": 168}


def _read(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Cannot read pytest inventory {path}: {exc}") from exc


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"pytest marker partition is incomplete: {message}")


def _summed(section: str, inventories: list[dict[str, Any]]) -> dict[str, int]:
    """Sum one inventory section over GUI shards.

    Shards hold disjoint file sets, so file counts sum exactly like test counts.
    """
    keys = ("total", "gui", "not_gui", "interactive", "gui_files", "not_gui_files")
    return {key: sum(inv[section][key] for inv in inventories) for key in keys}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--logic", required=True, type=Path)
    parser.add_argument("--gui", required=True, type=Path, nargs="+", help="one metrics JSON per GUI shard")
    args = parser.parse_args()

    logic = _read(args.logic)
    shards = [_read(path) for path in args.gui]
    _check(shards, "no GUI shard inventories provided")
    gui_collected = _summed("collected", shards)
    gui_eligible = _summed("eligible_not_interactive", shards)
    gui_selected = _summed("selected", shards)

    logic_collected = logic["collected"]
    _check(gui_collected == logic_collected, "the GUI shards collected a different test inventory than logic")
    _check(logic_collected["interactive"] == 0, "the unit inventory gained interactive tests excluded by CI")

    eligible = logic["eligible_not_interactive"]
    for index, shard in enumerate(shards):
        _check(
            shard["eligible_not_interactive"] == shard["collected"],
            f"GUI shard {index} disagrees with the default interactive-test filter",
        )
    _check(gui_eligible == eligible, "the GUI shards disagree with the default interactive-test filter")
    missing_fields = _BASELINE.keys() - eligible.keys()
    _check(
        not missing_fields,
        f"inventory is missing baseline fields {sorted(missing_fields)}; refresh pytest_ci_metrics.py output",
    )
    baseline = {key: eligible[key] for key in _BASELINE}
    _check(
        baseline == _BASELINE,
        f"eligible suite inventory changed from the audited baseline {_BASELINE} to {baseline}; "
        "review the test-set change and update this baseline deliberately",
    )
    expected_logic = eligible["not_gui"]
    expected_gui = eligible["gui"]
    _check(expected_logic + expected_gui == eligible["total"], "GUI and non-GUI counts do not sum to the suite")

    logic_selected = logic["selected"]
    _check(logic_selected["total"] == expected_logic, "logic job did not select every eligible non-GUI test")
    _check(logic_selected["not_gui"] == expected_logic, "logic job selected a GUI test")
    _check(logic_selected["gui"] == 0, "logic job selected a GUI test")
    _check(logic_selected["interactive"] == 0, "logic job selected an interactive test")

    for index, shard in enumerate(shards):
        selected = shard["selected"]
        _check(selected["interactive"] == 0, f"GUI shard {index} selected an interactive test")
        _check(selected["not_gui"] == 0, f"GUI shard {index} selected a non-GUI test")
    _check(gui_selected["total"] == expected_gui, "GUI shards did not select every eligible GUI test")
    _check(gui_selected["gui"] == expected_gui, "GUI shards selected a non-GUI test")
    _check(
        logic_selected["total"] + gui_selected["total"] == eligible["total"],
        "the partition dropped or duplicated tests",
    )

    sys.stdout.write(
        "Verified lossless pytest partition: "
        f"{eligible['total']} eligible tests = {expected_logic} logic + {expected_gui} GUI "
        f"across {len(shards)} GUI shards; "
        f"{eligible['interactive']} interactive tests remain excluded by the repository default.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
