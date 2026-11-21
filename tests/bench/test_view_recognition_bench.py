"""View-recognition accuracy + latency benchmarks (issue #639, step 5).

Measures the classification half of the Tier-1 bench over a deterministic
synthetic corpus: recognition accuracy (top-1, per-class recall) and the
per-clip recognition latency through :class:`ViewRecognitionService`. The
synthetic recognizer encodes the gold view in the frame mean, so the
accuracy numbers are exact and reproducible — no model or real corpus is
needed to detect a multiples-sized regression in the pipeline.

Run:  ECHO_BENCH=1 pytest tests/bench/test_view_recognition_bench.py -v --benchmark-only
"""

from __future__ import annotations

import os
from collections.abc import Sequence

import numpy as np
import pytest

from echo_personal_tool.domain.models.view_recognition import (
    KNOWN_VIEWS,
    UNKNOWN_VIEW,
    RecognizedView,
)
from echo_personal_tool.domain.services.view_recognition import ViewRecognitionService
from echo_personal_tool.domain.services.view_recognition_metrics import (
    accuracy_summary,
    per_class_recall,
    top1_accuracy,
)

_bench = pytest.mark.bench

_skip_no_env = pytest.mark.skipif(
    os.environ.get("ECHO_BENCH", "") != "1",
    reason="Set ECHO_BENCH=1 to run benchmarks",
)

_MEAN_STEP = 10.0


class _SyntheticRecognizer:
    """Deterministic recognizer: the view is encoded in the frame mean.

    A clip built for view ``i`` has mean ``100.0 + 10.0 * i``, so recognition
    is a pure arithmetic function of the frames — exact and reproducible.
    """

    _CONFIDENCE = 0.95

    def recognize(self, frames: Sequence[np.ndarray]) -> RecognizedView:
        flat = np.concatenate([np.asarray(f, dtype=np.float64).ravel() for f in frames])
        mean = float(flat.mean())
        index = int(round((mean - 100.0) / _MEAN_STEP))
        if not 0 <= index < len(KNOWN_VIEWS):
            return RecognizedView(UNKNOWN_VIEW, 0.1)
        return RecognizedView(KNOWN_VIEWS[index], self._CONFIDENCE)


def _clip_for_view(view: str, frames: int, size: int) -> np.ndarray:
    """Build a ``(frames, size, size)`` float32 clip whose mean encodes ``view``."""
    index = KNOWN_VIEWS.index(view)
    return np.full((frames, size, size), 100.0 + _MEAN_STEP * index, dtype=np.float32)


def _build_corpus(views: Sequence[str], frames: int, size: int) -> tuple[list[np.ndarray], list[str]]:
    clips = [_clip_for_view(v, frames, size) for v in views]
    return clips, list(views)


@_bench
@_skip_no_env
def test_bench_view_recognition_accuracy(benchmark) -> None:
    """End-to-end top-1 accuracy over the full canonical view corpus."""
    service = ViewRecognitionService(_SyntheticRecognizer())
    clips, gold = _build_corpus(KNOWN_VIEWS, frames=4, size=8)

    def _recognize_all() -> None:
        predicted = [service.recognize_clip(clip).view for clip in clips]
        assert top1_accuracy(gold, predicted) == pytest.approx(1.0)

    benchmark(_recognize_all)


@_bench
@_skip_no_env
def test_bench_view_recognition_per_class_recall(benchmark) -> None:
    """Per-class recall over the canonical corpus (every class present)."""
    service = ViewRecognitionService(_SyntheticRecognizer())
    clips, gold = _build_corpus(KNOWN_VIEWS, frames=4, size=8)

    def _recall_all() -> None:
        predicted = [service.recognize_clip(clip).view for clip in clips]
        recall = per_class_recall(gold, predicted, KNOWN_VIEWS)
        assert all(recall[view] == pytest.approx(1.0) for view in KNOWN_VIEWS)

    benchmark(_recall_all)


@_bench
@_skip_no_env
def test_bench_view_recognition_accuracy_summary(benchmark) -> None:
    """Aggregate accuracy report shape and value over the corpus."""
    service = ViewRecognitionService(_SyntheticRecognizer())
    clips, gold = _build_corpus(KNOWN_VIEWS, frames=4, size=8)

    def _summary_all() -> None:
        predicted = [service.recognize_clip(clip).view for clip in clips]
        report = accuracy_summary(gold, predicted, KNOWN_VIEWS)
        assert report["total"] == len(gold)
        assert report["top1_accuracy"] == pytest.approx(1.0)

    benchmark(_summary_all)


@_bench
@_skip_no_env
def test_bench_view_recognition_latency_single_clip(benchmark) -> None:
    """Recognition latency for one small cine clip (4 frames, 64x64)."""
    service = ViewRecognitionService(_SyntheticRecognizer())
    clip = _clip_for_view("A4C", frames=4, size=64)
    benchmark(service.recognize_clip, clip)


@_bench
@_skip_no_env
def test_bench_view_recognition_latency_full_corpus(benchmark) -> None:
    """Recognition latency for the whole canonical corpus (7 views)."""
    service = ViewRecognitionService(_SyntheticRecognizer())
    clips, _ = _build_corpus(KNOWN_VIEWS, frames=4, size=64)

    def _recognize_corpus() -> None:
        for clip in clips:
            service.recognize_clip(clip)

    benchmark(_recognize_corpus)
