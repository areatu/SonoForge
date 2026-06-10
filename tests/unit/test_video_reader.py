"""Unit tests for VideoReader."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from echo_personal_tool.infrastructure.video_reader import RING_BUFFER_SIZE, VideoReader


def _write_synthetic_mp4(
    path: Path,
    *,
    frame_count: int = 10,
    width: int = 32,
    height: int = 24,
    fps: float = 25.0,
) -> None:
    # MJPG fourcc produces distinct sequential frames in headless OpenCV builds.
    fourcc = cv2.VideoWriter_fourcc(*"MJPG")
    writer = cv2.VideoWriter(str(path), fourcc, fps, (width, height), isColor=True)
    if not writer.isOpened():
        raise RuntimeError("Failed to open VideoWriter for synthetic MP4")
    try:
        for index in range(frame_count):
            value = index % 256
            frame = np.full((height, width, 3), value, dtype=np.uint8)
            writer.write(frame)
    finally:
        writer.release()


def test_open_read_frame_count_and_shape(tmp_path: Path) -> None:
    video_path = tmp_path / "clip.mp4"
    _write_synthetic_mp4(video_path, frame_count=5, width=40, height=30, fps=30.0)

    reader = VideoReader()
    reader.open(video_path)

    assert reader.frame_count == 5
    assert reader.fps == pytest.approx(30.0)

    frame = reader.read_frame(0)
    assert frame.shape == (30, 40, 3)
    assert frame.dtype == np.uint8
    assert int(frame[0, 0, 0]) == 0

    frame3 = reader.read_frame(3)
    assert int(frame3[0, 0, 0]) == 3

    reader.release()


def test_read_frame_out_of_range_raises(tmp_path: Path) -> None:
    video_path = tmp_path / "clip.mp4"
    _write_synthetic_mp4(video_path, frame_count=3)

    reader = VideoReader()
    reader.open(video_path)

    with pytest.raises(IndexError):
        reader.read_frame(3)

    reader.release()


def test_ring_buffer_evicts_oldest_frames(tmp_path: Path) -> None:
    total_frames = RING_BUFFER_SIZE + 10
    video_path = tmp_path / "long_clip.mp4"
    _write_synthetic_mp4(video_path, frame_count=total_frames)

    reader = VideoReader()
    reader.open(video_path)

    for index in range(total_frames):
        reader.read_frame(index)

    for evicted in range(10):
        with pytest.raises(KeyError):
            reader.get_buffered_frame(evicted)

    for kept in range(10, total_frames):
        buffered = reader.get_buffered_frame(kept)
        assert int(buffered[0, 0, 0]) == kept

    reader.release()


def test_get_buffered_frame_without_read_raises(tmp_path: Path) -> None:
    video_path = tmp_path / "clip.mp4"
    _write_synthetic_mp4(video_path, frame_count=2)

    reader = VideoReader()
    reader.open(video_path)

    with pytest.raises(KeyError):
        reader.get_buffered_frame(0)

    reader.release()


def test_context_manager_releases_capture(tmp_path: Path) -> None:
    video_path = tmp_path / "clip.mp4"
    _write_synthetic_mp4(video_path, frame_count=2)

    with VideoReader() as reader:
        reader.open(video_path)
        assert reader.frame_count == 2

    with pytest.raises(RuntimeError):
        reader.read_frame(0)
