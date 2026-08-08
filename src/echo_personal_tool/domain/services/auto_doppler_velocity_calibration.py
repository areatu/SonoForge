from dataclasses import dataclass
import numpy as np

from echo_personal_tool.domain.models.doppler_roi import (
    DopplerKind,
    DopplerSpectrogramRoi,
)
from echo_personal_tool.domain.services.velocity_scale_detector import (
    detect_velocity_scale_ticks,
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
    """
    above = sorted(t for t in tick_ys if t < baseline_y - 1.0)
    below = sorted(t for t in tick_ys if t > baseline_y + 1.0)
    n_above = len(above)
    if n_above < 2 or len(below) < 2:
        return None

    pixel_interval = (above[-1] - above[0]) / max(1, n_above - 1)
    if pixel_interval <= 0:
        return None

    candidate_spans = _SPECTRAL_SPANS if kind == DopplerKind.SPECTRAL else _TISSUE_SPANS
    best: float | None = None
    best_score = -1.0
    for S in candidate_spans:
        per_interval = (S / 2.0) / n_above
        if not _round_velocity(per_interval):
            continue
        expected_px = (S / 2.0) / per_interval * (roi.height / S)
        implied_ppi = per_interval / pixel_interval
        expected_ppi = S / roi.height
        consistency = 1.0 - min(1.0, abs(implied_ppi - expected_ppi) / expected_ppi)
        score = consistency
        if score > best_score:
            best_score = score
            best = S
    if best_score < 0.6:
        return None
    return best


@dataclass(frozen=True)
class VelocityAutocalibrationResult:
    velocity_span_cm_s: float
    velocity_per_pixel_cm_s: float
    confidence: float
    method: str  # "ocr" | "inferred"


def try_auto_doppler_velocity_calibration(
    frame: np.ndarray,
    *,
    roi: DopplerSpectrogramRoi,
    baseline_y: float,
    kind: DopplerKind = DopplerKind.SPECTRAL,
) -> VelocityAutocalibrationResult | None:
    """Auto-calibrate Doppler velocity scale from detected ticks + baseline.

    Detects velocity-scale tick positions, then resolves them via either
    OCR label reading (if surya-ocr is available) or standard-value inference.

    Returns None if auto-detection is not possible (e.g., not enough ticks).
    """
    from echo_personal_tool.domain.services.velocity_scale_ocr import (
        read_velocity_labels,
    )

    tick_ys = detect_velocity_scale_ticks(frame, roi=roi)
    if len(tick_ys) < 4:
        return None

    # OCR path
    labels = read_velocity_labels(frame, roi=roi, tick_ys=tick_ys)
    if labels and len(labels) >= 2:
        paired = sorted(labels.items(), key=lambda kv: kv[0])
        (y0, v0), (y1, v1) = paired[0], paired[-1]
        dy = abs(y1 - y0)
        if dy > 1.0 and v1 != v0:
            vpp = abs(v1 - v0) / dy
            span = vpp * roi.height
            return VelocityAutocalibrationResult(
                velocity_span_cm_s=span,
                velocity_per_pixel_cm_s=vpp,
                confidence=0.95,
                method="ocr",
            )

    # Inference path
    span = infer_velocity_span(tick_ys, baseline_y, roi=roi, kind=kind)
    if span is None:
        return None
    vpp = span / roi.height
    return VelocityAutocalibrationResult(
        velocity_span_cm_s=span,
        velocity_per_pixel_cm_s=vpp,
        confidence=0.7,
        method="inferred",
    )