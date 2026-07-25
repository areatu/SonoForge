"""Extended unit tests for infrastructure/video_reader.py — covers buffer, context manager, edge cases."""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.infrastructure.video_reader import (
    RING_BUFFER_SIZE,
    VideoReader,
    get_thread_video_reader,
)
from tests.fixtures.generate_synthetic_media import write_synthetic_mp4


class TestVideoReaderConstruction:
    def test_default_buffer_size(self):
        reader = VideoReader()
        assert reader._buffer_size == RING_BUFFER_SIZE
        assert reader._frame_count == 0
        assert reader._fps == 0.0
        assert reader._capture is None

    def test_custom_buffer_size(self):
        reader = VideoReader(buffer_size=10)
        assert reader._buffer_size == 10


class TestVideoReaderOpen:
    def test_open_and_properties(self, tmp_path):
        path = tmp_path / "test.mp4"
        write_synthetic_mp4(path, frame_count=5, width=16, height=12)
        reader = VideoReader()
        reader.open(path)
        assert reader.frame_count == 5
        assert reader.fps > 0
        reader.release()

    def test_open_nonexistent_raises(self):
        reader = VideoReader()
        with pytest.raises(OSError, match="Cannot open video"):
            reader.open("/nonexistent/path.mp4")

    def test_open_same_path_noop(self, tmp_path):
        path = tmp_path / "test.mp4"
        write_synthetic_mp4(path, frame_count=3, width=16, height=12)
        reader = VideoReader()
        reader.open(path)
        cap_before = reader._capture
        reader.open(path)  # same path → should not recreate
        assert reader._capture is cap_before
        reader.release()


class TestVideoReaderReadFrame:
    def test_read_frame_sequential(self, tmp_path):
        path = tmp_path / "test.mp4"
        write_synthetic_mp4(path, frame_count=6, width=16, height=12)
        reader = VideoReader()
        reader.open(path)
        for i in range(6):
            frame = reader.read_frame(i)
            assert frame.shape == (12, 16, 3)
        reader.release()

    def test_read_frame_not_open_raises(self):
        reader = VideoReader()
        with pytest.raises(RuntimeError, match="not open"):
            reader.read_frame(0)

    def test_read_frame_negative_index_raises(self, tmp_path):
        path = tmp_path / "test.mp4"
        write_synthetic_mp4(path, frame_count=3, width=16, height=12)
        reader = VideoReader()
        reader.open(path)
        with pytest.raises(IndexError, match="out of range"):
            reader.read_frame(-1)
        reader.release()

    def test_read_frame_out_of_range_raises(self, tmp_path):
        path = tmp_path / "test.mp4"
        write_synthetic_mp4(path, frame_count=3, width=16, height=12)
        reader = VideoReader()
        reader.open(path)
        with pytest.raises(IndexError, match="out of range"):
            reader.read_frame(100)
        reader.release()

    def test_read_frame_random_access(self, tmp_path):
        path = tmp_path / "test.mp4"
        write_synthetic_mp4(path, frame_count=10, width=16, height=12)
        reader = VideoReader()
        reader.open(path)
        f5 = reader.read_frame(5)
        f2 = reader.read_frame(2)
        f8 = reader.read_frame(8)
        assert f5.shape == (12, 16, 3)
        assert f2.shape == (12, 16, 3)
        assert f8.shape == (12, 16, 3)
        reader.release()


class TestVideoReaderBuffer:
    def test_get_buffered_frame_not_in_buffer(self):
        reader = VideoReader()
        with pytest.raises(KeyError, match="not in the ring buffer"):
            reader.get_buffered_frame(0)

    def test_store_in_buffer_evicts_old(self):
        reader = VideoReader(buffer_size=3)
        frame = np.zeros((10, 10, 3), dtype=np.uint8)
        reader._store_in_buffer(0, frame)
        reader._store_in_buffer(1, frame.copy())
        reader._store_in_buffer(2, frame.copy())
        reader._store_in_buffer(3, frame.copy())
        assert 0 not in reader._buffer  # evicted
        assert 3 in reader._buffer

    def test_store_in_buffer_duplicate_noop(self):
        reader = VideoReader()
        frame = np.zeros((10, 10, 3), dtype=np.uint8)
        reader._store_in_buffer(0, frame)
        reader._store_in_buffer(0, frame)  # duplicate
        assert 0 in reader._buffer


class TestVideoReaderRelease:
    def test_release_resets_state(self, tmp_path):
        path = tmp_path / "test.mp4"
        write_synthetic_mp4(path, frame_count=3, width=16, height=12)
        reader = VideoReader()
        reader.open(path)
        assert reader._capture is not None
        reader.release()
        assert reader._capture is None
        assert reader._frame_count == 0
        assert reader._fps == 0.0
        assert reader._last_read_index is None
        assert reader._keyframe_index is None
        assert len(reader._buffer) == 0


class TestVideoReaderContextManager:
    def test_context_manager(self, tmp_path):
        path = tmp_path / "test.mp4"
        write_synthetic_mp4(path, frame_count=3, width=16, height=12)
        with VideoReader() as reader:
            reader.open(path)
            frame = reader.read_frame(0)
            assert frame.shape == (12, 16, 3)
        assert reader._capture is None


class TestVideoReaderKeyframeIndex:
    def test_keyframe_index_populated(self, tmp_path):
        path = tmp_path / "test.mp4"
        write_synthetic_mp4(path, frame_count=5, width=16, height=12)
        reader = VideoReader()
        reader.open(path)
        kf = reader.keyframe_index
        assert isinstance(kf, list)
        assert len(kf) >= 1
        assert kf[0] == 0
        reader.release()

    def test_keyframe_index_no_capture(self):
        reader = VideoReader()
        kf = reader.keyframe_index
        assert kf == [0]


class TestNearestKeyframe:
    def test_nearest_keyframe_at_exact(self, tmp_path):
        path = tmp_path / "test.mp4"
        write_synthetic_mp4(path, frame_count=5, width=16, height=12)
        reader = VideoReader()
        reader.open(path)
        reader._keyframe_index = [0, 2, 4]
        assert reader._nearest_keyframe(0) == 0
        assert reader._nearest_keyframe(2) == 2
        assert reader._nearest_keyframe(4) == 4
        reader.release()

    def test_nearest_keyframe_between(self, tmp_path):
        path = tmp_path / "test.mp4"
        write_synthetic_mp4(path, frame_count=5, width=16, height=12)
        reader = VideoReader()
        reader.open(path)
        reader._keyframe_index = [0, 2, 4]
        assert reader._nearest_keyframe(3) == 2
        assert reader._nearest_keyframe(1) == 0
        reader.release()


class TestThreadVideoReader:
    def test_same_thread_returns_same_instance(self):
        r1 = get_thread_video_reader()
        r2 = get_thread_video_reader()
        assert r1 is r2
