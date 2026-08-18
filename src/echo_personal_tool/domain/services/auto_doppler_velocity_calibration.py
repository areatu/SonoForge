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
    """True if per-interval velocity is a 'nice' clinical number."""
    if per_interval <= 0:
        return False
    nice = {1.0, 2.0, 2.5, 5.0, 10.0, 12.5, 15.0, 20.0, 25.0, 30.0, 50.0, 75.0, 100.0}
    for n in nice:
        if abs(per_interval - n) < 0.5:
            return True
    return False


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
    """
    if len(tick_ys) < 3:
        return None

    sorted_ticks = sorted(tick_ys)
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
