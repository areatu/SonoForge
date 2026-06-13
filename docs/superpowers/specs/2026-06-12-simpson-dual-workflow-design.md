# Simpson Dual Workflow Design Spec

**Date:** 2026-06-12  
**Status:** Approved (pending user review of written spec)

## Goal

Provide two parallel LV Simpson measurement workflows (Manual and MBS-lite) with explicit phase/view buttons, ED→ES guided transitions (status hint + blinking ES button), removal of D/S frame markers, and per-view Russian measurement labels in the results panel.

## Background

MBS-lite v1 ([2026-06-12-mbs-lite-design.md](./2026-06-12-mbs-lite-design.md)) implemented 3-click model contours and Simpson volume pipeline. The measurement tools panel currently has a single Simpson group where **Diastole/Systole both incorrectly call `start_model_contour`** (MBS-lite). Frame markers D/S (`ed_frame_index` / `es_frame_index`) are wired but the user workflow no longer needs them.

### Why measurements do not appear today

Code audit (current behavior):

| Layer | Behavior | Gap |
|-------|----------|-----|
| `ViewerWidget.set_contour_from_domain` | Emits `contours_changed` on contour complete/edit | OK |
| `AppController.on_contours_changed` | Stores contours, calls `_recompute_measurements()` | OK |
| `lvef_simpson.calculate` | Returns `LvefResult` **only when both ED and ES contours exist for the same view** | No partial results after ED alone |
| `lvef_simpson.calculate` | Requires `pixel_spacing` from loaded instance | Returns `None` if spacing missing |
| `MeasurementPanel._format_lvef_section` | Shows aggregate `EDV` / `ESV` / `LVEF` / `Method` only | No per-view labels, no length, English labels |
| Frame overlay | Shows contour completion text, not numeric metrics | No length/volume on overlay |

**Root cause for “nothing in Measurements”:** user completes only ED contour, or lacks pixel spacing — `calculate()` returns `None`, panel shows “No measurements yet”.

This spec fixes partial display and adds per-view Russian terminology.

## Architecture

```
MeasurementToolsPanel
  ├─ Manual group  → manual_simpson_requested(view, phase)
  └─ MBS group     → mbs_simpson_requested(view, phase)

MainWindow (coordinator)
  ├─ wires panel signals → ViewerWidget.start_contour / start_model_contour
  ├─ on contour_completed (LV, phase=ED) → status/overlay hint + panel.start_es_prompt(mode, view)
  ├─ on ES button press / ES contour complete → panel.stop_es_prompt()
  └─ existing contours_changed → AppController → recompute

AppController._recompute_measurements
  └─ lvef_simpson (extended) → MeasurementSnapshot.lvef with per-view metrics

MeasurementPanel
  └─ _format_lvef_section → Russian per-view lines + aggregate LVEF
```

**Coordinator choice:** `MainWindow` owns ED→ES workflow transitions; `MeasurementToolsPanel` owns button blink animation (QTimer ~500 ms, highlight style toggle).

## UI: Measurement Tools Panel

Replace the single Simpson `QGroupBox` with two sub-groups.

### Block 1 — Manual

```
┌─ Manual ─────────────────────────┐
│         4C          2C           │
│      Diastole    Diastole        │
│      Systole     Systole         │
└──────────────────────────────────┘
```

| Button | Signal | Viewer action |
|--------|--------|---------------|
| 4C Diastole | `manual_simpson_requested("A4C", "ED")` | `start_contour(phase="ED", view="A4C")` |
| 4C Systole | `manual_simpson_requested("A4C", "ES")` | `start_contour(phase="ES", view="A4C")` |
| 2C Diastole | `manual_simpson_requested("A2C", "ED")` | `start_contour(phase="ED", view="A2C")` |
| 2C Systole | `manual_simpson_requested("A2C", "ES")` | `start_contour(phase="ES", view="A2C")` |

Contour: orange (`source="manual"`). 3 clicks: MA septal → lateral → apex → node edit.

### Block 2 — MBS

```
┌─ MBS ────────────────────────────┐
│         4C          2C           │
│     EDV Auto     EDV Auto        │
│     ESV Auto     ESV Auto        │
└──────────────────────────────────┘
```

| Button | Signal | Viewer action |
|--------|--------|---------------|
| 4C EDV Auto | `mbs_simpson_requested("A4C", "ED")` | `start_model_contour(phase="ED", view="A4C")` |
| 4C ESV Auto | `mbs_simpson_requested("A4C", "ES")` | `start_model_contour(phase="ES", view="A4C")` |
| 2C EDV Auto | `mbs_simpson_requested("A2C", "ED")` | `start_model_contour(phase="ED", view="A2C")` |
| 2C ESV Auto | `mbs_simpson_requested("A2C", "ES")` | `start_model_contour(phase="ES", view="A2C")` |

