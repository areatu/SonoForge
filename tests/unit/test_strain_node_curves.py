"""Per-node and per-segment strain curves — the single strain definition (issue #C3).

The old code computed one strain value per *pair* of neighbouring kernels and
assigned it to both kernels, so two neighbours always shared a number and a
kernel never owned its own deformation. These tests pin the corrected model:
each node carries the clinical (Lagrange) strain of the sub-arc through it and
its neighbours, and segment curves are a same-frame weighted mean of node curves.

Definition note: strain is ``(L − L₀)/L₀ · 100 %`` — the convention of the
EACVI/ASE consensus and of the vendor packages. The older Green–Lagrange form
``0.5·((L/L₀)² − 1)·100`` understates |ε| (a 20 % shortening read as −18 %), so
the expected values below are *not* the previous ones.
"""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.services.strain_computation import (
    aggregate_segment_curves,
    compute_node_longitudinal_curves,
    global_curve_from_node_curves,
    peak_in_window,
)


def _positions(factors: list[float], *, base_step: float = 10.0) -> np.ndarray:
    """Straight line of nodes scaled by ``factor`` in every frame."""
    n_frames = len(factors)
    n_nodes = 5
    pts = np.zeros((n_frames, n_nodes, 2), dtype=np.float64)
    for t, factor in enumerate(factors):
        pts[t, :, 0] = np.arange(n_nodes) * base_step * factor
    return pts


class TestComputeNodeLongitudinalCurves:
    def test_uniform_shortening_is_identical_at_every_node(self) -> None:
        curves = compute_node_longitudinal_curves(_positions([1.0, 0.9, 0.8]), 0, (1.0, 1.0))
        assert curves[0] == pytest.approx(0.0, abs=1e-9)
        # 3-node sub-arc scales as the factor itself → (f - 1)*100
        assert curves[2] == pytest.approx((0.8 - 1.0) * 100.0, abs=1e-6)

    def test_each_node_owns_its_own_value(self) -> None:
        """The old pairwise formula gave nodes 1..3 the same number.

        ``target_length_mm=0`` asks for the minimal window (one neighbour on each
        side), which is the pure "own value" case; the pipeline default asks for
        a physical 10 mm baseline instead, see the two tests below.
        """
        ed = np.array([[0.0, 0.0], [10.0, 0.0], [20.0, 0.0], [30.0, 0.0]])
        es = np.array([[0.0, 0.0], [10.0, 0.0], [15.0, 0.0], [20.0, 0.0]])
        positions = np.stack([ed, es])
        curves = compute_node_longitudinal_curves(positions, 0, (1.0, 1.0), target_length_mm=0.0)
        # node 0: two-point segment (10 → 10 px), nodes 1-3: sub-arcs through
        # the moved node, node 1 → (10+5)/20 - 1 = -25 %, nodes 2-3 → -50 %.
        assert curves[1] == pytest.approx([0.0, -25.0, -50.0, -50.0], abs=1e-6)
        # neighbours no longer share a value: node 1 differs from node 2
        assert curves[1, 1] != pytest.approx(curves[1, 2])

    def test_material_window_has_a_physical_length(self) -> None:
        """The default baseline is a physical length, not a number of nodes.

        Kernels are spaced by index: near the annulus neighbours sit ~1.5 mm
        apart, so a one-neighbour baseline measures a 3 mm stretch where
        sub-pixel tracking noise reads as several percent of strain. The window
        grows to ``target_length_mm`` at ED and stays fixed for every frame.
        """
        positions = _positions([1.0, 0.9], base_step=1.0)  # 1 mm node spacing
        short = compute_node_longitudinal_curves(positions, 0, (1.0, 1.0), target_length_mm=0.0)
        long = compute_node_longitudinal_curves(positions, 0, (1.0, 1.0), target_length_mm=10.0)
        # Uniform shortening is scale-invariant, so both read -10 %: the values
        # must not depend on the window length ...
        assert short[1] == pytest.approx(-10.0, abs=1e-6)
        assert long[1] == pytest.approx(-10.0, abs=1e-6)
        # ... but the *sensitivity* to a jittered neighbour must drop with it.
        jittered = positions.copy()
        jittered[1, 1, 1] += 0.5  # half a pixel across the line, on one node
        short_j = compute_node_longitudinal_curves(jittered, 0, (1.0, 1.0), target_length_mm=0.0)
        long_j = compute_node_longitudinal_curves(jittered, 0, (1.0, 1.0), target_length_mm=10.0)
        short_sensitivity = abs(short_j[1, 1] - short[1, 1])
        long_sensitivity = abs(long_j[1, 1] - long[1, 1])
        assert short_sensitivity > 0.0
        assert long_sensitivity < short_sensitivity / 1.8

    def test_window_is_fixed_at_ed_and_covers_the_same_material(self) -> None:
        """A longer target never re-windows per frame (that would fake strain)."""
        positions = _positions([1.0, 0.9, 0.8])
        curves = compute_node_longitudinal_curves(positions, 0, (1.0, 1.0), target_length_mm=25.0)
        assert curves[1] == pytest.approx(-10.0, abs=1e-6)
        assert curves[2] == pytest.approx(-20.0, abs=1e-6)

    def test_endpoints_use_the_two_point_segment(self) -> None:
        positions = _positions([1.0, 0.5])
        curves = compute_node_longitudinal_curves(positions, 0, (1.0, 1.0))
        # Endpoint nodes only see one neighbour pair → (0.5 - 1)*100
        assert curves[1, 0] == pytest.approx(-50.0, abs=1e-6)
        assert curves[1, 0] == pytest.approx(curves[1, -1], abs=1e-6)

    def test_pixel_spacing_scales_out(self) -> None:
        a = compute_node_longitudinal_curves(_positions([1.0, 0.8]), 0, (1.0, 1.0))
        b = compute_node_longitudinal_curves(_positions([1.0, 0.8]), 0, (0.45, 0.45))
        assert a == pytest.approx(b, abs=1e-9)

    def test_nan_positions_stay_nan_and_do_not_spread_into_strain(self) -> None:
        positions = _positions([1.0, 0.9, 0.8])
        positions[1, 2, :] = np.nan
        curves = compute_node_longitudinal_curves(positions, 0, (1.0, 1.0))
        frame = curves[1]
        assert np.isfinite(frame[0]) and np.isfinite(frame[1])
        # The lost node itself cannot be measured ...
        assert not np.isfinite(frame[2])
        # ... while the ED frame is still the (finite) reference for every node.
        assert curves[0] == pytest.approx(0.0, abs=1e-9)

    def test_zero_length_reference_is_nan(self) -> None:
        positions = np.zeros((2, 4, 2))
        curves = compute_node_longitudinal_curves(positions, 0, (1.0, 1.0))
        assert np.all(np.isnan(curves))

    def test_invalid_input_shape(self) -> None:
        with pytest.raises(ValueError):
            compute_node_longitudinal_curves(np.zeros((3, 4)), 0, (1.0, 1.0))


