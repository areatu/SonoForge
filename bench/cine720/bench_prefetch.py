"""Prefetch-batch cost benchmark: mimics FrameLoaderWorker._run_batch exactly."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import psutil

_REPO_SRC = str(Path(__file__).resolve().parents[2] / "src")
if _REPO_SRC not in sys.path:
    sys.path.insert(0, _REPO_SRC)

from echo_personal_tool.infrastructure.dicom_session import get_thread_dicom_session  # noqa: E402

PROC = psutil.Process()


def rss() -> float:
    return PROC.memory_info().rss / 1e6


def run(path: Path, batch: int, n_batches: int, release_heavy: bool) -> None:
    session = get_thread_dicom_session()
    lat = []
    peak = 0.0
    for b in range(n_batches):
        start = (b * batch) % 60
        t0 = time.perf_counter()
        session.open(path)
        t_open = (time.perf_counter() - t0) * 1000
        t1 = time.perf_counter()
        for i in range(start, start + batch):
            session.decode_single_frame(i % 60)
        t_dec = (time.perf_counter() - t1) * 1000
        if release_heavy:
            session.release_heavy()
        lat.append((t_open + t_dec, t_open, t_dec))
        peak = max(peak, rss())
    avg = sum(x[0] for x in lat) / len(lat)
    avg_open = sum(x[1] for x in lat) / len(lat)
    avg_dec = sum(x[2] for x in lat) / len(lat)
    tag = "release_heavy per call (pre-fix)" if release_heavy else "shared warm session (current)"
    print(
        f"  batch={batch:2d}  {tag:32s}: {avg:7.1f} ms/batch "
        f"(open/extract {avg_open:6.1f} + decode {avg_dec:5.1f})  "
        f"-> {batch/ (avg/1000):6.1f} frames/s   peak RSS {peak:.0f} MB"
    )


if __name__ == "__main__":
    p = Path(sys.argv[1])
    print(f"=== {p.name}  ({p.stat().st_size/1e6:.1f} MB) ===")
    for batch in (5, 8, 16):
        run(p, batch, 6, True)
    for batch in (5, 8, 16):
        run(p, batch, 6, False)
