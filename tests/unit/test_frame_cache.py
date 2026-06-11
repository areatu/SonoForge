"""Unit tests for FrameCache."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from echo_personal_tool.application.frame_cache import FrameCache


def test_frame_cache_load_get_clear(tmp_path: Path) -> None:
    path = tmp_path / "clip.dcm"
    frames = np.arange(30, dtype=np.uint8).reshape(3, 2, 5)
    cache = FrameCache()

    assert not cache.is_ready(path)
    cache.load(path, frames)
    assert cache.is_ready(path)
    assert cache.frame_count() == 3
    assert cache.get(1)[0, 0] == 10
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
