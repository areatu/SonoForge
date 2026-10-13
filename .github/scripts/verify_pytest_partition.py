"""Verify that Linux logic and GUI jobs form a lossless marker partition."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_BASELINE = {"total": 6704, "gui": 3252, "not_gui": 3452, "gui_files": 165}


def _read(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Cannot read pytest inventory {path}: {exc}") from exc


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"pytest marker partition is incomplete: {message}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--logic", required=True, type=Path)
    parser.add_argument("--gui", required=True, type=Path)
    args = parser.parse_args()

    logic = _read(args.logic)
    gui = _read(args.gui)
    logic_collected = logic["collected"]
    gui_collected = gui["collected"]
    _check(logic_collected == gui_collected, "the two jobs collected different test inventories")
    _check(logic_collected["interactive"] == 0, "the unit inventory gained interactive tests excluded by CI")

    eligible = logic["eligible_not_interactive"]
    _check(eligible == gui["eligible_not_interactive"], "the default interactive-test filter differs")
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
    gui_selected = gui["selected"]
    _check(logic_selected["total"] == expected_logic, "logic job did not select every eligible non-GUI test")
    _check(logic_selected["not_gui"] == expected_logic, "logic job selected a GUI test")
    _check(logic_selected["gui"] == 0, "logic job selected a GUI test")
    _check(logic_selected["interactive"] == 0, "logic job selected an interactive test")

    _check(gui_selected["total"] == expected_gui, "GUI job did not select every eligible GUI test")
    _check(gui_selected["gui"] == expected_gui, "GUI job selected a non-GUI test")
    _check(gui_selected["not_gui"] == 0, "GUI job selected a non-GUI test")
    _check(gui_selected["interactive"] == 0, "GUI job selected an interactive test")
    _check(
        logic_selected["total"] + gui_selected["total"] == eligible["total"],
        "the partition dropped or duplicated tests",
    )

    sys.stdout.write(
        "Verified lossless pytest partition: "
        f"{eligible['total']} eligible tests = {expected_logic} logic + {expected_gui} GUI; "
        f"{eligible['interactive']} interactive tests remain excluded by the repository default.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
