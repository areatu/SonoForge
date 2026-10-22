"""Process-CPU wrapper: how many cores does playback actually burn?

Runs any harness from this folder and reports user+system CPU seconds and the average
number of cores used. Run the same command twice (e.g. ``--seconds 8`` and ``--seconds 1``)
and subtract to isolate the playback phase from interpreter/import/startup cost::

    cores_during_playback = (cpu_8s - cpu_1s) / (wall_8s - wall_1s)
    cpu_ms_per_frame      = 1000 * cores_during_playback / achieved_fps

Usage::

    QT_QPA_PLATFORM=offscreen python bench/cine720/bench_cpu.py \\
        bench/cine720/bench_playback_fixes.py <cine.dcm> --frames 60 --seconds 8
"""

from __future__ import annotations

import os
import runpy
import sys
import time


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    script = sys.argv[1]
    sys.argv = sys.argv[1:]

    wall_start = time.perf_counter()
    cpu_start = os.times()
    try:
        runpy.run_path(script, run_name="__main__")
    except SystemExit:
        pass
    cpu_end = os.times()
    wall = time.perf_counter() - wall_start
    cpu = (cpu_end.user - cpu_start.user) + (cpu_end.system - cpu_start.system)
    print(f"[cpuwrap] wall={wall:.2f}s cpu_user+sys={cpu:.2f}s -> cores={cpu / wall:.2f}")


if __name__ == "__main__":
    main()
