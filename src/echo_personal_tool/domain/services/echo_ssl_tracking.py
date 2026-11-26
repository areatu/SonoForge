"""Memory-only NCC/round-trip pseudo-target adapter over the existing domain tracker."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from echo_personal_tool.domain.models.speckle import SpeckleConfig, TrackingKernel
from echo_personal_tool.domain.services.echo_ssl_objectives import ncc_weights
from echo_personal_tool.domain.services.speckle_tracking import track_frame_pair


@dataclass(frozen=True)
class SSLWarp:
    positions: np.ndarray
    weights: np.ndarray
    closure_error: np.ndarray


def _patch_supported(frame: np.ndarray, point: np.ndarray, mask: np.ndarray, half: int) -> bool:
    if not np.isfinite(point).all():
        return False
    x, y = np.rint(point).astype(int)
    h, w = frame.shape
    if x < half or y < half or x + half >= w or y + half >= h:
        return False
    patch = frame[y - half : y + half + 1, x - half : x + half + 1]
    return bool(mask[y - half : y + half + 1, x - half : x + half + 1].all() and float(np.std(patch)) > 1e-6)


def track_ssl_nodes(
    reference: np.ndarray,
    target: np.ndarray,
    points: np.ndarray,
    *,
    reference_sector: np.ndarray | None = None,
    target_sector: np.ndarray | None = None,
    max_closure_px: float = 1.5,
) -> SSLWarp:
    """NCC >= .65 BOTH ways, round-trip <=1.5px, nonflat complete kernels.

    No spatial/temporal smoothing or synthetic physiological motion is applied
    to the pseudo-label. Invalid/black/dropout/outside-sector nodes get weight 0.
    Arrays must already have ECG/overlays suppressed by the caller.
    """
    source, destination, nodes = np.asarray(reference, float), np.asarray(target, float), np.asarray(points, float)
    if (
        source.ndim != 2
        or source.shape != destination.shape
        or min(source.shape) < 16
        or not np.isfinite(source).all()
        or not np.isfinite(destination).all()
        or nodes.ndim != 2
        or nodes.shape[1:] != (2,)
    ):
        raise ValueError("invalid SSL tracking inputs")
    masks = [
        np.ones(source.shape, bool) if m is None else np.asarray(m, bool) for m in (reference_sector, target_sector)
    ]
    if any(m.shape != source.shape for m in masks):
        raise ValueError("invalid SSL tracking sector")
    positions, weights, closure = nodes.copy(), np.zeros(len(nodes)), np.full(len(nodes), np.nan)
    ids = [i for i, p in enumerate(nodes) if _patch_supported(source, p, masks[0], 4)]
    if not ids:
        return SSLWarp(positions, weights, closure)
    config = SpeckleConfig(
        kernel_size=8, search_radius=5, pyramid_levels=2, ncc_threshold=0.65, outlier_sigma=0, subpixel=True
    )
    kernels = [TrackingKernel(tuple(nodes[i]), radius=4, node_index=i) for i in ids]
    forward = track_frame_pair(source, destination, kernels, config)
    reverse_kernels = [TrackingKernel(tuple(p), radius=4, node_index=i) for i, p in zip(ids, forward.kernel_positions)]
    backward = track_frame_pair(destination, source, reverse_kernels, config)
    errors = np.linalg.norm(backward.kernel_positions - nodes[ids], axis=-1)
    scores = np.minimum(forward.ncc_scores, backward.ncc_scores)
    quality = ncc_weights(scores, errors, max_closure_px=max_closure_px)
    supported = np.array([_patch_supported(destination, p, masks[1], 4) for p in forward.kernel_positions])
    quality *= supported & forward.valid_mask & backward.valid_mask
    positions[ids], weights[ids], closure[ids] = forward.kernel_positions, quality, errors
    return SSLWarp(positions, weights, closure)
