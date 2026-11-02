"""Unit tests for thumbnail frame selection logic."""

from __future__ import annotations

import pytest

from echo_personal_tool.application.workers.thumbnail_loader_worker import thumbnail_frame_index


@pytest.mark.parametrize(
    ("number_of_frames", "expected_index"),
    [
        (1, 0),
        (2, 0),
        (3, 1),
        (4, 1),
        (5, 2),
        (10, 4),
    ],
)
def test_thumbnail_frame_index(number_of_frames: int, expected_index: int) -> None:
    assert thumbnail_frame_index(number_of_frames) == expected_index
