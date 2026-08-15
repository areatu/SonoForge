# Doppler Velocity Scale Autocalibration (mp4) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the manual 3-step Doppler velocity calibration (baseline click → 2 grid-line clicks → velocity-span dialog) for mp4 frames with a single baseline click that auto-detects velocity scale ticks and resolves their digital values, producing a fully calibrated axis automatically.

**Architecture:** Build a `VelocityScaleDetector` (analog of `depth_scale_detector.py`) that detects tick/label positions on the right-side velocity scale strip of an mp4 frame, then a `try_auto_doppler_velocity_calibration()` orchestrator that maps detected ticks + baseline to a `velocity_per_pixel` value using either (a) standard-value inference (no new deps) or (b) OCR label reading (surya-ocr, already present in env). Wire the orchestrator into `_handle_doppler_calibration_click` so that after the baseline click the calibration is applied immediately; the existing 2-click + dialog path remains as a fallback when auto-detection is low-confidence.

**Tech Stack:** Python 3.11, NumPy, OpenCV (cv2), PySide6, existing `DopplerCalibrationState`/`DopplerAxisMapping` models. Optional OCR via `surya-ocr` (already installed in env, not a hard dependency).

## Global Constraints

- All image-processing functions accept `np.ndarray` frames (BGR uint8 from `VideoReader` / `cv2.VideoCapture`) — no DICOM assumptions.
- Doppler calibration state model is `DopplerCalibrationState` (frozen dataclass) — must remain immutable; build new instances, never mutate.
- The baseline represents 0 cm/s; velocity is symmetric ±`velocity_span_cm_s/2` around the baseline y.
- `DopplerKind.SPECTRAL` default span = 200.0 cm/s; `DopplerKind.TISSUE` default = 40.0 cm/s (from `doppler_roi.py:14`).
- No new hard dependencies in `pyproject.toml` — OCR (surya-ocr) is optional/soft-detected at runtime.
- All user-facing strings go through `tr()` i18n keys in `en.json`; add new keys, never inline Russian/English text.
- Tests use `pytest`; domain tests need no Qt, presentation tests need `pytestmark = pytest.mark.gui` + `qtbot`.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `src/echo_personal_tool/domain/services/velocity_scale_detector.py` | **Create.** Detect velocity-scale tick/label y-positions on the right-side strip of a spectrogram ROI. |
| `src/echo_personal_tool/domain/services/auto_doppler_velocity_calibration.py` | **Create.** Orchestrate tick detection + value resolution → `VelocityAutocalibrationResult`. |
| `src/echo_personal_tool/domain/services/velocity_scale_ocr.py` | **Create.** Optional OCR label reader (surya-ocr) returning `{y_px: velocity_cm_s}`. |
| `src/echo_personal_tool/presentation/viewer_widget.py` | **Modify.** `_handle_doppler_calibration_click` → auto-resolve after baseline; add fallback. |
| `src/echo_personal_tool/infrastructure/locales/en.json` | **Modify.** Add i18n keys for auto-cal status/success/fallback. |
| `tests/unit/test_velocity_scale_detector.py` | **Create.** Unit tests for tick detection. |
| `tests/unit/test_auto_doppler_velocity_calibration.py` | **Create.** Unit tests for orchestrator + inference. |
| `tests/unit/test_velocity_scale_ocr.py` | **Create.** Unit tests for OCR reader (mocked/present). |

---

## Task 1: VelocityScaleDetector — find velocity-scale ticks on the right strip

**Files:**
- Create: `src/echo_personal_tool/domain/services/velocity_scale_detector.py`
- Test: `tests/unit/test_velocity_scale_detector.py`

**Interfaces:**
- Consumes: `DopplerSpectrogramRoi` (from `doppler_roi.py`), `np.ndarray` frame.
- Produces: `detect_velocity_scale_ticks(frame, *, roi, ...) -> list[float]` returning sorted y-positions (frame coords) of scale ticks in the strip to the right of the spectrogram ROI.

