"""Vendor-independent, evidence-fusion baseline detector for spectral Doppler.

Motivation
----------
The tag-based baseline (``ReferencePixelY0`` + ``RegionLocationMinY0``) works on
GE/Philips/Siemens, but Samsung RS85 frames frequently carry no usable region
tags at all (PW/CW mis-tagged as ``SF=1`` with unusable physical deltas).  The
previous pixel fallbacks were single-cue heuristics (a thin uniform line, or the
darkest row) and each of them fails on a different Samsung layout:

* the baseline line may be interrupted by the spectrum drawn on top of it;
* the "darkest row" is the wall-filter notch or the panel gap, not zero velocity;
* dual-spectrum frames contain several plateau-like rows (B-mode edge, ruler).

This module replaces "one heuristic wins" with **weighted evidence fusion**: a
handful of independent, cheap cues each vote on a row, the votes are smeared
with a small Gaussian kernel and summed, and the arg-max is reported together
with a calibrated confidence and a per-cue breakdown (for logging/QA).

Cues
----
``line``       thin horizontal band of one uniform colour spanning the ROI width
               (the operator's primary visual cue; robust when the vendor draws
               a solid zero line).
``foot``       envelope-foot histogram: for every column the spectral signal
               forms an interval ``[a_c, b_c]``; zero velocity is the boundary
               shared by nearly all columns, so ``a_c``/``b_c`` accumulate into
               a sharp peak at the baseline.  Works when the line is hidden.
``static``     temporal cue (multi-frame only): the baseline is *drawn*, so it
               is the row with the lowest temporal variance inside the spectral
               band, while the spectrum flickers frame to frame.
``grid``       velocity-grid ladder: horizontal grid lines are equidistant and
               zero is one of them; used to *snap* the fused estimate, never to
               pick a row on its own.
``tag``        ``ReferencePixelY0`` when it lands strictly inside the ROI — a
               weak prior only, so a bogus Samsung ``0`` cannot win alone but a
               correct GE/Philips tag reinforces the pixel cues.

All cues are normalised to ``[0, 1]`` and combined with the weights in
``CueWeights``.  No cue is vendor-specific; Samsung simply ends up relying on
``foot``/``static`` because its ``line``/``tag`` evidence is missing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi
from echo_personal_tool.domain.services.doppler_baseline import detect_baseline_line_y

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CueWeights:
    """Relative weight of every evidence cue in the fusion step."""

    line: float = 1.0
    foot: float = 1.0
    static: float = 0.8
    tag: float = 0.4

    # Fusion parameters
    vote_sigma_px: float = 2.0
    grid_snap_px: float = 4.0


DEFAULT_WEIGHTS = CueWeights()


@dataclass(frozen=True)
class BaselineCue:
    """A single piece of evidence: a row plus its own (0..1) strength."""

    name: str
    y: float
    strength: float
    detail: str = ""


@dataclass(frozen=True)
class BaselineEstimate:
    """Fused baseline estimate with provenance."""

    y: float
    confidence: float
    source: str
    cues: list[BaselineCue] = field(default_factory=list)

    @property
    def is_confident(self) -> bool:
        return self.confidence >= 0.5


# ── helpers ────────────────────────────────────────────────────────────────


def _to_gray(frame: np.ndarray) -> np.ndarray | None:
    arr = np.asarray(frame)
    if arr.ndim == 3:
        arr = arr[..., :3].astype(np.float32)
        return 0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2]
    if arr.ndim == 2:
        return arr.astype(np.float32)
    return None


def _clip_roi(shape: tuple[int, int], roi: DopplerSpectrogramRoi) -> tuple[int, int, int, int] | None:
    height, width = shape
    x0 = int(max(0, min(roi.x0, width - 1)))
    y0 = int(max(0, min(roi.y0, height - 1)))
    x1 = int(max(x0 + 1, min(roi.x1, width)))
    y1 = int(max(y0 + 1, min(roi.y1, height)))
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1, y1


def _signal_mask(patch: np.ndarray) -> np.ndarray:
    """Binary spectral-signal mask, robust to the panel's dark background."""
    background = float(np.percentile(patch, 20))
    peak = float(np.percentile(patch, 99.5))
    if peak - background < 8.0:
        return np.zeros_like(patch, dtype=bool)
    threshold = background + 0.25 * (peak - background)
    return patch > max(threshold, background + 6.0)


# ── cues ───────────────────────────────────────────────────────────────────


def cue_line(frame: np.ndarray, roi: DopplerSpectrogramRoi) -> BaselineCue | None:
    """Thin uniform horizontal band (existing detector, reused as one vote)."""
    try:
        y = detect_baseline_line_y(frame, roi)
    except Exception:  # pragma: no cover - defensive
        return None
    if y is None:
        return None
    return BaselineCue(name="line", y=float(y), strength=1.0, detail="uniform thin band")