class TestSegmentAggregation:
    def test_same_frame_mean_and_not_peak_average(self) -> None:
        """Peaks of different segments happen at different instants (ESS vs GLS).

        Node 0 shortens early, node 1 late. Both definitions of the *peak*
        exist in the literature, but the EACVI/ASE global strain is read from
        the curve that is averaged **in the same frame**: it peaks at -20 %,
        never at the -40 % that averaging per-segment peaks would give.
        """
        curves = np.array(
            [
                [0.0, 0.0],  # ED reference
                [-40.0, 0.0],
                [0.0, 0.0],
                [0.0, -40.0],
            ]
        )
        segments = aggregate_segment_curves(curves, [1, 2])
        assert segments[1] == pytest.approx([0.0, -40.0, 0.0, 0.0])
        assert segments[2] == pytest.approx([0.0, 0.0, 0.0, -40.0])
        mean_of_peaks = (abs(peak_in_window(segments[1], 0, 3)) + abs(peak_in_window(segments[2], 0, 3))) / 2.0
        assert mean_of_peaks == pytest.approx(40.0)

        global_curve = global_curve_from_node_curves(curves)
        assert global_curve == pytest.approx([0.0, -20.0, 0.0, -20.0])
        assert peak_in_window(global_curve, 0, 3) == pytest.approx(-20.0)

    def test_constant_node_curves_stay_flat(self) -> None:
        curves = np.array([[0.0, 0.0], [-30.0, -30.0], [-20.0, -40.0]])
        combined = aggregate_segment_curves(curves, [1, 1])
        assert combined[1] == pytest.approx([0.0, -30.0, -30.0])

    def test_weights_and_missing_nodes(self) -> None:
        curves = np.array([[-10.0, -30.0, np.nan]])
        weighted = aggregate_segment_curves(curves, [1, 1, 1], node_weights=np.array([3.0, 1.0, 1.0]))
        assert weighted[1][0] == pytest.approx(-15.0)
        all_nan = aggregate_segment_curves(np.array([[np.nan, np.nan]]), [1, 1])
        assert np.isnan(all_nan[1][0])

    def test_unassigned_nodes_are_skipped(self) -> None:
        curves = np.array([[-10.0, -30.0]])
        assert aggregate_segment_curves(curves, [0, 2]).keys() == {2}

    def test_length_mismatch_raises(self) -> None:
        with pytest.raises(ValueError):
            aggregate_segment_curves(np.zeros((2, 3)), [1, 2])


