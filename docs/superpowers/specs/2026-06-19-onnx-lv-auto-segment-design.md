# ONNX LV Auto-Segment (A4C Simpson) — Design Spec

**Date:** 2026-06-19  
**Status:** Approved  
**Scope:** LV Auto group only (A4C monoplane ED/ES). Left Ventricle manual workflow unchanged.

## Goal

Deliver production-quality automatic LV endocardial contours for **Simpson monoplane A4C** EF and volumes via ONNX (EchoNet cavity segmentation), with ASE-compliant papillary muscle exclusion and hybrid review UX.

**In scope:** A4C ED + ES from **LV Auto** buttons; blood–endocardium boundary; papillary concavity removal; hybrid verify-before-accept.  
**Out of scope:** myocardial wall thickness; A2C auto-segment; Left Ventricle manual contours; ONNX fine-tune; temporal ED→ES propagation.

## Background

| Layer | Current state |
|-------|---------------|
| Model | `echonet_seg_resnet50.onnx` — DeepLabV3-ResNet50, 112×112, binary LV cavity logits |
| Inference | `OnnxInferenceEngine` + `OnnxWorker` (subprocess, 2s timeout) |
| Post-process | mask → contour → smooth 32 nodes → `closed_polygon_to_open_arc` (longest chord = annulus) |
| UI entry | System bar `I` + `AUTO_SEGMENT`; LV Auto buttons still use MBS-lite 3-click (`MBS_SIMPSON`) |
| Gap | No ASE papillary exclusion; auto-segment not wired to LV Auto buttons; no review gate before Simpson |

## Workflow isolation

### Left Ventricle (manual) — **no changes**

| Property | Value |
|----------|-------|
| Menu group | `Left Ventricle` |
| Action | `MANUAL_SIMPSON` |
| Mechanism | `start_contour` → 3 clicks (septal → lateral → apex) |
| `source` | `"manual"` |
| Refine | R-refine, magnetic snap, drag — existing behavior |

### LV Auto (ONNX v1)

| Property | Value |
|----------|-------|
| Menu group | `LV Auto` |
| Buttons (v1 active) | `LVEF Simpson EDV`, `LVEF Simpson ESV` (A4C only) |
| Buttons (v1 disabled) | `Simpson Biplane EDV/ESV` — tooltip: «A2C auto — в следующей версии» |
| Action | `MBS_SIMPSON` → **replaced** by ONNX auto-segment (no 3-click) |
| `source` | `"ai"` |
| Hotkey `I` / System bar | Only when LV Auto session active (`set_simpson_workflow_context` after EDV/ESV Auto press) |

### LV Auto flow

```
User: LV Auto → «LVEF Simpson EDV» (A4C, ED)
  → set_simpson_workflow_context(phase=ED, view=A4C, chamber=LV)
  → request_auto_segment()
  → [background] ONNX pipeline (below)
  → Contour(source="ai", review_pending=True)
  → overlay: «Проверьте контур (ASE) · R — уточнить · Enter — принять»
  → user: R / drag (optional)
  → Enter → review_pending=False → lvef_simpson.calculate() monoplan A4C
  → blink «LVEF Simpson ESV» in LV Auto group
```

Repeat for ES on ES frame. Manual Left Ventricle path never calls ONNX.

### Contour coexistence

- One contour per `(chamber, view, phase)` in state; auto-segment replaces existing `source="ai"` for same key.
- Manual contours (`source="manual"`) are never modified by auto pipeline.
- `lvef_simpson.calculate()` ignores contours with `review_pending=True`.
- Accepted contours: `source in {"manual", "ai"}`; legacy `source="model"` still supported for old sessions.

## Pipeline architecture

```
[frame A4C ED/ES]
    → prepare_tensor (per-frame norm v1; fixed train mean/std v1.1 when calibrated)
    → OnnxInferenceEngine.segment → mask
    → papillary_mask_cleanup(mask)              # NEW
    → mask_to_contour → smooth_contour(32)
    → closed_polygon_to_open_arc
    → exclude_papillary_concavities(arc)        # NEW — ASE
    → smooth_open_arc (light, existing)
    → [optional] refine_open_arc (ai config)    # manifest flag, default on
    → Contour(source="ai", review_pending=True)
    → user review → accept
    → Simpson monoplan A4C
```