The detector adapts `detect_depth_scale_ticks` (depth_scale_detector.py:10): instead of searching a vertical column for bright horizontal ticks, it searches a narrow vertical strip just right of `roi.x1` for the velocity-scale tick marks and labels. The strip is darker than the spectrogram interior, so ticks appear as bright horizontal segments.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_velocity_scale_detector.py
import numpy as np
import pytest
from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi
from echo_personal_tool.domain.services.velocity_scale_detector import (
    detect_velocity_scale_ticks,
)


def _make_frame_with_scale(
    height: int = 400,
    width: int = 640,
    roi: DopplerSpectrogramRoi | None = None,
    tick_ys: tuple[int, ...] = (80, 160, 240, 320),
    scale_x: int = 600,
) -> np.ndarray:
    frame = np.zeros((height, width), dtype=np.uint8)
    if roi is None:
        roi = DopplerSpectrogramRoi(x0=40, y0=20, width=540, height=360)
    # Spectrogram interior (dark) so the strip stands out
    frame[int(roi.y0):int(roi.y0 + roi.height), int(roi.x0):int(roi.x1)] = 30
    for y in tick_ys:
        # Tick mark in the strip to the right of the spectrogram
        frame[y, scale_x : scale_x + 10] = 220
    return frame


def test_detects_ticks_in_strip() -> None:
    roi = DopplerSpectrogramRoi(x0=40, y0=20, width=540, height=360)
    frame = _make_frame_with_scale(roi=roi, tick_ys=(80, 160, 240, 320), scale_x=600)
    ticks = detect_velocity_scale_ticks(frame, roi=roi)
    assert len(ticks) == 4
    # Each detected tick within 4px of a planted tick
    for ty in (80, 160, 240, 320):
        assert any(abs(t - ty) <= 4 for t in ticks)


def test_no_ticks_returns_empty() -> None:
    roi = DopplerSpectrogramRoi(x0=40, y0=20, width=540, height=360)
    frame = np.zeros((400, 640), dtype=np.uint8)
    ticks = detect_velocity_scale_ticks(frame, roi=roi)
    assert ticks == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/areatu/ECHO2026 && python -m pytest tests/unit/test_velocity_scale_detector.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'echo_personal_tool.domain.services.velocity_scale_detector'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/echo_personal_tool/domain/services/velocity_scale_detector.py
"""Detect tick marks on the Doppler velocity scale strip (right of spectrogram)."""

from __future__ import annotations

import numpy as np

from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi


def _cluster_to_tops(rows: np.ndarray, min_distance: float) -> list[float]:
    if len(rows) == 0:
        return []
    sorted_rows = np.sort(rows)
    clusters: list[list[float]] = [[float(sorted_rows[0])]]
    for r in sorted_rows[1:]:
        if r - clusters[-1][-1] <= min_distance:
            clusters[-1].append(float(r))
        else:
            clusters.append([float(r)])
    return [clusters[i][0] for i in range(len(clusters))]


def detect_velocity_scale_ticks(
    frame: np.ndarray,
    *,
    roi: DopplerSpectrogramRoi,
    strip_width_px: int = 40,
    min_tick_spacing_px: int = 5,
) -> list[float]:
    """Detect y-positions of velocity-scale tick marks in the strip right of *roi*.

    Returns sorted y-positions (frame coordinates). Empty list when none found.
    """
    if frame.ndim == 3:
        gray = np.mean(frame, axis=2).astype(np.float32)
    else:
        gray = frame.astype(np.float32)

    h, w = gray.shape
    strip_x0 = min(int(roi.x1), w - 1)
    strip_x1 = min(strip_x0 + strip_width_px, w)
    if strip_x1 <= strip_x0:
        return []

    y0 = max(0, int(roi.y0))
    y1 = min(h, int(roi.y0 + roi.height))
    sub = gray[y0:y1, strip_x0:strip_x1]
    if sub.size == 0:
        return []

    col_max = np.max(sub, axis=1)
    row_median = np.median(col_max)
    row_std = np.std(col_max)
    if row_std < 2.0:
        return []

    bright_threshold = max(row_median + 1.5 * row_std, 30.0)
    bright_rows = np.where(col_max > bright_threshold)[0]
    if len(bright_rows) == 0:
        return []

    candidates = _cluster_to_tops(bright_rows, min_tick_spacing_px)
    margin_top = int(sub.shape[0] * 0.04)
    margin_bottom = int(sub.shape[0] * 0.04)
    candidates = [c for c in candidates if margin_top <= c < sub.shape[0] - margin_bottom]
    return sorted(float(y0 + c) for c in candidates)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/areatu/ECHO2026 && python -m pytest tests/unit/test_velocity_scale_detector.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/domain/services/velocity_scale_detector.py tests/unit/test_velocity_scale_detector.py
