"""Tests for adaptive max_cache_bytes in FrameCache.

Verifies that FrameCache respects a per-instance max_cache_bytes cap and
evicts via _evict_to_memory_limit when exceeded, plus the minimum-size floor.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pytest

from echo_personal_tool.application.frame_cache import (
    _MIN_FRAME_SIZE_BYTES,
    FrameCache,
)


def test_frame_cache_respects_custom_max_bytes() -> None:
    cache = FrameCache(max_cache_bytes=2_000_000)
    assert cache._max_cache_bytes == 2_000_000


def test_frame_cache_default_max_bytes() -> None:
    cache = FrameCache()
    assert cache._max_cache_bytes == 2 * 1024 * 1024 * 1024


def test_evict_to_memory_limit_triggers_on_exceed() -> None:
    frame = np.zeros((500, 500), dtype=np.uint8)  # 250_000 bytes
    cache = FrameCache(max_cache_bytes=1_000_000, evict_window=100)

    for i in range(10):
        cache.put(i, frame)

    # 10 frames × 250_000 = 2_500_000 > 1_000_000 cap → eviction triggered
    assert cache._memory_bytes < 2_500_000


def test_low_memory_cache_evicts_aggressively() -> None:
    frame = np.zeros((500, 500), dtype=np.uint8)  # 250_000 bytes
    small_cache = FrameCache(max_cache_bytes=1_000_000, evict_window=2)

    for i in range(10):
        small_cache.put(i, frame)

    assert small_cache.memory_bytes() <= 1_000_000


def test_max_cache_bytes_above_minimum_floor() -> None:
    """Values below _MIN_FRAME_SIZE_BYTES are raised to the floor."""
    too_small = FrameCache(max_cache_bytes=1000)
    assert too_small._max_cache_bytes == _MIN_FRAME_SIZE_BYTES


def test_max_cache_bytes_above_floor_not_bumped() -> None:
    above = _MIN_FRAME_SIZE_BYTES + 1000
    cache = FrameCache(max_cache_bytes=above)
    assert cache._max_cache_bytes == above


def test_min_floor_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="echo_personal_tool.application.frame_cache"):
        FrameCache(max_cache_bytes=1000)
    assert any("below minimum" in r.message for r in caplog.records)


def test_max_cache_bytes_instance_isolation() -> None:
    """Two caches with different budgets do not interfere."""
    cache_a = FrameCache(max_cache_bytes=2_000_000)
    cache_b = FrameCache(max_cache_bytes=10_000_000)

    assert cache_a._max_cache_bytes != cache_b._max_cache_bytes
    assert cache_a._max_cache_bytes == 2_000_000
    assert cache_b._max_cache_bytes == 10_000_000


def test_frame_cache_memory_bytes_reflects_actual_usage() -> None:
    frame_1mb = np.zeros((512, 512), dtype=np.uint8)
    cache = FrameCache(max_cache_bytes=5_000_000)

    cache.put(0, frame_1mb)
    assert cache.memory_bytes() == frame_1mb.nbytes

    cache.put(1, frame_1mb)
    assert cache.memory_bytes() == frame_1mb.nbytes * 2
