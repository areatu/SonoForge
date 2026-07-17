# LV Auto Temporal Fusion — Neighbor-Aware Contour on Frame N

**Date:** 2026-07-05  
**Status:** Approved (brainstorming)  
**Depends on:** `2026-07-05-lv-auto-onnx-quality-design.md` (v1.5 per-frame pipeline)  
**Scope:** Improve **contour shape** on user-selected frame **N** using neighbors **N±2**, without changing `frame_index`. Annulus endpoints fused with small δ.

---

## Goal

When ED/ES boundary is ambiguous on a **static frame** (weak gradient, blur, papillary noise), use **temporal context** from ±2 neighboring frames to produce a **more stable endocardial contour** on frame **N**.

**User workflow unchanged:** user picks frame N → LV Auto EDV/ESV → review → Enter.  
**Simpson always uses frame N pixels** — only contour geometry is fused.

**Clinical intent:** comparison with neighbors helps «на глаз»; automatic fusion applies **temporal constraints** so fused contour does not jump (e.g. if neighbors show a higher apex, target apex must not shift basally beyond δ).

---

## Explicitly out of scope

| Item | Reason |
|------|--------|
| Accept contour on frame N±k (change `frame_index`) | User chose shape fusion on N |
| Full ED→ES tracking / speckle-bridge | Separate future spec |
| Rotation / optical-flow warp registration | v2 if translation insufficient |
| Automatic frame timing pick (which is «true» ED) | Not this spec |
| Single-frame still images (1 frame) | Fusion disabled when window empty |

---

## Background

| Current | Gap |
|---------|-----|
| One ONNX on frame N | No use of clearer neighbors |
| `refine_open_arc` on N gradient only | Fails when gradient weak on N but visible on N±1 |
| Annulus from single mask | Jitter on MA endpoints frame-to-frame |

---

## Architecture overview

```
User on frame N → LV Auto (phase ED/ES)
  │
  ├─ Prefetch [N−W … N+W], W=2
  │
  ├─ For each t in window: segment(t) via v1.5 pipeline → mask_t, contour_t
  │
  ├─ Register each t → N (translation by MA centroid delta)
  │
  ├─ Mask vote on N canvas → fused_mask
  ├─ open_arc_from_cavity_mask(fused_mask) → draft contour
  ├─ Node clamp vs center contour_N + neighbor contours
  ├─ Annulus fusion/vote with δ_annulus
  ├─ Apex direction lock + papillary + refine on frame N
  │
  └─ Contour(frame_index=N, review_pending=True)
        + TemporalFusionResult for ghost UX
```

New domain module: **`domain/services/lv_temporal_fusion.py`** (pure NumPy, no Qt).

---

## 1. Segmentation window

**Trigger:** `request_auto_segment` when instance has `total_frames > 1` and manifest `temporal_fusion.enabled: true`.

| Parameter | Default |
|-----------|---------|
| `window` W | 2 → frames `{N−2, N−1, N, N+1, N+2}` |
| Bounds | clamp to `[0, total_frames − 1]` |

**Execution:**

1. Segment **N first** (existing path) — show review UI immediately with center-only contour as interim.
2. Queue segment for other frames in window (same ROI policy as v1.5, same phase context).
3. On all completed (or timeout partial): run fusion, replace pending contour.

**Partial fusion:** if ≥3 valid frames (including N), fuse; else fall back to center-only N.

**Performance:** sequential ONNX worker (~2s × up to 5); progressive UI — status «Fusing 3/5 frames…».

---

## 2. Registration (v1)

**Translation-only** alignment to anchor N:

```python
dx_t = MA_centroid_x(N) - MA_centroid_x(t)
dy_t = MA_centroid_y(N) - MA_centroid_y(t)
```

Apply to binary `mask_t` and all contour points before fusion.

**MA centroid:** midpoint of septal/lateral from each frame's `open_arc_from_cavity_mask` (before fusion).

**v2 (deferred):** rotation from MA chord angle if bench shows >3 px residual at apex after translation.

---

## 3. Mask vote fusion

On anchor canvas (H×W of frame N):

1. Shift each aligned `mask_t` into frame N coordinates.
2. Per pixel: `vote_count = sum(mask_t pixel)`.
3. `fused_mask pixel = 1` if `vote_count >= vote_threshold`.

