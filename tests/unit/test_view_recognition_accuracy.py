"""Accuracy unit tests for view recognition (issue #639, step 5).

Covers the classification half of the Tier-1 bench: label-sequence metrics
(top-1 accuracy, per-class recall, confusion counts) and their aggregation,
plus the end-to-end accuracy of a deterministic synthetic recognizer driven
through :class:`ViewRecognitionService` over a small labelled corpus.

No model, no IO, no Qt — the synthetic recognizer is a pure deterministic
function of the frame statistics so the expected labels are exact.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pytest

from echo_personal_tool.domain.models.view_recognition import (
    KNOWN_VIEWS,
    UNKNOWN_VIEW,
    RecognizedView,
)
from echo_personal_tool.domain.ports import IViewRecognizer
from echo_personal_tool.domain.services.view_recognition import ViewRecognitionService
from echo_personal_tool.domain.services.view_recognition_metrics import (
    accuracy_summary,
    confusion_counts,
    per_class_recall,
    top1_accuracy,
)


class DeterministicRecognizer:
    """Deterministic recognizer: the view is encoded in the frame mean.

    Each synthetic clip carries a distinguishable mean intensity per view
    (``mean = 100.0 + 10.0 * index``), so a clip built for view ``i`` is
    always recognised as view ``i`` with confidence ``0.95``. This keeps the
    accuracy expectations exact without a real model.
    """

    _MEAN_STEP = 10.0
    _CONFIDENCE = 0.95

    def recognize(self, frames: Sequence[np.ndarray]) -> RecognizedView:
        flat = np.concatenate([np.asarray(f, dtype=np.float64).ravel() for f in frames])
        mean = float(flat.mean())
        index = int(round((mean - 100.0) / self._MEAN_STEP))
        if not 0 <= index < len(KNOWN_VIEWS):
            return RecognizedView(UNKNOWN_VIEW, 0.1)
        return RecognizedView(KNOWN_VIEWS[index], self._CONFIDENCE)


def _clip_for_view(view: str, frames: int = 4, size: int = 4) -> np.ndarray:
    """Build a ``(frames, size, size)`` float32 clip whose mean encodes ``view``."""
    index = KNOWN_VIEWS.index(view)
    mean = 100.0 + 10.0 * index
    return np.full((frames, size, size), mean, dtype=np.float32)


# ── label-sequence metrics ──────────────────────────────────────────


def test_top1_accuracy_perfect_corpus() -> None:
    gold = ["A4C", "A2C", "PLAX", "SAX"]
    predicted = list(gold)
    assert top1_accuracy(gold, predicted) == pytest.approx(1.0)


def test_top1_accuracy_partial_corpus() -> None:
    gold = ["A4C", "A2C", "PLAX", "SAX"]
    predicted = ["A4C", "A2C", "A4C", "SAX"]
    assert top1_accuracy(gold, predicted) == pytest.approx(0.75)


def test_top1_accuracy_empty_corpus_is_zero() -> None:
    assert top1_accuracy([], []) == 0.0


def test_top1_accuracy_length_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="length mismatch"):
        top1_accuracy(["A4C"], ["A4C", "SAX"])


def test_per_class_recall_reports_every_class() -> None:
    gold = ["A4C", "A4C", "SAX", "PLAX"]
    predicted = ["A4C", "SAX", "SAX", "PLAX"]
    recall = per_class_recall(gold, predicted, KNOWN_VIEWS)
    assert set(recall) == set(KNOWN_VIEWS)
    assert recall["A4C"] == pytest.approx(0.5)
    assert recall["SAX"] == pytest.approx(1.0)
    assert recall["PLAX"] == pytest.approx(1.0)
    # Classes with no gold samples stay visible with a zero score.
    assert recall["TEE"] == 0.0


def test_per_class_recall_unknown_gold_is_ignored() -> None:
    gold = ["A4C", UNKNOWN_VIEW]
    predicted = ["A4C", "A4C"]
    recall = per_class_recall(gold, predicted, KNOWN_VIEWS)
    assert recall["A4C"] == pytest.approx(1.0)


def test_per_class_recall_length_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="length mismatch"):
        per_class_recall(["A4C", "SAX"], ["A4C"], KNOWN_VIEWS)


def test_confusion_counts_diagonal_for_perfect_corpus() -> None:
    gold = ["A4C", "A2C", "SAX"]
    predicted = list(gold)
    counts = confusion_counts(gold, predicted)
    assert counts == {("A4C", "A4C"): 1, ("A2C", "A2C"): 1, ("SAX", "SAX"): 1}


def test_confusion_counts_off_diagonal_for_mistakes() -> None:
    gold = ["A4C", "A4C", "SAX"]
    predicted = ["A2C", "A4C", "A4C"]
    counts = confusion_counts(gold, predicted)
    assert counts == {("A4C", "A2C"): 1, ("A4C", "A4C"): 1, ("SAX", "A4C"): 1}


def test_confusion_counts_length_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="length mismatch"):
        confusion_counts(["A4C"], [])


def test_accuracy_summary_shape_and_values() -> None:
    gold = ["A4C", "A2C", "PLAX", "SAX"]
    predicted = ["A4C", "A4C", "PLAX", "SAX"]
    report = accuracy_summary(gold, predicted, KNOWN_VIEWS)
    assert report["total"] == 4
    assert report["top1_accuracy"] == pytest.approx(0.75)
    assert report["per_class_recall"]["A4C"] == pytest.approx(1.0)
    assert report["per_class_recall"]["A2C"] == pytest.approx(0.0)
    assert report["confusion"][("A2C", "A4C")] == 1


def test_accuracy_summary_empty_corpus() -> None:
    report = accuracy_summary([], [], KNOWN_VIEWS)
    assert report["total"] == 0
    assert report["top1_accuracy"] == 0.0
    assert report["confusion"] == {}


# ── end-to-end accuracy through the service ─────────────────────────


def test_service_recognizes_every_view_of_corpus() -> None:
    service = ViewRecognitionService(DeterministicRecognizer())
    gold = list(KNOWN_VIEWS)
    predicted = [service.recognize_clip(_clip_for_view(v)).view for v in gold]
    assert predicted == gold
    assert top1_accuracy(gold, predicted) == pytest.approx(1.0)


def test_service_confidence_meets_threshold() -> None:
    service = ViewRecognitionService(DeterministicRecognizer())
    result = service.recognize_clip(_clip_for_view("A4C"))
    assert result.is_confident
    assert result.confidence == pytest.approx(0.95)


def test_service_describe_summary_shape() -> None:
    service = ViewRecognitionService(DeterministicRecognizer())
    clip = _clip_for_view("SAX")
    frames = [clip[i] for i in range(clip.shape[0])]
    summary = service.describe(frames)
    assert summary["view"] == "SAX"
    assert summary["confidence"] == pytest.approx(0.95)
    assert summary["category"] == "parasternal_short"
    assert summary["confident"] is True


def test_recognizer_protocol_compatibility() -> None:
    # The synthetic recognizer satisfies the domain port used by the service.
    recognizer: IViewRecognizer = DeterministicRecognizer()
    service = ViewRecognitionService(recognizer)
    assert service.recognize_clip(_clip_for_view("TEE")).view == "TEE"
