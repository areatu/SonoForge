# Diameter & Area Comparison Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two comparison measurement tools — "Сравнение диаметров" (diameter comparison, %D) and "Сравнение площадей" (area comparison, %S) — that let the user draw two segments on the same frame and see the ratio in the frame overlay.

**Architecture:** New `MeasurementAction` enum values route through `main_window.py` → `viewer_widget.py`. A `_ComparisonState` dataclass in `viewer_widget.py` tracks the two-segment workflow. Comparison segments are stored in `_stored_linear_measurements` with keys `("D1", frame)` / `("D2", frame)` so they render via the existing persistent caliper pipeline. Results appear in the frame overlay (bottom-left, same as contour area labels). The "area comparison" button is wired but disabled (coming soon).

**Tech Stack:** Python 3.12, PySide6 (Qt), PyQtGraph, existing i18n (`tr()`), existing `LinearMeasurement` model.

## Global Constraints

- Python ≥ 3.12, PySide6 ≥ 6.5
- No new external dependencies
- All user-visible strings via `tr()` with keys in `ru.json` and `en.json`
- Follow existing code style: type hints, `from __future__ import annotations`, no comments unless asked
- Tests: `pytest` (existing framework in `tests/`)
- Frequent commits — one per task

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `src/echo_personal_tool/presentation/measurement_action.py` | Add `DIAMETER_COMPARE` and `AREA_COMPARE` enum values |
| Modify | `src/echo_personal_tool/presentation/measurement_tools_panel.py` | Add buttons to Setup group, add signals, disable area button |
| Modify | `src/echo_personal_tool/presentation/measures_menu.py` | Add entries to `menu.general` section |
| Modify | `src/echo_personal_tool/presentation/viewer_widget.py` | Add `_ComparisonState`, comparison logic, mouse routing, overlay |
| Modify | `src/echo_personal_tool/presentation/main_window.py` | Route new actions to viewer methods |
| Modify | `src/echo_personal_tool/infrastructure/locales/ru.json` | Russian translations |
| Modify | `src/echo_personal_tool/infrastructure/locales/en.json` | English translations |
| Create | `tests/unit/test_comparison_state.py` | Tests for `_ComparisonState` lifecycle |
| Create | `tests/unit/test_diameter_compare.py` | Tests for %D calculation |

---

### Task 1: Add enum values

**Files:**
- Modify: `src/echo_personal_tool/presentation/measurement_action.py`

**Interfaces:**
- Produces: `MeasurementAction.DIAMETER_COMPARE`, `MeasurementAction.AREA_COMPARE`

- [ ] **Step 1: Add new enum values**

Append before the closing of the class:

```python
    DIAMETER_COMPARE = "diameter_compare"
    AREA_COMPARE = "area_compare"
```

- [ ] **Step 2: Verify import**

Run: `python -c "from echo_personal_tool.presentation.measurement_action import MeasurementAction; print(MeasurementAction.DIAMETER_COMPARE)"`
Expected: `diameter_compare`

- [ ] **Step 3: Commit**

```bash
git add src/echo_personal_tool/presentation/measurement_action.py
git commit -m "feat: add DIAMETER_COMPARE and AREA_COMPARE to MeasurementAction"
```

---

### Task 2: Add i18n keys

**Files:**
- Modify: `src/echo_personal_tool/infrastructure/locales/ru.json`
- Modify: `src/echo_personal_tool/infrastructure/locales/en.json`

**Interfaces:**
- Produces: translation keys for menu, tools, viewer prompts, and result overlay

- [ ] **Step 1: Add Russian keys to `ru.json`**

In the `menu.*` section (after `"menu.spline_volume"`):

```json
  "menu.diameter_compare": "Сравнение диаметров",
  "menu.area_compare": "Сравнение площадей",
```

In the `tools.*` section (after `"tools.window"`):

```json
  "tools.diameter_compare": "Сравнение диаметров",
  "tools.diameter_compare_tip": "Два отрезка на одном кадре → %D (меньший/больший × 100%)",
  "tools.area_compare": "Сравнение площадей",
  "tools.area_compare_tip": "Два контура на одном кадре → %S (меньшая/большая × 100%)",
```

In the `viewer.*` section:

