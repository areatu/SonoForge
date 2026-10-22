"""Micro-costs on the main thread at 720p: leading-static scan, M-mode cached-frames stack."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_REPO_SRC = str(Path(__file__).resolve().parents[2] / "src")
if _REPO_SRC not in sys.path:
    sys.path.insert(0, _REPO_SRC)

import numpy as np  # noqa: E402
import psutil  # noqa: E402

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

from echo_personal_tool.application.app_controller import AppController  # noqa: E402
from echo_personal_tool.application.frame_cache import FrameCache  # noqa: E402

H, W = 720, 1280
n = 16
rng = np.random.default_rng(1)
frames = rng.integers(0, 255, (n, H, W, 3), dtype=np.uint8)

c = AppController()
c._frame_cache = FrameCache(evict_window=20, max_cache_bytes=512 * 1024 * 1024)

c._frame_cache.set_total_frames(Path("/tmp/x.dcm"), n)
for i in range(n):
    c._frame_cache.put(i, frames[i])

rss0 = psutil.Process().memory_info().rss / 1e6
t0 = time.perf_counter()
leading = c._detect_leading_static_from_cache(Path("/tmp/x.dcm"), n)
dt = (time.perf_counter() - t0) * 1000
print(f"_detect_leading_static_from_cache over {n} frames @720p RGB: {dt:.1f} ms (leading={leading})")

t0 = time.perf_counter()
arr = c._frame_cache.frames
dt2 = (time.perf_counter() - t0) * 1000
rss1 = psutil.Process().memory_info().rss / 1e6
print(f"FrameCache.frames (np.stack of {n} cached 720p frames): {dt2:.1f} ms, RSS +{rss1-rss0:.0f} MB -> {arr.nbytes/1e6:.0f} MB duplicate")

t0 = time.perf_counter()
lst = c.get_cached_frames()
print(f"get_cached_frames(): {(time.perf_counter()-t0)*1000:.1f} ms, {len(lst)} frames")

# percentiles / W-L first-frame cost at 720p
from echo_personal_tool.infrastructure.pixel_utils import compute_display_levels  # noqa: E402

g16 = rng.integers(0, 4095, (H, W), dtype=np.uint16)
t0 = time.perf_counter()
compute_display_levels(g16, dr_low_pct=5.0, dr_high_pct=100.0, window_scale=1.0, level_offset=0.0)
print(f"compute_display_levels uint16 720p (first frame after file switch): {(time.perf_counter()-t0)*1000:.1f} ms")

g8 = rng.integers(0, 255, (H, W), dtype=np.uint8)
t0 = time.perf_counter()
compute_display_levels(g8, dr_low_pct=5.0, dr_high_pct=100.0, window_scale=1.0, level_offset=0.0)
print(f"compute_display_levels uint8  720p: {(time.perf_counter()-t0)*1000:.1f} ms")
