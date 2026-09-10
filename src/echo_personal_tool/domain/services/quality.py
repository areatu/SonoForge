"""Honest STE quality assessment: tracking *fidelity* vs measurement *validity*.

Fidelity is how well the block matching followed the speckle pattern (the NCC
mean the module already reports). Validity is whether the resulting numbers are
a defined clinical measurement at all: is the geometry usable, is the material
line covered, are the two equivalent strain definitions in agreement, is the
deformation physiologically possible.

The old ``QC 95 %`` badge combined NCC with kernel coverage only, which is why
a confidently mis-tracked clip could read >90 % while the strain was nonsense.
This module turns that into a status (``valid`` / ``review`` / ``invalid``), a
confidence score and a list of machine-readable reason keys, so the UI and the
export can state *why* a number may not be trusted.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

STATUS_VALID = "valid"
STATUS_REVIEW = "review"
STATUS_INVALID = "invalid"

# Thresholds (fractions / percentage points). Kept together so the QC policy can
# be reviewed in one place.
MIN_COVERAGE_INVALID = 0.50
MIN_COVERAGE_REVIEW = 0.80
MAX_INTERPOLATED_REVIEW = 0.15
MAX_CONSISTENCY_DELTA_REVIEW = 2.0  # percentage points between definitions A and B
MIN_SEGMENTS_REVIEW = 3
# Cross-checks between independent estimates of the *same* global strain. The
# reported GLS is the peak of the global curve; the segment mean and the node
# end-systolic median are computed from the same tracking but a different
# aggregation, so they must broadly agree. Disagreement means the number
# depends on the aggregation choice and must not be presented as confident.
MAX_ESTIMATE_SPREAD_ABS = 5.0  # percentage points
MAX_ESTIMATE_SPREAD_REL = 0.30  # fraction of |GLS|
MAX_SIGN_FLIP_FRACTION = 0.25  # nodes shortening vs stretching at end-systole
# Position noise vs the signal it is supposed to measure. A polyline through
# noisy points is *longer* than the material line it samples (E|Δp+n| > |Δp|), so
# noise inflates the arc length of every frame and flattens the strain. When that
# inflation is comparable to the contraction itself, the number is not a
# measurement at all — whatever the NCC says. ``noise_to_signal`` is the
# estimated length bias divided by the measured contraction.
MAX_NOISE_TO_SIGNAL_INVALID = 1.0
MAX_NOISE_TO_SIGNAL_REVIEW = 0.35

REASON_NO_DATA = "strain.qc.reason.no_data"
REASON_GEOMETRY = "strain.qc.reason.geometry"
REASON_LOW_COVERAGE = "strain.qc.reason.low_coverage"
REASON_INTERPOLATION = "strain.qc.reason.interpolation"
REASON_CONSISTENCY = "strain.qc.reason.consistency"
REASON_FEW_SEGMENTS = "strain.qc.reason.few_segments"
REASON_PHYSIOLOGY = "strain.qc.reason.physiology"
REASON_CROSS_CHECK = "strain.qc.reason.cross_check"
REASON_LINE_COHERENCE = "strain.qc.reason.line_coherence"
REASON_TRACKING_NOISE = "strain.qc.reason.tracking_noise"


@dataclass(frozen=True)
class QualityReport:
    """Result of the validity assessment for one analysed view."""

    status: str = STATUS_INVALID
    confidence: float = 0.0
    fidelity: float = 0.0
    coverage: float = 0.0
    interpolated_fraction: float = 0.0
    consistency_delta: float = 0.0
    estimate_spread_pp: float = 0.0
    sign_flip_fraction: float = 0.0
    noise_to_signal: float = 0.0
    physiology_ok: bool = False
    reasons: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_valid(self) -> bool:
        return self.status == STATUS_VALID


def assess_tracking_quality(
    *,
    has_curve: bool = True,
    fidelity: float = 0.0,
    coverage: float = 0.0,
    interpolated_fraction: float = 0.0,
    consistency_delta: float = 0.0,
    estimate_spread_pp: float = 0.0,
    sign_flip_fraction: float = 0.0,
    noise_to_signal: float = 0.0,
    gls_pp: float = 0.0,
    physiology_ok: bool = True,
    physiology_notes: Sequence[str] = (),
    geometry_ok: bool = True,
    geometry_notes: Sequence[str] = (),
    n_segments_measured: int = 0,
) -> QualityReport:
    """Classify a tracking result as valid / needs review / invalid.

    Hard failures (no curve, unusable geometry, uncovered line, impossible
    deformation) make the result ``invalid``; soft signals (borderline coverage,
    interpolated frames, disagreement between the global-strain definitions,
    disagreement between independent estimators of the same strain, a material
    line that partly stretches, too few segments) downgrade it to ``review``.
    ``confidence`` never exceeds 0.35 for an invalid result and 0.75 for one
    that needs review, so a green "everything is fine" reading is impossible
    without passing the checks.

    ``estimate_spread_pp`` is the gap between the reported global strain and the
    (independent) segment-mean estimate; ``sign_flip_fraction`` is the share of
    the endocardial line whose end-systolic strain has the opposite sign of the
    reported GLS. Both are *metric* cross-checks: they need no reference and no
    ground truth, and they fail exactly when a confidently tracked clip carries
    a wrong number (plan §7.5, F4).

    ``noise_to_signal`` adds the measurement-theory check: the estimated
    arc-length bias caused by the position noise divided by the measured
    contraction. Noise makes a polyline longer, so it *shortens* the reported
    strain; when the bias is of the same order as the contraction the strain is
    not measurable and the result is ``invalid`` regardless of the NCC.
    """
    reasons: list[str] = []
    notes: list[str] = list(physiology_notes) + list(geometry_notes)
    hard_failure = False

    coverage = float(max(0.0, min(1.0, coverage)))
    fidelity = float(max(0.0, min(1.0, fidelity)))
    gls_reference = float(gls_pp) if gls_pp == gls_pp else 0.0  # NaN-safe
    interpolated_fraction = float(max(0.0, min(1.0, interpolated_fraction)))

    if not has_curve:
        reasons.append(REASON_NO_DATA)
        hard_failure = True
    if not geometry_ok:
        reasons.append(REASON_GEOMETRY)
        hard_failure = True
    if not physiology_ok:
        reasons.append(REASON_PHYSIOLOGY)
        hard_failure = True
    if has_curve and coverage < MIN_COVERAGE_INVALID:
        reasons.append(REASON_LOW_COVERAGE)
        hard_failure = True

    noise_ratio = float(noise_to_signal) if np.isfinite(noise_to_signal) else 0.0
    if has_curve and noise_ratio > MAX_NOISE_TO_SIGNAL_INVALID:
        reasons.append(REASON_TRACKING_NOISE)
        hard_failure = True

    soft = False
    if not hard_failure:
        if coverage < MIN_COVERAGE_REVIEW:
            reasons.append(REASON_LOW_COVERAGE)
            soft = True
        if interpolated_fraction > MAX_INTERPOLATED_REVIEW:
            reasons.append(REASON_INTERPOLATION)
            soft = True
        if consistency_delta > MAX_CONSISTENCY_DELTA_REVIEW:
            reasons.append(REASON_CONSISTENCY)
            soft = True
        spread = float(max(0.0, estimate_spread_pp))
        if spread > MAX_ESTIMATE_SPREAD_ABS and spread > MAX_ESTIMATE_SPREAD_REL * abs(gls_reference):
            reasons.append(REASON_CROSS_CHECK)
            soft = True
        if sign_flip_fraction > MAX_SIGN_FLIP_FRACTION:
            reasons.append(REASON_LINE_COHERENCE)
            soft = True
        if noise_ratio > MAX_NOISE_TO_SIGNAL_REVIEW:
            reasons.append(REASON_TRACKING_NOISE)
            soft = True
        if n_segments_measured < MIN_SEGMENTS_REVIEW:
            reasons.append(REASON_FEW_SEGMENTS)
            soft = True
        if physiology_notes:
            soft = True

    if hard_failure:
        status = STATUS_INVALID
    elif soft:
        status = STATUS_REVIEW
    else:
        status = STATUS_VALID

    # Confidence: fidelity and coverage dominate, interpolation and a
    # disagreement between definitions pull it down further.
    confidence = fidelity * coverage
    confidence *= 1.0 - 0.5 * min(interpolated_fraction / 0.30, 1.0)
    confidence -= 0.03 * max(0.0, consistency_delta - 1.0)
    confidence *= 1.0 - 0.5 * min(max(float(estimate_spread_pp) - 1.0, 0.0) / 8.0, 1.0)
    confidence *= 1.0 - 0.3 * min(float(sign_flip_fraction) / 0.5, 1.0)
    confidence *= 1.0 - 0.5 * min(noise_ratio / MAX_NOISE_TO_SIGNAL_INVALID, 1.0)
    confidence = float(max(0.0, min(1.0, confidence)))
    if status == STATUS_INVALID:
        confidence = min(confidence, 0.35)
    elif status == STATUS_REVIEW:
        confidence = min(confidence, 0.75)

    return QualityReport(
        status=status,
        confidence=confidence,
        fidelity=fidelity,
        coverage=coverage,
        interpolated_fraction=interpolated_fraction,
        consistency_delta=float(consistency_delta),
        estimate_spread_pp=float(estimate_spread_pp),
        noise_to_signal=noise_ratio,
        sign_flip_fraction=float(sign_flip_fraction),
        physiology_ok=bool(physiology_ok),
        reasons=tuple(dict.fromkeys(reasons)),
        notes=tuple(notes),
    )


# Short alias used by callers that already imported the module.
assess = assess_tracking_quality
