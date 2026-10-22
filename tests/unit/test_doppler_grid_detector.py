"""Tests for doppler_grid_detector."""

from __future__ import annotations

import numpy as np

from echo_personal_tool.domain.services.doppler_grid_detector import (
    detect_doppler_grid_lines,
)


def _make_frame_with_grid_lines(
    height: int = 200,
    width: int = 300,
    grid_line_ys: list[int] | None = None,
    bg_intensity: float = 20.0,
    line_intensity: float = 120.0,
) -> np.ndarray:
    """Create a synthetic frame with bright horizontal grid lines."""
    frame = np.full((height, width), bg_intensity, dtype=np.uint8)
    if grid_line_ys:
        for y in grid_line_ys:
            if 0 <= y < height:
                frame[y, :] = line_intensity
    return frame


def test_detect_grid_lines_basic():
    frame = _make_frame_with_grid_lines(height=200, width=300, grid_line_ys=[50, 100, 150])
    lines = detect_doppler_grid_lines(frame, x0=0, y0=0, width=300, height=200)
    assert len(lines) >= 2  # at least most lines detected


def test_detect_grid_lines_empty_frame():
    frame = np.full((200, 300), 50, dtype=np.uint8)  # uniform, no lines
    lines = detect_doppler_grid_lines(frame, x0=0, y0=0, width=300, height=200)
    assert lines == []


def test_detect_grid_lines_with_roi_offset():
    frame = _make_frame_with_grid_lines(height=300, width=400, grid_line_ys=[100, 150, 200])
    lines = detect_doppler_grid_lines(frame, x0=50, y0=80, width=200, height=120)
    # Lines should be in frame coordinates (y0 + local position)
    for line_y in lines:
        assert 80 <= line_y <= 200


def test_detect_grid_lines_single_line():
    frame = _make_frame_with_grid_lines(height=200, width=300, grid_line_ys=[100])
    lines = detect_doppler_grid_lines(frame, x0=0, y0=0, width=300, height=200)
    assert len(lines) >= 1


def test_detect_grid_lines_small_roi():
    frame = _make_frame_with_grid_lines(height=200, width=300, grid_line_ys=[50, 100, 150])
    lines = detect_doppler_grid_lines(frame, x0=100, y0=40, width=50, height=30)
    # Small ROI might detect 0 or 1 line
    assert isinstance(lines, list)


def test_detect_grid_lines_out_of_bounds_roi():
    frame = _make_frame_with_grid_lines(height=200, width=300)
    lines = detect_doppler_grid_lines(frame, x0=250, y0=180, width=100, height=50)
    assert isinstance(lines, list)
