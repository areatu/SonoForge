"""Strain computation from speckle tracking results."""

from __future__ import annotations

import numpy as np


def contour_arc_length(points: np.ndarray, pixel_spacing: tuple[float, float]) -> float:
    """Total arc length of a contour in physical units (mm)."""
    avg = np.mean(pixel_spacing)
    diffs = np.diff(points, axis=0)
    return float(np.sum(np.linalg.norm(diffs, axis=1)) * avg)


def compute_longitudinal_strain_gl(
    positions: np.ndarray,
    ed_index: int,
    pixel_spacing: tuple[float, float],
    endo_indices: list[int],
) -> np.ndarray:
    """Green-Lagrange longitudinal strain from smoothed kernel positions.

    E = 0.5 * ((L/L0)^2 - 1) * 100
    """
    n_frames = positions.shape[0]
    strain = np.zeros(n_frames)
    ed_pts = positions[ed_index, endo_indices, :]
    l0 = contour_arc_length(ed_pts, pixel_spacing)
    if l0 < 1e-6:
        return strain
    for t in range(n_frames):
        lt = contour_arc_length(positions[t, endo_indices, :], pixel_spacing)
        ratio = lt / l0
        strain[t] = 0.5 * (ratio**2 - 1.0) * 100.0
    return strain


def apply_drift_compensation(strain: np.ndarray, ed_index: int, end_index: int) -> np.ndarray:
    """Linear detrend so strain[ed_index]=0 and strain[end_index]=0."""
    out = strain.copy()
    if len(out) < 2 or ed_index == end_index:
        return out
    end_idx = int(np.clip(end_index, 0, len(out) - 1))
    drift_slope = (out[end_idx] - out[ed_index]) / max(end_idx - ed_index, 1)
    for t in range(len(out)):
        out[t] -= drift_slope * (t - ed_index)
    out[ed_index] = 0.0
    return out


def compute_radial_strain_gl(
    positions: np.ndarray,
    ed_index: int,
    pixel_spacing: tuple[float, float],
    endo_indices: list[int],
    epi_indices: list[int],
) -> np.ndarray:
    """Green-Lagrange radial strain from mean wall thickness."""
    n_frames = positions.shape[0]
    strain = np.zeros(n_frames)
    avg_spacing = np.mean(pixel_spacing)

    endo_ed = positions[ed_index, endo_indices, :]
    epi_ed = positions[ed_index, epi_indices, :]
    t0 = float(np.mean(np.linalg.norm(epi_ed - endo_ed, axis=1)) * avg_spacing)
    if t0 < 1e-6:
        return strain

    for t in range(n_frames):
        endo_t = positions[t, endo_indices, :]
        epi_t = positions[t, epi_indices, :]
        tt = float(np.mean(np.linalg.norm(epi_t - endo_t, axis=1)) * avg_spacing)
        ratio = tt / t0
        strain[t] = 0.5 * (ratio**2 - 1.0) * 100.0
    return strain


def compute_gls(
    longitudinal_strain: np.ndarray,
    ed_index: int,
    es_index: int,
) -> float:
    """Global Longitudinal Strain: peak negative strain between ED and ES.

    Args:
        longitudinal_strain: strain curve over all frames.
        ed_index: end-diastole frame index.
        es_index: end-systole frame index.

    Returns:
        GLS as negative percentage (e.g., -18.5%).
    """
    if ed_index == es_index:
        return 0.0
    start, end = min(ed_index, es_index), max(ed_index, es_index)
    segment = longitudinal_strain[start : end + 1]
    if len(segment) == 0:
        return 0.0
    return float(np.min(segment))


