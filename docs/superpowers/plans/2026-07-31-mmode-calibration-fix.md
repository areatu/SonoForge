# M-Mode Calibration Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix M-mode auto-calibration by making depth optional, allow partial state, and add 3-step manual wizard (ROI → depth → time).

**Architecture:** Make `MmodeCalibrationState.vertical_mm_per_pixel` optional (`float | None`), update `mmode_state_from_panel` to return partial state when depth is absent, chain manual wizard from depth to time step, and add `FrameTime`/`CineRate` fallback for time scale.

**Tech Stack:** Python 3.12+, PySide6, existing DICOM infrastructure.

## Global Constraints

- Python 3.12+, PySide6 >=6.6
- Existing test framework: pytest, tests in `tests/unit/`
- i18n via `tr()` function from `infrastructure/i18n.py`
- No new external dependencies
- `MmodeCalibrationState` is frozen dataclass — no mutation after creation

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `domain/models/frame_panels.py` | Modify | Make `vertical_mm_per_pixel` optional, add `from_dicom_tags`, helper methods |
| `domain/services/mmode_calibration.py` | Modify | Return partial state, add `horizontal_ms_from_dataset` |
| `presentation/viewer_widget.py` | Modify | Chain depth→time in wizard, partial auto UI |
| `infrastructure/locales/en.json` | Modify | Add i18n keys for time step |
| `infrastructure/locales/ru.json` | Modify | Add i18n keys for time step |
| `tests/unit/test_mmode_calibration.py` | Modify | Update tests for partial state, add new test cases |

---

### Task 1: Make `MmodeCalibrationState` accept optional depth

**Files:**
- Modify: `src/echo_personal_tool/domain/models/frame_panels.py:88-97`
- Modify: `tests/unit/test_mmode_calibration.py`

**Interfaces:**
- Consumes: existing `DopplerSpectrogramRoi`, `MmodeCalibrationState`
- Produces: `MmodeCalibrationState(vertical_mm_per_pixel: float | None)`, `is_complete()`, `has_depth_from_dicom()`, `has_time_from_dicom()`

- [ ] **Step 1: Write failing tests for partial state**

Add to `tests/unit/test_mmode_calibration.py`:

```python
class TestMmodeCalibrationStatePartial:
    def test_partial_state_no_depth(self):
        """State with ROI but no depth should exist but not be complete."""
        from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi
        state = MmodeCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50),
            vertical_mm_per_pixel=None,
            horizontal_ms_per_pixel=10.0,
        )
        assert state.is_complete() is False
        assert state.vertical_mm_per_pixel is None
        assert state.horizontal_ms_per_pixel == 10.0

    def test_partial_state_no_time(self):
        """State with ROI + depth but no time should be complete (time is optional)."""
        from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi
        state = MmodeCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50),
            vertical_mm_per_pixel=0.5,
            horizontal_ms_per_pixel=None,
        )
        assert state.is_complete() is True

    def test_complete_state(self):
        """State with all fields should be complete."""
        from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi
        state = MmodeCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50),
            vertical_mm_per_pixel=0.5,
            horizontal_ms_per_pixel=10.0,
        )
        assert state.is_complete() is True
        assert state.has_depth_from_dicom() is False
        assert state.has_time_from_dicom() is False

    def test_from_dicom_flags(self):
        """from_dicom_tags flag propagates to helper methods."""
        from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi
        state = MmodeCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50),
            vertical_mm_per_pixel=0.5,
            horizontal_ms_per_pixel=10.0,
            from_dicom_tags=True,
        )
        assert state.has_depth_from_dicom() is True
        assert state.has_time_from_dicom() is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_mmode_calibration.py -v`
Expected: FAIL — `TypeError: __init__()` missing required argument: 'vertical_mm_per_pixel' (or similar)

- [ ] **Step 3: Modify `MmodeCalibrationState` to accept optional depth**

In `domain/models/frame_panels.py`, replace lines 88-97:

```python
@dataclass(frozen=True)
class MmodeCalibrationState:
    """Per-instance M-mode strip calibration (vertical depth scale)."""

    roi: DopplerSpectrogramRoi
    vertical_mm_per_pixel: float | None = None
    horizontal_ms_per_pixel: float | None = None
    from_dicom_tags: bool = False

    def is_complete(self) -> bool:
        return (
            self.roi.width > 0
            and self.roi.height > 0
            and self.vertical_mm_per_pixel is not None
            and self.vertical_mm_per_pixel > 0.0
        )

    def has_depth_from_dicom(self) -> bool:
        return self.from_dicom_tags and self.vertical_mm_per_pixel is not None

    def has_time_from_dicom(self) -> bool:
        return self.from_dicom_tags and self.horizontal_ms_per_pixel is not None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_mmode_calibration.py -v`
Expected: All new tests PASS

