"""Unit tests for thread-local MP4 reader reuse."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from echo_personal_tool.infrastructure.video_reader import get_thread_video_reader
from tests.fixtures.generate_synthetic_media import write_synthetic_mp4


def test_thread_local_reader_sequential_playback(tmp_path: Path) -> None:
    path = tmp_path / "clip.mp4"
    write_synthetic_mp4(path, frame_count=6, width=16, height=12)

    reader = get_thread_video_reader()
    reader.open(path)

    frame0 = reader.read_frame(0)
    frame1 = reader.read_frame(1)
    frame2 = reader.read_frame(2)

    assert frame0.shape == (12, 16, 3)
    assert int(frame1[0, 0, 0]) == 1
    assert int(frame2[0, 0, 0]) == 2
    assert not np.array_equal(frame0, frame1)
