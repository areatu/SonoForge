"""Unit tests for the Multiview controller: state, clock and frame routing."""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from echo_personal_tool.domain.models.metadata import InstanceMetadata
from echo_personal_tool.domain.models.multiview import (
    DEFAULT_EVENT_LABEL,
    MAX_EVENT_LABEL,
    PaneId,
    PlaybackMode,
)
from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.presentation.multiview_controller import MultiViewController


class FakeViewer:
    """Records what the controller paints into one pane."""

    def __init__(self) -> None:
        self.frames: list[np.ndarray] = []
        self.transport: list[dict] = []

    def show_frame(self, pixels: np.ndarray) -> None:
        self.frames.append(pixels)

    def set_transport_state(self, **kwargs) -> None:
        self.transport.append(kwargs)


class FakePane:
    def __init__(self, pane_id: PaneId) -> None:
        self.pane_id = pane_id
        self.viewer = FakeViewer()
        self.headers: list[dict] = []
        self.markers: list[tuple] = []
        self.active: list[bool] = []
        self.cycle_counts: list[int] = []
        self.marker_bar_visible: list[bool] = []
        self.windows: list[tuple[int, int] | None] = []

    def set_header(self, **kwargs) -> None:
        self.headers.append(kwargs)

    def set_active(self, active: bool) -> None:
        self.active.append(active)

    def set_cycle_count(self, cycle_count: int) -> None:
        self.cycle_counts.append(cycle_count)

    def set_markers(self, markers, total_frames: int, current_frame: int) -> None:
        self.markers.append((tuple(markers), total_frames, current_frame))

    def set_window(self, span) -> None:
        self.windows.append(span)


class FakeCache:
    """Serves a deterministic frame per index."""

    def is_ready(self, path: Path) -> bool:
        return True

    def get(self, index: int) -> np.ndarray:
        return np.full((2, 2), index, dtype=np.uint8)


def _instance(
    frames: int = 30,
    frame_time_ms: float | None = 33.3,
    uid: str = "1.2.3",
    study: str = "study.1",
    path: str = "/tmp/clip.dcm",
) -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid=uid,
        series_uid="series.1",
        modality="US",
        number_of_frames=frames,
        pixel_spacing=None,
        frame_time_ms=frame_time_ms,
        series_description="A4C",
        path=Path(path),
        media_format="dicom",
    )


