"""Unit tests for the pure Multiview session/sync model."""

from __future__ import annotations

from pathlib import Path

import pytest

from echo_personal_tool.domain.models.metadata import InstanceMetadata
from echo_personal_tool.domain.models.multiview import (
    DEFAULT_EVENT_LABEL,
    MAX_GLOBAL_RATE,
    MIN_GLOBAL_RATE,
    EventMarker,
    MultiViewPaneState,
    MultiViewSession,
    PaneId,
    PlaybackMode,
)
from echo_personal_tool.domain.services.multiview_sync import (
    NOMINAL_FRAME_TIME_MS,
    RETIMING_WARNING_MAX,
    RETIMING_WARNING_MIN,
    SyncCycle,
    build_cycle_schedule,
    clamp_rate,
    common_window_frames,
    cycle_timing,
    cycles_from_markers,
    display_cycle_duration,
    frame_at_phase,
    frame_start_seconds,
    frame_time_ms,
    interval_seconds,
    last_frame_index,
    markers_ready,
    phase_of_frame,
    plan_common_window,
    validate_new_marker,
)


def _instance(
    *,
    frames: int = 30,
    frame_time_ms: float | None = 33.3,
    vector: tuple[float, ...] | None = None,
    uid: str = "1.2.3",
    study: str = "study.1",
    series: str = "series.1",
) -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid=uid,
        series_uid=series,
        modality="US",
        number_of_frames=frames,
        pixel_spacing=None,
        frame_time_ms=frame_time_ms,
        series_description="A4C",
        path=Path("/tmp/clip.dcm"),
        media_format="dicom",
        frame_time_vector=vector,
    )


def _pane(instance: InstanceMetadata | None = None, *, study: str | None = None) -> MultiViewPaneState:
    return MultiViewPaneState(instance=instance, study_uid=study if study is not None else "study.1")


# ── pane state ──────────────────────────────────────────────────────


class TestMultiViewPaneState:
    def test_defaults_are_empty(self) -> None:
        pane = MultiViewPaneState()
        assert pane.instance is None
        assert pane.current_frame == 0
        assert pane.markers == []
        assert pane.has_clip is False
        assert pane.total_frames == 0
        assert pane.instance_uid is None

    def test_generation_starts_at_zero(self) -> None:
        pane = MultiViewPaneState(instance=_instance())
        assert pane.generation == 0
        assert pane.has_clip is True
        assert pane.instance_uid == "1.2.3"
        assert pane.total_frames == 30

    def test_clear_markers(self) -> None:
        pane = MultiViewPaneState(markers=[EventMarker(frame_index=3), EventMarker(frame_index=9)])
        pane.clear_markers()
        assert pane.markers == []


class TestMultiViewSession:
    def test_defaults(self) -> None:
        session = MultiViewSession()
        assert set(session.panes) == {PaneId.LEFT, PaneId.RIGHT}
        assert session.active_pane is None
        assert session.playback_mode is PlaybackMode.INDEPENDENT
        assert session.selected_cycle_count == 1
        assert session.global_rate == 1.0
        assert session.is_playing is False

    def test_other_pane(self) -> None:
        session = MultiViewSession()
        assert session.other(PaneId.LEFT) is PaneId.RIGHT
        assert session.other(PaneId.RIGHT) is PaneId.LEFT

    def test_reset_common_starts_uses_current_frames(self) -> None:
        session = MultiViewSession()
        session.pane(PaneId.LEFT).current_frame = 4
        session.pane(PaneId.RIGHT).current_frame = 11
        session.reset_common_starts()
        assert session.common_start[PaneId.LEFT] == 4
        assert session.common_start[PaneId.RIGHT] == 11

    def test_clips_are_comparable_requires_same_study(self) -> None:
        session = MultiViewSession()
        session.panes[PaneId.LEFT] = _pane(_instance(uid="a"), study="s1")
        session.panes[PaneId.RIGHT] = _pane(_instance(uid="b"), study="s1")
        assert session.clips_are_comparable() is True
        session.panes[PaneId.RIGHT] = _pane(_instance(uid="b"), study="s2")
        assert session.clips_are_comparable() is False
        session.panes[PaneId.RIGHT] = MultiViewPaneState()
        assert session.clips_are_comparable() is False

    def test_unknown_study_is_treated_as_comparable(self) -> None:
        session = MultiViewSession()
        session.panes[PaneId.LEFT] = _pane(_instance(uid="a"), study=None)
        session.panes[PaneId.RIGHT] = _pane(_instance(uid="b"), study=None)
        assert session.clips_are_comparable() is True


