"""Sparse projections must never masquerade as a full cine (#544)."""

from pathlib import Path

import numpy as np
import pytest

from echo_personal_tool.application.frame_cache import FrameCache
from echo_personal_tool.domain.exceptions import IncompleteCineError


def _frame(index):
    return np.full((4, 4), index, dtype=np.uint8)


@pytest.mark.parametrize("indices", [(0, 4), (1, 2, 3, 4), (0, 1, 2, 3), (0, 1, 3, 4)])
def test_reading_partial_projection_does_not_satisfy_full_cine(indices):
    cache = FrameCache()
    cache.set_total_frames(Path("cine.dcm"), 5)
    for index in reversed(indices):
        cache.put(index, _frame(index))
    projection = cache.sparse_projection
    assert projection is not None
    assert projection.frame_indices == tuple(sorted(indices))
    assert cache.frames.shape[0] == len(indices)
    for offset, index in enumerate(projection.frame_indices):
        np.testing.assert_array_equal(projection.frames[offset], _frame(index))
    with pytest.raises(IncompleteCineError):
        cache.require_full_cine()


def test_filling_holes_promotes_only_complete_ordered_cine():
    cache = FrameCache()
    cache.set_total_frames(Path("cine.dcm"), 5)
    cache.put(0, _frame(0))
    cache.put(4, _frame(4))
    partial = cache.frames
    for index in (3, 1, 2):
        cache.put(index, _frame(index))
    full = cache.require_full_cine()
    np.testing.assert_array_equal(full, np.stack([_frame(i) for i in range(5)]))
    assert cache.frames is full
    assert cache.load_all_frames() is full
    assert partial.shape[0] == 2


def test_eviction_invalidates_full_cine_even_after_projection_read():
    cache = FrameCache(max_cache_bytes=1_000_000, evict_window=1)
    cache.load(Path("cine.dcm"), np.zeros((8, 512, 512), dtype=np.uint8))
    assert cache.require_full_cine().shape[0] == 8
    cache.set_current(4)
    projection = cache.sparse_projection
    assert projection is not None
    assert len(projection.frame_indices) < 8
    assert cache.frames.shape[0] < 8
    with pytest.raises(IncompleteCineError):
        cache.require_full_cine()


@pytest.mark.parametrize("path,total", [("other.dcm", 3), ("cine.dcm", 4), ("cine.dcm", 2)])
def test_source_or_count_change_drops_previous_full_stack(path, total):
    cache = FrameCache()
    cache.load(Path("cine.dcm"), np.stack([_frame(i) for i in range(3)]))
    cache.require_full_cine()
    cache.set_total_frames(Path(path), total)
    assert cache.frames is None
    with pytest.raises(IncompleteCineError):
        cache.require_full_cine()


def test_same_source_and_count_preserve_full_stack():
    cache = FrameCache()
    cache.load(Path("cine.dcm"), np.stack([_frame(i) for i in range(3)]))
    full = cache.require_full_cine()
    cache.set_total_frames(Path("cine.dcm"), 3)
    assert cache.require_full_cine() is full
    cache.clear()
    assert cache.sparse_projection is None
    with pytest.raises(IncompleteCineError):
        cache.require_full_cine()


def test_equal_count_with_invalid_source_indices_is_not_complete():
    cache = FrameCache()
    cache.set_total_frames(Path("cine.dcm"), 3)
    for index in (0, 2, 4):
        cache.put(index, _frame(index))
    assert cache.frames.shape[0] == 3
    with pytest.raises(IncompleteCineError):
        cache.require_full_cine()


def test_load_all_frames_after_partial_projection_decodes_full_source(tmp_path, monkeypatch):
    from echo_personal_tool.infrastructure import dicom_session

    class Source:
        def open(self, path):
            assert path == tmp_path / "cine.dcm"

        def decode_single_frame(self, index):
            return _frame(index)

    monkeypatch.setattr(dicom_session, "get_thread_dicom_session", lambda path: Source())
    cache = FrameCache()
    cache.set_total_frames(tmp_path / "cine.dcm", 5)
    cache.put(0, _frame(0))
    cache.put(4, _frame(4))
    assert cache.frames.shape[0] == 2
    loaded = cache.load_all_frames()
    np.testing.assert_array_equal(loaded, np.stack([_frame(i) for i in range(5)]))
    assert cache.require_full_cine() is loaded
