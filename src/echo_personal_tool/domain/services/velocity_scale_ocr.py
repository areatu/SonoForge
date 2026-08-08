"""Optional OCR-based reading of velocity scale labels (surya-ocr)."""

from __future__ import annotations

import re

import numpy as np
from PIL import Image

from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi

_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _parse_velocity_text(text: str) -> float | None:
    match = _NUM_RE.search(text or "")
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _surya_recognizer():
    try:
        from surya.recognition import RecognitionPredictor  # type: ignore
        from surya.detection import DetectionPredictor  # type: ignore
        from surya.foundation import FoundationPredictor  # type: ignore
    except Exception:  # pragma: no cover - env dependent
        return None
    try:
        fp = FoundationPredictor()
        det = DetectionPredictor()
        rec = RecognitionPredictor(fp)
        return lambda imgs: rec(imgs, det_predictor=det)
    except Exception:  # pragma: no cover - model load failure
        return None


def read_velocity_labels(
    frame: np.ndarray,
    *,
    roi: DopplerSpectrogramRoi,
    tick_ys: list[float],
    strip_width_px: int = 40,
) -> dict[float, float] | None:
    """Read velocity labels from tick positions in the scale strip.

    Crops a small horizontal band at each tick y, runs surya-ocr recognition,
    parses the leading integer, and maps it to the tick y.
    Returns None if surya-ocr is not importable or fails.
    """
    recognizer = _surya_recognizer()
    if recognizer is None or not tick_ys:
        return None

    h, w = frame.shape[:2]
    x0 = min(int(roi.x1), w - 1)
    x1 = min(x0 + strip_width_px, w)
    if x1 <= x0:
        return None

    results: dict[float, float] = {}
    for ty in tick_ys:
        y0 = max(0, int(ty) - 8)
        y1 = min(h, int(ty) + 8)
        crop = frame[y0:y1, x0:x1]
        if crop.size == 0:
            continue
        img = Image.fromarray(crop).convert("RGB")
        try:
            ocr = recognizer([img])
        except Exception:  # pragma: no cover - runtime OCR error
            continue
        if not ocr or not ocr[0].text_lines:
            continue
        text = " ".join(line.text for line in ocr[0].text_lines)
        value = _parse_velocity_text(text)
        if value is not None:
            results[float(ty)] = value

    return results if results else None