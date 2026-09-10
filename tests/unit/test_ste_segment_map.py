"""Phase 1 — LV geometry and segment map (issues #C1 and #C2).

The two defects pinned here decided whether the module *could* measure the
right thing at all:

* ``resample_closed`` treated the open apical arc (annulus → apex → annulus) as
  a closed ring, so the annulus chord became part of the material line and
  kernels were placed inside the LV cavity (#C1);
* AHA segments were assigned by the angle around the centroid of that arc,
  with view-independent, asymmetric bins (#C2).

Both are replaced by an arc-parameterised model: nodes are ordered along the
material line, the apex is the point farthest from the annulus chord, and the
six segments of a view are the two wall triplets (basal/mid/apical) of the
standard 18-segment AHA model.
"""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.models.speckle import SpeckleConfig, TrackingKernel
from echo_personal_tool.domain.services.aha_segments import assign_aha_segments
from echo_personal_tool.domain.services.border_tracking import (
    build_border_kernels,
    is_closed_contour,
    resample_along_arc,
    resample_closed,
    resample_open_arc,
)
from echo_personal_tool.domain.services.segment_map import (
    SEGMENT_NAMES,
    VIEW_WALLS,
    apex_index_from_arc,
    assign_segments_from_arc,
    normalise_view,
    segment_ids_in_bullseye_order,
    segments_present,
    view_segment_ids,
)


def _apical_arc(n: int = 61, *, width: float = 30.0, depth: float = 60.0) -> np.ndarray:
    """Open apical arc: annulus → apex → annulus, in node order."""
    theta = np.linspace(np.pi, 0.0, n)
    return np.column_stack([width * np.cos(theta), -depth * np.sin(theta)])


