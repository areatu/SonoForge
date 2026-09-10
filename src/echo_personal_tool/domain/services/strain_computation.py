"""Strain computation from speckle tracking results.

Strain definition
-----------------
Every strain value produced here is the clinical **Lagrange strain**

    ε(t) = (L(t) − L0) / L0 · 100 %

i.e. the relative change of length with respect to the end-diastolic length.
This is the definition used by the EACVI/ASE consensus and by the vendor
packages (GE, Philips, TomTec): a myocardium that shortens by 20 % reads
−20 %, which is what the −16 % / −18 % clinical thresholds refer to.

The module previously computed the Green–Lagrange strain
``0.5·((L/L0)² − 1)·100``, which is a different (finite-strain) measure: the
same 20 % shortening read as −18 %, so a truly abnormal −16 % was reported as
−14.7 % — inside the "normal" band. All strain values, curves and metrics now
come from :func:`lagrangian_strain_pct`, so a number can never be produced with
a different definition by accident.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from scipy.signal import savgol_filter


def contour_arc_length(points: np.ndarray, pixel_spacing: tuple[float, float]) -> float:
    """Total arc length of a contour in physical units (mm)."""
    avg = np.mean(pixel_spacing)
    diffs = np.diff(points, axis=0)
    return float(np.sum(np.linalg.norm(diffs, axis=1)) * avg)


def lagrangian_strain_pct(length: float | np.ndarray, reference_length: float | np.ndarray) -> float | np.ndarray:
    """Clinical Lagrange strain in percent: ``(L − L0) / L0 · 100``.

    NaN/zero reference lengths yield NaN instead of an invented zero, so a
    segment that cannot be measured stays missing.
    """
    length_arr = np.asarray(length, dtype=np.float64)
    ref_arr = np.asarray(reference_length, dtype=np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        strain = (length_arr - ref_arr) / ref_arr * 100.0
    if np.ndim(strain) == 0:
        return float(strain) if np.isfinite(strain) else float("nan")
    return strain


def compute_longitudinal_strain_gl(
    positions: np.ndarray,
    ed_index: int,
    pixel_spacing: tuple[float, float],
    endo_indices: list[int],
) -> np.ndarray:
    """Lagrange longitudinal strain (definition A: total arc length).

    ε = (L(t) − L0) / L0 · 100 %, see the module docstring.
    """
    n_frames = positions.shape[0]
    strain = np.zeros(n_frames)
    ed_pts = positions[ed_index, endo_indices, :]
    l0 = contour_arc_length(ed_pts, pixel_spacing)
    if l0 < 1e-6:
        return strain
    for t in range(n_frames):
        lt = contour_arc_length(positions[t, endo_indices, :], pixel_spacing)
        strain[t] = lagrangian_strain_pct(lt, l0)
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
        strain[t] = lagrangian_strain_pct(ratio, 1.0)
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

    Two tiers, because a measurement and a failure must not be confused:

    * **hard** — the curve *stretches* in systole (lengthening or radial
      thinning), the window has no data, or the peak is beyond any physiological
      range. A contraction cannot lengthen its own material line, so this is a
      tracking failure even when the NCC is high.
    * **soft** — there is simply no deformation to measure (peak ≈ 0). That is a
      legitimate finding (akinesia, a technical failure, or a phantom with no
      deformation) and must be *reported*, not silently invalidated: the number
      is honest, the clip is the problem.

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
    stretch = float(np.max(finite))
    if peak > -1.0:
        if stretch > 1.0:
            # The material line *lengthens* during systole: impossible for a
            # contracting wall, so this is a tracking failure, not a finding.
            reasons.append(f"systolic lengthening (peak {stretch:+.1f}%)")
        else:
            # No meaningful systolic shortening (GLS ≈ 0): a measurement, not an
            # impossibility — reported, and the caller downgrades it to review.
            reasons.append(f"no systolic shortening (peak {peak:+.1f}%)")

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
            rmin = float(np.min(rfinite))
            if rpeak <= 0.0:
                if rmin < -1.0:
                    reasons.append(f"radial thinning during systole (peak {rmin:+.1f}%)")
                else:
                    reasons.append("no radial thickening (radial peak <= 0%)")

    hard = [
        reason
        for reason in reasons
        if reason.startswith(("no longitudinal", "strain window has no finite"))
        or reason.startswith(("systolic lengthening", "radial thinning", "implausibly large"))
    ]
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
        strain[t] = lagrangian_strain_pct(ratio, 1.0)

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
        strain[t] = lagrangian_strain_pct(ratio, 1.0)

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
    *,
    target_length_mm: float = 10.0,
) -> np.ndarray:
    """Per-node longitudinal strain curves — the single strain definition.

    For every node ``i`` the local strain is the clinical (Lagrange) strain of
    the material sub-arc that runs through the node, so a node owns *its own*
    deformation instead of borrowing the strain of a neighbour pair (issue #C3):

        ε_i(t) = (L_i(t) − L_i(ED)) / L_i(ED) · 100 %

    The sub-arc is a **physical length**, not a fixed number of nodes: starting
    from the node, the window grows to both sides until its end-diastolic length
    reaches ``target_length_mm`` (or the material line ends). The window is
    chosen *once*, at ED, and is then kept for every frame, so all frames
    measure the same material interval. This matters because kernels are spaced
    by index (equal angle): near the annulus neighbours sit ~1.5 mm apart, and a
    fixed ±1-neighbour baseline would measure the strain of a 3 mm stretch,
    where sub-pixel tracking noise of 0.3 px turns into several percent of
    strain — the reason the segmental numbers used to swing wildly while the
    global line looked plausible. ``target_length_mm=0`` restores the minimal
    three-node window.

    A node whose *own* position is missing yields NaN for that node and frame,
    and a neighbour that is missing only shrinks the sub-arc to the tracked side
    — a lost node never erases the strain of its healthy neighbours. The caller
    can therefore mask exactly the untracked nodes instead of smoothing them
    into a plausible-looking curve.

    Args:
        positions: (n_frames, n_nodes, 2) node positions in arc order.
        ed_index: end-diastole frame index (the strain reference).
        pixel_spacing: (row, col) mm per pixel.
        target_length_mm: physical length of the material sub-arc at ED.

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

    avg_spacing = float(np.mean(pixel_spacing))
    target_px = max(float(target_length_mm), 0.0) / (avg_spacing if avg_spacing > 1e-9 else 1.0)

    # ── the material window of every node, chosen once at ED ────────────────
    ed_pts = pts[ed]
    step = np.linalg.norm(np.diff(ed_pts, axis=0), axis=1) * avg_spacing
    step = np.where(np.isfinite(step), step, 0.0)
    cumulative = np.concatenate([[0.0], np.cumsum(step)])
    left = np.empty(n_nodes, dtype=np.int64)
    right = np.empty(n_nodes, dtype=np.int64)
    for i in range(n_nodes):
        lo = hi = i
        length = 0.0
        while length < target_px and (lo > 0 or hi < n_nodes - 1):
            grow_left = lo > 0 and (hi >= n_nodes - 1 or step[lo - 1] >= step[hi])
            if grow_left:
                lo -= 1
            else:
                hi += 1
            length = cumulative[hi] - cumulative[lo]
        # A target of 0 keeps the minimal three-node window (issue #C3 default).
        left[i] = min(lo, max(i - 1, 0)) if target_px <= 0 else lo
        right[i] = max(hi, min(i + 1, n_nodes - 1)) if target_px <= 0 else hi

    def _subarc_length(frame_index: int) -> np.ndarray:
        """Length of each node's material sub-arc in this frame (mm)."""
        length = np.full(n_nodes, np.nan, dtype=np.float64)
        for i in range(n_nodes):
            if not np.isfinite(pts[frame_index, i]).all():
                continue
            # The window shrinks to the largest tracked run around the node, so
            # a lost neighbour never erases the strain of a healthy node.
            lo = i
            while lo > left[i] and np.isfinite(pts[frame_index, lo - 1]).all():
                lo -= 1
            hi = i
            while hi < right[i] and np.isfinite(pts[frame_index, hi + 1]).all():
                hi += 1
            polyline = pts[frame_index, lo : hi + 1]
            if polyline.shape[0] < 2:
                continue
            length[i] = float(np.sum(np.linalg.norm(np.diff(polyline, axis=0), axis=1))) * avg_spacing
        return length

    l0 = _subarc_length(ed)
    usable = np.isfinite(l0) & (l0 > 1e-6)
    if not np.any(usable):
        return curves

    for t in range(n_frames):
        lt = _subarc_length(t)
        # The window is fixed at ED, so both lengths cover the same material:
        # no re-windowing that would hide a lost node as "less deformation".
        ratio = np.full(n_nodes, np.nan, dtype=np.float64)
        np.divide(lt, l0, out=ratio, where=usable)
        curves[t] = lagrangian_strain_pct(ratio, 1.0)
    return curves


def arc_length_inflation_mm(
    raw_positions: np.ndarray,
    smoothed_positions: np.ndarray,
    indices: Sequence[int],
    pixel_spacing: tuple[float, float],
) -> float:
    """Median inflation (mm) of a noisy arc over the smoothed one.

    The direct measurement of the effect that matters (plan §7.5, F6): a polyline
    through noisy points is longer than the curve it samples, because
    ``E|Δp + n| > |Δp|``. Both the reference frame and every deformed frame carry
    the same bias, so it *flattens* the strain curve while leaving the NCC at
    ~0.9 — the "quality is high, GLS is wrong" symptom. Comparing the raw
    trajectory with the smoothed one (the pipeline's own best estimate of the
    contour) measures that inflation without any noise model:

        inflation = median_t ( L_raw(t) − L_smooth(t) )   ≥ 0

    Args:
        raw_positions: (n_frames, n_nodes, 2) positions before smoothing.
        smoothed_positions: (n_frames, n_nodes, 2) positions after smoothing.
        indices: columns of the material line, in arc order.
        pixel_spacing: (row, col) mm per pixel.

    Returns:
        Median length inflation in millimetres (never negative).
    """
    raw = np.asarray(raw_positions, dtype=np.float64)[:, list(indices), :]
    smooth = np.asarray(smoothed_positions, dtype=np.float64)[:, list(indices), :]
    if raw.shape[0] < 1 or raw.shape[1] < 2:
        return 0.0
    spacing = float(np.mean(pixel_spacing))
    l_raw = np.array([np.sum(np.linalg.norm(np.diff(frame, axis=0), axis=1)) for frame in raw])
    l_smooth = np.array([np.sum(np.linalg.norm(np.diff(frame, axis=0), axis=1)) for frame in smooth])
    diff = (l_raw - l_smooth) * spacing
    return float(max(np.median(diff), 0.0))


def arc_contraction_mm(
    positions: np.ndarray,
    indices: Sequence[int],
    ed_index: int,
    pixel_spacing: tuple[float, float],
    window_end: int | None = None,
) -> float:
    """Largest measured shortening of the material line (mm), ED to any frame.

    The signal the inflation is compared against: how much shorter the line ever
    gets inside the analysis window.

    Args:
        positions: (n_frames, n_nodes, 2) positions in pixels.
        indices: columns of the material line, in arc order.
        ed_index: end-diastole frame (the reference length).
        pixel_spacing: (row, col) mm per pixel.
        window_end: last frame of the analysis window (defaults to the last one).

    Returns:
        Shortening in millimetres (0 when the line never shortens).
    """
    pts = np.asarray(positions, dtype=np.float64)[:, list(indices), :]
    if pts.shape[0] < 1 or pts.shape[1] < 2:
        return 0.0
    ed = int(min(max(ed_index, 0), pts.shape[0] - 1))
    last = pts.shape[0] - 1 if window_end is None else int(min(max(window_end, ed), pts.shape[0] - 1))
    spacing = float(np.mean(pixel_spacing))
    lengths = np.array([np.sum(np.linalg.norm(np.diff(frame, axis=0), axis=1)) for frame in pts[ed : last + 1]])
    return float(max((lengths[0] - lengths.min()) * spacing, 0.0))


def smooth_curves_time(
    curves: np.ndarray,
    *,
    window: int = 7,
    polyorder: int = 2,
) -> np.ndarray:
    """Temporal Savitzky–Golay smoothing of strain curves, NaN-preserving.

    Speckle tracking is a per-frame measurement: even with clean trajectories a
    single frame can spike by several percent, and a *peak* read from such a
    curve (segmental peak systolic strain, TTP, ESS) is biased by exactly those
    spikes — the reason the segmental numbers swing while the global curve looks
    plausible. Vendors low-pass the strain curve in time before reading the
    metrics; this filter is the same idea and nothing else: the shape inside the
    systolic window is preserved (quadratic polynomial), the noise is not. NaN
    samples are interpolated for the fit and restored afterwards, so a lost
    node-frame stays visibly lost instead of being invented.

    Args:
        curves: (n_frames, n_nodes) strain in percent.
        window: filter length in frames (forced to an odd number ≥ 3).
        polyorder: polynomial order of the local fit (< window).

    Returns:
        Filtered copy of ``curves``.
    """
    arr = np.asarray(curves, dtype=np.float64)
    if arr.ndim != 2 or arr.shape[0] < 3:
        return arr.copy()
    n_frames = arr.shape[0]
    win = int(window)
    if win % 2 == 0:
        win += 1
    win = max(3, min(win, n_frames if n_frames % 2 == 1 else n_frames - 1))
    order = max(1, min(int(polyorder), win - 1))
    if win <= order + 1:
        return arr.copy()
    out = arr.copy()
    frame_index = np.arange(n_frames, dtype=np.float64)
    for node in range(arr.shape[1]):
        column = arr[:, node]
        finite = np.isfinite(column)
        if finite.sum() < order + 2:
            continue
        if finite.sum() < n_frames:
            column = np.interp(frame_index, frame_index[finite], column[finite])
        out[:, node] = savgol_filter(column, win, order, mode="interp")
        out[~finite, node] = np.nan
    return out


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
