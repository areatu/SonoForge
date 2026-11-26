"""Shared train/serve preprocessing and split helpers for chamber segmentation.

Unifies the tensor preparation path used by :class:`OnnxInferenceEngine` at
inference time and by ``scripts/finetune_la_seg.py`` / ``scripts/finetune_lv_seg.py``
at training time (issue #687):

1. Suppress burned-in vendor ECG strips (:mod:`burned_ecg_mask`) before ROI
   cropping and per-frame normalization so bright trace pixels never skew
   channel statistics or masquerade as atrial/basal walls.
2. Crop frame and mask with the exact same :class:`EchoNetCropTransform`.
3. Apply optional echo-safe spatial/photometric augmentations **without**
   horizontal flipping (which swaps left/right cardiac chambers) and **before**
   calling :func:`prepare_tensor`, preserving exact ``train == serve``
   z-score / fixed normalization parity.
4. Provide deterministic, leak-free ``study_uid`` group splitting and
   backbone state-dict head filtering so fine-tuning never resets a pretrained
   encoder to random weights when replacing the 1-class output layer.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from pathlib import PurePath
from typing import Any

import numpy as np
from scipy import ndimage

from echo_personal_tool.domain.services.burned_ecg_mask import (
    OVERRIDE_OFF,
    BurnedEcgStrip,
    detect_burned_ecg_strip,
    get_burned_ecg_override,
)
from echo_personal_tool.domain.services.segmentation_service import (
    EchoNetCropMode,
    EchoNetCropTransform,
    crop_frame_for_echonet,
    prepare_tensor,
)

#: Supported apical views for biplane LA segmentation (#548, #644).
LA_SUPPORTED_VIEWS: frozenset[str] = frozenset({"A4C", "A2C"})


def mask_burned_ecg_for_segmentation(
    frame: np.ndarray,
    *,
    ecg_strip: BurnedEcgStrip | None = None,
) -> np.ndarray:
    """Zero out a burned-in vendor ECG strip on ``frame`` when present.

    Respects the session override (:func:`get_burned_ecg_override`). On
    grayscale frames without an explicit ``ecg_strip`` or on clean frames
    with no green ECG signature, returns ``frame`` unchanged (no copy when
    already ``ndarray``).
    """
    array = np.asarray(frame)
    if array.ndim not in (2, 3) or min(array.shape[:2]) < 32:
        return array
    if ecg_strip is None:
        if get_burned_ecg_override() == OVERRIDE_OFF:
            return array
        if array.ndim != 3 or array.shape[2] < 3:
            return array
        ecg_strip = detect_burned_ecg_strip([array])
    if ecg_strip is None:
        return array

    strip_mask = ecg_strip.mask_for(array.shape)
    if not np.any(strip_mask):
        return array

    cleaned = array.copy()
    cleaned[strip_mask] = 0
    return cleaned


def prepare_segmentation_input(
    frame: np.ndarray,
    *,
    roi_xyxy: tuple[float, float, float, float] | None = None,
    crop_mode: str | EchoNetCropMode = EchoNetCropMode.CENTER_SQUARE,
    target_size: int = 112,
    fixed_mean: list[float] | None = None,
    fixed_std: list[float] | None = None,
    ecg_strip: BurnedEcgStrip | None = None,
) -> tuple[np.ndarray, EchoNetCropTransform]:
    """Canonical serve/train forward preprocessing: ECG-mask -> crop -> NCHW tensor."""
    cleaned = mask_burned_ecg_for_segmentation(frame, ecg_strip=ecg_strip)
    cropped, transform = crop_frame_for_echonet(
        cleaned,
        roi_xyxy=roi_xyxy,
        crop_mode=crop_mode,
    )
    tensor = prepare_tensor(
        cropped,
        target_size=target_size,
        fixed_mean=fixed_mean,
        fixed_std=fixed_std,
    )
    return tensor, transform


def resize_binary_mask(mask: np.ndarray, *, target_size: int) -> np.ndarray:
    """Nearest-neighbor resize of a 2D binary mask to ``(target_size, target_size)``."""
    binary = (np.asarray(mask) > 0).astype(np.uint8)
    if binary.ndim != 2:
        msg = f"mask must be 2D H×W, got shape {binary.shape}"
        raise ValueError(msg)
    height, width = binary.shape
    if height == 0 or width == 0:
        msg = "mask must have non-zero height and width"
        raise ValueError(msg)
    if (height, width) == (target_size, target_size):
        return binary
    zoom_y = target_size / height
    zoom_x = target_size / width
    resized = np.asarray(ndimage.zoom(binary, (zoom_y, zoom_x), order=0), dtype=np.uint8)
    return (resized > 0).astype(np.uint8)


def _warp_sector_around_apex(
    image: np.ndarray,
    *,
    angle_deg: float,
    scale: float,
    order: int,
) -> np.ndarray:
    """Rotate/scale 2D or 3D image around top-center ultrasound probe apex."""
    height, width = image.shape[:2]
    pivot_y = 0.0
    pivot_x = (width - 1) / 2.0
    theta = math.radians(angle_deg)
    cos_t = math.cos(theta) / max(scale, 1e-3)
    sin_t = math.sin(theta) / max(scale, 1e-3)
    rot_2d = np.array([[cos_t, sin_t], [-sin_t, cos_t]], dtype=np.float64)
    center = np.array([pivot_y, pivot_x], dtype=np.float64)
    offset_2d = center - rot_2d @ center

    if image.ndim == 2:
        return np.asarray(
            ndimage.affine_transform(
                image,
                rot_2d,
                offset=offset_2d,
                order=order,
                mode="constant",
                cval=0.0,
            ),
            dtype=image.dtype,
        )

    channels = [
        np.asarray(
            ndimage.affine_transform(
                image[..., c],
                rot_2d,
                offset=offset_2d,
                order=order,
                mode="constant",
                cval=0.0,
            ),
            dtype=image.dtype,
        )
        for c in range(image.shape[2])
    ]
    return np.stack(channels, axis=-1)


def augment_echo_segmentation_crop(
    cropped_frame: np.ndarray,
    cropped_mask: np.ndarray,
    *,
    rng: np.random.Generator | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Apply echo-safe spatial and acoustic augmentations without horizontal flip.

    Horizontal mirroring is intentionally forbidden: in apical and parasternal
    views it swaps septal/lateral walls and left/right chambers. Augmentations
    operate on raw intensity before :func:`prepare_tensor` so output statistics
    remain identical to inference-time normalization.
    """
    gen = rng if rng is not None else np.random.default_rng()
    frame_f = np.asarray(cropped_frame, dtype=np.float32)
    mask_u8 = (np.asarray(cropped_mask) > 0).astype(np.uint8)

    # 1. Small fan rotation (±10°) and depth scale (0.93..1.07) around probe apex
    if float(gen.random()) < 0.8:
        angle = float(gen.uniform(-10.0, 10.0))
        scale = float(gen.uniform(0.93, 1.07))
        frame_f = _warp_sector_around_apex(frame_f, angle_deg=angle, scale=scale, order=1)
        mask_u8 = (
            _warp_sector_around_apex(mask_u8.astype(np.float32), angle_deg=angle, scale=scale, order=0) > 0.5
        ).astype(np.uint8)

    max_val = float(frame_f.max())
    scale_peak = 255.0 if max_val > 1.5 else 1.0
    unit = np.clip(frame_f / max(scale_peak, 1e-6), 0.0, 1.0)

    # 2. Smooth depth TGC ramp along rows
    if float(gen.random()) < 0.6:
        height = unit.shape[0]
        top_gain = float(gen.uniform(0.85, 1.15))
        bottom_gain = float(gen.uniform(0.85, 1.15))
        ramp = np.linspace(top_gain, bottom_gain, height, dtype=np.float32)
        unit = unit * (ramp[:, None] if unit.ndim == 2 else ramp[:, None, None])

    # 3. Gamma compression / log-compression variation
    if float(gen.random()) < 0.6:
        gamma = float(gen.uniform(0.78, 1.30))
        unit = np.power(np.clip(unit, 0.0, 1.0), gamma, dtype=np.float32)

    # 4. Lateral wall / rib shadow attenuation wedge (simulates acoustic dropout)
    if float(gen.random()) < 0.35 and unit.shape[1] >= 16:
        width = unit.shape[1]
        center_x = float(gen.uniform(0.1 * width, 0.9 * width))
        sigma_x = float(gen.uniform(0.06 * width, 0.16 * width))
        attenuation = float(gen.uniform(0.35, 0.70))
        xs = np.arange(width, dtype=np.float32)
        dip = 1.0 - (1.0 - attenuation) * np.exp(-0.5 * ((xs - center_x) / max(sigma_x, 1.0)) ** 2)
        unit = unit * (dip[None, :] if unit.ndim == 2 else dip[None, :, None])

    # 5. Multiplicative Rayleigh-like speckle perturbation
    if float(gen.random()) < 0.6:
        sigma = float(gen.uniform(0.02, 0.07))
        noise = gen.normal(0.0, sigma, size=unit.shape).astype(np.float32)
        unit = unit + noise * unit

    restored = np.clip(unit, 0.0, 1.0) * scale_peak
    return restored.astype(np.float32), mask_u8


