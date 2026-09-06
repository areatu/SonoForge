from dataclasses import dataclass

import numpy as np

from echo_personal_tool.domain.models.doppler_roi import (
    DopplerKind,
    DopplerSpectrogramRoi,
)
from echo_personal_tool.domain.services.doppler_grid_detector import (
    detect_doppler_grid_lines,
)
from echo_personal_tool.domain.services.velocity_scale_detector import (
    detect_velocity_scale_ticks,
    find_best_scale_column,
)

_SPECTRAL_SPANS = [50.0, 100.0, 150.0, 200.0, 250.0, 300.0, 350.0, 400.0]
_TISSUE_SPANS = [5.0, 10.0, 15.0, 20.0, 25.0, 30.0]
_SAMSUNG_SPANS = [50.0, 100.0, 150.0, 200.0, 250.0, 300.0, 350.0, 400.0, 500.0, 600.0, 700.0, 800.0]
_SAMSUNG_TISSUE_SPANS = [20.0, 30.0, 40.0, 50.0, 60.0, 80.0, 100.0]


def _round_velocity(per_interval: float) -> bool:
    """True if per-interval velocity is a 'nice' clinical number.

    Relative tolerance (3.5%, floored at 0.2 and capped at 0.5 cm/s): scale
    ticks are laid out at exact nice values, so measured intervals land
    within detector noise of them. A flat ±0.5 tolerance used to admit
    false matches (e.g. 2.78 cm/s taken for 2.5), producing a wrong yet
    "unambiguous" span 3.5x off the real scale.
    """
    if per_interval <= 0:
        return False
    nice = {1.0, 2.0, 2.5, 5.0, 10.0, 12.5, 15.0, 20.0, 25.0, 30.0, 50.0, 75.0, 100.0}
    for n in nice:
        if abs(per_interval - n) <= min(0.5, max(0.2, 0.035 * n)):
            return True
    return False


def _drop_outlier_ticks(sorted_ticks: list[float]) -> list[float]:
    """Drop ticks whose every adjacent gap deviates >30% from the median gap.

    Scale ticks form an arithmetic progression, but detector output on
    untagged frames mixes in label artifacts and axis marks. A tick is
    removed only when ALL gaps touching it are irregular, so uniform sets
    pass through unchanged and interior ticks of a clean run survive a
    single noisy neighbour.
    """
    if len(sorted_ticks) < 3:
        return sorted_ticks
    gaps = [sorted_ticks[i + 1] - sorted_ticks[i] for i in range(len(sorted_ticks) - 1)]
    median_gap = float(np.median(gaps))
    if median_gap <= 0:
        return sorted_ticks
    keep = [True] * len(sorted_ticks)
    for i in range(len(sorted_ticks)):
        adjacent = []
        if i > 0:
            adjacent.append(gaps[i - 1])
        if i < len(gaps):
            adjacent.append(gaps[i])
        if adjacent and all(abs(g - median_gap) > 0.3 * median_gap for g in adjacent):
            keep[i] = False
    filtered = [t for t, k in zip(sorted_ticks, keep) if k]
    return filtered if len(filtered) >= 3 else sorted_ticks


def infer_velocity_span(
    tick_ys: list[float],
    baseline_y: float,
    *,
    roi: DopplerSpectrogramRoi,
    kind: DopplerKind = DopplerKind.SPECTRAL,
) -> float | None:
    """Infer velocity span from tick geometry.

    Returns the best-matching standard velocity span (cm/s) given tick geometry,
    or None if no good match.

    Works with ticks on either or both sides of the baseline. The baseline
    represents 0 cm/s; ticks above are positive, below are negative. For a
    standard span S with N intervals between consecutive ticks, each interval
    represents a velocity of S / N. We check that this matches a "nice" clinical
    number and that the implied velocity-per-pixel is consistent with the ROI
    height.

    The consistency score is invariant to S (it only couples tick spacing to
    ROI height), so when the nice-value arithmetic leaves several standard
    spans plausible the geometry cannot disambiguate them — inference must
    refuse rather than guess. Irregular ticks (label artifacts, axis marks)
    are dropped before inference so they cannot skew N.
    """
    if len(tick_ys) < 3:
        return None

    sorted_ticks = _drop_outlier_ticks(sorted(tick_ys))
    spacings = np.array([sorted_ticks[i + 1] - sorted_ticks[i] for i in range(len(sorted_ticks) - 1)])
    pixel_spacing = float(np.median(spacings))
    if pixel_spacing <= 0:
        return None

    above = sorted(t for t in sorted_ticks if t < baseline_y - 1.0)
    below = sorted(t for t in sorted_ticks if t > baseline_y + 1.0)
    n_above = len(above)
    n_below = len(below)

    # Need at least 2 ticks on one side of the baseline (1 interval)
    if n_above < 2 and n_below < 2:
        return None

    # Total velocity = span. Half-span = S/2 corresponds to the furthest
    # tick from the baseline on either side.
    n_furthest = max(n_above, n_below)
    if n_furthest < 2:
        n_furthest = 2

    candidate_spans = _SPECTRAL_SPANS if kind == DopplerKind.SPECTRAL else _TISSUE_SPANS
    consistent: list[float] = []

    for S in candidate_spans:
        per_interval = (S / 2.0) / n_furthest
        if not _round_velocity(per_interval):
            continue
        expected_vpp = S / roi.height
        implied_vpp = per_interval / pixel_spacing
        consistency = 1.0 - min(1.0, abs(implied_vpp - expected_vpp) / expected_vpp)
        if consistency >= 0.6:
            consistent.append(S)

    # Tick geometry alone cannot distinguish equally consistent standard
    # spans (the consistency score is invariant to S), so only return a
    # value when exactly one standard span is plausible.
    if len(consistent) != 1:
        return None
    return consistent[0]