class TestGlobalCurveFromNodes:
    def test_matches_node_mean(self) -> None:
        curves = np.array([[0.0, 0.0, 0.0], [-10.0, -20.0, -30.0]])
        out = global_curve_from_node_curves(curves)
        assert out == pytest.approx([0.0, -20.0])

    def test_matches_arc_length_definition_for_equispaced_nodes(self) -> None:
        """Definitions (A) total arc length and (B) node mean must agree.

        With the clinical (Lagrange) definition the two agree exactly for a
        *uniform* scaling — the case the consistency metric in the worker is
        gated on (§7.2.3). A non-uniform deformation makes them differ by
        design, and that difference is reported instead of hidden.
        """
        positions = _positions([1.0, 0.9, 0.8])
        node_curves = compute_node_longitudinal_curves(positions, 0, (1.0, 1.0))
        definition_b = global_curve_from_node_curves(node_curves)
        ed_pts = positions[0]
        l0 = float(np.sum(np.linalg.norm(np.diff(ed_pts, axis=0), axis=1)))
        manual_a = []
        for frame in positions:
            length = float(np.sum(np.linalg.norm(np.diff(frame, axis=0), axis=1)))
            manual_a.append((length / l0 - 1.0) * 100.0)
        assert definition_b == pytest.approx(manual_a, abs=1e-6)

    def test_definitions_differ_for_a_local_deformation(self) -> None:
        """A local bend moves the two definitions apart (non-zero consistency delta).

        They are equal for a uniform scaling only; the worker reports the
        difference as a self-consistency metric instead of hiding it.
        """
        ed = np.array([[0.0, 0.0], [10.0, 0.0], [20.0, 0.0], [30.0, 0.0], [40.0, 0.0]])
        es = np.array([[0.0, 0.0], [10.0, 6.0], [20.0, 8.0], [30.0, 6.0], [40.0, 0.0]])
        positions = np.stack([ed, es])
        node_curves = compute_node_longitudinal_curves(positions, 0, (1.0, 1.0))
        definition_b = float(global_curve_from_node_curves(node_curves)[1])
        l0 = float(np.sum(np.linalg.norm(np.diff(ed, axis=0), axis=1)))
        l1 = float(np.sum(np.linalg.norm(np.diff(es, axis=0), axis=1)))
        definition_a = (l1 / l0 - 1.0) * 100.0
        assert definition_a == pytest.approx(9.31, abs=0.05)
        assert definition_b == pytest.approx(10.75, abs=0.05)
        assert abs(definition_b - definition_a) > 1.0


class TestPeakInWindow:
    def test_ignores_nan_and_empty(self) -> None:
        curve = np.array([np.nan, -5.0, np.nan, -12.0, 3.0])
        assert peak_in_window(curve, 0, 4) == pytest.approx(-12.0)
        assert peak_in_window(np.array([np.nan, np.nan]), 0, 1) == 0.0
        assert peak_in_window(np.array([]), 0, 3) == 0.0

    def test_window_is_clipped_to_the_curve(self) -> None:
        curve = np.array([-1.0, -9.0, -2.0])
        assert peak_in_window(curve, -5, 99) == pytest.approx(-9.0)
        # boundaries may be given in either order → the window is 1..2
        assert peak_in_window(curve, 2, 1) == pytest.approx(-9.0)
        assert peak_in_window(curve, 5, 7) == pytest.approx(-2.0)  # clipped to the last frame
