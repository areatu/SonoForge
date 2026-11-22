"""Locate the vendor ECG strip burned into the clip's pixels (plan А.5, issue #643).

Vendor apical clips often carry an ECG strip drawn straight into the video
pixels with no DICOM waveform tags behind it.  Two failure modes motivated
this module (the user's screenshots):

* the strip sits in the black zone below the sector — harmless to look at,
  but any pixel-domain signal (dark pool, intensity, optical flow) reads its
  flicker as tissue motion;
* the strip is drawn *over* the lower sector — the tissue underneath is gone
  (the vendor erased it), so the region is honest ``unknown``: it must be
  excluded from ROI/flow/phase signals, never inpainted and never cropped
  away (cropping the sector loses the atria and the AV rings).

This module only *locates* — IoU against an annotated strip is the acceptance
metric, and locating deliberately shares no gate with *reading* the trace as
a signal (:func:`cine_phase_timeline.burned_ecg_signal`).  A noisy strip with
no QRS and an implausible heart rate yields no usable ECG signal, but the
mask must still fire: the strip is visible geometry even when it is not
readable rhythm.  Restoring the tissue under the strip is out of scope (no
inpainting); consumers treat masked pixels like dropout — ``unknown``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.ndimage import binary_dilation, find_objects
from scipy.ndimage import label as component_label

#: The strip signature lives in the lower part of the frame.  Samsung/GE draw
#: it at the very bottom, but a strip *over* the lower sector (the user's
#: 4CC:301 clip) can sit higher — the scan zone starts where the sector's
#: lower walls live, not at the black-zone boundary.
_STRIP_BAND_START = 0.55

#: Green-dominant pixel rule — identical to the burned-ECG signal reader so
#: one locate step serves both (the mask fires even when the read fails).
_MIN_GREEN = 60

#: Fraction of band pixels that may be green: below the low bound there is no
#: trace, above the high bound the frame is a green overlay, not a cine.
_MIN_GREEN_FRACTION = 0.001
_MAX_GREEN_FRACTION = 0.35

#: A strip component is wide; green annotation glyphs (``4CC : 275``) are
#: narrow islands and are rejected by the same width gate as the signal reader.
_MIN_TRACE_WIDTH_PX = 64
_MIN_TRACE_WIDTH_FRACTION = 0.15

#: Geometry sanity: a strip band is a horizontal sliver in the lower zone.
_MAX_STRIP_HEIGHT_FRACTION = 0.30
_STRIP_ROW_FLOOR_FRACTION = 0.55  # == the scan zone start: the component must live there

#: How many frames the signature is accumulated over (the strip is static;
#: sampling keeps the cost negligible next to tracking itself).
_MAX_SAMPLED_FRAMES = 12

#: Confidence when several sampled frames support the component (vs one).
_MULTI_FRAME_CONFIDENCE = 0.9
_SINGLE_FRAME_CONFIDENCE = 0.6

SCHEMA_VERSION = "1.0"

#: Override vocabulary: ``auto`` subtracts a detected strip; ``off`` says
#: "this clip has no strip / do not subtract" (the user's override).
OVERRIDE_AUTO = "auto"
OVERRIDE_OFF = "off"
OVERRIDE_MODES = frozenset({OVERRIDE_AUTO, OVERRIDE_OFF})

_override_mode = OVERRIDE_AUTO


def get_burned_ecg_override() -> str:
    """The session override for the burned-strip mask (``auto`` by default)."""
    return _override_mode


def store_burned_ecg_override(mode: str | None) -> None:
    """Remember the session override; an unknown value resets to ``auto``.

    Same contract as the А.4 force-source store: the UI may pass anything,
    and a value outside the vocabulary can never pin the mask off silently.
    """
    global _override_mode
    _override_mode = mode if mode in OVERRIDE_MODES else OVERRIDE_AUTO


@dataclass(frozen=True)
class BurnedEcgStrip:
    """The located strip: a row band × column span, plus the trace pixels.

    ``mask_for`` returns the *unknown* region — the whole band × span rect,
    not just the drawn line: the vendor erased the tissue under the strip, so
    everything inside the rect is treated like dropout.  ``pixel_mask`` keeps
    the actual trace pixels (the signal reader's column medians need them);
    it is runtime-only and never serialised.
    """

    row_start: int
    row_end: int
    col_start: int
    col_end: int
    confidence: float = _MULTI_FRAME_CONFIDENCE
    source: str = "signature"
    pixel_mask: np.ndarray | None = field(default=None, compare=False, repr=False)

    @property
    def rect(self) -> tuple[int, int, int, int]:
        """``(row_start, row_end, col_start, col_end)`` — the persistable form."""
        return (int(self.row_start), int(self.row_end), int(self.col_start), int(self.col_end))

    def mask_for(self, frame_shape: tuple[int, ...]) -> np.ndarray:
        """Boolean ``(h, w)`` mask of the unknown region; ``False`` outside the frame."""
        if len(frame_shape) < 2:
            return np.zeros((0, 0), dtype=bool)
        height, width = int(frame_shape[0]), int(frame_shape[1])
        mask = np.zeros((height, width), dtype=bool)
        r0 = max(0, min(height, int(self.row_start)))
        r1 = max(0, min(height, int(self.row_end)))
        c0 = max(0, min(width, int(self.col_start)))
        c1 = max(0, min(width, int(self.col_end)))
        if r1 > r0 and c1 > c0:
            mask[r0:r1, c0:c1] = True
        return mask

    def scaled(self, factor: float, out_shape: tuple[int, int]) -> BurnedEcgStrip:
        """The strip's rect scaled for a downscaled stack (pixel mask dropped).

        ``factor`` is ``out_dim / source_dim`` applied uniformly, exactly the
        factor the callers used for the frames themselves.
        """
        factor = float(factor)
        return BurnedEcgStrip(
            row_start=int(round(self.row_start * factor)),
            row_end=int(round(self.row_end * factor)),
            col_start=int(round(self.col_start * factor)),
            col_end=int(round(self.col_end * factor)),
            confidence=self.confidence,
            source=self.source,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialisable form (rect + provenance); the pixel mask stays runtime-only."""
        return {
            "schema_version": SCHEMA_VERSION,
            "row_start": int(self.row_start),
            "row_end": int(self.row_end),
            "col_start": int(self.col_start),
            "col_end": int(self.col_end),
            "confidence": float(self.confidence),
            "source": str(self.source),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BurnedEcgStrip:
        """Round-trip of :meth:`to_dict`; unknown source falls back to ``signature``."""
        values: list[int] = []
        for key in ("row_start", "row_end", "col_start", "col_end"):
            value = data.get(key)
            if not isinstance(value, (int, float)) or value < 0:
                raise ValueError("burned_ecg_strip: invalid rect")
            values.append(int(value))
        row_start, row_end, col_start, col_end = values
        return cls(
            row_start=row_start,
            row_end=row_end,
            col_start=col_start,
            col_end=col_end,
            confidence=float(data.get("confidence", _MULTI_FRAME_CONFIDENCE)),
            source=str(data.get("source", "signature")),
        )


def strip_from_rect(
    rect: tuple[int, int, int, int],
    *,
    confidence: float = 1.0,
) -> BurnedEcgStrip:
    """A manual strip: the user (or a stored record) pins the band directly."""
    return BurnedEcgStrip(
        row_start=int(rect[0]),
        row_end=int(rect[1]),
        col_start=int(rect[2]),
        col_end=int(rect[3]),
        confidence=float(confidence),
        source="manual",
    )


def strip_rect_iou(
    first: BurnedEcgStrip | tuple[int, int, int, int],
    second: BurnedEcgStrip | tuple[int, int, int, int],
) -> float:
    """Rect IoU of two strips — the acceptance metric for *locating*."""
    rect_a = first.rect if isinstance(first, BurnedEcgStrip) else tuple(int(v) for v in first)
    rect_b = second.rect if isinstance(second, BurnedEcgStrip) else tuple(int(v) for v in second)
    r0 = max(rect_a[0], rect_b[0])
    r1 = min(rect_a[1], rect_b[1])
    c0 = max(rect_a[2], rect_b[2])
    c1 = min(rect_a[3], rect_b[3])
    intersection = max(0, r1 - r0) * max(0, c1 - c0)
    area_a = max(0, rect_a[1] - rect_a[0]) * max(0, rect_a[3] - rect_a[2])
    area_b = max(0, rect_b[1] - rect_b[0]) * max(0, rect_b[3] - rect_b[2])
    union = area_a + area_b - intersection
    if union <= 0:
        return 0.0
    return float(intersection / union)


def _iter_frames(color_frames: np.ndarray | Sequence[np.ndarray]) -> list[np.ndarray]:
    """Frames as a list — a ``(N,H,W,3|4)`` stack iterates over frames, one frame wraps."""
    arr = np.asarray(color_frames)
    if arr.ndim == 4:
        return [arr[index] for index in range(arr.shape[0])]
    return [arr]


def _green_mask(frame: np.ndarray, band_start: int) -> tuple[np.ndarray, int]:
    """Green-dominant pixels of one frame's lower band (the shared signature)."""
    band = frame[band_start:, :, :3].astype(np.int32)
    red, green, blue = band[..., 0], band[..., 1], band[..., 2]
    mask = (green > red * 1.2) & (green > blue * 1.2) & (green > _MIN_GREEN)
    return mask, int(mask.sum())


def detect_burned_ecg_strip(
    color_frames: np.ndarray | Sequence[np.ndarray],
    *,
    n_frames: int | None = None,
) -> BurnedEcgStrip | None:
    """Locate the burned ECG strip; ``None`` when there is none.

    No rhythm gates on purpose: a noisy strip with no QRS (the user's
    4CC:301 clip) still covers pixels that must not reach the phase signals
    or the tracking kernels.  Reading the trace as a signal — with the HR and
    amplitude gates — stays in :func:`cine_phase_timeline.burned_ecg_signal`.
    """
    frames = [np.asarray(item) for item in _iter_frames(color_frames)]
    frames = [item for item in frames if item.ndim == 3 and item.shape[-1] >= 3]
    if not frames:
        return None
    height, width = int(frames[0].shape[0]), int(frames[0].shape[1])
    if min(height, width) < 32:
        return None
    total = len(frames) if n_frames is None else max(1, int(n_frames))
    if total != len(frames):
        frames = frames[: min(total, len(frames))]
    band_start = int(height * _STRIP_BAND_START)
    if band_start >= height - 2:
        return None

    stride = max(1, len(frames) // _MAX_SAMPLED_FRAMES)
    sampled = frames[::stride]
    combined = np.zeros((height - band_start, width), dtype=bool)
    green_px = 0
    support = 0
    for frame in sampled:
        if int(frame.shape[0]) != height or int(frame.shape[1]) != width:
            continue
        mask, count = _green_mask(frame, band_start)
        combined |= mask
        green_px += count
        support += 1 if count else 0
    if not support:
        return None
    green_fraction = green_px / (len(sampled) * combined.size)
    if green_fraction < _MIN_GREEN_FRACTION or green_fraction > _MAX_GREEN_FRACTION:
        return None

    # A tall QRS spike can leave the lower band and split from the baseline;
    # the same 2-D dilation the signal reader uses bonds the fragments while
    # the annotation glyphs stay separate (they sit well above the trace).
    dilated = binary_dilation(combined, structure=np.ones((5, 7), dtype=bool))
    labels, n_components = component_label(dilated)
    if n_components == 0:
        return None
    min_width = max(_MIN_TRACE_WIDTH_PX, int(_MIN_TRACE_WIDTH_FRACTION * width))
    keep = [
        index
        for index, slice_ in enumerate(find_objects(labels), start=1)
        if slice_ is not None and (slice_[1].stop - slice_[1].start) >= min_width
    ]
    if not keep:
        return None
    trace_mask = np.isin(labels, keep) & combined
    rows = np.nonzero(np.any(trace_mask, axis=1))[0]
    columns = np.nonzero(np.any(trace_mask, axis=0))[0]
    if rows.size == 0 or columns.size == 0:
        return None
    row_start = int(rows.min()) + band_start
    row_end = int(rows.max()) + band_start + 1
    col_start, col_end = int(columns.min()), int(columns.max()) + 1
    if row_start < int(height * _STRIP_ROW_FLOOR_FRACTION):
        return None
    if row_end - row_start > int(height * _MAX_STRIP_HEIGHT_FRACTION):
        return None

    full_mask = np.zeros((height, width), dtype=bool)
    full_mask[band_start:] = trace_mask
    confidence = _MULTI_FRAME_CONFIDENCE if support >= 3 else _SINGLE_FRAME_CONFIDENCE
    return BurnedEcgStrip(
        row_start=row_start,
        row_end=row_end,
        col_start=col_start,
        col_end=col_end,
        confidence=confidence,
        source="signature",
        pixel_mask=full_mask,
    )