```json
  "viewer.dcmp_click_start": "Сравнение диаметров: клик — начало 1-го отрезка",
  "viewer.dcmp_click_end": "Сравнение диаметров: клик — конец 1-го отрезка",
  "viewer.dcmp_second_start": "Сравнение диаметров: клик — начало 2-го отрезка",
  "viewer.dcmp_second_end": "Сравнение диаметров: клик — конец 2-го отрезка",
  "viewer.dcmp_result": "Сравнение диаметров\n{label1}: {length1}\n{label2}: {length2}\n%D = {percent_d}",
  "viewer.acmp_stub": "Сравнение площадей — будет позже",
  "viewer.dcmp_cancelled": "Сравнение диаметров отменено"
```

- [ ] **Step 2: Add English keys to `en.json`**

In `menu.*`:

```json
  "menu.diameter_compare": "Diameter Compare",
  "menu.area_compare": "Area Compare",
```

In `tools.*`:

```json
  "tools.diameter_compare": "Diameter Compare",
  "tools.diameter_compare_tip": "Two segments on one frame → %D (smaller/larger × 100%)",
  "tools.area_compare": "Area Compare",
  "tools.area_compare_tip": "Two contours on one frame → %S (smaller/larger × 100%)",
```

In `viewer.*`:

```json
  "viewer.dcmp_click_start": "Diameter compare: click — start 1st segment",
  "viewer.dcmp_click_end": "Diameter compare: click — end 1st segment",
  "viewer.dcmp_second_start": "Diameter compare: click — start 2nd segment",
  "viewer.dcmp_second_end": "Diameter compare: click — end 2nd segment",
  "viewer.dcmp_result": "Diameter Compare\n{label1}: {length1}\n{label2}: {length2}\n%D = {percent_d}",
  "viewer.acmp_stub": "Area compare — coming soon",
  "viewer.dcmp_cancelled": "Diameter compare cancelled"
```

- [ ] **Step 3: Verify JSON validity**

Run: `python -c "import json; json.load(open('src/echo_personal_tool/infrastructure/locales/ru.json')); json.load(open('src/echo_personal_tool/infrastructure/locales/en.json')); print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add src/echo_personal_tool/infrastructure/locales/ru.json src/echo_personal_tool/infrastructure/locales/en.json
git commit -m "feat: add i18n keys for diameter/area comparison tools"
```

---

### Task 3: Add buttons to MeasurementToolsPanel

**Files:**
- Modify: `src/echo_personal_tool/presentation/measurement_tools_panel.py`

**Interfaces:**
- Produces: `diameter_compare_requested = Signal()`, `area_compare_requested = Signal()`

- [ ] **Step 1: Add signals**

After `rv_s_prime_requested` (line 42):

```python
    diameter_compare_requested = Signal()
    area_compare_requested = Signal()
```

- [ ] **Step 2: Add buttons to `_build_setup_group`**

Before `row.addStretch(1)`:

```python
        btn_diam_compare = QPushButton(tr("tools.diameter_compare"))
        btn_diam_compare.setToolTip(tr("tools.diameter_compare_tip"))
        btn_diam_compare.clicked.connect(self.diameter_compare_requested.emit)
        row.addWidget(btn_diam_compare)
        btn_area_compare = QPushButton(tr("tools.area_compare"))
        btn_area_compare.setToolTip(tr("tools.area_compare_tip"))
        btn_area_compare.setEnabled(False)
        row.addWidget(btn_area_compare)
```

Note: `area_compare` button is disabled (stub, no contour logic yet).

- [ ] **Step 3: Commit**

```bash
git add src/echo_personal_tool/presentation/measurement_tools_panel.py
git commit -m "feat: add diameter/area compare buttons to MeasurementToolsPanel"
```

---

### Task 4: Add buttons to MeasuresMenu

**Files:**
- Modify: `src/echo_personal_tool/presentation/measures_menu.py`

**Interfaces:**
- Consumes: `MeasurementAction.DIAMETER_COMPARE`, `MeasurementAction.AREA_COMPARE`

- [ ] **Step 1: Add entries to `_MENU`**

In the `"menu.general"` tuple, append after `_btn("menu.spline_volume", ...)`:

```python
(_btn("menu.diameter_compare", MeasurementAction.DIAMETER_COMPARE),)
(_btn("menu.area_compare", MeasurementAction.AREA_COMPARE, enabled=False),)
```

Result:

