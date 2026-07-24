"""Unit tests for doppler_trace_points.finalize_vti_trace_points."""

from __future__ import annotations

from echo_personal_tool.domain.services.doppler_trace_points import (
    finalize_vti_trace_points,
)


class TestFinalizeVtiTracePoints:
    # ── short-circuit paths (< 3 points) ───────────────────────────

    def test_empty(self) -> None:
        assert finalize_vti_trace_points(()) == ()

    def test_single_point(self) -> None:
        result = finalize_vti_trace_points([(10.0, 50.0)])
        assert result == ((10.0, 50.0),)

    def test_two_points(self) -> None:
        result = finalize_vti_trace_points([(10.0, 50.0), (20.0, 60.0)])
        assert result == ((10.0, 50.0), (20.0, 60.0))

    def test_short_casts_to_float(self) -> None:
        result = finalize_vti_trace_points([(1, 2), (3, 4)])
        assert result == ((1.0, 2.0), (3.0, 4.0))

    # ── main path (>= 3 points) ────────────────────────────────────

    def test_three_points_sorted(self) -> None:
        points = [(0.0, 0.0), (50.0, 100.0), (100.0, 0.0)]
        result = finalize_vti_trace_points(points)
        assert result[0] == (0.0, 0.0)
        assert result[-1] == (100.0, 0.0)
        assert len(result) == 3

    def test_sorts_middle_points(self) -> None:
        points = [(0.0, 0.0), (80.0, 90.0), (40.0, 100.0), (100.0, 0.0)]
        result = finalize_vti_trace_points(points)
        times = [p[0] for p in result]
        assert times == sorted(times)

    def test_keeps_onset_and_offset(self) -> None:
        points = [(5.0, 10.0), (50.0, 80.0), (100.0, 5.0)]
        result = finalize_vti_trace_points(points)
        assert result[0] == (5.0, 10.0)
        assert result[-1] == (100.0, 5.0)

    def test_decimates_close_points(self) -> None:
        points = [
            (0.0, 0.0),
            (10.0, 50.0),
            (11.0, 55.0),   # too close to 10.0 (1ms < 2ms default)
            (12.5, 60.0),   # kept (2.5ms >= 2ms from 10.0)
            (50.0, 100.0),
            (100.0, 0.0),
        ]
        result = finalize_vti_trace_points(points)
        times = [p[0] for p in result]
        assert 11.0 not in times
        assert 12.5 in times
        assert 10.0 in times
        assert 50.0 in times

    def test_custom_min_dt(self) -> None:
        points = [
            (0.0, 0.0),
            (10.0, 50.0),
            (15.0, 60.0),
            (50.0, 100.0),
            (100.0, 0.0),
        ]
        # With min_dt=10ms, 15.0 is only 5ms after 10.0 → filtered
        result = finalize_vti_trace_points(points, min_dt_ms=10.0)
        times = [p[0] for p in result]
        assert 15.0 not in times

    def test_offset_pushed_after_last_middle(self) -> None:
        # Offset at same time as last middle point
        points = [
            (0.0, 0.0),
            (50.0, 100.0),
            (50.0, 0.0),  # offset same time as last middle
        ]
        result = finalize_vti_trace_points(points)
        assert result[-1][0] > 50.0

    def test_offset_before_last_middle(self) -> None:
        points = [
            (0.0, 0.0),
            (50.0, 100.0),
            (30.0, 0.0),  # offset before last middle
        ]
        result = finalize_vti_trace_points(points)
        # Offset should be pushed to > 50.0
        assert result[-1][0] > 50.0

    def test_duplicate_times_filtered(self) -> None:
        points = [
            (0.0, 0.0),
            (20.0, 50.0),
            (20.0, 60.0),  # same time as previous
            (40.0, 80.0),
            (100.0, 0.0),
        ]
        result = finalize_vti_trace_points(points)
        times = [p[0] for p in result]
        assert times.count(20.0) == 1

    def test_returns_tuple_of_tuples(self) -> None:
        points = [(0.0, 0.0), (50.0, 100.0), (100.0, 0.0)]
        result = finalize_vti_trace_points(points)
        assert isinstance(result, tuple)
        for p in result:
            assert isinstance(p, tuple)
            assert len(p) == 2

    def test_many_points(self) -> None:
        points = [(float(i), float(i * 10)) for i in range(0, 101, 5)]
        result = finalize_vti_trace_points(points, min_dt_ms=10.0)
        # Should decimate: only every other point kept (5ms apart, min 10ms)
        assert len(result) < len(points)
        # Onset and offset preserved
        assert result[0] == (0.0, 0.0)
        assert result[-1][0] == 100.0
