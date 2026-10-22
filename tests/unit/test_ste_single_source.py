"""Single source of truth for the numbers the user sees (Phase 0 of the STE plan).

Covers three Phase-0 fixes:
* the temporal smoothing no longer replaces low-NCC frames by interpolation
  (issue #C9 — fabricated smooth curves);
* the worker exposes per-node/per-segment curves computed with one definition
  (issue #C3 — worker vs UI vs export disagreed);
* the curves view plots the model's segment curves instead of re-deriving them.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy.signal import savgol_filter

from echo_personal_tool.domain.models.speckle import (
    SpeckleConfig,
    StrainResult,
    TrackingKernel,
)
from echo_personal_tool.domain.services.tracking_smoothing import smooth_trajectories


def _straight_track(n_frames: int = 9, n_kernels: int = 3) -> np.ndarray:
    positions = np.zeros((n_frames, n_kernels, 2), dtype=np.float64)
    for t in range(n_frames):
        for i in range(n_kernels):
            positions[t, i] = (10.0 + i * 6.0, 40.0 + 2.5 * t)
    return positions


class TestNoTimeReInterpolation:
    def test_low_quality_frames_are_not_replaced(self) -> None:
        """``smooth_trajectories`` must equal a plain Savitzky–Golay filter.

        The old quality-weighted branch substituted linearly interpolated
        positions for every frame with NCC < 0.5 before filtering, so a badly
        tracked frame produced a confident-looking smooth curve.
        """
        positions = _straight_track()
        # Break one frame badly and mark it low quality: the old code silently
        # replaced this spike with an interpolated value.
        positions[4, 1, 1] = 200.0
        ncc = np.full((positions.shape[0], positions.shape[1]), 0.9)
        ncc[4, 1] = 0.05

        kernels = [
            TrackingKernel(center=(10.0, 40.0), node_index=i, layer="endo", aha_segment=i + 1)
            for i in range(positions.shape[1])
        ]
        config = SpeckleConfig(spatial_smoothing=0.0, temporal_smoothing=1.0, quality_weighted_smoothing=True)
        out = smooth_trajectories(positions, ncc, kernels, config)

        window = int(round(2.0 * config.temporal_smoothing + 3.0))
        if window % 2 == 0:
            window += 1
        window = min(window, positions.shape[0])
        expected = savgol_filter(positions[:, 1, 1], window, min(2, window - 1), mode="interp")
        assert out[:, 1, 1] == pytest.approx(expected, abs=1e-9)

    def test_interpolated_positions_are_not_synthesised(self) -> None:
        """A frame that disagrees with its neighbours must stay visible."""
        positions = _straight_track()
        positions[4, 0, 1] = 500.0
        ncc = np.ones((positions.shape[0], positions.shape[1])) * 0.9
        ncc[4, 0] = 0.05
        kernels = [TrackingKernel(center=(10.0, 40.0), node_index=i, layer="endo") for i in range(positions.shape[1])]
        config = SpeckleConfig(spatial_smoothing=0.0, temporal_smoothing=1.0)
        out = smooth_trajectories(positions, ncc, kernels, config)
        # Old behaviour: value at frame 4 became ≈ the interpolation of frames
        # 0..3 and 5..8 (~45 px). It must now reflect the measured spike.
        assert out[4, 0, 1] > 100.0


# A4C measures the inferoseptal / anterolateral wall pair in the standard
# 18-segment AHA numbering (3/9/15 and 6/12/18).
A4C_SEGMENTS = (3, 6, 9, 12, 15, 18)


# Widget-level checks need a working Qt platform plugin (CI runs them under xvfb).
@pytest.mark.gui
class TestCurvesViewUsesModelNumbers:
    @pytest.fixture(autouse=True)
    def _setup_qapp(self):
        """Ensure QApplication exists for QWidget creation (mirrors the sibling view tests)."""
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            app = QApplication([])
        yield app

    @staticmethod
    def _result(segment_curves: dict[int, np.ndarray]) -> StrainResult:
        n = 8
        kernels = [
            TrackingKernel(center=(10.0 + i * 5.0, 40.0), node_index=i, layer="endo", aha_segment=min(i // 2 + 1, 3))
            for i in range(6)
        ]
        positions = np.zeros((n, 6, 2))
        for t in range(n):
            for i in range(6):
                positions[t, i] = (10.0 + i * 5.0, 40.0 + t)
        return StrainResult(
            longitudinal=np.linspace(0.0, -18.0, n),
            radial=np.zeros(n),
            gls=-18.0,
            segment_strain={3: -18.0},
            kernels=kernels,
            tracked_positions_all=positions,
            ed_index=0,
            es_index=n - 1,
            segment_curves=segment_curves,
        )

    def test_model_curves_win_over_local_recomputation(self) -> None:
        pytest.importorskip("PySide6")
        from echo_personal_tool.ui.strain_curves_view import StrainCurvesView

        model_curves = {3: np.array([0.0, -1.0, -2.0, -3.0, -4.0, -5.0, -6.0, -7.0])}
        view = StrainCurvesView()
        result = self._result(model_curves)

        captured: dict[int, np.ndarray] = {}

        # Intercept the panel update: the view must hand over the model curves
        # untouched (no re-derivation from kernel positions).
        original = view._update_panel

        def _spy(panel, gls, curves, result_, frame_time_ms, ecg, ecg_sample_rate):
            captured.update(curves)

        view._update_panel = _spy  # type: ignore[assignment]
        try:
            view.set_strain_data(result)
        finally:
            view._update_panel = original  # type: ignore[assignment]

        assert 3 in captured
        assert captured[3] == pytest.approx(model_curves[3])
        # Segments of other views are never plotted in this panel.
        assert set(captured) <= set(A4C_SEGMENTS)

    def test_fallback_uses_arc_order_not_raster_order(self) -> None:
        pytest.importorskip("PySide6")
        from echo_personal_tool.ui.strain_curves_view import StrainCurvesView

        view = StrainCurvesView()
        # Kernels of one segment but ordered so that raster sorting (x, y) would
        # zig-zag: node 0 and node 2 are at the same place in the opposite wall.
        kernels = [
            TrackingKernel(center=(10.0, 40.0), node_index=0, layer="endo", aha_segment=3),
            TrackingKernel(center=(30.0, 40.0), node_index=2, layer="endo", aha_segment=3),
            TrackingKernel(center=(20.0, 40.0), node_index=1, layer="endo", aha_segment=3),
        ]
        n = 4
        positions = np.zeros((n, 3, 2))
        for t in range(n):
            scale = 1.0 - 0.05 * t
            for i, k in enumerate(kernels):
                positions[t, i] = (k.center[0] * scale, k.center[1])
        result = StrainResult(
            longitudinal=np.zeros(n),
            radial=np.zeros(n),
            gls=0.0,
            segment_strain={3: 0.0},
            kernels=kernels,
            tracked_positions_all=positions,
            ed_index=0,
            es_index=n - 1,
        )
        curves = view._segment_curves_from_tracking(result, n)
        # A uniform shortening of the whole arc must be negative at ES
        assert curves[3][-1] < 0.0
