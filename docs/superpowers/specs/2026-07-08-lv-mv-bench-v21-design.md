# LV v2.1 — Bench LVEF/Zero-Edit + MV Landmark Geometry

**Date:** 2026-07-08  
**Status:** Draft (brainstorming)  
**Extends:** `2026-07-06-lv-auto-commercial-parity-design.md`  
**Scope:** Tier-1 bench completeness (Gates A/C), MV annulus geometry improvements, optional MA ONNX fallback, roadmap for next LV gains.

---

## Goal

Close the measurement loop on Tier-1 LV auto-contour: **real |ΔLVEF|** and **zero-edit rate** in `run_lv_auto_bench.py`, then improve **mitral annulus (MV line) endpoint accuracy** from ~19–23 px toward **< 10 px** using mask geometry (with optional MA-regressor ONNX if geometry plateaus above 15 px).

**Current baseline** (`bench/reports/lv_baseline_lvannulus_20260708.csv`, 210 frames):

| Gate | Target | Current |
|------|--------|---------|
| B — median IoU | > 0.82 | **0.860** PASS |
| B′ — annulus err (each) | < 10 px | **~23 / ~19 px** FAIL |
| A — median \|ΔLVEF\| | < 5% | **n/a** (not computed) |
| C — zero-edit rate | ≥ 60% | **n/a** (stubbed `False`) |
| Reject | < 15% | **0%** PASS |

**User priority (2026-07-08):** Phase 1 = bench metrics first; Phase 2 = MV geometry; MA ONNX only if geometry median still > 15 px.

---

## Success gates (unchanged)

Same release targets as commercial-parity v2.0. This spec adds **how** to measure and improve them; it does not change thresholds.

| Gate | Metric | Release |
|------|--------|---------|
| A | median \|ΔLVEF\| vs gold Simpson monoplane A4C | < 5% |
| B | median mask IoU | > 0.82 |
| B′ | median annulus endpoint L2 (septal, lateral each) | < 10 px |
| C | zero-edit accept rate (ED+ES pooled) | ≥ 60% |
| Reject | hard pipeline reject | < 15% |

**Zero-edit definition (product + bench):** auto contour accepted as-is if **\|ΔLVEF\| ≤ 5%** vs gold **or** frame **IoU ≥ 0.80** (`bench_metrics.zero_edit_accept`).

**Light-edit (Gate C′):** out of scope for v2.1 bench — requires user-edit simulation; defer to v2.1.1.

---

## Architecture overview

```
[manifest entry = one DICOM instance + ed_frame + es_frame]
  → per-frame: auto segment → IoU, annulus err (existing)
  → per-instance pair: lvef_simpson.calculate(ED, ES) auto vs gold
  → per-frame: lvef_delta (pair-level), zero_edit (pair delta + frame IoU)
  → CSV + gate summary

[MV geometry — Phase 2, segmentation_service]
  mask → basal band → _mitral_annulus_endpoints (prefer_high_y, done)
       → NEW _snap_annulus_to_mask_boundary
       → NEW optional _align_annulus_to_open_arc_tips
       → open_arc / quality gate unchanged interface

[MA ONNX — Phase 2b, conditional]
  if Tier-1 median annulus err > 15 px after geometry:
    2-point heatmap regressor → Fallback C in landmark chain
```

---

## Phase 1 — Bench: real |ΔLVEF| and zero-edit

### 1.1 Pairing unit

**Unit of LVEF comparison:** one **manifest entry** = one `instance_path` with its `ed_frame` and `es_frame`.

- Not `study_id` (many instances share one gold file).
- Not single-frame (LVEF requires ED+ES pair).

Both auto and gold LVEF use production `lvef_simpson.calculate((ed_contour, es_contour), pixel_spacing)` with `method == "simpson_monoplan"` and `view == A4C`.

### 1.2 Pixel spacing resolution

Order (first non-null wins):

1. `gold["pixel_spacing_mm"]` — `[row, col]` from gold JSON study root.
2. `DicomReaderImpl.read_metadata(instance_path).pixel_spacing` via `resolve_pixel_spacing`.
3. If missing: mark instance `lvef_skip_reason = "no_pixel_spacing"`; `lvef_delta = None` for both frames; IoU/annulus metrics still computed.

Gold contours for LVEF: build `Contour` from gold frame `points` + `mitral_annulus` (same as auto), `phase` lowercased, `review_pending=False`, `source="gold"`.

### 1.3 Bench runner refactor

**File:** `scripts/run_lv_auto_bench.py`

Two-pass structure per manifest entry:

