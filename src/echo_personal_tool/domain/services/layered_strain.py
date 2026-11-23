"""Layered LV strain — endo/mid/epi curves and the transmural gradient (plan А.8, issue #646).

The myocardium is measured the way the single-line pipeline already measures
it (:mod:`strain_computation`), only repeated per layer: the tracking kernels
sit in three rings between the endocardial and epicardial contours
(:func:`myocardial_zone.sample_kernels_in_zone` — the rings exist since the
dual-contour zone landed), so each ring is its own material line and owns a
global longitudinal strain curve computed with the *same* definition as the
endocardial one (Lagrangian arc-length change against ED, quality-weighted).

The clinical payoff is the **transmural gradient**: the endocardial layer
deforms more than the epicardial one in healthy myocardium, and subendocardial
ischaemia flattens that gradient before the ejection fraction moves. The
gradient here is ``GLS_epi − GLS_endo`` in percentage points — positive when
the endocardium shortens more than the epicardium (the normal direction), and
honestly ``None`` when either layer produced no curve.

Honest limits, the same as everywhere in this pipeline: a layer that lost too
many of its nodes to visibility falls back to its full arc (the same rule the
global endo curve applies, :data:`MIN_VISIBLE_NODES` in the worker) and a layer
with no kernels at all produces no curve — the result carries layers it
measured, never an interpolated stand-in. The curves share the worker's time
base: they come back as *window* curves (the caller embeds them full-length
with the same :func:`speckle_worker._embed_window_curve` rule the global curve
uses), so the endocardial layer's curve is bit-for-bit the global curve the
meta bar reports — one strain definition, not two.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np

from echo_personal_tool.domain.models.speckle import TrackingKernel
from echo_personal_tool.domain.services.strain_computation import (
    aggregate_segment_curves,
    compute_gls,
    compute_node_longitudinal_curves,
    compute_weighted_longitudinal_strain_gl,
    smooth_curves_time,
)

#: Myocardial layers, endo → epi. The order is also the reporting order.
LAYERS: tuple[str, ...] = ("endo", "mid", "epi")

#: Same visibility rule the worker applies to the endocardial arc: a layer
#: whose visible arc is shorter than this many nodes is measured on its full
#: line instead of a remnant (clinical review Q4).
DEFAULT_MIN_VISIBLE_NODES = 8


def layer_columns(
    kernels: Sequence[TrackingKernel],
    visible_nodes: np.ndarray | Mapping[int, bool] | None = None,
    *,
    min_visible: int = DEFAULT_MIN_VISIBLE_NODES,
) -> dict[str, list[int]]:
    """Kernel indices per layer, in arc order (by ``node_index``).

    ``visible_nodes`` — the worker's per-kernel visibility verdict indexed by
    kernel position; ``None`` keeps every kernel. A layer whose visible part
    falls below ``min_visible`` nodes falls back to its full arc — a remnant
    of the wall measures nothing comparable, the full line at least keeps the
    definition the ED frame declared.

    Raises:
        ValueError: if ``kernels`` is empty (the caller decides whether a
            run without kernels is an error; here it is not a silent ``{}``).
    """
    if len(kernels) == 0:
        raise ValueError("layer_columns needs at least one kernel")

    per_layer: dict[str, list[int]] = {}
    for kernel_index, kernel in enumerate(kernels):
        per_layer.setdefault(kernel.layer, []).append(kernel_index)

    columns: dict[str, list[int]] = {}
    for layer, indices in per_layer.items():
        ordered = sorted(indices, key=lambda i: kernels[i].node_index)
        if visible_nodes is None:
            columns[layer] = ordered
            continue
        visible = [i for i in ordered if bool(visible_nodes[i])]
        columns[layer] = visible if len(visible) >= min_visible else ordered
    return columns


def compute_layer_longitudinal_curves(
    positions: np.ndarray,
    ed_index: int,
    pixel_spacing: tuple[float, float],
    kernels: Sequence[TrackingKernel],
    ncc_weights: np.ndarray | None = None,
    visible_nodes: np.ndarray | Mapping[int, bool] | None = None,
    *,
    min_visible: int = DEFAULT_MIN_VISIBLE_NODES,
) -> dict[str, np.ndarray]:
    """Global longitudinal strain curve per layer (window curves, not embedded).

    Every layer's curve is computed with exactly the function the reported
    global curve uses (:func:`compute_weighted_longitudinal_strain_gl`) on
    that layer's arc-ordered columns — the endocardial curve therefore equals
    the reported global curve whenever the worker fed the same columns and
    weights, and the mid/epi curves are the same measurement on their own
    material line, not a rescaled copy.

    Returns:
        ``{layer: (n_window_frames,) curve in percent}`` — only layers that
        have at least two columns produce a curve (an arc of one node has no
        length to compare).
    """
    columns = layer_columns(kernels, visible_nodes, min_visible=min_visible)
    curves: dict[str, np.ndarray] = {}
    for layer in LAYERS:
        cols = columns.get(layer)
        if not cols or len(cols) < 2:
            continue
        curves[layer] = compute_weighted_longitudinal_strain_gl(
            positions,
            ed_index,
            pixel_spacing,
            cols,
            ncc_weights,
        )
    return curves


def compute_layer_gls(
    window_curves: Mapping[str, np.ndarray],
    *,
    ed_index: int,
    es_index: int,
) -> dict[str, float]:
    """Peak negative strain per layer — the same ``compute_gls`` definition.

    Args:
        window_curves: per-layer curves over the analysis window (what
            :func:`compute_layer_longitudinal_curves` returns).
        ed_index: end-diastole frame index (window-local).
        es_index: end-systole frame index (window-local).

    Returns:
        ``{layer: GLS %}`` — layers without a curve are absent, never ``0``.
    """
    return {
        layer: compute_gls(curve, ed_index, es_index)
        for layer, curve in ((l, window_curves.get(l)) for l in LAYERS)
        if curve is not None
    }


def transmural_gradient_pp(layer_gls: Mapping[str, float]) -> float | None:
    """Transmural gradient ``GLS_epi − GLS_endo`` in percentage points.

    Positive when the endocardial layer shortens more than the epicardial one
    (the normal transmural direction); near zero or negative when the gradient
    is flattened or inverted. ``None`` — honestly, when either layer produced
    no finite value: a gradient missing one of its two layers is not a number.
    """
    endo = layer_gls.get("endo")
    epi = layer_gls.get("epi")
    if endo is None or epi is None:
        return None
    endo_v, epi_v = float(endo), float(epi)
    if not (np.isfinite(endo_v) and np.isfinite(epi_v)):
        return None
    return float(epi_v - endo_v)


def compute_layer_segment_curves(
    positions: np.ndarray,
    ed_index: int,
    pixel_spacing: tuple[float, float],
    kernels: Sequence[TrackingKernel],
    visible_nodes: np.ndarray | Mapping[int, bool] | None = None,
    *,
    smoothing_frames: int = 9,
    min_visible: int = DEFAULT_MIN_VISIBLE_NODES,
) -> dict[str, dict[int, np.ndarray]]:
    """Per-segment longitudinal strain curves per layer (window curves).

    Mirrors the single-line pipeline node by node: every layer is its own
    material line, each node owns the Green–Lagrange strain of its sub-arc
    (:func:`compute_node_longitudinal_curves`), the curves get the same
    temporal smoothing the global segment curves receive, and the segment
    curve is the frame-wise weighted mean of its node curves
    (:func:`aggregate_segment_curves`). With the worker's smoothing setting
    the endocardial layer reproduces the reported ``segment_curves`` exactly —
    the layer plot is the same measurement, one definition deeper.

    Returns:
        ``{layer: {segment_id: (n_window_frames,) curve}}`` — layers and
        segments the layer cannot see are absent.
    """
    columns = layer_columns(kernels, visible_nodes, min_visible=min_visible)
    out: dict[str, dict[int, np.ndarray]] = {}
    for layer in LAYERS:
        cols = columns.get(layer)
        if not cols or len(cols) < 2:
            continue
        node_curves = compute_node_longitudinal_curves(
            positions[:, cols, :],
            ed_index,
            pixel_spacing,
        )
        node_curves = smooth_curves_time(node_curves, window=int(smoothing_frames), polyorder=2)
        segments = [kernels[i].aha_segment for i in cols]
        out[layer] = aggregate_segment_curves(node_curves, segments)
    return out
