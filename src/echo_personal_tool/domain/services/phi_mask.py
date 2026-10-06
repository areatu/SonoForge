"""Geometry of the PHI mask that hides burned-in patient data on a frame.

Ultrasound scanners burn the patient name, ID, hospital and study date straight
into the pixels.  Nothing in the pixel data says where that text is, so the
position comes from an empirical per-vendor profile (see
``infrastructure.phi_mask_profiles``) and is refined by the ultrasound region
geometry when the file carries ``SequenceOfUltrasoundRegions``.

Everything here is pure: numpy in, numpy out, no Qt, no I/O, no knowledge of
vendors.  Two rules shape the design:

* **The mask lives in image coordinates**, never in widget coordinates.  The
  viewport can shrink (anatomical M-mode takes the lower part of the window) and
  the image is then scaled to fit; a band tied to image rows follows the scaling
  and keeps covering the same text.
* **The input frame is never modified.**  Frames come from a cache and are shared
  with playback, M-mode extraction and export; writing into them would make the
  anonymized view irreversible and corrupt the cached pixels.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# A band wider than half a side means somebody mixed up fractions and sizes;
# refuse it instead of silently destroying the frame.
MAX_BAND_FRACTION = 0.5

# How many pixels to look at when estimating the background colour.  The median
# of a sparse glyph band is the background, so a subsample is enough and keeps
# the cost flat regardless of frame size.  8k already pins the median of a
# mostly-uniform band to within a level or two, and the difference between that
# and sampling everything is 0.15 ms versus 2.5 ms per 720p RGB frame.
BACKGROUND_SAMPLE_LIMIT = 8192


@dataclass(frozen=True)
class MaskRect:
    """A rectangle in image pixel coordinates, half-open (x1/y1 excluded)."""

    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def is_empty(self) -> bool:
        return self.x1 <= self.x0 or self.y1 <= self.y0

    def clamped(self, width: int, height: int) -> MaskRect:
        return MaskRect(
            x0=min(max(self.x0, 0), width),
            y0=min(max(self.y0, 0), height),
            x1=min(max(self.x1, 0), width),
            y1=min(max(self.y1, 0), height),
        )


@dataclass(frozen=True)
class MaskSpec:
    """Fraction of each side to cover, measured against the frame size.

    Values are fractions (``0.12`` = 12 % of the frame height for ``top``).
    Zero means "do not mask this side".
    """

    top: float = 0.0
    bottom: float = 0.0
    left: float = 0.0
    right: float = 0.0
    #: Cut the top band back to the first ultrasound panel row when the file
    #: carries region geometry.  Without it the band would eat into the sector
    #: whenever a vendor profile is slightly too generous.
    clamp_to_panel: bool = True
    #: True for screens whose upper part is analysis UI (strain "3 Point
    #: Contour"), not a text header.  A text detector must not auto-extend the
    #: mask there — see the design doc, §4.3.
    preserve_ui: bool = False


@dataclass(frozen=True)
class MaskPlan:
    """Resolved rectangles for one frame, ready to be filled."""

    rects: tuple[MaskRect, ...] = ()
    #: Why the plan ended up the way it is; kept for logs and tests.
    reason: str = ""

    @property
    def is_empty(self) -> bool:
        return not any(not rect.is_empty for rect in self.rects)


def band_extent(fraction: float, size: int) -> int:
    """Convert a side fraction into a pixel extent, 0 when disabled."""
    if fraction <= 0.0 or size <= 0:
        return 0
    clamped = min(max(float(fraction), 0.0), MAX_BAND_FRACTION)
    return int(round(clamped * size))


def resolve_mask_plan(
    spec: MaskSpec,
    height: int,
    width: int,
    *,
    panel_top: int | None = None,
    enabled: bool = True,
) -> MaskPlan:
    """Turn a :class:`MaskSpec` into pixel rectangles for a frame.

    ``panel_top`` is the first row of the topmost ultrasound panel
    (``min(RegionLocationMinY0)``).  When given, the top band is cut back to it
    so the mask never enters the image sector.
    """
    if not enabled:
        return MaskPlan(reason="disabled")
    if height <= 0 or width <= 0:
        return MaskPlan(reason="empty-frame")

    rects: list[MaskRect] = []

    top = band_extent(spec.top, height)
    if top:
        if spec.clamp_to_panel and panel_top is not None:
            top = min(top, max(int(panel_top), 0))
        rects.append(MaskRect(0, 0, width, top))

    bottom = band_extent(spec.bottom, height)
    if bottom:
        rects.append(MaskRect(0, max(height - bottom, 0), width, height))

    left = band_extent(spec.left, width)
    if left:
        rects.append(MaskRect(0, 0, left, height))

    right = band_extent(spec.right, width)
    if right:
        rects.append(MaskRect(max(width - right, 0), 0, width, height))

    resolved = tuple(rect.clamped(width, height) for rect in rects)
    resolved = tuple(rect for rect in resolved if not rect.is_empty)
    return MaskPlan(rects=resolved, reason="ok" if resolved else "no-bands")


def estimate_background(frame: np.ndarray, rect: MaskRect) -> np.ndarray | int:
    """Return the fill colour for ``rect``: the median of the covered pixels.

    The assumption is that burned-in text is a minority of the band's pixels —
    glyphs over a uniform background, which holds for every measured class
    (a header line covers roughly a tenth of its band).  Under that assumption
    the median *is* the background, whichever way round the text is drawn: a
    black band with white glyphs fills black, a white info bar with black
    glyphs fills white.  Colour frames get one value per channel, so the band
    keeps the colour character of the image instead of turning gray.

    If a vendor ever burns in a band that is mostly text, the fill degenerates
    into that colour; it still cannot *reveal* anything, it only looks odd, and
    the user can switch masking off in Settings → Display.
    """
    block = frame[rect.y0 : rect.y1, rect.x0 : rect.x1]
    if block.size == 0:
        return 0

    flat = block.reshape(-1) if block.ndim == 2 else block.reshape(-1, block.shape[-1])
    if flat.shape[0] > BACKGROUND_SAMPLE_LIMIT:
        step = int(np.ceil(flat.shape[0] / BACKGROUND_SAMPLE_LIMIT))
        flat = flat[::step]

    values = np.median(flat, axis=0)
    values = np.rint(values)
    if block.ndim == 2:
        return int(values)
    return values.astype(block.dtype, copy=False)


def fill_values(frame: np.ndarray, plan: MaskPlan) -> tuple[np.ndarray | int, ...]:
    """Return one fill value per rectangle, in ``plan`` order.

    Kept separate from :func:`apply_mask` so callers can compute the values once
    per clip and reuse them: the background of a scanner header does not change
    from frame to frame, and measuring it on every frame costs more than the
    fill itself (see ``AnonymizationFilter``).
    """
    values: list[np.ndarray | int] = []
    for rect in plan.rects:
        band = rect.clamped(frame.shape[1], frame.shape[0])
        if band.is_empty:
            values.append(0)
        else:
            values.append(estimate_background(frame, band))
    return tuple(values)


def apply_mask(
    frame: np.ndarray,
    plan: MaskPlan,
    *,
    fills: tuple[np.ndarray | int, ...] | None = None,
    out: np.ndarray | None = None,
) -> np.ndarray:
    """Fill every rectangle of ``plan`` with the local background colour.

    ``fills`` reuses values computed earlier by :func:`fill_values` instead of
    measuring the frame again.  The input is never modified: the result is
    written into ``out`` when it matches the frame shape and dtype, otherwise
    into a fresh array.  With an empty plan the input is returned unchanged, so
    a disabled mask costs nothing at all.
    """
    if plan.is_empty or frame.size == 0:
        return frame

    if out is None or out.shape != frame.shape or out.dtype != frame.dtype:
        out = np.empty_like(frame)
    np.copyto(out, frame)

    values = fills if fills is not None else fill_values(frame, plan)
    for rect, value in zip(plan.rects, values, strict=False):
        band = rect.clamped(frame.shape[1], frame.shape[0])
        if band.is_empty:
            continue
        out[band.y0 : band.y1, band.x0 : band.x1] = value
    return out
