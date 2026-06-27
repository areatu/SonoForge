"""Tests for P2: lazy frame loading with LRU eviction in FrameCache.

FrameCache now stores frames in a sparse dict and evicts frames
beyond a configurable window from the current playback position.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from echo_personal_tool.application.frame_cache import FrameCache
from echo_personal_tool.domain.exceptions import IncompleteCineError


def test_frame_cache_load_get_clear(tmp_path: Path) -> None:
    path = tmp_path / "clip.dcm"
    frames = np.arange(30, dtype=np.uint8).reshape(3, 2, 5)
    cache = FrameCache()

    assert not cache.is_ready(path)
    cache.load(path, frames)
    assert cache.is_ready(path)
    assert cache.frame_count() == 3
    assert np.array_equal(cache.get(1), frames[1])
    assert cache.memory_bytes() == frames.nbytes

    cache.clear()
    assert not cache.is_ready(path)
    with pytest.raises(RuntimeError):
        cache.get(0)


def test_frame_cache_color_stack(tmp_path: Path) -> None:
    path = tmp_path / "color_clip.dcm"
    frames = np.zeros((2, 3, 4, 3), dtype=np.uint8)
    frames[0, 0, 0] = np.array([255, 0, 0], dtype=np.uint8)
    frames[1, 1, 1] = np.array([0, 255, 0], dtype=np.uint8)
    cache = FrameCache()

    cache.load(path, frames)
    assert cache.is_ready(path)
    assert cache.frame_count() == 2

    frame0 = cache.get(0)
    frame1 = cache.get(1)
    assert frame0.shape == (3, 4, 3)
    assert frame1.shape == (3, 4, 3)
    assert np.array_equal(frame0[0, 0], np.array([255, 0, 0], dtype=np.uint8))
    assert np.array_equal(frame1[1, 1], np.array([0, 255, 0], dtype=np.uint8))
    assert cache.memory_bytes() == frames.nbytes


def test_frame_cache_is_ready_requires_same_path(tmp_path: Path) -> None:
    path_a = tmp_path / "a.dcm"
    path_b = tmp_path / "b.dcm"
    frames = np.zeros((2, 4, 4), dtype=np.uint8)
    cache = FrameCache()
    cache.load(path_a, frames)
    assert cache.is_ready(path_a)
    assert not cache.is_ready(path_b)


def test_frame_cache_get_index_error(tmp_path: Path) -> None:
    path = tmp_path / "clip.dcm"
    cache = FrameCache()
    cache.load(path, np.zeros((2, 4, 4), dtype=np.uint8))
    with pytest.raises(IndexError):
        cache.get(5)


def test_frame_cache_random_access_is_fast(tmp_path: Path) -> None:
    import time

    path = tmp_path / "clip.dcm"
    frames = np.zeros((50, 64, 64), dtype=np.uint8)
    cache = FrameCache()
    cache.load(path, frames)

    start = time.perf_counter()
    for _ in range(100):
        cache.get(int(np.random.randint(0, 50)))
    elapsed = time.perf_counter() - start
    assert elapsed < 0.1


def test_frame_cache_evicts_distant_frames(tmp_path: Path) -> None:
    """set_current() evicts frames beyond the keep window."""
    path = tmp_path / "clip.dcm"
    n = 60
    frames = np.arange(n * 4 * 4, dtype=np.uint16).reshape(n, 4, 4)
    cache = FrameCache(evict_window=20)
    cache.load(path, frames)
    assert cache.frame_count() == n

    cache.set_current(30)

    # Frames within window [30-20, 30+20] = [10, 50] → all kept
    assert cache.is_loaded(30)
    assert cache.is_loaded(10)
    assert cache.is_loaded(50)

    # Frames outside window evicted
    assert not cache.is_loaded(0)
    assert not cache.is_loaded(55)

    # Remaining frames within window after first eviction
    remaining = [i for i in range(n) if cache.is_loaded(i)]
    assert all(10 <= i <= 50 for i in remaining)


def test_frame_cache_eviction_reduces_memory(tmp_path: Path) -> None:
    path = tmp_path / "clip.dcm"
    n = 100
    frames = np.ones((n, 64, 64), dtype=np.uint8)
    cache = FrameCache(evict_window=20)
    cache.load(path, frames)

    full_mem = cache.memory_bytes()
    assert full_mem > 0

    cache.set_current(80)
    evicted_mem = cache.memory_bytes()
    assert evicted_mem < full_mem


def test_frame_cache_frames_property_reconstructs_array(tmp_path: Path) -> None:
    """Backward compat: .frames returns reconstructed array from loaded frames."""
    path = tmp_path / "clip.dcm"
    n = 60
    frames = np.arange(n * 3 * 3, dtype=np.uint16).reshape(n, 3, 3)
    cache = FrameCache(evict_window=20)
    cache.load(path, frames)

    cache.set_current(30)
    # Frames within window [10, 50] are loaded
    full = cache.frames
    assert full is not None
    assert full.shape[1:] == (3, 3)
    # Verify frame values match original
    assert np.array_equal(full[0], frames[10])  # first loaded frame
    assert np.array_equal(full[-1], frames[50])  # last loaded frame


def test_frame_cache_prefetch(tmp_path: Path) -> None:
    """prefetch() sets current and evicts distant frames."""
    path = tmp_path / "clip.dcm"
    n = 60
    frames = np.arange(n * 2 * 2, dtype=np.uint16).reshape(n, 2, 2)
    cache = FrameCache(evict_window=20)
    cache.load(path, frames)

    cache.set_current(30)
    cache.prefetch(30, near=5)

    # Frames within window should be loaded
    assert cache.is_loaded(25)
    assert cache.is_loaded(35)
    assert cache.is_loaded(30)


def test_require_full_cine_raises_on_partial():
    cache = FrameCache(evict_window=2)
    frames = np.zeros((10, 32, 32), dtype=np.uint8)
    cache.load(Path("fake.dcm"), frames)
    cache.set_current(5)
    with pytest.raises(IncompleteCineError):
        cache.require_full_cine()


def test_require_full_cine_returns_stack():
    cache = FrameCache()
    frames = np.arange(50, dtype=np.uint8).reshape(5, 2, 5)
    cache.load(Path("fake.dcm"), frames)
    out = cache.require_full_cine()
    assert out.shape == (5, 2, 5)