def prepare_training_pair(
    frame: np.ndarray,
    mask: np.ndarray,
    *,
    roi_xyxy: tuple[float, float, float, float] | None = None,
    crop_mode: str | EchoNetCropMode = EchoNetCropMode.CENTER_SQUARE,
    target_size: int = 112,
    fixed_mean: list[float] | None = None,
    fixed_std: list[float] | None = None,
    ecg_strip: BurnedEcgStrip | None = None,
    augment: bool = False,
    rng: np.random.Generator | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Prepare ``(input_chw_float32, mask_1hw_float32)`` with exact serve parity.

    When ``augment=False``, ``input_chw_float32`` equals
    ``prepare_segmentation_input(...)[0][0]`` up to floating-point identity.
    """
    cleaned = mask_burned_ecg_for_segmentation(frame, ecg_strip=ecg_strip)
    cropped_frame, transform = crop_frame_for_echonet(
        cleaned,
        roi_xyxy=roi_xyxy,
        crop_mode=crop_mode,
    )
    mask_arr = (np.asarray(mask) > 0).astype(np.uint8)
    cropped_mask = mask_arr[
        transform.crop_y0 : transform.crop_y0 + transform.crop_height,
        transform.crop_x0 : transform.crop_x0 + transform.crop_width,
    ]
    if augment:
        cropped_frame, cropped_mask = augment_echo_segmentation_crop(
            cropped_frame,
            cropped_mask,
            rng=rng,
        )

    tensor_nchw = prepare_tensor(
        cropped_frame,
        target_size=target_size,
        fixed_mean=fixed_mean,
        fixed_std=fixed_std,
    )
    resized_mask = resize_binary_mask(cropped_mask, target_size=target_size)
    return tensor_nchw[0], resized_mask[np.newaxis, :, :].astype(np.float32)


def infer_study_group_key(record: Mapping[str, Any]) -> str:
    """Derive a patient/study-level grouping key so splits never leak frames.

    Priority:
    1. Explicit ``study_uid`` or ``study_id`` field when non-empty.
    2. DICOM UID prefix before the last two dot-separated components when
       ``sop_instance_uid`` / ``sample_id`` looks like a multi-part UID.
    3. Parent directory + stem prefix of ``instance_path``.
    """
    for key in ("study_uid", "study_id"):
        raw = str(record.get(key, "") or "").strip()
        if raw:
            return raw

    for uid_key in ("sop_instance_uid", "sample_id"):
        uid = str(record.get(uid_key, "") or "").strip()
        parts = uid.split(".")
        if len(parts) >= 6 and all(part.isdigit() for part in parts[:4]):
            return ".".join(parts[:-2])

    instance_path = str(record.get("instance_path", "") or "").strip()
    if instance_path:
        pure = PurePath(instance_path)
        return f"{pure.parent.name}/{pure.stem}"
    return "unknown_study"


def split_samples_by_study(
    samples: Sequence[dict[str, Any]],
    *,
    val_ratio: float = 0.2,
    seed: int = 42,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Deterministic group split keeping every ``study_uid`` in one split only.

    When fewer than 2 distinct study groups exist or ``val_ratio <= 0``, all
    samples stay in ``train`` and ``val`` is empty.
    """
    if not 0.0 <= val_ratio < 1.0:
        msg = f"val_ratio must be in [0, 1), got {val_ratio}"
        raise ValueError(msg)
    if not samples or val_ratio == 0.0:
        return list(samples), []

    groups: dict[str, list[dict[str, Any]]] = {}
    for sample in samples:
        key = infer_study_group_key(sample)
        groups.setdefault(key, []).append(sample)

    group_keys = sorted(groups.keys())
    if len(group_keys) < 2:
        return list(samples), []

    rng = random.Random(seed)
    rng.shuffle(group_keys)
    n_val = max(1, min(len(group_keys) - 1, int(round(len(group_keys) * val_ratio))))
    val_keys = set(group_keys[:n_val])

    train_out: list[dict[str, Any]] = []
    val_out: list[dict[str, Any]] = []
    for sample in samples:
        if infer_study_group_key(sample) in val_keys:
            val_out.append(sample)
        else:
            train_out.append(sample)
    return train_out, val_out


def filter_segmentation_backbone_state_dict(
    checkpoint_state: Mapping[str, Any],
    target_state: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Keep pretrained encoder/ASPP weights whose shapes match ``target_state``.

    Strips ``module.`` DataParallel prefixes, drops ``aux_classifier.*`` keys,
    and skips mismatched final classifier layers (e.g. 21-class -> 1-class)
    instead of discarding the entire ResNet50 backbone. Raises ``ValueError``
    if zero ``backbone.*`` tensors matched.
    """
    filtered: dict[str, Any] = {}
    skipped: list[str] = []
    backbone_matched = 0

    for raw_key, tensor in checkpoint_state.items():
        key = str(raw_key).removeprefix("module.")
        if key.startswith("aux_classifier."):
            skipped.append(key)
            continue
        if key not in target_state:
            skipped.append(key)
            continue
        src_shape = getattr(tensor, "shape", None)
        dst_shape = getattr(target_state[key], "shape", None)
        if src_shape is None or dst_shape is None or tuple(src_shape) != tuple(dst_shape):
            skipped.append(key)
            continue
        filtered[key] = tensor
        if key.startswith("backbone."):
            backbone_matched += 1

    if backbone_matched == 0:
        msg = "checkpoint did not match any 'backbone.*' parameters in target model"
        raise ValueError(msg)

    return filtered, skipped
