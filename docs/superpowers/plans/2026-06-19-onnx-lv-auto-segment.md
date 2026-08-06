# ONNX LV Auto-Segment (A4C Simpson) Implementation Plan

> **Implementation status (2026-06-19):** v1 tasks implemented in codebase. Task checkboxes below are historical; live status — `ROADMAP.md` at repo root.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire EchoNet ONNX auto-segmentation to **LV Auto** A4C ED/ES buttons with ASE papillary post-processing and hybrid review-before-accept UX; Left Ventricle manual contours unchanged.

**Architecture:** Add pure-domain papillary cleanup in `segmentation_service.py`; extend `Contour` with `review_pending`; gate Simpson on accepted contours; replace `_on_mbs_simpson_requested` A4C path with `request_auto_segment`; Enter accepts pending AI contour. Manual `MANUAL_SIMPSON` path untouched.

**Tech Stack:** Python 3.11, NumPy, SciPy (`ndimage`), PySide6/pyqtgraph, onnxruntime (phase2 extra).

**Spec:** `docs/superpowers/specs/2026-06-19-onnx-lv-auto-segment-design.md`

---

## File map

| File | Responsibility |
|------|----------------|
| `domain/services/segmentation_service.py` | `papillary_mask_cleanup`, `exclude_papillary_concavities` |
| `domain/services/contour_geometry.py` | Reuse `apex_point`, `smooth_open_arc`, `point_line_distance` |
| `domain/models/contour.py` | `review_pending: bool` |
| `domain/calculations/lvef_simpson.py` | Skip `review_pending` contours |
| `application/app_controller.py` | Papillary pipeline in `_on_auto_segment_finished`; `accept_ai_contour_review`; LV Auto gating |
| `presentation/main_window.py` | LV Auto → auto-segment; Enter accept; manual unchanged |
| `presentation/measures_menu.py` | Disable LV Auto biplane buttons |
| `presentation/viewer_widget.py` | Dashed pen for pending AI; `pending_ai_review_contour()` |
| `presentation/system_bar.py` | Auto Segment enabled only in LV Auto session |
| `models/model_manifest.json` | `inference.auto_refine_after_segment` flag |
| `tests/unit/test_segmentation_service.py` | Papillary unit tests |
| `tests/unit/test_auto_segment_controller.py` | Pipeline + accept + gating |
| `tests/unit/test_lvef_simpson.py` | `review_pending` gate |
| `tests/unit/test_measures_menu.py` | Biplane disabled |
| `tests/unit/test_phase_hotkeys.py` | `I` gated on LV Auto session |

---

### Task 1: `papillary_mask_cleanup`

**Files:**
- Modify: `src/echo_personal_tool/domain/services/segmentation_service.py`
- Modify: `tests/unit/test_segmentation_service.py`

- [ ] **Step 1: Write failing tests**

```python
# Append to tests/unit/test_segmentation_service.py

from echo_personal_tool.domain.services.segmentation_service import papillary_mask_cleanup


def _mask_with_mid_notch(height: int = 64, width: int = 48) -> np.ndarray:
    mask = np.zeros((height, width), dtype=np.uint8)
    mask[8:56, 12:36] = 1
    mask[28:40, 20:28] = 0  # papillary-like notch
    return mask


def test_papillary_mask_cleanup_fills_mid_notch() -> None:
    mask = _mask_with_mid_notch()
    cleaned = papillary_mask_cleanup(mask)
    assert cleaned[32, 24] == 1
    assert cleaned.sum() >= mask.sum()


def test_papillary_mask_cleanup_preserves_largest_component() -> None:
    mask = _mask_with_mid_notch()
    mask[2:6, 2:6] = 1  # speckle
    cleaned = papillary_mask_cleanup(mask)
    assert cleaned[2:6, 2:6].sum() == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_segmentation_service.py::test_papillary_mask_cleanup_fills_mid_notch -v`
Expected: FAIL — `ImportError: cannot import name 'papillary_mask_cleanup'`

- [ ] **Step 3: Implement `papillary_mask_cleanup`**

