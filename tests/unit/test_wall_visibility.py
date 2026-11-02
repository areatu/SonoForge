"""Wall visibility: is the tissue under a tracked node in the image at all?

Clinical review Q4: when part of the wall leaves the sector, the tracker keeps
returning positions (it locks onto the edge of the data region, where a blank
patch can even score NCC 1.0), so the strain silently mixes measured and
unmeasured tissue. These tests pin the detector and the QC policy that keeps
such a view out of a "valid" reading.
"""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.services.quality import assess_tracking_quality
from echo_personal_tool.domain.services.wall_visibility import measure_wall_visibility

RADIUS = 6


def _textured_stack(n_frames: int = 10, size: int = 80, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return np.abs(rng.normal(120.0, 25.0, size=(n_frames, size, size)))


def _track(n_frames: int, nodes: list[tuple[float, float]]) -> np.ndarray:
    return np.tile(np.asarray(nodes, dtype=np.float64), (n_frames, 1, 1))


class TestMeasureWallVisibility:
    def test_tissue_inside_the_frame_is_fully_visible(self) -> None:
        frames = _textured_stack()
        visibility = measure_wall_visibility(frames, _track(frames.shape[0], [(40.0, 40.0), (45.0, 25.0)]))
        assert visibility.loss_fraction == 0.0
        assert visibility.visible_nodes().all()

    def test_blank_band_marks_the_nodes_over_it_lost(self) -> None:
        frames = _textured_stack()
        frames[:, 45:, :] = 0.0  # the apex leaves the sector from row 45 down
        visibility = measure_wall_visibility(
            frames,
            _track(frames.shape[0], [(40.0, 20.0), (40.0, 50.0)]),  # (x, y): visible / blank
        )
        assert visibility.node_loss[0] == 0.0
        assert visibility.node_loss[1] == pytest.approx(1.0)
        assert visibility.loss_fraction == pytest.approx(0.5)
        assert list(visibility.visible_nodes()) == [True, False]

    def test_kernel_leaving_the_frame_is_lost(self) -> None:
        frames = _textured_stack()
        visibility = measure_wall_visibility(
            frames,
            _track(frames.shape[0], [(40.0, 40.0), (40.0, RADIUS - 2)]),
        )
        assert visibility.node_loss[0] == 0.0
        assert visibility.node_loss[1] == pytest.approx(1.0)

    def test_nan_position_counts_as_not_visible(self) -> None:
        frames = _textured_stack()
        track = _track(frames.shape[0], [(40.0, 40.0)])
        track[0, 0, 1] = np.nan
        visibility = measure_wall_visibility(frames, track)
        assert visibility.node_loss[0] == pytest.approx(1.0 / frames.shape[0])
        assert visibility.visible_nodes().all()  # one frame of ten is below the limit
        assert not visibility.visible_nodes(max_loss=0.0)[0]

    def test_lost_speckle_is_detected_even_on_bright_pixels(self) -> None:
        """A flat bright area has no pattern: matching it is meaningless.

        This is the degenerate lock of ``cv2.matchTemplate``: a featureless
        template correlates at NCC 1.0 with any featureless region, so the
        tracker reports a confident match where there is nothing to measure.
        """
        frames = _textured_stack()
        frames[4:] = 200.0  # uniform, still above the data floor
        visibility = measure_wall_visibility(frames, _track(frames.shape[0], [(40.0, 40.0)]))
        assert visibility.node_loss[0] == pytest.approx(0.6)

    def test_empty_input_is_not_an_error(self) -> None:
        visibility = measure_wall_visibility(np.zeros((0, 40, 40)), np.zeros((0, 3, 2)))
        assert visibility.loss_fraction == 0.0
        assert visibility.visible_nodes().all()

    def test_shape_mismatch_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            measure_wall_visibility(np.zeros((4, 40, 40)), np.zeros((4, 3, 3)))


class TestVisibilityQualityPolicy:
    """Any exclusion has to be visible in the report; too much makes it invalid."""

    def _report(self, **kw):
        return assess_tracking_quality(
            has_curve=True,
            fidelity=0.9,
            coverage=1.0,
            interpolated_fraction=0.0,
            consistency_delta=0.0,
            physiology_ok=True,
            n_segments_measured=6,
            gls_pp=-19.0,
            **kw,
        )

    def test_fully_visible_wall_keeps_valid(self) -> None:
        report = self._report()
        assert report.status == "valid"
        assert "strain.qc.reason.edge_visibility" not in report.reasons

    def test_one_excluded_node_needs_review_and_is_stated(self) -> None:
        report = self._report(excluded_nodes=1, visibility_loss=0.02)
        assert report.status == "review"
        assert "strain.qc.reason.edge_visibility" in report.reasons
        assert any("no visible tissue" in note for note in report.notes)
        assert report.confidence <= 0.75

    def test_two_excluded_segments_are_invalid(self) -> None:
        """EACVI/ASE allow one excluded segment per view, not two."""
        report = self._report(excluded_segments=2, visibility_loss=0.05)
        assert report.status == "invalid"
        assert "strain.qc.reason.edge_visibility" in report.reasons

    def test_quarter_cycle_of_loss_is_invalid(self) -> None:
        report = self._report(visibility_loss=0.25)
        assert report.status == "invalid"
        assert "strain.qc.reason.edge_visibility" in report.reasons

    def test_loss_is_clamped_and_non_negative(self) -> None:
        report = self._report(visibility_loss=-0.5)
        assert report.status == "valid"
        assert report.visibility_loss == 0.0
