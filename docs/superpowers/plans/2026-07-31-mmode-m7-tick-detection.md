# M7 Implementation Plan — Heuristic Tick Detection for M-Mode Depth

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-calibrate M-mode depth (`vertical_mm_per_pixel`) from tick marks detected in the M-mode strip image when DICOM tags are absent.

**Architecture:** Reuse existing `depth_scale_detector.detect_depth_scale_ticks()` and `auto_depth_calibration.try_auto_depth_calibration()` within the M-mode panel ROI. When M-mode panel lacks `PhysicalDeltaY` and B-mode fallback also fails, detect ticks in the M-mode strip image to infer mm/pixel.

**Tech Stack:** Python 3.12+, numpy, existing depth scale detection infrastructure.

## Global Constraints

- Python 3.12+, PySide6 >=6.6
- Existing test framework: pytest, tests in `tests/unit/`
- No new external dependencies
- Reuse existing `depth_scale_detector` and `auto_depth_calibration` modules

## Key Findings from Exploration

- `detect_depth_scale_ticks(frame, x_center)` — detects ticks in a vertical strip at a given x coordinate. Works on any frame, not just B-mode.
- `auto_depth_calibration.try_auto_depth_calibration(frame)` — infers mm/pixel from detected ticks. Uses `find_scale_ticks()` which searches rightmost 85-99% of frame.
- `detect_panels_heuristic()` — splits frame into B-mode + M-mode at 62% height.
- `snap_y_to_nearest_tick()` — ready to use for M-mode calibration snapping.
- The gap: `find_scale_ticks()` searches the right edge (B-mode convention). M-mode ticks may be elsewhere.

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `domain/services/depth_scale_detector.py` | Modify | Add `find_scale_ticks_in_roi()` for M-mode ROI |
| `domain/services/auto_depth_calibration.py` | Modify | Add `try_auto_depth_calibration_in_roi()` |
| `presentation/viewer_widget.py` | Modify | Wire M7 into `try_apply_mmode_from_dicom_or_heuristic` |
| `tests/unit/test_depth_scale_detector.py` | Create/Modify | Tests for ROI-based tick detection |

---

### Task 1: Add `find_scale_ticks_in_roi()` to depth_scale_detector

**Files:**
- Modify: `src/echo_personal_tool/domain/services/depth_scale_detector.py`
- Modify/Create: `tests/unit/test_depth_scale_detector.py`

**Interfaces:**
- Consumes: `frame: np.ndarray`, `roi: DopplerSpectrogramRoi`
- Produces: `list[float]` of tick Y positions (in frame coordinates)

- [ ] **Step 1: Write failing test**

Create or update `tests/unit/test_depth_scale_detector.py`:

```python
"""Tests for depth_scale_detector ROI-based tick detection."""

from __future__ import annotations

import numpy as np

from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi
from echo_personal_tool.domain.services.depth_scale_detector import (
    detect_depth_scale_ticks,
    find_scale_ticks_in_roi,
)


def _make_frame_with_ticks(height=400, width=600, tick_positions=None, tick_width=30):
    """Create a synthetic frame with bright horizontal tick marks."""
    frame = np.zeros((height, width), dtype=np.uint8)
    if tick_positions is None:
        tick_positions = [50, 100, 150, 200, 250, 300, 350]
    for y in tick_positions:
        frame[y, 100:100 + tick_width] = 200
    return frame


class TestFindScaleTicksInRoi:
    def test_detects_ticks_in_roi(self):
        """Ticks within ROI are detected with correct Y positions."""
        frame = _make_frame_with_ticks()
        roi = DopplerSpectrogramRoi(x0=80, y0=0, width=80, height=400)
        ticks = find_scale_ticks_in_roi(frame, roi)
        assert len(ticks) >= 3
        # Ticks should be near expected positions
        for expected in [50, 100, 150]:
            assert any(abs(t - expected) < 5 for t in ticks)

    def test_ignores_ticks_outside_roi(self):
        """Ticks outside ROI horizontal range are not detected."""
        frame = _make_frame_with_ticks()
        # ROI far from tick column (ticks at x=100-130, ROI at x=300-380)
        roi = DopplerSpectrogramRoi(x0=300, y0=0, width=80, height=400)
        ticks = find_scale_ticks_in_roi(frame, roi)
        assert len(ticks) == 0

    def test_empty_roi(self):
        """Zero-width ROI returns empty list."""
        frame = _make_frame_with_ticks()
        roi = DopplerSpectrogramRoi(x0=100, y0=0, width=0, height=400)
        ticks = find_scale_ticks_in_roi(frame, roi)
        assert ticks == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_depth_scale_detector.py -v`