```python
(
    (
        "menu.general",
        (
            _btn("menu.caliper", MeasurementAction.CALIPER),
            _btn("menu.spline_area", MeasurementAction.SPLINE_AREA),
            _btn("menu.spline_volume", MeasurementAction.SPLINE_VOLUME),
            _btn("menu.diameter_compare", MeasurementAction.DIAMETER_COMPARE),
            _btn("menu.area_compare", MeasurementAction.AREA_COMPARE, enabled=False),
        ),
    ),
)
```

- [ ] **Step 2: Commit**

```bash
git add src/echo_personal_tool/presentation/measures_menu.py
git commit -m "feat: add diameter/area compare to MeasuresMenu (area disabled)"
```

---

### Task 5: Implement comparison state and logic in ViewerWidget

**Files:**
- Modify: `src/echo_personal_tool/presentation/viewer_widget.py`

**Interfaces:**
- Consumes: `LinearMeasurement`, `pixel_to_mm_length`, `inline_caliper_text`, `_stored_linear_measurements`
- Produces: `start_diameter_compare() -> bool`

- [ ] **Step 1: Add `_ComparisonState` dataclass**

Before `class ViewerWidget`, add:

```python
@dataclass
class _ComparisonState:
    kind: str = ""  # "diameter" or ""
    segment1_start: tuple[float, float] | None = None
    segment1_end: tuple[float, float] | None = None
    segment1_mm: float | None = None
    segment2_start: tuple[float, float] | None = None
    segment2_end: tuple[float, float] | None = None
    segment2_mm: float | None = None
    frame_index: int | None = None

    @property
    def first_segment_done(self) -> bool:
        return self.segment1_end is not None and self.segment1_mm is not None

    @property
    def is_active(self) -> bool:
        return self.kind != ""

    def reset(self) -> None:
        self.kind = ""
        self.segment1_start = None
        self.segment1_end = None
        self.segment1_mm = None
        self.segment2_start = None
        self.segment2_end = None
        self.segment2_mm = None
        self.frame_index = None
```

Ensure `from dataclasses import dataclass` is in the imports (check existing imports).

- [ ] **Step 2: Add state variable to `ViewerWidget.__init__`**

After `self._linear_caliper_active = False` (line 643):

```python
        self._comparison_state = _ComparisonState()
```

- [ ] **Step 3: Add `start_diameter_compare` method**

After `toggle_linear_caliper` (around line 1825):

```python
    def start_diameter_compare(self) -> bool:
        if self._current_frame is None:
            return False
        self._clear_calibration_caliper()
        self._clear_linear_caliper_graphics()
        self._linear_caliper_active = True
        self._linear_caliper_start = None
        self._comparison_state = _ComparisonState(
            kind="diameter",
            frame_index=self._contour_frame_index(),
        )
        self._measurement_label.setText(tr("viewer.dcmp_click_start"))
        return True
```

Key difference from original plan: does NOT call `_clear_linear_caliper()` (which would reset `_comparison_state`). Only clears graphics and calibration.

- [ ] **Step 4: Add `start_area_compare` stub**

```python
    def start_area_compare(self) -> bool:
        self._measurement_label.setText(tr("viewer.acmp_stub"))
        return True
```

- [ ] **Step 5: Route comparison in `_handle_linear_caliper_mouse_press`**

At the start of `_handle_linear_caliper_mouse_press` (line 4806), after `if not self._linear_caliper_active: return False`, add:

```python
        if self._comparison_state.kind == "diameter":
            return self._handle_diameter_compare_press(ev)
```

- [ ] **Step 6: Implement `_handle_diameter_compare_press`**