# ── timing helpers ──────────────────────────────────────────────────


class TestFrameTiming:
    def test_constant_frame_time(self) -> None:
        instance = _instance(frames=4, frame_time_ms=50.0)
        assert frame_time_ms(instance, 0) == 50.0
        assert frame_start_seconds(instance, 0) == 0.0
        assert frame_start_seconds(instance, 3) == pytest.approx(0.15)
        assert interval_seconds(instance, 0, 3) == pytest.approx(0.15)

    def test_vector_wins_over_frame_time(self) -> None:
        instance = _instance(frames=3, frame_time_ms=50.0, vector=(10.0, 20.0, 30.0))
        assert frame_time_ms(instance, 1) == 20.0
        assert frame_start_seconds(instance, 2) == pytest.approx(0.03)

    def test_zero_vector_entry_falls_back(self) -> None:
        instance = _instance(frames=3, frame_time_ms=40.0, vector=(0.0, 20.0, 30.0))
        assert frame_time_ms(instance, 0) == 40.0
        assert frame_time_ms(instance, 1) == 20.0

    def test_unknown_timing_returns_none(self) -> None:
        instance = _instance(frame_time_ms=None, vector=None)
        assert frame_time_ms(instance, 0) is None
        assert frame_start_seconds(instance, 2) is None
        assert interval_seconds(instance, 0, 2) is None

    def test_no_instance(self) -> None:
        assert frame_time_ms(None, 0) is None
        assert frame_start_seconds(None, 0) is None
        assert interval_seconds(None, 0, 3) is None

    def test_degenerate_interval(self) -> None:
        instance = _instance()
        assert interval_seconds(instance, 5, 5) is None
        assert interval_seconds(instance, 7, 3) is None

    def test_last_frame_index(self) -> None:
        assert last_frame_index(_instance(frames=30)) == 29
        assert last_frame_index(_instance(frames=0)) == 0
        assert last_frame_index(None) == 0


class TestClampRate:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (0.1, MIN_GLOBAL_RATE),
            (1.0, 1.0),
            (9.0, MAX_GLOBAL_RATE),
            (float("nan"), 1.0),
            (float("inf"), 1.0),
            (float("-inf"), 1.0),
        ],
    )
    def test_clamped(self, raw: float, expected: float) -> None:
        assert clamp_rate(raw) == pytest.approx(expected)


# ── common window ───────────────────────────────────────────────────