Expected: FAIL — `ImportError: cannot import name 'find_scale_ticks_in_roi'`

- [ ] **Step 3: Implement `find_scale_ticks_in_roi`**

Add to `depth_scale_detector.py`:

```python
def find_scale_ticks_in_roi(
    frame: np.ndarray, roi: DopplerSpectrogramRoi
) -> list[float]:
    """Detect depth ticks within a specific ROI (e.g., M-mode strip)."""
    from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi as _Roi

    if roi.width <= 0:
        return []

    # Extract ROI sub-frame
    h, w = frame.shape[:2]
    x0 = max(0, int(roi.x0))
    x1 = min(w, int(roi.x0 + roi.width))
    y0 = max(0, int(roi.y0))
    y1 = min(h, int(roi.y0 + roi.height))

    if x1 <= x0 or y1 <= y0:
        return []

    sub_frame = frame[y0:y1, x0:x1]

    # Search for the best column within the ROI
    best_x_local = 0
    best_count = 0
    # Search middle 60% of ROI width (skip edges)
    search_start = int(roi.width * 0.2)
    search_end = int(roi.width * 0.8)
    for x_center in range(search_start, search_end, 3):
        ticks = detect_depth_scale_ticks(
            sub_frame, x_center=x_center, search_half_width_px=10
        )
        if len(ticks) > best_count:
            best_count = len(ticks)
            best_x_local = x_center

    if best_count == 0:
        return []

    ticks_local = detect_depth_scale_ticks(
        sub_frame, x_center=best_x_local, search_half_width_px=10
    )

    # Convert back to frame coordinates
    return sorted(t + y0 for t in ticks_local)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_depth_scale_detector.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/domain/services/depth_scale_detector.py tests/unit/test_depth_scale_detector.py
git commit -m "feat(mmode): add find_scale_ticks_in_roi for M-mode depth detection"
```

---

### Task 2: Add `try_auto_depth_calibration_in_roi()` to auto_depth_calibration

**Files:**
- Modify: `src/echo_personal_tool/domain/services/auto_depth_calibration.py`
- Modify/Create: `tests/unit/test_auto_depth_calibration.py`

**Interfaces:**
- Consumes: `frame: np.ndarray`, `roi: DopplerSpectrogramRoi`
- Produces: `AutoCalibrationResult | None`

- [ ] **Step 1: Write failing test**

