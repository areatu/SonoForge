"""Clinical strain metrics over a full cardiac cycle (plan rev.3 §3.5, phase 2).

Why this module exists
----------------------
The module used to analyse only the ED…ES window and to report a single
number — the value at the end of that window. That is *end-systolic strain*
(ESS), not the global longitudinal strain vendors report, and it silently hides
post-systolic shortening; the drift of the baseline ("does the curve return to
zero at the next end-diastole?") was never measured, only "compensated".

Here every metric is derived from the strain curve of the *whole* cycle:

* ``avc_frame`` — aortic valve closure (start of the global strain peak search
  window for ESS) with an explicit source: ECG, the nadir of the Simpson area
  curve, the time of the global strain peak (Philips AutoSTRAIN behaviour) or a
  manual anchor;
* ``ess`` — strain at AVC (end-systolic strain);
* ``peak`` — most negative value of the curve over the whole cycle (post-
  systolic shortening included);
* ``gls``  — peak of the *global* curve — an AVC-independent parameter, which
  is what the EACVI/ASE consensus and the vendors call GLS;
* ``time_to_peak_ms`` — from ED to the peak (TTP), the basis of the
  time-to-peak bull's-eye and of dyssynchrony indices;
* ``peak`` is the **peak systolic** strain (the EACVI/ASE definition of the
  value a segment or the global curve reports): the most negative sample between
  ED and AVC plus a short tolerance for late-systolic peaks. An extremum that
  lies *after* systole is reported separately (``post_systolic_peak``,
  ``post_systolic_index``, ``is_post_systolic``) instead of being promoted to
  the result — a diastolic tracking artefact must not become the GLS;
* ``post_systolic_index`` — post-systolic shortening as a percentage of the
  systolic peak (0 when the curve does not shorten further after AVC);
* ``drift`` — the residual strain at the next end-diastole / end of the window,
  which must be reported as a number instead of being forced to zero.

All functions are NaN-safe and never invent a value: when the curve has no
finite sample inside a window the metric is ``nan`` and the caller can show
"not measured".
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# Sources of the AVC anchor, most to least trustworthy.
AVC_SOURCE_ECG = "ecg"
AVC_SOURCE_AREA = "simpson_area"
AVC_SOURCE_STRAIN_PEAK = "strain_peak"
AVC_SOURCE_MANUAL = "manual"
AVC_SOURCE_ES = "es"

AVC_SOURCE_CONFIDENCE: dict[str, float] = {
    AVC_SOURCE_MANUAL: 1.0,
    AVC_SOURCE_ECG: 0.9,
    AVC_SOURCE_AREA: 0.75,
    AVC_SOURCE_STRAIN_PEAK: 0.6,
    AVC_SOURCE_ES: 0.4,
}


def estimate_cycle_length_frames(
    ed_frame: int,
    es_frame: int,
    n_frames: int,
    *,
    heart_rate_bpm: float = 0.0,
    frame_time_ms: float = 33.3,
    rr_frames: float | None = None,
) -> int:
    """Length of one cardiac cycle in frames (analysis window of ED → next ED).

    Preference: the measured RR interval (ECG), then the heart rate, then the
    systolic interval scaled by the usual ~1/3 systole-to-cycle ratio. The
    result is always clamped to what the clip can actually show.
    """
    if rr_frames is not None and np.isfinite(rr_frames) and rr_frames > 1:
        cycle = int(round(float(rr_frames)))
    elif heart_rate_bpm and heart_rate_bpm > 20.0 and frame_time_ms > 0:
        cycle = int(round(60000.0 / heart_rate_bpm / frame_time_ms))
    else:
        systole = max(int(es_frame) - int(ed_frame), 1)
        cycle = int(round(systole / 0.35))
    # A cycle shorter than systole is not physiological; longer than the clip is
    # simply not available.
    cycle = max(cycle, max(int(es_frame) - int(ed_frame), 1) + 1)
    return int(min(cycle, max(n_frames - int(ed_frame), 1)))


def detect_avc_frame(
    *,
    ed_frame: int,
    es_frame: int,
    strain_curve: np.ndarray | None = None,
    ecg_avc_frame: int | None = None,
    area_curve: tuple[tuple[int, float], ...] = (),
    manual_avc: int | None = None,
    search_end: int | None = None,
) -> tuple[int, str, float]:
    """Aortic valve closure frame and the source it came from.

    Priority (each step is only used when the previous one is unavailable):
    manual anchor → ECG → nadir of the Simpson area curve → time of the global
    strain peak → the image-based ES anchor.
    """
    if manual_avc is not None:
        return int(manual_avc), AVC_SOURCE_MANUAL, AVC_SOURCE_CONFIDENCE[AVC_SOURCE_MANUAL]
    if ecg_avc_frame is not None:
        return int(ecg_avc_frame), AVC_SOURCE_ECG, AVC_SOURCE_CONFIDENCE[AVC_SOURCE_ECG]

    if area_curve:
        by_frame = {int(f): float(a) for f, a in area_curve if np.isfinite(a)}
        window = {f: a for f, a in by_frame.items() if ed_frame <= f <= (search_end if search_end is not None else f)}
        if len(window) >= 2:
            frame, _area = min(window.items(), key=lambda item: item[1])
            return int(frame), AVC_SOURCE_AREA, AVC_SOURCE_CONFIDENCE[AVC_SOURCE_AREA]

    if strain_curve is not None and len(strain_curve) > 0:
        # Philips AutoSTRAIN: when no ECG/area information exists, ES is taken
        # as the time of the global peak strain.
        peak = _peak_index(strain_curve, ed_frame, search_end)
        if peak is not None:
            return int(peak), AVC_SOURCE_STRAIN_PEAK, AVC_SOURCE_CONFIDENCE[AVC_SOURCE_STRAIN_PEAK]

    return int(es_frame), AVC_SOURCE_ES, AVC_SOURCE_CONFIDENCE[AVC_SOURCE_ES]


def _peak_index(curve: np.ndarray, start: int, end: int | None) -> int | None:
    """Index of the most negative finite value of ``curve`` in [start, end]."""
    arr = np.asarray(curve, dtype=np.float64)
    if arr.size == 0:
        return None
    last = arr.size - 1
    lo = int(min(max(start, 0), last))
    hi = last if end is None else int(min(max(end, 0), last))
    if hi < lo:
        lo, hi = hi, lo
    window = arr[lo : hi + 1]
    finite = np.isfinite(window)
    if not np.any(finite):
        return None
    idx = int(np.argmin(np.where(finite, window, np.inf)))
    return lo + idx


@dataclass(frozen=True)
class StrainMetrics:
    """Metrics of one strain curve over the analysed cycle."""

    peak: float = float("nan")  # peak systolic strain (ED .. AVC + tolerance)
    peak_frame: int | None = None
    ess: float = float("nan")  # value at AVC (end-systolic strain)
    time_to_peak_ms: float = float("nan")
    post_systolic_peak: float = float("nan")  # extremum after systole
    post_systolic_peak_frame: int | None = None
    post_systolic_index: float = float("nan")  # extra shortening after AVC, % of the peak
    drift: float = float("nan")  # residual strain at the end of the window
    is_post_systolic: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)


def compute_strain_metrics(
    curve: np.ndarray | None,
    *,
    ed_index: int,
    avc_index: int,
    window_end: int | None = None,
    frame_time_ms: float = 33.3,
    drift_tolerance: float = 2.0,
    post_avc_tolerance_ms: float = 50.0,
) -> StrainMetrics:
    """Metrics of one strain curve between ED and the end of the cycle.

    Args:
        curve: strain curve in percent (NaN where undefined).
        ed_index: end-diastole frame (strain reference, curve ≈ 0).
        avc_index: aortic valve closure frame — the end of systole.
        window_end: last analysed frame (next ED); defaults to the curve end.
        frame_time_ms: frame period, used for TTP.
        drift_tolerance: |residual| below this value (percentage points) is
            reported as "no drift" in the notes.
        post_avc_tolerance_ms: how far after AVC a peak is still accepted as
            systolic (late-systolic shortening); 0 searches strictly to AVC.

    Returns:
        :class:`StrainMetrics`; every field is ``nan`` when the curve does not
        contain a finite sample in the relevant window.
    """
    arr = np.asarray(curve, dtype=np.float64) if curve is not None else np.array([], dtype=np.float64)
    if arr.size == 0:
        return StrainMetrics(notes=("no strain curve",))
    notes: list[str] = []
    last = arr.size - 1
    ed = int(min(max(ed_index, 0), last))
    avc = int(min(max(avc_index, 0), last))
    end = last if window_end is None else int(min(max(window_end, ed), last))

    tolerance = int(round(max(float(post_avc_tolerance_ms), 0.0) / frame_time_ms)) if frame_time_ms > 0 else 1
    systolic_end = min(end, avc + tolerance) if avc >= ed else end

    peak_frame = _peak_index(arr, ed, systolic_end)
    if peak_frame is None:
        # Nothing finite inside systole: fall back to the whole window, but say
        # so — the value is then a diastolic extremum, not a peak systolic one.
        peak_frame = _peak_index(arr, ed, end)
        if peak_frame is not None:
            notes.append("no finite strain inside systole - peak read over the whole window")
    peak = float(arr[peak_frame]) if peak_frame is not None else float("nan")
    if peak_frame is None:
        notes.append("no finite strain inside the analysis window")

    ess_frame = _peak_index(arr, ed, avc) if avc >= ed else None
    ess = float(arr[ess_frame]) if ess_frame is not None else float("nan")

    ttp = float("nan")
    if peak_frame is not None and frame_time_ms > 0:
        ttp = float(max(peak_frame - ed, 0) * frame_time_ms)

    late_frame = _peak_index(arr, systolic_end + 1, end) if systolic_end < end else None
    post_systolic_peak = float(arr[late_frame]) if late_frame is not None else float("nan")

    psi = float("nan")
    if np.isfinite(peak) and np.isfinite(post_systolic_peak) and abs(peak) > 1e-6:
        # Negative strain shortens: a *deeper* extremum after systole means extra
        # shortening. Clamped at zero, so a diastolic rebound is not reported as
        # post-systolic shortening.
        psi = float(max((peak - post_systolic_peak) / abs(peak) * 100.0, 0.0))
    elif np.isfinite(peak):
        psi = 0.0

    is_post_systolic = bool(np.isfinite(psi) and psi > 5.0)
    if is_post_systolic:
        notes.append(
            f"post-systolic shortening: {post_systolic_peak:+.1f}% at frame "
            f"{int(late_frame)} ({psi:.0f}% deeper than the systolic peak)"
        )

    drift = float(arr[end]) if np.isfinite(arr[end]) else float("nan")
    if np.isfinite(drift) and abs(drift) > drift_tolerance:
        notes.append(f"baseline drift {drift:+.1f}% at the end of the window")
    if avc == ed:
        notes.append("AVC equals ED — end-systolic strain is not defined")

    return StrainMetrics(
        peak=peak,
        peak_frame=peak_frame,
        ess=ess,
        time_to_peak_ms=ttp,
        post_systolic_peak=post_systolic_peak,
        post_systolic_peak_frame=late_frame,
        post_systolic_index=psi,
        drift=drift,
        is_post_systolic=is_post_systolic,
        notes=tuple(notes),
    )


def metrics_by_segment(
    segment_curves: dict[int, np.ndarray],
    *,
    ed_index: int,
    avc_index: int,
    window_end: int | None = None,
    frame_time_ms: float = 33.3,
) -> dict[int, StrainMetrics]:
    """Same metrics per AHA segment (all curves share the time base)."""
    return {
        int(segment): compute_strain_metrics(
            curve,
            ed_index=ed_index,
            avc_index=avc_index,
            window_end=window_end,
            frame_time_ms=frame_time_ms,
        )
        for segment, curve in segment_curves.items()
    }


def time_to_peak_map(
    segment_curves: dict[int, np.ndarray],
    *,
    ed_index: int,
    avc_index: int,
    window_end: int | None = None,
    frame_time_ms: float = 33.3,
) -> dict[int, float]:
    """``{segment: time from ED to its peak}`` in ms — the TTP bull's-eye input."""
    metrics = metrics_by_segment(
        segment_curves,
        ed_index=ed_index,
        avc_index=avc_index,
        window_end=window_end,
        frame_time_ms=frame_time_ms,
    )
    return {seg: m.time_to_peak_ms for seg, m in metrics.items() if np.isfinite(m.time_to_peak_ms)}
