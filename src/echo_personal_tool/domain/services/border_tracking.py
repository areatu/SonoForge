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


def build_border_kernels(
    endo0: np.ndarray,
    epi0: np.ndarray,
    *,
    n_nodes: int = 48,
    layer_fracs: tuple[float, ...] = (0.0, 0.5, 1.0),
) -> tuple[list[TrackingKernel], np.ndarray]:
    """Create kernels on a node grid between the ED endo/epi contours.

    Node ``j`` owns one kernel per layer, at material fraction ``f`` between
    the endo (f=0) and epi (f=1) border points of that node.  Layer labels are
    ``endo`` (f=0), ``mid`` (f=0.5) and ``epi`` (f=1).

    Returns ``(kernels, layer_edges)`` where ``layer_edges`` maps each layer
    label to the (start, stop) kernel index range within ``kernels``.
    """
    endo = resample_closed(endo0, n_nodes)
    epi = resample_closed(epi0, n_nodes)
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


def _smooth_contour(pts: np.ndarray, window: int, ncc: np.ndarray, threshold: float) -> np.ndarray:
    """Replace low-NCC points by neighbor medians, then smooth along the arc.

    This is the spatial regularization step: it lets strong matches dominate
    while outliers (including lost wall segments) are filled coherently instead
    of drifting independently.
    """
    pts = pts.copy()
    n = len(pts)
    if n < 4:
        return pts
    half = max(1, window // 2)
    # 1) robust replacement of invalid nodes with the median of valid neighbors
    strong = ncc >= threshold
    if strong.sum() >= 2 and not strong.all():
        for i in range(n):
            if strong[i]:
                continue
            for radius in range(1, n):
                neigh = []
                for off in (-radius, radius):
                    if strong[(i + off) % n]:
                        neigh.append(pts[(i + off) % n])
                if len(neigh) >= 2:
                    break
            if neigh:
                pts[i] = np.median(np.asarray(neigh), axis=0)
    # 2) weighted moving average along the closed contour
    out = pts.copy()
    for i in range(n):
        acc = np.zeros(2)
        wsum = 0.0
        for off in range(-half, half + 1):
            w = 1.0 / (1.0 + abs(off))
            acc += w * pts[(i + off) % n]
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
    endo = resample_closed(endo0, n_nodes)
    epi = resample_closed(epi0, n_nodes)
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
        endo, epi, n_nodes=n_nodes, layer_fracs=(0.0, 0.5, 1.0)
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
            e_new[j], e_ncc[j] = _match_point(
                pyr_prev, pyr_cur, e_prev[j], config, j
            )
            p_new[j], p_ncc[j] = _match_point(
                pyr_prev, pyr_cur, p_prev[j], config, j
            )
        e_new = _smooth_contour(e_new, max(5, int(0.12 * n_nodes) | 1), e_ncc, ncc_thr)
        p_new = _smooth_contour(p_new, max(5, int(0.12 * n_nodes) | 1), p_ncc, ncc_thr)
        # Robust bulk motion of the epi border (median of Cartesian
        # displacements): a true translation shifts all nodes in the same
        # direction and is kept; a uniform radial expansion points in many
        # directions and its median is ~0, so it is not absorbed.  For small
        # median motion the borders are clamped radially against the FIXED ED
        # contour (the drawn epicardium stays the outer envelope); only a
        # large translation follows the translated envelope.
        t_global = np.median(p_new - epi, axis=0)
        if float(np.linalg.norm(t_global)) <= translation_threshold_px:
            e_new = _clamp_outward(e_new, lv_center, r_endo0, outward_slack_px)
            p_new = _clamp_outward(p_new, lv_center, r_epi0, outward_slack_px)
        else:
            e_new = _clamp_outward(e_new, lv_center + t_global, r_endo0, outward_slack_px)
            p_new = _clamp_outward(p_new, lv_center + t_global, r_epi0, outward_slack_px)
        # enforce per-node ordering epi outside endo with a minimal thickness
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
    pts: np.ndarray, center: np.ndarray, r0: np.ndarray, slack: float
) -> np.ndarray:
    """Clamp contour points so they never move outward past their ED radius.

    Inward motion (systolic contraction/thickening) is free; outward motion is
    limited to ``slack`` pixels beyond the ED radius.  The reference is the
    fixed ED LV center so the drawn endo/epi contours stay the outer envelope
    through the whole window.
    """
    v = pts - center
    r = np.linalg.norm(v, axis=1)
    limit = r0 + slack
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
