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


def test_aggregate_predictions_uses_median_softmax() -> None:
    # The mean would pick A2C (0.6 vs 0.4); the median ignores the outlier
    # frame and keeps A4C (0.6 vs 0.4), which is the robust clip-level view.
    probs = np.array(
        [
            [0.6, 0.4],
            [0.6, 0.4],
            [0.0, 1.0],
        ]
    )
    result = aggregate_predictions(probs, ("A4C", "A2C"))
    assert result.view == "A4C"
    assert result.confidence == pytest.approx(0.6)


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


# ML.0b contracts are executable without torch / ONNX / Qt.
@pytest.mark.parametrize("size", [16, 32])
def test_legacy_shared_builder_is_bitwise_compatible(size: int) -> None:
    from echo_personal_tool.domain.services.view_recognition_inference import (
        ViewInferenceConfig,
        prepare_clip_for_view_model,
    )

    frames = [_frame(24, 36, 3), _frame(24, 36, 1)]
    expected = batch_to_channels(clip_to_batch(frames, size))
    cfg = ViewInferenceConfig.from_manifest_section(None, input_size=size)
    assert np.array_equal(prepare_clip_for_view_model(frames, config=cfg), expected)


def test_ml0b_config_roundtrip_and_legacy_defaults() -> None:
    from echo_personal_tool.domain.services.view_recognition_inference import ViewInferenceConfig

    config = ViewInferenceConfig.ml0b_default(input_size=32)
    assert ViewInferenceConfig.from_manifest_section(config.to_manifest_fields()) == config
    legacy = ViewInferenceConfig.from_manifest_section({"class_names": ["A4C"]})
    assert legacy.input_mode == "single_frame"
    assert legacy.normalize_imagenet is False
    assert legacy.ood_min_cosine is None


def test_phase_fallback_and_channel_order() -> None:
    from echo_personal_tool.domain.services.view_recognition_inference import (
        ViewInferenceConfig,
        prepare_clip_for_view_model,
        select_phase_triplet_indices,
    )

    frames = [np.full((8, 8), value, dtype=np.float32) for value in (0.1, 0.2, 0.4, 0.6, 0.9)]
    assert select_phase_triplet_indices(frames) == [(0, 1, 3)]
    assert select_phase_triplet_indices(frames[:1]) == [(0, 0, 0)]
    assert select_phase_triplet_indices(frames[:2]) == [(0, 0, 1)]
    config = ViewInferenceConfig(input_size=8, input_mode="phase_triplet")
    batch = prepare_clip_for_view_model(frames, config=config)
    assert batch.shape == (1, 3, 8, 8)
    np.testing.assert_allclose(batch[0, :, 0, 0], [0.1, 0.2, 0.6])
    assert batch.flags.c_contiguous