```python
    def _handle_diameter_compare_press(self, ev) -> bool:
        if ev.button() != Qt.MouseButton.LeftButton:
            return False
        click: tuple[float, float] | None = None
        if hasattr(ev, "scenePos"):
            point = self._view.mapSceneToView(ev.scenePos())
            if point is not None:
                click = (float(point.x()), float(point.y()))
        if click is None:
            click = self._map_view_event(ev)
        if click is None:
            return False

        state = self._comparison_state
        frame = state.frame_index

        if state.segment1_start is None:
            state.segment1_start = click
            self._update_linear_caliper_preview(click, click)
            self._measurement_label.setText(tr("viewer.dcmp_click_end"))
            return True

        if state.segment1_end is None:
            state.segment1_end = click
            state.segment1_mm = self._compare_mm_length("D1", state.segment1_start, click)
            key = ("D1", frame if frame is not None else -1)
            self._stored_linear_measurements[key] = LinearMeasurement(
                label="D1",
                pixel_length=math.hypot(click[0] - state.segment1_start[0], click[1] - state.segment1_start[1]),
                millimeter_length=state.segment1_mm,
                frame_index=frame,
                start=state.segment1_start,
                end=click,
            )
            self._render_persistent_linear_calipers()
            self._refresh_frame_overlays()
            self._emit_stored_linear_measurements()
            self._linear_caliper_start = None
            self._clear_linear_caliper_graphics()
            self._linear_caliper_active = True
            self._measurement_label.setText(tr("viewer.dcmp_second_start"))
            return True

        if state.segment2_start is None:
            state.segment2_start = click
            self._linear_caliper_start = click
            self._update_linear_caliper_preview(click, click)
            self._measurement_label.setText(tr("viewer.dcmp_second_end"))
            return True

        state.segment2_end = click
        state.segment2_mm = self._compare_mm_length("D2", state.segment2_start, click)
        key = ("D2", frame if frame is not None else -1)
        self._stored_linear_measurements[key] = LinearMeasurement(
            label="D2",
            pixel_length=math.hypot(click[0] - state.segment2_start[0], click[1] - state.segment2_start[1]),
            millimeter_length=state.segment2_mm,
            frame_index=frame,
            start=state.segment2_start,
            end=click,
        )
        self._linear_caliper_start = None
        self._clear_linear_caliper_graphics()
        self._render_persistent_linear_calipers()
        self._refresh_frame_overlays()
        self._linear_caliper_active = False
        self._emit_stored_linear_measurements()
        return True
```

- [ ] **Step 7: Add `_compare_mm_length` helper**

```python
    def _compare_mm_length(
        self,
        label: str,
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> float:
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        pixel_length = math.hypot(dx, dy)
        angle_degrees = math.degrees(math.atan2(dy, dx))
        pixel_spacing = self._pixel_spacing_for_linear_label(label, start, end)
        if pixel_spacing is not None:
            return pixel_to_mm_length(pixel_length, angle_degrees, pixel_spacing)
        return pixel_length
```

- [ ] **Step 8: Verify mouse move preview for second segment**

No code change needed. The existing `_on_scene_mouse_moved` at line 896 checks `self._linear_caliper_active and self._linear_caliper_start is not None` to update the caliper preview. Since `start_diameter_compare` sets `self._linear_caliper_active = True`, and we set `self._linear_caliper_start = click` when starting the second segment (line 376 in Step 6), the existing logic handles the second segment preview automatically.

- [ ] **Step 9: Add `_build_comparison_d_overlay` helper**

After `_refresh_frame_overlays`:

```python
    def _build_comparison_d_overlay(self) -> str:
        state = self._comparison_state
        if state.kind != "diameter" or not state.first_segment_done or state.segment2_mm is None:
            return ""
        l1 = state.segment1_mm if state.segment1_mm is not None else 0.0
        l2 = state.segment2_mm if state.segment2_mm is not None else 0.0
        if l1 == 0 and l2 == 0:
            return ""
        bigger = max(l1, l2)
        smaller = min(l1, l2)
        pct = (smaller / bigger * 100.0) if bigger > 0 else 0.0
        unit = self._length_display_unit
        m1 = LinearMeasurement(label="D1", pixel_length=0, millimeter_length=l1)
        m2 = LinearMeasurement(label="D2", pixel_length=0, millimeter_length=l2)
        return tr(
            "viewer.dcmp_result",
            label1="D1",
            length1=inline_caliper_text(m1, length_unit=unit),
            label2="D2",
            length2=inline_caliper_text(m2, length_unit=unit),
            percent_d=f"{pct:.1f}%",
        )
```

- [ ] **Step 10: Modify `_refresh_frame_overlays` to include comparison result**

In `_refresh_frame_overlays` (line 4401), before `for line in extra_lines:`:

```python
        if self._comparison_state.kind == "diameter" and self._comparison_state.first_segment_done:
            cmp_line = self._build_comparison_d_overlay()
            if cmp_line:
                self.append_frame_overlay(cmp_line)
```

- [ ] **Step 11: Clear comparison state in `_clear_linear_caliper`**