- [ ] **Step 5: Fix existing tests that assume `vertical_mm_per_pixel` is required**

The existing `_m_mode_panel()` helper creates panels with deltas that produce valid `vertical_mm_per_pixel`. The existing test `test_valid_m_mode_panel` asserts `state.vertical_mm_per_pixel > 0.0` — this still works because the panel has deltas.

Check if `test_m_mode_no_vertical_calibration` needs updating — it currently expects `None` from `mmode_state_from_panel`, but after Task 2 it will return a partial state. **Defer this to Task 2.**

- [ ] **Step 6: Commit**

```bash
git add src/echo_personal_tool/domain/models/frame_panels.py tests/unit/test_mmode_calibration.py
git commit -m "feat(mmode): make vertical_mm_per_pixel optional in MmodeCalibrationState"
```

---

### Task 2: Return partial state from `mmode_state_from_panel`

**Files:**
- Modify: `src/echo_personal_tool/domain/services/mmode_calibration.py`
- Modify: `tests/unit/test_mmode_calibration.py`

**Interfaces:**
- Consumes: `MmodeCalibrationState` from Task 1
- Produces: `mmode_state_from_panel()` returns partial state when depth is absent

- [ ] **Step 1: Write failing test for partial panel**

Add to `tests/unit/test_mmode_calibration.py`:

```python
class TestMmodeStateFromPanelPartial:
    def test_m_mode_no_vertical_returns_partial(self):
        """M-mode panel without PhysicalDeltaY → partial state with ROI only."""
        panel = UltrasoundPanel(
            kind=PanelKind.M_MODE,
            bounds=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50),
        )
        state = mmode_state_from_panel(panel)
        assert state is not None
        assert state.vertical_mm_per_pixel is None
        assert state.horizontal_ms_per_pixel is None
        assert state.is_complete() is False
        assert state.roi.width == 100

    def test_m_mode_with_time_only(self):
        """M-mode panel with PhysicalDeltaX but no PhysicalDeltaY → partial state with time."""
        panel = UltrasoundPanel(
            kind=PanelKind.M_MODE,
            bounds=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50),
            physical_delta_x=0.01,
            physical_units_x=3,
        )
        state = mmode_state_from_panel(panel)
        assert state is not None
        assert state.vertical_mm_per_pixel is None
        assert state.horizontal_ms_per_pixel is not None
        assert state.is_complete() is False

    def test_m_mode_zero_vertical_still_returns_partial(self):
        """M-mode panel with PhysicalDeltaY=0 → partial state (not rejected)."""
        panel = UltrasoundPanel(
            kind=PanelKind.M_MODE,
            bounds=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50),
            physical_delta_y=0.0,
            physical_units_y=2,
        )
        state = mmode_state_from_panel(panel)
        assert state is not None
        assert state.vertical_mm_per_pixel is None
        assert state.is_complete() is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_mmode_calibration.py::TestMmodeStateFromPanelPartial -v`
Expected: FAIL — `assert state is not None` fails (current code returns `None`)

- [ ] **Step 3: Update `mmode_state_from_panel` to return partial state**

Replace entire `domain/services/mmode_calibration.py`:

```python
"""Build M-mode calibration from ultrasound panels."""

from __future__ import annotations

from echo_personal_tool.domain.models.frame_panels import (
    MmodeCalibrationState,
    PanelKind,
    UltrasoundPanel,
)


def mmode_state_from_panel(panel: UltrasoundPanel) -> MmodeCalibrationState | None:
    if panel.kind is not PanelKind.M_MODE:
        return None
    # ROI always; scales only if present
    return MmodeCalibrationState(
        roi=panel.bounds,
        vertical_mm_per_pixel=panel.vertical_mm_per_pixel,   # may be None
        horizontal_ms_per_pixel=panel.horizontal_ms_per_pixel,
        from_dicom_tags=True,
    )
```

- [ ] **Step 4: Update existing test that expected `None`**

The existing test `test_m_mode_no_vertical_calibration` (line 47-53) expects `mmode_state_from_panel(panel) is None`. After this change, it returns a partial state. Update it:

```python
def test_m_mode_no_vertical_calibration(self):
    """M-mode panel with no physical_delta_y → partial state (not None)."""
    panel = UltrasoundPanel(
        kind=PanelKind.M_MODE,
        bounds=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50),
    )
    state = mmode_state_from_panel(panel)
    assert state is not None
    assert state.vertical_mm_per_pixel is None
    assert state.is_complete() is False
```

Also update `test_m_mode_zero_vertical` (line 55-62):

```python
def test_m_mode_zero_vertical(self):
    """M-mode panel with PhysicalDeltaY=0 → partial state."""
    panel = UltrasoundPanel(
        kind=PanelKind.M_MODE,
        bounds=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50),
        physical_delta_y=0.0,
        physical_units_y=2,
    )
    state = mmode_state_from_panel(panel)
    assert state is not None
    assert state.vertical_mm_per_pixel is None
    assert state.is_complete() is False
```

