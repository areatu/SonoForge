"""Render the round-2 layout variants into docs/images/layout-variants/ (one process per screen)."""

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
JOBS = [
    ("lay_main", "render_m1"),
    ("lay_main", "render_m2"),
    ("lay_main", "render_m3"),
    ("lay_focus", "render_f1"),
    ("lay_focus", "render_f2"),
    ("lay_report", "render_r1"),
    ("lay_report", "render_r2"),
    ("lay_report", "render_r3"),
    ("lay_ref", "render_s1"),
    ("lay_ref", "render_s2"),
    ("lay_settings", "render_o1"),
    ("lay_sheet", "render_k1"),  # crops other screens → after them
    ("lay_sheet", "render_overview"),
]

if __name__ == "__main__":
    only = set(sys.argv[1:])
    for mod, fn in JOBS:
        if only and fn not in only and mod not in only:
            continue
        if not (HERE / f"{mod}.py").exists():
            print(f"SKIP {mod}.{fn}: no module")
            continue
        code = f"import {mod}; print({mod}.{fn}())"
        r = subprocess.run([sys.executable, "-c", code], cwd=HERE, capture_output=True, text=True)
        out = (r.stdout.strip().splitlines() or [""])[-1]
        print(("OK   " if r.returncode == 0 else "FAIL ") + f"{mod}.{fn}: {out}")
        if r.returncode != 0:
            print(r.stderr[-2500:])
