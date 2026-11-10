"""Verify that Linux logic and GUI jobs form a lossless marker partition."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

#: Counters that must agree between the inventory gate and the jobs that ran.
#: The gate itself (check_test_inventory.py, issue #473) compares them with the
#: base commit; this script only proves that the logic job and the GUI shards
#: executed exactly the inventory the gate collected. The audited ``_BASELINE``
#: literal that used to live here (20 shadowed assignments, 289 edits for 241
#: PRs) is gone — the base commit is the baseline now.
_FIELDS = ("total", "gui", "not_gui", "gui_files")


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


# The timing-budget test is run once, in isolation on GUI shard 0, and is
# intentionally excluded from the sharded pytest selection. Keep this explicit:
# the isolated run is a required CI step, while all other GUI tests must be
# selected by the six shards.
_ISOLATED_GUI_TESTS = 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--logic", required=True, type=Path)
    parser.add_argument("--gui", required=True, type=Path, nargs="+", help="one metrics JSON per GUI shard")
    parser.add_argument(
        "--expected",
        type=Path,
        help="HEAD counts written by check_test_inventory.py --output; CI always passes it",
    )
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
    missing_fields = set(_FIELDS) - eligible.keys()
    _check(
        not missing_fields,
        f"inventory is missing fields {sorted(missing_fields)}; refresh pytest_ci_metrics.py output",
    )
    if args.expected is not None:
        expected = _read(args.expected).get("eligible_not_interactive", {})
        gate = {key: expected.get(key) for key in _FIELDS}
        ran = {key: eligible[key] for key in _FIELDS}
        _check(
            gate == ran,
            f"the test jobs collected {ran}, but the inventory gate collected {gate}; "
            "both must see the same suite (check_test_inventory.py, issue #473)",
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
    sharded_gui = expected_gui - _ISOLATED_GUI_TESTS
    _check(
        gui_selected["total"] == sharded_gui,
        f"GUI shards selected {gui_selected['total']} tests; expected {sharded_gui} "
        f"because {_ISOLATED_GUI_TESTS} timing-budget test runs separately",
    )
    _check(gui_selected["gui"] == sharded_gui, "GUI shards selected a non-GUI test")
    _check(
        logic_selected["total"] + gui_selected["total"] + _ISOLATED_GUI_TESTS == eligible["total"],
        "the partition dropped or duplicated tests",
    )

    sys.stdout.write(
        "Verified pytest partition: "
        f"{eligible['total']} eligible tests = {expected_logic} logic + {sharded_gui} GUI-sharded "
        f"+ {_ISOLATED_GUI_TESTS} isolated timing-budget test across {len(shards)} GUI shards; "
        f"{eligible['interactive']} interactive tests remain excluded by the repository default.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
