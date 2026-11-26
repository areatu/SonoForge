"""Pure-core unit tests for segmentation train/serve parity and ML.0a fixes (#687)."""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.services.burned_ecg_mask import (
    OVERRIDE_AUTO,
    OVERRIDE_OFF,
    store_burned_ecg_override,
)
from echo_personal_tool.domain.services.segmentation_preprocess import (
    LA_SUPPORTED_VIEWS,
    augment_echo_segmentation_crop,
    filter_segmentation_backbone_state_dict,
    infer_study_group_key,
    mask_burned_ecg_for_segmentation,
    prepare_segmentation_input,
    prepare_training_pair,
    resize_binary_mask,
    split_samples_by_study,
)


def _frame_with_burned_green_ecg(height: int = 160, width: int = 200) -> np.ndarray:
    """Synthetic color B-mode frame with a wide green vendor ECG strip at bottom."""
    rng = np.random.default_rng(7)
    gray = rng.integers(25, 140, size=(height, width), dtype=np.uint8)
    rgb = np.stack([gray, gray, gray], axis=-1)
    # Draw wide green ECG band in the lower strip zone (rows 132..140, cols 15..185)
    rgb[132:140, 15:185, 0] = 10
    rgb[132:140, 15:185, 1] = 235
    rgb[132:140, 15:185, 2] = 15
    return rgb


def test_train_and_serve_tensors_match_within_1e6_with_burned_ecg() -> None:
    store_burned_ecg_override(OVERRIDE_AUTO)
    frame = _frame_with_burned_green_ecg()
    mask = np.zeros(frame.shape[:2], dtype=np.uint8)
    mask[40:110, 60:140] = 1
    roi = (10.0, 10.0, 190.0, 155.0)

    serve_tensor, _ = prepare_segmentation_input(
        frame,
        roi_xyxy=roi,
        crop_mode="full_roi",
        target_size=224,
    )
    train_chw, train_mask = prepare_training_pair(
        frame,
        mask,
        roi_xyxy=roi,
        crop_mode="full_roi",
        target_size=224,
        augment=False,
    )

    max_diff = float(np.max(np.abs(train_chw - serve_tensor[0])))
    assert max_diff < 1e-6
    assert train_chw.shape == (3, 224, 224)
    assert train_mask.shape == (1, 224, 224)
    assert set(np.unique(train_mask)).issubset({0.0, 1.0})


def test_mask_burned_ecg_zeros_green_strip_and_respects_override() -> None:
    frame = _frame_with_burned_green_ecg()
    try:
        store_burned_ecg_override(OVERRIDE_AUTO)
        cleaned = mask_burned_ecg_for_segmentation(frame)
        assert int(cleaned[134, 100, 1]) == 0
        # Tissue pixels above the strip remain untouched
        assert np.array_equal(cleaned[:110], frame[:110])

        store_burned_ecg_override(OVERRIDE_OFF)
        unmasked = mask_burned_ecg_for_segmentation(frame)
        assert int(unmasked[134, 100, 1]) == 235
    finally:
        store_burned_ecg_override(OVERRIDE_AUTO)


def test_augmentation_never_flips_left_right_anatomy() -> None:
    """Septal/left chamber placed strictly in left half stays in left half across seeds."""
    height, width = 128, 128
    frame = np.zeros((height, width), dtype=np.float32)
    mask = np.zeros((height, width), dtype=np.uint8)
    # Place asymmetric chamber strictly on the left side (cols 18..46)
    frame[36:96, 18:46] = 200.0
    mask[36:96, 18:46] = 1

    for seed in range(40):
        rng = np.random.default_rng(seed)
        aug_frame, aug_mask = augment_echo_segmentation_crop(frame, mask, rng=rng)
        ys, xs = np.where(aug_mask > 0)
        assert xs.size > 50
        centroid_x = float(xs.mean())
        assert centroid_x < width * 0.5, f"seed {seed} mirrored left chamber to x={centroid_x}"
        assert aug_frame.shape == frame.shape


