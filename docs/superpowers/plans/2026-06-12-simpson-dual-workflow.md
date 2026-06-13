# Simpson Dual Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split Simpson into Manual and MBS-lite button workflows with ED→ES hints/blink, remove D/S frame markers, and show per-view Russian LV metrics (length, КДО, КСО) in Measurements — including partial results after ED alone.

**Architecture:** Extend domain models (`LvViewMetrics`, `LvefResult`) and `lvef_simpson.calculate()` for partial per-view metrics. Remove `ed_frame_index`/`es_frame_index` from state. Rebuild `MeasurementToolsPanel` with Manual + MBS sub-groups. `MainWindow` coordinates ES prompts; panel owns blink animation. `ViewerWidget` shows numeric overlay per contour; `MeasurementPanel` renders Russian labels.

**Tech Stack:** Python 3.11, PySide6, NumPy, SciPy, pytest-qt.

**Spec:** [2026-06-12-simpson-dual-workflow-design.md](../specs/2026-06-12-simpson-dual-workflow-design.md)

---

## File map

| File | Responsibility |
|------|----------------|
| `domain/models/measurements.py` | `LvViewMetrics`, extended `LvefResult` |
| `domain/models/viewer_state.py` | Remove ED/ES frame fields |
| `domain/models/__init__.py` | Export `LvViewMetrics` |
| `domain/calculations/lvef_simpson.py` | Partial per-view metrics, length/volume per contour |
| `application/state_manager.py` | Remove `mark_ed`/`mark_es`/`clear_phase_markers` |
| `application/app_controller.py` | Remove phase-marker APIs; simplify auto-segment phase |
| `presentation/measurement_tools_panel.py` | Manual + MBS groups, blink API, new signals |
| `presentation/main_window.py` | Coordinator, wire signals, remove D/S shortcuts |
| `presentation/viewer_widget.py` | Remove ED/ES labels/timeline markers; numeric overlay |
| `presentation/measurement_panel.py` | Russian per-view LV section |
| `tests/unit/test_measurement_models.py` | `LvViewMetrics` tests |
| `tests/unit/test_lvef_simpson.py` | Partial + per-view assertions |
| `tests/unit/test_measurement_panel.py` | Russian labels |
| `tests/unit/test_measurement_tools_panel.py` | Dual groups, signals, blink |
| `tests/unit/test_measurement_controller.py` | Updated `LvefResult` shape |
| `tests/unit/test_state_manager.py` | Remove marker tests |
| `tests/unit/test_phase_hotkeys.py` | Remove D/S tests |
| `tests/unit/test_mbs_lite_service.py` | Updated `LvefResult` assertions |

---

### Task 1: Domain models — `LvViewMetrics` and extended `LvefResult`

**Files:**
- Modify: `src/echo_personal_tool/domain/models/measurements.py`
- Modify: `src/echo_personal_tool/domain/models/__init__.py`
- Modify: `tests/unit/test_measurement_models.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/unit/test_measurement_models.py`:

```python
from echo_personal_tool.domain.models import LvViewMetrics, LvefResult


def test_lv_view_metrics_defaults() -> None:
    metrics = LvViewMetrics()
    assert metrics.length_ed_mm is None
    assert metrics.length_es_mm is None
    assert metrics.edv_ml is None
    assert metrics.esv_ml is None


def test_lvef_result_partial_ed_only() -> None:
    result = LvefResult(
        a4c=LvViewMetrics(length_ed_mm=82.0, edv_ml=124.5),
        lvef_percent=None,
        method=None,
    )
    assert result.a4c is not None
    assert result.a4c.edv_ml == 124.5
    assert result.lvef_percent is None
    assert result.a2c is None
```

Update `test_lvef_result_creation` to use new shape:

```python
def test_lvef_result_creation() -> None:
    result = LvefResult(
        a4c=LvViewMetrics(edv_ml=120.0, esv_ml=45.0),
        lvef_percent=62.5,
        method="simpson_monoplan",
    )
    assert result.a4c is not None
    assert result.a4c.edv_ml == 120.0
    assert result.a4c.esv_ml == 45.0
    assert result.lvef_percent == 62.5
```

Update `test_measurement_snapshot_populated` similarly.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_measurement_models.py -v`  
Expected: FAIL — `LvViewMetrics` not defined; `LvefResult` missing `a4c` field

- [ ] **Step 3: Implement models**

Replace `LvefResult` in `measurements.py`:

```python
@dataclass(frozen=True)
class LvViewMetrics:
    length_ed_mm: float | None = None
    length_es_mm: float | None = None
    edv_ml: float | None = None
    esv_ml: float | None = None


