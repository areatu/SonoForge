"""Worker wiring of the layered strain (plan А.8, issue #646).

The worker stage `_run_layered_strain` reuses the tracking that already ran
(`state.smoothed`, the zone kernels, the NCC weights) and embeds the layer
curves full-length the same way the global curve is embedded. These tests
need PySide6 (QRunnable worker), so they stay out of the pure-core lane; the
domain itself is Qt-free and covered by ``test_layered_strain.py``.
"""

from __future__ import annotations

import types

import numpy as np
import pytest

pytestmark = pytest.mark.gui

N_NODES = 16
LAYERS_SCALE = {"endo": 40.0, "mid": 48.0, "epi": 56.0}


def _kernels() -> list:
    from echo_personal_tool.domain.models.speckle import TrackingKernel

    kernels: list[TrackingKernel] = []
    for layer, radius in LAYERS_SCALE.items():
        for i in range(N_NODES):
            angle = 2.0 * np.pi * i / N_NODES
            kernels.append(
                TrackingKernel(
                    center=(100.0 + radius * np.cos(angle), 150.0 + radius * np.sin(angle)),
                    radius=4,
                    node_index=i,
                    layer=layer,
                    aha_segment=(i % 6) + 1,
                )
            )
    return kernels


def _smoothed(kernels: list, frames: int = 25) -> np.ndarray:
    positions = np.zeros((frames, len(kernels), 2), dtype=np.float64)
    for layer, radius in LAYERS_SCALE.items():
        indices = [i for i, k in enumerate(kernels) if k.layer == layer]
        centres = np.array([kernels[i].center for i in indices])
        centroid = centres.mean(axis=0)
        target = {"endo": 0.80, "mid": 0.85, "epi": 0.90}[layer]
        for t in range(frames):
            scale = 1.0 + (target - 1.0) * min(t / 12, 1.0)
            positions[t, indices] = centroid + (centres - centroid) * scale
    return positions