Contour: green (`source="model"`). Same 3-click landmarks; `fit_contour_from_landmarks` warp. Future gradient snap / refinement hooks stay in MBS path (out of scope here).

### Keyboard shortcuts (unchanged)

| Key | Action |
|-----|--------|
| `C` | Manual contour on current frame; phase/view not preset (legacy shortcut) |
| `M` | MBS-lite on current frame; phase/view not preset |
| `Esc` | Cancel active tool; stop ES prompt blink |

Remove `D` / `S` shortcuts (see Phase markers removal).

### ES prompt blink

`MeasurementToolsPanel` API:

- `start_es_prompt(mode: Literal["manual", "mbs"], view: str) -> None` — blink target button (Systole or ESV Auto for given view in matching block)
- `stop_es_prompt() -> None` — clear timer and restore button style

**Start blink when:** `contour_completed` with `chamber="LV"`, `phase="ED"`, and completion originated from the matching workflow (manual `source="manual"` → blink Manual Systole; model `source="model"` → blink MBS ESV Auto).

**Stop blink when:**

- User presses the target ES button (same mode + view)
- User completes ES contour (same mode + view)
- User presses `Esc` or loads a different instance
- User starts a new ED measurement in the **same** block+view (replaces pending prompt)

Blink does not block other tools or views.

## Workflow ED → ES

Shared sequence for both Manual and MBS:

1. User selects frame on timeline (no auto-jump).
2. User presses ED button (Diastole / EDV Auto) for desired view.
3. Three clicks: MA septal → lateral → apex.
4. Contour appears; user may drag nodes (equal arc-length resample).
5. Metrics update (overlay + panel — see Measurements).
6. Status bar + frame overlay hint:
   - Manual 4C: *«Перейдите на кадр систолы и нажмите Systole (4C)»*
   - MBS 4C: *«Перейдите на кадр систолы и нажмите ESV Auto (4C)»*
   - (Analogous for 2C.)
7. Corresponding ES button blinks.
8. User steps to systole frame, presses ES button, repeats steps 3–5.

4C and 2C are independent. Manual and MBS workflows are independent (separate contour sets distinguished by `source` for display; see Contour identity).

## Phase markers removal (D / S)

Remove entirely:

| Item | Location |
|------|----------|
| `ed_frame_index`, `es_frame_index` | `ViewerState` |
| `mark_ed()`, `mark_es()`, `clear_phase_markers()` | `StateManager` |
| `mark_ed()`, `mark_es()`, `go_to_ed()`, `go_to_es()` | `AppController` |
| `_resolve_phase_for_frame()` | `AppController` (auto-segment; deferred) |
| `_resolve_contour_phase()` fallback to markers | `ViewerWidget` |
| `D` / `S` shortcuts | `MainWindow` |
| ED/ES timeline labels (`_ed_label`, `_es_label`) | `ViewerWidget` |

**Phase resolution rule:** phase comes only from the button that started the workflow (`phase` argument to `start_contour` / `start_model_contour`). Shortcuts `C` / `M` without a panel button default phase to `"ED"` if not otherwise set.

## Contour identity and storage

Upsert key: `(chamber="LV", view, phase)` — re-measuring the same view+phase replaces the previous contour (updates `frame_index` and `source`).

`lvef_simpson.calculate` groups by `view` + `phase`; last contour in state for a slot wins (unchanged iteration order).

Manual and MBS contours for the same view+phase cannot coexist — the later measurement replaces. User is expected to pick one workflow per session.

## Measurements

### Per-contour metrics (domain)

For each LV open-arc contour with `mitral_annulus` and valid `pixel_spacing`:

| Metric | Computation |
|--------|-------------|
| Length (mm) | Distance MA midpoint → apex (`long_axis_endpoints`) |
| Volume (mL) | Single-plane Simpson 20-disk (`_simpson_volume_ml`) for that contour |

**Area is not shown** in panel or overlay (removed from results per user request).

### Extended `LvefResult` (or companion dataclass)

Add per-view optional fields populated as contours become available:

```python
@dataclass(frozen=True)
class LvViewMetrics:
    length_ed_mm: float | None = None   # from ED contour
    length_es_mm: float | None = None   # from ES contour
    edv_ml: float | None = None         # КДО — ED contour volume
    esv_ml: float | None = None         # КСО — ES contour volume

@dataclass(frozen=True)
class LvefResult:
    a4c: LvViewMetrics | None = None
    a2c: LvViewMetrics | None = None
    lvef_percent: float | None = None   # aggregate when computable
    method: str | None = None           # simpson_monoplan / simpson_biplan
```