@dataclass(frozen=True)
class LvefResult:
    a4c: LvViewMetrics | None = None
    a2c: LvViewMetrics | None = None
    lvef_percent: float | None = None
    method: str | None = None  # simpson_monoplan / simpson_biplan
```

Export in `domain/models/__init__.py`:

```python
from echo_personal_tool.domain.models.measurements import (
    ...
    LvViewMetrics,
    ...
)

__all__ = [
    ...
    "LvViewMetrics",
    ...
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_measurement_models.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/domain/models/measurements.py \
        src/echo_personal_tool/domain/models/__init__.py \
        tests/unit/test_measurement_models.py
git commit -m "feat: add LvViewMetrics and extend LvefResult for per-view Simpson"
```

---

### Task 2: `lvef_simpson` — partial per-view metrics

**Files:**
- Modify: `src/echo_personal_tool/domain/calculations/lvef_simpson.py`
- Modify: `tests/unit/test_lvef_simpson.py`
- Modify: `tests/unit/test_measurement_controller.py`
- Modify: `tests/unit/test_mbs_lite_service.py`

- [ ] **Step 1: Write failing tests**

Replace `test_calculate_without_ed_es_pair_returns_none` in `test_lvef_simpson.py`:

```python
def test_calculate_single_ed_returns_partial_a4c_metrics() -> None:
    contours = (
        open_arc_contour(phase="ED", view="A4C", width_px=100.0, height_px=50.0),
    )
    result = calculate(contours, (0.5, 0.5))

    assert result is not None
    assert result.a4c is not None
    assert result.a4c.edv_ml is not None
    assert result.a4c.edv_ml > 0.0
    assert result.a4c.length_ed_mm is not None
    assert result.a4c.length_ed_mm > 0.0
    assert result.a4c.esv_ml is None
    assert result.lvef_percent is None
    assert result.method is None
```

Update existing full-pair tests to use per-view fields:

```python
assert result.a4c is not None
assert result.a4c.edv_ml == pytest.approx(49.087385, rel=1e-6)
assert result.a4c.esv_ml == pytest.approx(25.132741, rel=1e-6)
assert result.lvef_percent == pytest.approx(48.8, rel=1e-6)
assert result.method == "simpson_monoplan"
```

Add biplan per-view test:

```python
def test_calculate_biplan_populates_both_views() -> None:
    contours = (
        open_arc_contour(phase="ED", view="A4C", width_px=100.0, height_px=50.0),
        open_arc_contour(phase="ES", view="A4C", width_px=80.0, height_px=40.0),
        open_arc_contour(phase="ED", view="A2C", width_px=120.0, height_px=50.0),
        open_arc_contour(phase="ES", view="A2C", width_px=100.0, height_px=40.0),
    )
    result = calculate(contours, (0.5, 0.5))
    assert result is not None
    assert result.a4c is not None
    assert result.a2c is not None
    assert result.method == "simpson_biplan"
```

Update `test_measurement_controller.py`:

```python
assert snapshot.lvef.a4c is not None
assert snapshot.lvef.a4c.edv_ml > 0.0
assert snapshot.lvef.a4c.esv_ml > 0.0
```

Update `test_mbs_lite_service.py` similarly (`result.a4c.edv_ml`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_lvef_simpson.py tests/unit/test_measurement_controller.py tests/unit/test_mbs_lite_service.py -v`  
Expected: FAIL — `LvefResult` has no `edv_ml` attribute / partial path returns `None`

- [ ] **Step 3: Implement `calculate()` refactor**

Add helpers and refactor `lvef_simpson.py`:

```python
from echo_personal_tool.domain.models import Contour, LvefResult, LvViewMetrics


def _contour_length_mm(
    contour: Contour,
    pixel_spacing: tuple[float, float],
) -> float | None:
    if contour.mitral_annulus is None:
        return None
    points_mm, annulus_mm = _contour_to_mm(contour, pixel_spacing)
    base, tip = long_axis_endpoints(list(points_mm), annulus_mm)
    length = math.hypot(tip[0] - base[0], tip[1] - base[1])
    return length if length > 0.0 else None


def _contour_volume_ml(
    contour: Contour,
    pixel_spacing: tuple[float, float],
) -> float | None:
    points_mm, annulus_mm = _contour_to_mm(contour, pixel_spacing)
    volume = _simpson_volume_ml(points_mm, annulus_mm)
    return volume if volume > 0.0 else None


def _build_view_metrics(
    phases: dict[str, tuple[tuple[tuple[float, float], ...], tuple | None]],
    contours_by_phase: dict[str, Contour],
    pixel_spacing: tuple[float, float],
) -> LvViewMetrics | None:
    metrics = LvViewMetrics()
    has_any = False

    ed_contour = contours_by_phase.get("ed")
    if ed_contour is not None:
        length = _contour_length_mm(ed_contour, pixel_spacing)
        volume = _contour_volume_ml(ed_contour, pixel_spacing)
        if length is not None:
            metrics = dataclasses.replace(metrics, length_ed_mm=length)
            has_any = True
        if volume is not None:
            metrics = dataclasses.replace(metrics, edv_ml=volume)
            has_any = True

    es_contour = contours_by_phase.get("es")
    if es_contour is not None:
        length = _contour_length_mm(es_contour, pixel_spacing)
        volume = _contour_volume_ml(es_contour, pixel_spacing)
        if length is not None:
            metrics = dataclasses.replace(metrics, length_es_mm=length)
            has_any = True
        if volume is not None:
            metrics = dataclasses.replace(metrics, esv_ml=volume)
            has_any = True

    return metrics if has_any else None


def calculate(
    contours: tuple[Contour, ...],
    pixel_spacing: tuple[float, float] | None,
) -> LvefResult | None:
    if pixel_spacing is None:
        return None
    row_spacing, col_spacing = pixel_spacing
    if row_spacing <= 0.0 or col_spacing <= 0.0:
        return None

    grouped_contours: dict[str, dict[str, Contour]] = {"A4C": {}, "A2C": {}}
    grouped_mm: dict[str, dict[str, tuple]] = {"A4C": {}, "A2C": {}}

    for contour in contours:
        if contour.chamber.upper() != "LV":
            continue
        phase = contour.phase.casefold()
        view = contour.view.casefold().upper()
        if phase not in _VALID_PHASES or view not in _VALID_VIEWS:
            continue
        grouped_contours[view][phase] = contour
        grouped_mm[view][phase] = _contour_to_mm(contour, pixel_spacing)

    a4c = _build_view_metrics(grouped_mm["A4C"], grouped_contours["A4C"], pixel_spacing)
    a2c = _build_view_metrics(grouped_mm["A2C"], grouped_contours["A2C"], pixel_spacing)
    if a4c is None and a2c is None:
        return None

    per_view_volumes: dict[str, tuple[float, float]] = {}
    for view, metrics in (("A4C", a4c), ("A2C", a2c)):
        if metrics is None:
            continue
        if metrics.edv_ml is not None and metrics.esv_ml is not None:
            per_view_volumes[view] = (metrics.edv_ml, metrics.esv_ml)

    lvef_percent: float | None = None
    method: str | None = None
    if per_view_volumes:
        edv_ml = sum(v[0] for v in per_view_volumes.values()) / len(per_view_volumes)
        esv_ml = sum(v[1] for v in per_view_volumes.values()) / len(per_view_volumes)
        if edv_ml > 0.0:
            lvef_percent = (edv_ml - esv_ml) / edv_ml * 100.0
            method = "simpson_biplan" if len(per_view_volumes) == 2 else "simpson_monoplan"

    return LvefResult(a4c=a4c, a2c=a2c, lvef_percent=lvef_percent, method=method)
```

Add `import dataclasses` at top.

Export a public helper for overlay (same file):

```python
def format_contour_overlay(
    contour: Contour,
    pixel_spacing: tuple[float, float] | None,
) -> str:
    """Format frame overlay line: view phase · length · volume."""
    view = contour.view
    phase = contour.phase.upper()
    if pixel_spacing is None:
        return f"{view} {phase} · Длина: — · Объём: —"
    length = _contour_length_mm(contour, pixel_spacing)
    volume = _contour_volume_ml(contour, pixel_spacing)
    length_text = f"{length:.1f} mm" if length is not None else "—"
    volume_text = f"{volume:.1f} mL" if volume is not None else "—"
    return f"{view} {phase} · Длина: {length_text} · Объём: {volume_text}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_lvef_simpson.py tests/unit/test_measurement_controller.py tests/unit/test_mbs_lite_service.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/domain/calculations/lvef_simpson.py \
        tests/unit/test_lvef_simpson.py \
        tests/unit/test_measurement_controller.py \
        tests/unit/test_mbs_lite_service.py
git commit -m "feat: Simpson calculate returns partial per-view LV metrics"
```

---

### Task 3: Remove D/S phase markers from domain and application layer

**Files:**
- Modify: `src/echo_personal_tool/domain/models/viewer_state.py`
- Modify: `src/echo_personal_tool/application/state_manager.py`
- Modify: `src/echo_personal_tool/application/app_controller.py`
- Modify: `tests/unit/test_state_manager.py`
- Modify: `tests/unit/test_phase_hotkeys.py`
- Modify: `tests/unit/test_measurement_tools_panel.py`
- Modify: `tests/unit/test_measurement_panel.py`

- [ ] **Step 1: Update failing tests first**

In `test_state_manager.py`, remove `test_mark_ed_and_es_use_current_frame` and `test_clear_phase_markers_on_new_instance` marker assertions. Keep frame/playback tests; remove `ed_frame_index`/`es_frame_index` from `ViewerState` constructions.

In `test_phase_hotkeys.py`, **delete**:
- `test_viewer_widget_updates_ed_es_labels_on_state_change`
- `test_main_window_d_and_s_hotkeys_mark_phases`

In `test_measurement_tools_panel.py` and `test_measurement_panel.py`, remove `ed_frame_index`/`es_frame_index` kwargs from `ViewerState(...)`.

- [ ] **Step 2: Run tests to verify they fail on compile**

Run: `uv run pytest tests/unit/test_state_manager.py tests/unit/test_phase_hotkeys.py -v`  
Expected: FAIL — `ViewerState` unexpected keyword or missing fields

- [ ] **Step 3: Remove marker fields and methods**

`viewer_state.py` — remove `ed_frame_index` and `es_frame_index` fields.

`state_manager.py` — remove `_ed_frame_index`, `_es_frame_index`, `mark_ed()`, `mark_es()`, `clear_phase_markers()`, and their uses in `set_instance()` / `snapshot`.

`app_controller.py` — remove:
- `mark_ed()`, `mark_es()`, `go_to_ed()`, `go_to_es()`
- `_resolve_phase_for_frame()` (delete entire method)

Update `request_auto_segment()` to resolve phase without markers:

```python
def request_auto_segment(self) -> None:
    ...
    phase = None
    # Future: phase from active Simpson workflow in viewer.
    # v1: auto-segment remains non-functional without markers.
    if phase is None:
        self.status_message.emit("Auto-segmentation requires an active Simpson workflow")
        return
    ...
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_state_manager.py tests/unit/test_phase_hotkeys.py tests/unit/test_measurement_panel.py tests/unit/test_measurement_tools_panel.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/domain/models/viewer_state.py \
        src/echo_personal_tool/application/state_manager.py \
        src/echo_personal_tool/application/app_controller.py \
        tests/unit/test_state_manager.py \
        tests/unit/test_phase_hotkeys.py \
        tests/unit/test_measurement_panel.py \
        tests/unit/test_measurement_tools_panel.py
git commit -m "refactor: remove ED/ES frame markers from viewer state"
```

---

### Task 4: `MeasurementToolsPanel` — Manual + MBS groups and blink API

**Files:**
- Modify: `src/echo_personal_tool/presentation/measurement_tools_panel.py`
- Modify: `tests/unit/test_measurement_tools_panel.py`

- [ ] **Step 1: Write failing tests**

Replace `test_measurement_tools_panel_has_simpson_buttons`:

```python
def test_measurement_tools_panel_has_manual_and_mbs_buttons(qtbot) -> None:
    panel = MeasurementToolsPanel()
    qtbot.addWidget(panel)
    labels = {button.text() for button in panel.findChildren(QPushButton)}
    assert labels >= {
        "Diastole", "Systole", "EDV Auto", "ESV Auto",
        "All Diastole", "ESD Systole", "LA AP", "LAV",
    }
```

Add signal tests:

```python
def test_manual_simpson_signal_emits_view_and_phase(qtbot) -> None:
    panel = MeasurementToolsPanel()
    qtbot.addWidget(panel)
    received: list[tuple[str, str]] = []
    panel.manual_simpson_requested.connect(lambda v, p: received.append((v, p)))

    for button in panel.findChildren(QPushButton):
        if button.text() == "Diastole" and button.toolTip() == "A4C":
            button.click()
            break
    else:
        # fallback: click first Diastole and check one emission
        panel.findChildren(QPushButton)[0].click()

    assert received  # refined in implementation with objectName/tooltip
```

Better approach — store button refs and test directly:

```python
def test_manual_4c_diastole_emits_a4c_ed(qtbot) -> None:
    panel = MeasurementToolsPanel()
    qtbot.addWidget(panel)
    received: list[tuple[str, str]] = []
    panel.manual_simpson_requested.connect(lambda v, p: received.append((v, p)))
    panel._manual_buttons[("A4C", "ED")].click()
    assert received == [("A4C", "ED")]


def test_mbs_4c_edv_auto_emits_a4c_ed(qtbot) -> None:
    panel = MeasurementToolsPanel()
    qtbot.addWidget(panel)
    received: list[tuple[str, str]] = []
    panel.mbs_simpson_requested.connect(lambda v, p: received.append((v, p)))
    panel._mbs_buttons[("A4C", "ED")].click()
    assert received == [("A4C", "ED")]


def test_es_prompt_blinks_target_button(qtbot) -> None:
    panel = MeasurementToolsPanel()
    qtbot.addWidget(panel)
    button = panel._manual_buttons[("A4C", "ES")]
    panel.start_es_prompt("manual", "A4C")
    assert panel._blink_timer.isActive()
    panel.stop_es_prompt()
    assert not panel._blink_timer.isActive()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_measurement_tools_panel.py -v`  
Expected: FAIL — no `manual_simpson_requested`, no `_manual_buttons`

- [ ] **Step 3: Implement panel**

Key changes to `measurement_tools_panel.py`:

```python
from typing import Literal
from PySide6.QtCore import QTimer, Signal

class MeasurementToolsPanel(QWidget):
    manual_simpson_requested = Signal(str, str)  # view, phase
    mbs_simpson_requested = Signal(str, str)
    # keep existing lv2d/la/rv signals

    _BLINK_STYLE = "background-color: #fff59d; font-weight: bold;"
    _NORMAL_STYLE = ""

    def __init__(self, parent=None):
        ...
        self._manual_buttons: dict[tuple[str, str], QPushButton] = {}
        self._mbs_buttons: dict[tuple[str, str], QPushButton] = {}
        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(500)
        self._blink_timer.timeout.connect(self._toggle_blink)
        self._blink_target: QPushButton | None = None
        self._blink_on = False

        layout.addWidget(self._build_manual_group())
        layout.addWidget(self._build_mbs_group())
        ...

    def _build_view_column(
        self,
        view: str,
        ed_label: str,
        es_label: str,
        *,
        registry: dict[tuple[str, str], QPushButton],
        signal: Signal,
    ) -> QVBoxLayout:
        col = QVBoxLayout()
        col.addWidget(QLabel(view))
        btn_ed = QPushButton(ed_label)
        btn_ed.clicked.connect(lambda: signal.emit(view, "ED"))
        registry[(view, "ED")] = btn_ed
        col.addWidget(btn_ed)
        btn_es = QPushButton(es_label)
        btn_es.clicked.connect(lambda: signal.emit(view, "ES"))
        registry[(view, "ES")] = btn_es
        col.addWidget(btn_es)
        return col

    def _build_manual_group(self) -> QGroupBox:
        group = QGroupBox("Manual")
        row = QHBoxLayout(group)
        row.addLayout(self._build_view_column(
            "4C", "Diastole", "Systole",
            registry=self._manual_buttons,
            signal=self.manual_simpson_requested,
        ))
        row.addLayout(self._build_view_column(
            "2C", "Diastole", "Systole",
            registry=self._manual_buttons,
            signal=self.manual_simpson_requested,
        ))
        return group

    def _build_mbs_group(self) -> QGroupBox:
        group = QGroupBox("MBS")
        row = QHBoxLayout(group)
        row.addLayout(self._build_view_column(
            "4C", "EDV Auto", "ESV Auto",
            registry=self._mbs_buttons,
            signal=self.mbs_simpson_requested,
        ))
        row.addLayout(self._build_view_column(
            "2C", "EDV Auto", "ESV Auto",
            registry=self._mbs_buttons,
            signal=self.mbs_simpson_requested,
        ))
        return group

    def start_es_prompt(self, mode: Literal["manual", "mbs"], view: str) -> None:
        self.stop_es_prompt()
        mapping = {"4C": "A4C", "2C": "A2C"}
        key_view = mapping.get(view, view)
        registry = self._manual_buttons if mode == "manual" else self._mbs_buttons
        self._blink_target = registry.get((key_view if key_view in ("A4C", "A2C") else view, "ES"))
        if self._blink_target is None:
            # panel uses "4C"/"2C" labels — keys are ("4C","ES") etc.
            self._blink_target = registry.get((view, "ES"))
        if self._blink_target is not None:
            self._blink_timer.start()

    def stop_es_prompt(self) -> None:
        self._blink_timer.stop()
        if self._blink_target is not None:
            self._blink_target.setStyleSheet(self._NORMAL_STYLE)
        self._blink_target = None
        self._blink_on = False

    def _toggle_blink(self) -> None:
        if self._blink_target is None:
            return
        self._blink_on = not self._blink_on
        self._blink_target.setStyleSheet(
            self._BLINK_STYLE if self._blink_on else self._NORMAL_STYLE
        )
```

**Note:** Use consistent registry keys — recommend `("4C", "ED")` / `("2C", "ES")` in panel; emit `"A4C"`/`"A2C"` in signals via mapping in click lambdas:

```python
_VIEW_MAP = {"4C": "A4C", "2C": "A2C"}
btn_ed.clicked.connect(lambda v=view: signal.emit(_VIEW_MAP[v], "ED"))
```

Remove old `_build_simpson_group()` and `simpson_requested` signal.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_measurement_tools_panel.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/presentation/measurement_tools_panel.py \
        tests/unit/test_measurement_tools_panel.py
git commit -m "feat: split measurement panel into Manual and MBS Simpson groups"
```

---

### Task 5: `MainWindow` — coordinator and signal wiring

**Files:**
- Modify: `src/echo_personal_tool/presentation/main_window.py`
- Modify: `tests/unit/test_measurement_tools_panel.py` (integration test update)

- [ ] **Step 1: Write failing integration tests**

Replace `test_simpson_button_starts_model_contour`:

```python
def test_manual_diastole_starts_manual_contour(qtbot) -> None:
    ...
    window._on_manual_simpson_requested("A4C", "ED")
    assert window._viewer._contour_mode_kind == "manual"
    assert window._viewer._active_contour_phase == "ED"


def test_mbs_edv_auto_starts_model_contour(qtbot) -> None:
    ...
    window._on_mbs_simpson_requested("A4C", "ED")
    assert window._viewer._contour_mode_kind == "model"
```

Add ES prompt test:

```python
def test_ed_contour_completion_starts_es_prompt(qtbot) -> None:
    ...
    window._on_manual_simpson_requested("A4C", "ED")
    # complete 3-click manual contour
    window._viewer.handle_contour_click((10.0, 40.0))
    window._viewer.handle_contour_click((50.0, 40.0))
    window._viewer.handle_contour_click((30.0, 10.0))
    assert window._measurement_panel.tools._blink_timer.isActive()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_measurement_tools_panel.py -v`  
Expected: FAIL — `_on_manual_simpson_requested` not found

- [ ] **Step 3: Implement MainWindow coordinator**

Remove from `_install_shortcuts` and `_handle_key_press`:
```python
("D", self._controller.mark_ed),
("S", self._controller.mark_es),
```

Replace `_wire_measurement_tools`:

```python
def _wire_measurement_tools(self) -> None:
    tools = self._measurement_panel.tools
    tools.manual_simpson_requested.connect(self._on_manual_simpson_requested)
    tools.mbs_simpson_requested.connect(self._on_mbs_simpson_requested)
    tools.manual_simpson_requested.connect(self._on_es_button_pressed)
    tools.mbs_simpson_requested.connect(self._on_es_button_pressed)
    # keep lv2d/la/rv connections
```

Add handlers:

```python
def _on_manual_simpson_requested(self, view: str, phase: str) -> None:
    if self._view_mode != "2d":
        self._show_status("Switch to 2D view for Simpson contour")
        return
    if phase == "ED":
        self._measurement_panel.tools.stop_es_prompt()
    if self._viewer.start_contour(phase=phase, view=view):
        self._viewer.clear_frame_overlay()
        self._viewer.append_frame_overlay(
            f"Manual {view} {phase}: MA septal → lateral → apex"
        )
        self._show_status(
            f"Manual Simpson {view} {phase}: click MA septal, lateral, apex"
        )
    else:
        self._show_status("Load a frame first or cancel the active tool (Esc)")

def _on_mbs_simpson_requested(self, view: str, phase: str) -> None:
    if self._view_mode != "2d":
        self._show_status("Switch to 2D view for MBS-lite")
        return
    if phase == "ED":
        self._measurement_panel.tools.stop_es_prompt()
    if self._viewer.start_model_contour(phase=phase, view=view):
        self._viewer.clear_frame_overlay()
        self._viewer.append_frame_overlay(
            f"MBS-lite {view} {phase}: MA septal → lateral → apex"
        )
        self._show_status(
            f"MBS-lite {view} {phase}: click MA septal, lateral, apex"
        )
    else:
        self._show_status("Load a frame first or cancel the active tool (Esc)")

def _on_es_button_pressed(self, view: str, phase: str) -> None:
    if phase == "ES":
        self._measurement_panel.tools.stop_es_prompt()
```

Extend `_on_contour_completed`:

```python
def _on_contour_completed(self, contour: object) -> None:
    if not isinstance(contour, Contour):
        return
    # existing LAV workflow ...
    if contour.chamber.upper() != "LV":
        return

    pixel_spacing = (
        self._controller.state_manager.snapshot.instance.pixel_spacing
        if self._controller.state_manager.snapshot.instance is not None
        else None
    )
    from echo_personal_tool.domain.calculations.lvef_simpson import format_contour_overlay
    self._viewer.clear_frame_overlay()
    self._viewer.append_frame_overlay(format_contour_overlay(contour, pixel_spacing))

    if contour.phase.upper() == "ED":
        mode = "mbs" if contour.source == "model" else "manual"
        view_label = "4C" if contour.view.upper() == "A4C" else "2C"
        es_name = "ESV Auto" if mode == "mbs" else "Systole"
        self._viewer.append_frame_overlay(
            f"Перейдите на кадр систолы и нажмите {es_name} ({view_label})"
        )
        self._measurement_panel.tools.start_es_prompt(mode, view_label)
        self._show_status(
            f"Перейдите на кадр систолы и нажмите {es_name} ({view_label})"
        )
    elif contour.phase.upper() == "ES":
        self._measurement_panel.tools.stop_es_prompt()
```

Stop blink on Esc / instance change — extend `_cancel_active_tool` and `_on_instance_selected`:

```python
def _cancel_active_tool(self) -> None:
    self._measurement_panel.tools.stop_es_prompt()
    self._viewer.cancel_active_tool()
```

Delete `_on_simpson_requested`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_measurement_tools_panel.py tests/unit/test_phase_hotkeys.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/presentation/main_window.py \
        tests/unit/test_measurement_tools_panel.py
git commit -m "feat: wire Manual/MBS Simpson workflows with ED→ES prompt coordinator"
```

---

### Task 6: `ViewerWidget` — remove markers, fix phase default, overlay on drag

**Files:**
- Modify: `src/echo_personal_tool/presentation/viewer_widget.py`
- Modify: `tests/unit/test_phase_hotkeys.py` (if needed)

- [ ] **Step 1: Write failing test**

Add to `tests/unit/test_contour.py` or `test_measurement_tools_panel.py`:

```python
def test_resolve_contour_phase_defaults_to_ed_without_markers(qtbot) -> None:
    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    viewer.set_state(ViewerState(
        instance=None, current_frame_index=3, total_frames=10,
        frame_time_ms=33.3, is_playing=False,
    ))
    assert viewer._resolve_contour_phase() == "ED"
```

- [ ] **Step 2: Run test — expect FAIL** if markers still referenced

- [ ] **Step 3: Implement viewer changes**

Remove `_ed_label`, `_es_label` creation and `wl_row` additions.

In `set_state`, delete ED/ES label updates (lines using `ed_frame_index`/`es_frame_index`).

Simplify `_update_timeline_indicator`:

```python
def _update_timeline_indicator(self, viewer_state: ViewerState) -> None:
    self._timeline_slider.setToolTip("")
    self._timeline_slider.setStyleSheet("")
```

Replace `_resolve_contour_phase`:

```python
def _resolve_contour_phase(self) -> str:
    return "ED"
```

In `_finish_model_contour`, `_finish_manual_contour`, `finish_contour` — replace text-only overlay with `format_contour_overlay` (import from `lvef_simpson`). Keep `contour_completed.emit`.

In `_finalize_contour_point_drag`, after `contours_changed.emit`, update overlay for current-frame LV contour:

```python
if contour.chamber.upper() == "LV" and contour.frame_index == self._contour_frame_index():
    self.clear_frame_overlay()
    spacing = self._current_state.instance.pixel_spacing if self._current_state and self._current_state.instance else None
    self.append_frame_overlay(format_contour_overlay(contour, spacing))
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_contour.py tests/unit/test_phase_hotkeys.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/presentation/viewer_widget.py \
        tests/unit/test_contour.py
git commit -m "refactor: remove ED/ES viewer markers and add numeric contour overlay"
```

---

### Task 7: `MeasurementPanel` — Russian per-view labels

**Files:**
- Modify: `src/echo_personal_tool/presentation/measurement_panel.py`
- Modify: `tests/unit/test_measurement_panel.py`

- [ ] **Step 1: Write failing tests**

```python
def test_measurement_panel_shows_russian_lv_metrics_partial_ed(qtbot) -> None:
    panel = MeasurementPanel()
    qtbot.addWidget(panel)
    panel.set_measurement_snapshot(MeasurementSnapshot(
        lvef=LvefResult(
            a4c=LvViewMetrics(length_ed_mm=82.3, edv_ml=124.5),
        ),
    ))
    text = panel._summary_label.text()
    assert "Объёмы ЛЖ (Симпсон)" in text
    assert "Длина ЛЖ 4C" in text
    assert "КДО ЛЖ 4C" in text
    assert "КСО ЛЖ 4C" not in text
    assert "ФВ ЛЖ" not in text


def test_measurement_panel_shows_lvef_when_ed_es_pair_complete(qtbot) -> None:
    panel = MeasurementPanel()
    qtbot.addWidget(panel)
    panel.set_measurement_snapshot(MeasurementSnapshot(
        lvef=LvefResult(
            a4c=LvViewMetrics(
                length_ed_mm=82.0, length_es_mm=78.0,
                edv_ml=120.0, esv_ml=45.0,
            ),
            lvef_percent=62.5,
            method="simpson_monoplan",
        ),
    ))
    text = panel._summary_label.text()
    assert "КСО ЛЖ 4C" in text
    assert "ФВ ЛЖ" in text
    assert "62.5" in text
```

Update `test_measurement_panel_displays_computed_snapshot` to new `LvefResult` shape and Russian strings.

- [ ] **Step 2: Run tests — expect FAIL**

Run: `uv run pytest tests/unit/test_measurement_panel.py -v`

- [ ] **Step 3: Implement `_format_lvef_section`**

```python
def _format_lvef_section(self, snapshot: MeasurementSnapshot | None) -> list[str]:
    lvef = snapshot.lvef if snapshot is not None else None
    if lvef is None:
        return []

    lines = ["Объёмы ЛЖ (Симпсон)"]

    def append_view(view_label: str, metrics: LvViewMetrics | None) -> None:
        if metrics is None:
            return
        length = metrics.length_ed_mm if metrics.length_ed_mm is not None else metrics.length_es_mm
        length_line = self._optional_line(f"Длина ЛЖ {view_label}", length, " mm")
        if length_line:
            lines.append(length_line)
        kdo = self._optional_line(f"КДО ЛЖ {view_label}", metrics.edv_ml, " mL")
        if kdo:
            lines.append(kdo)
        kso = self._optional_line(f"КСО ЛЖ {view_label}", metrics.esv_ml, " mL")
        if kso:
            lines.append(kso)

    append_view("4C", lvef.a4c)
    append_view("2C", lvef.a2c)

    if lvef.lvef_percent is not None:
        lines.append(self._line("ФВ ЛЖ", lvef.lvef_percent, " %"))
    if lvef.method is not None:
        lines.append(f"  Метод: {lvef.method}")

    return lines if len(lines) > 1 else []
```

Import `LvViewMetrics` from domain models.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_measurement_panel.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/presentation/measurement_panel.py \
        tests/unit/test_measurement_panel.py
git commit -m "feat: show Russian per-view LV Simpson metrics in measurement panel"
```

---

### Task 8: Full test sweep and ruff

**Files:**
- Modify: any remaining tests referencing `ed_frame_index`, `LvefResult.edv_ml`, `simpson_requested`

- [ ] **Step 1: Grep for stale references**

Run:
```bash
rg 'ed_frame_index|es_frame_index|simpson_requested|LvefResult\(|\.edv_ml' tests src --glob '*.py'
```

Fix every hit.

- [ ] **Step 2: Run full unit suite**

Run:
```bash
uv run pytest tests/unit -q
uv run ruff check src tests
```

Expected: all PASS, no ruff errors

- [ ] **Step 3: Commit any remaining fixes**

```bash
git add -A
git commit -m "test: update suite for Simpson dual workflow and removed phase markers"
```

---

## Manual verification checklist

1. Load cine with pixel spacing → Manual 4C Diastole → 3 clicks → orange contour → panel: `Длина ЛЖ 4C`, `КДО ЛЖ 4C` → Systole (4C) blinks.
2. Step to ES frame → Systole → panel adds `КСО ЛЖ 4C`, `ФВ ЛЖ`.
3. MBS 4C EDV Auto → green contour → `ESV Auto` blinks.
4. `D` / `S` do nothing; no ED/ES labels on timeline.
5. 2C buttons independent from 4C.
6. Frame overlay shows `A4C ED · Длина: … · Объём: …` (no area).

---

## Spec coverage self-review

| Spec requirement | Task |
|------------------|------|
| Manual + MBS panel layout | Task 4 |
| Manual → `start_contour`, MBS → `start_model_contour` | Task 5 |
| ED→ES hint + blink | Task 5 |
| Remove D/S markers | Task 3, 6 |
| Partial measurements after ED | Task 2 |
| Russian labels, no area | Task 7, overlay Task 2/6 |
| `I` deferred | Task 3 (message only) |
| Frame overlay numeric metrics | Task 2, 5, 6 |