- [ ] **Step 5: Run all M-mode calibration tests**

Run: `pytest tests/unit/test_mmode_calibration.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/echo_personal_tool/domain/services/mmode_calibration.py tests/unit/test_mmode_calibration.py
git commit -m "fix(mmode): return partial calibration state when depth is absent"
```

---

### Task 3: Chain manual wizard depth → time step

**Files:**
- Modify: `src/echo_personal_tool/presentation/viewer_widget.py` (lines 5203-5223)
- Modify: `infrastructure/locales/en.json` (add i18n keys)
- Modify: `infrastructure/locales/ru.json` (add i18n keys)

**Interfaces:**
- Consumes: `_mmode_pending_roi` from wizard step 1 (ROI)
- Produces: `_calibration_kind = "mmode_time"` after depth step completes

- [ ] **Step 1: Add i18n keys**

In `infrastructure/locales/en.json`, add after existing `viewer.mmode_calibration_title`:

```json
"viewer.mmode_cal_time": "M-mode: click start of time interval",
"viewer.mmode_cal_time_prompt": "Known interval duration (ms)",
"viewer.mmode_calibration_complete": "M-mode calibration complete",
"viewer.mmode_partial_calibration": "M-mode: ROI from DICOM. Set depth/time manually."
```

In `infrastructure/locales/ru.json`, add after existing `viewer.mmode_calibration_title`:

```json
"viewer.mmode_cal_time": "M-mode: кликните начало временного интервала",
"viewer.mmode_cal_time_prompt": "Известная длительность интервала (мс)",
"viewer.mmode_calibration_complete": "Калибровка M-режима завершена",
"viewer.mmode_partial_calibration": "M-mode: ROI из DICOM. Задайте depth/time вручную."
```

- [ ] **Step 2: Modify `_prompt_mmode_depth_calibration` to chain to time step**

In `viewer_widget.py`, replace `_prompt_mmode_depth_calibration` (lines 5203-5223):

```python
def _prompt_mmode_depth_calibration(self, length_px: float) -> None:
    known_cm, accepted = QInputDialog.getDouble(
        self,
        tr("viewer.mmode_calibration_title"),
        tr("viewer.mmode_depth_prompt"),
        1.0,
        0.01,
        100.0,
        2,
    )
    self._clear_calibration_caliper()
    if not accepted or self._mmode_pending_roi is None or length_px <= 0.0:
        self._mmode_pending_roi = None
        return
    known_mm = known_cm * 10.0
    self._mmode_pending_depth_mm_per_pixel = known_mm / length_px
    # Chain to time step instead of applying immediately
    self._calibration_kind = "mmode_time"
    self._mmode_time_start_x = None
    self._measurement_label.setText(tr("viewer.mmode_cal_time"))
```

- [ ] **Step 3: Add initialization of `_mmode_pending_depth_mm_per_pixel`**

In `start_mmode_panel_calibration` (line 2371-2380), add initialization:

```python
def start_mmode_panel_calibration(self) -> bool:
    if self._current_frame is None:
        return False
    self.cancel_active_tool()
    self._clear_calibration_caliper()
    self._mmode_cal_step = "roi"
    self._mmode_roi_corner1 = None
    self._mmode_pending_roi = None
    self._mmode_pending_depth_mm_per_pixel = None  # ← ADD
    self._measurement_label.setText(tr("viewer.mmode_cal1"))
    return True
```

- [ ] **Step 4: Modify `_prompt_mmode_time_span` to build full state**

Replace `_prompt_mmode_time_span` (lines 5186-5201):

```python
def _prompt_mmode_time_span(self, length_px: float) -> None:
    span_ms, accepted = QInputDialog.getDouble(
        self,
        "M-mode time scale",
        tr("viewer.mmode_cal_time_prompt"),
        1000.0,
        1.0,
        10000.0,
        0,
    )
    self._clear_calibration_caliper()
    if not accepted or length_px <= 0.0:
        self._mmode_pending_roi = None
        self._mmode_pending_depth_mm_per_pixel = None
        return
    time_per_pixel_ms = span_ms / length_px
    # Build full calibration state if we have pending ROI + depth
    if self._mmode_pending_roi is not None and self._mmode_pending_depth_mm_per_pixel is not None:
        state = MmodeCalibrationState(
            roi=self._mmode_pending_roi,
            vertical_mm_per_pixel=self._mmode_pending_depth_mm_per_pixel,
            horizontal_ms_per_pixel=time_per_pixel_ms,
        )
        self._mmode_pending_roi = None
        self._mmode_pending_depth_mm_per_pixel = None
        self.apply_mmode_calibration_state(state)
    elif not self._syncing_state:
        # Standalone time calibration (no pending ROI)
        self.mmode_time_calibration_completed.emit(float(time_per_pixel_ms))
```