1. **Frame pass:** run auto segment for ED and ES; store `Contour | None`, per-frame IoU, annulus errors (current logic).
2. **Pair pass:** if both contours and both gold frames exist and spacing resolved:
   - `lvef_auto = calculate((ed_auto, es_auto), spacing).lvef_percent`
   - `lvef_gold = calculate((ed_gold, es_gold), spacing).lvef_percent`
   - `lvef_delta = lvef_delta(lvef_auto, lvef_gold)` from `bench_metrics`
   - Apply `lvef_delta` to **both** ED and ES rows for that instance.
3. **Zero-edit:** for each non-reject row: `zero_edit = zero_edit_accept(row["lvef_delta"], row["iou"])`.

Extract helpers (testable):

- `_resolve_pixel_spacing(gold: dict, instance_path: Path) -> tuple[float, float] | None`
- `_gold_frame_to_contour(gold_frame: dict) -> Contour`
- `_compute_pair_lvef(auto_ed, auto_es, gold_ed, gold_es, spacing) -> dict` with keys `lvef_auto`, `lvef_gold`, `lvef_delta`, optional `edv_*`, `esv_*` for CSV diagnostics.

### 1.4 CSV schema (extended)

Per-frame rows (unchanged keys + additions):

| Column | Description |
|--------|-------------|
| `lvef_auto` | Simpson LVEF % for instance pair (duplicated on ED/ES rows) |
| `lvef_gold` | Gold Simpson LVEF % |
| `lvef_delta` | \|auto − gold\| % |
| `lvef_skip_reason` | `no_pixel_spacing`, `missing_ed`, `missing_es`, `missing_gold`, `calculate_failed` |
| `zero_edit` | bool from `zero_edit_accept` |
| `pair_complete` | bool — both phases segmented and gold matched |

Summary block prints Gate A/C with PASS/FAIL (already stubbed in runner).

### 1.5 Aggregation rules

- `median_lvef_delta`: median over rows where `lvef_delta is not None` (210 rows max; paired values duplicated — use **one value per instance** via `pair_complete` dedup or aggregate at pair pass).
- `zero_edit_rate`: `n_zero / total` over all frame rows (ED+ES pooled), per commercial-parity spec.
- Document in code: deduplicate `lvef_delta` by `(study_id, instance)` when computing median for Gate A to avoid double-counting.

### 1.6 Tests

| Test | File |
|------|------|
| `_compute_pair_lvef` with synthetic contours + known spacing | `tests/unit/test_lv_bench_lvef.py` (new) |
| `zero_edit` set True when delta ≤ 5% even if IoU low | same |
| `zero_edit` True when IoU ≥ 0.80 even if delta None | `test_bench_metrics.py` (existing) |
| Integration: mock segment returning fixed contours → CSV columns populated | `tests/unit/test_run_lv_auto_bench.py` (new, lightweight) |

### 1.7 Acceptance criteria (Phase 1)

- Bench run on full manifest prints Gate A and Gate C (not n/a).
- CSV contains `lvef_auto`, `lvef_gold`, `lvef_delta`, `zero_edit` populated for ≥ 95% of instances with gold ED+ES and spacing.
- No change to inference pipeline (bench-only + helpers).

---

## Phase 2 — MV landmark geometry

### 2.1 Problem

`prefer_high_y` basal snap (2026-07-08) improved IoU and annulus error but **B′ still ~2× target**. Remaining error sources:

- Endpoints sit on **mask interior band mean**, not on **cavity opening boundary**.
- Septal/lateral buckets use **X-percentile trim**; sloped annulus needs **boundary walk** along basal edge.
- Open-arc first/last nodes may be closer to expert MA than raw mask statistics.

### 2.2 Approach comparison

| Approach | Idea | Pros | Cons |
|----------|------|------|------|
| **A — Boundary snap** (recommended) | Project septal/lateral to nearest mask-boundary pixel in basal band, same half-plane | Direct fix for B′; no new model | Needs clean boundary; fragile on fragmented ES masks |
| **B — Arc tip alignment** | Snap MA toward first/last smoothed open-arc nodes | Matches displayed contour | Arc tips can lag true annulus |
| **C — Horizontal chord only** | Leftmost/rightmost X at basal Y | Simple | Fails on sloped MV line |

**Recommendation:** Implement **A** first, then **B** as light blend (≤ 8 px):  
`ma_refined = 0.7 * boundary_snap + 0.3 * arc_tip` when arc tip within 8 px of bucket.

### 2.3 New functions

**File:** `src/echo_personal_tool/domain/services/segmentation_service.py`

