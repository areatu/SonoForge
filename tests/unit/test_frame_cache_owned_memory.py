"""Owned-buffer accounting for FrameCache (#545).

The audit found that evicting views of one full cine reduced the sum of
``frame.nbytes`` while the backing allocation stayed resident.  These tests
assert the accounting that replaces it: one owner per allocation, logical
bytes separately, and a real full->sparse transition that copies only the
survivors and releases the parent buffer.
"""

from __future__ import annotations

import gc
import weakref
from pathlib import Path

import numpy as np
import pytest

from echo_personal_tool.application.frame_cache import FrameCache


def _cine(frames: int = 24, side: int = 512) -> np.ndarray:
    return np.arange(frames * side * side, dtype=np.uint16).reshape(frames, side, side)


def test_views_into_one_cine_are_counted_once(tmp_path: Path) -> None:
    frames = _cine()
    cache = FrameCache(max_cache_bytes=frames.nbytes * 2)
    cache.load(tmp_path / "cine.dcm", frames)

    stats = cache.memory_stats()
    assert stats.mode == "full"
    assert stats.frame_count == frames.shape[0]
    assert stats.logical_bytes == frames.nbytes
    # One allocation, not len(store) copies of frame.nbytes.
    assert stats.owned_bytes == frames.nbytes
    assert cache.memory_bytes() == frames.nbytes


def test_evicting_most_views_releases_the_parent_and_switches_to_sparse(tmp_path: Path) -> None:
    frames = _cine(frames=30)
    # A budget that can hold only a small neighbourhood, so set_current()
    # really evicts most of the loaded full cine.
    cache = FrameCache(evict_window=4, max_cache_bytes=1_500_000)
    cache.load(tmp_path / "cine.dcm", frames)
    parent = weakref.ref(frames)

    cache.set_current(15)
    del frames
    gc.collect()

    stats = cache.memory_stats()
    assert stats.mode == "sparse"
    assert stats.frame_count < 30
    # Survivors are independent frames: no shared parent remains.
    assert stats.owned_bytes == stats.logical_bytes
    assert stats.owned_bytes < 30 * 512 * 512 * 2
    assert parent() is None


def test_peak_tracks_the_temporary_stack_not_only_final_bytes(tmp_path: Path) -> None:
    frames = _cine(frames=12, side=128)
    cache = FrameCache(max_cache_bytes=frames.nbytes * 4)
    cache.load(tmp_path / "cine.dcm", frames)
    for index in range(frames.shape[0]):
        cache.put(index, frames[index].copy())

    # `require_full_cine` stacks the sparse frames; the temporary double
    # residency is a peak the final byte count can no longer show.
    cache.require_full_cine()
    assert cache.peak_memory_bytes() >= 2 * frames.nbytes
    assert cache.memory_bytes() == frames.nbytes


def test_clear_resets_owned_and_peak_counters(tmp_path: Path) -> None:
    frames = _cine(frames=8, side=64)
    cache = FrameCache(max_cache_bytes=frames.nbytes * 2)
    cache.load(tmp_path / "cine.dcm", frames)
    assert cache.memory_bytes() > 0

    cache.clear()
    stats = cache.memory_stats()
    assert stats.owned_bytes == 0
    assert stats.logical_bytes == 0
    assert stats.pinned_bytes == 0
    assert stats.peak_bytes == 0
    assert stats.frame_count == 0


def test_putting_the_same_object_twice_counts_one_allocation() -> None:
    cache = FrameCache(max_cache_bytes=10_000_000)
    frame = np.zeros((64, 64), dtype=np.uint8)
    cache.put(0, frame)
    cache.put(1, frame)
    assert cache.memory_bytes() == frame.nbytes
    assert cache.logical_bytes() == 2 * frame.nbytes


def test_load_sparse_keeps_only_selected_independent_frames(tmp_path: Path) -> None:
    frames = _cine(frames=20, side=64)
    cache = FrameCache(max_cache_bytes=1_000_000, evict_window=4)
    cache.load_sparse(tmp_path / "cine.dcm", frames, indices=[3, 11, 11, 99, -1])

    stats = cache.memory_stats()
    assert stats.mode == "sparse"
    assert sorted(cache._frame_store) == [3, 11]
    assert stats.owned_bytes == stats.logical_bytes == 2 * 64 * 64 * 2
    assert cache._total_frames == 20


def test_full_cine_reservation_is_separate_and_enforced(tmp_path: Path) -> None:
    frames = _cine(frames=4, side=32)
    cache = FrameCache(max_cache_bytes=1_000_000, max_full_cine_bytes=frames.nbytes - 1)
    with pytest.raises(ValueError, match="full-cine reservation"):
        cache.load(tmp_path / "cine.dcm", frames)

    # The sparse path can still work with the same small reservation because
    # it copies only selected frames and never retains the full parent.
    cache.load_sparse(tmp_path / "cine.dcm", frames, indices=[0])
    assert cache.memory_stats().owned_bytes == frames[0].nbytes


def test_twenty_tab_switches_release_previous_cine_buffers(tmp_path: Path) -> None:
    """20 tab switches must not leave the previous cines resident.

    Each "tab" loads a full cine (views into its own parent), moves the
    playhead, then clears the cache.  The weak references prove the parent
    buffer is collectible after each switch, so the steady state is a plateau
    rather than a streak of one lost cine per tab.
    """
    parents: list[weakref.ReferenceType[np.ndarray]] = []
    peaks: list[int] = []
    for tab in range(20):
        frames = _cine(frames=10, side=256)
        parents.append(weakref.ref(frames))
        cache = FrameCache(evict_window=3, max_cache_bytes=1_000_000)
        cache.load(tmp_path / f"tab-{tab}.dcm", frames)
        cache.set_current(tab % 10)
        peaks.append(cache.peak_memory_bytes())
        cache.clear()
        del cache, frames
        gc.collect()

    assert all(ref() is None for ref in parents)
    # A per-tab peak stays bounded by one cine, not by the accumulated tabs.
    assert max(peaks) < 2 * 10 * 256 * 256 * 2
