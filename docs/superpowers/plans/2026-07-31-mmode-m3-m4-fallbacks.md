# M3+M4 Implementation Plan — FrameTime Fallback + B-Mode Depth Proxy

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add time scale fallback from `FrameTime`/`CineRate` (M3) and depth fallback from B-mode panel (M4) to M-mode calibration.

**Architecture:** When M-mode region lacks `PhysicalDeltaX` (time) or `PhysicalDeltaY` (depth), fall back to dataset-level `FrameTime` tag and B-mode panel's `vertical_mm_per_pixel` respectively. Both fallbacks are already extracted elsewhere — we just need to wire them into the M-mode calibration chain.

**Tech Stack:** Python 3.12+, PySide6, existing DICOM infrastructure.

## Global Constraints

- Python 3.12+, PySide6 >=6.6
- Existing test framework: pytest, tests in `tests/unit/`
- No new external dependencies
- `MmodeCalibrationState` from prior work accepts `vertical_mm_per_pixel: float | None`

## Key Findings from Exploration

- `self._current_state.frame_time_ms` already contains `FrameTime`/`CineRate` extracted by `dicom_metadata_mapper.py`
- `panels.b_mode.vertical_mm_per_pixel` is available from `FramePanelLayout` — B-mode and M-mode share the same physical depth in composite frames
- `_resolve_frame_panels()` returns the full layout with both `.m_mode` and `.b_mode`
- `try_parse_panels_from_path` reads the full dataset but discards it after extracting regions

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `domain/services/mmode_calibration.py` | Modify | Add `horizontal_ms_from_frame_time()` helper |
| `domain/models/frame_panels.py` | Modify | Add `MmodeCalibrationState.from_b_mode_depth` flag |
| `presentation/viewer_widget.py` | Modify | Wire fallbacks into `try_apply_mmode_from_dicom_or_heuristic` |
| `tests/unit/test_mmode_calibration.py` | Modify | Tests for new helper + fallback logic |

---

### Task 1: Add `horizontal_ms_from_frame_time` helper

**Files:**
- Modify: `src/echo_personal_tool/domain/services/mmode_calibration.py`
- Modify: `tests/unit/test_mmode_calibration.py`

**Interfaces:**
- Consumes: `frame_time_ms: float | None` from `ViewerState`
- Produces: `horizontal_ms_from_frame_time(frame_time_ms, roi_width_px) -> float | None`

- [ ] **Step 1: Write failing tests**

Add to `tests/unit/test_mmode_calibration.py`:

```python
class TestHorizontalMsFromFrameTime:
    def test_from_frame_time_ms(self):
        """FrameTime in ms → ms per pixel for single-frame M-mode strip."""
        from echo_personal_tool.domain.services.mmode_calibration import horizontal_ms_from_frame_time
        result = horizontal_ms_from_frame_time(500.0, 200.0)
        assert result == 500.0  # ms/px for single-frame strip

    def test_none_frame_time(self):
        """None frame_time → None."""
        from echo_personal_tool.domain.services.mmode_calibration import horizontal_ms_from_frame_time
        assert horizontal_ms_from_frame_time(None, 200.0) is None

    def test_zero_frame_time(self):
        """Zero frame_time → None."""
        from echo_personal_tool.domain.services.mmode_calibration import horizontal_ms_from_frame_time
        assert horizontal_ms_from_frame_time(0.0, 200.0) is None

    def test_zero_roi_width(self):
        """Zero roi_width → None."""
        from echo_personal_tool.domain.services.mmode_calibration import horizontal_ms_from_frame_time
        assert horizontal_ms_from_frame_time(500.0, 0.0) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_mmode_calibration.py::TestHorizontalMsFromFrameTime -v`
Expected: FAIL — `ImportError: cannot import name 'horizontal_ms_from_frame_time'`

- [ ] **Step 3: Implement the helper**

Add to `domain/services/mmode_calibration.py`:

```python
def horizontal_ms_from_frame_time(
    frame_time_ms: float | None, roi_width_px: float
) -> float | None:
    """Fallback time scale from dataset-level FrameTime tag.

    For single-frame M-mode strips: entire width = sweep duration.
    """
    if frame_time_ms is None or frame_time_ms <= 0.0:
        return None
    if roi_width_px <= 0.0:
        return None
    return float(frame_time_ms)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_mmode_calibration.py::TestHorizontalMsFromFrameTime -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/domain/services/mmode_calibration.py tests/unit/test_mmode_calibration.py
git commit -m "feat(mmode): add horizontal_ms_from_frame_time fallback helper"
```