- [ ] **Step 5: Reset pending state in `_clear_calibration_caliper`**

In `viewer_widget.py` `_clear_calibration_caliper` (line 3747-3755), add reset of `_mmode_pending_depth_mm_per_pixel`:

```python
def _clear_calibration_caliper(self) -> None:
    self._calibration_active = False
    self._calibration_start_y = None
    self._mmode_time_start_x = None
    self._calibration_kind = None
    self._doppler_grid_line_positions = []
    self._mmode_pending_depth_mm_per_pixel = None  # ← ADD
    self._clear_calibration_graphics()
    if not self._linear_caliper_active:
        self._measurement_label.setText(f"{self._current_caliper_label()}: —")
```

Also add the same reset in `cancel_active_tool` (line 3373) alongside `_mmode_pending_roi`:

```python
self._mmode_pending_roi = None
self._mmode_pending_depth_mm_per_pixel = None  # ← ADD
```

- [ ] **Step 6: Commit**

```bash
git add src/echo_personal_tool/presentation/viewer_widget.py src/echo_personal_tool/infrastructure/locales/en.json src/echo_personal_tool/infrastructure/locales/ru.json
git commit -m "feat(mmode): chain depth→time in manual wizard, add i18n keys"
```

---

### Task 4: Partial auto-calibration UI prompt

**Files:**
- Modify: `src/echo_personal_tool/presentation/viewer_widget.py` (lines 2358-2369)

**Interfaces:**
- Consumes: `MmodeCalibrationState` from Task 2 (partial state)
- Produces: UI prompt when auto-calibration is incomplete

- [ ] **Step 1: Modify `try_apply_mmode_from_dicom_or_heuristic` for partial state**

Replace lines 2358-2369:

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
    self.apply_mmode_calibration_state(state)
    if not state.is_complete():
        # ROI applied; depth/time missing → suggest manual input
        if state.vertical_mm_per_pixel is None:
            self._start_mmode_depth_only()
        elif state.horizontal_ms_per_pixel is None:
            self._start_mmode_time_only()
    return True
```

- [ ] **Step 2: Add `_start_mmode_depth_only` helper**

Add after `try_apply_mmode_from_dicom_or_heuristic`:

```python
def _start_mmode_depth_only(self) -> None:
    """Start depth calibration without re-defining ROI (uses existing ROI from DICOM)."""
    if self._mmode_calibration_state is None:
        return
    self.cancel_active_tool()
    self._clear_calibration_caliper()
    self._mmode_pending_roi = self._mmode_calibration_state.roi
    self._mmode_pending_depth_mm_per_pixel = None
    self._calibration_kind = "mmode_depth"
    self._calibration_active = True
    self._calibration_x = self._mmode_calibration_state.roi.x0 + self._mmode_calibration_state.roi.width / 2.0
    self._calibration_start_y = None
    self._measurement_label.setText(tr("viewer.mmode_cal_depth"))
```

- [ ] **Step 3: Add `_start_mmode_time_only` helper**

Add after `_start_mmode_depth_only`:

```python
def _start_mmode_time_only(self) -> None:
    """Start time calibration without re-defining ROI (uses existing ROI from DICOM)."""
    if self._mmode_calibration_state is None:
        return
    self.cancel_active_tool()
    self._clear_calibration_caliper()
    self._calibration_kind = "mmode_time"
    self._calibration_active = True
    self._mmode_time_start_x = None
    self._calibration_start_y = None
    self._measurement_label.setText(tr("viewer.mmode_cal_time"))
```

- [ ] **Step 4: Commit**

```bash
git add src/echo_personal_tool/presentation/viewer_widget.py
git commit -m "feat(mmode): partial auto-calibration prompts for missing scales"
```

---

### Task 5: Run full test suite and verify

**Files:**
- Verify: `tests/unit/test_mmode_calibration.py`
- Verify: No regressions in other M-mode tests

- [ ] **Step 1: Run all M-mode unit tests**

Run: `pytest tests/unit/test_mmode_calibration.py tests/unit/test_mmode_models.py tests/unit/test_mmode_widget.py -v`
Expected: All PASS

- [ ] **Step 2: Run lint/typecheck**

Run: `ruff check src/echo_personal_tool/domain/models/frame_panels.py src/echo_personal_tool/domain/services/mmode_calibration.py src/echo_personal_tool/presentation/viewer_widget.py`
Expected: No errors

- [ ] **Step 3: Final commit if needed**

If any fixes were needed in Step 1-2:

```bash
git add -A
git commit -m "fix(mmode): address review feedback from calibration fix"
```

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-31-mmode-calibration-fix.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
