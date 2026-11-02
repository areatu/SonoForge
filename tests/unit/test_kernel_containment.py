"""Unit tests for radial wall-band containment of STE kernels (Phase 4a)."""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.models.speckle import TrackingKernel
from echo_personal_tool.domain.services.speckle_tracking import (
    clamp_kernels_to_wall_band,
    clamp_trajectories_to_wall,
)

pytestmark = pytest.mark.gui


def _synthetic_ring(n_cols: int = 8, *, r_endo: float = 20.0, thickness: float = 8.0, center=(100.0, 100.0)):
    cx, cy = center
    kernels: list[TrackingKernel] = []
    positions: list[np.ndarray] = []
    for i in range(n_cols):
        angle = 2.0 * np.pi * i / n_cols
        for t, layer in enumerate(("endo", "mid", "epi")):
            radius = r_endo + thickness * t / 2.0
            pos = np.array([cx + radius * np.cos(angle), cy + radius * np.sin(angle)])
            kernels.append(
                TrackingKernel(
                    center=(float(pos[0]), float(pos[1])),
                    node_index=i,
                    layer=layer,
                    radius=6,
                )
            )
            positions.append(pos)
    return kernels, np.asarray(positions, dtype=np.float64)


def test_ordered_positions_are_left_untouched() -> None:
    kernels, positions = _synthetic_ring()
    out, changed = clamp_kernels_to_wall_band(positions, kernels, positions)
    assert changed == 0
    np.testing.assert_allclose(out, positions, atol=1e-9)


def test_epicardium_pulled_back_inside_band() -> None:
    kernels, positions = _synthetic_ring()
    bad = positions.copy()
    # One epi kernel jumped far outward along its own ray (radial drift).
    c = np.array([100.0, 100.0])
    epi_id = next(i for i, k in enumerate(kernels) if k.layer == "epi" and k.node_index == 3)
    bad[epi_id] = c + (positions[epi_id] - c) * 4.0
    out, changed = clamp_kernels_to_wall_band(bad, kernels, positions)
    assert changed >= 1
    for i in range(0, len(kernels), 3):  # per column
        r_endo = np.linalg.norm(out[i] - c)
        r_mid = np.linalg.norm(out[i + 1] - c)
        r_epi = np.linalg.norm(out[i + 2] - c)
        assert r_endo < r_mid < r_epi, f"column {i // 3} order broken"


def test_inverted_layers_are_reordered() -> None:
    kernels, positions = _synthetic_ring()
    bad = positions.copy()
    # Column 5: endo and epi swap their radial positions.
    col = [i for i, k in enumerate(kernels) if k.node_index == 5]
    endo_id, epi_id = col[0], col[2]
    bad[endo_id], bad[epi_id] = bad[epi_id].copy(), bad[endo_id].copy()
    out, changed = clamp_kernels_to_wall_band(bad, kernels, positions)
    assert changed >= 1
    c = np.array([100.0, 100.0])
    col_pts = out[col]
    radii = np.linalg.norm(col_pts - c, axis=1)
    assert radii[0] < radii[1] < radii[2]


def test_sequential_loop_keeps_kernels_in_band(monkeypatch) -> None:
    from echo_personal_tool.domain.services import speckle_tracking as st

    kernels, ed_pos = _synthetic_ring(n_cols=6)
    frames = np.zeros((4, 220, 220), dtype=np.float32)

    def _fake_pair(ref, tgt, kernels_, config, zone_mask=None):
        from echo_personal_tool.domain.models.speckle import TrackingResult

        n = len(kernels_)
        pos = np.array([k.center for k in kernels_], dtype=np.float64)
        c = np.array([100.0, 100.0])
        epi_id = next(i for i, k in enumerate(kernels_) if k.layer == "epi" and k.node_index == 2)
        pos[epi_id] = c + (pos[epi_id] - c) * 5.0  # radial jump far outside the wall
        return TrackingResult(
            frame_index=0,
            displacements=np.zeros((n, 2)),
            ncc_scores=np.ones(n),
            valid_mask=np.ones(n, dtype=bool),
            kernel_positions=pos,
        )

    monkeypatch.setattr(st, "track_frame_pair", _fake_pair)
    config = st.SpeckleConfig(tracking_mode="sequential", bidirectional=False)
    results = st.track_cine_sequential(frames, kernels, ed_index=0, config=config)
    last = next(r for r in results if r.frame_index == 3).kernel_positions
    c = np.array([100.0, 100.0])
    for i in range(0, len(kernels), 3):
        radii = np.linalg.norm(last[i : i + 3] - c, axis=1)
        assert radii[0] < radii[1] < radii[2], f"column {i // 3} layer order inverted"
        assert radii[2] < 32.5, "epi kernel escaped the wall band"


def test_trajectory_clamp_preserves_ed_and_shape() -> None:
    kernels, ed_pos = _synthetic_ring(n_cols=6)
    traj = np.stack([ed_pos, ed_pos + 2.0, ed_pos.copy()])
    # Corrupt frame 1 heavily.
    traj[1] = traj[1] * 5.0
    out, total = clamp_trajectories_to_wall(traj, kernels, ed_index=0)
    assert out.shape == traj.shape
    assert total > 0
    # ED frame (index 0) must be preserved — already in-band.
    np.testing.assert_allclose(out[0], ed_pos, atol=1e-9)
