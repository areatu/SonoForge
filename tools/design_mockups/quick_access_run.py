"""Render each quick-access concept in its own PySide process."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
JOBS = (
    "render_01_labeled_toolbar",
    "render_02_pinned_tool_rail",
    "render_03_anatomy_board",
)


def main() -> int:
    selected = set(sys.argv[1:])
    for job in JOBS:
        if selected and job not in selected:
            continue
        code = f"import quick_access; print(quick_access.{job}())"
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
