"""Bounded soft study-context inference. No Qt, persistence, identifiers in logs or I/O.

Visual OOD/UNKNOWN and confident out-of-order clips cannot be overruled by a
protocol. Manual decisions are hard boundary conditions, not training labels.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np

from echo_personal_tool.domain.models.view_recognition import (
    TTE_STANDARD_VIEWS,
    UNKNOWN_VIEW,
    ViewDecision,
    ViewDecisionSource,
)


@dataclass(frozen=True)
class StudyViewClip:
    series_uid: str
    probabilities: tuple[float, ...]
    acquisition_time: str | None = None
    instance_number: int | None = None
    visual_view: str | None = None
    out_of_distribution: bool = False


@dataclass(frozen=True)
class StudyViewCue:
    series_uid: str
    kind: Literal["plax_linear", "rv_measurement", "la_biplane"]


@dataclass(frozen=True)
class StudyViewResolution:
    series_uid: str
    view: str
    confidence: float
    source: ViewDecisionSource
    probabilities: tuple[float, ...]
    reason: str


def acquisition_seconds(value: str | None) -> float | None:
    """DICOM TM only; never parse dates, locale strings or use filename order."""
    if not value:
        return None
    pieces = value.split(".")
    whole = pieces[0]
    if len(pieces) > 2 or len(whole) not in {2, 4, 6} or not whole.isdigit():
        return None
    if len(pieces) == 2 and (len(whole) != 6 or not pieces[1].isdigit() or len(pieces[1]) > 6):
        return None
    hour = int(whole[:2])
    minute = int(whole[2:4]) if len(whole) >= 4 else 0
    second = int(whole[4:6]) if len(whole) == 6 else 0
    if hour > 23 or minute > 59 or second > 59:
        return None
    return 3600.0 * hour + 60.0 * minute + second + (float("0." + pieces[1]) if len(pieces) == 2 else 0.0)


def _ordered(clips: Sequence[StudyViewClip]) -> tuple[list[int], bool]:
    times = [acquisition_seconds(c.acquisition_time) for c in clips]
    if all(t is not None for t in times):
        return sorted(
            range(len(clips)), key=lambda i: (times[i], clips[i].instance_number or 0, clips[i].series_uid)
        ), True
    if all(c.instance_number is not None for c in clips):
        return sorted(range(len(clips)), key=lambda i: (clips[i].instance_number, clips[i].series_uid)), True
    # No fabricated chronological relationship for incomplete metadata.
    return list(range(len(clips))), False


def _context_posteriors(emissions: np.ndarray, strength: float) -> np.ndarray:
    n, k = emissions.shape
    indices = np.arange(k)
    delta = indices[None, :] - indices[:, None]
    preference = np.where(delta == 0, 1.0, np.where(delta > 0, 1.0 / np.maximum(delta, 1), 0.1))
    transitions = np.exp(strength * preference)
    transitions /= transitions.sum(axis=1, keepdims=True)
    forward = np.zeros_like(emissions)
    backward = np.ones_like(emissions)
    forward[0] = emissions[0] / emissions[0].sum()
    for i in range(1, n):
        row = (forward[i - 1] @ transitions) * emissions[i]
        forward[i] = row / row.sum()
    for i in range(n - 2, -1, -1):
        row = transitions @ (emissions[i + 1] * backward[i + 1])
        backward[i] = row / row.sum()
    result = forward * backward
    return np.asarray(result / result.sum(axis=1, keepdims=True), dtype=float)


def resolve_study_views(
    clips: Sequence[StudyViewClip],
    *,
    manual_decisions: Mapping[str, ViewDecision] | None = None,
    cues: Sequence[StudyViewCue] = (),
    threshold: float = 0.6,
    protocol_strength: float = 0.45,
    measurement_strength: float = 0.8,
) -> tuple[StudyViewResolution, ...]:
    """Forward/backward soft protocol with capped evidence; output in INPUT order.

    No promotions with max visual p < .35, explicit UNKNOWN or OOD. Visual p
    >= threshold locks the label, even in reversed/skipped protocols. Neighbour and
    repeated measurement evidence cannot accumulate unbounded pseudo-certainty.
    Only explicit MANUAL store decisions become hard anchors (including UNKNOWN).
    """
    if (
        not 0.5 <= threshold <= 0.85
        or not 0 <= protocol_strength <= 0.5
        or not 0 <= measurement_strength <= 1
        or len(clips) > 512
    ):
        raise ValueError("invalid study context configuration")
    if not clips:
        return ()
    ids = [c.series_uid for c in clips]
    if len(set(ids)) != len(ids) or any(not uid for uid in ids):
        raise ValueError("study context needs unique nonempty series keys")
    probabilities = np.asarray([c.probabilities for c in clips], dtype=float)
    if (
        probabilities.shape != (len(clips), len(TTE_STANDARD_VIEWS))
        or not np.isfinite(probabilities).all()
        or np.any(probabilities < 0)
        or not np.allclose(probabilities.sum(axis=1), 1.0, atol=1e-6, rtol=0)
    ):
        raise ValueError("invalid study view probabilities/taxonomy")
    manual = {k: v for k, v in (manual_decisions or {}).items() if v.source is ViewDecisionSource.MANUAL}
    if any(k != v.series_uid for k, v in manual.items()):
        raise ValueError("manual decision identity mismatch")
    preferences = {"plax_linear": ("PLAX",), "rv_measurement": ("A4C", "RV_A4C"), "la_biplane": ("A4C", "A2C")}
    prior = np.zeros_like(probabilities)
    for cue in cues:
        if cue.kind not in preferences or cue.series_uid not in ids:
            raise ValueError("invalid or unbound study measurement cue")
        row = ids.index(cue.series_uid)
        for view in preferences[cue.kind]:
            prior[row, TTE_STANDARD_VIEWS.index(view)] = 1.0
    top = probabilities.argmax(axis=1)
    maxima = probabilities.max(axis=1)
    blocked = [c.out_of_distribution or c.visual_view == UNKNOWN_VIEW or maxima[i] < 0.35 for i, c in enumerate(clips)]
    emissions = np.maximum(probabilities, 1e-12) * np.exp(measurement_strength * prior)
    for i, clip in enumerate(clips):
        decision = manual.get(clip.series_uid)
        if decision is not None and decision.view in TTE_STANDARD_VIEWS:
            emissions[i] = 0
            emissions[i, TTE_STANDARD_VIEWS.index(decision.view)] = 1.0
        elif blocked[i] or decision is not None:
            emissions[i] = 1.0
    order, chronological = _ordered(clips)
    posterior = _context_posteriors(emissions[order], protocol_strength if chronological else 0.0)
    posterior = posterior[np.argsort(order)]
    result = []
    for i, clip in enumerate(clips):
        decision = manual.get(clip.series_uid)
        if decision is not None:
            view, confidence, source, reason = decision.view, 1.0, ViewDecisionSource.MANUAL, "manual_locked"
        elif blocked[i]:
            view, confidence, source, reason = UNKNOWN_VIEW, float(maxima[i]), ViewDecisionSource.AUTO, "visual_unknown"
        elif maxima[i] >= threshold:
            view, confidence, source, reason = (
                TTE_STANDARD_VIEWS[top[i]],
                float(maxima[i]),
                ViewDecisionSource.AUTO,
                "visual_locked",
            )
        else:
            index = int(posterior[i].argmax())
            confidence = float(posterior[i, index])
            view = TTE_STANDARD_VIEWS[index] if confidence >= threshold else UNKNOWN_VIEW
            source = (
                ViewDecisionSource.AUTO
                if np.allclose(posterior[i], probabilities[i], atol=1e-9, rtol=0)
                else ViewDecisionSource.AUTO_STUDY_CONTEXT
            )
            reason = "study_context" if view != UNKNOWN_VIEW else "insufficient_evidence"
        row = probabilities[i] if reason in {"visual_unknown", "visual_locked"} else posterior[i]
        result.append(
            StudyViewResolution(clip.series_uid, view, confidence, source, tuple(float(x) for x in row), reason)
        )
    return tuple(result)
