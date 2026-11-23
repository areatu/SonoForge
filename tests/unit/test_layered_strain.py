"""Layered LV strain — per-layer curves, GLS and the transmural gradient (plan А.8, issue #646).

Synthetic geometry: three concentric rings of kernels (endo/mid/epi) on
circular "walls" whose arc length is scaled by a known factor over the cycle.
Uniform scaling about the ring centre scales every arc length by the same
factor, so each layer's curve reads its contraction directly — endo −20 %,
mid −15 %, epi −10 % — and the assertions can pin the *ordering* (the
transmural gradient), the exact definition reuse (the endo curve is the one
``compute_weighted_longitudinal_strain_gl`` produces) and the honest gaps
(missing layers, visibility fallback) without a Qt or a tracker.
"""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.models.speckle import TrackingKernel
from echo_personal_tool.domain.services.layered_strain import (
    LAYERS,
    compute_layer_gls,
    compute_layer_longitudinal_curves,
    compute_layer_segment_curves,
    layer_columns,
    transmural_gradient_pp,
)
from echo_personal_tool.domain.services.strain_computation import (
    compute_gls,
    compute_weighted_longitudinal_strain_gl,
)

N_NODES = 24
ED = 0
ES = 12
N_FRAMES = 25
CONTRACTION = {"endo": 0.80, "mid": 0.85, "epi": 0.90}
RING_RADIUS = {"endo": 40.0, "mid": 48.0, "epi": 56.0}


def _kernels() -> list[TrackingKernel]:
    kernels: list[TrackingKernel] = []
    for layer in LAYERS:
        radius = RING_RADIUS[layer]
        for i in range(N_NODES):
            angle = 2.0 * np.pi * i / N_NODES
            kernels.append(
                TrackingKernel(
                    center=(100.0 + radius * np.cos(angle), 100.0 + radius * np.sin(angle)),
                    radius=4,
                    node_index=i,
                    layer=layer,
                    aha_segment=(i % 6) + 1,
                )
            )
    return kernels


def _positions(kernels: list[TrackingKernel], frames: int = N_FRAMES) -> np.ndarray:
    """Each ring scales uniformly about its own centroid: 1.0 → contraction at ES, hold."""
    positions = np.zeros((frames, len(kernels), 2), dtype=np.float64)
    for layer in LAYERS:
        indices = [i for i, k in enumerate(kernels) if k.layer == layer]
        if not indices:
            continue
        centres = np.array([kernels[i].center for i in indices])
        centroid = centres.mean(axis=0)
        for t in range(frames):
            target = CONTRACTION[layer]
            scale = 1.0 + (target - 1.0) * min(t / ES, 1.0)
            positions[t, indices] = centroid + (centres - centroid) * scale
    return positions


def test_layer_columns_are_arc_ordered_per_layer() -> None:
    kernels = _kernels()
    columns = layer_columns(kernels)
    assert set(columns) == set(LAYERS)
    for layer in LAYERS:
        cols = columns[layer]
        assert len(cols) == N_NODES
        assert all(kernels[i].layer == layer for i in cols)
        node_order = [kernels[i].node_index for i in cols]
        assert node_order == sorted(node_order)


def test_layer_columns_reject_an_empty_kernel_list() -> None:
    with pytest.raises(ValueError, match="at least one kernel"):
        layer_columns([])


def test_layer_curves_show_the_transmural_gradient() -> None:
    kernels = _kernels()
    positions = _positions(kernels)
    curves = compute_layer_longitudinal_curves(positions, ED, (1.0, 1.0), kernels)
    assert set(curves) == set(LAYERS)

    gls = compute_layer_gls(curves, ed_index=ED, es_index=ES)
    # Endocardium shortens more than epicardium: more negative curve peaks.
    assert gls["endo"] < gls["mid"] < gls["epi"] < 0.0
    assert gls["endo"] == pytest.approx(-20.0, abs=1.0)
    assert gls["epi"] == pytest.approx(-10.0, abs=1.0)

    gradient = transmural_gradient_pp(gls)
    assert gradient is not None
    # epi −10 − endo −20 = +10 pp: positive when the endocardium deforms more.
    assert gradient == pytest.approx(10.0, abs=1.0)


def test_endo_curve_is_the_global_definition_on_its_columns() -> None:
    kernels = _kernels()
    positions = _positions(kernels)
    curves = compute_layer_longitudinal_curves(positions, ED, (1.0, 1.0), kernels)
    endo_cols = layer_columns(kernels)["endo"]
    reference = compute_weighted_longitudinal_strain_gl(positions, ED, (1.0, 1.0), endo_cols, None)
    np.testing.assert_allclose(curves["endo"], reference)


def test_layer_gls_matches_compute_gls_per_layer() -> None:
    kernels = _kernels()
    positions = _positions(kernels)
    curves = compute_layer_longitudinal_curves(positions, ED, (1.0, 1.0), kernels)
    gls = compute_layer_gls(curves, ed_index=ED, es_index=ES)
    for layer, curve in curves.items():
        assert gls[layer] == pytest.approx(compute_gls(curve, ED, ES))


