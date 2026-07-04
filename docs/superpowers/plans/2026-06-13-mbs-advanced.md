# MBS Advanced (v1.1) Implementation Plan

> **STATUS: CANCELLED (2026-07-04)** — superseded by Lamé + R-refine; ED→ES propagate not planned.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Active contour border refinement after MBS 3-click landmarks, A2C shape template, and ED→ES propagation on ESV Auto.

**Architecture:** Pure-domain `active_contour_refine.py` (discrete open snake); `mbs_lite_service` uses barycentric templates per view and orchestrates fit+refine; `ViewerWidget` calls refine after apex click and propagates ED contour on ES button.

**Tech Stack:** Python 3.11, NumPy, SciPy (`ndimage`), pytest.

**Spec:** [2026-06-13-mbs-advanced-design.md](../specs/2026-06-13-mbs-advanced-design.md)

---

### Task 1: A2C template + barycentric warp

**Files:**
- Modify: `src/echo_personal_tool/domain/services/lv_shape_template.py`
- Modify: `src/echo_personal_tool/domain/services/mbs_lite_service.py`
- Modify: `tests/unit/test_mbs_lite_service.py`

- [ ] Add `CANONICAL_LV_ARC_A2C` with distinct mid-arc weights
- [ ] Warp via barycentric template selected by `view`
- [ ] Test A4C vs A2C templates differ

### Task 2: active_contour_refine module

**Files:**
- Create: `src/echo_personal_tool/domain/services/active_contour_refine.py`
- Create: `tests/unit/test_active_contour_refine.py`

- [ ] `ActiveContourConfig`, `refine_open_arc()`
- [ ] Synthetic dark-cavity / bright-rim test

### Task 3: fit_and_refine + ED→ES propagate in domain

**Files:**
- Modify: `src/echo_personal_tool/domain/services/mbs_lite_service.py`
- Modify: `tests/unit/test_mbs_lite_service.py`

- [ ] `fit_and_refine_contour_from_landmarks(frame, ...)`
- [ ] `propagate_model_contour_to_frame(frame, ed_contour, phase, frame_index)`

### Task 4: ViewerWidget + MainWindow wiring

**Files:**
- Modify: `src/echo_personal_tool/presentation/viewer_widget.py`
- Modify: `src/echo_personal_tool/presentation/main_window.py`
- Modify: `tests/unit/test_measurement_wiring.py` (if needed)

- [ ] `_finish_model_contour` uses fit_and_refine
- [ ] `start_model_contour(ES)` propagates from ED when available
- [ ] Status messages for propagation vs 3-click

### Task 5: Verification

```bash
uv run pytest tests/unit/test_active_contour_refine.py tests/unit/test_mbs_lite_service.py -v
uv run pytest tests/unit -q
uv run ruff check src tests
```