git commit -m "feat(doppler): add velocity scale tick detector for mp4 frames"
```

---

## Task 2: Standard-value inference (no new deps)

**Files:**
- Create: `src/echo_personal_tool/domain/services/auto_doppler_velocity_calibration.py` (inference portion)
- Test: `tests/unit/test_auto_doppler_velocity_calibration.py`

**Interfaces:**
- Consumes: `detect_velocity_scale_ticks`, `DopplerSpectrogramRoi`, `DopplerKind`, baseline y (float).
- Produces: `infer_velocity_span(tick_ys, baseline_y, *, roi, kind) -> float | None` — returns the best-matching standard velocity span (cm/s) given tick geometry, or None.

Inference logic: the baseline is 0 cm/s. Grid lines above/below it are evenly spaced. We test each standard spectral/tissue span; for a span S the velocity at the topmost tick above baseline is `S/2` and the velocity between adjacent ticks is `S/(2*N_above)`. We pick the S whose implied per-interval velocity is a "round" clinical number and whose spacing matches the detected pixel spacing. This mirrors `auto_depth_calibration.py:_infer_major_spacing`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_auto_doppler_velocity_calibration.py
import numpy as np
from echo_personal_tool.domain.models.doppler_roi import (
    DopplerKind,
    DopplerSpectrogramRoi,
)
from echo_personal_tool.domain.services.auto_doppler_velocity_calibration import (
    infer_velocity_span,
)

_SPECTRAL_SPANS = [50.0, 100.0, 150.0, 200.0, 250.0, 300.0, 350.0, 400.0]


def test_infer_span_matches_known_layout() -> None:
    # ROI height 400, baseline at center y=200, 4 evenly spaced ticks above
    # at 40px spacing -> top tick at y=40 (160px above baseline).
    roi = DopplerSpectrogramRoi(x0=40, y0=0, width=540, height=400)
    baseline_y = 200.0
    tick_ys = [40.0, 80.0, 120.0, 160.0, 200.0, 240.0, 280.0, 320.0, 360.0]
    span = infer_velocity_span(tick_ys, baseline_y, roi=roi, kind=DopplerKind.SPECTRAL)
    assert span in _SPECTRAL_SPANS
    # 4 intervals above baseline over 160px; span/2 must divide evenly
    n_above = 4
    per_interval = (span / 2.0) / n_above
    # Consistency: pixel spacing should match the computed per-velocity-velocity
    # interval. For a uniform scale, the detected pixel interval (not 160px but
    # the actual spacing) is consistent only when the span is a standard value.
    # This assertion confirms the span is one of the known standard values.
    assert span in _SPECTRAL_SPANS


def test_infer_span_none_for_degenerate() -> None:
    roi = DopplerSpectrogramRoi(x0=40, y0=0, width=540, height=400)
    span = infer_velocity_span([200.0], 200.0, roi=roi, kind=DopplerKind.SPECTRAL)
    assert span is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/areatu/ECHO2026 && python -m pytest tests/unit/test_auto_doppler_velocity_calibration.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/echo_personal_tool/domain/services/auto_doppler_velocity_calibration.py
"""Auto-calibrate Doppler velocity scale from detected ticks + baseline."""

from __future__ import annotations

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
        # Consistency: pixel interval should match roi-derived spacing
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/areatu/ECHO2026 && python -m pytest tests/unit/test_auto_doppler_velocity_calibration.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/domain/services/auto_doppler_velocity_calibration.py tests/unit/test_auto_doppler_velocity_calibration.py
git commit -m "feat(doppler): infer velocity span from tick geometry"
```

---

## Task 3: Optional OCR label reader (surya-ocr)

**Files:**
- Create: `src/echo_personal_tool/domain/services/velocity_scale_ocr.py`
- Test: `tests/unit/test_velocity_scale_ocr.py`