class TestCommonWindow:
    def test_duration_is_the_shorter_remainder(self) -> None:
        left = _instance(frames=30, frame_time_ms=33.3, uid="l")  # 29 × 33.3 ms
        right = _instance(frames=20, frame_time_ms=50.0, uid="r")  # 19 × 50 ms
        window = plan_common_window(left, 0, right, 0)
        assert window.is_valid
        assert window.duration_s == pytest.approx(0.95, abs=1e-6)
        # both panes stop at the common time, each at its own frame rate
        assert window.left_end == 28  # frame 29 would only start at 0.9657 s
        assert window.right_end == 19

    def test_start_frames_shift_the_end(self) -> None:
        left = _instance(frames=30, frame_time_ms=100.0, uid="l")
        right = _instance(frames=30, frame_time_ms=100.0, uid="r")
        window = plan_common_window(left, 10, right, 0)
        assert window.left_start == 10
        assert window.duration_s == pytest.approx(1.9)

    def test_missing_timing_keeps_frames_but_no_duration(self) -> None:
        left = _instance(frame_time_ms=None, uid="l")
        right = _instance(frame_time_ms=33.3, uid="r")
        window = plan_common_window(left, 0, right, 0)
        assert window.is_valid is False
        assert window.has_timing is False
        assert window.left_end == 29

    def test_frames_progress_with_elapsed(self) -> None:
        left = _instance(frames=11, frame_time_ms=100.0, uid="l")
        right = _instance(frames=21, frame_time_ms=100.0, uid="r")
        window = plan_common_window(left, 0, right, 0)
        assert window.duration_s == pytest.approx(1.0)
        assert common_window_frames(window, 0.0, left, right) == (0, 0)
        # time-based: both panes are half a second in, NOT half a clip
        assert common_window_frames(window, 0.5, left, right) == (5, 5)
        assert common_window_frames(window, 1.0, left, right) == (10, 10)
        # past the window clamps to the end
        assert common_window_frames(window, 5.0, left, right) == (10, 10)

    def test_different_frame_rates_stay_time_aligned(self) -> None:
        left = _instance(frames=11, frame_time_ms=100.0, uid="l")  # 1.0 s of frames
        right = _instance(frames=21, frame_time_ms=50.0, uid="r")  # 1.0 s of frames
        window = plan_common_window(left, 0, right, 0)
        assert window.duration_s == pytest.approx(1.0)
        # the slow clip is still mid-cycle when the fast one is done
        assert common_window_frames(window, 0.5, left, right) == (5, 10)

    def test_the_longer_clip_never_runs_past_the_common_end(self) -> None:
        left = _instance(frames=31, frame_time_ms=33.3, uid="l")  # 0.999 s left
        right = _instance(frames=11, frame_time_ms=100.0, uid="r")  # 1.0 s left
        window = plan_common_window(left, 0, right, 0)
        # T_common is the shorter remainder: the fast clip runs out first
        assert window.duration_s == pytest.approx(0.999, abs=1e-6)
        assert window.right_end == 9
        assert window.left_end == 30  # 0.999 s / 33.3 ms
        assert common_window_frames(window, 0.999, left, right) == (30, 9)

    def test_no_timing_stays_at_start(self) -> None:
        left = _instance(frame_time_ms=None, uid="l")
        right = _instance(frame_time_ms=33.3, uid="r")
        window = plan_common_window(left, 0, right, 0)
        assert common_window_frames(window, 0.5, left, right) == (0, 0)


# ── cycles and speed factors ────────────────────────────────────────


class TestCycles:
    def test_single_cycle_needs_two_markers(self) -> None:
        assert cycles_from_markers([], 1) == ()
        assert cycles_from_markers([EventMarker(frame_index=3)], 1) == ()
        cycles = cycles_from_markers([EventMarker(frame_index=3), EventMarker(frame_index=12)], 1)
        assert cycles == ((3, 12),)

    def test_two_cycles_need_three_markers(self) -> None:
        markers = [EventMarker(frame_index=i) for i in (3, 12, 20)]
        assert cycles_from_markers(markers[:2], 2) == ()
        cycles = cycles_from_markers(markers, 2)
        assert cycles == ((3, 12), (12, 20))

    def test_extra_markers_are_ignored(self) -> None:
        markers = [EventMarker(frame_index=i) for i in (1, 5, 9, 14)]
        assert cycles_from_markers(markers, 2) == ((1, 5), (5, 9))

    def test_markers_ready(self) -> None:
        assert markers_ready([EventMarker(frame_index=1)], 1) is False
        assert markers_ready([EventMarker(frame_index=1), EventMarker(frame_index=4)], 1) is True
        assert markers_ready([EventMarker(frame_index=1), EventMarker(frame_index=4)], 2) is False

    def test_default_label_is_mitral_valve(self) -> None:
        assert EventMarker(frame_index=0).label == DEFAULT_EVENT_LABEL