### New domain functions

**File:** `domain/services/segmentation_service.py`

```python
def papillary_mask_cleanup(
    mask: np.ndarray,
    *,
    long_axis_hint: tuple[tuple[float, float], tuple[float, float]] | None = None,
) -> np.ndarray: ...


def exclude_papillary_concavities(
    open_points: list[tuple[float, float]],
    annulus: tuple[tuple[float, float], tuple[float, float]],
    apex: tuple[float, float],
    *,
    depth_threshold_ratio: float = 0.04,
    min_depth_px: float = 2.0,
) -> list[tuple[float, float]]: ...
```

## ASE papillary exclusion

Clinical rule (ASE Simpson): contour along blood–endocardium interface; **exclude papillary muscle indentations** in the mid-cavity (smooth outward).

### Step A — mask cleanup

1. Derive long axis from mask bounding box (MA ≈ top of mask, apex ≈ bottom centroid) if `long_axis_hint` absent.
2. Oriented morphological **closing** with elliptical SE aligned to long axis.
   - SE length ≈ `clamp(0.04 × axis_length, 5, 15)` px at mask resolution (before upscale).
3. Keep largest connected component.
4. Upscale to original frame size (existing `_upscale_mask`).

### Step B — open-arc concavity fill

1. Fix MA endpoints (septal, lateral); identify apex as farthest interior node from MA chord.
2. For each interior node (not MA endpoints):
   - Signed perpendicular distance to MA–apex chord (inward = negative).
   - If `depth < -threshold` where `threshold = max(min_depth_px, depth_threshold_ratio × MA_length)`:
     - Project node onto chord line (or local spline envelope of neighbors).
3. Light `smooth_open_arc` (4–8 iterations, existing constants).
4. Optional auto R-refine via `refine_open_arc_contour` with `active_contour_config_for_source("ai")`.

## Preprocessing (ONNX input)

### v1 — keep per-frame normalization

- `prepare_tensor`: per-channel mean/std per frame (current behavior).
- Document in manifest `preprocessing.normalization_mode: per_frame` as v1 default.

### v1.1 — fixed EchoNet train stats (deferred)

- When Tier-1 DICOM calibration completes, switch to `fixed_mean` / `fixed_std` from manifest.
- Fallback to per-frame if null.

### Input constraints

- Grayscale H×W or RGB H×W×3 from current frame pixels (window/level applied display buffer).
- Resize 112×112 cubic (existing `ndimage.zoom` order=3).

## Data model

**File:** `domain/models/contour.py`

```python
@dataclass
class Contour:
    ...
    review_pending: bool = False  # meaningful only when source="ai"
```

**File:** `domain/calculations/lvef_simpson.py`

- Skip contours where `review_pending is True`.
- v1 monoplan: require accepted A4C ED + A4C ES (`source="ai"` or manual if user mixed workflows — last accepted wins per key).

## UX review (hybrid C)

| State | Behavior |
|-------|----------|
| `review_pending=True` | Contour visible (AI pen color, distinct from manual orange); **no Simpson volumes in panel/overlay results** |
| `R` | Gradient refine; stays pending |
| Drag nodes | Existing AI contour edit |
| `Enter` | Accept → `review_pending=False` → recompute measurements |
| `Esc` | Discard AI contour for active phase; status prompts re-run EDV/ESV Auto |

**Status after segment:**
> `A4C ED: проверьте контур (ASE, без папиллярных мышц) · R — уточнить · Enter — принять`

**Pen colors:** keep manual orange / legacy model green; AI contour uses dedicated color (e.g. cyan or existing AI styling in `viewer_widget`).

## Error handling

