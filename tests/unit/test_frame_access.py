"""Characterization of the read-only frame seam (issue #552, slice 1).

The UI owns no decoder or cache state: it asks ``FrameAccess`` for readiness,
one resident frame, or a complete cine.  These tests pin the lifecycle the
facade must preserve when the user switches clips or closes a tab.
"""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.application.frame_access import FrameAccess
from echo_personal_tool.application.frame_cache import FrameCache


def _frames(count: int) -> np.ndarray:
    return np.arange(count * 4, dtype=np.uint8).reshape(count, 2, 2)


@pytest.fixture()
def access() -> FrameAccess:
    return FrameAccess(FrameCache(max_cache_bytes=4 * 1024 * 1024))


def test_status_starts_not_ready(access: FrameAccess) -> None:
    status = access.status()
    assert status.ready is False
    assert status.frame_count == 0
    assert status.loaded_count == 0
    assert status.source_path is None


def test_status_ready_after_source_and_frames(access: FrameAccess, tmp_path) -> None:
    path = tmp_path / "clip.dcm"
    access._cache.set_total_frames(path, 3)
    partial = access.status()
    assert partial.ready is True
    assert partial.frame_count == 3
    assert partial.loaded_count == 0

    frames = _frames(3)
    for index in range(3):
        access._cache.put(index, frames[index])

    full = access.status()
    assert full.ready is True
    assert full.frame_count == 3
    assert full.loaded_count == 3
    assert full.source_path == path.resolve()


def test_frame_returns_only_resident_pixels_for_the_current_source(access: FrameAccess, tmp_path) -> None:
    path = tmp_path / "clip.dcm"
    frames = _frames(2)
    access._cache.set_total_frames(path, 2)
    access._cache.put(1, frames[1])

    assert access.frame(path, 1) is not None
    assert np.array_equal(access.frame(path, 1), frames[1])
    # Not resident, another clip and out-of-range all degrade to a loader miss.
    assert access.frame(path, 0) is None
    assert access.frame(tmp_path / "other.dcm", 1) is None
    assert access.frame(path, 99) is None
    assert access.frame(None, 1) is None


def test_full_cine_requires_every_frame(access: FrameAccess, tmp_path) -> None:
    path = tmp_path / "clip.dcm"
    frames = _frames(3)
    access._cache.set_total_frames(path, 3)
    access._cache.put(0, frames[0])

    assert access.full_cine() is None

    for index in range(1, 3):
        access._cache.put(index, frames[index])

    stacked = access.full_cine()
    assert stacked is not None
    assert np.array_equal(stacked, frames)


def test_switching_clip_drops_the_previous_generation(access: FrameAccess, tmp_path) -> None:
    first = tmp_path / "first.dcm"
    second = tmp_path / "second.dcm"
    frames = _frames(2)
    access._cache.set_total_frames(first, 2)
    for index in range(2):
        access._cache.put(index, frames[index])
    assert access.frame(first, 0) is not None

    access._cache.set_total_frames(second, 5)

    assert access.frame(first, 0) is None
    assert access.full_cine() is None
    status = access.status()
    assert status.source_path == second.resolve()
    assert status.frame_count == 5
    assert status.loaded_count == 0


def test_closing_the_tab_clears_the_facade(access: FrameAccess, tmp_path) -> None:
    path = tmp_path / "clip.dcm"
    frames = _frames(2)
    access._cache.set_total_frames(path, 2)
    for index in range(2):
        access._cache.put(index, frames[index])
    assert access.frames()

    access._cache.clear()

    assert access.frames() == []
    assert access.full_cine() is None
    assert access.frame(path, 0) is None
    status = access.status()
    assert status.ready is False
    assert status.frame_count == 0
    assert status.loaded_count == 0
    assert status.source_path is None