def compute_weighted_longitudinal_strain_gl(
    positions: np.ndarray,
    ed_index: int,
    pixel_spacing: tuple[float, float],
    endo_indices: list[int],
    ncc_weights: np.ndarray | None = None,
) -> np.ndarray:
    """Quality-weighted Green-Lagrange longitudinal strain.

    Each segment's contribution to arc length is weighted by the average NCC
    of its endpoints. Higher-quality kernels contribute more to the strain curve.

    Args:
        positions: (N_frames, N_kernels, 2) smoothed kernel positions.
        ed_index: end-diastole frame index.
        pixel_spacing: (row, col) mm per pixel.
        endo_indices: indices of endocardial kernels.
        ncc_weights: (N_kernels,) NCC scores per kernel. If None, equal weights.

    Returns:
        (N_frames,) longitudinal strain curve in percent.
    """
    n_frames = positions.shape[0]
    n_endo = len(endo_indices)
    if n_endo < 2:
        return np.zeros(n_frames)

    avg_spacing = np.mean(pixel_spacing)

    if ncc_weights is None:
        ncc_weights = np.ones(len(positions[0]), dtype=np.float64)

    ed_pts = positions[ed_index, endo_indices, :]

    # Compute weighted arc length at ED (L0)
    l0 = 0.0
    for j in range(n_endo - 1):
        i1 = endo_indices[j]
        i2 = endo_indices[j + 1]
        dist = np.linalg.norm(ed_pts[j + 1] - ed_pts[j]) * avg_spacing
        weight = (ncc_weights[i1] + ncc_weights[i2]) / 2.0
        l0 += dist * weight

    if l0 < 1e-6:
        return np.zeros(n_frames)

    strain = np.zeros(n_frames)
    for t in range(n_frames):
        pts_t = positions[t, endo_indices, :]
        lt = 0.0
        for j in range(n_endo - 1):
            i1 = endo_indices[j]
            i2 = endo_indices[j + 1]
            dist = np.linalg.norm(pts_t[j + 1] - pts_t[j]) * avg_spacing
            weight = (ncc_weights[i1] + ncc_weights[i2]) / 2.0
            lt += dist * weight
        ratio = lt / l0
        strain[t] = 0.5 * (ratio**2 - 1.0) * 100.0

    return strain


def compute_weighted_radial_strain_gl(
    positions: np.ndarray,
    ed_index: int,
    pixel_spacing: tuple[float, float],
    endo_indices: list[int],
    epi_indices: list[int],
    ncc_weights: np.ndarray | None = None,
) -> np.ndarray:
    """Quality-weighted Green-Lagrange radial strain.

    Each wall thickness measurement is weighted by the average NCC of its
    endocardial and epicardial kernel pair.

    Args:
        positions: (N_frames, N_kernels, 2) smoothed kernel positions.
        ed_index: end-diastole frame index.
        pixel_spacing: (row, col) mm per pixel.
        endo_indices: indices of endocardial kernels.
        epi_indices: indices of epicardial kernels.
        ncc_weights: (N_kernels,) NCC scores per kernel. If None, equal weights.

    Returns:
        (N_frames,) radial strain curve in percent.
    """
    n_frames = positions.shape[0]
    n_pairs = min(len(endo_indices), len(epi_indices))
    if n_pairs < 1:
        return np.zeros(n_frames)

    avg_spacing = np.mean(pixel_spacing)

    if ncc_weights is None:
        ncc_weights = np.ones(len(positions[0]), dtype=np.float64)

    # Compute weighted wall thickness at ED (t0)
    t0 = 0.0
    for j in range(n_pairs):
        i_endo = endo_indices[j]
        i_epi = epi_indices[j]
        endo_ed = positions[ed_index, i_endo, :]
        epi_ed = positions[ed_index, i_epi, :]
        thickness = np.linalg.norm(epi_ed - endo_ed) * avg_spacing
        weight = (ncc_weights[i_endo] + ncc_weights[i_epi]) / 2.0
        t0 += thickness * weight

    if t0 < 1e-6:
        return np.zeros(n_frames)

    strain = np.zeros(n_frames)
    for t in range(n_frames):
        tt = 0.0
        for j in range(n_pairs):
            i_endo = endo_indices[j]
            i_epi = epi_indices[j]
            endo_t = positions[t, i_endo, :]
            epi_t = positions[t, i_epi, :]
            thickness = np.linalg.norm(epi_t - endo_t) * avg_spacing
            weight = (ncc_weights[i_endo] + ncc_weights[i_epi]) / 2.0
            tt += thickness * weight
        ratio = tt / t0
        strain[t] = 0.5 * (ratio**2 - 1.0) * 100.0

    return strain


def compute_strain_rate(
    strain_curve: np.ndarray,
    frame_times_ms: list[float] | np.ndarray,
) -> np.ndarray:
    """Time derivative of strain curve.

    Args:
        strain_curve: (N,) strain values in percent.
        frame_times_ms: per-frame time intervals in ms.

    Returns:
        (N,) strain rate in %/s.
    """
    n = len(strain_curve)
    rate = np.zeros(n)
    times = np.array(frame_times_ms, dtype=np.float64)
    if len(times) != n:
        times = np.full(n, 33.3)

    for i in range(1, n):
        dt_s = (times[i] - times[i - 1]) / 1000.0
        if dt_s > 1e-6:
            rate[i] = (strain_curve[i] - strain_curve[i - 1]) / dt_s

    return rate
