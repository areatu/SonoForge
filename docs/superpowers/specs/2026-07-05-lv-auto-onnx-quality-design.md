# LV Auto ONNX Quality v1.5 — Per-Frame Segmentation

**Date:** 2026-07-05  
**Status:** Approved (brainstorming)  
**Supersedes:** partial items in `2026-06-19-onnx-lv-auto-segment-design.md` (preprocessing v1.1, ROI gaps)  
**Scope:** Per-frame ONNX quality on **ED and ES** frames — ROI, preprocessing, papillary post-process, edge refine. **No temporal tracking.**

---

## Goal

Improve endocardial contour quality from **LV Auto → LVEF Simpson EDV/ESV** (A4C monoplane) without changing the user workflow (user still seeks ED/ES frames manually).

**Success criteria (benchmark gate):**

| Metric | Target |
|--------|--------|
| Median \|ΔLVEF\| vs reference (monoplan A4C) | < 5% on paired ED+ES |
| Mask IoU vs manual reference | > 0.85 median (internal set) |
| Annulus endpoint error | < 8 px median at native resolution |
| MP4 ROI regression | 0 cases with full-frame crop (UI bars in ONNX input) |

Stretch goal (ROADMAP): ±3% LVEF vs Standard — not a release blocker for v1.5.

---

## Explicitly out of scope

| Item | Reason |
|------|--------|
| ED→ES speckle / temporal tracking | Separate spec (future) |
| One-click full-cycle Auto Simpson | Depends on tracking |
| A2C auto-segment / biplane | v2 — separate model |
| 224×224 model re-export | Phase B after v1.5 benchmark |
| ONNX fine-tune / new weights | Phase B |
| TTA ensemble (flip/average) | Phase B optional |
| Myocardial wall / epicardium | Never in LV Auto v1 |

**Manual Left Ventricle workflow:** unchanged.

---

## Background — current pipeline gaps

Audit (2026-07-05):

| Area | Current | Gap |
|------|---------|-----|
| **ROI MP4** | `_resolve_segment_roi_bounds` returns `None` for cine | ONNX sees **full frame** (scale bars, overlays) |
| **ROI DICOM** | `SequenceOfUltrasoundRegions` → crop | No sector trim; some vendors leave black margins |
| **Frozen cine ROI** | `StudyMeasurementSession.cine_segment_roi` exists | Not wired into auto-segment for MP4 |
| **Preprocess** | per-frame mean/std in `prepare_tensor` | ES frames darker → distribution shift vs ED |
| **v1.1 norm** | `fixed_mean/std: null` in manifest | Deferred since v1 |
| **Threshold** | fixed sigmoid 0.5 | Suboptimal on low-contrast ES |
| **Mask upscale** | `embed_echonet_mask` zoom `order=0` | Jagged boundary → annulus error |
| **Papillary A** | `papillary_mask_cleanup`; `long_axis_hint` ignored | Closing not aligned with LV long axis |
| **Papillary B** | `exclude_papillary_concavities(ratio=0.04)` | Same params for ED and ES |
| **Open arc** | `open_arc_from_cavity_mask` primary | Fallback `closed_polygon_to_open_arc` degrades quality |
| **Edge refine** | `refine_open_arc_contour` only when `is_cine` | DICOM skips post-ONNX edge snap |
| **Manifest** | `auto_refine_after_segment: false` | Refine off for DICOM even if flag toggled |

---

## Architecture (unchanged entry points)

```
User: LV Auto → LVEF Simpson EDV/ESV (A4C)
  → set_simpson_workflow_context(phase, view=A4C)
  → request_auto_segment()
  → [OnnxWorker] segment(frame, roi_xyxy, crop_mode)
  → post-process pipeline (v1.5 enhanced)
  → Contour(source="ai", review_pending=True)
  → user R / drag / Enter
  → lvef_simpson.calculate() monoplan A4C
```

Post-process v1.5:

