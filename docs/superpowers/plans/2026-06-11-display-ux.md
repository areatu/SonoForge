# Display UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement task-by-task.

**Goal:** Fix browser filenames, DICOM color display, larger thumbnails, and W/L + dynamic-range controls.

**Architecture:** Presentation fixes in `local_browser` + `viewer_widget`; infrastructure color preservation in `dicom_session` + `frame_cache`; shared percentile helper in `pixel_utils`.

**Tech Stack:** PySide6, PyQtGraph, pydicom, NumPy, pytest

**Spec:** `docs/superpowers/specs/2026-06-11-display-ux-design.md`

---

### Task 1: Browser instance labels

**Files:**
- Modify: `src/echo_personal_tool/presentation/local_browser.py`
- Create: `tests/unit/test_local_browser_labels.py`

- [ ] **Step 1: Write failing test**

```python
"""Tests for LocalBrowser instance labels."""

from __future__ import annotations

from pathlib import Path

from echo_personal_tool.domain.models import InstanceMetadata
from echo_personal_tool.presentation.local_browser import _instance_label


def test_dicom_instance_label_uses_filename() -> None:
    instance = InstanceMetadata(
        sop_instance_uid="1.2.840.113619.2.55.3.604688123.868.1730000000.123",
        series_uid="1.2.3.4",
        modality="US",
        number_of_frames=45,
        path=Path("/data/study/A4C_clip.dcm"),
        media_format="dicom",
    )
    label = _instance_label(instance)
    assert label.startswith("A4C_clip.dcm")
    assert "45 frames" in label
    assert "1.2.840" not in label


def test_single_frame_label() -> None:
    instance = InstanceMetadata(
        sop_instance_uid="1.2.3",
        series_uid="1.2.4",
        modality="US",
        number_of_frames=1,
        path=Path("/data/frame.dcm"),
    )
    assert _instance_label(instance) == "frame.dcm (1 frame)"
```

- [ ] **Step 2: Run test — expect FAIL**

- [ ] **Step 3: Fix `_instance_label`**

```python
def _instance_label(instance: InstanceMetadata) -> str:
    if instance.number_of_frames == 1:
        frame_label = "1 frame"
    else:
        frame_label = f"{instance.number_of_frames} frames"
    if instance.path is not None:
        filename = instance.path.name
    else:
        filename = f"{instance.sop_instance_uid[:12]}…"
    return f"{filename} ({frame_label})"
```

- [ ] **Step 4: pytest + ruff + commit**

```bash
git commit -m "fix: show disk filename for DICOM instances in browser"
```

---

### Task 2: DICOM color preservation

**Files:**
- Modify: `src/echo_personal_tool/infrastructure/dicom_session.py`
- Modify: `src/echo_personal_tool/application/frame_cache.py`
- Modify: `tests/fixtures/generate_synthetic_dicom.py`
- Modify: `tests/unit/test_dicom_session.py`
- Modify: `tests/unit/test_frame_cache.py`

- [ ] **Step 1: Add `write_synthetic_rgb_dicom(path, frame_count=1, rows=32, cols=32)`** — RGB `PhotometricInterpretation`, `SamplesPerPixel=3`, planar or interleaved per pydicom defaults (interleaved H×W×3 per frame in pixel data).

- [ ] **Step 2: Tests** — RGB decode shape `(1,32,32,3)` or multiframe `(N,32,32,3)`; `FrameCache` accepts 4D stack.

- [ ] **Step 3: Update `stack_pixel_array`** — if last dim is 3 or 4, keep color; only strip alpha to RGB if needed. Grayscale paths unchanged.

- [ ] **Step 4: Update `FrameCache.load`** — allow `ndim==4` and `shape[-1] in (3,4)` OR `ndim==3`.

- [ ] **Step 5: pytest + commit**

```bash
git commit -m "feat: preserve RGB color in DicomSession and FrameCache"
```

---

### Task 3: Larger thumbnails

**Files:**
- Modify: `src/echo_personal_tool/application/workers/thumbnail_loader_worker.py`
- Modify: `src/echo_personal_tool/presentation/local_browser.py`
- Modify: `tests/unit/test_thumbnail_qimage.py`

- [ ] **Step 1: Change `THUMBNAIL_SIZE = 128`**

- [ ] **Step 2: In `LocalBrowserWidget.__init__`:**

```python
from PySide6.QtCore import QSize
self.setIconSize(QSize(128, 128))
```

- [ ] **Step 3: Update tests expecting 64 → 128**

- [ ] **Step 4: pytest + commit**

```bash
git commit -m "feat: increase sidebar thumbnail size to 128px"
```

---

### Task 4: Window/Level + Dynamic Range sliders

**Files:**
- Modify: `src/echo_personal_tool/infrastructure/pixel_utils.py`
- Modify: `src/echo_personal_tool/presentation/viewer_widget.py`
- Create: `tests/unit/test_pixel_utils_display_range.py`

- [ ] **Step 1: Add to `pixel_utils.py`:**

```python
def percentile_range(
    frame: np.ndarray,
    low_pct: float,
    high_pct: float,
) -> tuple[float, float]:
    """Return (vmin, vmax) from percentile clip; low_pct/high_pct in [0, 100]."""
    flat = np.asarray(frame, dtype=np.float64).ravel()
    flat = flat[np.isfinite(flat)]
    if flat.size == 0:
        return 0.0, 1.0
    lo = float(np.percentile(flat, np.clip(low_pct, 0.0, 100.0)))
    hi = float(np.percentile(flat, np.clip(high_pct, 0.0, 100.0)))
    if hi <= lo:
        hi = lo + 1.0
    return lo, hi


def compute_display_levels(
    frame: np.ndarray,
    *,
    dr_low_pct: float,
    dr_high_pct: float,
    window_scale: float,
    level_offset: float,
) -> tuple[float, float]:
    """Map W/L + DR percentiles to pyqtgraph (low, high) levels."""
    vmin, vmax = percentile_range(frame, dr_low_pct, dr_high_pct)
    span = max(vmax - vmin, 1.0)
    window = span * max(window_scale, 0.01)
    center = vmin + span * (0.5 + 0.5 * level_offset)
    return center - window / 2.0, center + window / 2.0
```

- [ ] **Step 2: Unit tests for `percentile_range` and `compute_display_levels`**

- [ ] **Step 3: ViewerWidget** — add `_dr_low_slider`, `_dr_high_slider` (0–100, defaults 0/100); refactor `_update_levels` to use `compute_display_levels`; reset DR on new frame in `show_frame`.

- [ ] **Step 4: Layout** — add row or extend wl_row: `DR min %`, `DR max %` labels + sliders.

- [ ] **Step 5: pytest + commit**

```bash
git commit -m "feat: add dynamic range percentile sliders with window/level"
```

---

### Task 5: Full regression

- [ ] Run `uv run pytest -v` and `uv run ruff check src tests`
- [ ] Commit any test fixes if needed

```bash
git commit -m "test: display UX regression pass"  # only if fixes needed
```
