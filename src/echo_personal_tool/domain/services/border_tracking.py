"""Vendor-style wall-border STE: propagate endo/epi contours frame-to-frame.

Commercial STE (EchoPAC, QLab) does not freeze the ED contours and run
independent kernels inside a static band.  It propagates the myocardial
borders through the cycle with the same block-matching motion estimates and
keeps the tracked material between the *moving* endo/epi borders.  This module
implements that shape:

  1. Resample the ED endo and epi contours to a common node grid.
  2. Track the border points sequentially (frame-to-frame) with NCC block
     matching, exactly like the kernel tracker.
  3. Regularize each frame's contours: outliers are replaced by neighbor
     medians along the contour, then the contour is spatially smoothed — this
     is the "global coherent motion field" approximation that independent
     per-kernel matching lacks.
  4. Reconstruct per-layer kernel positions for any radial material fraction
     between the propagated borders, so kernels always live inside the moving
     wall band (nothing can cross endo/epi by construction).
"""

from __future__ import annotations

import logging

import numpy as np

from echo_personal_tool.domain.models.speckle import SpeckleConfig, TrackingKernel
from echo_personal_tool.domain.services.speckle_tracking import (
    block_match_single,
    build_gaussian_pyramid,
)

logger = logging.getLogger(__name__)


def resample_closed(points: np.ndarray, n: int) -> np.ndarray:
    """Resample a closed contour to ``n`` points spaced by arc length."""
    pts = np.asarray(points, dtype=np.float64)
    if len(pts) == 0:
        return pts
    closed = pts.copy()
    if not np.allclose(closed[0], closed[-1]):
        closed = np.concatenate([closed, closed[:1]], axis=0)
    seg = np.linalg.norm(np.diff(closed, axis=0), axis=1)
    total = float(seg.sum())
    if total <= 0:
        return pts[:n].copy() if len(pts) >= n else pts.copy()
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    target = np.linspace(0.0, total, n, endpoint=False)
    out = np.zeros((n, 2), dtype=np.float64)
    j = 0
    for i, t in enumerate(target):
        while j < len(cum) - 2 and cum[j + 1] <= t:
            j += 1
        if cum[j + 1] - cum[j] < 1e-9:
            out[i] = closed[j]
            continue
        frac = (t - cum[j]) / (cum[j + 1] - cum[j])
        out[i] = closed[j] * (1.0 - frac) + closed[j + 1] * frac
    return out


def resample_open_arc(points: np.ndarray, n: int) -> np.ndarray:
    """Resample an **open** apical arc to ``n`` points spaced by arc length.

    The STE material line runs from one mitral annulus point through the apex to
    the other one. Treating it as a closed contour (``resample_closed``) appends
    the first point to the end, so the annulus chord becomes part of the
    geometry: nodes are distributed over the chord and kernels are placed inside
    the LV cavity instead of in the myocardium (issue #C1 — the single largest
    geometric defect of the module). Both endpoints are preserved here and no
    segment is ever added between the last and the first point.
    """
    pts = np.asarray(points, dtype=np.float64)
    if len(pts) == 0:
        return pts
    if len(pts) == 1:
        return np.repeat(pts, n, axis=0)
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    total = float(seg.sum())
    if total <= 0:
        return pts[:n].copy() if len(pts) >= n else pts.copy()
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    target = np.linspace(0.0, total, n)
    out = np.zeros((n, 2), dtype=np.float64)
    out[:, 0] = np.interp(target, cum, pts[:, 0])
    out[:, 1] = np.interp(target, cum, pts[:, 1])
    return out


def is_closed_contour(points: np.ndarray, tol_px: float = 1.0) -> bool:
    """Whether a contour is a closed ring (first point == last point)."""
    pts = np.asarray(points, dtype=np.float64)
    if len(pts) < 3:
        return False
    return bool(np.linalg.norm(pts[0] - pts[-1]) <= tol_px)


def resample_along_arc(points: np.ndarray, n: int, *, closed: bool | None = None) -> np.ndarray:
    """Resample a contour with the resampler that matches its topology.

    ``closed=None`` auto-detects: an STE apical arc is open and must keep its
    endpoints, a full ring (test phantoms, LA/RV contours) keeps the wrap-around.
    """
    if closed is None:
        closed = is_closed_contour(points)
    return resample_closed(points, n) if closed else resample_open_arc(points, n)