```
[112×112 mask in full-frame coords]
  → papillary_mask_cleanup (phase-aware, axis-aligned)
  → open_arc_from_cavity_mask
  → exclude_papillary_concavities (phase-aware)
  → refine_open_arc_contour (all media if manifest flag)
  → explain_lv_auto_reject_reason → accept or reject
  → Contour(review_pending=True)
```

---

## 1. ROI improvements

### 1.1 Fix MP4 / cine ROI (critical)

**File:** `application/app_controller.py` — `_resolve_segment_roi_bounds`

**Current:** returns `None` for non-DICOM → full-frame ONNX input.

**Target:**

```python
return resolve_segment_roi_xyxy(
    frame,
    media_format=media_format,
    instance_path=instance_path,
    frozen_cine_roi=self._frozen_cine_segment_roi(),
)
```

**Frozen ROI policy:** same as existing cine segment logic — ROI from frame 0 cached in `StudyMeasurementSession`; reused for all frames in clip (ED and ES share ROI).

### 1.2 DICOM sector trim

After `SequenceOfUltrasoundRegions` bounds (or heuristic fallback), apply `_trim_sector_content_bounds` from `segment_roi.py` to drop black margins above/below tissue fan.

Parameters: `intensity_percentile=35`, `trim_bottom=True`, `pad_px=6` (existing defaults).

> **v1.5 deviation (2026-07-05):** `_trim_sector_content_bounds` was implemented then **reverted** because it cut the LV apex on real DICOM data. `SequenceOfUltrasoundRegions` bounds are already correct for DICOM; the trim is only useful for cine/MP4 where `_trim_sector_content_bounds` is applied in `resolve_cine_segment_roi_xyxy`. **Decision: trim is NOT applied to DICOM.** Keep this note for future benchmark — re-enable if vendor data shows black margins in US regions.

### 1.3 Crop mode (manifest)

**File:** `models/model_manifest.json`

```json
"inference": {
  "crop_mode": "center_square",
  ...
}
```

Values: `"center_square"` (default, EchoNet training) | `"full_roi"`.

Implement via existing `EchoNetCropMode` in `segmentation_service.crop_frame_for_echonet`. A/B comparison in benchmark harness; default stays `center_square` unless data shows `full_roi` wins.

### 1.4 Debug overlay (developer)

When viewer debug overlay is visible (`toggle_debug_overlay`), draw ROI rectangle used for last auto-segment (store last `roi_xyxy` on controller). Not user-facing in production UI.

> **Implemented (2026-07-05):** `_last_segment_roi_xyxy` stored on controller, ROI drawn as dashed red rectangle on ViewBox, coords shown in debug label. Toggle off clears rect.

---

## 2. Preprocessing & inference

### 2.1 Normalization v1.1

**File:** `segmentation_service.prepare_tensor`, `model_manifest.json`

```json
"preprocessing": {
  "normalization_mode": "fixed_if_available",
  "fixed_mean": [0.124, 0.124, 0.124],
  "fixed_std": [0.116, 0.116, 0.116],
  ...
}
```

**Note:** Initial values are EchoNet-Dynamic train-split placeholders; calibrate via `scripts/calibrate_echonet_norm.py` on Tier-1 DICOM set before release. If `fixed_mean` is null → fallback to per-frame (current behavior).

Modes:

| `normalization_mode` | Behavior |
|----------------------|----------|
| `per_frame` | Current v1 |
| `fixed` | Always fixed mean/std |
| `fixed_if_available` | Fixed when manifest values non-null, else per_frame |

### 2.2 Adaptive logit threshold

**File:** `segmentation_service.logits_to_mask`

Replace fixed `threshold=0.5` with:

1. Apply sigmoid to logits.
2. Compute Otsu threshold on sigmoid values inside crop.
3. Clamp to `[0.35, 0.65]`.
4. Binarize at adaptive threshold.

