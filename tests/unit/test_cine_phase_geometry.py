"""Pure geometry tests for the phase strip (no Qt required)."""

from __future__ import annotations

import numpy as np

from echo_personal_tool.domain.services.cine_phase_timeline import build_phase_timeline
from echo_personal_tool.presentation.cine_phase_geometry import (
    SLIDER_INSET,
    frame_at_x,
    frame_ratio,
    marker_points,
    segment_rects,
    x_for_frame,
)


def _timeline() -> object:
    n = 72
    curve = np.cos(2 * np.pi * (np.arange(n) - 3) / 24)
    return build_phase_timeline(n_frames=n, frame_time_ms=33.3, area_curve=curve)


def test_frame_ratio_clamps_to_unit_interval() -> None:
    assert frame_ratio(-5, 20) == 0.0
    assert frame_ratio(19, 20) == 1.0
    assert frame_ratio(30, 20) == 1.0
    assert frame_ratio(3, 1) == 0.0


def test_first_and_last_frame_sit_under_the_slider_handle_centres() -> None:
    left, width = 0.0, 400.0
    first = x_for_frame(0, 60, left, width)
    last = x_for_frame(59, 60, left, width)
    assert first == SLIDER_INSET
    assert last == width - SLIDER_INSET
    assert first < x_for_frame(30, 60, left, width) < last


def test_x_and_frame_are_inverse() -> None:
    for frame in (0, 1, 7, 30, 58, 59):
        x = x_for_frame(frame, 60, 0.0, 400.0)
        assert frame_at_x(x, 60, 0.0, 400.0) == frame


def test_segments_are_ordered_and_cover_the_track() -> None:
    timeline = _timeline()
    rects = list(segment_rects(timeline, 0.0, 400.0))
    assert rects
    assert rects[0][0] == SLIDER_INSET
    assert rects[-1][1] == 400.0 - SLIDER_INSET
    assert all(x0 <= x1 for x0, x1, _ in rects)
    assert all(rects[i][1] <= rects[i + 1][0] + 1e-9 for i in range(len(rects) - 1))


def test_marker_points_follow_frame_positions() -> None:
    timeline = _timeline()
    points = list(marker_points(timeline, 0.0, 400.0))
    assert len(points) == 2 * len(timeline.cycles)
    assert any(abs(x - x_for_frame(3, timeline.n_frames, 0.0, 400.0)) < 1e-9 and m.kind == "ed" for x, m in points)
    assert any(abs(x - x_for_frame(15, timeline.n_frames, 0.0, 400.0)) < 1e-9 and m.kind == "es" for x, m in points)