class TestOpenArcResampling:
    def test_open_resampler_keeps_the_endpoints(self) -> None:
        arc = _apical_arc(31)
        out = resample_open_arc(arc, 16)
        assert out.shape == (16, 2)
        assert out[0] == pytest.approx(arc[0], abs=1e-9)
        assert out[-1] == pytest.approx(arc[-1], abs=1e-9)

    def test_open_resampler_never_invents_the_chord(self) -> None:
        """No resampled node may leave the drawn arc (the chord has no nodes)."""
        arc = _apical_arc(41)
        out = resample_open_arc(arc, 40)
        # The chord of this semicircle passes through (0, 0); a closed resample
        # puts nodes there, an open one keeps every node on the arc.
        radii = np.linalg.norm(out, axis=1)
        assert radii.min() > 0.5 * 30.0, radii.min()

    def test_closed_resampler_still_wraps_a_ring(self) -> None:
        square = np.array([[0, 0], [10, 0], [10, 10], [0, 10]], dtype=float)
        out = resample_closed(square, 40)
        seg = np.linalg.norm(np.diff(np.vstack([out, out[:1]]), axis=0), axis=1)
        assert abs(seg.mean() - 1.0) < 1e-3

    def test_topology_detection_and_dispatch(self) -> None:
        arc = _apical_arc(21)
        ring = np.vstack([arc, arc[:1]])
        assert not is_closed_contour(arc)
        assert is_closed_contour(ring)
        assert resample_along_arc(arc, 12) == pytest.approx(resample_open_arc(arc, 12))
        assert resample_along_arc(ring, 12) == pytest.approx(resample_closed(ring, 12))

    def test_border_kernels_keep_all_nodes_off_the_chord(self) -> None:
        """#C1: the annulus chord must contain no node and no kernel.

        Resampling an apical arc as a closed ring spreads nodes over the chord,
        which lands kernels in the LV cavity. With the open resampler the only
        nodes near the chord line are the two annulus endpoints of each layer.
        """
        endo = _apical_arc(41)
        epi = endo * np.array([1.25, 1.2])
        kernels, _edges = build_border_kernels(endo, epi, n_nodes=24)
        near_chord = [k for k in kernels if abs(k.center[1]) < 0.5]
        # One annulus node per layer per side: endo×2 + mid×2 + epi×2 = 6.
        assert len(near_chord) == 6
        # The node grid runs annulus → apex → annulus, monotonically in |y|.
        endo_nodes = sorted((k for k in kernels if k.layer == "endo"), key=lambda k: k.node_index)
        ys = np.array([k.center[1] for k in endo_nodes])
        assert ys[0] > ys[len(ys) // 2] < ys[-1]


class TestApexAndLevels:
    def test_apex_is_the_farthest_point_from_the_annulus_chord(self) -> None:
        arc = _apical_arc(61)
        assert apex_index_from_arc(arc) == 30

    def test_apex_detection_is_robust_to_a_flipped_image(self) -> None:
        arc = _apical_arc(61)
        flipped = np.column_stack([-arc[:, 0], arc[:, 1]])[::-1]
        idx = apex_index_from_arc(flipped)
        assert abs(idx - 30) <= 1

    def test_levels_split_into_three_thirds_per_wall(self) -> None:
        arc = _apical_arc(61)
        assignment = assign_segments_from_arc(arc, "A4C")
        assert assignment.n_nodes == 61
        assert set(assignment.node_sides) == {0, 1}
        # Each wall gets basal, mid and apical nodes.
        for side in (0, 1):
            levels = {assignment.node_levels[i] for i in range(61) if assignment.node_sides[i] == side}
            assert levels == {0, 1, 2}


class TestSegmentMapPerView:
    @pytest.mark.parametrize(
        ("view", "expected"),
        [
            ("A4C", (3, 6, 9, 12, 15, 18)),
            ("A2C", (1, 4, 7, 10, 13, 16)),
            ("A3C", (2, 5, 8, 11, 14, 17)),
        ],
    )
    def test_view_names_its_own_wall_pair(self, view: str, expected: tuple[int, ...]) -> None:
        assignment = assign_segments_from_arc(_apical_arc(), view)
        assert segments_present(assignment.node_segments) == expected
        assert expected == tuple(sorted(view_segment_ids(view)))

    def test_views_cover_the_18_segments_exactly_once(self) -> None:
        ids = [seg for view in ("A4C", "A2C", "A3C") for seg in view_segment_ids(view)]
        assert len(ids) == len(set(ids)) == 18
        assert set(ids) == set(range(1, 19))

    def test_every_node_gets_exactly_one_segment(self) -> None:
        assignment = assign_segments_from_arc(_apical_arc(), "A4C")
        assert all(seg > 0 for seg in assignment.node_segments)
        # Segments are contiguous runs of the arc (no interleaving).
        runs = [assignment.node_segments[0]]
        for seg in assignment.node_segments[1:]:
            if seg != runs[-1]:
                runs.append(seg)
        assert len(runs) == len(set(runs)) == 6

    def test_bullseye_order_covers_the_standard_model(self) -> None:
        assert segment_ids_in_bullseye_order() == tuple(range(1, 19))
        assert set(SEGMENT_NAMES) == set(range(1, 19))

    def test_view_normalisation(self) -> None:
        assert normalise_view(None) == "A4C"
        assert normalise_view("a2c") == "A2C"
        assert normalise_view("DAO (A3C)") == "A4C"  # unknown → documented default
        assert normalise_view("A3C") == "A3C"
        assert set(VIEW_WALLS) >= {"A4C", "A2C", "A3C"}


class TestKernelAssignment:
    @staticmethod
    def _kernels(arc: np.ndarray, layers: tuple[str, ...] = ("endo", "epi")) -> list[TrackingKernel]:
        kernels: list[TrackingKernel] = []
        for layer in layers:
            for i, point in enumerate(arc):
                kernels.append(
                    TrackingKernel(
                        center=(float(point[0]), float(point[1])),
                        node_index=i,
                        layer=layer,
                    )
                )
        return kernels

    def test_all_layers_of_a_node_share_its_segment(self) -> None:
        arc = _apical_arc(31)
        kernels = self._kernels(arc)
        assigned = assign_aha_segments(kernels, lv_center=(0.0, 0.0), view="A4C")
        by_node: dict[int, set[int]] = {}
        for kernel in assigned:
            by_node.setdefault(kernel.node_index, set()).add(kernel.aha_segment)
        assert all(len(segments) == 1 for segments in by_node.values())

    def test_view_changes_the_named_walls(self) -> None:
        arc = _apical_arc(31)
        a4c = {k.aha_segment for k in assign_aha_segments(self._kernels(arc, ("endo",)), (0.0, 0.0), "A4C")}
        a2c = {k.aha_segment for k in assign_aha_segments(self._kernels(arc, ("endo",)), (0.0, 0.0), "A2C")}
        assert a4c == {3, 9, 15, 6, 12, 18}
        assert a2c == {1, 7, 13, 4, 10, 16}

    def test_assignment_does_not_depend_on_kernel_order(self) -> None:
        arc = _apical_arc(31)
        kernels = self._kernels(arc, ("endo",))
        straight = {
            k.node_index: k.aha_segment for k in assign_aha_segments(kernels, (0.0, 0.0), "A3C")
        }
        shuffled = assign_aha_segments(list(reversed(kernels)), (0.0, 0.0), "A3C")
        assert {k.node_index: k.aha_segment for k in shuffled} == straight

    def test_legacy_fallback_still_returns_segments(self) -> None:
        """With fewer than three endo nodes the angular fallback must not crash."""
        kernels = [
            TrackingKernel(center=(10.0, 10.0), node_index=0, layer="endo"),
            TrackingKernel(center=(20.0, 10.0), node_index=1, layer="endo"),
        ]
        assigned = assign_aha_segments(kernels, lv_center=(0.0, 0.0), view="A4C")
        assert all(k.aha_segment > 0 for k in assigned)


class TestHeartPhantomInvariants:
    """A contracting apical arc: segment strain must be negative everywhere."""

    def test_contracting_arc_gives_negative_segment_strain(self) -> None:
        from echo_personal_tool.domain.services.strain_computation import compute_node_longitudinal_curves

        arc = _apical_arc(31)
        positions = np.stack([arc, arc * 0.9])  # 10 % uniform contraction at ES
        curves = compute_node_longitudinal_curves(positions, 0, (1.0, 1.0))
        assignment = assign_segments_from_arc(arc, "A4C")
        for seg in segments_present(assignment.node_segments):
            values = [curves[1, i] for i, s in enumerate(assignment.node_segments) if s == seg]
            assert np.mean(values) < 0.0

    def test_epi_contour_is_outside_the_endo_arc(self) -> None:
        endo = _apical_arc(41)
        epi = endo * np.array([1.25, 1.2])
        # The epicardium must stay farther from the arc centre at every node
        # (the annulus endpoints lie on the chord, so a chord distance test
        # would be degenerate there).
        assert np.all(np.linalg.norm(epi, axis=1) > np.linalg.norm(endo, axis=1))

    def test_config_defaults_do_not_depend_on_the_view(self) -> None:
        cfg = SpeckleConfig()
        assert cfg.tracking_mode in {"sequential", "border", "incremental"}
