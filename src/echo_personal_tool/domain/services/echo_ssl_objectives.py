"""Pure NumPy ML.4 objectives and fail-safe gates. No training runtime or I/O.

Phase is ventricular: LA reservoir grows towards ventricular ES. These are
soft learning priors, never clinical measurements or a diagnosis of normality.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from echo_personal_tool.domain.services.phase_field import PhaseField

MIN_NCC = 0.65
MIN_PHASE_CONFIDENCE = 0.6


@dataclass(frozen=True)
class SSLCycle:
    ed: int
    es: int
    end: int


def trusted_cycles(field: PhaseField) -> tuple[SSLCycle, ...]:
    """No extrapolated/partial beats, invalid phi or low-confidence physiology."""
    if not np.isfinite(field.confidence) or not MIN_PHASE_CONFIDENCE <= field.confidence <= 1:
        return ()
    phi = np.asarray(field.phi)
    if phi.shape != (field.n_frames,) or not np.isfinite(phi).all() or np.any((phi < 0) | (phi >= 1)):
        return ()
    result = []
    for cycle in field.cycles:
        a, b, c = cycle.ed_frame, cycle.es_frame, cycle.end_frame
        if (
            cycle.partial
            or not np.isfinite(cycle.confidence)
            or not MIN_PHASE_CONFIDENCE <= cycle.confidence <= 1
            or not 0 <= a < b < c <= field.n_frames
            or abs(float(phi[a])) > 1e-5
            or phi[b] <= 0
            or np.any(np.diff(phi[a:c]) < -1e-6)
        ):
            continue
        result.append(SSLCycle(a, b, c))
    return tuple(result)


def cycle_triplets(field: PhaseField) -> tuple[tuple[int, int, int], ...]:
    return tuple((c.ed, (c.ed + c.es) // 2, c.es) for c in trusted_cycles(field) if c.es - c.ed >= 2)


def phase_shape_weights(field: PhaseField) -> np.ndarray | None:
    """Continuous ED->ES->ED interpolation, only inside measured trusted cycles.

    NaN outside a trusted complete cycle: caller must use a stated alternative,
    not treat missing phase as measured ED. End-systole is not assumed to be 0.5.
    """
    cycles = trusted_cycles(field)
    if not cycles:
        return None
    weights = np.full(field.n_frames, np.nan)
    for c in cycles:
        weights[c.ed : c.es + 1] = np.linspace(0, 1, c.es - c.ed + 1)
        weights[c.es : c.end] = 1 - np.arange(c.end - c.es) / (c.end - c.es)
    return weights


def ncc_weights(ncc: np.ndarray, closure_error: np.ndarray, *, max_closure_px: float = 1.5) -> np.ndarray:
    scores, closure = np.asarray(ncc, float), np.asarray(closure_error, float)
    if scores.shape != closure.shape or not np.isfinite(max_closure_px) or max_closure_px <= 0:
        raise ValueError("invalid warp quality contract")
    valid = (
        np.isfinite(scores)
        & np.isfinite(closure)
        & (scores >= MIN_NCC)
        & (scores <= 1)
        & (closure >= 0)
        & (closure <= max_closure_px)
    )
    return np.where(valid, scores, 0.0)


def warp_consistency_loss(predicted: np.ndarray, warped: np.ndarray, weights: np.ndarray) -> float:
    p, t, w = np.asarray(predicted, float), np.asarray(warped, float), np.asarray(weights, float)
    if p.shape != t.shape or p.shape[-1:] != (2,) or w.shape != p.shape[:-1]:
        raise ValueError("incompatible warp arrays")
    if not np.isfinite(w).all() or np.any((w < 0) | (w > 1)):
        raise ValueError("invalid warp weights")
    use = w > 0
    if not use.any():
        return 0.0
    if not np.isfinite(p[use]).all() or not np.isfinite(t[use]).all():
        raise ValueError("nonfinite observed warp")
    return float(np.sum(np.linalg.norm(p[use] - t[use], axis=-1) * w[use]) / w[use].sum())


def physiology_terms(
    areas: Mapping[str, np.ndarray],
    field: PhaseField,
    *,
    landmarks: np.ndarray | None = None,
    max_speed_per_s: float = 3.0,
    max_acceleration_per_s2: float = 30.0,
) -> dict[str, float]:
    """Dimensionless area priors and normalized-coordinate kinematic bounds.

    Low-confidence phase makes ALL terms exactly zero, including landmarks.
    No assumed fps. Missing timestamps disable only the kinematic term.
    """
    terms = {"ventricles": 0.0, "la_reservoir": 0.0, "landmark_motion": 0.0}
    cycles = trusted_cycles(field)
    if not cycles:
        return terms
    for chamber, curve in areas.items():
        if chamber not in {"LV", "RV", "LA"}:
            raise ValueError("unsupported SSL chamber")
        values = np.asarray(curve, float)
        if values.shape != (field.n_frames,) or not np.isfinite(values).all() or np.any(values <= 0):
            raise ValueError("invalid area curve")
        for c in cycles:
            segment = values[c.ed : c.end]
            normalized = segment / max(float(segment.mean()), 1e-8)
            # Negating LA turns its reservoir expansion into ventricular contraction.
            signed = -normalized if chamber == "LA" else normalized
            es = c.es - c.ed
            order = max(0.0, 0.01 - (signed[0] - signed[es]))
            extrema = float(np.maximum(signed - signed[0], 0).mean() + np.maximum(signed[es] - signed, 0).mean())
            monotonic = float(np.maximum(np.diff(signed[: es + 1]), 0).mean())
            terms["la_reservoir" if chamber == "LA" else "ventricles"] += (order + extrema + monotonic) / len(cycles)
    if (
        landmarks is not None
        and field.frame_time_ms is not None
        and np.isfinite(field.frame_time_ms)
        and field.frame_time_ms > 0
    ):
        points = np.asarray(landmarks, float)
        if (
            points.ndim != 3
            or points.shape[0] != field.n_frames
            or points.shape[-1] != 2
            or not np.isfinite(points).all()
            or not np.isfinite([max_speed_per_s, max_acceleration_per_s2]).all()
            or min(max_speed_per_s, max_acceleration_per_s2) <= 0
        ):
            raise ValueError("invalid landmark motion")
        dt = field.frame_time_ms / 1000
        for c in cycles:
            segment = points[c.ed : c.end]
            speed = np.linalg.norm(np.diff(segment, axis=0), axis=-1) / dt
            accel = np.linalg.norm(np.diff(segment, n=2, axis=0), axis=-1) / dt**2
            penalty = float(np.maximum(speed / max_speed_per_s - 1, 0).mean())
            if accel.size:
                penalty += float(np.maximum(accel / max_acceleration_per_s2 - 1, 0).mean())
                penalty += 0.01 * float(np.mean((accel / max_acceleration_per_s2) ** 2))
            terms["landmark_motion"] += penalty / len(cycles)
    return terms


def cycle_view_loss(first: np.ndarray, second: np.ndarray) -> float:
    """Positive-pair cosine loss in prototype space; needs teacher/gold anti-collapse anchor."""
    a, b = np.asarray(first, float), np.asarray(second, float)
    if a.shape != b.shape or a.ndim != 2 or not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError("invalid cycle prototypes")
    if len(a) == 0:
        return 0.0
    na, nb = np.linalg.norm(a, axis=-1), np.linalg.norm(b, axis=-1)
    if np.any(na < 1e-8) or np.any(nb < 1e-8):
        raise ValueError("degenerate cycle prototypes")
    return float(np.mean(1 - np.clip(np.sum(a * b, axis=-1) / (na * nb), -1, 1)))


def candidate_reject_reasons(
    jitter_before: Mapping[str, float | None],
    jitter_after: Mapping[str, float | None],
    gold_before: Mapping[str, float],
    gold_after: Mapping[str, float],
    *,
    minimum_improvement: float = 0.01,
) -> tuple[str, ...]:
    """Fail closed: both LA/RV need held-out motion evidence and unchanged gold coverage.

    Gold keys are per-chamber IoU plus node_error; no missing chamber can be
    hidden by a better aggregate. No degradation except 1e-9 numerical noise.
    """
    if not 0 < minimum_improvement < 1:
        raise ValueError("invalid improvement gate")
    reasons = []
    for chamber in ("LA", "RV"):
        before, after = jitter_before.get(chamber), jitter_after.get(chamber)
        if before is None or after is None or not np.isfinite([before, after]).all() or before <= 0 or after < 0:
            reasons.append(f"missing_{chamber.lower()}_jitter")
        elif after > before * (1 - minimum_improvement):
            reasons.append(f"{chamber.lower()}_jitter_not_improved")
    required = {"LV_iou", "LA_iou", "RV_iou", "node_error_px", "frames"}
    if not required <= gold_before.keys() or gold_before.keys() != gold_after.keys():
        reasons.append("incomplete_gold")
    elif (
        not all(np.isfinite(v) for v in (*gold_before.values(), *gold_after.values()))
        or gold_before["frames"] <= 0
        or gold_after["frames"] != gold_before["frames"]
    ):
        reasons.append("invalid_gold_coverage")
    else:
        for key in ("LV_iou", "LA_iou", "RV_iou"):
            if (
                not 0 <= gold_after[key] <= 1
                or not 0 <= gold_before[key] <= 1
                or gold_after[key] < gold_before[key] - 1e-9
            ):
                reasons.append(f"{key.lower()}_degraded")
        if (
            gold_after["node_error_px"] < 0
            or gold_before["node_error_px"] < 0
            or gold_after["node_error_px"] > gold_before["node_error_px"] + 1e-9
        ):
            reasons.append("gold_nodes_degraded")
    return tuple(reasons)