def infer_samsung_velocity_span(
    tick_ys: list[float],
    *,
    roi: DopplerSpectrogramRoi,
    kind: DopplerKind = DopplerKind.SPECTRAL,
) -> float | None:
    """Infer Samsung RS85 full span from a robust tick lattice.

    Samsung screenshots commonly contain extra short marks and label strokes,
    so counting all detected ticks is unreliable. The ruler interval is still
    stable. RS85 uses clinically conventional intervals: approximately
    30 cm/s for compact scales and 100 cm/s for wide scales. The resulting
    full span is rounded to the nearest standard panel span.
    """
    if len(tick_ys) < 4 or roi.height <= 0.0:
        return None

    ticks = sorted(float(value) for value in tick_ys)
    gaps = np.diff(ticks)
    gaps = gaps[gaps >= max(8.0, roi.height * 0.04)]
    if len(gaps) < 2:
        return None
    spacing = float(np.median(gaps))
    if spacing <= 0.0:
        return None

    if kind is DopplerKind.TISSUE:
        # Tissue Doppler uses a compact scale, commonly labelled 4, 8, 12,
        # 16... cm/s. Keep this branch separate from PW/CW's 30/100 cm/s
        # intervals; otherwise tissue velocities are overestimated by a large
        # factor.
        # The common Samsung TDI labels are 4, 8, 12, 16... cm/s.
        interval_candidates = (4.0,)
        candidate_spans = _SAMSUNG_TISSUE_SPANS
    else:
        # Empirical RS85 ruler layout: about 30 cm/s at ~35 px and 100 cm/s at
        # ~90 px. Keep the thresholds conservative to avoid accepting text noise.
        if spacing >= 70.0:
            interval_candidates = (100.0,)
        elif spacing >= 28.0:
            interval_candidates = (30.0,)
        elif spacing >= 15.0:
            interval_candidates = (20.0,)
        else:
            interval_candidates = (10.0,)
        candidate_spans = _SAMSUNG_SPANS

    raw_candidates = [interval * roi.height / spacing for interval in interval_candidates]
    raw_span = min(raw_candidates, key=lambda value: min(abs(value - candidate) for candidate in candidate_spans))
    span = min(candidate_spans, key=lambda candidate: abs(candidate - raw_span))
    if abs(span - raw_span) / max(raw_span, 1.0) > 0.18:
        return None
    return float(span)


@dataclass(frozen=True)
class VelocityAutocalibrationResult:
    velocity_span_cm_s: float
    velocity_per_pixel_cm_s: float
    confidence: float
    method: str  # "inferred"


def try_auto_doppler_velocity_calibration(
    frame: np.ndarray,
    *,
    roi: DopplerSpectrogramRoi,
    baseline_y: float,
    kind: DopplerKind = DopplerKind.SPECTRAL,
) -> VelocityAutocalibrationResult | None:
    """Auto-calibrate Doppler velocity scale from detected ticks + baseline.

    Detects velocity-scale tick positions, then resolves them via
    standard-value inference (fast, no external dependencies).

    Returns None if auto-detection is not possible (e.g., not enough ticks
    or non-standard scale layout).
    """
    tick_ys = find_best_scale_column(frame, roi=roi, search_width_px=120, baseline_y=baseline_y)
    if len(tick_ys) < 4:
        tick_ys = detect_velocity_scale_ticks(frame, roi=roi, baseline_y=baseline_y)
    if len(tick_ys) < 4:
        tick_ys = detect_doppler_grid_lines(
            frame,
            x0=int(roi.x0),
            y0=int(roi.y0),
            width=int(roi.width),
            height=int(roi.height),
        )

    if len(tick_ys) < 4:
        return None

    # Samsung's ruler conventions require vendor identification. This generic
    # service has no dataset/vendor context, so do not guess a Samsung scale
    # from an otherwise ambiguous layout.
    span = infer_velocity_span(tick_ys, baseline_y, roi=roi, kind=kind)
    if span is not None:
        vpp = span / roi.height
        return VelocityAutocalibrationResult(
            velocity_span_cm_s=span,
            velocity_per_pixel_cm_s=vpp,
            confidence=0.7,
            method="inferred",
        )

    return None
