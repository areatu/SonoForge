"""ECG-independent cardiac phase field φ(t) for cine clips (plan А.3, issue #641).

One continuous phase per frame — φ(t) ∈ [0, 1), φ = 0 at every ED
(end-diastole, maximal cavity) and φ → 1 at the next ED, so the systolic
fraction is directly readable as φ(ES) — built from the clip's own image
periodicity, with no ECG waveform and no labels.

The pragmatic model of the plan (the issue allows "self-supervised on
periodicity OR pragmatic image signals + a light regressor"):

* **Signals.** Every polarity-known proxy is a phase carrier: an LV
  cavity-area curve (from segmentation masks or a stored Simpson curve), the
  gain-normalised dark-pool fraction and the tissue brightness from
  :mod:`cine_phase_image_signals`.  Optical-flow magnitude is extracted too,
  but it is polarity-free: like the motion proxy there, it may corroborate
  the rhythm (a small confidence bonus) and must never drive ED/ES.
* **Model.** A per-clip harmonic regressor fitted *on the clip itself* by
  minimising a periodicity loss — the reconstruction residual of a truncated
  Fourier basis over the whole beat-period band.  No labels, no external
  data, no pre-trained weights; the refined period and the adjusted fit R²
  are the learned quantities.  The shortest period whose basis explains the
  signal wins (for a perfectly periodic clip every divisor fits equally, and
  a longer candidate misses the harmonics), so a systole/filling split cannot
  halve the beat and an exactly periodic clip cannot double it.  A
  dataset-trained ONNX encoder stays future work (see
  ``docs/reviews/2026-11-21-a3-phase-field-641-ru.md``): every parameter it
  would learn is estimated here from the single clip at hand.
* **Field.** ED anchors are prominence-filtered maxima of the fused signal,
  detected *circularly* (the clip is padded with a full period on each side,
  so an ED next to the clip boundary keeps the prominence of its
  neighbouring valleys); ES is the in-cycle minimum.  φ is the cycle
  normalised time between anchors — monotone inside every cycle by
  construction, and the ED/ES frames are exact image measurements, not clock
  extrapolations.  Truncated leading/trailing regions ride the fitted period
  and are flagged ``partial`` — like
  :class:`~...cine_phase_timeline.PhaseCycle`, they are never a measured
  beat.
* **Equivariance.** Every step (z-scoring, wrap-mode smoothing, circular
  peak padding, least-squares fit quality) is exactly equivariant under a
  circular shift of the clip and covariant under time reversal — the
  invariant tests of the issue (phase shift / inversion do not change the
  strain the cycles produce) hold by construction, not by tuning.
* **Confidence.** Harmonic fit quality × carrier concordance × rhythm
  regularity, multiplicative so every factor can veto, gated: below
  ``min_confidence`` the field carries no cycles and an all-zero φ — a weak
  guess must never look confident.

Bridges: :func:`phase_field_to_ed_es_mapping` speaks the
``ecg_ed_es_mapper`` vocabulary and :func:`phase_field_to_cardiac_cycles`
speaks the Doppler cycle service's ms-domain one;
:func:`phase_field_ed_es_fallback` plugs the field into
``detect_ed_es_for_cine(image_fallback=...)`` until source routing (plan
А.4) makes the field a first-class phase source.

This is a visual/navigation and averaging aid, not a validated clinical
measurement — the same contract as :mod:`cine_phase_timeline`.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np
from scipy.signal import find_peaks, savgol_filter

from echo_personal_tool.domain.models.ecg import EcEDFrameMapping
from echo_personal_tool.domain.services.cine_phase_image_signals import image_phase_signals

if TYPE_CHECKING:
    from echo_personal_tool.domain.services.cardiac_cycle_service import CardiacCycle

SCHEMA_VERSION = "1.0"
SOURCE_PHASE_FIELD = "phase_field"

#: Below this the whole field is rejected (no cycles, φ ≡ 0) — the same
#: "never paint a confident-looking guess" gate as ``cine_phase_timeline``.
DEFAULT_MIN_CONFIDENCE = 0.35

_MIN_FRAMES = 4
_MIN_HR_BPM = 35.0
_MAX_HR_BPM = 200.0
_MIN_PERIOD_FRAMES = 6
_MAX_PERIOD_FRAMES = 60
_HARMONICS = 2
#: Minimum adjusted R² of the harmonic fit for a signal to count as periodic.
#: Same role as the ACF ≥ 0.30 gate of ``cine_phase_timeline._build_signals``.
_MIN_FIT_R2 = 0.30
_GRID_STEP = 0.5
_POLISH_STEP = 0.02
#: R² tie tolerance when preferring the shortest fitting period: a longer
#: candidate must be *genuinely* better to beat the fundamental.
_R2_TIE_TOL = 1e-4
_MIN_CARRIER_CORR = 0.2
_SUPPORT_MIN_CORR = 0.3
_SUPPORT_BONUS = 0.10
_FLOW_MAX_SIZE = 96
_MAX_TRAILING_WINDOWS = 3

#: Phase carriers: polarity known, ED = maximum (same doctrine as
#: ``cine_phase_timeline``).  Flow/motion is supporting evidence only.
_CARRIER_WEIGHTS: dict[str, float] = {"area": 1.0, "dark_pool": 0.8, "intensity": 0.7}


# ── Value types ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PhaseFieldCycle:
    """One cardiac cycle of the phase field.

    ``ed_frame`` is inclusive, ``end_frame`` exclusive (the next ED, an
    extrapolated period window, or the end of the clip).  ``partial`` marks a
    cycle whose start or end is extrapolated beyond a detected ED anchor —
    the UI/measurements must never treat it as a complete measured beat.
    """

    ed_frame: int
    es_frame: int
    end_frame: int
    confidence: float
    partial: bool = False

    @property
    def duration_frames(self) -> int:
        return max(0, self.end_frame - self.ed_frame)

    @property
    def systole_frames(self) -> int:
        return max(0, self.es_frame - self.ed_frame)

    @property
    def systole_fraction(self) -> float | None:
        """Measured systole fraction of the cycle; ``None`` when degenerate."""
        duration = self.duration_frames
        if duration <= 0:
            return None
        return (self.es_frame - self.ed_frame) / duration


@dataclass(frozen=True, eq=False)
class PhaseField:
    """Continuous ECG-independent phase annotation of one cine clip."""

    n_frames: int
    frame_time_ms: float | None
    phi: np.ndarray  # float64 (n_frames,), values in [0, 1), φ = 0 at every ED
    ed_frames: tuple[int, ...]
    es_frames: tuple[int, ...]  # one ES per entry of ``cycles``, same order
    cycles: tuple[PhaseFieldCycle, ...]
    source_signal: str
    period_frames: float
    confidence: float
    warnings: tuple[str, ...] = ()
    schema_version: str = SCHEMA_VERSION

    def phase_at(self, frame: int) -> float:
        if 0 <= frame < self.phi.size:
            return float(self.phi[frame])
        return 0.0

    @property
    def heart_rate_bpm(self) -> float | None:
        """Median RR over complete cycles; ``None`` when time is unknown."""
        if self.frame_time_ms is None or self.frame_time_ms <= 0:
            return None
        durations = [c.duration_frames for c in self.cycles if not c.partial and c.duration_frames > 0]
        if not durations:
            return None
        rr_ms = float(np.median(durations)) * self.frame_time_ms
        return 60000.0 / rr_ms if rr_ms > 0 else None

    def best_cycle(self) -> PhaseFieldCycle | None:
        """Highest-confidence cycle; complete cycles win over partial ones."""
        pool = [c for c in self.cycles if not c.partial] or list(self.cycles)
        if not pool:
            return None
        return max(pool, key=lambda c: c.confidence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "n_frames": self.n_frames,
            "frame_time_ms": self.frame_time_ms,
            "phi": [round(float(v), 6) for v in self.phi],
            "ed_frames": list(self.ed_frames),
            "es_frames": list(self.es_frames),
            "cycles": [
                {
                    "ed_frame": c.ed_frame,
                    "es_frame": c.es_frame,
                    "end_frame": c.end_frame,
                    "confidence": c.confidence,
                    "partial": c.partial,
                }
                for c in self.cycles
            ],
            "source_signal": self.source_signal,
            "period_frames": self.period_frames,
            "confidence": self.confidence,
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PhaseField:
        n = max(0, int(data.get("n_frames", 0)))
        cycles = tuple(
            PhaseFieldCycle(
                ed_frame=int(c["ed_frame"]),
                es_frame=int(c["es_frame"]),
                end_frame=int(c["end_frame"]),
                confidence=float(c.get("confidence", 0.0)),
                partial=bool(c.get("partial", False)),
            )
            for c in data.get("cycles", [])
        )
        phi_values = data.get("phi", [])
        phi = np.asarray(phi_values, dtype=np.float64) if phi_values else np.zeros(n, dtype=np.float64)
        if phi.size != n:
            phi = np.zeros(n, dtype=np.float64)
        frame_time = data.get("frame_time_ms")
        return cls(
            n_frames=n,
            frame_time_ms=float(frame_time) if frame_time is not None else None,
            phi=phi,
            ed_frames=tuple(int(f) for f in data.get("ed_frames", [])),
            es_frames=tuple(int(f) for f in data.get("es_frames", [])),
            cycles=cycles,
            source_signal=str(data.get("source_signal", "")),
            period_frames=float(data.get("period_frames", 0.0)),
            confidence=float(data.get("confidence", 0.0)),
            warnings=tuple(str(w) for w in data.get("warnings", [])),
            schema_version=str(data.get("schema_version", SCHEMA_VERSION)),
        )


# ── Signal extraction ───────────────────────────────────────────────────────


def _gray_stack(frames: np.ndarray | Sequence[np.ndarray]) -> np.ndarray | None:
    """Accept (N,H,W) or (N,H,W,3|4), return float32 (N,H,W) or ``None``."""
    try:
        arr = np.asarray(frames)
    except ValueError:
        return None
    if arr.ndim == 4:
        if arr.shape[-1] not in (3, 4):
            return None
        arr = arr[..., :3].mean(axis=-1)
    if arr.ndim != 3 or arr.shape[0] < 1 or min(arr.shape[1:]) < 4:
        return None
    return np.asarray(arr, dtype=np.float32)


def cavity_area_from_masks(masks: np.ndarray | Sequence[np.ndarray]) -> np.ndarray:
    """Per-frame LV cavity area fraction from a boolean mask stack.

    The cardiac signal from an LV mask (plan А.3): ED = maximal cavity area.
    Empty vector when the stack is malformed or the area never changes.
    """
    empty = np.zeros(0, dtype=np.float64)
    try:
        arr = np.asarray(masks)
    except ValueError:
        return empty
    if arr.ndim != 3 or arr.shape[0] < 1:
        return empty
    boolean = arr.astype(bool)
    pixels = max(1, int(boolean.shape[1]) * int(boolean.shape[2]))
    area = np.asarray(boolean.sum(axis=(1, 2)), dtype=np.float64) / pixels
    if float(np.ptp(area)) < 1e-9:
        return empty
    return area


def optical_flow_magnitude_signal(
    gray_frames: np.ndarray | Sequence[np.ndarray],
    *,
    max_size: int = _FLOW_MAX_SIZE,
) -> np.ndarray:
    """Polarity-free tissue motion magnitude per frame (Farneback).

    Supporting rhythm evidence only: it has no ED/ES polarity and may burst
    twice per beat, exactly like the frame-difference motion proxy of
    :mod:`cine_phase_image_signals`.  Frames are downscaled to ``max_size``
    before the flow — temporal resolution is preserved.  Empty vector when
    the clip is malformed or the flow cannot be computed.
    """
    empty = np.zeros(0, dtype=np.float64)
    gray = _gray_stack(gray_frames)
    if gray is None or gray.shape[0] < 2:
        return empty
    height, width = int(gray.shape[1]), int(gray.shape[2])
    if min(height, width) < 8:
        return empty
    scale = min(1.0, float(max_size) / float(max(height, width)))
    if scale < 1.0:
        out_w, out_h = max(4, int(round(width * scale))), max(4, int(round(height * scale)))
        small = np.stack([cv2.resize(frame, (out_w, out_h), interpolation=cv2.INTER_AREA) for frame in gray])
    else:
        small = gray
    u8 = np.clip(small, 0.0, 255.0).astype(np.uint8)
    n = int(u8.shape[0])
    magnitude = np.zeros(n, dtype=np.float64)
    try:
        for index in range(n - 1):
            flow = cv2.calcOpticalFlowFarneback(u8[index], u8[index + 1], None, 0.5, 2, 9, 2, 5, 1.2, 0)
            magnitude[index + 1] = float(np.mean(np.sqrt(flow[..., 0] ** 2 + flow[..., 1] ** 2)))
    except cv2.error:
        return empty
    magnitude[0] = magnitude[1]
    if float(np.ptp(magnitude)) < 1e-9:
        return empty
    return magnitude


def extract_phase_candidates(
    *,
    frames: np.ndarray | Sequence[np.ndarray] | None = None,
    area_curve: np.ndarray | Sequence[float] | None = None,
    lv_masks: np.ndarray | Sequence[np.ndarray] | None = None,
) -> dict[str, np.ndarray]:
    """Candidate phase signals, each gain-normalised, ED-oriented.

    ``area`` wins from an explicit curve; the LV-mask stack is only used when
    no curve was supplied.  ``intensity`` is inverted so that every carrier
    has ED = maximum (bright myocardium fills the ROI in systole).  ``flow``
    is polarity-free supporting evidence.  Empty vectors are omitted.
    """
    candidates: dict[str, np.ndarray] = {}
    curve = _finite_curve(area_curve)
    if curve is not None:
        candidates["area"] = curve
    if lv_masks is not None and "area" not in candidates:
        mask_area = cavity_area_from_masks(lv_masks)
        if mask_area.size:
            candidates["area"] = mask_area
    gray = _gray_stack(frames) if frames is not None else None
    if gray is not None:
        dark, intensity, _motion = image_phase_signals(gray)
        if dark.size == gray.shape[0]:
            candidates["dark_pool"] = np.asarray(dark, dtype=np.float64)
        if intensity.size == gray.shape[0]:
            candidates["intensity"] = -np.asarray(intensity, dtype=np.float64)
        flow = optical_flow_magnitude_signal(gray)
        if flow.size == gray.shape[0]:
            candidates["flow"] = flow
    return candidates


def _finite_curve(values: np.ndarray | Sequence[float] | None) -> np.ndarray | None:
    if values is None:
        return None
    arr = np.asarray(values, dtype=np.float64).reshape(-1)
    if arr.size == 0 or not np.isfinite(arr).any():
        return None
    if float(np.ptp(arr[np.isfinite(arr)])) < 1e-9:
        return None
    return arr


# ── Periodicity machinery ───────────────────────────────────────────────────


def _period_band(n_frames: int, fps: float | None) -> tuple[int, int]:
    """Plausible beat period in frames from the HR plausibility band."""
    if fps is not None and fps > 0:
        min_p = max(_MIN_PERIOD_FRAMES, int(math.floor(fps * 60.0 / _MAX_HR_BPM)))
        max_p = min(_MAX_PERIOD_FRAMES, int(math.ceil(fps * 60.0 / _MIN_HR_BPM)))
    else:
        min_p, max_p = _MIN_PERIOD_FRAMES, _MAX_PERIOD_FRAMES
    max_p = min(max_p, max(2, n_frames - 2))
    min_p = min(min_p, max_p)
    return min_p, max_p


def _harmonic_basis(n: int, period: float) -> np.ndarray:
    t = np.arange(n, dtype=np.float64)
    columns = [np.ones(n, dtype=np.float64)]
    for k in range(1, _HARMONICS + 1):
        w = 2.0 * math.pi * k / period
        columns.append(np.sin(w * t))
        columns.append(np.cos(w * t))
    return np.stack(columns, axis=1)


def _fit_r2(x: np.ndarray, period: float) -> float:
    """Adjusted variance explained by the truncated Fourier basis at ``period``.

    Minimising the complementary reconstruction residual *is* the periodicity
    loss the plan names: no labels, the clip itself is the training set.  The
    adjustment (df penalty for the 2·harmonics+1 basis columns) keeps a short
    noisy clip from scoring a fit it earned by overfitting.

    Exactly invariant under a circular shift of the clip: a shift phase-rotates
    the basis columns without changing their span, so the optimal residual —
    and therefore R² — is untouched.  A time reversal likewise only mirrors
    the span.  This is what makes the period estimate, and with it the whole
    field, shift/reversal equivariant.
    """
    basis = _harmonic_basis(x.size, period)
    n, k = int(x.size), int(basis.shape[1])
    if n <= k + 1:
        return 0.0
    coefficients, *_ = np.linalg.lstsq(basis, x, rcond=None)
    residual = x - basis @ coefficients
    ss_res = float(np.dot(residual, residual))
    centered = x - float(x.mean())
    ss_tot = float(np.dot(centered, centered))
    if ss_tot < 1e-12:
        return 0.0
    r2 = 1.0 - (ss_res / ss_tot) * ((n - 1) / (n - k - 1))
    return min(1.0, max(0.0, r2))


def _harmonic_period(x: np.ndarray, band: tuple[int, int]) -> tuple[float, float] | None:
    """Beat period and fit quality: the shortest period that explains the signal.

    A coarse R² sweep over the whole plausible band, then a fine polish.  The
    winner is the *earliest* period whose fit is within ``_R2_TIE_TOL`` of the
    best: for a perfectly periodic clip every divisor fits equally well and
    the fundamental wins, while a longer candidate misses the harmonics of an
    asymmetric waveform and can never win — so neither a systole/filling split
    nor an exactly periodic clip corrupts the period.
    """
    min_p, max_p = band
    if x.size < max_p + 2 or max_p < min_p:
        return None
    coarse = np.arange(min_p, max_p + 1e-9, _GRID_STEP)
    coarse_scores = [_fit_r2(x, float(p)) for p in coarse]
    best_coarse = max(coarse_scores)
    centre_i = next((i for i, score in enumerate(coarse_scores) if score >= best_coarse - _R2_TIE_TOL), 0)
    centre = float(coarse[centre_i])
    fine = np.arange(max(min_p, centre - _GRID_STEP), min(max_p, centre + _GRID_STEP) + 1e-9, _POLISH_STEP)
    if fine.size == 0:
        return centre, best_coarse
    fine_scores = [_fit_r2(x, float(p)) for p in fine]
    best_i = int(np.argmax(fine_scores))
    return float(fine[best_i]), min(1.0, max(0.0, float(fine_scores[best_i])))


def _consensus_period(periods: Sequence[float]) -> float:
    """Median carrier period with harmonic reconciliation (2× / ÷2 outliers)."""
    median = float(np.median(np.asarray(periods, dtype=np.float64)))
    reconciled: list[float] = []
    for period in periods:
        value = float(period)
        while value < 0.7 * median:
            value *= 2.0
        while value > 1.4 * median and value >= 2.0:
            value *= 0.5
        reconciled.append(value)
    return max(2.0, float(np.median(reconciled)))


def _pearson(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b)) / denom if denom > 0.0 else 0.0


def _best_circular_shift(sig: np.ndarray, ref: np.ndarray, max_shift: int) -> tuple[np.ndarray, float]:
    """Align ``sig`` to ``ref`` by circular shift within ±``max_shift`` frames."""
    best_corr, best_shift = -2.0, 0
    for shift in range(-max_shift, max_shift + 1):
        corr = _pearson(np.roll(sig, shift), ref)
        if corr > best_corr:
            best_corr, best_shift = corr, shift
    return np.roll(sig, best_shift), best_corr


def _compose(
    carriers: dict[str, np.ndarray],
    scored: Sequence[tuple[str, float, float]],
    period0: float,
    warnings: list[str],
) -> tuple[np.ndarray, float, str] | None:
    """Fuse polarity-known carriers into one ED-oriented composite signal.

    Returns ``(composite, agreement, reference_name)`` or ``None``.  A carrier
    that cannot be aligned to the reference at the consensus period is dropped
    with a warning — it is noise or a harmonic, not the beat.
    """
    order = sorted(scored, key=lambda s: (-_CARRIER_WEIGHTS.get(s[0], 0.0), s[0]))
    reference_name = order[0][0]
    reference = carriers[reference_name]
    max_shift = max(1, int(round(0.25 * period0)))
    used: list[tuple[np.ndarray, float, float]] = []
    for name, _period_i, _r2_i in order:
        signal = carriers[name]
        if name == reference_name:
            aligned, corr = signal, 1.0
        else:
            aligned, corr = _best_circular_shift(signal, reference, max_shift)
        if corr < _MIN_CARRIER_CORR:
            warnings.append(f"carrier_dropped:{name}")
            continue
        used.append((aligned, _CARRIER_WEIGHTS.get(name, 0.5), corr))
    if not used:
        return None
    total_weight = sum(weight for _, weight, _ in used)
    composite = sum((aligned * weight for aligned, weight, _ in used), start=np.zeros_like(reference))
    composite = composite / total_weight
    std = float(composite.std())
    if std < 1e-9:
        return None
    composite = (composite - float(composite.mean())) / std
    if len(used) == 1:
        # One carrier alone carries no cross-signal concordance evidence.
        agreement = 0.5
    else:
        agreement = sum(weight * corr for _, weight, corr in used) / total_weight
    return composite, min(1.0, max(0.0, agreement)), reference_name


def _smooth_signal(x: np.ndarray, period: float) -> np.ndarray:
    """Light quadratic smoothing that preserves extrema positions.

    ``mode="wrap"`` keeps the smoothing equivariant under a circular shift of
    the clip, so the invariant tests (phase shift) compare like with like.
    The quadratic local fit is deliberately preferred over a plain moving
    average: the mechanical peak is asymmetric (gentle filling rise, steep
    systolic fall) and an average pulls its apex aside by up to two frames.
    """
    n = int(x.size)
    window = int(round(period / 3.0))
    if window % 2 == 0:
        window += 1
    window = max(5, min(window, n if n % 2 == 1 else n - 1))
    if window >= n or window <= 3:
        return np.asarray(x, dtype=np.float64)
    try:
        return np.asarray(
            savgol_filter(np.asarray(x, dtype=np.float64), window, 2, mode="wrap"),
            dtype=np.float64,
        )
    except ValueError:
        return np.asarray(x, dtype=np.float64)


def _anchors(
    composite: np.ndarray,
    smooth: np.ndarray,
    period: float,
) -> tuple[np.ndarray, list[int], bool]:
    """ED anchors (prominence-filtered maxima), one ES per pair, gap-corrected.

    ED peaks are detected *circularly* on the raw composite — the signal is
    padded with a full period on each side, so an ED next to the clip boundary
    keeps the prominence of its neighbouring valleys instead of being measured
    against the edge, and a clip that starts at an ED yields that ED as an
    anchor.  The raw signal (not the smoothed one) drives peak detection: a
    wrap-mode window straddling a non-phase-continuous seam (a clip of
    non-integer beats) would pull the apex aside.  ES is the in-cycle minimum
    of the smoothed composite, where windows stay interior.

    Anchors whose gap to their neighbour leaves ``[0.55, 1.6] · period``
    cannot be beats of the measured rhythm — a spike or a merged double beat.
    The weaker anchor of each violating pair is dropped, matching the
    ``cine_phase_timeline`` doctrine that extrema must follow the period.
    The third element reports whether such a correction happened.
    """
    n = int(composite.size)
    rng = float(np.percentile(composite, 95) - np.percentile(composite, 5))
    prominence = max(0.15 * rng, 1e-9)
    pad = int(math.ceil(period))
    if pad < n:
        extended = np.concatenate([composite[n - pad :], composite, composite[:pad]])
    else:
        extended = composite
    # No `distance` floor here: in the padded extension a peak and its own
    # one-period-apart copy can sit closer than the floor near a seam, and
    # the tie-break would drop a genuine boundary peak.  Copies fold onto
    # their frame below; sub-period double maxima are handled afterwards by
    # the gap validation, which drops the weaker of a too-close pair.
    peaks_ext, properties = find_peaks(extended, prominence=prominence)
    if peaks_ext.size == 0:
        return np.zeros(0, dtype=np.int64), [], False

    frame_prominence: dict[int, float] = {}
    for index, value in zip(peaks_ext, properties["prominences"]):
        frame = int(np.mod(int(index) - pad, n)) if pad < n else int(index)
        frame_prominence[frame] = max(frame_prominence.get(frame, 0.0), float(value))
    kept = sorted(frame_prominence.items())

    index = 0
    corrected = False
    while index + 1 < len(kept):
        gap = kept[index + 1][0] - kept[index][0]
        if gap < 0.55 * period or gap > 1.6 * period:
            drop = index + 1 if kept[index][1] >= kept[index + 1][1] else index
            del kept[drop]
            corrected = True
        else:
            index += 1
    eds = np.asarray([frame for frame, _prominence in kept], dtype=np.int64)

    es_pairs: list[int] = []
    for ed, next_ed in zip(eds[:-1], eds[1:]):
        segment = smooth[int(ed) + 1 : int(next_ed)]
        if segment.size == 0:
            continue
        es_pairs.append(int(ed) + 1 + int(np.argmin(segment)))
    return eds, es_pairs, corrected


# ── Confidence, cycles, φ ───────────────────────────────────────────────────


def _clamp01(value: float) -> float:
    return min(1.0, max(0.0, value))


def _clip_confidence(fit_r2: float, agreement: float, regularity: float, support_corr: float | None) -> float:
    """Multiplicative evidence: fit quality × concordance × regularity.

    Every factor can veto: a clip whose carriers are periodic but never agree,
    or whose anchors arrive at irregular gaps, cannot reach the acceptance
    gate through one strong term alone.  With a single carrier the agreement
    factor rests at its neutral 0.8 — no free concordance credit.
    """
    confidence = fit_r2 * (0.6 + 0.4 * agreement) * (0.7 + 0.3 * regularity)
    if support_corr is not None:
        confidence *= 1.0 + _SUPPORT_BONUS * support_corr
    return _clamp01(confidence)


def _anchor_regularity(eds: np.ndarray) -> float:
    """How uniform the ED-to-ED gaps are (1.0 = metronomic; 0.6 when unknown).

    Same neutral value as the ``cine_phase_timeline`` regularity prior.
    """
    gaps = np.diff(eds)
    if gaps.size < 2:
        return 0.6
    mean_gap = float(np.mean(gaps))
    if mean_gap <= 1e-9:
        return 0.6
    return 1.0 - _clamp01(float(np.std(gaps)) / mean_gap)


def _virtual_ed_before(first_ed: int, median_gap: float) -> float:
    """Largest extrapolated ED position ≤ 0 covering the leading frames."""
    return float(first_ed) - median_gap * max(1, math.ceil(float(first_ed) / median_gap))


def _median_anchor_gap(eds: np.ndarray, period: float) -> float:
    """Median ED-to-ED gap; the fitted period when only one anchor exists.

    The gaps are integer frame distances between equivariant anchors, so —
    unlike the refined period, whose least-squares polish is exactly
    equivariant only at periods dividing the clip length — the median gap
    keeps φ exactly equivariant under a circular shift.
    """
    gaps = np.diff(eds)
    if gaps.size < 1:
        return float(period)
    return max(2.0, float(np.median(gaps)))


def _build_cycles(
    composite: np.ndarray,
    eds: np.ndarray,
    es_pairs: Sequence[int],
    n_frames: int,
    period: float,
    clip_confidence: float,
) -> tuple[PhaseFieldCycle, ...]:
    """Cycle entries: leading partial, complete cycles, extrapolated tail.

    The leading entry spans at most one period (a longer leading region would
    wrap φ inside a single entry); earlier frames stay covered by φ's ramp
    but belong to no reportable cycle.
    """
    rng = float(np.percentile(composite, 95) - np.percentile(composite, 5))
    if rng <= 1e-9:
        rng = 1.0
    median_gap = _median_anchor_gap(eds, period)
    cycles: list[PhaseFieldCycle] = []

    first_ed = int(eds[0])
    if first_ed >= 3:
        start = max(0, first_ed - max(3, int(round(median_gap))))
        es0 = start + int(np.argmin(composite[start:first_ed]))
        prominence = (float(composite[first_ed]) - float(composite[es0])) / rng
        cycles.append(
            PhaseFieldCycle(
                ed_frame=start,
                es_frame=es0,
                end_frame=first_ed,
                confidence=_cycle_confidence(clip_confidence, prominence, partial=True),
                partial=True,
            )
        )

    for ed, next_ed, es in zip(eds[:-1], eds[1:], es_pairs):
        prominence = (float(composite[int(ed)]) - float(composite[es])) / rng
        cycles.append(
            PhaseFieldCycle(
                ed_frame=int(ed),
                es_frame=es,
                end_frame=int(next_ed),
                confidence=_cycle_confidence(clip_confidence, prominence, partial=False),
                partial=False,
            )
        )

    last_ed = int(eds[-1])
    window = max(2, int(round(median_gap)))
    end = last_ed + window
    for _ in range(_MAX_TRAILING_WINDOWS):
        if end > n_frames:
            end = n_frames
        if end - last_ed < 2:
            break
        segment = composite[last_ed + 1 : end]
        es_t = last_ed + 1 + int(np.argmin(segment)) if segment.size else last_ed
        prominence = (float(composite[last_ed]) - float(composite[es_t])) / rng
        cycles.append(
            PhaseFieldCycle(
                ed_frame=last_ed,
                es_frame=es_t,
                end_frame=end,
                confidence=_cycle_confidence(clip_confidence, prominence, partial=True),
                partial=True,
            )
        )
        if end >= n_frames:
            break
        last_ed, end = end, end + window
    return tuple(cycles)


def _cycle_confidence(clip_confidence: float, prominence: float, partial: bool) -> float:
    confidence = clip_confidence * (0.5 + 0.5 * _clamp01(prominence))
    if partial:
        confidence *= 0.85
    return round(_clamp01(confidence), 4)


def _phi_curve(eds: np.ndarray, n_frames: int, period: float) -> np.ndarray:
    """φ(t) ∈ [0, 1): cycle-normalised time — monotone inside every cycle.

    Complete cycles map linearly between their ED anchors; truncated
    leading/trailing regions ride the fitted period as flagged extrapolation.
    The plain ramp (rather than an ES-warped coordinate) keeps φ exactly
    equivariant under a circular shift of the clip — the mechanical ES is
    read from the cycle entries, and its fraction from
    :attr:`PhaseFieldCycle.systole_fraction`.
    """
    phi = np.zeros(n_frames, dtype=np.float64)
    if eds.size == 0:
        return phi
    median_gap = _median_anchor_gap(eds, period)

    first_ed = int(eds[0])
    if first_ed > 0:
        virtual = _virtual_ed_before(first_ed, median_gap)
        leading = np.arange(0, first_ed, dtype=np.int64)
        phi[leading] = np.mod((leading - virtual) / median_gap, 1.0)

    for ed, next_ed in zip(eds[:-1], eds[1:]):
        ed_i, next_i = int(ed), int(next_ed)
        if next_i - ed_i < 1:
            continue
        frames = np.arange(ed_i, next_i, dtype=np.int64)
        phi[frames] = (frames - ed_i) / float(next_i - ed_i)

    last_ed = int(eds[-1])
    if last_ed < n_frames:
        trailing = np.arange(last_ed, n_frames, dtype=np.int64)
        phi[trailing] = np.mod((trailing - last_ed) / median_gap, 1.0)
    return np.clip(phi, 0.0, 1.0 - 1e-9)


def _support_correlation(flow: np.ndarray, composite: np.ndarray, period: float) -> float | None:
    """|corr| of the polarity-free flow with the composite at the beat lag."""
    max_shift = max(1, int(round(0.25 * period)))
    _aligned, corr = _best_circular_shift(flow, composite, max_shift)
    magnitude = abs(corr)
    return magnitude if magnitude >= _SUPPORT_MIN_CORR else None


# ── Builder ─────────────────────────────────────────────────────────────────


def _resolve_n_frames(
    n_frames: int | None,
    gray: np.ndarray | None,
    area_curve: np.ndarray | Sequence[float] | None,
    lv_masks: np.ndarray | Sequence[np.ndarray] | None,
) -> int:
    for candidate in (
        n_frames,
        int(gray.shape[0]) if gray is not None else None,
        len(area_curve) if area_curve is not None else None,
        len(lv_masks) if lv_masks is not None else None,
    ):
        if candidate is not None and int(candidate) > 0:
            return int(candidate)
    return 0


def _validated_frame_time(frame_time_ms: float | None) -> float | None:
    if frame_time_ms is None:
        return None
    value = float(frame_time_ms)
    if not math.isfinite(value) or value <= 0:
        return None
    return value


def _zscored(values: np.ndarray | Sequence[float] | None, n_frames: int) -> np.ndarray | None:
    """Z-score a candidate carrier.

    No linear detrend on purpose: a per-clip linear fit is *not* equivariant
    under circular shift or time reversal, and both are acceptance invariants
    of the phase field.  Image proxies arrive gain-normalised per frame from
    :mod:`cine_phase_image_signals` already, and a trend-driven pseudo-period
    cannot pass the adjusted-R² gate of the harmonic fit.
    """
    if values is None:
        return None
    arr = np.asarray(values, dtype=np.float64).reshape(-1)
    if arr.size != n_frames:
        return None
    if not np.isfinite(arr).all():
        good = np.isfinite(arr)
        if int(good.sum()) < max(2, n_frames // 2):
            return None
        idx = np.arange(n_frames, dtype=np.float64)
        arr = np.interp(idx, idx[good], arr[good])
    std = float(arr.std())
    if std < 1e-9:
        return None
    return (arr - float(arr.mean())) / std


def _unavailable(n_frames: int, frame_time_ms: float | None, warnings: Sequence[str]) -> PhaseField:
    return PhaseField(
        n_frames=max(0, n_frames),
        frame_time_ms=frame_time_ms,
        phi=np.zeros(max(0, n_frames), dtype=np.float64),
        ed_frames=(),
        es_frames=(),
        cycles=(),
        source_signal="",
        period_frames=0.0,
        confidence=0.0,
        warnings=tuple(sorted(set(warnings))),
    )


def build_phase_field(
    *,
    n_frames: int | None = None,
    frame_time_ms: float | None = None,
    frames: np.ndarray | Sequence[np.ndarray] | None = None,
    area_curve: np.ndarray | Sequence[float] | None = None,
    lv_masks: np.ndarray | Sequence[np.ndarray] | None = None,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> PhaseField:
    """Build the continuous phase field φ(t) for one cine clip, without ECG.

    Args:
        n_frames: number of frames (authoritative when given; otherwise taken
            from ``frames``, then ``area_curve``, then ``lv_masks``).
        frame_time_ms: DICOM ``FrameTime`` / video fps in ms; ``None`` keeps
            all reasoning in frames and adds a ``frame_time_unknown`` warning.
        frames: optional ``(N,H,W)`` or ``(N,H,W,3|4)`` stack — the worker
            normally passes a spatially reduced copy.
        area_curve: LV cavity-area-like curve (from segmentation or a stored
            Simpson curve), ED = maximum.  ``NaN`` entries are interpolated.
        lv_masks: optional boolean LV mask stack; its per-frame area is used
            only when no ``area_curve`` is supplied.
        min_confidence: below this the field carries no cycles and φ ≡ 0.

    Returns:
        A :class:`PhaseField`.  Never raises for bad input: unusable data
        produces an empty field with ``warnings``.
    """
    warnings: list[str] = []
    gray = _gray_stack(frames) if frames is not None else None
    n = _resolve_n_frames(n_frames, gray, area_curve, lv_masks)
    if n < _MIN_FRAMES:
        return _unavailable(max(0, n), None, ("no_frames",))
    frame_time = _validated_frame_time(frame_time_ms)
    if frame_time is None:
        warnings.append("frame_time_unknown")

    candidates = extract_phase_candidates(
        frames=None if gray is None else gray,
        area_curve=area_curve,
        lv_masks=lv_masks,
    )
    carriers: dict[str, np.ndarray] = {}
    for name in _CARRIER_WEIGHTS:
        if name not in candidates:
            continue
        if np.asarray(candidates[name]).size != n:
            warnings.append(f"{name}_length_mismatch")
            continue
        z = _zscored(candidates[name], n)
        if z is not None:
            carriers[name] = z
    flow = _zscored(candidates.get("flow"), n)

    fps = 1000.0 / frame_time if frame_time is not None else None
    band = _period_band(n, fps)
    scored: list[tuple[str, float, float]] = []
    for name in sorted(carriers, key=lambda s: (-_CARRIER_WEIGHTS[s], s)):
        found = _harmonic_period(carriers[name], band)
        if found is not None and found[1] >= _MIN_FIT_R2:
            scored.append((name, found[0], found[1]))
    if not scored:
        if flow is not None and _harmonic_period(flow, band) is not None:
            _, flow_r2 = _harmonic_period(flow, band) or (0.0, 0.0)
            if flow_r2 >= _MIN_FIT_R2:
                warnings.append("motion_only")
        warnings.append("no_periodic_signal")
        return _unavailable(n, frame_time, warnings)

    period0 = _consensus_period([period for _name, period, _r2 in scored])
    composed = _compose(carriers, scored, period0, warnings)
    if composed is None:
        warnings.append("no_periodic_signal")
        return _unavailable(n, frame_time, warnings)
    composite, agreement, reference_name = composed

    period_fit = _harmonic_period(composite, band)
    if period_fit is None:  # pragma: no cover - gated carriers guarantee a fit
        warnings.append("no_periodic_signal")
        return _unavailable(n, frame_time, warnings)
    period, fit_r2 = period_fit
    smooth = _smooth_signal(composite, period)
    eds, es_pairs, gap_corrected = _anchors(composite, smooth, period)
    if gap_corrected:
        warnings.append("irregular_anchors")
    if eds.size == 0:
        warnings.append("no_cycles")
        return _unavailable(n, frame_time, warnings)

    support_corr = _support_correlation(flow, composite, period) if flow is not None else None
    clip_confidence = _clip_confidence(fit_r2, agreement, _anchor_regularity(eds), support_corr)

    cycles = _build_cycles(composite, eds, es_pairs, n, period, clip_confidence)
    phi = _phi_curve(eds, n, period)
    if clip_confidence < min_confidence:
        warnings.append("low_confidence")
        cycles = ()
        phi = np.zeros(n, dtype=np.float64)
    if any(c.partial for c in cycles):
        warnings.append("partial_cycles")

    return PhaseField(
        n_frames=n,
        frame_time_ms=frame_time,
        phi=phi,
        ed_frames=tuple(int(e) for e in eds),
        es_frames=tuple(c.es_frame for c in cycles),
        cycles=cycles,
        source_signal=reference_name,
        period_frames=float(period),
        confidence=round(float(clip_confidence), 4),
        warnings=tuple(sorted(set(warnings))),
    )


# ── Bridges (plan А.3 step 4) ───────────────────────────────────────────────


def phase_field_to_ed_es_mapping(field: PhaseField) -> EcEDFrameMapping:
    """Express the field in the ``ecg_ed_es_mapper`` vocabulary (source=image).

    The best cycle supplies ED/ES and the cycle bounds; without an accepted
    cycle the mapper's own image-fallback sentinel is returned so routing
    (plan А.4) can treat both paths uniformly.
    """
    cycle = field.best_cycle()
    if cycle is None:
        return EcEDFrameMapping(
            ed_frame_index=0,
            es_frame_index=max(1, field.n_frames // 3),
            cycle_start_frame=0,
            cycle_end_frame=max(0, field.n_frames - 1),
            source="image",
        )
    return EcEDFrameMapping(
        ed_frame_index=cycle.ed_frame,
        es_frame_index=cycle.es_frame,
        cycle_start_frame=cycle.ed_frame,
        cycle_end_frame=min(cycle.end_frame - 1, field.n_frames - 1),
        source="image",
    )


def phase_field_to_cardiac_cycles(field: PhaseField) -> list[CardiacCycle]:
    """Express complete cycles in the ``cardiac_cycle_service`` ms domain.

    Partial (extrapolated) cycles are skipped — the Doppler service averages
    complete beats only.  Empty list when ``frame_time_ms`` is unknown.
    """
    from echo_personal_tool.domain.services.cardiac_cycle_service import CardiacCycle

    frame_time = field.frame_time_ms
    if frame_time is None or frame_time <= 0:
        return []
    cycles: list[CardiacCycle] = []
    for cycle in field.cycles:
        if cycle.partial or cycle.duration_frames <= 0:
            continue
        start_ms = cycle.ed_frame * frame_time
        end_ms = cycle.end_frame * frame_time
        cycles.append(
            CardiacCycle(
                start_ms=start_ms,
                end_ms=end_ms,
                r_peak_ms=start_ms,
                ed_ms=start_ms,
                es_ms=cycle.es_frame * frame_time,
                source="image",
                confidence=float(cycle.confidence),
                rr_ms=end_ms - start_ms,
            )
        )
    return cycles


def phase_field_ed_es_fallback(
    *,
    frames: np.ndarray | Sequence[np.ndarray] | None = None,
    area_curve: np.ndarray | Sequence[float] | None = None,
    lv_masks: np.ndarray | Sequence[np.ndarray] | None = None,
    frame_time_ms: float | None = None,
) -> Callable[[], tuple[int, int]]:
    """Adapter for ``detect_ed_es_for_cine(image_fallback=...)`` (image source).

    The returned callable never raises — :func:`build_phase_field` already
    degrades to an empty field for unusable input — and yields the
    ``(ed, es)`` frame indices of the best cycle, or the mapper's generic
    fallback sentinel when the field was rejected.
    """

    def fallback() -> tuple[int, int]:
        field = build_phase_field(
            frames=frames,
            area_curve=area_curve,
            lv_masks=lv_masks,
            frame_time_ms=frame_time_ms,
        )
        cycle = field.best_cycle()
        if cycle is None:
            return 0, max(1, field.n_frames // 3)
        return cycle.ed_frame, cycle.es_frame

    return fallback
