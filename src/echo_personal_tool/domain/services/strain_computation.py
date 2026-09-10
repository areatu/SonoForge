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


def assess_strain_plausibility(
    longitudinal: np.ndarray,
    radial: np.ndarray | None,
    ed_index: int,
    es_index: int,
) -> tuple[bool, list[str]]:
    """Physiological plausibility checks for the strain curves.

    Longitudinal strain over the ED..ES systolic window must shorten (negative
    peak), with the peak reached at or near end-systole; radial strain (when
    available) must thicken (positive). The checks separate hard failures from
    soft warnings so callers can report an honest QC score instead of deriving
    "quality" from NCC alone (issue #3: NCC>90% while the deformation curve is
    physiologically impossible).

    Returns ``(plausible, reasons)``. ``plausible`` is False only for hard
    failures; ``reasons`` lists every finding, hard ones first.
    """
    reasons: list[str] = []
    if longitudinal is None or longitudinal.size == 0:
        return False, ["no longitudinal strain curve"]

    start, end = int(min(ed_index, es_index)), int(max(ed_index, es_index))
    window = longitudinal[start : end + 1]
    finite = window[np.isfinite(window)]
    if finite.size == 0:
        return False, ["strain window has no finite values"]

    peak = float(np.min(finite))
    if peak > -1.0:
        # No meaningful systolic shortening (GLS ≈ 0 or positive).
        reasons.append(f"no systolic shortening (peak {peak:.1f}%)")

    # The most negative longitudinal strain should occur at/near ES.
    argmin_global = start + int(np.nanargmin(np.where(np.isnan(window), np.inf, window)))
    mid = start + (end - start) / 2.0
    if argmin_global < mid - (end - start) * 0.15:
        reasons.append("strain peak occurs before mid-systole — check ED/ES or tracking")

    if peak < -45.0:
        reasons.append(f"implausibly large strain ({peak:.1f}%)")

    if radial is not None and radial.size > 0:
        rwin = radial[start : end + 1]
        rfinite = rwin[np.isfinite(rwin)]
        if rfinite.size > 0:
            rpeak = float(np.max(rfinite))
            if rpeak <= 0.0:
                reasons.append("no radial thickening (radial peak <= 0%)")

    hard = [r for r in reasons if r.startswith("no ")]
    plausible = not hard
    return plausible, reasons


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


def peak_in_window(curve: np.ndarray, start: int, end: int) -> float:
    """Most negative (peak systolic) value of a strain curve inside a window.

    The window is defined by its two boundaries, which may be given in either
    order; both are clamped to the curve, so a window that runs past a frame
    boundary is read at the nearest available frame instead of silently turning
    into a normal-looking zero. NaN-safe: frames where the strain is undefined
    (outside the tracked window, lost nodes) never win the peak and never turn
    the result into NaN. Returns 0.0 only when the window holds no finite value
    at all.
    """
    if curve is None or len(curve) == 0:
        return 0.0
    last = len(curve) - 1
    lo = min(max(int(min(start, end)), 0), last)
    hi = min(max(int(max(start, end)), 0), last)
    window = np.asarray(curve[lo : hi + 1], dtype=np.float64)
    finite = window[np.isfinite(window)]
    if finite.size == 0:
        return 0.0
    return float(np.min(finite))


def compute_node_longitudinal_curves(
    positions: np.ndarray,
    ed_index: int,
    pixel_spacing: tuple[float, float],
) -> np.ndarray:
    """Per-node longitudinal strain curves — the single strain definition.

    For every node ``i`` the local strain is the Green–Lagrange strain of the
    sub-arc that runs through the node and its two neighbours
    (``x[i-1] -> x[i] -> x[i+1]``), so a node owns *its own* deformation instead
    of borrowing the strain of a neighbour pair (issue #C3):

        E_i(t) = 0.5 * ((L_i(t) / L_i(ED)) ** 2 - 1) * 100

    The first and last node fall back to the two-point segment (they have no
    neighbour on the other side); this keeps the whole material line covered
    without inventing data. A node whose *own* position is missing yields NaN
    for that node and frame, and a neighbour that is missing only shrinks the
    sub-arc to the tracked side — a lost node never erases the strain of its
    healthy neighbours. The caller can therefore mask exactly the untracked
    nodes instead of smoothing them into a plausible-looking curve.

    Args:
        positions: (n_frames, n_nodes, 2) node positions in arc order.
        ed_index: end-diastole frame index (the strain reference).
        pixel_spacing: (row, col) mm per pixel.

    Returns:
        (n_frames, n_nodes) strain in percent; NaN where undefined.
    """
    pts = np.asarray(positions, dtype=np.float64)
    if pts.ndim != 3 or pts.shape[2] != 2:
        raise ValueError("positions must have shape (n_frames, n_nodes, 2)")
    n_frames, n_nodes, _ = pts.shape
    curves = np.full((n_frames, n_nodes), np.nan, dtype=np.float64)
    if n_nodes < 2 or n_frames == 0:
        return curves

    ed = int(ed_index)
    if not 0 <= ed < n_frames:
        return curves

    index = np.arange(n_nodes)
    left = np.clip(index - 1, 0, n_nodes - 1)
    right = np.clip(index + 1, 0, n_nodes - 1)
    avg_spacing = float(np.mean(pixel_spacing))

    def _subarc_length(frame_index: int) -> np.ndarray:
        a = pts[frame_index, left, :]
        b = pts[frame_index, :, :]
        c = pts[frame_index, right, :]
        finite = np.isfinite(pts[frame_index]).all(axis=1)
        has_left = (left != index) & np.isfinite(a).all(axis=1)
        has_right = (right != index) & np.isfinite(c).all(axis=1)
        d_ab = np.linalg.norm(b - a, axis=1)
        d_bc = np.linalg.norm(c - b, axis=1)
        # A lost node must not erase its healthy neighbours. The sub-arc shrinks
        # to the part that is actually tracked (one-sided segment) instead of
        # propagating NaN along the whole material line.
        full = finite & has_left & has_right
        only_ab = finite & has_left & ~has_right
        only_bc = finite & has_right & ~has_left
        length = np.full(n_nodes, np.nan, dtype=np.float64)
        length[full] = d_ab[full] + d_bc[full]
        length[only_ab] = d_ab[only_ab]
        length[only_bc] = d_bc[only_bc]
        return length * avg_spacing

    l0 = _subarc_length(ed)
    usable = np.isfinite(l0) & (l0 > 1e-6)
    if not np.any(usable):
        return curves

    for t in range(n_frames):
        lt = _subarc_length(t)
        ratio = np.full(n_nodes, np.nan, dtype=np.float64)
        np.divide(lt, l0, out=ratio, where=usable)
        curves[t] = 0.5 * (ratio**2 - 1.0) * 100.0
    return curves


