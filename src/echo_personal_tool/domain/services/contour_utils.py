"""Contour geometry utilities for deterministic STE."""

from __future__ import annotations

import numpy as np


def resample_contour(points: np.ndarray, n_points: int = 128) -> np.ndarray:
    """Uniform arc-length resampling of a closed/open polyline."""
    pts = np.asarray(points, dtype=np.float64)
    if pts.shape[0] < 2:
        raise ValueError("Contour needs at least 2 points")
    if pts.shape[0] == n_points:
        return pts.copy()
    diffs = np.diff(pts, axis=0)
    seg_lens = np.linalg.norm(diffs, axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg_lens)])
    total = cum[-1]
    if total < 1e-9:
        return np.tile(pts[0], (n_points, 1))
    targets = np.linspace(0.0, total, n_points, endpoint=False)
    out = np.zeros((n_points, 2), dtype=np.float64)
    for i, t in enumerate(targets):
        idx = int(np.searchsorted(cum, t, side="right") - 1)
        idx = min(max(idx, 0), len(seg_lens) - 1)
        seg_start = cum[idx]
        seg_len = seg_lens[idx] if seg_lens[idx] > 1e-9 else 1.0
        alpha = (t - seg_start) / seg_len
        out[i] = pts[idx] + alpha * (pts[idx + 1] - pts[idx])
    return out