```python
"""Tests for auto_depth_calibration ROI-based calibration."""

from __future__ import annotations

import numpy as np

from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi
from echo_personal_tool.domain.services.auto_depth_calibration import (
    try_auto_depth_calibration_in_roi,
)


def _make_frame_with_regular_ticks(height=400, width=600, spacing=50, offset=50):
    """Create a synthetic frame with regularly spaced tick marks."""
    frame = np.zeros((height, width), dtype=np.uint8)
    y = offset
    while y < height - 20:
        frame[y, 100:140] = 200
        y += spacing
    return frame


class TestTryAutoDepthCalibrationInRoi:
    def test_detects_regular_ticks(self):
        """Regular ticks in ROI → valid calibration result."""
        frame = _make_frame_with_regular_ticks()
        roi = DopplerSpectrogramRoi(x0=80, y0=0, width=80, height=400)
        result = try_auto_depth_calibration_in_roi(frame, roi)
        assert result is not None
        assert result.spacing[0] > 0  # vertical mm/px
        assert result.tick_count >= 3
        assert result.confidence > 0.0

    def test_no_ticks_returns_none(self):
        """Empty frame → None."""
        frame = np.zeros((400, 600), dtype=np.uint8)
        roi = DopplerSpectrogramRoi(x0=80, y0=0, width=80, height=400)
        result = try_auto_depth_calibration_in_roi(frame, roi)
        assert result is None

    def test_roi_outside_frame_returns_none(self):
        """ROI outside frame bounds → None."""
        frame = np.zeros((400, 600), dtype=np.uint8)
        roi = DopplerSpectrogramRoi(x0=700, y0=0, width=80, height=400)
        result = try_auto_depth_calibration_in_roi(frame, roi)
        assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_auto_depth_calibration.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement `try_auto_depth_calibration_in_roi`**

Add to `auto_depth_calibration.py`:

```python
def try_auto_depth_calibration_in_roi(
    frame: np.ndarray,
    roi: DopplerSpectrogramRoi,
    *,
    cm_per_major_tick: float = 1.0,
    min_ticks: int = 3,
    max_spacing_cv: float = 0.5,
    min_span_fraction: float = 0.15,
) -> AutoCalibrationResult | None:
    """Auto depth calibration within a specific ROI (e.g., M-mode strip)."""
    from echo_personal_tool.domain.services.depth_scale_detector import find_scale_ticks_in_roi

    ticks = find_scale_ticks_in_roi(frame, roi)
    if len(ticks) < min_ticks:
        return None

    roi_height = roi.height
    span_px = ticks[-1] - ticks[0]
    if roi_height > 0 and span_px / roi_height < min_span_fraction:
        return None

    spacings = np.array([ticks[i + 1] - ticks[i] for i in range(len(ticks) - 1)])

    major_spacing = _infer_major_spacing(spacings)
    if major_spacing is None:
        return None

    close_mask = (spacings > major_spacing * 0.5) & (spacings < major_spacing * 2.0)
    close_spacings = spacings[close_mask]
    if len(close_spacings) < 2:
        return None

    cv = float(np.std(close_spacings) / np.mean(close_spacings))
    if cv > max_spacing_cv:
        return None

    pixel_span = ticks[-1] - ticks[0]
    n_major_intervals = int(round(pixel_span / major_spacing))
    if n_major_intervals < 1:
        return None
    known_mm = n_major_intervals * cm_per_major_tick * 10.0
    spacing = spacing_from_known_distance(pixel_span, known_mm)

    tick_score = min(len(close_spacings) / 10.0, 1.0)
    uniformity_score = max(0.0, 1.0 - cv / max_spacing_cv)
    confidence = 0.5 * tick_score + 0.5 * uniformity_score

    return AutoCalibrationResult(
        spacing=spacing,
        tick_count=len(close_spacings),
        span_px=pixel_span,
        confidence=confidence,
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_auto_depth_calibration.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/domain/services/auto_depth_calibration.py tests/unit/test_auto_depth_calibration.py
git commit -m "feat(mmode): add try_auto_depth_calibration_in_roi for M-mode"
```

---

### Task 3: Wire M7 into `try_apply_mmode_from_dicom_or_heuristic`

**Files:**
- Modify: `src/echo_personal_tool/presentation/viewer_widget.py`

**Interfaces:**
- Consumes: `try_auto_depth_calibration_in_roi(frame, roi)`
- Produces: `vertical_mm_per_pixel` from tick detection

- [ ] **Step 1: Modify fallback chain in `try_apply_mmode_from_dicom_or_heuristic`**

The current fallback chain (after M3+M4):
```
panel → state → B-mode depth fallback → FrameTime fallback → apply → prompt if incomplete
```

New chain:
```
panel → state → B-mode depth fallback → FrameTime fallback
  → if depth still None: try tick detection in M-mode ROI
  → apply → prompt if incomplete
```

Add after the M3 FrameTime fallback block, before `self.apply_mmode_calibration_state(state)`:

```python
# --- M7: Tick detection fallback ---
if vertical_mm is None and self._current_frame is not None:
    from echo_personal_tool.domain.services.auto_depth_calibration import (
        try_auto_depth_calibration_in_roi,
    )
    tick_result = try_auto_depth_calibration_in_roi(self._current_frame, state.roi)
    if tick_result is not None and tick_result.spacing[0] > 0.0:
        vertical_mm = tick_result.spacing[0]
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/unit/test_mmode_calibration.py -v`
Expected: All PASS (no regressions)

- [ ] **Step 3: Commit**

```bash
git add src/echo_personal_tool/presentation/viewer_widget.py
git commit -m "feat(mmode): wire tick detection fallback for M-mode depth"
```

---

### Task 4: Final verification

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/unit/test_mmode_calibration.py tests/unit/test_depth_scale_detector.py tests/unit/test_auto_depth_calibration.py -v`
Expected: All PASS

- [ ] **Step 2: Run lint**

Run: `ruff check src/echo_personal_tool/domain/services/depth_scale_detector.py src/echo_personal_tool/domain/services/auto_depth_calibration.py src/echo_personal_tool/presentation/viewer_widget.py`
Expected: Clean

- [ ] **Step 3: Update spec**

Mark M7 as done in `docs/superpowers/specs/2026-07-31-mmode-calibration-fix.md` DoD.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-07-31-mmode-calibration-fix.md
git commit -m "docs(mmode): mark M7 as done in spec"
```

---

## Execution Handoff

Plan complete. Two execution options:

**1. Subagent-Driven (recommended)** — dispatch fresh subagent per task

**2. Inline Execution** — execute in this session

Which approach?