```python
# Add to segmentation_service.py after logits_to_mask


def papillary_mask_cleanup(
    mask: np.ndarray,
    *,
    long_axis_hint: tuple[tuple[float, float], tuple[float, float]] | None = None,
) -> np.ndarray:
    """Morphological closing along LV long axis to remove papillary notches."""
    del long_axis_hint  # v1: derive from mask bbox
    binary = np.asarray(mask) > 0
    if not binary.any():
        return np.zeros_like(binary, dtype=np.uint8)

    ys, xs = np.where(binary)
    top_y, bottom_y = int(ys.min()), int(ys.max())
    axis_length = float(bottom_y - top_y + 1)
    se_len = int(np.clip(0.04 * axis_length, 5, 15))

    structure = np.zeros((se_len, se_len), dtype=np.uint8)
    cy, cx = se_len // 2, se_len // 2
    for row in range(se_len):
        structure[row, cx] = 1

    closed = ndimage.binary_closing(binary, structure=structure)
    labeled, count = ndimage.label(closed)
    if count == 0:
        return closed.astype(np.uint8)
    counts = np.bincount(labeled.ravel())
    counts[0] = 0
    largest = int(np.argmax(counts))
    return (labeled == largest).astype(np.uint8)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_segmentation_service.py -k papillary_mask -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/domain/services/segmentation_service.py tests/unit/test_segmentation_service.py
git commit -m "feat: papillary mask cleanup for ONNX LV segment"
```

---

### Task 2: `exclude_papillary_concavities`

**Files:**
- Modify: `src/echo_personal_tool/domain/services/segmentation_service.py`
- Modify: `tests/unit/test_segmentation_service.py`

- [ ] **Step 1: Write failing tests**

```python
from echo_personal_tool.domain.services.segmentation_service import exclude_papillary_concavities


def _arc_with_inward_bump() -> tuple[list[tuple[float, float]], tuple, tuple]:
    annulus = ((0.0, 0.0), (100.0, 0.0))
    apex = (50.0, 80.0)
    points = [
        annulus[0],
        (25.0, 40.0),
        (50.0, 55.0),  # inward bump (papillary)
        (75.0, 40.0),
        annulus[1],
    ]
    return points, annulus, apex


def test_exclude_papillary_concavities_raises_mid_cavity_bump() -> None:
    points, annulus, apex = _arc_with_inward_bump()
    result = exclude_papillary_concavities(points, annulus, apex)
    assert result[0] == annulus[0]
    assert result[-1] == annulus[1]
    mid_y = result[2][1]
    assert mid_y >= 55.0 - 2.0  # bumped outward toward chord


def test_exclude_papillary_concavities_leaves_smooth_arc_unchanged() -> None:
    annulus = ((0.0, 0.0), (100.0, 0.0))
    apex = (50.0, 80.0)
    points = [annulus[0], (50.0, 70.0), annulus[1]]
    result = exclude_papillary_concavities(points, annulus, apex)
    assert result[1][1] == pytest.approx(70.0, abs=2.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_segmentation_service.py::test_exclude_papillary_concavities_raises_mid_cavity_bump -v`
Expected: FAIL — import error

- [ ] **Step 3: Implement**

