"""Pure validation metrics for the research validation harness (#418).

The numerical core behind ``application.ef_validation``: agreement metrics
between a measurement tool under validation and an external reference
standard (EchoNet-Dynamic EF values today, any numeric reference tomorrow).
No Qt, no numpy, no I/O — the same pure-core guarantee as
``domain/calculations``, exercised by the Qt-free ``test-pure-core`` job.

Every function fails closed on degenerate input: empty or mismatched series,
non-finite values, or zero-variance series raise ``ValueError`` with a stable
message instead of returning a silently meaningless number.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

#: Research status marker: every report built from these metrics is
#: research-only until #418 completes its external validation protocol.
RESEARCH_ONLY = True


def _validated_pair_series(reference: Sequence[float], predicted: Sequence[float]) -> list[tuple[float, float]]:
    if len(reference) != len(predicted):
        raise ValueError("length_mismatch")
    if len(reference) == 0:
        raise ValueError("empty_input")
    pairs: list[tuple[float, float]] = []
    for ref, pred in zip(reference, predicted, strict=True):
        try:
            ref_f = float(ref)
            pred_f = float(pred)
        except (TypeError, ValueError) as exc:
            raise ValueError("non_numeric_input") from exc
        if not (math.isfinite(ref_f) and math.isfinite(pred_f)):
            raise ValueError("non_finite_input")
        pairs.append((ref_f, pred_f))
    return pairs


def mean_absolute_error(reference: Sequence[float], predicted: Sequence[float]) -> float:
    """MAE of ``predicted`` against ``reference`` (EF percentage points)."""
    pairs = _validated_pair_series(reference, predicted)
    return sum(abs(pred - ref) for ref, pred in pairs) / len(pairs)


def bias(reference: Sequence[float], predicted: Sequence[float]) -> float:
    """Mean signed difference ``predicted - reference`` (over-/under-estimation)."""
    pairs = _validated_pair_series(reference, predicted)
    return sum(pred - ref for ref, pred in pairs) / len(pairs)


def standard_deviation(values: Sequence[float]) -> float:
    """Sample standard deviation (n-1); a single value raises ``ValueError``."""
    if len(values) < 2:
        raise ValueError("insufficient_data")
    validated: list[float] = []
    for value in values:
        value_f = float(value)
        if not math.isfinite(value_f):
            raise ValueError("non_finite_input")
        validated.append(value_f)
    mean = sum(validated) / len(validated)
    variance = sum((value - mean) ** 2 for value in validated) / (len(validated) - 1)
    return math.sqrt(variance)


def bland_altman_limits(reference: Sequence[float], predicted: Sequence[float]) -> tuple[float, float, float]:
    """Bland–Altman bias and 95% limits of agreement of the differences.

    Returns ``(bias, lower, upper)`` with ``lower/upper = bias ± 1.96·SD`` of
    the per-pair differences ``predicted - reference``.
    """
    pairs = _validated_pair_series(reference, predicted)
    differences = [pred - ref for ref, pred in pairs]
    mean_diff = sum(differences) / len(differences)
    sd = standard_deviation(differences)
    spread = 1.96 * sd
    return mean_diff, mean_diff - spread, mean_diff + spread


def pearson_r(reference: Sequence[float], predicted: Sequence[float]) -> float:
    """Pearson correlation of the paired series.

    Raises ``ValueError`` for fewer than two pairs or a zero-variance series —
    a correlation of a constant series is undefined, not zero.
    """
    pairs = _validated_pair_series(reference, predicted)
    if len(pairs) < 2:
        raise ValueError("insufficient_data")
    ref_mean = sum(ref for ref, _ in pairs) / len(pairs)
    pred_mean = sum(pred for _, pred in pairs) / len(pairs)
    ref_sd = standard_deviation([ref for ref, _ in pairs])
    pred_sd = standard_deviation([pred for _, pred in pairs])
    if ref_sd == 0.0 or pred_sd == 0.0:
        raise ValueError("degenerate_input")
    covariance = sum((ref - ref_mean) * (pred - pred_mean) for ref, pred in pairs) / (len(pairs) - 1)
    r = covariance / (ref_sd * pred_sd)
    return max(-1.0, min(1.0, r))


def confusion_counts(
    reference: Sequence[float],
    predicted: Sequence[float],
    *,
    threshold: float,
) -> tuple[int, int, int, int]:
    """``(tp, fp, fn, tn)`` for reduced-EF detection at *threshold*.

    The positive class is ``reference < threshold`` (reduced EF): a
    *reference* value below the threshold is condition-positive, and a
    *predicted* value below it is a positive call.
    """
    pairs = _validated_pair_series(reference, predicted)
    tp = fp = fn = tn = 0
    for ref, pred in pairs:
        condition_positive = ref < threshold
        call_positive = pred < threshold
        if condition_positive and call_positive:
            tp += 1
        elif not condition_positive and call_positive:
            fp += 1
        elif condition_positive:
            fn += 1
        else:
            tn += 1
    return tp, fp, fn, tn


def sensitivity_specificity(
    reference: Sequence[float],
    predicted: Sequence[float],
    *,
    threshold: float,
) -> tuple[float | None, float | None]:
    """Sensitivity/specificity of reduced-EF detection; ``None`` when undefined.

    A denominator of zero (no condition-positive or no condition-negative
    pairs) yields ``None`` for that statistic — a missing rate is reported as
    missing, never as 0.0 or 1.0.
    """
    tp, fp, fn, tn = confusion_counts(reference, predicted, threshold=threshold)
    sensitivity = tp / (tp + fn) if (tp + fn) > 0 else None
    specificity = tn / (tn + fp) if (tn + fp) > 0 else None
    return sensitivity, specificity
