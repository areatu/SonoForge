"""Playback diagnostics as a measuring instrument: what the report actually counts.

The audit (§5, "Измеримость") found the report could not be trusted to size a fix: every
prefetch run was recorded twice as a decode batch, buffer depth was only ever reported in
frames, and frames shown through the skip paths were not counted as shown at all.
"""

from __future__ import annotations

import pytest

from echo_personal_tool.infrastructure import playback_diagnostics as pd
from echo_personal_tool.infrastructure.playback_diagnostics import PlaybackDiagnostics


@pytest.fixture
def diag():
    """A diagnostics collector with monitoring forced on."""
    collector = PlaybackDiagnostics()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(pd, "_ENABLED", True)
        collector.start(fps_target=30.0, frame_count=60)
        yield collector
        collector.stop()


def test_decode_batch_and_round_trip_are_separate_counters(diag) -> None:
    diag.on_decode_batch(0, 5, 20.0)
    diag.on_batch_round_trip(0, 5, 35.0)

    report = diag.stop()

    assert len(report.decode_batches) == 1
    assert report.decode_batches[0].count == 5
    assert report.decode_batches[0].elapsed_ms == 20.0
    assert len(report.batch_round_trips) == 1
    assert report.batch_round_trips[0].elapsed_ms == 35.0

    summary = report.summary()
    assert "total decoded: 5" in summary
    assert "total decoded: 10" not in summary
    assert "Batch round trip" in summary


def test_summary_reports_frames_shown_and_decode_amplification(diag) -> None:
    for i in range(3):
        diag.on_frame_tick(i, phase="cache_hit")
    diag.on_frame_tick(3, phase="cache_miss")
    diag.on_decode_batch(0, 8, 16.0)

    summary = diag.stop().summary()

    # 8 decoded for 3 displayed: the miss tick is not a displayed frame.
    assert "frames shown:  3" in summary
    assert "decode amplification: 2.67 decoded per frame shown" in summary


def test_buffer_depth_is_reported_in_seconds_too(diag) -> None:
    diag.on_frame_tick(1, phase="cache_hit", buffered_frames=5, frame_time_ms=33.3)
    diag.on_frame_tick(2, phase="cache_hit", buffered_frames=15, frame_time_ms=33.3)

    report = diag.stop()
    summary = report.summary()

    assert report.frame_ticks[0].buffer_seconds == pytest.approx(5 * 33.3 / 1000.0)
    assert "Playback buffer" in summary
    assert "avg:           10.0 frames (0.33 s)" in summary
    assert "min:           5 frames (0.17 s)" in summary
    assert "empty at tick: 0/2" in summary


def test_empty_buffer_ticks_are_counted(diag) -> None:
    diag.on_frame_tick(1, phase="cache_hit", buffered_frames=0, frame_time_ms=33.3)
    diag.on_frame_tick(2, phase="cache_miss", buffered_frames=0, frame_time_ms=33.3)

    summary = diag.stop().summary()

    assert "empty at tick: 2/2" in summary


def test_buffer_section_is_absent_without_reports(diag) -> None:
    diag.on_frame_tick(1, phase="cache_hit")

    summary = diag.stop().summary()

    assert "Playback buffer" not in summary
    assert summary  # the report still renders


def test_round_trip_percentile(diag) -> None:
    for i in range(20):
        diag.on_batch_round_trip(i, 4, float(i + 1))

    summary = diag.stop().summary()

    assert "runs:          20" in summary
    assert "frames:        80" in summary
    assert "p95:           19.0 ms" in summary
    assert "max:           20.0 ms" in summary


def test_skip_phases_count_as_displayed_frames(diag) -> None:
    diag.on_frame_tick(1, phase="cache_hit")
    diag.on_frame_tick(3, phase="skip_next")
    diag.on_frame_tick(9, phase="lag_skip")
    diag.on_decode_batch(0, 6, 12.0)

    summary = diag.stop().summary()

    assert "skip_next: 1" in summary
    assert "lag_skip: 1" in summary
    # A skip puts a frame on screen: it is shown, so it belongs in the denominator of the
    # amplification ratio. Before, only cache_hit/cache_miss ticks existed and every
    # displayed skip was invisible in the report.
    assert "frames shown:  3" in summary
    assert "decode amplification: 2.00 decoded per frame shown" in summary


def test_a_new_run_starts_with_empty_counters(diag) -> None:
    diag.on_decode_batch(0, 5, 20.0)
    diag.on_batch_round_trip(0, 5, 35.0)
    diag.stop()

    diag.start(fps_target=30.0, frame_count=60)
    report = diag.stop()

    assert report.decode_batches == []
    assert report.batch_round_trips == []


def test_inactive_collector_records_nothing() -> None:
    collector = PlaybackDiagnostics()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(pd, "_ENABLED", False)
        collector.on_batch_round_trip(0, 5, 35.0)
        collector.on_frame_tick(0, phase="cache_hit", buffered_frames=3, frame_time_ms=33.3)

    assert collector._round_trips == []
    assert collector._ticks == []