class FakeClock:
    """Controllable replacement for ``time.monotonic``."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture()
def rig(monkeypatch):
    controller = MagicMock()
    controller._frame_cache = FakeCache()
    mv = MultiViewController(controller)
    panes = {PaneId.LEFT: FakePane(PaneId.LEFT), PaneId.RIGHT: FakePane(PaneId.RIGHT)}
    for pane_id, pane in panes.items():
        mv.attach_pane(pane_id, pane)
    clock = FakeClock()
    monkeypatch.setattr(mv, "_now_ms", lambda: clock.now * 1000.0)
    status: list[str] = []
    warnings: list[tuple[str, str]] = []
    mv.status_message.connect(status.append)
    mv.warning_requested.connect(lambda title, body: warnings.append((title, body)))
    return SimpleNamespace(mv=mv, panes=panes, clock=clock, status=status, warnings=warnings, controller=controller)


def _load_both(rig, *, left_kwargs=None, right_kwargs=None) -> None:
    rig.mv.load_instance(PaneId.LEFT, _instance(uid="left", path="/tmp/left.dcm", **(left_kwargs or {})), "study.1")
    rig.mv.load_instance(PaneId.RIGHT, _instance(uid="right", path="/tmp/right.dcm", **(right_kwargs or {})), "study.1")
    rig.mv.activate(PaneId.LEFT)


def _painted_frames(pane: FakePane) -> list[int]:
    return [int(frame[0, 0]) for frame in pane.viewer.frames]


# ── pane lifecycle ──────────────────────────────────────────────────


class TestPaneLifecycle:
    def test_load_instance_resets_pane_local_state(self, rig) -> None:
        _load_both(rig)
        rig.mv.place_marker(PaneId.LEFT, 0)
        assert rig.mv.session.pane(PaneId.LEFT).markers
        rig.mv.load_instance(PaneId.LEFT, _instance(uid="left2", path="/tmp/left2.dcm"), "study.1")
        pane = rig.mv.session.pane(PaneId.LEFT)
        assert pane.instance_uid == "left2"
        assert pane.current_frame == 0
        assert pane.markers == []
        assert pane.generation >= 2
        assert pane.load_error is None
        # the other pane is untouched
        assert rig.mv.session.pane(PaneId.RIGHT).instance_uid == "right"

    def test_clear_pane_empties_it(self, rig) -> None:
        _load_both(rig)
        rig.mv.clear_pane(PaneId.RIGHT)
        pane = rig.mv.session.pane(PaneId.RIGHT)
        assert pane.instance is None
        assert pane.study_uid is None
        assert pane.has_clip is False

    def test_reset_session_drops_both_panes(self, rig) -> None:
        _load_both(rig)
        rig.mv.set_mode(PlaybackMode.COMMON_WINDOW)
        rig.mv.reset_session()
        assert rig.mv.session.pane(PaneId.LEFT).instance is None
        assert rig.mv.session.pane(PaneId.RIGHT).instance is None
        assert rig.mv.session.playback_mode is PlaybackMode.INDEPENDENT
        assert rig.mv.session.active_pane is None

    def test_empty_pane_cannot_become_active(self, rig) -> None:
        rig.mv.activate(PaneId.RIGHT)
        assert rig.mv.session.active_pane is None

    def test_left_pane_frame_goes_back_to_the_controller(self, rig) -> None:
        _load_both(rig)
        released: list[int] = []
        rig.mv.left_pane_released.connect(released.append)
        rig.mv.set_frame(PaneId.LEFT, 7)
        assert released == [7]
        assert rig.mv.session.pane(PaneId.LEFT).current_frame == 7

    def test_right_pane_frame_is_painted_locally(self, rig) -> None:
        _load_both(rig)
        rig.mv.set_frame(PaneId.RIGHT, 5)
        assert _painted_frames(rig.panes[PaneId.RIGHT]) == [0, 5]


# ── independent mode ────────────────────────────────────────────────


class TestIndependentMode:
    def test_play_is_refused_without_both_clips(self, rig) -> None:
        rig.mv.set_mode(PlaybackMode.INDEPENDENT)
        rig.mv.play()
        assert rig.mv.session.is_playing is False
        assert rig.status[-1] != ""

    def test_wheel_scrolls_only_the_pane_under_the_cursor(self, rig) -> None:
        _load_both(rig)
        rig.mv.set_frame(PaneId.LEFT, 4)
        rig.mv.scroll_by(PaneId.RIGHT, 9)
        assert rig.mv.session.pane(PaneId.RIGHT).current_frame == 9
        assert rig.mv.session.pane(PaneId.LEFT).current_frame == 4

    def test_frame_is_clamped_to_the_clip(self, rig) -> None:
        _load_both(rig)
        rig.mv.set_frame(PaneId.RIGHT, 999)
        assert rig.mv.session.pane(PaneId.RIGHT).current_frame == 29
        rig.mv.set_frame(PaneId.RIGHT, -5)
        assert rig.mv.session.pane(PaneId.RIGHT).current_frame == 0


# ── common window (spec §8.2) ───────────────────────────────────────


class TestCommonWindow:
    def test_both_clips_start_together(self, rig) -> None:
        # 100 ms/frame on both sides, 30 frames.
        _load_both(rig, left_kwargs={"frame_time_ms": 100.0}, right_kwargs={"frame_time_ms": 100.0})
        rig.mv.set_frame(PaneId.LEFT, 0)
        rig.mv.set_frame(PaneId.RIGHT, 0)
        rig.mv.set_mode(PlaybackMode.COMMON_WINDOW)
        rig.mv.play()
        assert rig.mv.session.is_playing is True
        left = rig.mv.session.pane(PaneId.LEFT).current_frame
        right = rig.mv.session.pane(PaneId.RIGHT).current_frame
        assert left == right == 0
        assert tr("multiview.status.basis_phase") not in rig.mv.status_text()
        assert tr("multiview.mode.common_window") != rig.mv.status_text()

    def test_window_ends_at_the_shorter_remainder(self, rig) -> None:
        _load_both(
            rig,
            left_kwargs={"frames": 30, "frame_time_ms": 100.0},
            right_kwargs={"frames": 11, "frame_time_ms": 100.0},
        )
        rig.mv.set_mode(PlaybackMode.COMMON_WINDOW)
        rig.mv.play()
        window = rig.mv._window
        assert window is not None
        # left remainder 29*0.1 = 2.9 s, right remainder 10*0.1 = 1.0 s
        assert window.duration_s == pytest.approx(1.0)
        # the window is time-based, not phase-based: half a second into the
        # window both panes sit on the frame that started 0.5 s in.
        rig.clock.advance(0.5)
        rig.mv._on_clock_tick()
        assert rig.mv.session.pane(PaneId.LEFT).current_frame == 5
        assert rig.mv.session.pane(PaneId.RIGHT).current_frame == 5

    def test_window_is_shown_on_both_timelines(self, rig) -> None:
        _load_both(
            rig,
            left_kwargs={"frames": 30, "frame_time_ms": 100.0},
            right_kwargs={"frames": 11, "frame_time_ms": 100.0},
        )
        rig.mv.set_mode(PlaybackMode.COMMON_WINDOW)
        rig.mv.play()
        left_pane = rig.mv._panes[PaneId.LEFT]
        right_pane = rig.mv._panes[PaneId.RIGHT]
        assert left_pane.windows[-1] == (0, 10)
        assert right_pane.windows[-1] == (0, 10)
        # outside the common window the band disappears
        rig.mv.set_mode(PlaybackMode.INDEPENDENT)
        assert left_pane.windows[-1] is None
        assert right_pane.windows[-1] is None

    def test_endpoint_hold_then_loop(self, rig) -> None:
        _load_both(rig, left_kwargs={"frame_time_ms": 100.0}, right_kwargs={"frame_time_ms": 100.0})
        rig.mv.set_mode(PlaybackMode.COMMON_WINDOW)
        rig.mv.play()
        rig.clock.advance(2.9)
        rig.mv._on_clock_tick()
        assert rig.mv.session.pane(PaneId.LEFT).current_frame == 29
        assert rig.mv.session.pane(PaneId.RIGHT).current_frame == 29
        # during the 150 ms hold nothing moves
        rig.clock.advance(0.05)
        rig.mv._on_clock_tick()
        assert rig.mv.session.pane(PaneId.LEFT).current_frame == 29
        # after the hold the loop restarts from the start frames
        rig.clock.advance(0.2)
        rig.mv._on_clock_tick()
        assert rig.mv.session.pane(PaneId.LEFT).current_frame == 0
        assert rig.mv.session.pane(PaneId.RIGHT).current_frame == 0

    def test_stop_returns_to_the_start_frames(self, rig) -> None:
        _load_both(rig, left_kwargs={"frame_time_ms": 100.0}, right_kwargs={"frame_time_ms": 100.0})
        rig.mv.set_frame(PaneId.LEFT, 3)
        rig.mv.set_frame(PaneId.RIGHT, 6)
        rig.mv.set_mode(PlaybackMode.COMMON_WINDOW)
        rig.mv.play()
        rig.clock.advance(0.4)
        rig.mv._on_clock_tick()
        rig.mv.stop()
        assert rig.mv.session.is_playing is False
        assert rig.mv.session.pane(PaneId.LEFT).current_frame == 3
        assert rig.mv.session.pane(PaneId.RIGHT).current_frame == 6

    def test_scrubbing_re_anchors_the_window(self, rig) -> None:
        _load_both(rig, left_kwargs={"frame_time_ms": 100.0}, right_kwargs={"frame_time_ms": 100.0})
        rig.mv.set_mode(PlaybackMode.COMMON_WINDOW)
        rig.mv.set_frame(PaneId.RIGHT, 10)
        assert rig.mv.session.common_start[PaneId.RIGHT] == 10
        assert rig.mv._window.right_start == 10

    def test_unknown_timing_is_reported(self, rig) -> None:
        _load_both(rig, left_kwargs={"frame_time_ms": None}, right_kwargs={"frame_time_ms": None})
        rig.mv.set_mode(PlaybackMode.COMMON_WINDOW)
        assert "неизвестно" in rig.mv.status_text()


# ── event cycles (spec §7, §8.3) ────────────────────────────────────


def _mark_both(rig, left_frames, right_frames) -> None:
    for ordinal, frame in enumerate(left_frames):
        rig.mv.set_frame(PaneId.LEFT, frame)
        rig.mv.place_marker(PaneId.LEFT, ordinal)
    for ordinal, frame in enumerate(right_frames):
        rig.mv.set_frame(PaneId.RIGHT, frame)
        rig.mv.place_marker(PaneId.RIGHT, ordinal)


class TestEventCycles:
    def test_single_cycle_needs_two_markers_per_pane(self, rig) -> None:
        _load_both(rig)
        rig.mv.set_mode(PlaybackMode.EVENT_CYCLE)
        rig.mv.play()
        assert rig.mv.session.is_playing is False
        assert rig.mv.status_text() == tr("multiview.status.markers_incomplete")

    def test_both_clips_show_their_first_marker_together(self, rig) -> None:
        # 100 ms/frame; left cycle 0..10 (1.0 s), right cycle 0..20 (2.0 s).
        _load_both(rig, left_kwargs={"frame_time_ms": 100.0}, right_kwargs={"frame_time_ms": 100.0})
        _mark_both(rig, [0, 10], [0, 20])
        rig.mv.set_mode(PlaybackMode.EVENT_CYCLE)
        rig.mv.play()
        assert rig.mv.session.pane(PaneId.LEFT).current_frame == 0
        assert rig.mv.session.pane(PaneId.RIGHT).current_frame == 0
        schedule = rig.mv._schedule
        assert schedule is not None
        assert schedule.total_s == pytest.approx(1.5)
        assert schedule.entries[0].timing.k_left == pytest.approx(1.0 / 1.5)
        assert schedule.entries[0].timing.k_right == pytest.approx(2.0 / 1.5)

    def test_phase_maps_to_each_own_interval(self, rig) -> None:
        _load_both(rig, left_kwargs={"frame_time_ms": 100.0}, right_kwargs={"frame_time_ms": 100.0})
        _mark_both(rig, [0, 10], [0, 20])
        rig.mv.set_mode(PlaybackMode.EVENT_CYCLE)
        rig.mv.play()
        rig.clock.advance(0.75)  # half of the 1.5 s display cycle
        rig.mv._on_clock_tick()
        assert rig.mv.session.pane(PaneId.LEFT).current_frame == 5
        assert rig.mv.session.pane(PaneId.RIGHT).current_frame == 10

    def test_two_cycles_get_separate_factors(self, rig) -> None:
        _load_both(rig, left_kwargs={"frame_time_ms": 100.0}, right_kwargs={"frame_time_ms": 100.0})
        # left: MK0=0 MK1=10 MK2=20 → RR1 = 1.0 s, RR2 = 1.0 s
        # right: MK0=0 MK1=20 MK2=30 → RR1 = 2.0 s, RR2 = 1.0 s
        _load_both(
            rig,
            left_kwargs={"frame_time_ms": 100.0, "frames": 40},
            right_kwargs={"frame_time_ms": 100.0, "frames": 40},
        )
        _mark_both(rig, [0, 10, 20], [0, 20, 30])
        rig.mv.set_cycle_count(2)
        rig.mv.set_mode(PlaybackMode.EVENT_CYCLE)
        schedule = rig.mv._schedule
        assert schedule is not None
        assert len(schedule.entries) == 2
        first, second = schedule.entries
        assert first.timing.k_left == pytest.approx(1.0 / 1.5)
        assert first.timing.k_right == pytest.approx(2.0 / 1.5)
        assert second.timing.k_left == pytest.approx(1.0)
        assert second.timing.k_right == pytest.approx(1.0)
        assert second.timing.k_left != first.timing.k_left

    def test_two_cycles_switch_on_the_middle_marker(self, rig) -> None:
        _load_both(
            rig,
            left_kwargs={"frame_time_ms": 100.0, "frames": 40},
            right_kwargs={"frame_time_ms": 100.0, "frames": 40},
        )
        _mark_both(rig, [0, 10, 20], [0, 20, 30])
        rig.mv.set_cycle_count(2)
        rig.mv.set_mode(PlaybackMode.EVENT_CYCLE)
        rig.mv.play()
        # cycle 1 lasts 1.5 s; at 1.5 s the playhead is on MK1 of both clips
        rig.clock.advance(1.5)
        rig.mv._on_clock_tick()
        assert rig.mv.session.pane(PaneId.LEFT).current_frame == 10
        assert rig.mv.session.pane(PaneId.RIGHT).current_frame == 20
        # cycle 2 lasts 1.0 s; half of it is 0.5 s later
        rig.clock.advance(0.5)
        rig.mv._on_clock_tick()
        assert rig.mv.session.pane(PaneId.LEFT).current_frame == 15
        assert rig.mv.session.pane(PaneId.RIGHT).current_frame == 25

    def test_heavy_retiming_warns_once(self, rig) -> None:
        # left interval 0.1 s vs right 10 s → factors far outside 0.5x-2.0x
        _load_both(
            rig,
            left_kwargs={"frames": 200, "frame_time_ms": 10.0},
            right_kwargs={"frames": 200, "frame_time_ms": 100.0},
        )
        _mark_both(rig, [0, 10], [0, 100])
        rig.mv.set_mode(PlaybackMode.EVENT_CYCLE)
        rig.mv.play()
        assert len(rig.warnings) == 1
        assert "0.5" in rig.warnings[0][1]
        assert rig.warnings[0][0] == tr("multiview.warning.retiming_title")
        rig.mv.set_rate(0.75)
        assert len(rig.warnings) == 1

    def test_rate_changes_the_display_duration(self, rig) -> None:
        _load_both(rig, left_kwargs={"frame_time_ms": 100.0}, right_kwargs={"frame_time_ms": 100.0})
        _mark_both(rig, [0, 10], [0, 10])
        rig.mv.set_mode(PlaybackMode.EVENT_CYCLE)
        assert rig.mv._schedule.total_s == pytest.approx(1.0)
        rig.mv.set_rate(2.0)
        assert rig.mv._schedule.total_s == pytest.approx(0.5)

    def test_rate_is_clamped_to_the_supported_band(self, rig) -> None:
        rig.mv.set_rate(99.0)
        assert rig.mv.session.global_rate == 2.0
        rig.mv.set_rate(0.01)
        assert rig.mv.session.global_rate == 0.5

    def test_marker_seek_moves_the_playhead(self, rig) -> None:
        _load_both(rig, left_kwargs={"frame_time_ms": 100.0}, right_kwargs={"frame_time_ms": 100.0})
        _mark_both(rig, [0, 10], [0, 20])
        rig.mv.set_mode(PlaybackMode.EVENT_CYCLE)
        rig.mv.play()
        rig.clock.advance(0.3)
        rig.mv._on_clock_tick()
        rig.mv.pause()
        # clicking the left MK2 jumps to the end of the cycle on both panes
        rig.mv.seek_marker(PaneId.LEFT, 10)
        assert rig.mv.session.pane(PaneId.LEFT).current_frame == 10
        assert rig.mv.session.pane(PaneId.RIGHT).current_frame == 20

    def test_wheel_moves_the_shared_playhead(self, rig) -> None:
        _load_both(rig, left_kwargs={"frame_time_ms": 100.0}, right_kwargs={"frame_time_ms": 100.0})
        _mark_both(rig, [0, 10], [0, 20])
        rig.mv.set_mode(PlaybackMode.EVENT_CYCLE)
        rig.mv.play()
        rig.clock.advance(0.2)
        rig.mv._on_clock_tick()
        assert rig.mv.session.pane(PaneId.LEFT).current_frame == 1
        # 3 frames of the left clip = 0.3 s of the shared playhead
        rig.mv.scroll_by(PaneId.LEFT, 4)
        assert rig.mv.session.pane(PaneId.LEFT).current_frame == 3
        assert rig.mv.session.pane(PaneId.RIGHT).current_frame == 6

    def test_stop_returns_to_the_first_marker(self, rig) -> None:
        _load_both(rig, left_kwargs={"frame_time_ms": 100.0}, right_kwargs={"frame_time_ms": 100.0})
        _mark_both(rig, [2, 12], [4, 24])
        rig.mv.set_mode(PlaybackMode.EVENT_CYCLE)
        rig.mv.play()
        rig.clock.advance(0.3)
        rig.mv._on_clock_tick()
        rig.mv.stop()
        assert rig.mv.session.pane(PaneId.LEFT).current_frame == 2
        assert rig.mv.session.pane(PaneId.RIGHT).current_frame == 4

    def test_only_original_frames_are_shown(self, rig) -> None:
        _load_both(rig, left_kwargs={"frame_time_ms": 100.0}, right_kwargs={"frame_time_ms": 100.0})
        _mark_both(rig, [0, 10], [0, 20])
        rig.mv.set_mode(PlaybackMode.EVENT_CYCLE)
        rig.mv.play()
        seen = set()
        for step in range(0, 30):
            rig.clock.advance(0.05)
            rig.mv._on_clock_tick()
            seen.add(rig.mv.session.pane(PaneId.LEFT).current_frame)
            seen.add(rig.mv.session.pane(PaneId.RIGHT).current_frame)
        assert seen <= set(range(0, 21))


# ── markers ─────────────────────────────────────────────────────────


class TestClipReplacement:
    def test_replacing_a_clip_stops_the_synchronised_playback(self, rig) -> None:
        _load_both(rig, left_kwargs={"frame_time_ms": 100.0}, right_kwargs={"frame_time_ms": 100.0})
        _mark_both(rig, [0, 10], [0, 20])
        rig.mv.set_mode(PlaybackMode.EVENT_CYCLE)
        rig.mv.play()
        assert rig.mv.session.is_playing is True
        rig.mv.load_instance(PaneId.RIGHT, _instance(uid="right2", frames=40, frame_time_ms=50.0), "study.1")
        # spec 6.2: the replacement stops playback, it does not resume it
        assert rig.mv.session.is_playing is False

    def test_replacing_a_clip_clears_only_that_pane(self, rig) -> None:
        _load_both(rig)
        _mark_both(rig, [1, 5], [2, 7])
        rig.mv.set_frame(PaneId.LEFT, 3)
        rig.mv.load_instance(PaneId.RIGHT, _instance(uid="right2", frames=40), "study.1")
        left = rig.mv.session.pane(PaneId.LEFT)
        right = rig.mv.session.pane(PaneId.RIGHT)
        assert left.markers and left.current_frame == 3
        assert right.markers == []
        assert right.current_frame == 0
        assert right.instance_uid == "right2"

    def test_replacing_a_clip_drops_the_cached_plan(self, rig) -> None:
        _load_both(rig, left_kwargs={"frame_time_ms": 100.0}, right_kwargs={"frame_time_ms": 100.0})
        _mark_both(rig, [0, 10], [0, 20])
        rig.mv.set_mode(PlaybackMode.EVENT_CYCLE)
        assert rig.mv._schedule is not None
        rig.mv.load_instance(PaneId.RIGHT, _instance(uid="right2", frames=40), "study.1")
        assert rig.mv._schedule is None
        assert rig.mv._window is None


class TestMarkers:
    def test_markers_are_strictly_forward(self, rig) -> None:
        _load_both(rig)
        rig.mv.set_frame(PaneId.LEFT, 5)
        rig.mv.place_marker(PaneId.LEFT, 0)
        rig.mv.set_frame(PaneId.LEFT, 5)
        rig.mv.place_marker(PaneId.LEFT, 1)
        assert len(rig.mv.session.pane(PaneId.LEFT).markers) == 1
        assert rig.status[-1] == tr("multiview.marker.out_of_order")
        rig.mv.set_frame(PaneId.LEFT, 2)
        rig.mv.place_marker(PaneId.LEFT, 1)
        assert len(rig.mv.session.pane(PaneId.LEFT).markers) == 1

    def test_marker_on_the_last_frame_is_refused(self, rig) -> None:
        _load_both(rig, right_kwargs={"frames": 10})
        rig.mv.set_frame(PaneId.RIGHT, 9)
        rig.mv.place_marker(PaneId.RIGHT, 0)
        assert rig.mv.session.pane(PaneId.RIGHT).markers == []
        assert rig.status[-1] == tr("multiview.marker.no_room")

    def test_replacing_a_marker_drops_the_later_ones(self, rig) -> None:
        _load_both(rig)
        for frame in (2, 8, 15):
            rig.mv.set_frame(PaneId.LEFT, frame)
            rig.mv.place_marker(PaneId.LEFT, len(rig.mv.session.pane(PaneId.LEFT).markers))
        assert len(rig.mv.session.pane(PaneId.LEFT).markers) == 3
        rig.mv.set_frame(PaneId.LEFT, 5)
        rig.mv.place_marker(PaneId.LEFT, 1)
        markers = rig.mv.session.pane(PaneId.LEFT).markers
        assert [marker.frame_index for marker in markers] == [2, 5]

    def test_placing_a_marker_pauses_playback(self, rig) -> None:
        _load_both(rig, left_kwargs={"frame_time_ms": 100.0}, right_kwargs={"frame_time_ms": 100.0})
        _mark_both(rig, [0, 10], [0, 20])
        rig.mv.set_mode(PlaybackMode.EVENT_CYCLE)
        rig.mv.play()
        assert rig.mv.session.is_playing is True
        rig.mv.set_frame(PaneId.LEFT, 3)
        rig.mv.place_marker(PaneId.LEFT, 2)
        assert rig.mv.session.is_playing is False

    def test_marker_can_be_renamed(self, rig) -> None:
        _load_both(rig)
        _mark_both(rig, [1, 5], [2, 7])
        rig.mv.rename_marker(PaneId.LEFT, 0, "Tricuspid")
        assert rig.mv.session.pane(PaneId.LEFT).markers[0].label == "Tricuspid"
        # the other pane keeps the default label
        assert rig.mv.session.pane(PaneId.RIGHT).markers[0].label == DEFAULT_EVENT_LABEL

    def test_renaming_keeps_the_frame_and_the_order(self, rig) -> None:
        _load_both(rig)
        _mark_both(rig, [1, 5], [2, 7])
        rig.mv.rename_marker(PaneId.LEFT, 1, "End systole")
        markers = rig.mv.session.pane(PaneId.LEFT).markers
        assert [marker.frame_index for marker in markers] == [1, 5]
        assert [marker.label for marker in markers] == [DEFAULT_EVENT_LABEL, "End systole"]

    def test_blank_label_falls_back_to_the_default(self, rig) -> None:
        _load_both(rig)
        _mark_both(rig, [1, 5], [2, 7])
        rig.mv.rename_marker(PaneId.LEFT, 0, "   ")
        assert rig.mv.session.pane(PaneId.LEFT).markers[0].label == DEFAULT_EVENT_LABEL

    def test_long_label_is_capped(self, rig) -> None:
        _load_both(rig)
        _mark_both(rig, [1, 5], [2, 7])
        rig.mv.rename_marker(PaneId.LEFT, 0, "X" * 200)
        assert len(rig.mv.session.pane(PaneId.LEFT).markers[0].label) == MAX_EVENT_LABEL

    def test_renaming_an_unknown_marker_is_ignored(self, rig) -> None:
        _load_both(rig)
        _mark_both(rig, [1, 5], [2, 7])
        rig.mv.rename_marker(PaneId.LEFT, 9, "Nope")
        assert len(rig.mv.session.pane(PaneId.LEFT).markers) == 2
        rig.mv.rename_marker(PaneId.LEFT, -1, "Nope")
        assert len(rig.mv.session.pane(PaneId.LEFT).markers) == 2

    def test_clear_markers_is_per_pane(self, rig) -> None:
        _load_both(rig)
        _mark_both(rig, [1, 5], [2, 7])
        rig.mv.clear_markers(PaneId.LEFT)
        assert rig.mv.session.pane(PaneId.LEFT).markers == []
        assert len(rig.mv.session.pane(PaneId.RIGHT).markers) == 2

    def test_clear_all_markers(self, rig) -> None:
        _load_both(rig)
        _mark_both(rig, [1, 5], [2, 7])
        rig.mv.clear_all_markers()
        assert rig.mv.session.pane(PaneId.LEFT).markers == []
        assert rig.mv.session.pane(PaneId.RIGHT).markers == []

    def test_remove_marker_truncates_the_sequence(self, rig) -> None:
        _load_both(rig)
        _mark_both(rig, [1, 5, 9], [1, 5, 9])
        rig.mv.remove_marker(PaneId.LEFT, 1)
        assert [marker.frame_index for marker in rig.mv.session.pane(PaneId.LEFT).markers] == [1]
        assert len(rig.mv.session.pane(PaneId.RIGHT).markers) == 3


# ── robustness ──────────────────────────────────────────────────────


class TestRobustness:
    def test_stale_loader_answer_is_dropped(self, rig) -> None:
        _load_both(rig)
        pane = rig.mv.session.pane(PaneId.RIGHT)
        stale_generation = pane.generation
        rig.mv.load_instance(PaneId.RIGHT, _instance(uid="right2", path="/tmp/right2.dcm"), "study.1")
        painted_before = len(rig.panes[PaneId.RIGHT].viewer.frames)
        # a late answer for the replaced clip must not repaint the pane
        rig.mv._on_pane_frame(PaneId.RIGHT, stale_generation, 3, np.full((2, 2), 99, dtype=np.uint8))
        assert len(rig.panes[PaneId.RIGHT].viewer.frames) == painted_before
        assert rig.mv.session.pane(PaneId.RIGHT).current_frame == 0

    def test_only_one_request_per_pane_is_in_flight(self, rig) -> None:
        _load_both(rig)
        for frame in range(1, 12):
            rig.mv.set_frame(PaneId.RIGHT, frame)
        # the newest frame wins, no queue of stale requests accumulates
        assert rig.mv.session.pane(PaneId.RIGHT).current_frame == 11
        assert _painted_frames(rig.panes[PaneId.RIGHT])[-1] == 11

    def test_load_failure_pauses_and_reports(self, rig) -> None:
        _load_both(rig, left_kwargs={"frame_time_ms": 100.0}, right_kwargs={"frame_time_ms": 100.0})
        _mark_both(rig, [0, 10], [0, 20])
        rig.mv.set_mode(PlaybackMode.EVENT_CYCLE)
        rig.mv.play()
        pane = rig.mv.session.pane(PaneId.RIGHT)
        rig.mv._on_pane_frame_failed(PaneId.RIGHT, pane.generation, "decode error")
        assert rig.mv.session.is_playing is False
        assert pane.load_error == "decode error"
        assert rig.status[-1] == "decode error"

    def test_shutdown_stops_the_clock(self, rig) -> None:
        _load_both(rig, left_kwargs={"frame_time_ms": 100.0}, right_kwargs={"frame_time_ms": 100.0})
        rig.mv.set_mode(PlaybackMode.COMMON_WINDOW)
        rig.mv.play()
        rig.clock.advance(0.5)
        rig.mv._on_clock_tick()
        painted = len(rig.panes[PaneId.LEFT].viewer.frames)
        rig.mv.shutdown()
        assert rig.mv._panes == {}
        assert rig.mv._clock_timer.isActive() is False
        # a late tick must not touch a torn-down session
        rig.clock.advance(0.5)
        rig.mv._on_clock_tick()
        assert len(rig.panes[PaneId.LEFT].viewer.frames) == painted

    def test_mode_switch_stops_playback(self, rig) -> None:
        _load_both(rig, left_kwargs={"frame_time_ms": 100.0}, right_kwargs={"frame_time_ms": 100.0})
        rig.mv.set_mode(PlaybackMode.COMMON_WINDOW)
        rig.mv.play()
        assert rig.mv.session.is_playing is True
        rig.mv.set_mode(PlaybackMode.INDEPENDENT)
        assert rig.mv.session.is_playing is False
        assert rig.mv._owns_left is False

    def test_toggle_play_delegates_to_the_controller_in_independent_mode(self, rig) -> None:
        _load_both(rig)
        rig.mv.toggle_play(PaneId.LEFT)
        rig.controller.toggle_playback.assert_called_once_with()

    def test_now_uses_a_monotonic_clock(self) -> None:
        controller = MagicMock()
        mv = MultiViewController(controller)
        first = mv._now_ms()
        # 0.01 s is below the clock granularity of some Windows runners.
        time.sleep(0.05)
        assert mv._now_ms() > first