| Condition | UX |
|-----------|-----|
| Playback active | «Pause playback before auto-segmentation» |
| No LV Auto context (phase not ED/ES) | «Выберите LV Auto → EDV/ESV» |
| View ≠ A4C in v1 | A2C buttons disabled; if forced: «A2C auto — в следующей версии» |
| Frame not loaded | «Current frame is not loaded yet» |
| onnxruntime / model missing | «Сегментация недоступна — используйте ручной контур» (manual LV unaffected) |
| Segmentation in progress | «Segmentation already in progress» |
| Timeout (2s) | «Сегментация: таймаут — повторите или используйте ручной контур» |
| Empty mask / no contour | «Сегментация не нашла контур — используйте ручной контур» |
| Open-arc conversion failed | «Сегментация: не удалось построить open arc» |
| Stale frame (user changed frame during inference) | Silent discard (existing `_auto_segment_context_matches`) |
| No pixel spacing | Panel/overlay show «—»; status warn once (existing) |
| Accept without spacing | Allow contour storage; Simpson volumes omitted until spacing available |

## Files to change

| File | Change |
|------|--------|
| `domain/services/segmentation_service.py` | `papillary_mask_cleanup`, `exclude_papillary_concavities` |
| `domain/models/contour.py` | `review_pending` field |
| `domain/calculations/lvef_simpson.py` | Skip pending; document monoplan A4C auto path |
| `application/app_controller.py` | Wire papillary steps in `_on_auto_segment_finished`; LV Auto-only gating |
| `presentation/main_window.py` | `_on_mbs_simpson_requested` A4C → auto-segment; Enter accept; disable A2C LV Auto |
| `presentation/measures_menu.py` | Disable biplane LV Auto buttons + tooltips |
| `presentation/viewer_widget.py` | Review-pending styling; accept gesture |
| `presentation/system_bar.py` | `I` enabled only in LV Auto session |
| `models/model_manifest.json` | `inference.auto_refine_after_segment: true` (optional flag) |
| `tests/unit/test_segmentation_service.py` | Papillary synthetic tests |
| `tests/unit/test_auto_segment_controller.py` | LV Auto gating, review_pending, accept flow |
| `tests/unit/test_lvef_simpson.py` | Ignore `review_pending` |
| `tests/unit/test_measures_menu.py` | A2C LV Auto disabled |
| `tests/unit/test_phase_hotkeys.py` | `I` only in LV Auto session |

**Untouched:** `start_contour`, manual magnetic snap, `contour_edge_snap` manual config, MBS-lite for manual path.

## Testing

### Unit (synthetic)

```bash
uv run pytest tests/unit/test_segmentation_service.py \
  tests/unit/test_auto_segment_controller.py \
  tests/unit/test_lvef_simpson.py \
  tests/unit/test_measures_menu.py \
  tests/unit/test_phase_hotkeys.py -q
uv run ruff check src tests
```

| Test | Assert |
|------|--------|
| Mask with papillary notch | `papillary_mask_cleanup` reduces concavity count |
| Open arc with inward bump | `exclude_papillary_concavities` removes bump; MA endpoints fixed |
| `review_pending=True` | `calculate()` returns None or omits that phase volume |
| Accept flow | `review_pending=False` → EDV/ESV computed |
| LV Auto EDV press | `request_auto_segment` started, not `start_model_contour` |
| Manual LV EDV press | `start_contour` only, no ONNX |
| `I` hotkey | Calls segment only when LV Auto context set |

### Manual checklist

1. DICOM A4C cine with spacing → LV Auto EDV on ED frame → AI contour + review prompt → Enter → `КДО ЛЖ 4C` in panel.
2. Step to ES → LV Auto ESV → accept → `КСО ЛЖ 4C`, `ФВ ЛЖ` monoplan.
3. R-refine before accept updates contour; volumes update only after Enter.
4. Left Ventricle manual EDV → 3-click orange contour; no ONNX; magnetic snap works.
5. `I` does nothing outside LV Auto session.
6. LV Auto Biplane buttons disabled with tooltip.
7. Clip with visible papillary muscles → contour smooths mid-cavity (visual ASE check).

## Phased delivery

| Phase | Content | Status |
|-------|---------|--------|
| **v1** | LV Auto A4C ONNX + papillary post-process + review UX; disable A2C auto | ✅ Done (see `ROADMAP.md`) |
| **v1.1** | Fixed train mean/std; improved annulus from mask geometry | [ ] Planned |
| **v2** | A2C auto (separate model or validated EchoNet transfer) | [ ] Planned |

## Verification note

Accuracy vs reference EF is **not** a release gate for v1; gate is correct pipeline wiring, ASE post-process unit tests, and manual checklist on representative A4C clips.