class TestCycleTiming:
    def test_equal_intervals_keep_original_speed(self) -> None:
        timing = cycle_timing(0.90, 0.90, 1.0)
        assert timing.t_display_s == pytest.approx(0.90)
        assert timing.k_left == pytest.approx(1.0)
        assert timing.k_right == pytest.approx(1.0)
        assert timing.needs_warning is False

    def test_spec_example(self) -> None:
        # A: 0.80 s, B: 1.00 s at 1.0× → both take 0.90 s.
        timing = cycle_timing(0.80, 1.00, 1.0)
        assert timing.t_display_s == pytest.approx(0.90)
        assert timing.k_left == pytest.approx(0.80 / 0.90)
        assert timing.k_right == pytest.approx(1.00 / 0.90)
        assert timing.k_left < 1.0  # left must be slowed down
        assert timing.k_right > 1.0  # right must be sped up

    def test_global_rate_scales_display(self) -> None:
        slow = cycle_timing(0.80, 1.00, 0.5)
        assert slow.t_display_s == pytest.approx(1.80)
        assert slow.k_left == pytest.approx(0.80 / 1.80)
        assert slow.k_right == pytest.approx(1.00 / 1.80)

    def test_display_duration_helper(self) -> None:
        assert display_cycle_duration(0.8, 1.0, 1.0) == pytest.approx(0.9)
        assert display_cycle_duration(0.8, 1.0, 2.0) == pytest.approx(0.45)

    def test_warning_band(self) -> None:
        assert RETIMING_WARNING_MIN == 0.5
        assert RETIMING_WARNING_MAX == 2.0
        assert cycle_timing(0.25, 1.0, 1.0).needs_warning is True
        assert cycle_timing(0.45, 1.0, 1.0).needs_warning is False
        assert cycle_timing(0.25, 1.0, 1.0).max_abs_deviation == pytest.approx(0.6)

    def test_degenerate_timing_is_identity(self) -> None:
        timing = cycle_timing(0.0, 0.0, 1.0)
        assert timing.t_display_s == 0.0
        assert timing.k_left == 1.0
        assert timing.k_right == 1.0


# ── phase mapping ───────────────────────────────────────────────────


class TestPhaseMapping:
    def test_constant_frame_time_maps_linearly(self) -> None:
        instance = _instance(frames=11, frame_time_ms=100.0)
        assert frame_at_phase(instance, 0, 10, 0.0) == 0
        assert frame_at_phase(instance, 0, 10, 0.5) == 5
        assert frame_at_phase(instance, 0, 10, 1.0) == 10

    def test_variable_timing_holds_long_frames(self) -> None:
        # frames 0,1,2 take 10, 700, 200 ms → phase 0.5 lands on frame 1.
        instance = _instance(frames=4, frame_time_ms=100.0, vector=(10.0, 700.0, 200.0, 90.0))
        assert frame_at_phase(instance, 0, 3, 0.0) == 0
        # frame 1 spans 10–710 ms, so t=91 ms already shows frame 1
        assert frame_at_phase(instance, 0, 3, 0.1) == 1
        assert frame_at_phase(instance, 0, 3, 0.5) == 1
        assert frame_at_phase(instance, 0, 3, 0.9) == 2
        assert frame_at_phase(instance, 0, 3, 1.0) == 3

    def test_phase_is_clamped(self) -> None:
        instance = _instance(frames=11, frame_time_ms=100.0)
        assert frame_at_phase(instance, 0, 10, -3.0) == 0
        assert frame_at_phase(instance, 0, 10, 3.0) == 10

    def test_without_timing_falls_back_to_index_interpolation(self) -> None:
        instance = _instance(frames=11, frame_time_ms=None)
        assert frame_at_phase(instance, 0, 10, 0.0) == 0
        assert frame_at_phase(instance, 0, 10, 0.5) == 5
        assert frame_at_phase(instance, 0, 10, 1.0) == 10

    def test_no_instance(self) -> None:
        # no timing: frame-index interpolation only (phase-only navigation)
        assert frame_at_phase(None, 0, 10, 0.5) == 5

    def test_degenerate_cycle(self) -> None:
        instance = _instance(frames=11, frame_time_ms=100.0)
        assert frame_at_phase(instance, 4, 4, 0.5) == 4

    def test_phase_of_frame_round_trips(self) -> None:
        instance = _instance(frames=11, frame_time_ms=100.0)
        for phase in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
            frame = frame_at_phase(instance, 0, 10, phase)
            assert phase_of_frame(instance, 0, 10, frame) == pytest.approx(phase, abs=1e-6)

    def test_phase_of_frame_clamps(self) -> None:
        instance = _instance(frames=11, frame_time_ms=100.0)
        assert phase_of_frame(instance, 2, 8, -5) == 0.0
        assert phase_of_frame(instance, 2, 8, 99) == 1.0

    def test_phase_of_frame_without_timing(self) -> None:
        instance = _instance(frames=11, frame_time_ms=None)
        assert phase_of_frame(instance, 0, 10, 5) == pytest.approx(0.5)


