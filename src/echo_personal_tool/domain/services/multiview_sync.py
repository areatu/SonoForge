"""Pure timing maths for Multiview playback synchronisation.

No Qt, no DICOM, no numpy: everything here works on plain floats so the rules
of the spec (``docs/superpowers/specs/2026-10-01-multiview-two-clips-spec-ru.md``,
§8) can be verified by unit tests alone.

Two synchronisation modes are supported:

``COMMON_WINDOW``
    Both clips start together and run for the shorter of the two remaining
    durations.  Time-based, *not* phase-based.

``EVENT_CYCLE``
    Each cycle is normalised to a common display duration; every clip keeps its
    own speed factor ``k`` (``k < 1`` stretch/slow down, ``k > 1``
    compress/speed up).  Only original frames are shown: no interpolation and
    no synthetic frames are ever produced.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import NamedTuple

from echo_personal_tool.domain.models.metadata import InstanceMetadata
from echo_personal_tool.domain.models.multiview import (
    MAX_GLOBAL_RATE,
    MIN_GLOBAL_RATE,
    EventMarker,
)

#: Outside this band the UI must warn before starting the cycle (spec §8.4).
RETIMING_WARNING_MIN = 0.5
RETIMING_WARNING_MAX = 2.0

_EPS = 1e-9


# ── per-clip timing helpers ─────────────────────────────────────────


def frame_time_ms(instance: InstanceMetadata | None, frame_index: int) -> float | None:
    """Duration of a single frame in milliseconds, or ``None`` if unknown."""
    if instance is None or frame_index < 0:
        return None
    vector = instance.frame_time_vector
    if vector is not None and frame_index < len(vector):
        value = float(vector[frame_index])
        if value > 0:
            return value
        # A zero/negative entry is a broken tag: fall back to FrameTime.
    if instance.frame_time_ms is not None and instance.frame_time_ms > 0:
        return float(instance.frame_time_ms)
    return None


def frame_start_seconds(instance: InstanceMetadata | None, frame_index: int) -> float | None:
    """Wall-clock offset of ``frame_index`` from the first frame (seconds)."""
    if instance is None or frame_index < 0:
        return None
    total = 0.0
    for index in range(frame_index):
        step = frame_time_ms(instance, index)
        if step is None:
            return None
        total += step
    return total / 1000.0


def interval_seconds(
    instance: InstanceMetadata | None,
    start_frame: int,
    end_frame: int,
) -> float | None:
    """Duration of the inclusive frame interval ``[start_frame, end_frame]``."""
    if instance is None or end_frame <= start_frame:
        return None
    start = frame_start_seconds(instance, start_frame)
    if start is None:
        return None
    end = frame_start_seconds(instance, end_frame)
    if end is None:
        return None
    duration = end - start
    if duration <= 0:
        return None
    return duration


def remaining_seconds(instance: InstanceMetadata | None, start_frame: int) -> float | None:
    """Duration from ``start_frame`` to the end of the clip.

    ``None`` means the clip carries no usable timing, which is different from
    ``0.0`` (the pane already sits on its last frame).
    """
    if instance is None:
        return None
    start = clamp_frame(instance, start_frame)
    end = last_frame_index(instance)
    if end <= start:
        return 0.0
    return interval_seconds(instance, start, end)


def frame_after_seconds(instance: InstanceMetadata | None, start_frame: int, seconds: float) -> int:
    """Frame shown ``seconds`` after ``start_frame``; frames are held, never blended.

    Only original frames are ever returned: the walk advances one frame at a
    time and stops at the last frame whose display interval started before the
    target time.
    """
    last = last_frame_index(instance)
    start = clamp_frame(instance, start_frame)
    if instance is None or last <= start or seconds <= 0:
        return start
    target_ms = float(seconds) * 1000.0
    elapsed_ms = 0.0
    index = start
    while index < last:
        step_ms = frame_time_ms(instance, index)
        if step_ms is None:
            # Unknown timing: fall back to the nominal frame step so the pane
            # still advances instead of freezing.
            step_ms = NOMINAL_FRAME_TIME_MS
        if elapsed_ms + step_ms > target_ms + _EPS:
            break
        elapsed_ms += step_ms
        index += 1
    return index


def last_frame_index(instance: InstanceMetadata | None) -> int:
    """Last valid frame index of a clip (0 for an empty/unknown clip)."""
    if instance is None:
        return 0
    total = int(instance.number_of_frames or 0)
    return max(0, total - 1)


def clamp_frame(instance: InstanceMetadata | None, frame_index: int) -> int:
    return max(0, min(last_frame_index(instance), int(frame_index)))


def clamp_rate(rate: float) -> float:
    """Clamp the global transport rate into the supported 0.5×–2.0× band."""
    if not math.isfinite(rate):
        return 1.0
    return max(MIN_GLOBAL_RATE, min(MAX_GLOBAL_RATE, float(rate)))


# ── common window (spec §8.2) ───────────────────────────────────────


@dataclass(frozen=True)
class CommonWindow:
    """Result of planning the ``Общий фрагмент`` playback."""

    left_start: int
    left_end: int
    right_start: int
    right_end: int
    duration_s: float | None

    @property
    def is_valid(self) -> bool:
        return self.duration_s is not None and self.duration_s > 0

    @property
    def has_timing(self) -> bool:
        return self.duration_s is not None


def plan_common_window(
    left: InstanceMetadata | None,
    left_start: int,
    right: InstanceMetadata | None,
    right_start: int,
) -> CommonWindow:
    """Both clips start at their own frame and stop at the shorter remainder.

    ``T_common = min(T_left_remaining, T_right_remaining)``.  When frame timing
    is unknown the window is still playable but frame-based only: the caller
    must then show ``время неизвестно`` instead of a duration.
    """
    left_start = clamp_frame(left, left_start)
    right_start = clamp_frame(right, right_start)
    left_seconds = remaining_seconds(left, left_start)
    right_seconds = remaining_seconds(right, right_start)
    duration: float | None
    if left_seconds is None or right_seconds is None:
        duration = None
    else:
        duration = min(left_seconds, right_seconds)
    if duration is None or duration <= 0:
        # Frame-count fallback: the caller reports "time unknown".
        shared_frames = min(
            last_frame_index(left) - left_start,
            last_frame_index(right) - right_start,
        )
        left_end = clamp_frame(left, left_start + max(0, shared_frames))
        right_end = clamp_frame(right, right_start + max(0, shared_frames))
    else:
        left_end = frame_after_seconds(left, left_start, duration)
        right_end = frame_after_seconds(right, right_start, duration)
    return CommonWindow(
        left_start=left_start,
        left_end=left_end,
        right_start=right_start,
        right_end=right_end,
        duration_s=duration,
    )


def common_window_frames(
    window: CommonWindow,
    elapsed_s: float,
    left: InstanceMetadata | None = None,
    right: InstanceMetadata | None = None,
) -> tuple[int, int]:
    """Frame index of each pane after ``elapsed_s`` inside a common window.

    The window is **time-based**: both panes advance by the same wall-clock
    offset, each at its own frame rate (``по времени, не по фазе``).  Without
    the clips the pre-computed end frames are returned, which keeps the
    endpoint hold correct.
    """
    duration = window.duration_s
    if duration is None or duration <= 0:
        return window.left_start, window.right_start
    offset = min(duration, max(0.0, elapsed_s))
    if left is None or right is None:
        return window.left_end, window.right_end
    return (
        frame_after_seconds(left, window.left_start, offset),
        frame_after_seconds(right, window.right_start, offset),
    )


# ── event cycles (spec §8.3) ────────────────────────────────────────


class SyncCycle(NamedTuple):
    """One cycle between two neighbouring markers of a pane."""

    start_frame: int
    end_frame: int


@dataclass(frozen=True)
class CycleTiming:
    """Speed factors of one paired cycle at a given global rate."""

    t_display_s: float
    k_left: float
    k_right: float

    @property
    def max_abs_deviation(self) -> float:
        return max(abs(self.k_left - 1.0), abs(self.k_right - 1.0))

    @property
    def needs_warning(self) -> bool:
        return self.k_left < RETIMING_WARNING_MIN or self.k_right > RETIMING_WARNING_MAX


def display_cycle_duration(t_left_s: float, t_right_s: float, global_rate: float) -> float:
    """``T_display = mean(T_left, T_right) / r``."""
    rate = clamp_rate(global_rate)
    return ((t_left_s + t_right_s) / 2.0) / rate


def cycle_timing(t_left_s: float, t_right_s: float, global_rate: float) -> CycleTiming:
    """Per-clip speed factors so both cycles occupy ``T_display`` seconds."""
    t_display = display_cycle_duration(t_left_s, t_right_s, global_rate)
    if t_display <= 0:
        return CycleTiming(t_display_s=0.0, k_left=1.0, k_right=1.0)
    return CycleTiming(
        t_display_s=t_display,
        k_left=t_left_s / t_display,
        k_right=t_right_s / t_display,
    )


#: Assumed frame duration when neither FrameTime nor FrameTimeVector is present.
#: Used only to keep a phase-based cycle *navigable*; the UI must then report
#: «время неизвестно» and never claim real-time synchronisation (spec §8.4).
NOMINAL_FRAME_TIME_MS = 33.3


def interval_seconds_or_nominal(
    instance: InstanceMetadata | None,
    start_frame: int,
    end_frame: int,
) -> tuple[float, bool]:
    """Interval duration in seconds plus a flag telling whether it is real."""
    duration = interval_seconds(instance, start_frame, end_frame)
    if duration is not None:
        return duration, True
    frames = max(0, end_frame - start_frame)
    return frames * NOMINAL_FRAME_TIME_MS / 1000.0, False


@dataclass(frozen=True)
class CycleScheduleEntry:
    """One paired cycle with its position inside the whole loop."""

    cycle_index: int
    start_s: float
    duration_s: float
    left: SyncCycle
    right: SyncCycle
    timing: CycleTiming
    timing_known: bool


@dataclass(frozen=True)
class CycleSchedule:
    """The full ``MK…MK`` loop: N paired cycles back to back."""

    entries: tuple[CycleScheduleEntry, ...]
    timing_known: bool

    @property
    def total_s(self) -> float:
        return sum(entry.duration_s for entry in self.entries)

    @property
    def is_valid(self) -> bool:
        return bool(self.entries) and self.total_s > 0

    def locate(self, elapsed_s: float) -> tuple[CycleScheduleEntry | None, float]:
        """Cycle containing ``elapsed_s`` plus the normalised phase inside it.

        A boundary belongs to the cycle that starts there: reaching ``MK1``
        switches the playhead to the second cycle (spec §7.3).
        """
        if not self.entries:
            return None, 0.0
        remaining = min(max(elapsed_s, 0.0), self.total_s)
        for index, entry in enumerate(self.entries):
            is_last = index == len(self.entries) - 1
            if is_last or remaining < entry.start_s + entry.duration_s:
                span = entry.duration_s
                phase = 0.0 if span <= 0 else (remaining - entry.start_s) / span
                return entry, min(1.0, max(0.0, phase))
        return self.entries[-1], 1.0


def build_cycle_schedule(
    left: InstanceMetadata | None,
    left_cycles: Sequence[SyncCycle],
    right: InstanceMetadata | None,
    right_cycles: Sequence[SyncCycle],
    global_rate: float,
) -> CycleSchedule:
    """Pair the cycles of both panes into one looping schedule.

    Each cycle gets its own display duration and its own per-clip speed factor,
    so ``MK0→MK1`` and ``MK1→MK2`` compensate different RR lengths separately
    instead of averaging one factor over the whole two-cycle clip (spec §7.3).
    """
    pairs = min(len(left_cycles), len(right_cycles))
    entries: list[CycleScheduleEntry] = []
    cursor = 0.0
    timing_known = pairs > 0
    for index in range(pairs):
        left_cycle = left_cycles[index]
        right_cycle = right_cycles[index]
        t_left, left_known = interval_seconds_or_nominal(left, left_cycle.start_frame, left_cycle.end_frame)
        t_right, right_known = interval_seconds_or_nominal(right, right_cycle.start_frame, right_cycle.end_frame)
        timing = cycle_timing(t_left, t_right, global_rate)
        entries.append(
            CycleScheduleEntry(
                cycle_index=index,
                start_s=cursor,
                duration_s=timing.t_display_s,
                left=left_cycle,
                right=right_cycle,
                timing=timing,
                timing_known=left_known and right_known,
            )
        )
        cursor += timing.t_display_s
        timing_known = timing_known and left_known and right_known
    return CycleSchedule(entries=tuple(entries), timing_known=timing_known)


def cycles_from_markers(markers: Sequence[EventMarker], cycle_count: int) -> tuple[SyncCycle, ...]:
    """Cycles implied by the ordered markers of one pane.

    ``cycle_count == 1`` needs two markers (``MK1→MK2``), ``cycle_count == 2``
    needs three (``MK0→MK1→MK2``).  Anything shorter yields no cycle.
    """
    needed = max(2, int(cycle_count) + 1)
    if len(markers) < needed:
        return ()
    count = min(int(cycle_count), len(markers) - 1)
    return tuple(
        SyncCycle(start_frame=markers[index].frame_index, end_frame=markers[index + 1].frame_index)
        for index in range(count)
    )


def markers_ready(markers: Sequence[EventMarker], cycle_count: int) -> bool:
    return bool(cycles_from_markers(markers, cycle_count))


def frame_at_phase(
    instance: InstanceMetadata | None,
    start_frame: int,
    end_frame: int,
    phase: float,
) -> int:
    """Original frame shown at normalised position ``phase`` (0…1).

    No interpolation: the nearest available *original* frame is returned, so a
    slowed-down interval simply holds frames longer and a sped-up interval
    skips some of them.  Without frame timing only frame-index interpolation is
    possible and the caller must label the result as phase-only.
    """
    if end_frame <= start_frame:
        return start_frame
    ratio = min(1.0, max(0.0, float(phase)))
    if ratio >= 1.0:
        return end_frame
    duration = interval_seconds(instance, start_frame, end_frame)
    if duration is None:
        return start_frame + int(round(ratio * (end_frame - start_frame)))
    target = ratio * duration
    base = frame_start_seconds(instance, start_frame) or 0.0
    chosen = start_frame
    for index in range(start_frame, end_frame + 1):
        offset = frame_start_seconds(instance, index)
        if offset is None:
            break
        if offset - base <= target + _EPS:
            chosen = index
        else:
            break
    return chosen


def phase_of_frame(
    instance: InstanceMetadata | None,
    start_frame: int,
    end_frame: int,
    frame_index: int,
) -> float:
    """Inverse of :func:`frame_at_phase` — normalised position of a frame."""
    if end_frame <= start_frame:
        return 0.0
    clamped = min(max(frame_index, start_frame), end_frame)
    if clamped >= end_frame:
        return 1.0
    duration = interval_seconds(instance, start_frame, end_frame)
    if duration is None:
        return (clamped - start_frame) / float(end_frame - start_frame)
    base = frame_start_seconds(instance, start_frame)
    offset = frame_start_seconds(instance, clamped)
    if base is None or offset is None:
        return (clamped - start_frame) / float(end_frame - start_frame)
    return min(1.0, max(0.0, (offset - base) / duration))


# ── marker validation (spec §7.1) ──────────────────────────────────


def validate_new_marker(
    markers: Sequence[EventMarker],
    frame_index: int,
    total_frames: int,
) -> str | None:
    """Return an i18n key describing why a marker cannot be placed.

    ``None`` means the marker is acceptable.  Markers must move strictly
    forward in time: duplicates and out-of-order placements are rejected, and a
    marker needs at least one frame after it for the closing event of a cycle.
    """
    if frame_index < 0:
        return "multiview.marker.invalid_frame"
    if total_frames > 0:
        if frame_index >= total_frames:
            return "multiview.marker.invalid_frame"
        if frame_index + 1 >= total_frames:
            return "multiview.marker.no_room"
    if markers and frame_index <= markers[-1].frame_index:
        return "multiview.marker.out_of_order"
    return None