**Interfaces:**
- Consumes: `np.ndarray` frame, `DopplerSpectrogramRoi`, tick y-positions.
- Produces: `read_velocity_labels(frame, *, roi, tick_ys) -> dict[float, float] | None` mapping tick y → velocity cm/s; returns None if OCR unavailable/failed.

The reader crops a small horizontal band at each tick y (within the scale strip), runs surya-ocr recognition if importable, parses the leading integer (ignoring units/whitespace), and maps it to the tick y. It must be tolerant: if surya-ocr is not importable (not a hard dep), return None so the caller falls back to inference.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_velocity_scale_ocr.py
import numpy as np
from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi
from echo_personal_tool.domain.services.velocity_scale_ocr import (
    read_velocity_labels,
    _parse_velocity_text,
)


def test_parse_velocity_text() -> None:
    assert _parse_velocity_text("50") == 50.0
    assert _parse_velocity_text("100 cm/s") == 100.0
    assert _parse_velocity_text(" 150 ") == 150.0
    assert _parse_velocity_text("no-number") is None


def test_read_labels_returns_none_without_ocr(monkeypatch) -> None:
    # Simulate missing surya module
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("surya"):
            raise ImportError("no surya")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    roi = DopplerSpectrogramRoi(x0=40, y0=0, width=540, height=400)
    frame = np.zeros((400, 640), dtype=np.uint8)
    result = read_velocity_labels(frame, roi=roi, tick_ys=[200.0])
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/areatu/ECHO2026 && python -m pytest tests/unit/test_velocity_scale_ocr.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/echo_personal_tool/domain/services/velocity_scale_ocr.py
"""Optional OCR-based reading of velocity scale labels (surya-ocr)."""

from __future__ import annotations

import re

import numpy as np

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
    recognizer = _surya_recognizer()
    if recognizer is None or not tick_ys:
        return None

    h, w = frame.shape[:2]
    from PIL import Image  # type: ignore

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/areatu/ECHO2026 && python -m pytest tests/unit/test_velocity_scale_ocr.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/domain/services/velocity_scale_ocr.py tests/unit/test_velocity_scale_ocr.py
git commit -m "feat(doppler): optional OCR label reader for velocity scale"
```

---

## Task 4: Orchestrator `try_auto_doppler_velocity_calibration`

**Files:**
- Modify: `src/echo_personal_tool/domain/services/auto_doppler_velocity_calibration.py` (add orchestrator)
- Test: `tests/unit/test_auto_doppler_velocity_calibration.py` (add orchestrator tests)

**Interfaces:**
- Consumes: `detect_velocity_scale_ticks`, `infer_velocity_span`, `read_velocity_labels`, `DopplerSpectrogramRoi`, baseline y.
- Produces: `try_auto_doppler_velocity_calibration(frame, *, roi, baseline_y, kind) -> VelocityAutocalibrationResult | None`.

Result dataclass holds `velocity_span_cm_s`, `velocity_per_pixel_cm_s`, `confidence`, `method` ("ocr" | "inferred"). OCR path: from `{y: velocity}` we compute `velocity_per_pixel = (v_top - v_bottom) / |y_top - y_bottom|` then `velocity_span = velocity_per_pixel * roi.height`. Inference path uses `infer_velocity_span` then the same geometry. Confidence is high for OCR, medium for inference.

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/unit/test_auto_doppler_velocity_calibration.py
from echo_personal_tool.domain.services.auto_doppler_velocity_calibration import (
    VelocityAutocalibrationResult,
    try_auto_doppler_velocity_calibration,
)


def test_orchestrator_inferred_path() -> None:
    roi = DopplerSpectrogramRoi(x0=40, y0=0, width=540, height=400)
    baseline_y = 200.0
    tick_ys = [40.0, 80.0, 120.0, 160.0, 200.0, 240.0, 280.0, 320.0, 360.0]
    frame = np.zeros((400, 640), dtype=np.uint8)
    # plant ticks in strip
    for ty in tick_ys:
        frame[int(ty), 600:610] = 220
    result = try_auto_doppler_velocity_calibration(
        frame, roi=roi, baseline_y=baseline_y, kind=DopplerKind.SPECTRAL
    )
    assert result is not None
    assert result.velocity_span_cm_s in _SPECTRAL_SPANS
    assert result.velocity_per_pixel_cm_s > 0
    assert 0.0 < result.confidence <= 1.0


def test_orchestrator_with_ocr_labels(monkeypatch) -> None:
    roi = DopplerSpectrogramRoi(x0=40, y0=0, width=540, height=400)
    # 4 ticks evenly spaced in strip: 20, 100, 200, 300
    # OCR mock: label at y=100 = "200", label at y=300 = "0"
    # dy=200, vpp=1.0 → span=400 (standard)
    frame = np.zeros((400, 640), dtype=np.uint8)
    for y in [20, 100, 200, 300]:
        frame[y, 600:610] = 220

    def fake_read(frame, roi, tick_ys):
        return {100.0: 200.0, 300.0: 0.0}

    monkeypatch.setattr(mod, "read_velocity_labels", fake_read)
    result = try_auto_doppler_velocity_calibration(
        frame, roi=roi, baseline_y=200.0, kind=DopplerKind.SPECTRAL
    )
    assert result is not None
    assert result.method == "ocr"
    assert abs(result.velocity_span_cm_s - 400.0) < 1e-6
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/areatu/ECHO2026 && python -m pytest tests/unit/test_auto_doppler_velocity_calibration.py -v`
Expected: FAIL (NameError / missing symbols)

