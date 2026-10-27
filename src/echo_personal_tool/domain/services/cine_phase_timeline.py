"""Frame-by-frame cardiac phase labelling for echo cine loops, with and without ECG.

Pure NumPy/SciPy: no Qt, no file I/O, no DICOM.  The module answers one question —
"which frames of this clip are systole, which are diastole, and how sure are we?" —
and returns a :class:`PhaseTimeline` that both the main viewer and the STE window
can draw on their playback bars.

Design notes (full rationale in
``docs/superpowers/specs/2026-10-26-cine-phase-timeline-markers-ru.md``):

* ECG gives **ED and RR only**.  ES is a mechanical event and is refined from an
  image/area/strain signal; without one it is a documented prior estimate.
* Without ECG the phase comes from a periodic "area-like" signal (ED = maximum,
  ES = minimum): a supplied area/strain curve, or image-derived dark-pool and
  intensity proxies.  Period comes from autocorrelation, extrema from
  prominence-filtered peaks, and the polarity of an unlabelled signal is chosen
  from duration/curvature priors (or a single manual anchor).
* Confidence is part of the result.  Below ``min_confidence`` every frame is
  ``unknown``: the UI must never paint a confident-looking guess.

This is a visual/navigation aid, not a validated clinical measurement.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

import numpy as np
from scipy.ndimage import uniform_filter1d
from scipy.signal import detrend, find_peaks, savgol_filter

from echo_personal_tool.domain.services.cine_phase_image_signals import image_phase_signals

SCHEMA_VERSION = "1.0"

PHASE_SYSTOLE = "systole"
PHASE_DIASTOLE = "diastole"
PHASE_UNKNOWN = "unknown"

SOURCE_UNAVAILABLE = "unavailable"

DEFAULT_MIN_CONFIDENCE = 0.35
_DEFAULT_FRAME_TIME_MS = 33.3  # only used when DICOM/MP4 metadata has no fps
_MIN_HR_BPM = 35.0
_MAX_HR_BPM = 200.0

#: Relative trust in a phase source.  Used for confidence, not for hard gating:
#: a weak source may still win if it is the only periodic signal present.
_SOURCE_WEIGHTS: dict[str, float] = {
    "area": 1.00,
    "strain": 0.95,
    "burned_ecg": 0.80,
    "dark_pool": 0.80,
    "intensity": 0.70,
    "unlabelled": 0.70,
    "motion": 0.40,
}

# ── Value types ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PhaseCycle:
    """One cardiac cycle in frame coordinates.

    ``ed_frame`` is inclusive, ``end_frame`` exclusive (the next ED or the end
    of the clip).  ``partial`` marks a truncated first/last cycle; the UI draws
    it hatched and never treats it as a complete measured beat.
    """

    ed_frame: int
    es_frame: int
    end_frame: int
    confidence: float
    source: str
    partial: bool = False

    @property
    def duration_frames(self) -> int:
        return max(0, self.end_frame - self.ed_frame)

    @property
    def systole_frames(self) -> int:
        return max(0, self.es_frame - self.ed_frame)


@dataclass(frozen=True)
class PhaseSegment:
    """A continuous run of one phase, ready to be painted on the timeline."""

    start_frame: int  # inclusive
    end_frame: int  # exclusive
    phase: str
    confidence: float
    source: str
    cycle_index: int


@dataclass(frozen=True)
class PhaseMarker:
    """A discrete event chip (ED/ES) on the playback bar."""

    frame: int
    kind: str  # "ed" | "es"
    label: str  # short UI label
    confidence: float
    source: str
    cycle_index: int
    partial: bool = False


@dataclass(frozen=True)
class PhaseTimeline:
    """Complete, serialisable phase annotation of one cine clip."""

    n_frames: int
    frame_time_ms: float | None
    labels: tuple[str, ...]  # one of PHASE_* per frame
    cycles: tuple[PhaseCycle, ...]
    source: str
    confidence: float
    warnings: tuple[str, ...] = ()
    schema_version: str = SCHEMA_VERSION

    def phase_at(self, frame: int) -> str:
        if 0 <= frame < len(self.labels):
            return self.labels[frame]
        return PHASE_UNKNOWN

    def segments(self) -> tuple[PhaseSegment, ...]:
        """Merge the per-cycle phases into a paint-ready list of runs."""
        if not any(p in (PHASE_SYSTOLE, PHASE_DIASTOLE) for p in self.labels):
            return (PhaseSegment(0, self.n_frames, PHASE_UNKNOWN, 0.0, self.source, -1),) if self.n_frames else ()
        segments: list[PhaseSegment] = []
        cursor = 0
        for index, cycle in enumerate(self.cycles):
            ed = _clip_int(cycle.ed_frame, 0, self.n_frames)
            es = _clip_int(cycle.es_frame, ed, self.n_frames)
            end = _clip_int(cycle.end_frame, es, self.n_frames)
            if ed > cursor:
                segments.append(PhaseSegment(cursor, ed, PHASE_UNKNOWN, 0.0, self.source, -1))
            if es > ed:
                segments.append(PhaseSegment(ed, es, PHASE_SYSTOLE, cycle.confidence, cycle.source, index))
            if end > es:
                segments.append(PhaseSegment(es, end, PHASE_DIASTOLE, cycle.confidence, cycle.source, index))
            cursor = max(cursor, end)
        if cursor < self.n_frames:
            segments.append(PhaseSegment(cursor, self.n_frames, PHASE_UNKNOWN, 0.0, self.source, -1))
        return tuple(segments)

    def markers(self) -> tuple[PhaseMarker, ...]:
        """ED/ES chips only when a phase was actually accepted, never a guess."""
        if not any(p in (PHASE_SYSTOLE, PHASE_DIASTOLE) for p in self.labels):
            return ()
        result: list[PhaseMarker] = []
        for index, cycle in enumerate(self.cycles):
            if not (0 <= cycle.ed_frame < self.n_frames):
                continue
            result.append(
                PhaseMarker(
                    frame=cycle.ed_frame,
                    kind="ed",
                    label="ED",
                    confidence=cycle.confidence,
                    source=cycle.source,
                    cycle_index=index,
                    partial=cycle.partial,
                )
            )
            if 0 <= cycle.es_frame < self.n_frames:
                result.append(
                    PhaseMarker(
                        frame=cycle.es_frame,
                        kind="es",
                        label="ES",
                        confidence=cycle.confidence,
                        source=cycle.source,
                        cycle_index=index,
                        partial=cycle.partial,
                    )
                )
        return tuple(result)

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

    def with_manual_ed_es(self, cycle_index: int, ed_frame: int, es_frame: int) -> PhaseTimeline:
        """Apply a user drag of the ED/ES chips and rebuild the frame labels.

        Only the chosen cycle changes; its ``source`` becomes ``"manual"`` so the
        UI/export can distinguish a confirmed frame from a computed one.  The
        automatic result is *not* mutated, which keeps "reset correction" cheap.
        """
        if not (0 <= cycle_index < len(self.cycles)):
            return self
        old = self.cycles[cycle_index]
        ed = _clip_int(ed_frame, 0, old.end_frame - 1)
        es = _clip_int(es_frame, ed + 1, old.end_frame - 1)
        if es <= ed:
            es = min(ed + 1, old.end_frame - 1)
        corrected = replace(
            old,
            ed_frame=ed,
            es_frame=es,
            confidence=1.0,
            source="manual",
        )
        cycles = tuple(replace(c) if i != cycle_index else corrected for i, c in enumerate(self.cycles))
        source = "manual" if all(c.source == "manual" for c in cycles) else f"{self.source}+manual"
        return replace(
            self,
            cycles=cycles,
            labels=_labels_from_cycles(self.n_frames, cycles),
            source=source,
            confidence=max(self.confidence, 0.9),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "n_frames": self.n_frames,
            "frame_time_ms": self.frame_time_ms,
            "labels": list(self.labels),
            "cycles": [
                {
                    "ed_frame": c.ed_frame,
                    "es_frame": c.es_frame,
                    "end_frame": c.end_frame,
                    "confidence": c.confidence,
                    "source": c.source,
                    "partial": c.partial,
                }
                for c in self.cycles
            ],
            "source": self.source,
            "confidence": self.confidence,
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PhaseTimeline:
        cycles = tuple(
            PhaseCycle(
                ed_frame=int(c["ed_frame"]),
                es_frame=int(c["es_frame"]),
                end_frame=int(c["end_frame"]),
                confidence=float(c.get("confidence", 0.0)),
                source=str(c.get("source", SOURCE_UNAVAILABLE)),
                partial=bool(c.get("partial", False)),
            )
            for c in data.get("cycles", [])
        )
        n_frames = int(data.get("n_frames", 0))
        labels = tuple(str(p) for p in data.get("labels", []))
        if len(labels) != n_frames:
            labels = _labels_from_cycles(n_frames, cycles)
        return cls(
            n_frames=n_frames,
            frame_time_ms=data.get("frame_time_ms"),
            labels=labels,
            cycles=cycles,
            source=str(data.get("source", SOURCE_UNAVAILABLE)),
            confidence=float(data.get("confidence", 0.0)),
            warnings=tuple(str(w) for w in data.get("warnings", [])),
            schema_version=str(data.get("schema_version", SCHEMA_VERSION)),
        )


# ── Public API ──────────────────────────────────────────────────────────────


def build_phase_timeline(
    *,
    n_frames: int,
    frame_time_ms: float | None = None,
    frames: np.ndarray | None = None,
    area_curve: np.ndarray | None = None,
    strain_curve: np.ndarray | None = None,
    unlabelled_curve: np.ndarray | None = None,
    ecg_r_peaks_ms: np.ndarray | None = None,
    ecg_confidence: float = 1.0,
    ecg_offset_ms: float = 0.0,
    align_ecg: bool = True,
    burned_ecg_r_peaks_ms: np.ndarray | None = None,
    manual_anchor: tuple[int, str] | None = None,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> PhaseTimeline:
    """Label every frame of a cine clip as systole / diastole / unknown.

    Args:
        n_frames: number of frames in the clip (authoritative).
        frame_time_ms: DICOM ``FrameTime`` / video fps in ms; ``None`` is
            tolerated (all reasoning stays in frames), but adds a warning.
        frames: optional ``(N,H,W)`` or ``(N,H,W,3)`` stack.  Only used to
            derive image signals; the worker normally passes a 64x64 version.
        area_curve: optional LV area-like curve, ED = maximum, ES = minimum.
            ``NaN`` entries (frames outside an analysis window) are interpolated.
        strain_curve: optional global longitudinal strain curve (ED ~ 0,
            ES = most negative), i.e. also ED = maximum, ES = minimum.
        unlabelled_curve: optional periodic signal whose polarity is unknown
            (a vendor index, a motion trace).  Which extrema are ED is chosen
            from duration/curvature priors or by ``manual_anchor``.
        ecg_r_peaks_ms: R-peak times in the ECG recording's own time base.
        ecg_confidence: detector confidence for those peaks (0..1).
        ecg_offset_ms: time from ECG recording start to cine frame 0.  When
            non-zero it is trusted (e.g. from ``TriggerTime``) and auto-alignment
            is skipped.
        align_ecg: search the offset against the area-like signal when no
            trusted offset is supplied (fixes the STE §2.5 trigger-offset bug).
        burned_ecg_r_peaks_ms: R-peaks recovered from an ECG trace drawn into
            the video pixels; used only when there is no real waveform.
        manual_anchor: ``(frame, "ed"|"es")`` — one user click that resolves the
            polarity of an unlabelled image signal.
        min_confidence: below this the whole clip is labelled ``unknown``.

    Returns:
        A :class:`PhaseTimeline`.  Never raises for bad input: unusable data
        produces an all-``unknown`` timeline with ``warnings``.
    """
    n = int(n_frames)
    if n <= 0:
        return _unavailable(0, frame_time_ms, ("no_frames",))

    warnings: set[str] = set()
    ft: float | None = float(frame_time_ms) if frame_time_ms and frame_time_ms > 0 else None
    ft_eff = ft if ft else _DEFAULT_FRAME_TIME_MS
    fps = 1000.0 / ft_eff
    if ft is None:
        warnings.add("frame_time_unknown")

    gray, _color = _prepare_frames(frames, n)
    raw_signals: list[tuple[str, np.ndarray, float, bool]] = []  # name, values, weight, polarity_known

    supplied_area = _as_vector(area_curve, n)
    if supplied_area is not None:
        raw_signals.append(("area", supplied_area, _SOURCE_WEIGHTS["area"], True))
    supplied_strain = _as_vector(strain_curve, n)
    if supplied_strain is not None:
        # Longitudinal strain is ~0 at ED and negative at ES => ED is the max.
        raw_signals.append(("strain", supplied_strain, _SOURCE_WEIGHTS["strain"], True))
    supplied_unlabelled = _as_vector(unlabelled_curve, n)
    if supplied_unlabelled is not None:
        raw_signals.append(("unlabelled", supplied_unlabelled, _SOURCE_WEIGHTS["unlabelled"], False))

    if gray is not None:
        dark, inten, _motion = image_phase_signals(gray)
        if dark.size == n:
            raw_signals.append(("dark_pool", dark, _SOURCE_WEIGHTS["dark_pool"], True))
        if inten.size == n:
            # Bright myocardium fills the fixed ROI in systole => invert so ED = max.
            raw_signals.append(("intensity", -inten, _SOURCE_WEIGHTS["intensity"], True))
        # Motion can have two bursts per beat and has no ED/ES polarity.
        # It must never become the phase source or shift area/ECG extrema.
        # A static ECG trace's width is NOT the cine duration. Without sweep
        # calibration there is no valid x->frame mapping. Only explicitly
        # aligned burned_ecg_r_peaks_ms may supply electrical timing.

    signals = _build_signals(raw_signals, fps, ft_eff, manual_anchor)
    r_peaks = _as_peak_times(ecg_r_peaks_ms)
    ecg_weight = float(ecg_confidence)
    ecg_is_burned = False
    burned = _as_peak_times(burned_ecg_r_peaks_ms)
    if r_peaks.size < 2 and burned.size >= 2:
        # A trace burned into the pixels already shares the video time base.
        r_peaks = burned
        ecg_is_burned = True
        ecg_weight = 0.6
        warnings.add("burned_ecg")
    if not signals and r_peaks.size < 2:
        warnings.add("no_periodic_signal")
        return _unavailable(n, ft, tuple(sorted(warnings)))

    best: _Signal | None = None
    cycles: list[PhaseCycle] = []
    source = SOURCE_UNAVAILABLE
    confidence = 0.0
    if signals:
        best, cycles, _ = _best_signal_cycles(signals, n, ft_eff, warnings)
        if cycles:
            agreement = _fuse_extrema(cycles, signals, best)
            source = best.name
            confidence = _clamp(best.weight * (0.75 * best.q_signal + 0.25 * agreement))

    # ── ECG path: electrical timing for ED, image timing for ES ─────────────
    # When frame_time_ms is missing, infer it from the ECG heart rate and
    # clip duration — many DICOMs carry an ECG waveform but omit FrameTime.
    ft_ecg = ft
    if ft_ecg is None and r_peaks.size >= 3 and ecg_weight >= 0.3:
        rr_vals = np.diff(r_peaks)
        median_rr = float(np.median(rr_vals)) if rr_vals.size else 0.0
        if median_rr > 0:
            # Estimate beats in the clip from a provisional ~30 fps assumption.
            est_beats = max(1.0, n / (median_rr / _DEFAULT_FRAME_TIME_MS))
            inferred = median_rr * est_beats / n
            if 15.0 <= inferred <= 100.0:  # 10–66 fps plausibility gate
                ft_ecg = inferred
                warnings.add("frame_time_inferred")
    if r_peaks.size >= 2 and ecg_weight >= 0.3 and ft_ecg is not None:
        ecg = _cycles_from_ecg(
            r_peaks,
            n,
            ft_ecg,
            best.y if best is not None and (best.polarity_known or manual_anchor is not None) else None,
            offset_ms=ecg_offset_ms,
            align=align_ecg and not ecg_is_burned,
            trusted_alignment=ecg_is_burned,
            warnings=warnings,
        )
        if ecg.cycles:
            cycles = ecg.cycles
            has_image_es = any(c.source == "ecg+area" for c in cycles)
            source = ("burned_ecg" if ecg_is_burned else "ecg") + ("+area" if has_image_es else "+prior")
            alignment_factor = 0.70 + 0.30 * ecg.alignment_quality
            confidence = _clamp(ecg_weight * alignment_factor * (0.95 if has_image_es else 0.75))
            if ecg.irregular:
                warnings.add("irregular_rhythm")
                confidence *= 0.85
            if ecg_is_burned:
                cycles = [replace(c, source=c.source.replace("ecg", "burned_ecg")) for c in cycles]
        else:
            warnings.add("ecg_unusable")
    elif r_peaks.size >= 2:
        warnings.add("ecg_unusable")

    if not cycles:
        warnings.add("no_cycles")
        return _unavailable(n, ft, tuple(sorted(warnings)))

    labels = _labels_from_cycles(n, cycles)
    if confidence < min_confidence:
        warnings.add("low_confidence")
        labels = (PHASE_UNKNOWN,) * n
        # Keeping guessed cycles here used to paint ED/ES chips and coloured
        # segments even though phase_at() honestly returned unknown.
        cycles = []
    if any(c.partial for c in cycles):
        warnings.add("partial_cycles")

    return PhaseTimeline(
        n_frames=n,
        frame_time_ms=ft,
        labels=labels,
        cycles=tuple(cycles),
        source=source,
        confidence=round(confidence, 4),
        warnings=tuple(sorted(warnings)),
    )


# ── Signal extraction from pixels ───────────────────────────────────────────


def dark_pool_signal(gray_frames: np.ndarray) -> np.ndarray:
    """Gain-normalised dark fraction in the tissue sector; ED=max, ES=min."""
    return image_phase_signals(gray_frames)[0]


def intensity_signal(gray_frames: np.ndarray) -> np.ndarray:
    """Gain-normalised tissue brightness (ES=max); no black-sector pixels."""
    return image_phase_signals(gray_frames)[1]


def motion_signal(gray_frames: np.ndarray) -> np.ndarray:
    """Gain-normalised inter-frame difference, never an ED/ES polarity cue."""
    return image_phase_signals(gray_frames)[2]


def burned_ecg_signal(color_frames: np.ndarray, frame_time_ms: float, n_frames: int) -> np.ndarray | None:
    """Recover R-peak times from a green ECG trace drawn into the video.

    Diagnostic prototype only, not used automatically: a static trace has no
    known sweep speed or offset relative to frame zero. Locate green-dominant
    pixels in the lower quarter and detect sharp upstrokes. The returned times
    assume ``x`` spans the clip duration; a caller must calibrate that assumption
    before passing them to build_phase_timeline. Returns ``None`` when the trace
    is missing, grayscale, or the implied HR is implausible.  Known limits
    (yellow/white traces, non-linear sweep, cropped trace) are P1 work.
    """
    arr = np.asarray(color_frames)
    if arr.ndim != 4 or arr.shape[-1] < 3 or arr.shape[0] < 8 or frame_time_ms <= 0:
        return None
    band = arr[:, int(arr.shape[1] * 0.70) :, :, :3].astype(np.float32)
    red, green, blue = band[..., 0], band[..., 1], band[..., 2]
    mask = (green > red * 1.2) & (green > blue * 1.2) & (green > 60)
    if float(mask.mean()) < 0.001 or float(mask.mean()) > 0.35:
        return None
    width = mask.shape[2]
    combined = np.any(mask, axis=0)  # (h, w): trace present in at least one frame
    trace = np.full(width, np.nan, dtype=np.float64)
    for x in range(width):
        ys = np.nonzero(combined[:, x])[0]
        if ys.size >= 1:
            trace[x] = float(np.median(ys))
    if np.isfinite(trace).sum() < width * 0.5:
        return None
    idx = np.arange(width)
    good = np.isfinite(trace)
    trace = np.interp(idx, idx[good], trace[good])
    span = float(np.percentile(trace, 95) - np.percentile(trace, 5))
    if span < 3.0:
        return None
    peaks, _ = find_peaks(-trace, prominence=max(2.0, 0.2 * span), distance=max(3, width // 12))
    if peaks.size < 2 or peaks.size > 14:
        return None
    duration_ms = n_frames * frame_time_ms
    times = peaks / max(1, width - 1) * duration_ms
    rr = np.diff(times)
    if rr.size and (np.median(rr) < 60000.0 / _MAX_HR_BPM or np.median(rr) > 60000.0 / _MIN_HR_BPM):
        return None
    return np.asarray(times, dtype=np.float64)


# ── Internal: signal preparation ────────────────────────────────────────────


@dataclass
class _Signal:
    name: str
    y: np.ndarray  # z-normalised, area-like when polarity_known / ed_at_max
    weight: float
    polarity_known: bool
    ed_at_max: bool
    period: int
    strength: float
    ed_idx: np.ndarray
    es_idx: np.ndarray
    q_signal: float
    polarity_margin: float = 1.0


@dataclass
class _EcgCycles:
    cycles: list[PhaseCycle]
    alignment_quality: float
    irregular: bool


def _build_signals(
    raw: list[tuple[str, np.ndarray, float, bool]],
    fps: float,
    frame_time_ms: float,
    manual_anchor: tuple[int, str] | None,
) -> list[_Signal]:
    prepared: list[_Signal] = []
    periods: list[float] = []
    for name, values, weight, polarity_known in raw:
        y = _normalise_signal(values)
        if y is None:
            continue
        period_info = _estimate_period(y, fps)
        if period_info is None:
            continue
        period, strength = period_info
        # White noise reaches ACF ≈ 0.33 somewhere in the HR search band;
        # 0.30 lets real-but-noisy echo clips through while still rejecting
        # pure noise (downstream extrema/regularity validation filters the rest).
        if strength < 0.30:
            continue
        prepared.append(
            _Signal(
                name=name,
                y=y,
                weight=weight,
                polarity_known=polarity_known,
                ed_at_max=True,
                period=period,
                strength=strength,
                ed_idx=np.zeros(0, dtype=np.int64),
                es_idx=np.zeros(0, dtype=np.int64),
                q_signal=0.0,
            )
        )
        if polarity_known:
            periods.append(float(period))
    if not prepared:
        return []

    # An image proxy may report a harmonic rather than the beat period.
    # Reconcile against the consensus of the polarity-known signals.
    consensus = float(np.median(periods)) if periods else 0.0
    for signal in prepared:
        if consensus > 0 and signal.period < 0.7 * consensus:
            signal.period = max(3, int(round(signal.period * 2)))

    valid: list[_Signal] = []
    for signal in prepared:
        _fill_extrema(signal, frame_time_ms, manual_anchor)
        if signal.ed_idx.size == 0 or signal.es_idx.size == 0:
            continue
        # Extrema must follow the period we measured.  Random spikes with a
        # single huge gap are artefacts, not cardiac cycles.
        gaps = np.diff(signal.ed_idx)
        if signal.ed_idx.size < 2 and signal.strength < 0.6:
            continue
        if gaps.size and (float(np.min(gaps)) < 0.70 * signal.period or float(np.max(gaps)) > 1.50 * signal.period):
            continue
        rng = float(np.percentile(signal.y, 95) - np.percentile(signal.y, 5))
        prom = 0.0
        # Prominence proxy: how far an extremum stands out from its neighbours.
        for idx in np.concatenate([signal.ed_idx, signal.es_idx]):
            lo, hi = max(1, int(idx) - 2), min(signal.y.size - 1, int(idx) + 2)
            prom += abs(signal.y[int(idx)] - 0.5 * (signal.y[lo] + signal.y[hi]))
        prom_ratio = _clamp(prom / max(1e-9, len(signal.ed_idx) + len(signal.es_idx)) / max(1e-9, rng))
        gaps = np.diff(signal.ed_idx)
        regularity = 1.0 - _clamp(float(np.std(gaps)) / max(1e-9, float(np.mean(gaps)))) if gaps.size >= 2 else 0.6
        signal.q_signal = _clamp((0.5 * signal.strength + 0.3 * prom_ratio + 0.2 * regularity) * signal.polarity_margin)
        valid.append(signal)

    return valid


def _fill_extrema(signal: _Signal, frame_time_ms: float, manual_anchor: tuple[int, str] | None) -> None:
    y = signal.y
    rng = float(np.percentile(y, 95) - np.percentile(y, 5))
    prominence = max(0.15 * rng, 0.15)
    distance = max(2, int(0.6 * signal.period))
    hi, _ = find_peaks(y, prominence=prominence, distance=distance)
    lo, _ = find_peaks(-y, prominence=prominence, distance=distance)
    hi, lo = _with_edge_extrema(y, hi, lo, prominence, signal.period)
    if hi.size == 0 or lo.size == 0:
        return

    if signal.polarity_known:
        ed_at_max = True
    elif manual_anchor is not None:
        anchor_frame, anchor_kind = manual_anchor
        nearest_hi = int(hi[np.argmin(np.abs(hi - anchor_frame))])
        nearest_lo = int(lo[np.argmin(np.abs(lo - anchor_frame))])
        if anchor_kind == "ed":
            ed_at_max = abs(nearest_hi - anchor_frame) <= abs(nearest_lo - anchor_frame)
        else:
            ed_at_max = abs(nearest_lo - anchor_frame) <= abs(nearest_hi - anchor_frame)
    else:
        ed_at_max, margin = _score_polarity(y, hi, lo, signal.period, frame_time_ms)
        # An ambiguous prior is evidence of uncertainty, not a free decision.
        signal.polarity_margin = 0.3 + 0.7 * (1.0 - np.exp(-margin))

    signal.ed_at_max = ed_at_max
    ed, es = (hi, lo) if ed_at_max else (lo, hi)
    ed = np.asarray(ed, dtype=np.int64).copy()
    es = np.asarray(es, dtype=np.int64).copy()
    if not ed_at_max:
        signal.y = -y  # make the signal area-like for ES search / ECG alignment
    if manual_anchor is not None:
        anchor_frame, anchor_kind = manual_anchor
        target = ed if anchor_kind == "ed" else es
        if target.size:
            nearest = int(np.argmin(np.abs(target - anchor_frame)))
            if abs(int(target[nearest]) - anchor_frame) <= max(2, signal.period // 2):
                target[nearest] = int(anchor_frame)
                target.sort()
    signal.ed_idx = ed
    signal.es_idx = es


def _with_edge_extrema(
    y: np.ndarray,
    hi: np.ndarray,
    lo: np.ndarray,
    prominence: float,
    period: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Recover extrema that ``find_peaks`` misses at the clip borders.

    ``find_peaks`` needs a minimum on both sides, so a cine that *starts* at ED
    (a very common gated acquisition) loses its first — and most important —
    cycle.  Interior local extrema in the first/last half-period are added with
    one-sided prominence; index 0 is added only when it is clearly a peak
    (falling, not rising).  A rising tail at the end is never called an ED.
    """
    n = y.size
    if n < 6:
        return np.asarray(hi, dtype=np.int64), np.asarray(lo, dtype=np.int64)
    half = max(3, int(period // 2))
    hi_set, lo_set = set(int(i) for i in hi), set(int(i) for i in lo)
    for start, stop in ((0, min(n - 1, half)), (max(1, n - half), n)):
        for index in range(max(1, start), min(n - 1, stop)):
            left = y[max(0, index - half) : index]
            right = y[index + 1 : min(n, index + half)]
            window = np.concatenate([left, right])
            if window.size < 3:
                continue
            if y[index] > y[index - 1] and y[index] > y[index + 1]:
                if y[index] - float(np.min(window)) >= prominence:
                    hi_set.add(index)
            if y[index] < y[index - 1] and y[index] < y[index + 1]:
                if float(np.max(window)) - y[index] >= prominence:
                    lo_set.add(index)
    if y[0] > y[1] and y[0] >= y[2]:
        right = y[1 : min(n, half)]
        if right.size >= 2 and y[0] - float(np.min(right)) >= prominence:
            hi_set.add(0)
        if right.size >= 2 and float(np.max(right)) - y[0] >= prominence:
            lo_set.discard(0)
    return np.asarray(sorted(hi_set), dtype=np.int64), np.asarray(sorted(lo_set), dtype=np.int64)


def _score_polarity(
    y: np.ndarray,
    hi: np.ndarray,
    lo: np.ndarray,
    period: int,
    frame_time_ms: float,
) -> tuple[bool, float]:
    """Choose which extrema are ED using duration and curvature physiology.

    Returns ``(ed_at_max, margin)``.  A small margin means the UI should lower
    its confidence rather than pretend the ambiguity was resolved.
    """

    def score(ed: np.ndarray, es: np.ndarray) -> float:
        systoles: list[int] = []
        curv_ed: list[float] = []
        curv_es: list[float] = []
        for start in ed:
            cand = es[(es > start) & (es < start + 0.6 * period)]
            if cand.size == 0:
                continue
            end = int(cand[0])
            systoles.append(end - int(start))
            if 1 <= start < y.size - 1:
                curv_ed.append(abs(y[start - 1] - 2 * y[start] + y[start + 1]))
            if 1 <= end < y.size - 1:
                curv_es.append(abs(y[end - 1] - 2 * y[end] + y[end + 1]))
        if not systoles:
            return -1e6
        rr_ms = period * frame_time_ms
        expected_ms = _expected_systole_ms(rr_ms)
        expected_fraction = _clamp(expected_ms / max(1e-9, rr_ms), 0.2, 0.5)
        observed_fraction = float(np.median(systoles)) / max(1, period)
        duration_score = -abs(observed_fraction - expected_fraction) / 0.25
        # ES is normally a sharper turn than the flat diastasis ED plateau.
        sharpness = float(np.mean(curv_es)) - float(np.mean(curv_ed)) if curv_ed and curv_es else 0.0
        return float(duration_score + 0.5 * float(np.tanh(sharpness)))

    s_max = score(hi, lo)
    s_min = score(lo, hi)
    return (s_max >= s_min, abs(s_max - s_min))


# ── Internal: ECG ───────────────────────────────────────────────────────────


def _cycles_from_ecg(
    r_peaks_ms: np.ndarray,
    n_frames: int,
    frame_time_ms: float,
    area_like: np.ndarray | None,
    *,
    offset_ms: float,
    align: bool,
    warnings: set[str],
    trusted_alignment: bool = False,
) -> _EcgCycles:
    peaks = np.unique(np.asarray(r_peaks_ms, dtype=np.float64))
    peaks = peaks[np.isfinite(peaks)]
    if peaks.size < 2:
        return _EcgCycles([], 0.0, False)
    rr_ms = float(np.median(np.diff(peaks)))
    if rr_ms <= 0:
        return _EcgCycles([], 0.0, False)

    offset = float(offset_ms)
    alignment_quality = 0.25
    if abs(offset) < 1e-9 and align and area_like is not None:
        offset, alignment_quality = _align_ecg_offset(peaks, area_like, frame_time_ms, n_frames, rr_ms)
        if alignment_quality < 0.30:
            warnings.add("ecg_not_aligned")
    elif abs(offset) > 1e-9:
        alignment_quality = 0.85  # trusted DICOM trigger offset
    elif trusted_alignment:
        alignment_quality = 0.90  # burned-in trace already shares the video time base
    elif area_like is None:
        warnings.add("ecg_not_aligned")

    all_frames = np.unique(np.rint((peaks - offset) / frame_time_ms).astype(np.int64))
    frame_idx = all_frames[(all_frames >= 0) & (all_frames < n_frames)]
    if frame_idx.size == 0:
        return _EcgCycles([], alignment_quality, False)

    rr_values = np.diff(peaks)
    irregular = bool(rr_values.size >= 2 and float(np.std(rr_values)) / max(1e-9, float(np.mean(rr_values))) > 0.15)
    cycles: list[PhaseCycle] = []
    period_frames = max(4, int(round(rr_ms / frame_time_ms)))
    confidence = _clamp(alignment_quality)

    for ed in frame_idx:
        following = all_frames[all_frames > ed]
        preceding = all_frames[all_frames < ed]
        # Even an R-peak outside the clip fixes this beat's true RR. Never use
        # the truncated tail duration as RR (it shifted the final ES early).
        rr_frames = (
            int(following[0] - ed) if following.size else int(ed - preceding[-1]) if preceding.size else period_frames
        )
        rr = rr_frames * frame_time_ms
        if not (60000.0 / _MAX_HR_BPM <= rr <= 60000.0 / _MIN_HR_BPM):
            continue
        end = min(n_frames, int(ed) + rr_frames)
        partial = not following.size or int(ed) + rr_frames > n_frames
        if end - ed < 4:
            continue
        es = _es_in_window(area_like, int(ed), end, rr_frames, frame_time_ms)
        cycle_source = "ecg+area"
        if es is None:
            # A prior stays explicit and cannot invent an ES at the clip edge.
            es = int(ed) + max(3, int(round(_expected_systole_ms(rr) / frame_time_ms)))
            cycle_source = "ecg+prior"
            warnings.add("es_from_prior")
        if not (ed < es < end):
            continue
        cycles.append(
            PhaseCycle(
                ed_frame=int(ed),
                es_frame=int(es),
                end_frame=int(end),
                confidence=confidence,
                source=cycle_source,
                partial=partial,
            )
        )
    return _EcgCycles(cycles, alignment_quality, irregular)


def _align_ecg_offset(
    r_peaks_ms: np.ndarray,
    area_like: np.ndarray,
    frame_time_ms: float,
    n_frames: int,
    rr_ms: float,
) -> tuple[float, float]:
    """Find the ECG→cine shift that puts R-peaks on area maxima (= ED).

    ``offset`` is the time from the start of the ECG recording to cine frame 0.
    The search covers ±RR/2 in half-frame steps.  The scoring signal is a
    high-passed area curve (a ``1,5·RR`` moving baseline removed): a raw area
    curve has gain drift and broad Savitzky–Golay plateaus, which make neighbouring
    shifts tie and lets the alignment jump a whole frame.
    """
    y = np.asarray(area_like, dtype=np.float64)
    if y.size != n_frames or not np.isfinite(y).any():
        return 0.0, 0.0
    period_frames = max(4, rr_ms / frame_time_ms)
    window = int(round(period_frames * 1.5)) | 1
    window = min(window, n_frames if n_frames % 2 else n_frames - 1)
    window = max(5, window)
    baseline = uniform_filter1d(y, size=window, mode="nearest")
    high_pass = y - baseline
    spread = float(np.std(high_pass))
    if spread < 1e-9:
        return 0.0, 0.0
    high_pass = (high_pass - float(np.mean(high_pass))) / spread

    max_shift = min(rr_ms / 2.0, 900.0)
    step = max(frame_time_ms / 2.0, 1.0)
    shifts = np.arange(-max_shift, max_shift + step, step)
    best_score, best_shift = -1e9, 0.0
    for shift in shifts:
        idx = np.rint((r_peaks_ms - shift) / frame_time_ms).astype(np.int64)
        idx = idx[(idx >= 0) & (idx < n_frames)]
        if idx.size < 1:
            continue
        score = float(np.mean(high_pass[idx])) + 0.02 * idx.size
        if score > best_score:
            best_score, best_shift = score, float(shift)
    quality = _clamp((best_score - 0.02) / 1.3)
    return best_shift, quality


def _es_in_window(
    area_like: np.ndarray | None,
    ed: int,
    end: int,
    rr_frames: int,
    frame_time_ms: float,
) -> int | None:
    if area_like is None:
        return None
    low = ed + max(3, int(0.20 * rr_frames), int(180.0 / frame_time_ms))
    high = min(end - 1, ed + int(0.50 * rr_frames), ed + int(400.0 / frame_time_ms))
    if high <= low or low >= area_like.size:
        return None
    window = np.asarray(area_like[low : high + 1], dtype=np.float64)
    if not np.isfinite(window).any():
        return None
    candidate = int(low + np.nanargmin(window))
    # A falling curve at the search boundary is not a mechanical nadir.
    if candidate <= 0 or candidate + 1 >= min(end, area_like.size):
        return None
    if area_like[candidate] > min(area_like[candidate - 1], area_like[candidate + 1]):
        return None
    return candidate


# ── Internal: cycles, fusion, helpers ───────────────────────────────────────


def _best_signal_cycles(
    signals: list[_Signal],
    n_frames: int,
    frame_time_ms: float,
    warnings: set[str],
) -> tuple[_Signal, list[PhaseCycle], float]:
    ranked = sorted(
        signals,
        key=lambda s: s.weight * (0.55 * s.strength + 0.45 * s.q_signal),
        reverse=True,
    )
    for candidate in ranked:
        cycles = _cycles_from_extrema(candidate, n_frames, frame_time_ms, warnings)
        if cycles:
            return candidate, cycles, candidate.q_signal
    return ranked[0], [], ranked[0].q_signal


def _cycles_from_extrema(
    signal: _Signal,
    n_frames: int,
    frame_time_ms: float,
    warnings: set[str],
) -> list[PhaseCycle]:
    ed = np.asarray(sorted(set(int(i) for i in signal.ed_idx)), dtype=np.int64)
    es = np.asarray(sorted(set(int(i) for i in signal.es_idx)), dtype=np.int64)
    # Greedy minimum spacing: never let two noisy maxima create a tiny cycle.
    kept: list[int] = []
    for candidate in ed:
        if not kept or candidate - kept[-1] >= max(3, int(0.6 * signal.period)):
            kept.append(int(candidate))
    if len(kept) < 2 and len(ed) == 1:
        kept = [int(ed[0])]
    if not kept:
        return []

    cycles: list[PhaseCycle] = []
    for i, start in enumerate(kept):
        is_last = i + 1 >= len(kept)
        end = n_frames if is_last else kept[i + 1]
        if end - start < max(4, int(0.6 * signal.period)):
            continue
        candidates = es[(es > start) & (es < min(end, start + 0.6 * signal.period))]
        if candidates.size:
            stop = int(candidates[0])
        else:
            # A truncated contraction is not a measured ES. ECG-only priors
            # are explicit in their own path; image-only cycles need a nadir.
            continue
        if not (start < stop < end):
            continue
        cycles.append(
            PhaseCycle(
                ed_frame=start,
                es_frame=stop,
                end_frame=end,
                confidence=_clamp(signal.q_signal),
                source=signal.name,
                partial=is_last,
            )
        )
    return cycles


def _fuse_extrema(cycles: list[PhaseCycle], signals: list[_Signal], best: _Signal) -> float:
    """Median-snap ED/ES to other signals within ±2 frames; return agreement."""
    others = [s for s in signals if s is not best]
    if not others:
        # One clean periodic signal is not "disagreement": neutral, not zero.
        return 0.75
    hits, total = 0, 0
    updated: list[PhaseCycle] = []
    for cycle in cycles:
        ed, es = cycle.ed_frame, cycle.es_frame
        ed_vals, es_vals = [ed], [es]
        for other in others:
            for frame, target, bucket in ((ed, other.ed_idx, ed_vals), (es, other.es_idx, es_vals)):
                total += 1
                if target.size == 0:
                    continue
                nearest = int(target[np.argmin(np.abs(target - frame))])
                if abs(nearest - frame) <= 2:
                    bucket.append(nearest)
                    hits += 1
        new_ed = int(round(float(np.median(ed_vals))))
        new_es = int(round(float(np.median(es_vals))))
        if not (cycle.ed_frame - 2 <= new_ed < new_es <= cycle.end_frame - 1):
            new_ed, new_es = ed, es
        updated.append(replace(cycle, ed_frame=new_ed, es_frame=new_es))
    cycles[:] = updated
    return _clamp(hits / max(1, total))


def _labels_from_cycles(n_frames: int, cycles: tuple[PhaseCycle, ...] | list[PhaseCycle]) -> tuple[str, ...]:
    labels = [PHASE_UNKNOWN] * n_frames
    for cycle in cycles:
        for frame in range(max(0, cycle.ed_frame), min(n_frames, cycle.es_frame)):
            labels[frame] = PHASE_SYSTOLE
        for frame in range(max(0, cycle.es_frame), min(n_frames, cycle.end_frame)):
            labels[frame] = PHASE_DIASTOLE
    return tuple(labels)


def _unavailable(n_frames: int, frame_time_ms: float | None, warnings: tuple[str, ...]) -> PhaseTimeline:
    return PhaseTimeline(
        n_frames=max(0, n_frames),
        frame_time_ms=frame_time_ms,
        labels=(PHASE_UNKNOWN,) * max(0, n_frames),
        cycles=(),
        source=SOURCE_UNAVAILABLE,
        confidence=0.0,
        warnings=tuple(sorted(set(warnings) | {"phase_unavailable"})),
    )


def _prepare_frames(frames: Any, n_frames: int) -> tuple[np.ndarray | None, np.ndarray | None]:
    if frames is None:
        return None, None
    arr = np.asarray(frames)
    if arr.ndim == 3:
        gray, color = arr.astype(np.float32), None
    elif arr.ndim == 4 and arr.shape[-1] >= 3:
        color = arr[..., :3].astype(np.float32)
        gray = color.mean(axis=-1)
    else:
        return None, None
    if gray.shape[0] != n_frames or gray.shape[0] < 4:
        return None, None
    step = max(1, gray.shape[1] // 64, gray.shape[2] // 64)
    gray = np.ascontiguousarray(gray[:, ::step, ::step])
    color = None if color is None else np.ascontiguousarray(color[:, ::step, ::step, :])
    return gray, color


def _normalise_signal(values: np.ndarray | None) -> np.ndarray | None:
    if values is None:
        return None
    y = np.asarray(values, dtype=np.float64).ravel()
    if y.size < 6:
        return None
    idx = np.arange(y.size)
    good = np.isfinite(y)
    if good.sum() < 6:
        return None
    y = np.interp(idx, idx[good], y[good])
    y = detrend(y, type="linear")
    window = min(9, y.size if y.size % 2 else y.size - 1)
    if window >= 5:
        y = savgol_filter(y, window_length=window, polyorder=2)
    std = float(np.std(y))
    if std < 1e-9:
        return None
    return np.asarray((y - float(np.mean(y))) / std, dtype=np.float64)


def _estimate_period(y: np.ndarray, fps: float) -> tuple[int, float] | None:
    n = y.size
    if n < 8 or fps <= 0:
        return None
    centred = y - float(np.mean(y))
    power = np.fft.rfft(centred, n=2 * n)
    acf = np.fft.irfft(power * np.conj(power))[:n]
    if acf[0] <= 1e-12:
        return None
    acf = acf / acf[0]
    min_lag = max(2, int(60.0 / _MAX_HR_BPM * fps))
    max_lag = min(n - 1, int(60.0 / _MIN_HR_BPM * fps))
    if min_lag >= max_lag or n < 1.4 * min_lag:
        return None
    peaks, _ = find_peaks(acf, prominence=0.05)
    candidates = peaks[(peaks >= min_lag) & (peaks <= max_lag) & (peaks <= n / 1.4)]
    if candidates.size:
        lag = int(candidates[np.argmax(acf[candidates])])
        strength = _clamp(float(acf[lag]))
    else:
        lag, strength = 0, 0.0
    if strength < 0.30:
        # A short clip (1–1.5 beats) has too little overlap for autocorrelation.
        # The distance between a maximum, the next minimum and the next maximum
        # still gives the period; mark it as moderate-confidence evidence.
        fallback = _period_from_extrema(y, fps)
        if fallback is None:
            return None
        return fallback, 0.5
    return max(3, lag), strength


def _period_from_extrema(y: np.ndarray, fps: float) -> int | None:
    """Last-resort period estimate for clips that contain only one full beat."""
    spread = float(np.std(y))
    if spread < 1e-9:
        return None
    distance = max(2, int(0.2 * fps))
    hi, _ = find_peaks(y, prominence=0.6 * spread, distance=distance)
    lo, _ = find_peaks(-y, prominence=0.6 * spread, distance=distance)
    # Boundary maxima are invisible to find_peaks; recover them before judging
    # whether the clip contains a full beat.
    hi, lo = _with_edge_extrema(y, hi, lo, 0.6 * spread, int(0.8 * fps))
    if hi.size + lo.size < 3 or abs(int(hi.size) - int(lo.size)) > 1:
        return None
    extrema = np.sort(np.concatenate([hi, lo]))
    gaps = np.diff(extrema)
    if gaps.size < 2:
        return None
    period = int(round(2.0 * float(np.median(gaps))))
    # Require a plausible, well-observed beat: this fallback is deliberately
    # conservative, otherwise noise extrema would masquerade as a rhythm.
    if period < max(15.0, 0.5 * fps) or period > 60.0 / _MIN_HR_BPM * fps:
        return None
    if y.size < 1.2 * period:
        return None
    return max(3, period)


def _as_vector(values: Any, n_frames: int) -> np.ndarray | None:
    if values is None:
        return None
    raw = np.asarray(values)
    # Sparse (frame, value) samples arrive as a 2-column table.  Check this
    # before flattening: a 10x2 table has 20 entries and would otherwise be
    # mistaken for a 20-frame signal.
    if raw.ndim == 2 and raw.shape[1] == 2:
        pairs = raw.astype(np.float64)
        out = np.full(n_frames, np.nan, dtype=np.float64)
        for frame, value in pairs:
            if 0 <= int(frame) < n_frames:
                out[int(frame)] = float(value)
        return out
    arr = raw.astype(np.float64).ravel()
    if arr.size == 0:
        return None
    if arr.size == n_frames:
        return arr
    return np.interp(np.linspace(0, 1, n_frames), np.linspace(0, 1, arr.size), arr)


def _as_peak_times(values: Any) -> np.ndarray:
    if values is None:
        return np.zeros(0, dtype=np.float64)
    arr = np.asarray(values, dtype=np.float64).ravel()
    return np.asarray(arr[np.isfinite(arr)], dtype=np.float64)


def _expected_systole_ms(rr_ms: float) -> float:
    """Weissler-style prior: systole shortens only mildly as HR rises."""
    hr = 60000.0 / max(1.0, rr_ms)
    return float(np.clip(400.0 - 1.2 * (hr - 60.0), 180.0, 400.0))


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return float(np.clip(value, low, high))


def _clip_int(value: int, low: int, high: int) -> int:
    return int(np.clip(int(value), int(low), max(int(low), int(high))))