def cue_envelope_foot(frame: np.ndarray, roi: DopplerSpectrogramRoi) -> BaselineCue | None:
    """Histogram of per-column signal boundaries ("feet" of the envelope).

    Spectral flow always *starts* at zero velocity, so for the vast majority of
    columns either the upper or the lower boundary of the signal interval sits
    on the baseline.  Those boundaries pile up into a single sharp histogram
    peak, while the outer (envelope) boundary is spread over the waveform.
    """
    gray = _to_gray(frame)
    if gray is None:
        return None
    box = _clip_roi(gray.shape, roi)
    if box is None:
        return None
    x0, y0, x1, y1 = box
    patch = gray[y0:y1, x0:x1]
    n_rows, n_cols = patch.shape
    if n_rows < 8 or n_cols < 8:
        return None

    mask = _signal_mask(patch)
    cols_with_signal = mask.any(axis=0)
    if int(cols_with_signal.sum()) < max(8, int(0.2 * n_cols)):
        return None

    hist = np.zeros(n_rows, dtype=np.float64)
    for c in np.flatnonzero(cols_with_signal):
        rows = np.flatnonzero(mask[:, c])
        hist[rows[0]] += 1.0
        hist[rows[-1]] += 1.0

    # Smooth: the drawn baseline is 1-3 px thick and columns jitter by a pixel.
    kernel = np.array([0.25, 0.5, 1.0, 0.5, 0.25])
    kernel /= kernel.sum()
    smooth = np.convolve(hist, kernel, mode="same")

    idx = int(np.argmax(smooth))
    peak = float(smooth[idx])
    if peak <= 0.0:
        return None

    # Strength = how dominant the peak is versus the rest of the profile.
    others = np.delete(smooth, slice(max(0, idx - 3), idx + 4))
    baseline_level = float(np.mean(others)) if others.size else 0.0
    contrast = (peak - baseline_level) / peak if peak > 0 else 0.0
    coverage = peak / (2.0 * float(cols_with_signal.sum()))
    strength = float(np.clip(0.5 * contrast + 0.5 * min(1.0, 2.0 * coverage), 0.0, 1.0))
    if strength < 0.2:
        return None

    # Sub-pixel refinement by centre of mass of the peak neighbourhood.
    lo = max(0, idx - 2)
    hi = min(n_rows, idx + 3)
    weights = smooth[lo:hi]
    centre = float(np.sum(np.arange(lo, hi) * weights) / np.sum(weights)) if weights.sum() > 0 else float(idx)

    return BaselineCue(
        name="foot",
        y=float(y0 + centre) + 0.5,
        strength=strength,
        detail=f"peak={peak:.0f} contrast={contrast:.2f}",
    )


def cue_static_row(frames: list[np.ndarray], roi: DopplerSpectrogramRoi) -> BaselineCue | None:
    """Row that stays constant across frames while the spectrum flickers."""
    grays = [g for g in (_to_gray(f) for f in frames) if g is not None]
    if len(grays) < 3:
        return None
    shape = grays[0].shape
    if any(g.shape != shape for g in grays):
        return None
    box = _clip_roi(shape, roi)
    if box is None:
        return None
    x0, y0, x1, y1 = box
    stack = np.stack([g[y0:y1, x0:x1] for g in grays], axis=0)
    n_rows = stack.shape[1]
    if n_rows < 8:
        return None

    temporal_std = stack.std(axis=0).mean(axis=1)  # per row
    row_mean = stack.mean(axis=(0, 2))

    # Only rows that actually contain drawn content qualify (skip pure
    # background: it is static too, but it is not the baseline).
    background = float(np.percentile(row_mean, 10))
    peak = float(np.percentile(row_mean, 99))
    if peak - background < 5.0:
        return None
    content = row_mean > background + 0.2 * (peak - background)
    if not content.any():
        return None

    scores = np.where(content, 1.0 / (1.0 + temporal_std), 0.0)
    idx = int(np.argmax(scores))
    active_std = temporal_std[content]
    median_std = float(np.median(active_std)) if active_std.size else 0.0
    if median_std <= 1e-6:
        return None
    ratio = float(temporal_std[idx] / median_std)
    strength = float(np.clip(1.0 - ratio, 0.0, 1.0))
    if strength < 0.2:
        return None
    return BaselineCue(
        name="static",
        y=float(y0 + idx) + 0.5,
        strength=strength,
        detail=f"std={temporal_std[idx]:.2f} vs median {median_std:.2f}",
    )