- [ ] **Step 3: Write minimal implementation**

Append to `auto_doppler_velocity_calibration.py`:

```python
from dataclasses import dataclass


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
    from echo_personal_tool.domain.services.velocity_scale_ocr import read_velocity_labels

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/areatu/ECHO2026 && python -m pytest tests/unit/test_auto_doppler_velocity_calibration.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/domain/services/auto_doppler_velocity_calibration.py tests/unit/test_auto_doppler_velocity_calibration.py
git commit -m "feat(doppler): add velocity autocalibration orchestrator"
```

---

## Task 5: Wire into viewer — baseline click auto-resolves

**Files:**
- Modify: `src/echo_personal_tool/presentation/viewer_widget.py` (`_handle_doppler_calibration_click`)
- Modify: `src/echo_personal_tool/infrastructure/locales/en.json` (i18n keys)
- Test: `tests/unit/test_doppler_widget.py` (or new `tests/unit/test_doppler_autocal_widget.py`)

**Interfaces:**
- Consumes: `try_auto_doppler_velocity_calibration`, `calibration_from_roi_and_baseline`, `apply_doppler_calibration_state`.
- Produces: after baseline click, if auto-calibration returns high confidence → apply and show success overlay; otherwise fall back to existing `_begin_doppler_velocity_calibration` (2-click + dialog).

The change is localized to `_handle_doppler_calibration_click` (currently at line ~3083). After storing `self._doppler_pending_baseline_y = y` and building `partial`, attempt auto-calibration using `self._current_frame`, `self._doppler_pending_roi`, and `y`. On success, build a full `DopplerCalibrationState` with the resolved `velocity_span_cm_s` and call `apply_doppler_calibration_state`; on failure, proceed to `_begin_doppler_velocity_calibration()` as today.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_doppler_autocal_widget.py
import numpy as np
import pytest

pytestmark = pytest.mark.gui

from echo_personal_tool.domain.models.doppler_roi import (
    DopplerKind,
    DopplerSpectrogramRoi,
)
from echo_personal_tool.presentation.viewer_widget import ViewerWidget


def _frame_with_ticks(height=400, width=640, baseline_y=200,
                      tick_ys=(40,80,120,160,200,240,280,320,360), scale_x=600):
    frame = np.zeros((height, width), dtype=np.uint8)
    roi = DopplerSpectrogramRoi(x0=40, y0=0, width=540, height=height)
    frame[int(roi.y0):int(roi.y0+roi.height), int(roi.x0):int(roi.x1)] = 30
    for ty in tick_ys:
        frame[ty, scale_x:scale_x+10] = 220
    return frame, roi