In `_clear_linear_caliper` (line 3367), add at the top (before `self._linear_caliper_active = False`):

```python
    def _clear_linear_caliper(self) -> None:
        if self._comparison_state.kind:
            self._comparison_state.reset()
        self._linear_caliper_active = False
        self._linear_caliper_start = None
        self._clear_linear_caliper_graphics()
        self._caliper_sequence = []
        self._caliper_sequence_size = 0
        self._measurement_label.setText(f"{self._current_caliper_label()}: —")
        if not self._syncing_state:
            self._emit_stored_linear_measurements()
```

This ensures comparison is cancelled whenever `_clear_linear_caliper` is called: from `toggle_linear_caliper`, `start_calibration_caliper`, `clear()`, `set_state()`, and `cancel_active_tool`. Since `start_diameter_compare` calls `_clear_linear_caliper_graphics()` (not `_clear_linear_caliper()`), the new comparison state won't be reset during startup.

- [ ] **Step 12: Ensure results overlay shows D1/D2 via `_emit_stored_linear_measurements`**

After the comparison completes (end of `_handle_diameter_compare_press`), `_emit_stored_linear_measurements()` is already called (line 398). This triggers `linear_measurements_changed` signal → `_sync_results_overlay` in main_window → D1/D2 appear in the results overlay (top-right). The D1/D2 also appear in the frame overlay (bottom-left) via `_refresh_frame_overlays` → `_linear_measurements_for_frame`. Both overlays show the data.

- [ ] **Step 13: Commit**

```bash
git add src/echo_personal_tool/presentation/viewer_widget.py
git commit -m "feat: implement diameter comparison logic in ViewerWidget"
```

---

### Task 6: Wire actions in MainWindow

**Files:**
- Modify: `src/echo_personal_tool/presentation/main_window.py`

**Interfaces:**
- Consumes: `MeasurementAction.DIAMETER_COMPARE`, `MeasurementAction.AREA_COMPARE`
- Produces: routing from action → viewer method

- [ ] **Step 1: Connect panel signals**

In `MainWindow.__init__`, after existing tool panel connections:

```python
        self._tool_panel.diameter_compare_requested.connect(self._on_diameter_compare_requested)
        self._tool_panel.area_compare_requested.connect(self._on_area_compare_requested)
```

- [ ] **Step 2: Add action routing**

In the action routing method, after the `MeasurementAction.CALIPER` branch:

```python
        elif action == MeasurementAction.DIAMETER_COMPARE:
            self._on_diameter_compare_requested()
        elif action == MeasurementAction.AREA_COMPARE:
            self._on_area_compare_requested()
```

- [ ] **Step 3: Implement handler methods**

```python
def _on_diameter_compare_requested(self) -> None:
    if self._viewer.start_diameter_compare():
        self._show_status(tr("viewer.dcmp_click_start"))
    else:
        self._show_status("Load a frame first")


def _on_area_compare_requested(self) -> None:
    self._viewer.start_area_compare()
```

- [ ] **Step 4: Commit**

```bash
git add src/echo_personal_tool/presentation/main_window.py
git commit -m "feat: wire diameter/area compare actions in MainWindow"
```

---

### Task 7: Write unit tests

**Files:**
- Create: `tests/unit/test_comparison_state.py`
- Create: `tests/unit/test_diameter_compare.py`

- [ ] **Step 1: Write `_ComparisonState` tests**

```python
# tests/unit/test_comparison_state.py
from echo_personal_tool.presentation.viewer_widget import _ComparisonState


def test_empty_state_is_not_active():
    state = _ComparisonState()
    assert not state.is_active
    assert not state.first_segment_done


def test_diameter_state_is_active():
    state = _ComparisonState(kind="diameter")
    assert state.is_active


def test_first_segment_done_after_both_endpoints():
    state = _ComparisonState(kind="diameter", segment1_start=(0, 0), segment1_end=(10, 0), segment1_mm=5.0)
    assert state.first_segment_done


def test_first_segment_not_done_without_mm():
    state = _ComparisonState(kind="diameter", segment1_start=(0, 0), segment1_end=(10, 0))
    assert not state.first_segment_done


def test_reset_clears_all():
    state = _ComparisonState(kind="diameter", segment1_start=(0, 0), segment1_end=(10, 0), segment1_mm=5.0)
    state.reset()
    assert not state.is_active
    assert state.segment1_start is None
    assert state.segment1_mm is None
```

