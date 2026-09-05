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
    def test_short_points_unchanged(self):
        points = [(1.0, 10.0)]
        result = filter_velocity_spikes(points)
        assert result == ((1.0, 10.0),)

    def test_spike_replaced_by_median(self):
        points = [
            (1.0, 50.0),
            (2.0, 52.0),
            (3.0, 51.0),
            (4.0, 200.0),
            (5.0, 53.0),
            (6.0, 50.0),
            (7.0, 49.0),
        ]
        result = filter_velocity_spikes(points)
        assert result[3][1] != 200.0
        assert result[3][1] < 100.0

    def test_no_spike_in_smooth_curve(self):
        points = [(i * 10.0, 50.0 + i * 2.0) for i in range(8)]
        result = filter_velocity_spikes(points)
        assert len(result) == 8

    def test_max_clamp(self):
        points = [
            (1.0, 50.0),
            (2.0, 52.0),
            (3.0, 999.0),
            (4.0, 53.0),
            (5.0, 50.0),
        ]
        result = filter_velocity_spikes(points, max_velocity_cm_s=400.0)
        assert result[2][1] <= 400.0
        assert result[2][1] != 999.0

    def test_negative_velocities(self):
        points = [
            (1.0, -50.0),
            (2.0, -52.0),
            (3.0, -55.0),
            (4.0, -53.0),
            (5.0, -50.0),
        ]
        result = filter_velocity_spikes(points, max_velocity_cm_s=400.0)
        assert result[2][1] == -55.0


class TestFilterVelocitySpikesAdaptive:
    """Tests for the rolling-median adaptive spike filter."""

    def test_single_spike_replaced(self):
        points = [(0.0, 50.0), (10.0, 55.0), (20.0, 200.0), (30.0, 52.0), (40.0, 48.0)]
        result = filter_velocity_spikes(points)
        assert result[2][1] != 200.0
        assert result[2][1] < 100.0

    def test_no_spike_preserved(self):
        points = [(0.0, 50.0), (10.0, 60.0), (20.0, 70.0), (30.0, 65.0), (40.0, 55.0)]
        result = filter_velocity_spikes(points)
        assert len(result) == 5

    def test_adapts_to_low_velocity(self):
        points = [(0.0, 30.0), (10.0, 32.0), (20.0, 80.0), (30.0, 31.0), (40.0, 29.0)]
        result = filter_velocity_spikes(points)
        assert result[2][1] != 80.0

    def test_adapts_to_high_velocity(self):
        points = [(0.0, 150.0), (10.0, 200.0), (20.0, 300.0), (30.0, 210.0), (40.0, 160.0)]
        result = filter_velocity_spikes(points)
        assert result[2][1] == 300.0

    def test_edge_point_filtered(self):
        points = [(0.0, 200.0), (10.0, 50.0), (20.0, 55.0), (30.0, 52.0), (40.0, 48.0)]
        result = filter_velocity_spikes(points)
        assert result[0][1] != 200.0

    def test_two_points_unchanged(self):
        points = [(0.0, 50.0), (10.0, 60.0)]
        result = filter_velocity_spikes(points)
        assert len(result) == 2

    def test_max_clamp_still_works(self):
        points = [(0.0, 50.0), (10.0, 55.0), (20.0, 999.0), (30.0, 52.0), (40.0, 48.0)]
        result = filter_velocity_spikes(points, max_velocity_cm_s=400.0)
        assert result[2][1] <= 400.0

    def test_explicit_high_limit_preserves_high_velocity(self):
        points = [(0.0, -490.0), (10.0, -480.0), (20.0, -470.0)]
        result = filter_velocity_spikes(points, max_velocity_cm_s=600.0)
        assert result[0][1] == -490.0

    def test_k_mad_parameter(self):
        points = [(0.0, 50.0), (10.0, 55.0), (20.0, 120.0), (30.0, 52.0), (40.0, 48.0)]
        strict = filter_velocity_spikes(points, k_mad=2.0)
        loose = filter_velocity_spikes(points, k_mad=5.0)
        assert strict[2][1] != 120.0 or loose[2][1] == 120.0