def test_baseline_click_autocalibrates(qtbot, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QMouseEvent

    widget = ViewerWidget()
    qtbot.addWidget(widget)
    frame, roi = _frame_with_ticks()
    widget._current_frame = frame
    widget._doppler_pending_roi = roi
    widget._doppler_cal_step = "baseline"
    widget._doppler_cal_kind = DopplerKind.SPECTRAL

    # Simulate a left-button press at baseline y
    ev = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        __import__("PySide6.QtCore").QPointF(320, 200),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    handled = widget._handle_doppler_calibration_click(ev)
    assert handled is True
    # Auto-calibration should have produced a calibrated state
    assert widget._doppler_calibration_state is not None
    assert widget._doppler_calibration_state.has_velocity_scale()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/areatu/ECHO2026 && python -m pytest tests/unit/test_doppler_autocal_widget.py -v`
Expected: FAIL (auto-calibration not wired → state None)

- [ ] **Step 3: Write minimal implementation**

In `viewer_widget.py`, add import at top (near line 79):

```python
from echo_personal_tool.domain.services.auto_doppler_velocity_calibration import (
    try_auto_doppler_velocity_calibration,
)
```

Modify `_handle_doppler_calibration_click` baseline branch (after `self._begin_doppler_velocity_calibration()` call) — replace the unconditional call with auto-try:

```python
        if self._doppler_cal_step == "baseline":
            self._doppler_pending_baseline_y = y
            height, width = self._current_frame.shape[:2]
            roi = self._doppler_pending_roi or DopplerSpectrogramRoi(
                x0=0.0, y0=0.0, width=float(width), height=max(1.0, float(height))
            )
            # Attempt one-click auto-calibration (analog of B-mode auto-cal)
            auto = try_auto_doppler_velocity_calibration(
                self._current_frame,
                roi=roi,
                baseline_y=y,
                kind=self._doppler_cal_kind,
            )
            if auto is not None and auto.confidence >= 0.6:
                state = calibration_from_roi_and_baseline(
                    roi,
                    y,
                    velocity_span_cm_s=auto.velocity_span_cm_s,
                    time_span_ms=0.0,
                    kind=self._doppler_cal_kind,
                )
                self.apply_doppler_calibration_state(state)
                self._doppler_pending_roi = None
                self._doppler_pending_baseline_y = None
                self._doppler_cal_step = None
                self._measurement_label.setText(tr("viewer.doppler_calibration_auto_ok"))
                self.spectral_calibration_completed.emit(auto.velocity_span_cm_s)
                return True
            # Fallback: existing 2-click + dialog flow
            partial = calibration_from_roi_and_baseline(
                roi,
                y,
                time_span_ms=0.0,
                kind=self._doppler_cal_kind,
            )
            self._doppler.set_axis_mapping(build_axis_mapping(partial))
            self._begin_doppler_velocity_calibration()
            return True
```

Add i18n key to `en.json` (merge into existing `viewer.*` block):

```json
"viewer.doppler_calibration_auto_ok": "Doppler velocity scale calibrated automatically"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/areatu/ECHO2026 && python -m pytest tests/unit/test_doppler_autocal_widget.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/presentation/viewer_widget.py src/echo_personal_tool/infrastructure/locales/en.json tests/unit/test_doppler_autocal_widget.py
git commit -m "feat(doppler): auto-resolve velocity scale on baseline click for mp4"
```

---

## Self-Review

1. **Spec coverage:** Tick detection (Task 1) ✅; digital value identification via OCR (Task 3) + inference fallback (Task 2) ✅; single baseline-click replaces 3 steps (Task 5) ✅; mp4 frame compatibility (np.ndarray, no DICOM) ✅; B-mode autocal analog (reuses `detect_*` pattern) ✅.
2. **Placeholder scan:** No TBD/TODO. All code blocks are concrete. Test code is inline.
3. **Type consistency:** `detect_velocity_scale_ticks(frame, *, roi) -> list[float]` used consistently in Tasks 1, 4. `infer_velocity_span(tick_ys, baseline_y, *, roi, kind) -> float | None` used in Tasks 2, 4. `VelocityAutocalibrationResult` defined in Task 4 and consumed in Task 5 via `.velocity_span_cm_s` / `.confidence`. `read_velocity_labels(frame, *, roi, tick_ys) -> dict[float, float] | None` consistent in Tasks 3, 4.

**Plan complete and saved to `docs/superpowers/plans/2026-08-08-doppler-velocity-autocalibration.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