- [ ] **Step 2: Run state tests**

Run: `pytest tests/unit/test_comparison_state.py -v`
Expected: All PASS

- [ ] **Step 3: Write %D calculation tests**

```python
# tests/unit/test_diameter_compare.py
from echo_personal_tool.presentation.viewer_widget import _ComparisonState


def test_percent_d_smaller_second():
    s = _ComparisonState(kind="diameter", segment1_mm=10.0, segment2_mm=5.0)
    bigger = max(s.segment1_mm, s.segment2_mm)
    smaller = min(s.segment1_mm, s.segment2_mm)
    assert smaller / bigger * 100.0 == 50.0


def test_percent_d_equal():
    s = _ComparisonState(kind="diameter", segment1_mm=8.0, segment2_mm=8.0)
    bigger = max(s.segment1_mm, s.segment2_mm)
    smaller = min(s.segment1_mm, s.segment2_mm)
    assert smaller / bigger * 100.0 == 100.0


def test_percent_d_larger_second():
    s = _ComparisonState(kind="diameter", segment1_mm=6.0, segment2_mm=15.0)
    bigger = max(s.segment1_mm, s.segment2_mm)
    smaller = min(s.segment1_mm, s.segment2_mm)
    assert abs(smaller / bigger * 100.0 - 40.0) < 0.01


def test_overlay_not_shown_without_second_segment():
    s = _ComparisonState(kind="diameter", segment1_mm=10.0)
    assert s.first_segment_done
    assert s.segment2_mm is None
```

- [ ] **Step 4: Run all tests**

Run: `pytest tests/unit/test_comparison_state.py tests/unit/test_diameter_compare.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_comparison_state.py tests/unit/test_diameter_compare.py
git commit -m "test: add unit tests for diameter comparison logic"
```

---

### Task 8: Integration smoke test & lint

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/unit/ -v --tb=short`
Expected: No failures

- [ ] **Step 2: Run lint**

Run: `ruff check src/echo_personal_tool/presentation/measurement_action.py src/echo_personal_tool/presentation/measurement_tools_panel.py src/echo_personal_tool/presentation/measures_menu.py src/echo_personal_tool/presentation/viewer_widget.py src/echo_personal_tool/presentation/main_window.py`
Expected: No new errors

- [ ] **Step 3: Verify JSON validity**

Run: `python -c "import json; [json.load(open(f)) for f in ['src/echo_personal_tool/infrastructure/locales/ru.json', 'src/echo_personal_tool/infrastructure/locales/en.json']]; print('OK')"`

- [ ] **Step 4: Final commit if fixes needed**

```bash
git add -A && git commit -m "fix: lint fixes for comparison tools"
```

---

## What changed from v1

| # | Issue | Fix |
|---|-------|-----|
| 1 | Segments not rendered | Store D1/D2 in `_stored_linear_measurements` with keys `("D1", frame)` |
| 2 | "0.0%" shown prematurely | `_build_comparison_d_overlay` returns `""` if `segment2_mm is None` |
| 3 | `_caliper_labels` polluted | Don't call `_set_caliper_label` — comparison doesn't use the label cycle |
| 4 | No preview for 2nd segment | Set `self._linear_caliper_start = click` when 2nd segment starts → existing `_on_scene_mouse_moved` handles it |
| 5 | Double state reset | `_comparison_state.reset()` only in `_clear_linear_caliper`, not in `cancel_active_tool` |
| 6 | Frame change loses state | `start_diameter_compare` calls `_clear_linear_caliper_graphics()` instead of `_clear_linear_caliper()` |
| 7 | Wrong overlay | Frame overlay (bottom-left) + results overlay (top-right) via `_emit_stored_linear_measurements` |
| 8 | `pixel_length=0` | Acceptable — `inline_caliper_text` uses `millimeter_length` when available |
| 9 | Area stub silent | Button disabled in both panel and menu; `start_area_compare` shows "coming soon" |
| 10 | Missing mouseMoveEvent branch | Already covered by existing `_on_scene_mouse_moved` logic at line 896 |
| 11 | D1/D2 persist across files | `_comparison_state.reset()` in `_clear_linear_caliper` — covers all call sites including `set_state` |
| 12 | D1/D2 not in results overlay | `_emit_stored_linear_measurements` called after both 1st and 2nd segment |