def aggregate_segment_curves(
    node_curves: np.ndarray,
    node_segments: list[int] | np.ndarray,
    node_weights: np.ndarray | None = None,
) -> dict[int, np.ndarray]:
    """Segment curves as the weighted mean of the node curves **in one frame**.

    Averaging per-segment *peaks* taken at different instants is explicitly not
    compatible with the EACVI/ASE definition of global strain, so every segment
    curve is a weighted mean over its nodes at each time step; peaks and
    end-systolic values are read from that curve afterwards.

    Args:
        node_curves: (n_frames, n_nodes) node strain curves in percent.
        node_segments: AHA segment id per node (<= 0 means "unassigned").
        node_weights: optional per-node weights (ED arc length by default).

    Returns:
        ``{segment_id: (n_frames,) curve}``; segments without any finite value
        in a frame get NaN there instead of a fabricated number.
    """
    curves = np.asarray(node_curves, dtype=np.float64)
    if curves.ndim != 2 or curves.shape[1] == 0:
        return {}
    n_frames, n_nodes = curves.shape
    segments = np.asarray(node_segments, dtype=np.int64)
    if segments.shape[0] != n_nodes:
        raise ValueError("node_segments length must match node_curves columns")
    weights = np.ones(n_nodes, dtype=np.float64) if node_weights is None else np.asarray(node_weights, dtype=np.float64)
    weights = np.where(np.isfinite(weights) & (weights > 0), weights, 0.0)

    out: dict[int, np.ndarray] = {}
    for seg_id in sorted({int(s) for s in segments if int(s) > 0}):
        mask = segments == seg_id
        if not np.any(mask):
            continue
        seg_w = weights[mask]
        seg_curves = curves[:, mask]
        w = np.broadcast_to(seg_w, seg_curves.shape)
        finite = np.isfinite(seg_curves)
        w = np.where(finite, w, 0.0)
        wsum = w.sum(axis=1)
        weighted = np.where(finite, np.nan_to_num(seg_curves, nan=0.0) * w, 0.0).sum(axis=1)
        curve = np.full(n_frames, np.nan, dtype=np.float64)
        good = wsum > 1e-9
        curve[good] = weighted[good] / wsum[good]
        out[seg_id] = curve
    return out


def global_curve_from_node_curves(
    node_curves: np.ndarray,
    node_weights: np.ndarray | None = None,
) -> np.ndarray:
    """Whole-line strain curve built from the node curves (definition B).

    Mathematically this is the alternative form of the global strain (mean of
    the values along the line) and must agree with the total-arc-length curve
    (definition A, :func:`compute_longitudinal_strain_gl`) when the nodes are
    equi-spaced — the difference between the two is reported as a
    self-consistency metric instead of being hidden.
    """
    curves = np.asarray(node_curves, dtype=np.float64)
    if curves.ndim != 2 or curves.shape[1] == 0:
        return np.array([], dtype=np.float64)
    n_nodes = curves.shape[1]
    weights = np.ones(n_nodes, dtype=np.float64) if node_weights is None else np.asarray(node_weights, dtype=np.float64)
    weights = np.where(np.isfinite(weights) & (weights > 0), weights, 0.0)
    w = np.broadcast_to(weights, curves.shape)
    finite = np.isfinite(curves)
    w = np.where(finite, w, 0.0)
    wsum = w.sum(axis=1)
    weighted = np.where(finite, np.nan_to_num(curves, nan=0.0) * w, 0.0).sum(axis=1)
    out = np.full(curves.shape[0], np.nan, dtype=np.float64)
    good = wsum > 1e-9
    out[good] = weighted[good] / wsum[good]
    return out