# ── marker validation ───────────────────────────────────────────────


class TestMarkerValidation:
    def test_first_marker_is_accepted(self) -> None:
        assert validate_new_marker([], 0, 30) is None

    def test_forward_marker_is_accepted(self) -> None:
        markers = [EventMarker(frame_index=4)]
        assert validate_new_marker(markers, 12, 30) is None

    def test_duplicate_frame_is_rejected(self) -> None:
        markers = [EventMarker(frame_index=4)]
        assert validate_new_marker(markers, 4, 30) == "multiview.marker.out_of_order"

    def test_backwards_marker_is_rejected(self) -> None:
        markers = [EventMarker(frame_index=4), EventMarker(frame_index=12)]
        assert validate_new_marker(markers, 8, 30) == "multiview.marker.out_of_order"

    def test_frame_beyond_clip_is_rejected(self) -> None:
        assert validate_new_marker([], 30, 30) == "multiview.marker.invalid_frame"
        assert validate_new_marker([], -1, 30) == "multiview.marker.invalid_frame"

    def test_last_frame_has_no_room_for_a_cycle(self) -> None:
        markers = [EventMarker(frame_index=28)]
        assert validate_new_marker(markers, 29, 30) == "multiview.marker.no_room"
        assert validate_new_marker([], 29, 30) == "multiview.marker.no_room"
        assert validate_new_marker([], 20, 30) is None

    def test_unknown_total_allows_any_frame(self) -> None:
        assert validate_new_marker([], 5, 0) is None


# ── cycle schedule (spec §7.3, §8.3) ────────────────────────────────