```python
import math

from echo_personal_tool.domain.services.contour_geometry import smooth_open_arc


def _signed_depth_to_chord(
    point: tuple[float, float],
    chord_start: tuple[float, float],
    chord_end: tuple[float, float],
    *,
    inward_reference: tuple[float, float],
) -> float:
    """Negative depth = point is on inward_reference side of chord (concavity)."""
    x0, y0 = point
    x1, y1 = chord_start
    x2, y2 = chord_end
    cross = (x2 - x1) * (y0 - y1) - (y2 - y1) * (x0 - x1)
    ref_cross = (x2 - x1) * (inward_reference[1] - y1) - (y2 - y1) * (inward_reference[0] - x1)
    sign = -1.0 if ref_cross >= 0.0 else 1.0
    numer = abs((y2 - y1) * x0 - (x2 - x1) * y0 + x2 * y1 - y2 * x1)
    denom = math.hypot(x2 - x1, y2 - y1)
    if denom == 0.0:
        return 0.0
    return sign * numer / denom


def _project_onto_segment(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> tuple[float, float]:
    sx, sy = start
    ex, ey = end
    px, py = point
    dx, dy = ex - sx, ey - sy
    denom = dx * dx + dy * dy
    if denom == 0.0:
        return start
    t = max(0.0, min(1.0, ((px - sx) * dx + (py - sy) * dy) / denom))
    return (sx + t * dx, sy + t * dy)


def exclude_papillary_concavities(
    open_points: list[tuple[float, float]],
    annulus: tuple[tuple[float, float], tuple[float, float]],
    apex: tuple[float, float],
    *,
    depth_threshold_ratio: float = 0.04,
    min_depth_px: float = 2.0,
) -> list[tuple[float, float]]:
    """Push interior nodes outward when concave vs MA–apex chord (ASE papillary rule)."""
    if len(open_points) < 3:
        return list(open_points)

    septal, lateral = annulus
    ma_len = math.hypot(lateral[0] - septal[0], lateral[1] - septal[1])
    threshold = max(min_depth_px, depth_threshold_ratio * ma_len)

    adjusted = [(float(x), float(y)) for x, y in open_points]
    for index in range(1, len(adjusted) - 1):
        depth = _signed_depth_to_chord(
            adjusted[index],
            septal,
            lateral,
            inward_reference=apex,
        )
        if depth < -threshold:
            adjusted[index] = _project_onto_segment(adjusted[index], septal, lateral)

    return smooth_open_arc(adjusted, annulus, apex=apex, iterations=4, blend=0.35)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_segmentation_service.py -k exclude_papillary -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/domain/services/segmentation_service.py tests/unit/test_segmentation_service.py
git commit -m "feat: ASE papillary concavity exclusion on open arc"
```

---

### Task 3: `Contour.review_pending` + Simpson gate

**Files:**
- Modify: `src/echo_personal_tool/domain/models/contour.py`
- Modify: `src/echo_personal_tool/domain/calculations/lvef_simpson.py`
- Modify: `tests/unit/test_lvef_simpson.py`

- [ ] **Step 1: Write failing test**

```python
def test_calculate_ignores_review_pending_contours() -> None:
    pending = open_arc_contour(phase="ed", view="A4C", width_px=100.0, height_px=50.0)
    pending.review_pending = True
    accepted = open_arc_contour(phase="es", view="A4C", width_px=80.0, height_px=40.0)
    result = calculate((pending, accepted), (0.5, 0.5))
    # Only ES accepted — no monoplan pair
    assert result is not None
    assert result.a4c is not None
    assert result.a4c.edv_ml is None
    assert result.a4c.esv_ml is not None
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `uv run pytest tests/unit/test_lvef_simpson.py::test_calculate_ignores_review_pending_contours -v`

- [ ] **Step 3: Add field and filter**

```python
# contour.py
@dataclass
class Contour:
    ...
    review_pending: bool = False
```

```python
# lvef_simpson.py — inside calculate() loop, after chamber/phase/view checks:
if contour.review_pending:
    continue
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_lvef_simpson.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/domain/models/contour.py \
  src/echo_personal_tool/domain/calculations/lvef_simpson.py \
  tests/unit/test_lvef_simpson.py
git commit -m "feat: gate Simpson on accepted AI contours via review_pending"
```

---

### Task 4: AppController — papillary pipeline + accept + LV Auto gating

**Files:**
- Modify: `src/echo_personal_tool/application/app_controller.py`
- Modify: `tests/unit/test_auto_segment_controller.py`

- [ ] **Step 1: Write failing tests**

```python
def test_on_auto_segment_finished_sets_review_pending(
    qapp,
    monkeypatch,
) -> None:
    controller, _, _, instance, pixels = _prepared_controller(monkeypatch)
    controller.set_simpson_workflow_context(phase="ED", view="A4C")
    mask = _circle_mask(height=64, width=48, center_y=32, center_x=24, radius=18)

    controller._on_auto_segment_finished("ED", "A4C", "LV", instance.path, 0, (64, 48), mask)

    contours = controller.state_manager.snapshot.contours
    assert len(contours) == 1
    assert contours[0].source == "ai"
    assert contours[0].review_pending is True


