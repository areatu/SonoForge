"""Runtime detection for playback tuning on low-end vs high-end systems."""

from __future__ import annotations

import os
from dataclasses import dataclass

import psutil

_LOW_END_CORES = 2
_LOW_END_RAM_GB = 8.0


@dataclass(frozen=True)
class PlaybackConfig:
    """Adaptive playback tuning detected at startup."""

    prefetch_radius: int  # target decoded frames ahead of playhead; stop prefetch when reached
    min_buffer: int  # minimum ahead before playback is considered healthy (lag-skip threshold input)
    batch_size: int  # max frames per prefetch worker run (capped by prefetch_radius - ahead)
    max_lag_frames: int  # skip forward when loaded ahead exceeds this but next frame missing
    evict_window: int  # FrameCache LRU half-width around current index
    scroll_debounce_ms: int  # wheel coalesce window
    scroll_batch_size: int  # neighbor prefetch after scroll target frame


_LOW_END = PlaybackConfig(
    prefetch_radius=5,
    min_buffer=3,
    batch_size=5,
    max_lag_frames=2,
    evict_window=30,
    scroll_debounce_ms=80,
    scroll_batch_size=3,
)

_HIGH_END = PlaybackConfig(
    prefetch_radius=10,
    min_buffer=5,
    batch_size=8,
    max_lag_frames=4,
    evict_window=40,
    scroll_debounce_ms=50,
    scroll_batch_size=8,
)


def detect_playback_config() -> PlaybackConfig:
    cores = os.cpu_count() or 2
    ram_gb = psutil.virtual_memory().total / 1e9
    is_low_end = cores <= _LOW_END_CORES or ram_gb <= _LOW_END_RAM_GB
    return _LOW_END if is_low_end else _HIGH_END
