"""Render every main-window mockup into docs/images/main-window-variants/.

Each screen runs in its own interpreter: PySide6 6.12 on CPython 3.11 hits a
None-refcount bug ("none_dealloc") after very many QPainter calls in one process.
"""

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
JOBS = [
    ("screen_a", "render_a1"),
    ("screen_a", "render_a2"),
    ("screen_b", "render_b1"),
    ("screen_b", "render_b2"),
    ("screen_c", "render_c1"),
    ("screen_c", "render_c2"),
    ("screen_d", "render_d1"),
    ("screen_d", "render_d2"),
    ("screen_e", "render_e1"),  # crops A1/B1 → must run after them
    ("screen_e", "render_overview"),  # uses A1, B1, C1, D1
]

if __name__ == "__main__":
    only = set(sys.argv[1:])
    for mod, fn in JOBS:
        if only and fn not in only and mod not in only:
            continue
        code = f"import {mod}; print({mod}.{fn}())"
        r = subprocess.run([sys.executable, "-c", code], cwd=HERE, capture_output=True, text=True)
        out = (r.stdout.strip().splitlines() or [""])[-1]
        print(("OK   " if r.returncode == 0 else "FAIL ") + f"{mod}.{fn}: {out}")
        if r.returncode != 0:
            print(r.stderr[-2000:])
