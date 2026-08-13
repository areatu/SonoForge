"""Tests for doppler_trace_points.finalize_vti_trace_points."""

from __future__ import annotations

from echo_personal_tool.domain.services.doppler_trace_points import (
    filter_velocity_spikes,
    finalize_vti_trace_points,
)


class TestFinalizeVtiTracePoints:
    """Sort, decimate, and anchor onset/offset."""

    def test_empty_input(self):
        assert finalize_vti_trace_points(()) == ()

    def test_single_point_passthrough(self):
        result = finalize_vti_trace_points([(10.0, 50.0)])
        assert result == ((10.0, 50.0),)

    def test_two_points_passthrough(self):
        result = finalize_vti_trace_points([(1.0, 10.0), (2.0, 20.0)])
        assert result == ((1.0, 10.0), (2.0, 20.0))

    def test_sorted_by_time(self):
        points = [(5.0, 50.0), (1.0, 10.0), (3.0, 30.0), (7.0, 70.0)]
        result = finalize_vti_trace_points(points)
        times = [t for t, _ in result]
        assert times == sorted(times)

    def test_onset_offset_preserved(self):
        points = [(10.0, 5.0), (20.0, 40.0), (30.0, 30.0), (40.0, 10.0)]
        result = finalize_vti_trace_points(points)
        assert result[0] == (10.0, 5.0)
        assert result[-1] == (40.0, 10.0)

    def test_decimation_removes_close_points(self):
        points = [(0.0, 10.0), (0.5, 20.0), (1.0, 30.0), (5.0, 40.0), (50.0, 10.0)]
        result = finalize_vti_trace_points(points, min_dt_ms=2.0)
        # Points closer than 2.0 ms should be removed
        for i in range(1, len(result)):
            assert result[i][0] - result[i - 1][0] >= 2.0

    def test_duplicate_times_filtered(self):
        points = [(10.0, 10.0), (10.0, 20.0), (20.0, 30.0)]
        result = finalize_vti_trace_points(points)
        times = [t for t, _ in result]
        # Only one of the t=10.0 points should remain (the onset)
        assert len(times) == len(set(times))

    def test_offset_moved_if_collides(self):
        """If offset time <= last filtered middle point, it should be pushed forward."""
        # onset=0, middle sorted: 10, 20; offset=5 which is < 20 (last middle)
        points = [(0.0, 10.0), (20.0, 40.0), (10.0, 30.0), (5.0, 20.0)]
        result = finalize_vti_trace_points(points, min_dt_ms=2.0)
        # Offset gets pushed to filtered[-1][0] + min_dt_ms = 20 + 2 = 22
        assert result[-1][0] >= result[-2][0] + 2.0

    def test_many_points_decimated(self):
        points = [(float(i), float(i * 10)) for i in range(100)]
        result = finalize_vti_trace_points(points, min_dt_ms=3.0)
        assert len(result) < len(points)
        # Onset and offset preserved
        assert result[0][0] == 0.0
        assert result[-1][0] == 99.0

    def test_non_monotonic_middle_sorted(self):
        points = [(0.0, 5.0), (40.0, 40.0), (20.0, 20.0), (60.0, 10.0)]
        result = finalize_vti_trace_points(points)
        times = [t for t, _ in result]
        assert times == sorted(times)

    def test_float_conversion(self):
        points = [(1, 2), (3, 4), (5, 6)]
        result = finalize_vti_trace_points(points)
        for t, v in result:
            assert isinstance(t, float)
            assert isinstance(v, float)


class TestFilterVelocitySpikes:
    """Remove sharp velocity spikes by smoothing to neighbors."""

    def test_passthrough_when_no_spikes(self):
        points = [(1.0, 10.0), (2.0, 50.0), (3.0, 80.0), (4.0, 40.0), (5.0, 10.0)]
        result = filter_velocity_spikes(points)
        assert len(result) == len(points)
        assert result[2] == (3.0, 80.0)

    def test_spike_replaced_by_neighbor_average(self):
        # velocity jumps: 10 -> 100 -> 10 (spike of 90 > 100 threshold... use lower threshold)
        points = [(1.0, 10.0), (2.0, 100.0), (3.0, 10.0)]
        result = filter_velocity_spikes(points, spike_threshold_cm_s=50.0)
        # (100.0 - 10.0 > 50 AND 100.0 - 10.0 > 50) => spike replaced by (10+10)/2 = 10.0
        assert result[1] == (2.0, 10.0)

    def test_no_spike_when_one_side_matches(self):
        # 10 -> 100 -> 95: only one side > 50, no spike
        points = [(1.0, 10.0), (2.0, 100.0), (3.0, 95.0)]
        result = filter_velocity_spikes(points, spike_threshold_cm_s=50.0)
        assert result[1] == (2.0, 100.0)

    def test_clamps_extreme_velocity(self):
        points = [(1.0, 50.0), (2.0, 500.0), (3.0, 50.0)]
        result = filter_velocity_spikes(points, max_velocity_cm_s=400.0)
        # 500 → clamped to 400; both |400-50|>100 → spike
        # replaced by (50+50)/2 = 50.0
        assert result[1][1] == 50.0

    def test_clamps_negative_velocity(self):
        points = [(1.0, -50.0), (2.0, -500.0), (3.0, -50.0)]
        result = filter_velocity_spikes(points, max_velocity_cm_s=400.0)
        # -500 → clamped to -400; both |-400-(-50)|>100 → spike
        # replaced by (-50 + -50)/2 = -50.0
        assert result[1][1] == -50.0

    def test_short_input_passthrough(self):
        result = filter_velocity_spikes([(1.0, 10.0)])
        assert result == ((1.0, 10.0),)