def build_border_kernels(
    endo0: np.ndarray,
    epi0: np.ndarray,
    *,
    n_nodes: int = 48,
    layer_fracs: tuple[float, ...] = (0.0, 0.5, 1.0),
    closed: bool | None = None,
) -> tuple[list[TrackingKernel], np.ndarray]:
    """Create kernels on a node grid between the ED endo/epi contours.

    Node ``j`` owns one kernel per layer, at material fraction ``f`` between
    the endo (f=0) and epi (f=1) border points of that node.  Layer labels are
    ``endo`` (f=0), ``mid`` (f=0.5) and ``epi`` (f=1).

    Returns ``(kernels, layer_edges)`` where ``layer_edges`` maps each layer
    label to the (start, stop) kernel index range within ``kernels``.
    """
    endo = resample_along_arc(endo0, n_nodes, closed=closed)
    epi = resample_along_arc(epi0, n_nodes, closed=closed)
    fracs = sorted(set(layer_fracs))
    labels = {0.0: "endo", 1.0: "epi"}
    label_for = {f: labels.get(f, "mid") for f in fracs}
    kernels: list[TrackingKernel] = []
    for j in range(n_nodes):
        for f in fracs:
            pt = endo[j] * (1.0 - f) + epi[j] * f
            kernels.append(
                TrackingKernel(
                    center=(float(pt[0]), float(pt[1])),
                    node_index=j,
                    layer=label_for[f],
                    radius=4,
                    arc_length_param=float(j / max(n_nodes - 1, 1)),
                )
            )
    layer_edges: dict[str, tuple[int, int]] = {}
    for f in fracs:
        lab = label_for[f]
        idx = [i for i, k in enumerate(kernels) if k.layer == lab]
        if idx:
            layer_edges[lab] = (idx[0], idx[-1] + 1)
    return kernels, layer_edges


