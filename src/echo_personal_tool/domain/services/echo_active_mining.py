"""Deterministic review ranking; no labels, data selection for training or I/O."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from echo_personal_tool.domain.services.echo_ssl_objectives import warp_consistency_loss


@dataclass(frozen=True)
class ClipUncertainty:
    clip_index: int
    prototype_distance: float
    warp_disagreement: float | None
    valid_warp_nodes: int


@dataclass(frozen=True)
class RankedClip:
    clip_index: int
    score: float
    prototype_distance: float
    warp_disagreement: float | None
    valid_warp_nodes: int


def prototype_distance(cosines: np.ndarray) -> float:
    values = np.asarray(cosines, float)
    if values.ndim == 1:
        values = values[None, :]
    if values.ndim != 2 or min(values.shape) < 1 or not np.isfinite(values).all() or np.any(np.abs(values) > 1.0001):
        raise ValueError("invalid view prototype evidence")
    return float((1.0 - np.clip(values.mean(axis=0).max(), -1, 1)) / 2.0)


def normalized_warp_disagreement(
    predicted_next: np.ndarray,
    warped_previous: np.ndarray,
    weights: np.ndarray,
    *,
    image_diagonal: float,
) -> float | None:
    if not np.isfinite(image_diagonal) or image_diagonal <= 0:
        raise ValueError("invalid image scale")
    error = warp_consistency_loss(predicted_next, warped_previous, weights)
    if np.count_nonzero(np.asarray(weights) > 0) < 3:
        return None
    return error / image_diagonal


def rank_uncertain_clips(
    evidence: Sequence[ClipUncertainty],
    *,
    top_k: int = 10,
    ood_weight: float = 0.5,
    warp_weight: float = 0.5,
    warp_scale: float = 0.02,
) -> tuple[RankedClip, ...]:
    """Sort descending uncertainty, tie by original explicit manifest row.

    Missing NCC evidence stays None, NOT a claim of consistency. Such clips
    have only an OOD contribution and retain their missing-evidence flag.
    No arbitrary source filename, patient UID or seed enters the score.
    """
    if (
        not 1 <= top_k <= 1024
        or not np.isfinite([ood_weight, warp_weight, warp_scale]).all()
        or min(ood_weight, warp_weight) < 0
        or ood_weight + warp_weight <= 0
        or warp_scale <= 0
        or len(evidence) > 4096
        or len({e.clip_index for e in evidence}) != len(evidence)
    ):
        raise ValueError("invalid mining configuration")
    result = []
    for item in evidence:
        if (
            item.clip_index < 0
            or item.valid_warp_nodes < 0
            or not np.isfinite(item.prototype_distance)
            or not 0 <= item.prototype_distance <= 1
        ):
            raise ValueError("invalid clip uncertainty")
        warp = item.warp_disagreement
        if warp is not None and (not np.isfinite(warp) or warp < 0 or item.valid_warp_nodes < 3):
            raise ValueError("invalid observed warp disagreement")
        score = ood_weight * item.prototype_distance
        if warp is not None:
            score += warp_weight * min(warp / warp_scale, 1.0)
        score /= ood_weight + warp_weight
        result.append(RankedClip(item.clip_index, score, item.prototype_distance, warp, item.valid_warp_nodes))
    return tuple(sorted(result, key=lambda r: (-r.score, r.clip_index))[:top_k])
