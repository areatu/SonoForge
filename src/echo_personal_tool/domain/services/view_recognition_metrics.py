"""View-recognition accuracy metrics for bench evaluation.

Pure functions over label sequences — no Qt, no IO, no randomness. They
complement :mod:`echo_personal_tool.domain.services.bench_metrics` (which
covers segmentation metrics): this module answers the classification half of
the Tier-1 bench question — how often the recogniser names the right view,
per view and in aggregate (#639 step 5).

All functions require equal-length ``gold`` / ``predicted`` sequences and
raise :class:`ValueError` on a mismatch, so a silently truncated comparison
can never inflate the reported accuracy.
"""

from __future__ import annotations

from collections.abc import Sequence


def top1_accuracy(gold: Sequence[str], predicted: Sequence[str]) -> float:
    """Fraction of gold labels the recogniser predicted correctly.

    Returns ``0.0`` for an empty corpus. Raises :class:`ValueError` when the
    label sequences differ in length.
    """
    if len(gold) != len(predicted):
        raise ValueError(f"label length mismatch: gold={len(gold)} predicted={len(predicted)}")
    if not gold:
        return 0.0
    correct = sum(1 for g, p in zip(gold, predicted, strict=True) if g == p)
    return correct / len(gold)


def per_class_recall(
    gold: Sequence[str],
    predicted: Sequence[str],
    class_names: Sequence[str],
) -> dict[str, float]:
    """Recall (sensitivity) per class: hits / gold samples of that class.

    Classes with no gold samples report ``0.0`` so the report shape stays
    closed and a silently dropped class cannot hide inside a missing key.
    """
    if len(gold) != len(predicted):
        raise ValueError(f"label length mismatch: gold={len(gold)} predicted={len(predicted)}")
    totals: dict[str, int] = {name: 0 for name in class_names}
    hits: dict[str, int] = {name: 0 for name in class_names}
    for g, p in zip(gold, predicted, strict=True):
        if g in totals:
            totals[g] += 1
            if p == g:
                hits[g] += 1
    return {name: (hits[name] / totals[name] if totals[name] else 0.0) for name in class_names}


def confusion_counts(
    gold: Sequence[str],
    predicted: Sequence[str],
) -> dict[tuple[str, str], int]:
    """Count observed ``(gold, predicted)`` label pairs.

    Only pairs that actually occurred are present in the mapping; a perfect
    recogniser reports exactly ``len(gold)`` diagonal entries.
    """
    if len(gold) != len(predicted):
        raise ValueError(f"label length mismatch: gold={len(gold)} predicted={len(predicted)}")
    counts: dict[tuple[str, str], int] = {}
    for g, p in zip(gold, predicted, strict=True):
        key = (g, p)
        counts[key] = counts.get(key, 0) + 1
    return counts


def accuracy_summary(
    gold: Sequence[str],
    predicted: Sequence[str],
    class_names: Sequence[str],
) -> dict[str, object]:
    """Aggregate accuracy report over a labelled corpus.

    Mirrors the shape of :func:`bench_metrics.aggregate_bench_results`:
    ``total``, ``top1``, ``per_class`` and ``confusion``, so downstream tooling
    can consume segmentation and classification benches uniformly.
    """
    if not gold:
        return {
            "total": 0,
            "top1_accuracy": 0.0,
            "per_class_recall": {name: 0.0 for name in class_names},
            "confusion": {},
        }
    return {
        "total": len(gold),
        "top1_accuracy": top1_accuracy(gold, predicted),
        "per_class_recall": per_class_recall(gold, predicted, class_names),
        "confusion": confusion_counts(gold, predicted),
    }