Manifest override: `inference.logit_threshold: null` (adaptive) | `0.5` (fixed, for A/B).

Log chosen threshold in `cine_segment_diagnostics` report.

### 2.3 Mask upscale quality

**File:** `segmentation_service.embed_echonet_mask`

Change zoom from `order=0` (nearest) to `order=1` (linear) + re-threshold at 0.5 after upscale.

Benchmark compares order=0 vs order=1; ship order=1 if annulus error improves without IoU regression.

### 2.4 Timeout

Optional manifest bump: `inference.timeout_sec: 3.0` (from 2.0) if subprocess overhead on slow machines causes false timeouts. Default: keep 2.0 unless CI shows timeouts.

---

## 3. Papillary & open-arc (ASE)

### 3.1 Phase-aware mask cleanup

**File:** `segmentation_service.papillary_mask_cleanup`

| Parameter | ED | ES |
|-----------|----|----|
| `se_length_ratio` | 0.04 | 0.06 |
| `se_len clamp` | [5, 15] px | [6, 18] px |

**Axis-aligned closing:** use oriented ellipse SE aligned to LV long axis:

1. Derive axis from mask bbox (top = narrow, bottom = wide) or from `long_axis_hint` when provided (second pass after draft annulus/apex).
2. Replace ignored `long_axis_hint` parameter with actual usage when hint available.

Optional pre-step: morphological **opening** (disk r=2) before closing to break thin bridges to papillary tissue.

### 3.2 Phase-aware concavity exclusion

**File:** `segmentation_service.exclude_papillary_concavities`

Pass `phase: Literal["ED", "ES"]` from `app_controller._on_auto_segment_finished`:

| Parameter | ED | ES |
|-----------|----|----|
| `depth_threshold_ratio` | 0.04 | 0.05 |
| `min_depth_px` | 2.0 | 2.0 |

Smoothing after fill: `smooth_open_arc` iterations=4 (unchanged).

### 3.3 Open-arc primary path

Keep `open_arc_from_cavity_mask` as **only** happy path when mask quality sufficient.

Fallback `closed_polygon_to_open_arc`:

- Log at WARNING: `"degraded open-arc fallback"`.
- Emit diagnostic flag in segment report.
- Do not silently prefer fallback when primary fails on small masks — reject with `explain_lv_auto_reject_reason`.

### 3.4 Auto edge refine (all media)

**Manifest:**

```json
"inference": {
  "auto_refine_after_segment": true,
  ...
}
```

**File:** `app_controller._on_auto_segment_finished`

Change condition from `is_cine or manifest flag` to **manifest flag only** (default `true` in v1.5).

Uses existing `refine_open_arc_contour(frame, draft, cine=is_cine)` with `active_contour_config_for_source("ai")`.

---

## 4. ES-specific handling

| ES artifact | Mitigation in v1.5 |
|-------------|-------------------|
| Darker frame | fixed norm + adaptive threshold |
| Smaller cavity | phase-aware closing + concavity ratio |
| Papillary prominence | stronger ES morph + concavity threshold |
| Mask too small | keep min 80 px; if annulus OK and area 50–80, allow with warning status |
| Collapsed arc | existing `explain_lv_auto_reject_reason` messages |

**Min mask pixels:** remain 80 default; optional manifest `inference.min_mask_pixels_es: 50` if benchmark shows false rejects on valid ES.

---

## 5. Quality gates & diagnostics

### 5.1 Reject reasons (unchanged API)

`explain_lv_auto_reject_reason(contour, pixel_spacing)` — pixel geometry only.

v1.5 adds optional debug: attach last mask thumbnail path in diagnostics JSON (not UI).

### 5.2 Benchmark harness

**Extend:** `domain/services/cine_segment_diagnostics.py` + `tests/interactive/test_cine_segment_diagnostics.py`

Batch mode:

```bash
python -m pytest tests/bench/test_lv_auto_quality_bench.py -v  # new
```