def test_accept_ai_contour_review_clears_pending(qapp, monkeypatch) -> None:
    controller, _, _, instance, _ = _prepared_controller(monkeypatch)
    controller.set_simpson_workflow_context(phase="ED", view="A4C")
    mask = _circle_mask(height=64, width=48, center_y=32, center_x=24, radius=18)
    controller._on_auto_segment_finished("ED", "A4C", "LV", instance.path, 0, (64, 48), mask)
    assert controller.accept_ai_contour_review("A4C", "ED") is True
    assert controller.state_manager.snapshot.contours[0].review_pending is False


def test_request_auto_segment_requires_a4c_view(qapp, monkeypatch) -> None:
    controller, thread_pool, _, _, _ = _prepared_controller(monkeypatch)
    controller.set_simpson_workflow_context(phase="ED", view="A2C")
    messages: list[str] = []
    controller.status_message.connect(messages.append)
    controller.request_auto_segment()
    assert thread_pool.started == []
    assert "A2C" in messages[-1] or "следующей" in messages[-1]
```

Add helper `_circle_mask` in test file (copy from test_segmentation_service).

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Update `_on_auto_segment_finished`**

```python
# New imports
from echo_personal_tool.domain.services.contour_geometry import apex_point
from echo_personal_tool.domain.services.segmentation_service import (
    closed_polygon_to_open_arc,
    exclude_papillary_concavities,
    mask_to_contour,
    papillary_mask_cleanup,
    smooth_contour,
)

# In _on_auto_segment_finished, after isinstance(mask) check:
cleaned_mask = papillary_mask_cleanup(mask)
closed_points = smooth_contour(
    mask_to_contour(cleaned_mask, original_shape),
    num_nodes=32,
)
# ... existing empty check ...
open_points, annulus = closed_polygon_to_open_arc(closed_points, view_hint=view)
apex = apex_point(open_points, annulus)
open_points = exclude_papillary_concavities(open_points, annulus, apex)

contour = Contour(
    phase=phase,
    view=view,
    chamber=chamber,
    mitral_annulus=annulus,
    points=open_points,
    source="ai",
    review_pending=True,
    num_nodes=len(open_points),
    frame_index=frame_index,
)
# status message:
self.status_message.emit(
    f"{view} {phase}: проверьте контур (ASE, без папиллярных мышц) · R — уточнить · Enter — принять"
)
```

- [ ] **Step 4: Add `accept_ai_contour_review` and A4C gating**

```python
def is_lv_auto_session_active(self) -> bool:
    return self._auto_segment_phase in {"ED", "ES"} and self._auto_segment_view == "A4C"


def accept_ai_contour_review(self, view: str, phase: str) -> bool:
    phase_key = phase.upper()
    view_key = view.upper()
    updated: list[Contour] = []
    found = False
    for existing in self._state_manager.snapshot.contours:
        if (
            existing.source == "ai"
            and existing.review_pending
            and existing.view.upper() == view_key
            and existing.phase.upper() == phase_key
            and existing.chamber.upper() == "LV"
        ):
            updated.append(dataclasses.replace(existing, review_pending=False))
            found = True
        else:
            updated.append(existing)
    if not found:
        return False
    self.on_contours_changed(updated)
    self.status_message.emit(f"{view_key} {phase_key}: контур принят")
    return True
```

```python
# request_auto_segment — after phase check, add:
if view.upper() != "A4C":
    self.status_message.emit("A2C auto — в следующей версии")
    return
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/unit/test_auto_segment_controller.py -v`

- [ ] **Step 6: Commit**

```bash
git add src/echo_personal_tool/application/app_controller.py tests/unit/test_auto_segment_controller.py
git commit -m "feat: ONNX auto-segment pipeline with review_pending and LV Auto gating"
```

---

### Task 5: MainWindow — LV Auto triggers ONNX; Enter accepts

**Files:**
- Modify: `src/echo_personal_tool/presentation/main_window.py`
- Modify: `tests/unit/test_measurement_tools_panel.py` (if MBS wiring test exists)

- [ ] **Step 1: Replace `_on_mbs_simpson_requested` for A4C**

```python
def _on_mbs_simpson_requested(self, view: str, phase: str) -> None:
    if view.upper() != "A4C":
        self._show_status("A2C auto — в следующей версии")
        return
    self._controller.set_simpson_workflow_context(phase=phase, view=view, chamber="LV")
    self._system_bar.set_auto_segment_enabled(True)
    self._viewer.clear_frame_overlay()
    self._viewer.append_frame_overlay(f"LV Auto {view} {phase}: сегментация…")
    self._controller.request_auto_segment(phase=phase, view=view, chamber="LV")