| Parameter | ED | ES |
|-----------|----|-----|
| `vote_threshold` | 3 | 3 |

(out of max 5 frames; if only 3 valid frames, threshold = 2)

4. `papillary_mask_cleanup(fused_mask, phase=…)` once on fused result.
5. `open_arc_from_cavity_mask(fused_mask)` → initial open arc + annulus + apex.

Frames failing `explain_lv_auto_reject_reason` **excluded** from vote (not counted in denominator).

---

## 4. Node clamp (interior + apex)

After mask path, refine with **robust node fusion** against:

- `contour_center` — ONNX-only on N (aligned)
- `contour_t` — each valid neighbor (aligned)

Resample all arcs to **32 nodes** (existing `resample_open_arc`); endpoints = annulus (see §5).

For interior node index `i ∈ (1 … 30)`:

```python
positions_i = [contour_t.points[i] for t in valid_frames]
median_i = component_wise_median(positions_i)
center_i = contour_center.points[i]

shift_cap = max_node_shift_ratio * MA_length_px
fused_i = clamp(median_i, center_i - shift_cap, center_i + shift_cap)
```

| Parameter | ED | ES |
|-----------|----|-----|
| `max_node_shift_ratio` | 0.03 | 0.025 |

**Apex node** (index closest to `apex_landmark`): use `apex_max_shift_ratio` (stricter):

| Parameter | ED | ES |
|-----------|----|-----|
| `apex_max_shift_ratio` | 0.02 | 0.015 |

### 4.1 Apex direction lock

If neighbors agree apex is **more apical** than center (smaller y in image coords, viewer `invertY=True`):

```python
neighbor_apex_ys = [apex_y_t for t in valid, t != N]
if count(apex_y_t < center_apex_y) >= 2:
    fused_apex_y = min(fused_apex_y, center_apex_y + apex_epsilon_px)
```

`apex_epsilon_px = apex_max_shift_ratio * MA_length_px`.

Symmetric rule optional v2 (neighbors more basal → cap upward shift); **not in v1**.

---

## 5. Annulus fusion (vote + small δ)

**Decision:** annulus **not** locked to center frame; **fusion/vote with small δ** (user approved).

### 5.1 Septal and lateral endpoints separately

For each endpoint (septal, lateral):

```python
positions = [annulus_t.septal for t in valid_frames]  # 2D points
median_pt = component_wise_median(positions)
center_pt = annulus_center.septal

δ_annulus = annulus_max_shift_ratio * MA_length_px
fused_septal = clamp(median_pt, center_pt - δ_annulus, center_pt + δ_annulus)
```

Same for lateral.

| Parameter | ED | ES |
|-----------|----|-----|
| `annulus_max_shift_ratio` | 0.015 | 0.012 |

**Rationale:** MA is relatively stable over ±2 frames but not pixel-identical; median reduces jitter while δ prevents wild jumps vs center ONNX.

### 5.2 Order of operations

1. Fuse interior + apex nodes (with annulus endpoints temporarily from center).
2. Fuse annulus endpoints (§5.1).
3. Force `fused_points[0] = fused_septal`, `fused_points[-1] = fused_lateral`.
4. `exclude_papillary_concavities(fused_points, annulus, apex, phase=…)`.
5. `smooth_open_arc` (4 iter).
6. `refine_open_arc_contour(frame_N, …)` on **frame N pixels** (manifest `auto_refine_after_segment`).

---

## 6. UX — comparison «на глаз»

Fusion is **automatic**; ghosts support visual comparison **without changing frame N**.

| Control | Action |
|---------|--------|
| Default overlay | **Fused** contour (solid AI styling) |
| `G` | Toggle **center-only** ONNX on N (dashed, 50% opacity) vs fused |
| `Shift+G` | Also show **one neighbor** ghost (aligned), 25% opacity |
| `[` / `]` | Cycle which **neighbor** ghost is shown (for comparison only) |
| `Enter` | Accept **fused** contour on frame N |
| `R` | R-refine fused on N |
| `Esc` | Discard |

**Status line example:**

> `A4C ED · frame 14 · fused 4/5 · G: center vs fused · ←/→ neighbor`

No keyboard action changes `frame_index` of accepted contour.

---

## 7. Data model