class TestWorkerLayeredStage:
    def _run_stage(self, visible_nodes=None):
        from echo_personal_tool.application.workers.speckle_worker import SpeckleTrackingWorker
        from echo_personal_tool.domain.models.speckle import MyocardialZone, SpeckleConfig

        theta = np.linspace(0.0, 2.0 * np.pi, N_NODES)
        zone = MyocardialZone(
            endo_points=np.column_stack([100 + 40 * np.cos(theta), 150 + 40 * np.sin(theta)]),
            epi_points=np.column_stack([100 + 56 * np.cos(theta), 150 + 56 * np.sin(theta)]),
            thickness_mm=8.0,
            pixel_spacing=(0.5, 0.5),
        )
        worker = SpeckleTrackingWorker(
            frames=None,
            zone=zone,
            pixel_spacing=(0.5, 0.5),
        )
        kernels = _kernels()
        state = types.SimpleNamespace(
            smoothed=_smoothed(kernels),
            kernels=kernels,
            local_ed=0,
            local_es=12,
            n_frames=25,
            phase_start=0,
            phase_end=24,
            ed_ncc=np.ones(len(kernels)),
            visible_nodes=visible_nodes if visible_nodes is not None else np.ones(len(kernels), dtype=bool),
            strain_endo=[i for i, k in enumerate(kernels) if k.layer == "endo"],
            strain_endo_all=[i for i, k in enumerate(kernels) if k.layer == "endo"],
            config=SpeckleConfig.preset_standard(),
        )
        worker._run_layered_strain(state)
        return state, kernels

    def test_the_stage_produces_three_layers_with_a_positive_gradient(self) -> None:
        state, _kernels = self._run_stage()
        assert set(state.layer_curves) == {"endo", "mid", "epi"}
        assert set(state.layer_gls) == {"endo", "mid", "epi"}
        assert state.layer_gls["endo"] < state.layer_gls["epi"] < 0.0
        assert state.layer_gls["endo"] == pytest.approx(-20.0, abs=1.5)
        gradient = state.layer_gls["epi"] - state.layer_gls["endo"]
        assert gradient == pytest.approx(10.0, abs=1.5)
        for curve in state.layer_curves.values():
            assert curve.shape == (25,)

    def test_the_endo_layer_is_the_global_curve_bit_for_bit(self) -> None:
        """The reported GLS comes from the endo columns + the same weights —
        the layered stage must reproduce it exactly, not approximately."""
        from echo_personal_tool.domain.services.strain_computation import (
            compute_gls,
            compute_weighted_longitudinal_strain_gl,
        )

        state, kernels = self._run_stage()
        endo_cols = sorted((i for i, k in enumerate(kernels) if k.layer == "endo"), key=lambda i: kernels[i].node_index)
        window_long = compute_weighted_longitudinal_strain_gl(state.smoothed, 0, (0.5, 0.5), endo_cols, state.ed_ncc)
        assert state.layer_gls["endo"] == pytest.approx(compute_gls(window_long, 0, 12), abs=1e-9)
        # Embedded full-length on the state's time base (the whole 25-frame
        # run here): finite over the analysis window the worker declared.
        endo = state.layer_curves["endo"]
        assert endo.shape == (25,)
        assert np.isfinite(endo[0]) and np.isfinite(endo[12]) and np.isfinite(endo[24])

    def test_layer_segment_curves_are_embedded_full_length(self) -> None:
        state, _kernels = self._run_stage()
        assert set(state.layer_segment_curves) == {"endo", "mid", "epi"}
        for per_layer in state.layer_segment_curves.values():
            assert per_layer
            for curve in per_layer.values():
                assert curve.shape == (25,)

    def test_visibility_loss_of_a_whole_layer_falls_back_to_its_full_arc(self) -> None:
        """Uniform contraction measures the same strain on any sub-arc, so the
        observable difference here is the fallback rule: 4 visible mid nodes
        (< 8) must measure the layer on its full 16-node line again."""
        state, kernels = self._run_stage()
        visible = np.ones(len(kernels), dtype=bool)
        mid_cols = [i for i, k in enumerate(kernels) if k.layer == "mid"]
        for kernel_index in mid_cols[:12]:
            visible[kernel_index] = False
        state2, _ = self._run_stage(visible_nodes=visible)
        # The other layers are untouched by the mid layer's visibility loss.
        assert state2.layer_gls["endo"] == pytest.approx(state.layer_gls["endo"], abs=1e-9)
        assert state2.layer_gls["epi"] == pytest.approx(state.layer_gls["epi"], abs=1e-9)
        # And the mid layer fell back to its full arc — the unfiltered value.
        assert state2.layer_gls["mid"] == pytest.approx(state.layer_gls["mid"], abs=1e-9)

    def test_the_radial_fallback_drops_the_visibility_filter(self) -> None:
        """When _run_strain_curves reverted the endo arc to its full line, the
        layered curves must describe the same (unfiltered) measurement."""
        from echo_personal_tool.application.workers.speckle_worker import SpeckleTrackingWorker
        from echo_personal_tool.domain.models.speckle import MyocardialZone, SpeckleConfig

        state, kernels = self._run_stage()
        visible = np.ones(len(kernels), dtype=bool)
        mid_cols = [i for i, k in enumerate(kernels) if k.layer == "mid"]
        for kernel_index in mid_cols[:4]:
            visible[kernel_index] = False
        fallback_state = types.SimpleNamespace(
            smoothed=state.smoothed,
            kernels=kernels,
            local_ed=0,
            local_es=12,
            n_frames=25,
            phase_start=0,
            phase_end=24,
            ed_ncc=np.ones(len(kernels)),
            visible_nodes=visible,
            strain_endo=list(state.strain_endo_all),  # fallback in effect
            strain_endo_all=list(state.strain_endo_all),
            config=SpeckleConfig.preset_standard(),
        )
        theta = np.linspace(0.0, 2.0 * np.pi, N_NODES)
        zone = MyocardialZone(
            endo_points=np.column_stack([100 + 40 * np.cos(theta), 150 + 40 * np.sin(theta)]),
            epi_points=np.column_stack([100 + 56 * np.cos(theta), 150 + 56 * np.sin(theta)]),
            thickness_mm=8.0,
            pixel_spacing=(0.5, 0.5),
        )
        worker = SpeckleTrackingWorker(frames=None, zone=zone, pixel_spacing=(0.5, 0.5))
        worker._run_layered_strain(fallback_state)
        # The mid layer measured on its full line despite the 4 lost nodes —
        # the same measurement the reverted global curve describes.
        assert fallback_state.layer_gls["mid"] == pytest.approx(state.layer_gls["mid"], abs=1e-9)