```

- [ ] **Step 2: Gate `_request_auto_segment_shortcut`**

```python
def _request_auto_segment_shortcut(self) -> None:
    if not self._controller.is_lv_auto_session_active():
        self._show_status("Выберите LV Auto → EDV/ESV")
        return
    if not self._controller.state_manager.snapshot.is_playing:
        self._controller.request_auto_segment()
```

- [ ] **Step 3: Enter accepts pending AI review**

```python
def _finish_active_tool_shortcut(self) -> None:
    pending = self._viewer.pending_ai_review_contour()
    if pending is not None:
        view, phase = pending.view, pending.phase
        if self._controller.accept_ai_contour_review(view, phase):
            self._viewer.clear_frame_overlay()
            self._maybe_prompt_es_auto(view, phase, mode="mbs")
        return
    # existing trace / finish_contour logic unchanged
```

- [ ] **Step 4: Keep `_on_manual_simpson_requested` unchanged** — verify no edits.

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/presentation/main_window.py
git commit -m "feat: LV Auto buttons trigger ONNX; Enter accepts AI contour"
```

---

### Task 6: Measures menu — disable LV Auto biplane

**Files:**
- Modify: `src/echo_personal_tool/presentation/measures_menu.py`
- Modify: `tests/unit/test_measures_menu.py`

- [ ] **Step 1: Write failing test**

```python
def test_lv_auto_biplane_buttons_disabled(_qapp) -> None:
    menu = MeasuresMenuWidget()
    buttons = [child for child in menu.findChildren(QPushButton) if child.text().startswith("Simpson Biplane")]
    assert len(buttons) == 2
    assert all(not button.isEnabled() for button in buttons)
    assert all("следующей" in button.toolTip() for button in buttons)
```

- [ ] **Step 2: Disable biplane in `_MENU`**

```python
(_btn("Simpson Biplane EDV", MeasurementAction.MBS_SIMPSON, view="A2C", phase="ED", enabled=False),)
(_btn("Simpson Biplane ESV", MeasurementAction.MBS_SIMPSON, view="A2C", phase="ES", enabled=False),)
```

In `MeasuresAccordionSection` button loop:

```python
if not spec.enabled:
    button.setToolTip("A2C auto — в следующей версии")
```

- [ ] **Step 3: Run test + commit**

```bash
uv run pytest tests/unit/test_measures_menu.py::test_lv_auto_biplane_buttons_disabled -v
git add src/echo_personal_tool/presentation/measures_menu.py tests/unit/test_measures_menu.py
git commit -m "feat: disable LV Auto biplane buttons in v1"
```

---

### Task 7: ViewerWidget — pending AI review helper + dashed pen

**Files:**
- Modify: `src/echo_personal_tool/presentation/viewer_widget.py`

- [ ] **Step 1: Add dashed pen for pending AI**

```python
# __init__
self._contour_pen_ai_pending = pg.mkPen("#00bcd4", width=2, style=Qt.PenStyle.DashLine)
```

```python
def _contour_pen_for(self, contour: Contour) -> pg.QtGui.QPen:
    if contour.source == "ai":
        if contour.review_pending:
            return self._contour_pen_ai_pending
        return self._contour_pen_ai
    ...
```

- [ ] **Step 2: Add `pending_ai_review_contour`**

```python
def pending_ai_review_contour(self) -> Contour | None:
    frame_index = self._current_frame_index
    for contour in self._stored_contours:
        if contour.source == "ai" and contour.review_pending and contour.frame_index == frame_index:
            return contour
    return None
```

- [ ] **Step 3: Esc discards pending AI contour**

In `cancel_active_tool` or dedicated handler called from main_window Esc when no active tool:

```python
def discard_pending_ai_contour(self) -> bool:
    pending = self.pending_ai_review_contour()
    if pending is None:
        return False
    self._stored_contours = [
        c
        for c in self._stored_contours
        if not (
            c.source == "ai"
            and c.review_pending
            and c.frame_index == pending.frame_index
            and c.phase == pending.phase
            and c.view == pending.view
        )
    ]
    self._render_contours_for_current_frame()
    return True
```

Wire from `main_window._cancel_active_tool` when `discard_pending_ai_contour()` returns True.

- [ ] **Step 4: Commit**

```bash
git add src/echo_personal_tool/presentation/viewer_widget.py src/echo_personal_tool/presentation/main_window.py
git commit -m "feat: pending AI contour styling and accept/discard helpers"
```

---

### Task 8: System bar + hotkey tests

**Files:**
- Modify: `src/echo_personal_tool/presentation/system_bar.py`
- Modify: `tests/unit/test_phase_hotkeys.py`

- [ ] **Step 1: Update hotkey test**

```python
def test_main_window_i_hotkey_requires_lv_auto_session(qtbot) -> None:
    controller = AppController()
    controller.is_lv_auto_session_active = MagicMock(return_value=False)
    controller.request_auto_segment = MagicMock()
    window = MainWindow(controller=controller)
    qtbot.addWidget(window)
    qtbot.keyClick(window, Qt.Key.Key_I)
    controller.request_auto_segment.assert_not_called()
```

Update existing `test_main_window_i_hotkey_requests_auto_segment_in_2d_mode` to set `controller.set_simpson_workflow_context(phase="ED", view="A4C")` before keypress.

- [ ] **Step 2: System bar — disable Auto Segment by default**

Ensure `set_auto_segment_enabled(False)` on startup; enabled only when LV Auto button pressed (Task 5).

- [ ] **Step 3: Run tests + commit**

```bash
uv run pytest tests/unit/test_phase_hotkeys.py tests/unit/test_system_bar.py -v
git add tests/unit/test_phase_hotkeys.py src/echo_personal_tool/presentation/system_bar.py
git commit -m "test: gate I hotkey on LV Auto session"
```

---

### Task 9: Manifest flag + optional auto R-refine

**Files:**
- Modify: `models/model_manifest.json`
- Modify: `src/echo_personal_tool/application/app_controller.py`

- [ ] **Step 1: Add manifest key**

```json
"inference": {
  ...
  "auto_refine_after_segment": true
}
```

- [ ] **Step 2: In `_on_auto_segment_finished`, after exclude_papillary_concavities**

```python
if self._should_auto_refine_after_segment() and self._current_frame_pixels is not None:
    from echo_personal_tool.domain.services.mbs_lite_service import refine_open_arc_contour

    draft = Contour(...)  # build draft without storing yet
    refined, _ = refine_open_arc_contour(
        self._current_frame_pixels,
        draft,
        display_levels=self._state_manager.snapshot.display_levels,
    )
    open_points = list(refined.points)
```

Only apply when manifest flag true; keep `review_pending=True`.

- [ ] **Step 3: Commit**

```bash
git add models/model_manifest.json src/echo_personal_tool/application/app_controller.py
git commit -m "feat: optional auto R-refine after ONNX segment"
```

---

### Task 10: Final verification

- [x] **Step 1: Run full unit suite** (user-maintained; see AGENTS.md)

- [x] **Step 2: Update spec status** — `Status: Approved` in design spec

- [~] **Step 3: Manual checklist** (user runs on DICOM A4C cine per spec)

---

## Spec coverage checklist

| Spec requirement | Task |
|------------------|------|
| ASE papillary mask cleanup | Task 1 |
| ASE open-arc concavity fill | Task 2 |
| `review_pending` + Simpson gate | Task 3 |
| LV Auto ONNX pipeline | Task 4 |
| Manual LV untouched | Task 5 Step 4 |
| Enter accept / Esc discard | Tasks 5, 7 |
| A2C disabled | Task 6 |
| `I` only in LV Auto session | Tasks 5, 8 |
| Auto R-refine optional | Task 9 |
| Error messages (A4C only, unavailable) | Task 4 |

## Out of scope (do not implement)

- Left Ventricle `MANUAL_SIMPSON` changes
- A2C ONNX
- Fixed train mean/std (v1.1)
- Wall thickness / multi-class miocardium
