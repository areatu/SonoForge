"""Playback FPS and memory diagnostics for multiframe DICOM cine.

Runtime diagnostics for identifying bottlenecks in the playback pipeline:
  - Per-frame timing (decode, cache lookup, render)
  - RSS / numpy array memory breakdown
  - FrameCache utilization and eviction stats
  - Prefetch pipeline health

Enable with ECHO_PLAYBACK_DIAG=1 environment variable.

Usage:
    from echo_personal_tool.infrastructure.playback_diagnostics import diagnostics

    # At playback start:
    diagnostics.start(fps_target=30, frame_count=120)

    # Each frame tick (from _advance_playback):
    diagnostics.on_frame_tick(frame_index, phase="cache_hit")

    # Each decode (from FrameLoaderWorker):
    diagnostics.on_decode_batch(start_idx, count, elapsed_ms)

    # At playback stop / report:
    report = diagnostics.stop()
    # report.summary() -> prints to log
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Literal

import psutil

_LOG = logging.getLogger("echo_personal_tool.playback_diag")
_ENABLED = os.environ.get("ECHO_PLAYBACK_DIAG", "0") == "1"


def _rss_mb() -> float:
    try:
        return psutil.Process().memory_info().rss / 1e6
    except Exception:
        return 0.0


def _numpy_memory_report() -> dict[str, object]:
    """Snapshot of numpy array memory: total allocated, count, dtype breakdown."""
    try:
        import numpy as np

        import gc

        gc.collect()
        arrs = [a for a in gc.get_objects() if isinstance(a, np.ndarray)]
        total_bytes = sum(a.nbytes for a in arrs)
        by_dtype: dict[str, int] = {}
        for a in arrs:
            key = str(a.dtype)
            by_dtype[key] = by_dtype.get(key, 0) + a.nbytes
        return {
            "array_count": len(arrs),
            "total_bytes": total_bytes,
            "total_mb": total_bytes / 1e6,
            "by_dtype": by_dtype,
        }
    except Exception:
        return {"array_count": 0, "total_bytes": 0, "total_mb": 0.0, "by_dtype": {}}


@dataclass
class FrameTickRecord:
    frame_index: int
    timestamp: float
    phase: str
    elapsed_ms: float = 0.0


@dataclass
class DecodeBatchRecord:
    start_idx: int
    count: int
    elapsed_ms: float


@dataclass
class PlaybackReport:
    fps_target: float
    frame_count: int
    total_elapsed_ms: float
    frame_ticks: list[FrameTickRecord]
    decode_batches: list[DecodeBatchRecord]
    rss_start_mb: float
    rss_end_mb: float
    rss_peak_mb: float
    numpy_snapshots: list[dict[str, object]]
    wall_clock_jitter_ms: list[float]

    def summary(self) -> str:
        lines: list[str] = []
        lines.append("=" * 72)
        lines.append("  PLAYBACK DIAGNOSTICS REPORT")
        lines.append("=" * 72)
        lines.append(f"  Target FPS:     {self.fps_target:.1f}")
        lines.append(f"  Total frames:   {self.frame_count}")
        lines.append(f"  Total elapsed:  {self.total_elapsed_ms:.1f} ms")

        if self.total_elapsed_ms > 0:
            actual_fps = self.frame_count / (self.total_elapsed_ms / 1000.0)
            lines.append(f"  Actual FPS:     {actual_fps:.1f}")
            lines.append(f"  FPS deficit:    {self.fps_target - actual_fps:+.1f}")

        # Frame timing stats
        if self.frame_ticks:
            deltas = [self.frame_ticks[i].elapsed_ms for i in range(1, len(self.frame_ticks))]
            if deltas:
                avg_ms = sum(deltas) / len(deltas)
                max_ms = max(deltas)
                min_ms = min(deltas)
                target_ms = 1000.0 / self.fps_target if self.fps_target > 0 else 33.3
                overdue = sum(1 for d in deltas if d > target_ms * 1.5)
                lines.append("")
                lines.append("  Frame tick timing:")
                lines.append(f"    avg:  {avg_ms:.2f} ms")
                lines.append(f"    min:  {min_ms:.2f} ms")
                lines.append(f"    max:  {max_ms:.2f} ms")
                lines.append(f"    target: {target_ms:.2f} ms")
                lines.append(f"    overdue (>1.5x): {overdue}/{len(deltas)} ({100*overdue/len(deltas):.1f}%)")

        # Wall-clock jitter
        if self.wall_clock_jitter_ms:
            jitter = self.wall_clock_jitter_ms
            avg_j = sum(jitter) / len(jitter)
            max_j = max(jitter)
            lines.append("")
            lines.append("  Wall-clock jitter (interval delta vs target):")
            lines.append(f"    avg:  {avg_j:+.2f} ms")
            lines.append(f"    max:  {max_j:+.2f} ms")

        # Decode batches
        if self.decode_batches:
            total_decoded = sum(b.count for b in self.decode_batches)
            total_decode_ms = sum(b.elapsed_ms for b in self.decode_batches)
            avg_batch_ms = total_decode_ms / len(self.decode_batches)
            avg_per_frame = total_decode_ms / total_decoded if total_decoded else 0
            lines.append("")
            lines.append("  Decode batches:")
            lines.append(f"    batches:       {len(self.decode_batches)}")
            lines.append(f"    total decoded: {total_decoded}")
            lines.append(f"    total decode:  {total_decode_ms:.1f} ms")
            lines.append(f"    avg batch:     {avg_batch_ms:.1f} ms")
            lines.append(f"    avg per frame: {avg_per_frame:.2f} ms")
            lines.append(f"    throughput:    {1000.0/avg_per_frame:.0f} frames/sec" if avg_per_frame > 0 else "    throughput:    inf")

        # Memory
        lines.append("")
        lines.append("  Memory:")
        lines.append(f"    RSS start:  {self.rss_start_mb:.1f} MB")
        lines.append(f"    RSS end:    {self.rss_end_mb:.1f} MB")
        lines.append(f"    RSS peak:   {self.rss_peak_mb:.1f} MB")
        lines.append(f"    RSS delta:  {self.rss_end_mb - self.rss_start_mb:+.1f} MB")

        if self.numpy_snapshots:
            last_np = self.numpy_snapshots[-1]
            lines.append(f"    numpy arrays:  {last_np.get('array_count', '?')}")
            lines.append(f"    numpy total:   {last_np.get('total_mb', 0):.1f} MB")
            by_dtype = last_np.get("by_dtype", {})
            if by_dtype:
                for dt, nbytes in sorted(by_dtype.items(), key=lambda x: -x[1]):
                    lines.append(f"      {dt}: {nbytes/1e6:.1f} MB")

        # Phase breakdown
        phases: dict[str, int] = {}
        for tick in self.frame_ticks:
            phases[tick.phase] = phases.get(tick.phase, 0) + 1
        if phases:
            lines.append("")
            lines.append("  Tick phases:")
            for phase, count in sorted(phases.items(), key=lambda x: -x[1]):
                lines.append(f"    {phase}: {count}")

        lines.append("=" * 72)
        return "\n".join(lines)


class PlaybackDiagnostics:
    """Collects per-frame and per-batch timing for playback bottleneck analysis."""

    def __init__(self) -> None:
        self._active = False
        self._fps_target: float = 30.0
        self._frame_count: int = 0
        self._ticks: list[FrameTickRecord] = []
        self._decode_batches: list[DecodeBatchRecord] = []
        self._numpy_snapshots: list[dict[str, object]] = []
        self._rss_start_mb: float = 0.0
        self._rss_end_mb: float = 0.0
        self._rss_peak_mb: float = 0.0
        self._wall_jitter: list[float] = []
        self._last_tick_time: float = 0.0
        self._target_interval_ms: float = 33.3

    @property
    def enabled(self) -> bool:
        return _ENABLED and self._active

    def start(self, *, fps_target: float = 30.0, frame_count: int = 0) -> None:
        if not _ENABLED:
            return
        self._active = True
        self._fps_target = fps_target
        self._frame_count = frame_count
        self._target_interval_ms = 1000.0 / fps_target if fps_target > 0 else 33.3
        self._ticks.clear()
        self._decode_batches.clear()
        self._numpy_snapshots.clear()
        self._wall_jitter.clear()
        self._rss_start_mb = _rss_mb()
        self._rss_end_mb = self._rss_start_mb
        self._rss_peak_mb = self._rss_start_mb
        self._last_tick_time = time.perf_counter()
        self._numpy_snapshots.append(_numpy_memory_report())
        _LOG.info(
            "[PLAYBACK_DIAG] start  fps_target=%.1f  frame_count=%d  rss=%.1f MB",
            fps_target,
            frame_count,
            self._rss_start_mb,
        )

    def on_frame_tick(self, frame_index: int, *, phase: str = "ok") -> None:
        if not self.enabled:
            return
        now = time.perf_counter()
        elapsed_ms = (now - self._last_tick_time) * 1000.0 if self._last_tick_time > 0 else 0.0
        self._last_tick_time = now

        jitter_ms = elapsed_ms - self._target_interval_ms
        self._wall_jitter.append(jitter_ms)

        rss = _rss_mb()
        self._rss_end_mb = rss
        if rss > self._rss_peak_mb:
            self._rss_peak_mb = rss

        tick = FrameTickRecord(
            frame_index=frame_index,
            timestamp=now,
            phase=phase,
            elapsed_ms=elapsed_ms,
        )
        self._ticks.append(tick)

        if frame_index % 30 == 0 and frame_index > 0:
            _LOG.info(
                "[PLAYBACK_DIAG] frame=%d  phase=%s  elapsed=%.1f ms  jitter=%+.1f ms  rss=%.1f MB",
                frame_index,
                phase,
                elapsed_ms,
                jitter_ms,
                rss,
            )

    def on_decode_batch(self, start_idx: int, count: int, elapsed_ms: float) -> None:
        if not self.enabled:
            return
        self._decode_batches.append(
            DecodeBatchRecord(start_idx=start_idx, count=count, elapsed_ms=elapsed_ms)
        )
        _LOG.info(
            "[PLAYBACK_DIAG] decode_batch  start=%d  count=%d  elapsed=%.1f ms  throughput=%.0f fps",
            start_idx,
            count,
            elapsed_ms,
            1000.0 * count / elapsed_ms if elapsed_ms > 0 else 0,
        )

    def snapshot_memory(self) -> None:
        """Take a numpy memory snapshot (call periodically)."""
        if not self.enabled:
            return
        self._numpy_snapshots.append(_numpy_memory_report())

    def stop(self) -> PlaybackReport:
        if not self._active:
            return PlaybackReport(
                fps_target=0, frame_count=0, total_elapsed_ms=0,
                frame_ticks=[], decode_batches=[],
                rss_start_mb=0, rss_end_mb=0, rss_peak_mb=0,
                numpy_snapshots=[], wall_clock_jitter_ms=[],
            )
        self._rss_end_mb = _rss_mb()
        total_ms = sum(t.elapsed_ms for t in self._ticks) if self._ticks else 0.0
        report = PlaybackReport(
            fps_target=self._fps_target,
            frame_count=self._frame_count,
            total_elapsed_ms=total_ms,
            frame_ticks=list(self._ticks),
            decode_batches=list(self._decode_batches),
            rss_start_mb=self._rss_start_mb,
            rss_end_mb=self._rss_end_mb,
            rss_peak_mb=self._rss_peak_mb,
            numpy_snapshots=list(self._numpy_snapshots),
            wall_clock_jitter_ms=list(self._wall_jitter),
        )
        _LOG.info("\n%s", report.summary())
        self._active = False
        return report


# Module-level singleton
diagnostics = PlaybackDiagnostics()
