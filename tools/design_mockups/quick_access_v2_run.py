"""Render each second-round quick-access concept in its own PySide process.

Same reason as ``quick_access_run.py``: after a few dozen QPainter canvases in one
CPython process, PySide6's teardown raises ``none_dealloc``; a fresh process per
canvas keeps the run deterministic.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
JOBS = (
    "render_11_active_tool",
    "render_12_two_tiers",
    "render_13_tool_in_step",
    "render_overview",
)


def main() -> int:
    selected = set(sys.argv[1:])
    for job in JOBS:
        if selected and job not in selected:
            continue
        code = f"import quick_access_v2; print(quick_access_v2.{job}())"
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=HERE,
            capture_output=True,
            text=True,
            check=False,
        )
        output = (result.stdout.strip().splitlines() or [""])[-1]
        print(("OK   " if result.returncode == 0 else "FAIL ") + f"{job}: {output}")  # noqa: T201
        if result.returncode != 0:
            print(result.stderr[-2500:])  # noqa: T201
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