```python
@dataclass
class TemporalFusionResult:
    anchor_frame_index: int
    fused_contour: Contour              # frame_index = anchor, review_pending=True
    center_contour: Contour             # ONNX N only (aligned)
    neighbor_contours: dict[int, Contour]  # aligned to N
    frames_used: int
    frames_requested: int
    config: TemporalFusionConfig        # frozen snapshot for reproducibility
```

**File:** `domain/models/temporal_fusion.py` (or fields in existing models module).

Controller: `_temporal_fusion_result: TemporalFusionResult | None` cleared on accept/Esc/instance change.

---

## 8. Manifest configuration

**File:** `models/model_manifest.json`

```json
"temporal_fusion": {
  "enabled": true,
  "window": 2,
  "vote_threshold": 3,
  "max_node_shift_ratio_ed": 0.03,
  "max_node_shift_ratio_es": 0.025,
  "apex_max_shift_ratio_ed": 0.02,
  "apex_max_shift_ratio_es": 0.015,
  "annulus_max_shift_ratio_ed": 0.015,
  "annulus_max_shift_ratio_es": 0.012,
  "apex_direction_lock": true
}
```

Phase-specific values selected by `phase` argument (ED vs ES).

Disable fusion: `"enabled": false` → current single-frame behavior.

---

## 9. Files to change

| File | Change |
|------|--------|
| `domain/services/lv_temporal_fusion.py` | **Create** — register, vote, clamp, annulus fuse |
| `domain/models/temporal_fusion.py` | **Create** — dataclasses |
| `application/app_controller.py` | Window segment queue, fusion orchestration, store result |
| `presentation/viewer_widget.py` | Ghost overlays, `[`/`]`/`G` during review |
| `presentation/main_window.py` | Wire keys when `pending_ai_review` + fusion active |
| `models/model_manifest.json` | `temporal_fusion` block |
| `infrastructure/locales/en.json`, `ru.json` | Status strings |
| `tests/unit/test_lv_temporal_fusion.py` | **Create** |
| `tests/unit/test_auto_segment_controller.py` | Fusion enabled path |

**No change** to `lvef_simpson.calculate()` — uses accepted contour on frame N.

---

## 10. Testing

### Unit (`test_lv_temporal_fusion.py`)

| Test | Assert |
|------|--------|
| Translation registration | Centroid aligns after shift |
| Mask vote 3/5 | Bad single frame ignored |
| Node clamp | Median outside cap → clamped to center ± shift_cap |
| Apex direction lock | Neighbors higher → fused apex not below center + ε |
| Annulus fuse δ | Median annulus outside δ → clamped to center ± δ_annulus |
| Partial window | 3 frames → fusion runs; 1 frame → center-only |

### Integration

- Controller: N=10, mock 5 masks → single `review_pending` fused contour, `frame_index=10`.
- Ghost toggle does not alter stored fused contour.

### Manual

1. Ambiguous ED on N → fused smoother than center-only; `G` shows difference.
2. ES with papillary noise → vote reduces notch vs center.
3. Neighbors with higher apex → fused apex does not drop basally.
4. Annulus: fused MA stable vs flickering center-only when scrolling `[`/`]` ghosts.

---

## 11. Implementation order

| # | Task |
|---|------|
| 1 | `lv_temporal_fusion.py` pure functions + unit tests |
| 2 | Controller: multi-frame segment queue after N |
| 3 | Fusion hook in `_on_auto_segment_finished` |
| 4 | Viewer ghost overlays + keys |
| 5 | Locales + manifest defaults |
| 6 | Manual checklist on 3 cines |

**Depends on v1.5** for stable per-frame masks (ROI, norm). Can stub v1.5 in tests with synthetic masks.

---

## 12. Relation to other specs

| Spec | Relation |
|------|----------|
| `2026-07-05-lv-auto-onnx-quality-design.md` | v1.5 — input quality per frame |
| `2026-06-19-onnx-lv-auto-segment-design.md` | v1 base review UX (Enter/R/Esc) |
| `2026-06-27-ste-clinical-parity-design.md` | Independent; no speckle in fusion v1 |

---

Implementation plan via `writing-plans` → `docs/superpowers/plans/2026-07-05-lv-auto-temporal-fusion.md` (after v1.5 plan or as Phase 2).
