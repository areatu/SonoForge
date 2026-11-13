"""Queue depth / pending bytes under scrub and tab-switch bursts (#553).

Informational, like the other benches: it records wall time and the gate's bounded
counters instead of asserting a hardware-dependent latency.  Run with:

    ECHO_BENCH=1 pytest tests/bench/test_decode_queue_bench.py -v -s
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from echo_personal_tool.application.decode_gate import DecodeGate, DecodePriority

_BENCH = pytest.mark.skipif(
    os.environ.get("ECHO_BENCH", "") != "1",
    reason="Set ECHO_BENCH=1 to run benchmarks",
)


class _Request:
    def __init__(self, path: Path, start: int, frames: int, priority: DecodePriority) -> None:
        self.decode_path = path
        self.priority = priority
        self.requested_frames = frames
        self.frame_range = (start, start + frames)
        self.estimated_frame_bytes = 512 * 512 * 2
        self.cancelled = False

    def cancel_parked(self) -> None:
        self.cancelled = True


@_BENCH
def test_bench_scrub_and_tab_switch_queue_bounds(tmp_path: Path) -> None:
    gate = DecodeGate(max_parked_requests_per_file=8, max_parked_frames_per_file=128)
    owner = _Request(tmp_path / "cine.dcm", 0, 1, DecodePriority.INTERACTIVE)
    assert gate.enter(owner) is True

    # Scrub: 200 interactive targets on the owning file. Coalescing must keep the
    # parked queue at one, no matter how fast the user moves.
    started = time.perf_counter()
    for index in range(200):
        request = _Request(tmp_path / "cine.dcm", index % 60, 1, DecodePriority.INTERACTIVE)
        gate.enter(request)
    scrub_seconds = time.perf_counter() - started
    scrub_stats = gate.stats()
    assert scrub_stats.parked_requests == 1

    # Tab switch: 20 files, each with a speculative prefetch batch that nobody drains.
    started = time.perf_counter()
    for tab in range(20):
        path = tmp_path / f"tab-{tab}.dcm"
        tab_owner = _Request(path, 0, 1, DecodePriority.INTERACTIVE)
        gate.enter(tab_owner)
        for batch in range(4):
            gate.enter(_Request(path, batch * 30, 30, DecodePriority.PLAYBACK))
    switch_seconds = time.perf_counter() - started
    switch_stats = gate.stats()
    assert switch_stats.parked_requests <= gate._max_parked_requests  # noqa: SLF001 - bench introspection
    assert switch_stats.pending_bytes <= gate._max_pending_bytes  # noqa: SLF001
    print(
        f"\n  scrub: {scrub_seconds * 1000:.2f} ms, depth {scrub_stats.parked_requests}, "
        f"pending {scrub_stats.pending_bytes / 1e6:.1f} MB; "
        f"20 tabs: {switch_seconds * 1000:.2f} ms, depth {switch_stats.parked_requests}, "
        f"pending {switch_stats.pending_bytes / 1e6:.1f} MB, dropped {switch_stats.dropped_requests}"
    )