def cue_tag(tag_baseline_y: float | None, roi: DopplerSpectrogramRoi) -> BaselineCue | None:
    """``ReferencePixelY0``-derived prior, accepted only strictly inside ROI."""
    if tag_baseline_y is None:
        return None
    y = float(tag_baseline_y)
    margin = 0.05 * roi.height
    if not (roi.y0 + margin <= y <= roi.y1 - margin):
        return None
    return BaselineCue(name="tag", y=y, strength=1.0, detail="ReferencePixelY0")


def snap_to_grid(y: float, grid_lines: list[float] | None, tolerance_px: float) -> tuple[float, bool]:
    """Snap ``y`` to the nearest velocity-grid line within ``tolerance_px``."""
    if not grid_lines:
        return y, False
    nearest = min(grid_lines, key=lambda g: abs(g - y))
    if abs(nearest - y) <= tolerance_px:
        return float(nearest), True
    return y, False


# ── fusion ─────────────────────────────────────────────────────────────────


def fuse_cues(
    cues: list[BaselineCue],
    roi: DopplerSpectrogramRoi,
    *,
    weights: CueWeights = DEFAULT_WEIGHTS,
    grid_lines: list[float] | None = None,
) -> BaselineEstimate:
    """Combine cue votes into a single estimate with a confidence score."""
    usable = [c for c in cues if c is not None]
    if not usable:
        return BaselineEstimate(
            y=roi.y0 + roi.height / 2.0,
            confidence=0.0,
            source="fallback: ROI centre (no evidence)",
            cues=[],
        )

    weight_of = {
        "line": weights.line,
        "foot": weights.foot,
        "static": weights.static,
        "tag": weights.tag,
    }

    y_lo = int(np.floor(roi.y0))
    y_hi = int(np.ceil(roi.y1))
    rows = np.arange(y_lo, max(y_lo + 1, y_hi), dtype=np.float64)
    sigma = max(0.5, weights.vote_sigma_px)

    votes = np.zeros_like(rows)
    for cue in usable:
        w = weight_of.get(cue.name, 0.5) * cue.strength
        votes += w * np.exp(-0.5 * ((rows - cue.y) / sigma) ** 2)

    idx = int(np.argmax(votes))
    y = float(rows[idx])
    total = float(np.sum([weight_of.get(c.name, 0.5) * c.strength for c in usable]))
    agreement = float(votes[idx] / total) if total > 0 else 0.0

    y, snapped = snap_to_grid(y, grid_lines, weights.grid_snap_px)

    # Confidence: how much of the available evidence mass agrees on this row,
    # scaled by how much evidence there is at all (a single weak cue must not
    # look as trustworthy as three concordant ones).
    evidence_mass = min(1.0, total / (weights.line + weights.foot))
    confidence = float(np.clip(0.35 * evidence_mass + 0.65 * agreement * evidence_mass, 0.0, 1.0))
    if snapped:
        confidence = min(1.0, confidence + 0.05)

    names = "+".join(f"{c.name}:{c.strength:.2f}" for c in usable)
    source = f"fusion[{names}]" + (" snapped-to-grid" if snapped else "")
    return BaselineEstimate(y=y, confidence=confidence, source=source, cues=usable)


def detect_baseline_robust(
    frame: np.ndarray,
    roi: DopplerSpectrogramRoi,
    *,
    frames: list[np.ndarray] | None = None,
    tag_baseline_y: float | None = None,
    grid_lines: list[float] | None = None,
    weights: CueWeights = DEFAULT_WEIGHTS,
) -> BaselineEstimate:
    """Detect the zero-velocity baseline by fusing independent visual cues.

    Args:
        frame: current frame (2D grayscale or 3D RGB).
        roi: spectrogram ROI in frame coordinates.
        frames: optional additional frames of the same clip enabling the
            temporal ``static`` cue (pass a handful, e.g. every 5th frame).
        tag_baseline_y: optional absolute Y from ``ReferencePixelY0``; used as a
            weak prior only (Samsung writes bogus zeros).
        grid_lines: optional velocity-grid rows used to snap the result.
        weights: cue weights / fusion parameters.

    Returns:
        BaselineEstimate; callers should treat ``confidence < 0.5`` as "ask the
        operator" rather than silently calibrating.
    """
    cues: list[BaselineCue] = []
    for cue in (
        cue_line(frame, roi),
        cue_envelope_foot(frame, roi),
        cue_static_row(frames, roi) if frames else None,
        cue_tag(tag_baseline_y, roi),
    ):
        if cue is not None:
            cues.append(cue)

    estimate = fuse_cues(cues, roi, weights=weights, grid_lines=grid_lines)
    logger.debug(
        "baseline fusion: y=%.1f conf=%.2f source=%s",
        estimate.y,
        estimate.confidence,
        estimate.source,
    )
    return estimate