def _smooth_contour(
    pts: np.ndarray,
    window: int,
    ncc: np.ndarray,
    threshold: float,
    *,
    closed: bool = True,
) -> np.ndarray:
    """Replace low-NCC points by neighbor medians, then smooth along the arc.

    This is the spatial regularization step: it lets strong matches dominate
    while outliers (including lost wall segments) are filled coherently instead
    of drifting independently.

    For an **open** arc the neighbours are searched on the tracked side only and
    the moving average is mirrored at both ends instead of wrapping around: on
    an apical arc the two ends are the opposite mitral annulus points, and
    wrapping blends them into each other.
    """
    pts = pts.copy()
    n = len(pts)
    if n < 4:
        return pts
    half = max(1, window // 2)

    def _step(index: int, offset: int) -> int:
        """Neighbour index; clamps (mirrors) at the ends of an open arc."""
        idx = index + offset
        if closed:
            return idx % n
        if idx < 0:
            return -idx
        if idx > n - 1:
            return 2 * (n - 1) - idx
        return idx

    # 1) robust replacement of invalid nodes with the median of valid neighbors
    strong = ncc >= threshold
    if strong.sum() >= 2 and not strong.all():
        for i in range(n):
            if strong[i]:
                continue
            neigh: list[np.ndarray] = []
            for radius in range(1, n):
                neigh = []
                for offset in (-radius, radius):
                    idx = _step(i, offset) if not closed else (i + offset) % n
                    if 0 <= idx < n and strong[idx]:
                        neigh.append(pts[idx])
                if len(neigh) >= 2 or (not closed and len(neigh) >= 1 and radius >= 2):
                    break
            if neigh:
                pts[i] = np.median(np.asarray(neigh), axis=0)
    # 2) weighted moving average along the arc
    out = pts.copy()
    for i in range(n):
        acc = np.zeros(2)
        wsum = 0.0
        for off in range(-half, half + 1):
            w = 1.0 / (1.0 + abs(off))
            acc += w * pts[_step(i, off)]
            wsum += w
        out[i] = acc / wsum
    return out


def propagate_wall_borders(
    frames: np.ndarray,
    endo0: np.ndarray,
    epi0: np.ndarray,
    config: SpeckleConfig,
    *,
    n_nodes: int = 64,
    min_thickness_px: float = 2.0,
    outward_slack_px: float = 2.0,
    closed: bool | None = None,
    max_inward_frac: float = 0.5,
) -> dict:
    """Track the wall borders through ``frames``.

    ``frames`` must already be preprocessed the way the kernel tracker expects
    (the caller normalizes/preprocesses them).  ``endo0``/``epi0`` are the ED
    contours in pixel coordinates.

    Returns a dict with:
      ``positions``  (n_frames, n_kernels, 2) per-material-layer kernel
      ``ncc``        (n_frames, n_kernels) NCC per kernel
      ``valid``      (n_frames, n_kernels) bool
      ``endo``       (n_frames, n_nodes, 2) propagated endo border
      ``epi``        (n_frames, n_nodes, 2) propagated epi border
      ``kernels``    kernel descriptors matching the first axis of positions
      ``layer_edges`` label -> (start, stop) index range
    """
    # Apical STE arcs are open (annulus → apex → annulus): resampling them as a
    # closed ring would fold the annulus chord into the material line (issue #C1).
    endo = resample_along_arc(endo0, n_nodes, closed=closed)
    epi = resample_along_arc(epi0, n_nodes, closed=closed)
    is_open = not (is_closed_contour(endo0) if closed is None else closed)
    n_frames = int(frames.shape[0])
    # Fixed ED reference geometry: during systole the epicardium barely moves
    # and must never blow outward past the user-drawn contour. Both borders
    # are clamped radially against their ED radii (per node) so they may move
    # inward freely (contraction/thickening) but not outward beyond a small
    # slack — this stops cumulative outward drift of weak NCC matches from
    # pushing kernels through the drawn epicardium (issue #7, user-visible).
    lv_center = np.mean(endo, axis=0)
    r_endo0 = np.linalg.norm(endo - lv_center, axis=1)
    r_epi0 = np.linalg.norm(epi - lv_center, axis=1)
    # Small estimated bulk motion (<= ``translation_threshold_px``) is treated
    # as local NCC noise/drift and clamped hard against the fixed ED contour;
    # only a genuinely large translation (whole heart swinging) follows the
    # translated envelope instead — otherwise the drawn epicardium stays the
    # absolute outer bound and kernels cannot cross it.
    translation_threshold_px = 3.0
    ncc_thr = float(config.ncc_threshold)

    kernels, layer_edges = build_border_kernels(
        endo, epi, n_nodes=n_nodes, layer_fracs=(0.0, 0.5, 1.0), closed=closed
    )
    n_k = len(kernels)

    # material fractions per kernel index
    frac_of = {}
    lab_of = {}
    for i, k in enumerate(kernels):
        lab_of[i] = k.layer
        f = 0.0 if k.layer == "endo" else (1.0 if k.layer == "epi" else 0.5)
        frac_of[i] = f

    endo_t = np.zeros((n_frames, n_nodes, 2), dtype=np.float64)
    epi_t = np.zeros((n_frames, n_nodes, 2), dtype=np.float64)
    positions = np.zeros((n_frames, n_k, 2), dtype=np.float64)
    ncc_all = np.zeros((n_frames, n_k), dtype=np.float64)
    valid_all = np.zeros((n_frames, n_k), dtype=bool)

    endo_t[0] = endo
    epi_t[0] = epi
    positions[0] = np.array([k.center for k in kernels])
    ncc_all[0] = 1.0
    valid_all[0] = True

    e_prev = endo
    p_prev = epi
    pyr_prev = build_gaussian_pyramid(frames[0].astype(np.float32), config.pyramid_levels)
    for t in range(1, n_frames):
        pyr_cur = build_gaussian_pyramid(frames[t].astype(np.float32), config.pyramid_levels)
        e_new = np.zeros_like(e_prev)
        p_new = np.zeros_like(p_prev)
        e_ncc = np.zeros(n_nodes)
        p_ncc = np.zeros(n_nodes)
        for j in range(n_nodes):
            e_new[j], e_ncc[j] = _match_point(pyr_prev, pyr_cur, e_prev[j], config, j)
            p_new[j], p_ncc[j] = _match_point(pyr_prev, pyr_cur, p_prev[j], config, j)
        e_new = _smooth_contour(e_new, max(5, int(0.12 * n_nodes) | 1), e_ncc, ncc_thr, closed=not is_open)
        p_new = _smooth_contour(p_new, max(5, int(0.12 * n_nodes) | 1), p_ncc, ncc_thr, closed=not is_open)
        # Robust bulk motion of the epi border (median of Cartesian
        # displacements): a true translation shifts all nodes in the same
        # direction and is kept; a uniform radial expansion points in many
        # directions and its median is ~0, so it is not absorbed.  For small
        # median motion the borders are clamped radially against the FIXED ED
        # contour (the drawn epicardium stays the outer envelope); only a
        # large translation follows the translated envelope.
        t_global = np.median(p_new - epi, axis=0)
        # An open apical arc is not a closed ring around the centre: a node may
        # legitimately travel a long way radially (basal nodes nearly reach the
        # centre in a foreshortened view), so only "the node did not collapse
        # past the ED position by more than half the radius" is enforced.
        inward_cap = max_inward_frac if is_open else None
        if float(np.linalg.norm(t_global)) <= translation_threshold_px:
            e_new = _clamp_outward(
                e_new, lv_center, r_endo0, outward_slack_px, center0=lv_center, max_inward=inward_cap
            )
            p_new = _clamp_outward(
                p_new, lv_center, r_epi0, outward_slack_px, center0=lv_center, max_inward=inward_cap
            )
        else:
            shifted = lv_center + t_global
            e_new = _clamp_outward(e_new, shifted, r_endo0, outward_slack_px, center0=shifted, max_inward=inward_cap)
            p_new = _clamp_outward(p_new, shifted, r_epi0, outward_slack_px, center0=shifted, max_inward=inward_cap)
        # Enforce the per-node ordering epi-outside-endo with a minimal
        # thickness. The clamped epicardium is the hard outer envelope (it is
        # the contour the user drew), so a pair that ends up too close is
        # resolved by moving the ENDO node inward; only when there is no room
        # left is the epi node pushed out, which keeps the old fallback.
        center = np.mean(e_new, axis=0)
        for j in range(n_nodes):
            u = p_new[j] - center
            d = float(np.linalg.norm(u))
            if d < 1e-6:
                u = np.array([1.0, 0.0])
                d = 1.0
            else:
                u = u / d
            r_e = float(np.dot(e_new[j] - center, u))
            if r_e > d - min_thickness_px:
                room = d - min_thickness_px
                if room > 1e-3:
                    e_new[j] = center + u * room
                else:
                    p_new[j] = e_new[j] + u * min_thickness_px
        endo_t[t] = e_new
        epi_t[t] = p_new
        for i in range(n_k):
            j = kernels[i].node_index
            f = frac_of[i]
            pos = endo_t[t, j] * (1.0 - f) + epi_t[t, j] * f
            positions[t, i] = pos
            if lab_of[i] == "endo":
                ncc_all[t, i] = float(e_ncc[j])
                valid_all[t, i] = e_ncc[j] >= ncc_thr
            elif lab_of[i] == "epi":
                ncc_all[t, i] = float(p_ncc[j])
                valid_all[t, i] = p_ncc[j] >= ncc_thr
            else:
                ncc_all[t, i] = min(float(e_ncc[j]), float(p_ncc[j]))
                valid_all[t, i] = valid_all[t - 1, i]
        e_prev = e_new
        p_prev = p_new
        pyr_prev = pyr_cur

    return {
        "positions": positions,
        "ncc": ncc_all,
        "valid": valid_all,
        "endo": endo_t,
        "epi": epi_t,
        "kernels": kernels,
        "layer_edges": layer_edges,
    }


def _clamp_outward(
    pts: np.ndarray,
    center: np.ndarray,
    r0: np.ndarray,
    slack: float,
    *,
    center0: np.ndarray | None = None,
    max_inward: float | None = None,
) -> np.ndarray:
    """Clamp contour points so they never move outward past their ED radius.

    Inward motion (systolic contraction/thickening) is free; outward motion is
    limited to ``slack`` pixels beyond the ED radius.  The reference is the
    fixed ED LV center so the drawn endo/epi contours stay the outer envelope
    through the whole window.

    ``max_inward`` optionally bounds how far a node may *collapse* towards
    ``center0`` (the ED cavity centre). Radial clamping is disk-based and cannot
    by itself see the difference between "the wall contracted" and "the node
    slid along the arc towards the apex" — without this bound a run of weak
    matches creeps toward the centre and the material line loses the apex.
    """
    v = pts - center
    r = np.linalg.norm(v, axis=1)
    limit = r0 + slack
    if max_inward is not None and center0 is not None:
        r_ed = np.linalg.norm(pts - center0, axis=1)
        r_ref = np.where(r0 > 1e-6, r0, 1.0)
        floor = r_ref * max(0.0, 1.0 - max_inward)
        under = r_ed < floor
        if np.any(under):
            pts = pts.copy()
            u = pts[under] - center0
            d = np.linalg.norm(u, axis=1)
            safe = np.where(d > 1e-6, d, 1.0)
            pts[under] = center0 + u / safe[:, None] * floor[under][:, None]
    over = r > limit
    if not np.any(over):
        return pts
    out = pts.copy()
    safe = r[over] > 1e-9
    idx = np.where(over)[0][safe]
    out[idx] = center + v[idx] * (limit[idx] / r[idx])[:, None]
    return out


def _match_point(
    pyr_ref, pyr_tgt, center: np.ndarray, config: SpeckleConfig, node_index: int
) -> tuple[np.ndarray, float]:
    """NCC match a single border point between the two frames."""
    dx, dy, ncc = block_match_single(pyr_ref, pyr_tgt, (float(center[0]), float(center[1])), config)
    return np.array([center[0] + dx, center[1] + dy]), float(ncc)