def test_split_samples_by_study_prevents_study_leakage() -> None:
    samples = [
        {"study_uid": "study_A", "frame_index": 0},
        {"study_uid": "study_A", "frame_index": 12},
        {"study_uid": "study_B", "frame_index": 3},
        {"study_uid": "study_B", "frame_index": 18},
        {"study_uid": "study_C", "frame_index": 5},
        {"study_uid": "study_D", "frame_index": 9},
        {"study_uid": "study_E", "frame_index": 11},
    ]
    train_split, val_split = split_samples_by_study(samples, val_ratio=0.25, seed=42)
    train_studies = {infer_study_group_key(s) for s in train_split}
    val_studies = {infer_study_group_key(s) for s in val_split}

    assert len(train_split) + len(val_split) == len(samples)
    assert len(val_studies) >= 1
    assert train_studies.isdisjoint(val_studies)


def test_infer_study_group_key_groups_dicom_series_from_same_study() -> None:
    s1 = {"sop_instance_uid": "1.2.410.200001.1.1185.20251024.1091321961.124.16"}
    s2 = {"sop_instance_uid": "1.2.410.200001.1.1185.20251024.1091321961.974.19"}
    other = {"sop_instance_uid": "1.2.410.200001.1.1185.20251110.1132545058.799.26"}

    assert infer_study_group_key(s1) == infer_study_group_key(s2)
    assert infer_study_group_key(s1) != infer_study_group_key(other)


def test_filter_backbone_state_dict_preserves_encoder_and_skips_head_mismatch() -> None:
    target_state = {
        "backbone.conv1.weight": np.zeros((64, 3, 7, 7), dtype=np.float32),
        "backbone.layer1.0.conv1.weight": np.zeros((64, 64, 1, 1), dtype=np.float32),
        "classifier.0.convs.0.0.weight": np.zeros((256, 2048, 1, 1), dtype=np.float32),
        "classifier.4.weight": np.zeros((1, 256, 1, 1), dtype=np.float32),
        "classifier.4.bias": np.zeros((1,), dtype=np.float32),
    }
    checkpoint_state = {
        "module.backbone.conv1.weight": np.ones((64, 3, 7, 7), dtype=np.float32),
        "module.backbone.layer1.0.conv1.weight": np.ones((64, 64, 1, 1), dtype=np.float32),
        "module.classifier.0.convs.0.0.weight": np.full((256, 2048, 1, 1), 2.0, dtype=np.float32),
        # Mismatched 21-class head + auxiliary head must be cleanly skipped
        "module.classifier.4.weight": np.ones((21, 256, 1, 1), dtype=np.float32),
        "module.classifier.4.bias": np.ones((21,), dtype=np.float32),
        "module.aux_classifier.4.weight": np.ones((21, 256, 1, 1), dtype=np.float32),
    }

    filtered, skipped = filter_segmentation_backbone_state_dict(checkpoint_state, target_state)

    assert set(filtered.keys()) == {
        "backbone.conv1.weight",
        "backbone.layer1.0.conv1.weight",
        "classifier.0.convs.0.0.weight",
    }
    assert "classifier.4.weight" in skipped
    assert "aux_classifier.4.weight" in skipped


def test_filter_backbone_state_dict_rejects_empty_backbone_match() -> None:
    target_state = {"backbone.conv1.weight": np.zeros((64, 3, 7, 7), dtype=np.float32)}
    bad_checkpoint = {"unrelated.weight": np.ones((4, 4), dtype=np.float32)}

    with pytest.raises(ValueError, match="backbone"):
        filter_segmentation_backbone_state_dict(bad_checkpoint, target_state)


def test_resize_binary_mask_validates_dimensions_and_supported_la_views() -> None:
    assert LA_SUPPORTED_VIEWS == frozenset({"A4C", "A2C"})
    with pytest.raises(ValueError, match="2D"):
        resize_binary_mask(np.zeros((4, 4, 1), dtype=np.uint8), target_size=8)
