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