class TestCycleSchedule:
    def test_two_cycles_have_separate_factors(self) -> None:
        # left RR1 = 0.8 s, RR2 = 0.9 s; right RR1 = 1.0 s, RR2 = 0.7 s.
        left = _instance(frames=100, frame_time_ms=10.0, uid="l")
        right = _instance(frames=100, frame_time_ms=10.0, uid="r")
        schedule = build_cycle_schedule(
            left,
            [SyncCycle(0, 80), SyncCycle(80, 170)],
            right,
            [SyncCycle(0, 100), SyncCycle(100, 170)],
            1.0,
        )
        assert schedule.is_valid
        assert schedule.timing_known is True
        first, second = schedule.entries
        assert first.duration_s == pytest.approx(0.90)
        assert first.timing.k_left == pytest.approx(0.8 / 0.9)
        assert first.timing.k_right == pytest.approx(1.0 / 0.9)
        # RR2: mean(0.9, 0.7) = 0.8 → different factors from cycle 1.
        assert second.duration_s == pytest.approx(0.80)
        assert second.timing.k_left == pytest.approx(0.9 / 0.8)
        assert second.timing.k_right == pytest.approx(0.7 / 0.8)
        assert second.timing.k_left != first.timing.k_left
        assert schedule.total_s == pytest.approx(1.70)

    def test_locate_walks_the_cycles(self) -> None:
        left = _instance(frames=100, frame_time_ms=10.0, uid="l")
        right = _instance(frames=100, frame_time_ms=10.0, uid="r")
        schedule = build_cycle_schedule(
            left, [SyncCycle(0, 80), SyncCycle(80, 170)], right, [SyncCycle(0, 80), SyncCycle(80, 170)], 1.0
        )
        entry, phase = schedule.locate(0.0)
        assert entry is schedule.entries[0]
        assert phase == pytest.approx(0.0)
        entry, phase = schedule.locate(0.4)
        assert entry is schedule.entries[0]
        assert phase == pytest.approx(0.5)
        entry, phase = schedule.locate(0.8)
        assert entry is schedule.entries[1]
        assert phase == pytest.approx(0.0)
        entry, phase = schedule.locate(1.25)
        assert entry is schedule.entries[1]
        assert phase == pytest.approx(0.5)
        entry, phase = schedule.locate(schedule.total_s)
        assert entry is schedule.entries[1]
        assert phase == pytest.approx(1.0)
        # past the end clamps into the last cycle
        entry, phase = schedule.locate(99.0)
        assert entry is schedule.entries[1]
        assert phase == pytest.approx(1.0)

    def test_single_cycle_schedule(self) -> None:
        left = _instance(frames=100, frame_time_ms=10.0, uid="l")
        right = _instance(frames=100, frame_time_ms=10.0, uid="r")
        schedule = build_cycle_schedule(left, [SyncCycle(0, 80)], right, [SyncCycle(0, 80)], 1.0)
        assert len(schedule.entries) == 1
        assert schedule.total_s == pytest.approx(0.8)

    def test_mismatched_cycle_counts_use_the_shorter(self) -> None:
        left = _instance(frames=100, frame_time_ms=10.0, uid="l")
        right = _instance(frames=100, frame_time_ms=10.0, uid="r")
        schedule = build_cycle_schedule(left, [SyncCycle(0, 80), SyncCycle(80, 170)], right, [SyncCycle(0, 80)], 1.0)
        assert len(schedule.entries) == 1

    def test_no_cycles_is_invalid(self) -> None:
        left = _instance(frames=100, frame_time_ms=10.0, uid="l")
        schedule = build_cycle_schedule(left, [], left, [], 1.0)
        assert schedule.is_valid is False
        assert schedule.total_s == 0.0
        assert schedule.locate(1.0) == (None, 0.0)

    def test_missing_timing_is_reported(self) -> None:
        left = _instance(frames=100, frame_time_ms=None, uid="l")
        right = _instance(frames=100, frame_time_ms=10.0, uid="r")
        schedule = build_cycle_schedule(left, [SyncCycle(0, 80)], right, [SyncCycle(0, 80)], 1.0)
        assert schedule.timing_known is False
        assert schedule.entries[0].timing_known is False
        # nominal 33.3 ms/frame keeps the left cycle navigable; the display
        # duration is the mean of the nominal left and the real right one.
        nominal = 80 * NOMINAL_FRAME_TIME_MS / 1000.0
        assert schedule.total_s == pytest.approx((nominal + 0.8) / 2.0)
        entry, phase = schedule.locate(schedule.total_s / 2.0)
        assert phase == pytest.approx(0.5)

    def test_global_rate_scales_every_cycle(self) -> None:
        left = _instance(frames=100, frame_time_ms=10.0, uid="l")
        right = _instance(frames=100, frame_time_ms=10.0, uid="r")
        fast = build_cycle_schedule(left, [SyncCycle(0, 80)], right, [SyncCycle(0, 80)], 2.0)
        assert fast.total_s == pytest.approx(0.4)
        assert fast.entries[0].timing.k_left == pytest.approx(2.0)
        assert fast.entries[0].timing.k_right == pytest.approx(2.0)