Inputs: env `ECHO_LV_AUTO_BENCH=<dir>` with DICOM/MP4 + optional reference contours JSON.

Outputs per case: IoU, annulus error, arc span, LVEF, threshold used, ROI bounds, fallback flag.

### 5.3 Regression tests (unit)

| Test | File |
|------|------|
| MP4 ROI non-null | `test_segment_roi.py` (new or extend) |
| Phase papillary params | `test_segmentation_service.py` |
| Adaptive threshold clamp | `test_segmentation_service.py` |
| fixed_if_available norm | `test_segmentation_service.py` |
| embed order=1 shape | `test_segmentation_service.py` |
| Controller passes phase to cleanup | `test_auto_segment_controller.py` |

---

## 6. Files to change

| File | Change |
|------|--------|
| `application/app_controller.py` | MP4 ROI; phase to papillary; refine gate; debug ROI cache |
| `domain/services/segment_roi.py` | Export trim helper for DICOM path if needed |
| `domain/services/segmentation_service.py` | Norm modes; adaptive threshold; embed upscale; phase-aware papillary |
| `models/model_manifest.json` | preprocessing v1.1; inference flags |
| `infrastructure/onnx_engine.py` | Pass phase/crop_mode if needed |
| `scripts/calibrate_echonet_norm.py` | **Create** — compute mean/std from Tier-1 DICOM |
| `domain/services/cine_segment_diagnostics.py` | Log threshold, ROI, fallback |
| `tests/unit/test_segmentation_service.py` | New cases |
| `tests/unit/test_auto_segment_controller.py` | MP4 ROI wiring |
| `tests/bench/test_lv_auto_quality_bench.py` | **Create** — optional bench |
| `ROADMAP.md` | v1.5 row under LV Auto ONNX |

**No UI changes** except debug ROI overlay (dev-only). Review UX (Enter/R/Esc) unchanged.

---

## 7. Implementation order

| # | Task | Risk |
|---|------|------|
| 1 | MP4 ROI fix | Low — highest impact |
| 2 | DICOM sector trim | Low |
| 3 | Adaptive threshold + embed upscale | Medium — needs bench |
| 4 | Phase-aware papillary | Medium |
| 5 | fixed norm v1.1 + calibrate script | Medium |
| 6 | auto_refine for DICOM | Low |
| 7 | Benchmark + unit tests | Low |
| 8 | Manifest defaults + ROADMAP | Low |

---

## 8. Phase B (after v1.5 benchmark)

Not in this spec — track separately:

- 224×224 ONNX re-export
- int8 vs fp32 model selection
- TTA horizontal flip ensemble
- ±3% Standard validation gate as release criterion

---

## 9. Relation to other specs

| Spec | Relation |
|------|----------|
| `2026-06-19-onnx-lv-auto-segment-design.md` | v1 base; v1.5 extends preprocessing § and ROI |
| `2026-07-05-lv-auto-temporal-fusion-design.md` | v1.6 — neighbor fusion on frame N (after v1.5) |
| `2026-06-27-ste-clinical-parity-design.md` | Speckle tracking — **not** used in v1.5 |
| `2026-06-13-mbs-advanced.md` | Cancelled; ED→ES propagate not revived here |

---

## 10. Manual verification checklist

1. DICOM A4C: ED frame → LVEF Simpson EDV → contour follows endo, no papillary notches.
2. Same study ES frame → ESV Auto → smaller cavity, no collapse reject on typical case.
3. MP4 cine: confirm ROI excludes side UI (debug overlay).
4. Toggle W/L before segment → contour still reasonable (display buffer input).
5. R-refine on AI contour → Enter → LVEF appears in overlay.
6. Reject case: wrong view → clear Russian message from `explain_lv_auto_reject_reason`.

---

Implementation plan via `writing-plans` → `docs/superpowers/plans/2026-07-05-lv-auto-onnx-quality.md`.
