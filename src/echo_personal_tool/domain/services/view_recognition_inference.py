"""View-recognition inference helpers (pure, no Qt / no torch / no ORT).

Frame preprocessing and prediction aggregation for the view classifier:
resize a frame to the model's input size, batch a clip's frames into the
tensor the ONNX model expects, and aggregate per-frame logits into a single
:class:`RecognizedView`.

Keeping this in the domain layer means the same preprocessing is used by
training, evaluation and the ONNX adapter, and the aggregation rule (mean
softmax over frames) is unit-tested without any model stack installed
(#639 step 2).
"""

from __future__ import annotations

from collections.abc import Sequence

import cv2
import numpy as np

from echo_personal_tool.domain.models.view_recognition import (
    KNOWN_VIEWS,
    RecognizedView,
)


def preprocess_frame(frame: np.ndarray, input_size: int) -> np.ndarray:
    """Resize a single frame to ``(input_size, input_size)`` float32.

    Grayscale frames are converted to a 3-channel image (replicated), so the
    same pipeline serves monochrome and RGB inputs. The output range is the
    ``[0, 1]`` clip scale used everywhere in the view-recognition pipeline.
    """
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


def aggregate_predictions(
    probs: np.ndarray,
    class_names: Sequence[str] = KNOWN_VIEWS,
) -> RecognizedView:
    """Aggregate per-frame class probabilities into one :class:`RecognizedView`.

    ``probs`` is ``(N, C)`` non-negative class probabilities per frame. The
    clip's prediction is the mean probability vector: every frame votes with
    its full distribution, which is stable when frame counts vary and never
    silently drops frames. The confidence is the winning class' mean
    probability.
    """
    array = np.asarray(probs, dtype=np.float64)
    if array.ndim != 2:
        raise ValueError(f"probs must be (N, C), got shape {array.shape}")
    if array.size == 0:
        raise ValueError("probs is empty")
    names = tuple(class_names)
    if array.shape[1] != len(names):
        raise ValueError(f"probs has {array.shape[1]} columns but class_names has {len(names)}")
    mean = array.mean(axis=0)
    index = int(np.argmax(mean))
    return RecognizedView(names[index], float(mean[index]))