def test_triplets_use_phase_field_cycles(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from echo_personal_tool.domain.services import view_recognition_inference as inference

    cycles = [SimpleNamespace(partial=False, ed_frame=1, es_frame=5)]
    monkeypatch.setattr(inference, "build_phase_field", lambda **_kwargs: SimpleNamespace(cycles=cycles))
    frames = [np.full((32, 32), i / 8, dtype=np.float32) for i in range(8)]
    assert inference.select_phase_triplet_indices(frames) == [(1, 3, 5)]


def test_phase_triplet_imagenet_normalization() -> None:
    from echo_personal_tool.domain.services.view_recognition_inference import (
        IMAGENET_MEAN,
        IMAGENET_STD,
        ViewInferenceConfig,
        prepare_clip_for_view_model,
    )

    config = ViewInferenceConfig.ml0b_default(input_size=16)
    batch = prepare_clip_for_view_model([np.full((8, 8), 128, dtype=np.uint8)], config=config)
    expected = (128 / 255 - np.array(IMAGENET_MEAN)) / np.array(IMAGENET_STD)
    np.testing.assert_allclose(batch[0, :, 5, 5], expected, atol=1e-6)
    assert batch.dtype == np.float32


def test_canonical_crop_excludes_vendor_corner_text() -> None:
    from echo_personal_tool.domain.services.view_recognition_inference import (
        detect_sector_crop_box,
        extract_canonical_sector_crop,
    )

    frame = np.zeros((160, 240), dtype=np.uint8)
    frame[25:135, 55:185] = 120
    frame[3:7, 3:20] = 255  # isolated vendor/HUD glyph
    box = detect_sector_crop_box([frame])
    y0, x0, y1, x1 = box
    assert 7 < y0 <= 25 and 20 < x0 <= 55
    assert 135 <= y1 < 160 and 185 <= x1 < 240
    cropped = extract_canonical_sector_crop(frame, box=box)
    assert cropped.max() == 120


def test_view_preprocessing_masks_burned_ecg_before_resize() -> None:
    from echo_personal_tool.domain.services.burned_ecg_mask import (
        OVERRIDE_AUTO,
        store_burned_ecg_override,
    )
    from echo_personal_tool.domain.services.view_recognition_inference import mask_burned_ecg_in_frames

    store_burned_ecg_override(OVERRIDE_AUTO)
    rgb = np.full((160, 200, 3), 80, dtype=np.uint8)
    rgb[132:140, 15:185] = (10, 235, 15)
    for frame in (rgb, rgb.astype(np.float32) / 255):
        cleaned = mask_burned_ecg_in_frames([frame])[0]
        assert np.count_nonzero(cleaned[134, 100]) == 0
        np.testing.assert_array_equal(cleaned[:110], frame[:110])
        assert frame[134, 100, 1] > 0  # input never mutated


def test_view_augmentation_never_mirrors_chambers_and_is_seeded() -> None:
    from echo_personal_tool.domain.services.view_recognition_inference import augment_echo_view_clip

    clip = np.zeros((3, 96, 96), dtype=np.float32)
    clip[:, 30:70, 12:32] = 0.8
    for seed in range(30):
        result = augment_echo_view_clip(clip, rng=np.random.default_rng(seed))
        assert result.shape == clip.shape
        assert np.all((0 <= result) & (result <= 1))
        _, xs = np.where(result[0] > 0.1)
        assert xs.size > 50 and xs.mean() < 48
    np.testing.assert_array_equal(
        augment_echo_view_clip(clip, rng=np.random.default_rng(42)),
        augment_echo_view_clip(clip, rng=np.random.default_rng(42)),
    )


@pytest.mark.parametrize("gate", ["entropy", "confidence", "cosine"])
def test_ood_rejects_ambiguous_or_distant_prototypes(gate: str) -> None:
    from echo_personal_tool.domain.services.view_recognition_inference import aggregate_predictions_with_ood

    kwargs = {
        "entropy": {"max_entropy_ratio": 0.8},
        "confidence": {"min_confidence": 0.7},
        "cosine": {"min_cosine": 0.25, "cosine_similarities": np.array([[0.1, 0.05]])},
    }[gate]
    probs = np.array([[0.5, 0.5]]) if gate != "cosine" else np.array([[0.99, 0.01]])
    assert aggregate_predictions_with_ood(probs, ("RV_A4C", "SUBCOSTAL"), **kwargs).view == "UNKNOWN"


def test_ood_accepts_confident_extended_class() -> None:
    from echo_personal_tool.domain.services.view_recognition_inference import aggregate_predictions_with_ood

    result = aggregate_predictions_with_ood(
        np.array([[0.99, 0.01]]),
        ("RV_A4C", "SUBCOSTAL"),
        cosine_similarities=np.array([[0.8, 0.1]]),
        min_cosine=0.25,
        max_entropy_ratio=0.88,
        min_confidence=0.3,
    )
    assert result.view == "RV_A4C" and result.confidence == pytest.approx(0.99)


@pytest.mark.parametrize("dtype", [np.uint8, np.float32])
def test_rgb_phase_channels_remain_float32(dtype: type) -> None:
    from echo_personal_tool.domain.services.view_recognition_inference import (
        ViewInferenceConfig,
        prepare_clip_for_view_model,
    )

    rgb = np.empty((8, 8, 3), dtype=dtype)
    rgb[...] = [30, 60, 90] if dtype == np.uint8 else [0.1, 0.2, 0.3]
    config = ViewInferenceConfig(input_size=8, input_mode="phase_triplet")
    batch = prepare_clip_for_view_model([rgb], config=config)
    assert batch.dtype == np.float32
    np.testing.assert_allclose(batch, 60 / 255 if dtype == np.uint8 else 0.2, atol=1e-7)