`calculate()` returns `LvefResult` when **at least one** LV contour exists (partial OK). `lvef_percent` and `method` set only when both ED and ES exist for at least one view (existing mono/biplane averaging logic).

### Panel labels (Russian)

Section header: **«Объёмы ЛЖ (Симпсон)»**

Per view (show line only when value is available):

| Label | Source |
|-------|--------|
| `Длина ЛЖ 4C` | `a4c.length_ed_mm` if ED done, else `a4c.length_es_mm` |
| `КДО ЛЖ 4C` | `a4c.edv_ml` |
| `КСО ЛЖ 4C` | `a4c.esv_ml` |
| `Длина ЛЖ 2C` | `a2c.length_ed_mm` if ED done, else `a2c.length_es_mm` |
| `КДО ЛЖ 2C` | `a2c.edv_ml` |
| `КСО ЛЖ 2C` | `a2c.esv_ml` |

Aggregate (when computable):

| Label | Source |
|-------|--------|
| `ФВ ЛЖ` | `lvef_percent` (%) |
| `Метод` | `method` |

**Length display rule:** prefer ED-phase length when ED contour exists; otherwise show ES-phase length. If both exist, ED length is shown (clinical default for LV length). Future enhancement: show both — out of scope.

### Frame overlay (current frame)

On contour complete and on node-drag finalize for the active frame, show:

```
A4C ED · Длина: 82.3 mm · Объём: 124.5 mL
```

No area. Overlay clears on frame change (existing behavior).

## Auto-segmentation (`I`)

**Out of scope for this implementation.** Currently non-functional in practice. Future spec: `I` works only inside an active Simpson contour session; phase from the button that started the session (answer C from brainstorming).

No changes to `request_auto_segment()` in this release beyond removing `_resolve_phase_for_frame` dependency on markers.

## Files to change

| File | Change |
|------|--------|
| `presentation/measurement_tools_panel.py` | Two sub-groups, new signals, blink API |
| `presentation/main_window.py` | Coordinator, wire new signals, ES prompt on `contour_completed`, remove D/S |
| `presentation/viewer_widget.py` | Remove ED/ES labels; phase from button only |
| `presentation/measurement_panel.py` | Russian per-view LV section |
| `application/app_controller.py` | Remove mark_ed/es, go_to_ed/es |
| `application/state_manager.py` | Remove ed/es frame fields and mark methods |
| `domain/models/viewer_state.py` | Remove ed_frame_index, es_frame_index |
| `domain/models/measurements.py` | Add `LvViewMetrics`, extend `LvefResult` |
| `domain/calculations/lvef_simpson.py` | Partial results, per-view length/volume |
| `domain/services/contour_geometry.py` | (if needed) export long-axis length helper |
| `tests/unit/test_measurement_tools_panel.py` | Panel layout, signals, blink |
| `tests/unit/test_phase_hotkeys.py` | Remove or replace D/S tests |
| `tests/unit/test_state_manager.py` | Remove mark_ed/es tests |
| `tests/unit/test_lvef_simpson.py` | Partial + per-view metrics |
| `tests/unit/test_measurement_panel.py` | Russian labels, partial ED display |

## Out of scope

- MBS-lite gradient snap / border refinement (v1.1)
- Auto-segmentation (`I`) implementation
- Separate A2C shape template
- Temporal ED→ES propagation
- LA/RV measurement changes
- Area display anywhere in LV results

## Error handling

| Condition | UX |
|-----------|-----|
| No frame loaded | Status: «Load a frame first» |
| Active tool in progress | Status: «Cancel active tool (Esc)» |
| No pixel spacing | Panel: per-view lines omitted; overlay shows «—» for numeric values; status warns once |
| Invalid landmarks (MBS) | 3-click rejected; user retries |
| 2D view not active | Status: «Switch to 2D view for Simpson» |

## Testing

```bash
uv run pytest tests/unit/test_measurement_tools_panel.py \
  tests/unit/test_lvef_simpson.py \
  tests/unit/test_measurement_panel.py \
  tests/unit/test_state_manager.py \
  tests/unit/test_phase_hotkeys.py -q
uv run ruff check src tests
```

**Manual checklist:**

1. Load cine with pixel spacing → Manual 4C Diastole on ED frame → 3 clicks → orange contour → panel shows `Длина ЛЖ 4C`, `КДО ЛЖ 4C`; Systole (4C) blinks.
2. Step to ES frame → Systole → orange ES contour → panel adds `КСО ЛЖ 4C`, `ФВ ЛЖ`.
3. MBS 4C EDV Auto → green contour → `ESV Auto (4C)` blinks; same ED→ES flow.
4. `D` / `S` do nothing; timeline has no ED/ES markers.
5. 2C buttons work independently from 4C.

## Verification note

Tests are not run by the agent per project rules; user runs the commands above.