---

### Task 2: Wire fallbacks into `try_apply_mmode_from_dicom_or_heuristic`

**Files:**
- Modify: `src/echo_personal_tool/presentation/viewer_widget.py` (lines 2358-2376)

**Interfaces:**
- Consumes: `self._current_state.frame_time_ms`, `panels.b_mode.vertical_mm_per_pixel`
- Produces: Updated `MmodeCalibrationState` with fallback values when panel lacks deltas

- [ ] **Step 1: Modify `try_apply_mmode_from_dicom_or_heuristic` to apply fallbacks**

The current flow:
```
panel → mmode_state_from_panel(panel) → state (may have None for depth/time)
→ apply state → if incomplete, prompt manual
```

New flow:
```
panel → mmode_state_from_panel(panel) → state
→ if depth is None: try B-mode proxy from panels.b_mode
→ if time is None: try FrameTime from self._current_state
→ rebuild state with fallbacks applied
→ apply state → if incomplete, prompt manual
```

Replace `try_apply_mmode_from_dicom_or_heuristic` in `viewer_widget.py`:

```python
def try_apply_mmode_from_dicom_or_heuristic(self) -> bool:
    panels = self._resolve_frame_panels()
    if panels is None:
        return False
    m_panel = panels.m_mode
    if m_panel is None:
        return False
    state = mmode_state_from_panel(m_panel)
    if state is None:
        return False

    # --- M4: B-mode depth fallback ---
    vertical_mm = state.vertical_mm_per_pixel
    if vertical_mm is None and panels.b_mode is not None:
        b_depth = panels.b_mode.vertical_mm_per_pixel
        if b_depth is not None and b_depth > 0.0:
            vertical_mm = b_depth

    # --- M3: FrameTime fallback ---
    horizontal_ms = state.horizontal_ms_per_pixel
    if horizontal_ms is None and self._current_state is not None:
        horizontal_ms = horizontal_ms_from_frame_time(
            self._current_state.frame_time_ms, state.roi.width
        )

    # Rebuild state with fallbacks if values changed
    if vertical_mm != state.vertical_mm_per_pixel or horizontal_ms != state.horizontal_ms_per_pixel:
        state = MmodeCalibrationState(
            roi=state.roi,
            vertical_mm_per_pixel=vertical_mm,
            horizontal_ms_per_pixel=horizontal_ms,
            from_dicom_tags=state.from_dicom_tags,
        )

    self.apply_mmode_calibration_state(state)
    if not state.is_complete():
        if state.vertical_mm_per_pixel is None:
            self._start_mmode_depth_only()
        elif state.horizontal_ms_per_pixel is None:
            self._start_mmode_time_only()
    return True
```

- [ ] **Step 2: Add import for `horizontal_ms_from_frame_time`**

At the top of `viewer_widget.py`, add to the existing import from `mmode_calibration`:

```python
from echo_personal_tool.domain.services.mmode_calibration import (
    horizontal_ms_from_frame_time,
    mmode_state_from_panel,
)
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/unit/test_mmode_calibration.py -v`
Expected: All PASS (no regressions)

- [ ] **Step 4: Commit**

```bash
git add src/echo_personal_tool/presentation/viewer_widget.py
git commit -m "feat(mmode): wire FrameTime and B-mode depth fallbacks into auto-calibration"
```

---

### Task 3: Update spec and verify end-to-end

**Files:**
- Modify: `docs/superpowers/specs/2026-07-31-mmode-calibration-fix.md` (mark M3+M4 as done)

- [ ] **Step 1: Run full M-mode test suite**

Run: `pytest tests/unit/test_mmode_calibration.py tests/unit/test_mmode_models.py tests/unit/test_mmode_widget.py -v`
Expected: All PASS

- [ ] **Step 2: Run lint**

Run: `ruff check src/echo_personal_tool/domain/services/mmode_calibration.py src/echo_personal_tool/presentation/viewer_widget.py`
Expected: Clean

- [ ] **Step 3: Update spec DoD**

In `docs/superpowers/specs/2026-07-31-mmode-calibration-fix.md`, mark M3 and M4 as done in the DoD section.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-07-31-mmode-calibration-fix.md
git commit -m "docs(mmode): mark M3+M4 as done in spec"
```

---

## Execution Handoff

Plan complete. Two execution options:

**1. Subagent-Driven (recommended)** — dispatch fresh subagent per task

**2. Inline Execution** — execute in this session

Which approach?
