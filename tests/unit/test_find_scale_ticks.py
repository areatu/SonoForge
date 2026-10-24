from __future__ import annotations

import numpy as np

from echo_personal_tool.domain.services.depth_scale_detector import (
    find_best_scale_column,
    find_scale_ticks,
)


def _frame_with_ticks_on_right(
    height: int = 400,
    width: int = 640,
    tick_x: int = 600,
    tick_spacing: int = 20,
) -> np.ndarray:
    frame = np.zeros((height, width), dtype=np.uint8)
    frame[:, 50:550] = np.random.randint(10, 60, (height, 500), dtype=np.uint8)
    for y in range(10, height - 10, tick_spacing):
        frame[y, tick_x : tick_x + 8] = 200
    return frame


def test_find_best_scale_column_returns_x_near_ticks() -> None:
    frame = _frame_with_ticks_on_right(tick_x=600)
    x = find_best_scale_column(frame)
    assert 580 <= x <= 620


def test_find_best_scale_column_blank_frame_returns_zero() -> None:
    frame = np.zeros((200, 120), dtype=np.uint8)
    x = find_best_scale_column(frame)
    assert x == 0


def test_find_scale_ticks_returns_list() -> None:
    frame = _frame_with_ticks_on_right()
    ticks = find_scale_ticks(frame)
    assert len(ticks) >= 5


def test_find_scale_ticks_blank_frame() -> None:
    frame = np.zeros((200, 120), dtype=np.uint8)
    ticks = find_scale_ticks(frame)
    assert ticks == []
