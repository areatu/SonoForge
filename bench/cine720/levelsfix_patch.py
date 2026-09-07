"""Prototype fix: restore the display-levels cache for grayscale W/L frames.

Two independent defects make `_update_levels()` recompute `compute_display_levels()`
(a full-frame float64 percentile pass, 12.7-19.7 ms at 1280x720) on **every** frame:

1. Key order mismatch.
   `ViewerWidget.show_frame_fast()` writes `_cached_levels_key = (dr, window, level)`
   (viewer_widget.py:1800-1805) while `_update_levels()` compares it against
   `sliders_key = (window, level, dr)` (viewer_widget.py:7424-7428). With the default
   sliders (50, 100, 50) the tuples never compare equal, so the cache never hits.

2. Outlier heuristic assumes an 8-bit scale.
   `_is_levels_outlier()` (viewer_widget.py:7515) tests `mean < 5 or mean > 250` and
   `std < 3` against raw pixel values. For MONOCHROME2 uint16 frames (mean ~15000) it
   always answers "outlier", so `low/high` are never stored and the W/L window is
   recomputed per frame -> visible brightness flicker during playback as well.

This prototype patches both, so the levels are computed once per slider change and the
per-frame cost drops to `np.take(lut, src, out=dst)` (~1 ms at 720p).
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_SRC = str(Path(__file__).resolve().parents[2] / "src")
if _REPO_SRC not in sys.path:
    sys.path.insert(0, _REPO_SRC)

import numpy as np  # noqa: E402


class _PermKey(tuple):
    """Tuple that compares equal to any permutation of itself (prototype only).

    Lets the two different writer orders match the reader's order without touching
    production code. A permutation-insensitive key could in principle alias two
    different slider settings with the same value multiset; the real fix is to use one
    canonical order in both places.
    """

    def __eq__(self, other):
        return isinstance(other, tuple) and len(other) == 3 and sorted(self) == sorted(other)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(tuple(sorted(self)))


def apply(*, verbose: bool = False) -> None:
    from echo_personal_tool.presentation import viewer_widget as vw

    # --- fix 1: make the cached key order-insensitive ---
    def _get(self):
        return self.__dict__.get("_cached_levels_key")

    def _set(self, value):
        self.__dict__["_cached_levels_key"] = _PermKey(value) if isinstance(value, tuple) else value

    vw.ViewerWidget._cached_levels_key = property(_get, _set)

    # --- fix 2: dtype-aware outlier thresholds + float32 stats ---
    def _is_levels_outlier(self, low: float, high: float, frame) -> bool:
        arr = np.asarray(frame)
        full = 65535.0 if arr.dtype == np.uint16 else 255.0
        if (high - low) < 10.0 * full / 255.0:
            return True
        flat = arr.astype(np.float32).ravel()
        mean = float(flat.mean()) * 255.0 / full
        std = float(flat.std()) * 255.0 / full
        return mean < 5.0 or mean > 250.0 or std < 3.0

    vw.ViewerWidget._is_levels_outlier = _is_levels_outlier

    if verbose:
        print("[patch] display-levels cache restored (key order + dtype-aware outlier)")
