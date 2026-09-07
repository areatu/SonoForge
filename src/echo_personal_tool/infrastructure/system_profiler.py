"""Runtime detection for playback tuning on low-end vs high-end systems."""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass

import psutil

_LOG = logging.getLogger(__name__)

_LOW_END_CORES = 2
_LOW_END_RAM_GIB = 8.0
# Below this much *free* memory the economical profile is used no matter how big the
# machine is: a 32 GB box with 1.5 GB left behaves like a weak one for the next minutes.
_LOW_END_AVAILABLE_GIB = 2.0


@dataclass(frozen=True)
class PlaybackConfig:
    """Adaptive playback tuning detected at startup."""

    prefetch_radius: int  # floor for decoded frames ahead of playhead; stop prefetch when reached
    min_buffer: int  # minimum ahead before playback is considered healthy (lag-skip threshold input)
    batch_size: int  # max frames per prefetch worker run (capped by prefetch_radius - ahead)
    max_lag_frames: int  # skip forward when loaded ahead exceeds this but next frame missing
    evict_window: int  # FrameCache LRU half-width around current index
    scroll_debounce_ms: int  # wheel coalesce window
    scroll_batch_size: int  # neighbor prefetch after scroll target frame
    # Buffer depth in seconds of playback ahead of the playhead. A radius counted in frames
    # (5/10) is only 0.08-0.33 s at 30-60 fps and does not survive one slow decode batch;
    # the controller converts this to frames and caps it by what the frame cache can hold.
    # Defaulted so existing PlaybackConfig(...) constructions keep working.
    prefetch_seconds: float = 1.0


_LOW_END = PlaybackConfig(
    prefetch_radius=5,
    min_buffer=3,
    batch_size=5,
    max_lag_frames=2,
    evict_window=12,
    scroll_debounce_ms=80,
    scroll_batch_size=3,
    prefetch_seconds=1.0,
)

_HIGH_END = PlaybackConfig(
    prefetch_radius=10,
    min_buffer=5,
    batch_size=8,
    max_lag_frames=4,
    evict_window=20,
    scroll_debounce_ms=50,
    scroll_batch_size=8,
)


def detect_playback_config() -> PlaybackConfig:
    cores = os.cpu_count() or 2
    ram_gb = psutil.virtual_memory().total / 1e9
    is_low_end = cores <= _LOW_END_CORES or ram_gb <= _LOW_END_RAM_GB
    return _LOW_END if is_low_end else _HIGH_END
