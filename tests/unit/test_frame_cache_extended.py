"""Extended tests for FrameCache (covering load_all_frames, edge cases, _evict)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from echo_personal_tool.application.frame_cache import FrameCache
from echo_personal_tool.domain.exceptions import IncompleteCineError


def test_load_invalid_shape_raises() -> None:
    cache = FrameCache()
    with pytest.raises(ValueError, match="Expected frames shape"):
        cache.load(Path("x.dcm"), np.zeros((3,), dtype=np.uint8))


def test_load_4d_with_channels_accepted() -> None:
    """4D with last dim=3 or 4 is accepted (color frames)."""
    cache = FrameCache()
    arr = np.zeros((2, 4, 4, 4), dtype=np.uint8)
    cache.load(Path("x.dcm"), arr)
    assert cache.frame_count() == 2


def test_get_negative_index_raises() -> None:
    cache = FrameCache()
    cache.load(Path("x.dcm"), np.zeros((3, 4, 4), dtype=np.uint8))
    with pytest.raises(IndexError):
        cache.get(-1)


def test_put_evicts_when_exceeding_double_window() -> None:
    """put() triggers eviction when sorted_keys > evict_window * 2."""
    cache = FrameCache(evict_window=3, max_cache_bytes=1_000_000)
    cache.set_total_frames(Path("x.dcm"), total=50)
    # Manually put more than 6 frames
    for i in range(8):
        cache.put(i, np.zeros((2, 2), dtype=np.uint8))
    # Should have evicted some frames
    assert len([k for k in range(8) if cache.is_loaded(k)]) <= 7


def test_pin_prevents_eviction() -> None:
    cache = FrameCache(evict_window=5, max_cache_bytes=1_000_000)
    cache.set_total_frames(Path("x.dcm"), total=30)
    for i in range(15):
        cache.put(i, np.ones((2, 2), dtype=np.uint8) * i)
    # Pin frame 0 and set current far away
    cache.pin(0)
    cache.set_current(10)
    # Frame 0 should still be loaded because it's pinned
    assert cache.is_loaded(0)


def test_unpin_allows_eviction() -> None:
    cache = FrameCache(evict_window=5, max_cache_bytes=1_000_000)
    cache.set_total_frames(Path("x.dcm"), total=30)
    for i in range(15):
        cache.put(i, np.ones((2, 2), dtype=np.uint8) * i)
    cache.pin(0)
    cache.unpin(0)
    cache.set_current(10)
    assert not cache.is_loaded(0)


def test_load_all_frames_already_cached() -> None:
    """load_all_frames returns cached array when all frames loaded."""
    cache = FrameCache()
    frames = np.arange(12, dtype=np.uint8).reshape(3, 2, 2)
    cache.load(Path("x.dcm"), frames)
    result = cache.load_all_frames()
    np.testing.assert_array_equal(result, frames)


def test_load_all_frames_empty_raises() -> None:
    cache = FrameCache()
    with pytest.raises(IncompleteCineError, match="No frames available"):
        cache.load_all_frames()


def test_load_all_frames_no_source_raises() -> None:
    """When only total_frames is set but no frames loaded and no source."""
    cache = FrameCache()
    cache._total_frames = 5  # set directly without source
    with pytest.raises(IncompleteCineError, match="No source path set"):
        cache.load_all_frames()


def test_load_all_frames_from_video(tmp_path: Path) -> None:
    """load_all_frames reads from video file when path is .mp4."""
    cache = FrameCache()
    total = 3
    cache.set_total_frames(tmp_path / "clip.mp4", total)

    mock_reader = MagicMock()
    mock_reader.read_frame.side_effect = [np.zeros((4, 4), dtype=np.uint8) for _ in range(total)]

    with patch(
        "echo_personal_tool.infrastructure.video_reader.get_thread_video_reader",
        return_value=mock_reader,
    ):
        result = cache.load_all_frames()

    assert result.shape[0] == total
    assert mock_reader.open.called
    assert mock_reader.read_frame.call_count == total


def test_load_all_frames_from_dicom(tmp_path: Path) -> None:
    """load_all_frames reads from DICOM file when path is .dcm."""
    cache = FrameCache()
    total = 2
    cache.set_total_frames(tmp_path / "clip.dcm", total)

    mock_session = MagicMock()
    mock_session.decode_single_frame.side_effect = [np.ones((4, 4), dtype=np.uint8) * i for i in range(total)]

    with patch(
        "echo_personal_tool.infrastructure.dicom_session.get_thread_dicom_session",
        return_value=mock_session,
    ):
        result = cache.load_all_frames()

    assert result.shape[0] == total
    assert mock_session.open.called


def test_require_full_cine_empty_raises() -> None:
    cache = FrameCache()
    with pytest.raises(IncompleteCineError, match="empty"):
        cache.require_full_cine()


def test_frames_property_empty_returns_none() -> None:
    cache = FrameCache()
    assert cache.frames is None


def test_frames_property_partial_load_returns_sorted() -> None:
    """When not all frames loaded, .frames returns only loaded keys in order."""
    cache = FrameCache()
    cache.set_total_frames(Path("x.dcm"), total=5)
    cache.put(1, np.ones((2, 2), dtype=np.uint8))
    cache.put(3, np.ones((2, 2), dtype=np.uint8) * 3)
    result = cache.frames
    assert result is not None
    assert result.shape[0] == 2
    np.testing.assert_array_equal(result[0], np.ones((2, 2), dtype=np.uint8))
    np.testing.assert_array_equal(result[1], np.ones((2, 2), dtype=np.uint8) * 3)


def test_loaded_ahead_empty_cache() -> None:
    cache = FrameCache()
    assert cache.loaded_ahead(0) == 0


def test_loaded_before_empty_cache() -> None:
    cache = FrameCache()
    assert cache.loaded_before(0) == 0


def test_nearest_loaded_before_empty_cache() -> None:
    cache = FrameCache()
    assert cache.nearest_loaded_before(5) is None


def test_nearest_loaded_ahead_empty_cache() -> None:
    cache = FrameCache()
    assert cache.nearest_loaded_ahead(5) is None


def test_is_loaded_empty_cache() -> None:
    cache = FrameCache()
    assert not cache.is_loaded(0)


def test_clear_resets_all_state() -> None:
    cache = FrameCache()
    cache.load(Path("x.dcm"), np.zeros((3, 4, 4), dtype=np.uint8))
    cache.pin(1)
    cache.clear()
    assert cache.frame_count() == 0
    assert cache.source_path is None
    assert cache.frames is None
    assert cache.memory_bytes() == 0
    assert not cache.is_loaded(0)


def test_memory_bytes_after_eviction() -> None:
    cache = FrameCache(evict_window=3, max_cache_bytes=1_000_000)
    cache.set_total_frames(Path("x.dcm"), total=20)
    for i in range(20):
        cache.put(i, np.ones((8, 8), dtype=np.uint8))
    full_mem = cache.memory_bytes()
    cache.set_current(15)
    assert cache.memory_bytes() < full_mem
