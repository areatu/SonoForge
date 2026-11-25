"""View-recognition inference and preprocessing helpers (pure, no Qt / no torch / no ORT).

Provides both the legacy v1 single-frame helpers and the canonical ML.0b
pipeline (issue #688, #639):

1. Burned-in vendor ECG strip suppression (:mod:`burned_ecg_mask`) + canonical
   ultrasound sector cone crop (:func:`detect_sector_crop_box`) so scanner UI
   glyphs and black margins do not drive view classification.
2. Dynamic 3-phase input ``[ED, mid-systole, ES]`` selected via
   :func:`build_phase_field` (#641) with deterministic quantile / static-frame
   fallback, encoding valve and wall motion into the 3 input channels at zero
   extra 2D convolution cost.
3. Exact train/serve ImageNet channel normalization parity
   (:func:`prepare_clip_for_view_model`).
4. Echo-safe clip augmentations (:func:`augment_echo_view_clip`) **without**
   horizontal mirroring (which swaps left/right chambers in echocardiography).
5. Prototype cosine similarity + normalized entropy OOD gating
   (:func:`aggregate_predictions_with_ood`) returning honest ``UNKNOWN`` on
   off-axis or non-cardiac clips.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
from scipy import ndimage

from echo_personal_tool.domain.models.view_recognition import (
    KNOWN_VIEWS,
    UNKNOWN_VIEW,
    RecognizedView,
)
from echo_personal_tool.domain.services.burned_ecg_mask import (
    OVERRIDE_OFF,
    detect_burned_ecg_strip,
    get_burned_ecg_override,
)
from echo_personal_tool.domain.services.phase_field import build_phase_field
from echo_personal_tool.domain.services.segment_roi import detect_view_sector_crop_box

IMAGENET_MEAN: tuple[float, float, float] = (0.485, 0.456, 0.406)
IMAGENET_STD: tuple[float, float, float] = (0.229, 0.224, 0.225)

INPUT_MODE_SINGLE_FRAME = "single_frame"
INPUT_MODE_PHASE_TRIPLET = "phase_triplet"


@dataclass(frozen=True)
class ViewInferenceConfig:
    """Shared train/serve preprocessing and OOD gating configuration."""

    input_size: int = 224
    input_mode: str = INPUT_MODE_SINGLE_FRAME
    sector_crop: bool = False
    normalize_imagenet: bool = False
    max_triplets: int = 3
    logit_scale: float | None = None
    ood_min_cosine: float | None = None
    ood_max_entropy_ratio: float | None = None
    ood_min_confidence: float | None = None

    @classmethod
    def ml0b_default(cls, *, input_size: int = 224) -> ViewInferenceConfig:
        """Recommended ML.0b configuration for newly trained prototype models."""
        return cls(
            input_size=input_size,
            input_mode=INPUT_MODE_PHASE_TRIPLET,
            sector_crop=True,
            normalize_imagenet=True,
            max_triplets=3,
            logit_scale=12.0,
            ood_min_cosine=0.25,
            ood_max_entropy_ratio=0.88,
            ood_min_confidence=0.30,
        )

    @classmethod
    def from_manifest_section(
        cls,
        section: Mapping[str, Any] | None,
        *,
        input_size: int = 224,
    ) -> ViewInferenceConfig:
        """Parse ``view_recognition`` manifest metadata; legacy manifests keep v1 defaults."""
        if not isinstance(section, Mapping):
            return cls(input_size=input_size)
        prep = section.get("preprocessing")
        ood = section.get("ood")
        prep_map = prep if isinstance(prep, Mapping) else {}
        ood_map = ood if isinstance(ood, Mapping) else {}
        raw_scale = section.get("logit_scale", ood_map.get("logit_scale"))
        raw_min_cos = ood_map.get("min_cosine")
        raw_max_ent = ood_map.get("max_entropy_ratio")
        raw_min_conf = ood_map.get("min_confidence")
        return cls(
            input_size=int(prep_map.get("input_size", input_size)),
            input_mode=str(prep_map.get("input_mode", INPUT_MODE_SINGLE_FRAME)),
            sector_crop=bool(prep_map.get("sector_crop", False)),
            normalize_imagenet=bool(prep_map.get("normalize_imagenet", False)),
            max_triplets=max(1, int(prep_map.get("max_triplets", 3))),
            logit_scale=float(raw_scale) if raw_scale is not None else None,
            ood_min_cosine=float(raw_min_cos) if raw_min_cos is not None else None,
            ood_max_entropy_ratio=float(raw_max_ent) if raw_max_ent is not None else None,
            ood_min_confidence=float(raw_min_conf) if raw_min_conf is not None else None,
        )

    def to_manifest_fields(self) -> dict[str, Any]:
        """Serialize preprocessing and OOD fields for ``io_contract.json`` / ``model_manifest.json``."""
        data: dict[str, Any] = {
            "preprocessing": {
                "input_size": self.input_size,
                "input_mode": self.input_mode,
                "sector_crop": self.sector_crop,
                "normalize_imagenet": self.normalize_imagenet,
                "max_triplets": self.max_triplets,
            }
        }
        if self.logit_scale is not None:
            data["logit_scale"] = self.logit_scale
        ood: dict[str, float] = {}
        if self.ood_min_cosine is not None:
            ood["min_cosine"] = self.ood_min_cosine
        if self.ood_max_entropy_ratio is not None:
            ood["max_entropy_ratio"] = self.ood_max_entropy_ratio
        if self.ood_min_confidence is not None:
            ood["min_confidence"] = self.ood_min_confidence
        if ood:
            data["ood"] = ood
        return data


def _to_grayscale_unit(frame: np.ndarray) -> np.ndarray:
    """Convert H×W or H×W×(1|3) frame to 2D float32 in ``[0, 1]``."""
    arr = np.asarray(frame)
    if arr.ndim == 2:
        gray = arr.astype(np.float32)
    elif arr.ndim == 3 and arr.shape[2] == 1:
        gray = arr[..., 0].astype(np.float32)
    elif arr.ndim == 3 and arr.shape[2] == 3:
        gray = np.mean(arr.astype(np.float32), axis=2)
    else:
        raise ValueError(f"frame must be H×W or H×W×3, got shape {arr.shape}")
    if float(gray.max()) > 1.0:
        gray = gray / 255.0
    return np.clip(gray, 0.0, 1.0).astype(np.float32, copy=False)


def mask_burned_ecg_in_frames(frames: Sequence[np.ndarray]) -> list[np.ndarray]:
    """Zero out a burned-in green vendor ECG strip across all frames of a clip."""
    if not frames:
        return []
    arrays = [np.asarray(f) for f in frames]
    if get_burned_ecg_override() == OVERRIDE_OFF:
        return arrays
    first = arrays[0]
    if first.ndim != 3 or first.shape[2] < 3 or min(first.shape[:2]) < 32:
        return arrays
    if not all(a.shape == first.shape for a in arrays):
        return arrays

    # burned_ecg_mask expects uint8-scale RGB intensities (> 60 green threshold)
    probe_frames = [
        (np.clip(a, 0.0, 1.0) * 255.0).astype(np.uint8) if float(a.max()) <= 1.0 else a.astype(np.uint8)
        for a in arrays[:12]
    ]
    strip = detect_burned_ecg_strip(probe_frames, n_frames=len(arrays))
    if strip is None:
        return arrays
    mask = strip.mask_for(first.shape)
    if not np.any(mask):
        return arrays
    cleaned: list[np.ndarray] = []
    for arr in arrays:
        copy = arr.copy()
        copy[mask] = 0
        cleaned.append(copy)
    return cleaned


def detect_sector_crop_box(
    frames: Sequence[np.ndarray],
    *,
    pad_ratio: float = 0.03,
) -> tuple[int, int, int, int]:
    """Locate the B-mode sector via shared ROI geometry, excluding isolated HUD glyphs."""
    if not frames:
        raise ValueError("clip is empty: at least one frame is required")
    indices = np.linspace(0, len(frames) - 1, num=min(len(frames), 8), dtype=int)
    gray_frames = [_to_grayscale_unit(frames[int(i)]) for i in indices]
    return detect_view_sector_crop_box(gray_frames, pad_ratio=pad_ratio)


def extract_canonical_sector_crop(
    frame: np.ndarray,
    *,
    box: tuple[int, int, int, int] | None = None,
) -> np.ndarray:
    """Crop ``frame`` to the ultrasound sector cone ``(y0, x0, y1, x1)``."""
    arr = np.asarray(frame)
    y0, x0, y1, x1 = box if box is not None else detect_sector_crop_box([arr])
    return arr[y0:y1, x0:x1]


def select_phase_triplet_indices(
    frames: Sequence[np.ndarray],
    *,
    max_triplets: int = 3,
) -> list[tuple[int, int, int]]:
    """Select ``(ed_idx, mid_systole_idx, es_idx)`` cardiac phase triplets.

    Uses :func:`build_phase_field` (#641) when periodic cardiac motion is
    detected, returning up to ``max_triplets`` beat triplets. Falls back to
    deterministic cycle quantiles ``(0, 0.35*(N-1), 0.70*(N-1))`` for short or
    aperiodic clips, and ``(0, 0, 0)`` for a single static frame.
    """
    n = len(frames)
    if n <= 0:
        raise ValueError("clip is empty: at least one frame is required")
    if n == 1:
        return [(0, 0, 0)]
    if n == 2:
        return [(0, 0, 1)]

    first_shape = np.asarray(frames[0]).shape[:2]
    uniform_shapes = all(np.asarray(f).shape[:2] == first_shape for f in frames)
    if n >= 6 and uniform_shapes and min(first_shape) >= 16:
        gray_small = np.stack(
            [cv2.resize(_to_grayscale_unit(f), (64, 64), interpolation=cv2.INTER_AREA) for f in frames],
            axis=0,
        )
        pf = build_phase_field(frames=gray_small)
        complete = [c for c in pf.cycles if not c.partial]
        chosen_cycles = complete[: max(1, max_triplets)]
        if not chosen_cycles:
            best = pf.best_cycle()
            if best is not None:
                chosen_cycles = [best]
        triplets: list[tuple[int, int, int]] = []
        for cycle in chosen_cycles:
            ed = int(np.clip(cycle.ed_frame, 0, n - 1))
            es = int(np.clip(cycle.es_frame, 0, n - 1))
            mid = int(np.clip((ed + es) // 2, 0, n - 1))
            triplets.append((ed, mid, es))
        if triplets:
            return triplets

    ed_q = 0
    mid_q = int(np.clip(round(0.35 * (n - 1)), 0, n - 1))
    es_q = int(np.clip(round(0.70 * (n - 1)), 0, n - 1))
    return [(ed_q, mid_q, es_q)]


def normalize_imagenet_nchw(batch_nchw: np.ndarray) -> np.ndarray:
    """Apply standard ImageNet ``(x - mean) / std`` normalization to ``(N, 3, H, W)``."""
    arr = np.asarray(batch_nchw, dtype=np.float32)
    if arr.ndim != 4 or arr.shape[1] != 3:
        raise ValueError(f"expected (N, 3, H, W) batch, got shape {arr.shape}")
    mean = np.array(IMAGENET_MEAN, dtype=np.float32).reshape(1, 3, 1, 1)
    std = np.array(IMAGENET_STD, dtype=np.float32).reshape(1, 3, 1, 1)
    return ((arr - mean) / std).astype(np.float32, copy=False)


def preprocess_frame(frame: np.ndarray, input_size: int) -> np.ndarray:
    """Resize a single frame to ``(input_size, input_size, 3)`` float32 in ``[0, 1]``."""
    array = np.asarray(frame)
    if array.ndim == 2:
        array = np.stack([array] * 3, axis=-1)
    elif array.ndim == 3 and array.shape[2] == 1:
        array = np.repeat(array, 3, axis=2)
    elif array.ndim != 3 or array.shape[2] != 3:
        raise ValueError(f"frame must be H×W or H×W×3, got shape {array.shape}")
    resized = cv2.resize(array, (input_size, input_size), interpolation=cv2.INTER_AREA)
    if resized.max() > 1.0:
        resized = resized.astype(np.float32) / 255.0
    else:
        resized = resized.astype(np.float32)
    return resized


def clip_to_batch(frames: Sequence[np.ndarray], input_size: int) -> np.ndarray:
    """Stack ``frames`` into a ``(N, input_size, input_size, 3)`` float32 batch."""
    if not frames:
        raise ValueError("clip is empty: at least one frame is required")
    prepared = [preprocess_frame(frame, input_size) for frame in frames]
    return np.stack(prepared, axis=0)


def batch_to_channels(batch: np.ndarray) -> np.ndarray:
    """Transpose a ``(N, H, W, 3)`` batch to the model's ``(N, 3, H, W)`` layout."""
    return np.transpose(batch, (0, 3, 1, 2))


def prepare_clip_for_view_model(
    frames: Sequence[np.ndarray],
    *,
    config: ViewInferenceConfig | None = None,
) -> np.ndarray:
    """Unified train/serve tensor builder returning ``(B, 3, input_size, input_size)``.

    * Legacy ``single_frame`` mode without ``sector_crop`` / ``normalize_imagenet``
      behaves identically to ``batch_to_channels(clip_to_batch(frames, input_size))``.
    * ``phase_triplet`` mode suppresses burned-in ECG traces, crops to the
      clip-level canonical ultrasound sector cone, builds ``[ED, mid, ES]``
      3-channel tensors, and applies ImageNet channel normalization.
    """
    if not frames:
        raise ValueError("clip is empty: at least one frame is required")
    cfg = config if config is not None else ViewInferenceConfig()

    work_frames: Sequence[np.ndarray] = frames
    if cfg.sector_crop or cfg.input_mode == INPUT_MODE_PHASE_TRIPLET:
        work_frames = mask_burned_ecg_in_frames(work_frames)

    crop_box: tuple[int, int, int, int] | None = None
    if cfg.sector_crop:
        crop_box = detect_sector_crop_box(work_frames)

    if cfg.input_mode == INPUT_MODE_PHASE_TRIPLET:
        phase_frames = (
            [extract_canonical_sector_crop(f, box=crop_box) for f in work_frames]
            if crop_box is not None
            else work_frames
        )
        triplets = select_phase_triplet_indices(phase_frames, max_triplets=cfg.max_triplets)
        samples_nchw: list[np.ndarray] = []
        for ed_i, mid_i, es_i in triplets:
            channels: list[np.ndarray] = []
            for idx in (ed_i, mid_i, es_i):
                raw_f = work_frames[idx]
                cropped = extract_canonical_sector_crop(raw_f, box=crop_box) if crop_box is not None else raw_f
                gray = _to_grayscale_unit(cropped)
                resized = cv2.resize(
                    gray,
                    (cfg.input_size, cfg.input_size),
                    interpolation=cv2.INTER_AREA,
                ).astype(np.float32)
                channels.append(resized)
            samples_nchw.append(np.stack(channels, axis=0))
        batch_nchw = np.stack(samples_nchw, axis=0).astype(np.float32)
    else:
        cropped_frames = (
            [extract_canonical_sector_crop(f, box=crop_box) for f in work_frames]
            if crop_box is not None
            else work_frames
        )
        batch_nchw = batch_to_channels(clip_to_batch(cropped_frames, cfg.input_size)).astype(np.float32, copy=False)

    if cfg.normalize_imagenet:
        batch_nchw = normalize_imagenet_nchw(batch_nchw)
    return np.ascontiguousarray(batch_nchw, dtype=np.float32)


def _warp_frame_around_apex(
    frame_2d: np.ndarray,
    *,
    angle_deg: float,
    scale: float,
    tx_px: float,
    ty_px: float,
) -> np.ndarray:
    height, width = frame_2d.shape
    pivot = np.array([0.0, (width - 1) / 2.0], dtype=np.float64)
    theta = math.radians(angle_deg)
    inv_s = 1.0 / max(scale, 1e-3)
    mat = np.array(
        [[math.cos(theta) * inv_s, math.sin(theta) * inv_s], [-math.sin(theta) * inv_s, math.cos(theta) * inv_s]],
        dtype=np.float64,
    )
    shift = np.array([ty_px, tx_px], dtype=np.float64)
    offset = pivot - mat @ (pivot + shift)
    return np.asarray(
        ndimage.affine_transform(frame_2d, mat, offset=offset, order=1, mode="constant", cval=0.0),
        dtype=np.float32,
    )


def augment_echo_view_clip(
    clip: np.ndarray,
    *,
    rng: np.random.Generator | None = None,
    frame_jitter: bool = False,
) -> np.ndarray:
    """Apply temporally coherent ultrasound sector augmentations without H-flip.

    Horizontal flipping is strictly excluded so left/right cardiac chambers
    never invert (preserving ``A4C`` vs ``RV_A4C`` vs ``A3C`` geometry).
    """
    arr = np.asarray(clip, dtype=np.float32)
    if arr.size == 0 or arr.shape[0] == 0:
        return arr
    gen = rng if rng is not None else np.random.default_rng()
    frames = [arr[i].copy() for i in range(arr.shape[0])]

    if frame_jitter and len(frames) >= 3:
        low, high = len(frames) // 4, (3 * len(frames)) // 4
        other = int(gen.integers(low, max(low + 1, high + 1)))
        middle = len(frames) // 2
        frames[middle], frames[other] = frames[other], frames[middle]

    angle = float(gen.uniform(-10.0, 10.0))
    scale = float(gen.uniform(0.92, 1.08))
    tx_frac = float(gen.uniform(-0.04, 0.04))
    ty_frac = float(gen.uniform(-0.04, 0.04))
    gamma = float(gen.uniform(0.85, 1.18))
    top_tgc = float(gen.uniform(0.88, 1.12))
    bot_tgc = float(gen.uniform(0.88, 1.12))
    speckle_sigma = float(gen.uniform(0.01, 0.045))
    apply_rib_shadow = float(gen.random()) < 0.35
    shadow_angle = float(gen.uniform(-0.45, 0.45))
    shadow_width = float(gen.uniform(0.06, 0.14))
    shadow_atten = float(gen.uniform(0.35, 0.70))

    height, width = frames[0].shape[:2]
    tgc_ramp = np.linspace(top_tgc, bot_tgc, height, dtype=np.float32)
    rib_mask: np.ndarray | None = None
    if apply_rib_shadow and min(height, width) >= 8:
        yy, xx = np.meshgrid(
            np.linspace(1.0, float(height), height, dtype=np.float32),
            np.linspace(-1.0, 1.0, width, dtype=np.float32),
            indexing="ij",
        )
        beam_angle = np.arctan2(xx * (width / 2.0), yy)
        rib_mask = 1.0 - (1.0 - shadow_atten) * np.exp(
            -0.5 * ((beam_angle - shadow_angle) / max(shadow_width, 1e-3)) ** 2
        )

    out_frames: list[np.ndarray] = []
    for frame in frames:
        max_val = float(frame.max())
        peak = 255.0 if max_val > 1.5 else 1.0
        unit = np.clip(frame / peak, 0.0, 1.0)
        if unit.ndim == 2:
            warped = _warp_frame_around_apex(
                unit,
                angle_deg=angle,
                scale=scale,
                tx_px=tx_frac * width,
                ty_px=ty_frac * height,
            )
            warped = warped * tgc_ramp[:, None]
            if rib_mask is not None:
                warped = warped * rib_mask
        else:
            channels = [
                _warp_frame_around_apex(
                    unit[..., c],
                    angle_deg=angle,
                    scale=scale,
                    tx_px=tx_frac * width,
                    ty_px=ty_frac * height,
                )
                for c in range(unit.shape[2])
            ]
            warped = np.stack(channels, axis=-1) * tgc_ramp[:, None, None]
            if rib_mask is not None:
                warped = warped * rib_mask[:, :, None]

        warped = np.power(np.clip(warped, 0.0, 1.0), gamma, dtype=np.float32)
        noise = gen.normal(0.0, speckle_sigma, size=warped.shape).astype(np.float32)
        warped = np.clip(warped + noise * warped, 0.0, 1.0) * peak
        out_frames.append(warped.astype(np.float32))

    return np.stack(out_frames, axis=0)


def aggregate_predictions(
    probs: np.ndarray,
    class_names: Sequence[str] = KNOWN_VIEWS,
) -> RecognizedView:
    """Aggregate per-frame class probabilities into one :class:`RecognizedView`."""
    return aggregate_predictions_with_ood(probs, class_names)


def aggregate_predictions_with_ood(
    probs: np.ndarray,
    class_names: Sequence[str] = KNOWN_VIEWS,
    *,
    cosine_similarities: np.ndarray | None = None,
    min_cosine: float | None = None,
    max_entropy_ratio: float | None = None,
    min_confidence: float | None = None,
) -> RecognizedView:
    """Aggregate probabilities with optional prototype cosine & entropy OOD gates.

    When OOD gates are configured and the clip lies far from every canonical
    view prototype (``max_cosine < min_cosine``), exhibits near-uniform high
    entropy (``H / ln(C) > max_entropy_ratio``), or falls below ``min_confidence``,
    returns ``RecognizedView(UNKNOWN_VIEW, confidence)`` instead of guessing.
    """
    array = np.asarray(probs, dtype=np.float64)
    if array.ndim != 2:
        raise ValueError(f"probs must be (N, C), got shape {array.shape}")
    if array.size == 0:
        raise ValueError("probs is empty")
    names = tuple(class_names)
    if array.shape[1] != len(names):
        raise ValueError(f"probs has {array.shape[1]} columns but class_names has {len(names)}")

    median = np.median(array, axis=0)
    index = int(np.argmax(median))
    best_prob = float(median[index])

    if min_confidence is not None and best_prob < float(min_confidence):
        return RecognizedView(UNKNOWN_VIEW, best_prob)

    if max_entropy_ratio is not None and len(names) > 1:
        total = float(median.sum())
        dist = median / total if total > 1e-12 else np.full(len(names), 1.0 / len(names))
        clipped = np.clip(dist, 1e-12, 1.0)
        entropy = float(-np.sum(clipped * np.log(clipped)))
        norm_entropy = entropy / math.log(len(names))
        if norm_entropy > float(max_entropy_ratio):
            return RecognizedView(UNKNOWN_VIEW, best_prob)

    if min_cosine is not None and cosine_similarities is not None:
        cos_arr = np.asarray(cosine_similarities, dtype=np.float64)
        if cos_arr.shape == array.shape:
            median_cos = np.median(cos_arr, axis=0)
            if float(np.max(median_cos)) < float(min_cosine):
                return RecognizedView(UNKNOWN_VIEW, best_prob)

    return RecognizedView(names[index], best_prob)