def test_visibility_filters_columns_and_falls_back_below_the_minimum() -> None:
    kernels = _kernels()
    # Five lost endo nodes: 19 visible — the arc is filtered.
    visible = np.ones(len(kernels), dtype=bool)
    endo_cols = layer_columns(kernels)["endo"]
    for kernel_index in endo_cols[:5]:
        visible[kernel_index] = False
    filtered = layer_columns(kernels, visible)
    assert len(filtered["endo"]) == N_NODES - 5
    assert all(kernels[i].layer == "endo" and bool(visible[i]) for i in filtered["endo"])

    # Nearly the whole ring lost: the filtered remnant (4 nodes < 8) measures
    # nothing comparable, so the layer falls back to its full arc.
    visible2 = np.ones(len(kernels), dtype=bool)
    for kernel_index in endo_cols[: N_NODES - 4]:
        visible2[kernel_index] = False
    fallback = layer_columns(kernels, visible2)
    assert len(fallback["endo"]) == N_NODES


def test_visibility_propagates_into_the_curves() -> None:
    kernels = _kernels()
    positions = _positions(kernels)
    visible = np.ones(len(kernels), dtype=bool)
    for kernel_index in layer_columns(kernels)["mid"][:4]:
        visible[kernel_index] = False
    curves = compute_layer_longitudinal_curves(positions, ED, (1.0, 1.0), kernels, visible_nodes=visible)
    mid_reference = compute_weighted_longitudinal_strain_gl(
        positions,
        ED,
        (1.0, 1.0),
        layer_columns(kernels, visible)["mid"],
        None,
    )
    np.testing.assert_allclose(curves["mid"], mid_reference)


def test_a_missing_layer_is_absent_and_the_gradient_still_works() -> None:
    kernels = [k for k in _kernels() if k.layer != "mid"]
    positions = _positions(kernels)
    curves = compute_layer_longitudinal_curves(positions, ED, (1.0, 1.0), kernels)
    assert "mid" not in curves
    assert set(curves) == {"endo", "epi"}
    gls = compute_layer_gls(curves, ed_index=ED, es_index=ES)
    gradient = transmural_gradient_pp(gls)
    assert gradient is not None and gradient == pytest.approx(10.0, abs=1.0)


def test_the_gradient_is_none_without_one_of_its_layers() -> None:
    assert transmural_gradient_pp({"endo": -20.0}) is None
    assert transmural_gradient_pp({"endo": -20.0, "epi": float("nan")}) is None
    assert transmural_gradient_pp({}) is None


def test_a_single_node_layer_produces_no_curve() -> None:
    kernels = _kernels()[: N_NODES + 1]  # endo ring + one mid node
    positions = _positions(kernels)
    curves = compute_layer_longitudinal_curves(positions, ED, (1.0, 1.0), kernels)
    assert "mid" not in curves
    assert set(curves) == {"endo"}


def test_layer_segment_curves_follow_aha_segments() -> None:
    kernels = _kernels()
    positions = _positions(kernels)
    per_layer = compute_layer_segment_curves(
        positions,
        ED,
        (1.0, 1.0),
        kernels,
        smoothing_frames=1,  # no temporal smoothing: pure aggregation
    )
    assert set(per_layer) == set(LAYERS)
    for layer, segments in per_layer.items():
        assert set(segments) == set(range(1, 7))
        for curve in segments.values():
            assert curve.shape == (N_FRAMES - ES - 1 + ES + 1,) or curve.size == N_FRAMES - 0


def test_endo_segment_curves_mirror_the_manual_single_line_path() -> None:
    """The endo layer's segment curves equal the single-line pipeline's recipe."""
    from echo_personal_tool.domain.services.strain_computation import (
        aggregate_segment_curves,
        compute_node_longitudinal_curves,
    )

    kernels = _kernels()
    positions = _positions(kernels)
    endo_cols = layer_columns(kernels)["endo"]
    manual = aggregate_segment_curves(
        compute_node_longitudinal_curves(positions[:, endo_cols, :], ED, (1.0, 1.0)),
        [kernels[i].aha_segment for i in endo_cols],
    )
    per_layer = compute_layer_segment_curves(
        positions,
        ED,
        (1.0, 1.0),
        kernels,
        smoothing_frames=1,
    )
    assert set(per_layer["endo"]) == set(manual)
    for seg, curve in manual.items():
        np.testing.assert_allclose(per_layer["endo"][seg], curve)


def test_layer_segment_curves_differ_between_layers() -> None:
    """Layers are separate material lines: the same segment reads differently."""
    kernels = _kernels()
    positions = _positions(kernels)
    per_layer = compute_layer_segment_curves(
        positions,
        ED,
        (1.0, 1.0),
        kernels,
        smoothing_frames=1,
    )
    shared = set(per_layer["endo"]) & set(per_layer["epi"])
    assert shared
    segment = sorted(shared)[0]
    endo_peak = float(np.nanmin(per_layer["endo"][segment]))
    epi_peak = float(np.nanmin(per_layer["epi"][segment]))
    assert endo_peak < epi_peak < 0.0