```python
def _mask_boundary_points_in_band(
    mask: np.ndarray, y_low: int, y_high: int,
) -> tuple[np.ndarray, np.ndarray]: ...

def _snap_annulus_to_mask_boundary(
    septal: tuple[float, float],
    lateral: tuple[float, float],
    mask: np.ndarray,
    *,
    basal_y_range: tuple[int, int],
    search_radius_px: float = 12.0,
) -> tuple[tuple[float, float], tuple[float, float]]: ...

def _blend_annulus_with_arc_tips(
    annulus: tuple[...],
    open_points: list[tuple[float, float]],
    *,
    max_blend_dist_px: float = 8.0,
    blend_weight: float = 0.3,
) -> tuple[tuple[float, float], tuple[float, float]]: ...
```

Wire into `_annulus_and_apex_from_mask_pixels` and `_fallback_annulus_wider_band` **after** `_mitral_annulus_endpoints`, passing cleaned cavity mask and basal band bounds.

### 2.4 Parameters (bench-tunable constants)

| Parameter | Default | Tune via |
|-----------|---------|----------|
| `search_radius_px` | 12 | Tier-1 grid 8–16 if needed |
| `max_blend_dist_px` | 8 | unit tests + bench |
| `blend_weight` | 0.3 | keep fixed in v2.1 |

### 2.5 Tests

- Synthetic mask: known septal/lateral on boundary → snap does not move > 1 px.
- Sloped annulus mask: endpoints preserve Y ordering (septal left, lateral right).
- Regression: existing `test_mitral_annulus_endpoints_allow_sloped_mv_line` still passes.
- Bench re-run: target median septal/lateral **< 15 px** as Phase 2 exit; **< 10 px** as release.

### 2.6 Acceptance criteria (Phase 2)

- `median_septal_err` and `median_lateral_err` improve ≥ 25% vs lvannulus baseline without IoU regression > 0.01.
- No increase in pipeline reject rate.

---

## Phase 2b — MA landmark ONNX (conditional)

**Entry condition:** After Phase 2 geometry, Tier-1 median annulus error (max of septal/lateral medians) **still > 15 px** and mask IoU ≥ 0.82.

**Not in v2.1 initial sprint** unless entry condition met.

| Item | Detail |
|------|--------|
| Model | 2-point heatmap / coordinate regression on 224×224 crop |
| Training data | Tier-1 gold `mitral_annulus` (~105 studies × 2 phases) |
| Integration | Fallback C after `_fallback_annulus_sector_chord` in `open_arc_from_cavity_mask` |
| Script | `scripts/train_ma_landmark.py`, export to `models/ma_landmark_224.onnx` |
| Gate | Promote only if B′ median < 12 px without IoU regression |

---

## Phase 3 — Next steps (after Gates A/C measurable)

Ordered by expected ROI once bench is live:

| # | Item | Trigger | Expected impact |
|---|------|---------|-----------------|
| 1 | **ES mask outliers** | Per-frame IoU < 0.65 on ES | Gate B, indirectly A |
| 2 | **Papillary / phase cleanup** | ES depth-ratio rejects or concavity leaks | IoU + annulus |
| 3 | **Crop mode A/B re-bench** | Gate B plateau | IoU on wide-sector DICOM |
| 4 | **224×224 model promotion** | Norm stable (`per_frame` kept) | IoU + LVEF |
| 5 | **Decoder fine-tune** | Gate A fail with good IoU | Gate A primary |
| 6 | **Light-edit bench (C′)** | Zero-edit < 60% but IoU high | Product accept modeling |
| 7 | **Temporal fusion default** | Gate A pass without fusion | Robustness on noisy frames |

---

## Explicitly out of scope (v2.1)

- LA auto segmentation (separate spec)
- Light-edit user simulation in bench
- EchoPAC comparison as release gate
- A2C auto model
- int8 / TTA ensemble

---

## Files touched (summary)

| Phase | Create | Modify |
|-------|--------|--------|
| 1 | `tests/unit/test_lv_bench_lvef.py`, optional `test_run_lv_auto_bench.py` | `scripts/run_lv_auto_bench.py` |
| 2 | — | `segmentation_service.py`, `tests/unit/test_segmentation_service.py` |
| 2b | `scripts/train_ma_landmark.py` | `onnx_engine.py`, `open_arc_from_cavity_mask` chain |

---

## Risks

| Risk | Mitigation |
|------|------------|
| Gold missing `pixel_spacing_mm` | DICOM resolver fallback; report skip count |
| LVEF sensitive to MA error | Phase 2 geometry; monitor Gate A vs B′ correlation in CSV |
| Boundary snap on ES fragmentation | Wider basal band in snap only; keep fallback A/B chain |
| Double-counting lvef_delta in median | Dedup by instance in `aggregate_bench_results` extension |

---

## Relation to other specs

- **Supersedes nothing** — extends commercial-parity v2.0 measurement gap.
- **Defers** temporal fusion (`2026-07-05-lv-auto-temporal-fusion-design.md`) until Gate A measured.
- **Independent of** LA spec (`2026-07-06-la-auto-segmentation-design.md`).
