"""Pure geometry for the cardiac phase strip above a frame slider.

Kept free of Qt so the pixel↔frame mapping can be unit-tested without a display.
The constants mirror the groove of a horizontal ``QSlider``: its handle centre
never reaches the very edge of the widget, so frame 0 and frame N-1 must be
drawn ``SLIDER_INSET`` pixels inside the strip.
"""

from __future__ import annotations

from collections.abc import Iterator

from echo_personal_tool.domain.services.cine_phase_timeline import PhaseMarker, PhaseTimeline

SLIDER_INSET = 9.0


def frame_ratio(frame: int, total_frames: int) -> float:
    if total_frames <= 1:
        return 0.0
    return min(1.0, max(0.0, float(frame) / float(total_frames - 1)))


def x_for_frame(frame: int, total_frames: int, left: float, width: float, inset: float = SLIDER_INSET) -> float:
    usable = max(0.0, float(width) - 2.0 * inset)
    return float(left) + inset + usable * frame_ratio(frame, total_frames)


def frame_at_x(x: float, total_frames: int, left: float, width: float, inset: float = SLIDER_INSET) -> int:
    if total_frames <= 1:
        return 0
    usable = max(1.0, float(width) - 2.0 * inset)
    ratio = min(1.0, max(0.0, (float(x) - float(left) - inset) / usable))
    return int(round(ratio * (total_frames - 1)))


def segment_rects(
    timeline: PhaseTimeline,
    left: float,
    width: float,
    inset: float = SLIDER_INSET,
) -> Iterator[tuple[float, float, object]]:
    """Yield ``(x_start, x_end, PhaseSegment)`` in frame order."""
    total = timeline.n_frames
    for segment in timeline.segments():
        yield (
            x_for_frame(segment.start_frame, total, left, width, inset),
            x_for_frame(segment.end_frame, total, left, width, inset),
            segment,
        )


def marker_points(
    timeline: PhaseTimeline,
    left: float,
    width: float,
    inset: float = SLIDER_INSET,
) -> Iterator[tuple[float, PhaseMarker]]:
    """Yield ``(x, PhaseMarker)`` in frame order."""
    for marker in timeline.markers():
        yield x_for_frame(marker.frame, timeline.n_frames, left, width, inset), marker
