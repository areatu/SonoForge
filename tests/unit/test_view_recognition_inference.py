"""Unit tests for view-recognition inference helpers (issue #639, step 2).

Covers the pure preprocessing + aggregation pipeline: frame resize to the
model input size, clip-to-batch stacking, channel layout, and the mean-softmax
aggregation rule — no torch, no ONNX runtime, no Qt.
"""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.models.view_recognition import KNOWN_VIEWS
from echo_personal_tool.domain.services.view_recognition_inference import (
    aggregate_predictions,
    batch_to_channels,
    clip_to_batch,
    preprocess_frame,
)


def _frame(rows: int = 8, cols: int = 12, channels: int = 1) -> np.ndarray:
    rng = np.random.default_rng(0)
    return rng.integers(0, 256, (rows, cols, channels), dtype=np.uint8)


# ── preprocess_frame ─────────────────────────────────────────────────


def test_preprocess_frame_resizes_and_normalizes() -> None:
    frame = _frame(rows=16, cols=24)
    out = preprocess_frame(frame, 8)
    assert out.shape == (8, 8, 3)
    assert out.dtype == np.float32
    assert out.min() >= 0.0
    assert out.max() <= 1.0


def test_preprocess_frame_replicates_grayscale_to_3_channels() -> None:
    frame = np.full((4, 4), 128, dtype=np.uint8)
    out = preprocess_frame(frame, 8)
    assert out.shape == (8, 8, 3)
    # All three channels equal the replicated grayscale value.
    assert np.array_equal(out[..., 0], out[..., 1])
    assert np.array_equal(out[..., 1], out[..., 2])


def test_preprocess_frame_accepts_float_input_in_unit_range() -> None:
    frame = np.linspace(0.0, 1.0, 16 * 16).reshape(16, 16).astype(np.float32)
    out = preprocess_frame(frame, 8)
    assert out.shape == (8, 8, 3)
    assert out.max() <= 1.0


def test_preprocess_frame_rejects_bad_shape() -> None:
    with pytest.raises(ValueError, match="frame must be"):
        preprocess_frame(np.zeros((2, 2, 4), dtype=np.uint8), 8)


# ── clip_to_batch / batch_to_channels ─────────────────────────────────


def test_clip_to_batch_stacks_frames() -> None:
    frames = [_frame(rows=8, cols=8), _frame(rows=16, cols=16)]
    batch = clip_to_batch(frames, 10)
    assert batch.shape == (2, 10, 10, 3)
    assert batch.dtype == np.float32


def test_clip_to_batch_rejects_empty_clip() -> None:
    with pytest.raises(ValueError, match="empty"):
        clip_to_batch([], 8)


def test_batch_to_channels_transposes_layout() -> None:
    batch = np.zeros((2, 5, 5, 3), dtype=np.float32)
    channels = batch_to_channels(batch)
    assert channels.shape == (2, 3, 5, 5)
    assert channels[0, 0, 0, 0] == batch[0, 0, 0, 0]


def test_clip_to_batch_then_channels_round_trip() -> None:
    frames = [_frame(), _frame(rows=6, cols=9)]
    channels = batch_to_channels(clip_to_batch(frames, 12))
    assert channels.shape == (2, 3, 12, 12)


# ── aggregate_predictions ─────────────────────────────────────────────


def test_aggregate_predictions_uses_mean_softmax() -> None:
    probs = np.array(
        [
            [0.8, 0.2],
            [0.6, 0.4],
        ]
    )
    result = aggregate_predictions(probs, ("A4C", "A2C"))
    assert result.view == "A4C"
    assert result.confidence == pytest.approx(0.7)


def test_aggregate_predictions_unanimous_frames() -> None:
    probs = np.array([[0.0, 0.9], [0.0, 0.95]])
    result = aggregate_predictions(probs, ("A4C", "A2C"))
    assert result.view == "A2C"
    assert result.confidence == pytest.approx(0.925)


def test_aggregate_predictions_single_frame() -> None:
    one_hot = np.zeros((1, len(KNOWN_VIEWS)))
    one_hot[0, 2] = 0.7
    one_hot[0, 5] = 0.3
    result = aggregate_predictions(one_hot, KNOWN_VIEWS)
    assert result.view == KNOWN_VIEWS[2]
    assert result.confidence == pytest.approx(0.7)


def test_aggregate_predictions_unknown_view_fallback_never_wins() -> None:
    # A class that is all zeros can never win the argmax, so a clip with no
    # signal falls back to the highest-probability real class instead of
    # inventing a view.
    probs = np.array([[0.3, 0.3, 0.4, 0.0, 0.0, 0.0, 0.0]])
    result = aggregate_predictions(probs, KNOWN_VIEWS)
    assert result.view in KNOWN_VIEWS
    assert result.confidence > 0.0


def test_aggregate_predictions_shape_validation() -> None:
    with pytest.raises(ValueError, match="must be \\(N, C\\)"):
        aggregate_predictions(np.zeros((2, 2, 2)), KNOWN_VIEWS)
    with pytest.raises(ValueError, match="empty"):
        aggregate_predictions(np.zeros((0, 7)), KNOWN_VIEWS)
    with pytest.raises(ValueError, match="columns"):
        aggregate_predictions(np.zeros((2, 3)), KNOWN_VIEWS)
