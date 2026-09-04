# Plan: LV long axis / MA, then temporal fusion

**Date:** 2026-09-04  
**Status:** proposed  
**Depends on:** two-pass auto-LV (`lv_cavity_mask_to_open_arc`), ASE Simpson 20-disk `h = max(L)/20`  
**Does not change:** disk count, monoplane formula, n=32 editor nodes, A2C auto model

---

## Goal

Simpson volume is now geometrically consistent. Remaining error is **where the long axis and mitral annulus sit**. Fusion cannot fix a bad axis — it only averages it.

Order is strict:

1. **One frame:** MA + apex + axis used by Simpson, papillary, and overlay are the same objects.
2. **Neighbors:** same pipeline + quality gate before they vote.
3. **Fusion:** vote on cleaned masks, then clamp landmarks; keep fusion off until a bench says it helps.

---

## Current state (code, not intent)

### Axis / MA

| Path | What it actually uses |
|------|------------------------|
| Simpson `L` / overlay disks | `long_axis_endpoints` = MA midpoint → **farthest point from MA chord** (`apex_point`) |
| Stored `apex_landmark` | Opposite **narrow 8% Y-band** of the mask (`_annulus_and_apex_from_mask_pixels`) |
| Two-pass papillary SE | Pass 1: bbox top/bottom row centroids. Pass 2: **MA mid → stored apex**, not Simpson tip |
| MA septal/lateral | Wider cavity opening (12% band) → percentile trim → boundary snap → blend with arc tips → optional MA ONNX if `models/ma_landmark_224.onnx` exists |

Mismatch: papillary and fusion register on `apex_landmark`; volumes use a different tip. On a tilted or notched cavity those two points diverge.

### Fusion

Manifest has `"temporal_fusion.enabled": true`. Commercial-parity spec said **default false until Gate A**. Neighbors are segmented with two-pass; **the voted mask is not** — `temporal_fuse` still does one `papillary_mask_cleanup` + `open_arc_from_cavity_mask`.

Other gaps vs the fusion spec:

- Neighbors are **not** run through `explain_lv_auto_reject_reason` before the vote.
- After `confidence_weighted` filter, `aligned_masks` is **not rebuilt** — low-confidence frames still vote.
- Node clamp requires `len(pts) == len(open_points)`; otherwise the neighbor is silently skipped (no resample).
- Alignment is **MA-centroid translation only** (rotation deferred).
- Cine `ValueError` diagnostics still inspect the **raw** mask.

---

## Principle

Do not turn fusion “smarter” until one-frame landmarks are Simpson-aligned. Otherwise fusion locks in the wrong MA/apex with a δ clamp around the center frame.

---

## Phase A — unify axis / MA (one frame)

**Outcome:** papillary pass 2, stored landmarks, overlay axis, and `_long_axis_mm` share one `(annulus, apex)` pair.

### A1. Canonical apex after open-arc

After `open_arc_from_cavity_mask` (both passes of `lv_cavity_mask_to_open_arc`):

```text
apex = apex_point(open_points, annulus)   # farthest from MA chord
```

Keep the band-derived point only as a **seed** if the arc is too short. Write that apex onto `Contour.apex_landmark`.

Tests: synthetic tilted ellipse — `apex_landmark` == Simpson tip within 1 px.

### A2. Papillary pass 2 uses the same axis

`long_axis_hint=(ma_mid, canonical_apex)`. Optional: if pass-2 mask IoU vs pass-1 drops below ~0.85 **or** pixel count jumps >25%, keep pass 1 (closing over-grew into myocardium).

### A3. MA: geometry first, ONNX as blend not source

Keep band + snap as primary. Tighten:

- Basal band: prefer **high-y** (or low-y) consistently with `annulus_end` (already `prefer_high_y`).
- After snap, **recompute** MA length; if it shrinks below quality-gate min, reject rather than blend toward a collapsed chord.
- MA ONNX (`_try_refine_annulus_with_onnx`): keep 0.35 blend and 25 px cap; **do not** promote it to primary until Tier-1 B′ (annulus error) is measured. If the file is missing, path is already a no-op.

### A4. Quality gate on landmarks, not only arc span

Add (or tighten) checks already sketched in commercial parity:

| Check | Reject if |
|-------|-----------|
| Apex vs MA mid | long axis < 15 px (exists) **or** apex on the MA side of the chord (inverted) |
| MA slope | \|angle vs image X\| > ~40° **and** depth/MA < 0.2 (likely wrong opening) |
| Pass-2 vs pass-1 | optional log-only in A2 |

Cine diagnostics: on `ValueError`, report **cleaned** mask bbox/centroid.

**Stop:** A4C ED/ES auto, no fusion. Overlay disks sit on the same L as volume. No longest-chord return.

---

## Phase B — fusion correctness (still default **off** for release)

Do this **before** re-enabling fusion in the shipped manifest. Local `enabled: true` is fine for benches.

### B1. Same per-frame pipeline as auto-LV

In `temporal_fuse` LV branch replace

`papillary_mask_cleanup` + `open_arc_from_cavity_mask`

with `lv_cavity_mask_to_open_arc(fused_mask, phase=…)` (or vote **already-cleaned** neighbor masks — pick one; prefer vote on cleaned masks so papillary notches do not win the vote).

### B2. Gate neighbors before vote

Controller: after neighbor two-pass, `explain_lv_auto_reject_reason(..., roi_xyxy=same ROI)`. Fail → `_on_neighbor_segment_failed` (exclude from vote **and** from `frames_used`).

### B3. Confidence filter must rebuild the vote set

After `min_confidence_score`, drop those ids from `aligned_masks` and recompute threshold `min(vote_threshold, n_valid)`.

### B4. Resample before node median

All arcs → 32 nodes via `resample_open_arc_landmarks` with **that frame’s** fused/aligned MA, then median. No silent skip on length mismatch.

### B5. Manifest default

Ship `"temporal_fusion.enabled": false` (parity spec). Enable only after Phase C bench. Keep the rest of the fusion block as-is.

**Stop:** with fusion forced on in tests, 3 good + 1 garbage neighbor → garbage excluded; fused contour still `frame_index=N`.

---

## Phase C — fusion quality (only if A+B and Gate A without fusion)

Do **not** start C to “hide” a bad MA.

### C1. Register on long axis, not only MA mid

v1 stays translation. If bench residual at apex after translation > 3 px (already in fusion spec §2 v2): add **rotation** from MA-chord angle (or MA mid → apex) before vote.

### C2. Landmark fusion order (already specified, make it true)

1. Interior nodes: median, clamp to center ± `max_node_shift_ratio * MA`.
2. Apex: stricter cap + direction lock using **canonical apex** (A1), not band y.
3. Annulus: median ± `annulus_max_shift_ratio * MA`, then pin endpoints.
4. `exclude_papillary_concavities` + smooth + refine on **frame N pixels**.

Direction lock today assumes smaller image-y is more apical (A4C sector). Keep that; do not invert for “bottom annulus” views without a view_hint.

### C3. Ghost UX already exists (`G`, neighbor cycle)

No new keys. Status must show `fused k/n` after B2 exclusions.

### C4. Promotion rule

Re-enable fusion in manifest only if Tier-1 (or current `run_lv_auto_bench.py`) shows:

- median \|ΔLVEF\| **not worse** than fusion-off, and
- zero-edit accept **up** or papillary-notch rate **down**,

on the same gold. If fusion helps ES notches but hurts ED volume, consider `enabled` only for ES.

---

## Explicitly out of scope

| Item | Why |
|------|-----|
| Change n disks / monoplane h | ASE already applied |
| Optical flow / speckle-bridge ED→ES | Separate STE path |
| A2C auto model | No weights; biplane still needs a second contour |
| Separate MA CNN as required | Optional blend only (A3) |
| Auto-delete outlier contours | Review only |
| Dense per-frame fusion window > ±2 | Cost; W=2 is enough if masks are clean |

---

## Tests (minimum)

**Phase A**

- Tilted open arc: `apex_landmark` == `apex_point(points, annulus)`.
- Two-pass: pass-2 hint equals MA mid → that apex; over-grow keeps pass 1.
- Quality: inverted apex (annulus_y < apex_y on A4C) still rejected.

**Phase B**

- `temporal_fuse` LV calls two-pass helper (mock).
- Neighbor reject reason → not in `aligned_masks`.
- Confidence below 0.3 → dropped from vote (mask sum changes).
- 31 vs 32 nodes → resampled, median defined.

**Phase C**

- Existing `test_temporal_fusion_v2.py` plus rotation unit if C1 lands.

Bench: `scripts/run_lv_auto_bench.py` already on two-pass; add columns `apex_vs_simpson_px`, `fusion_on`, `frames_used`.

---

## Suggested implementation order

| # | Task | Risk if skipped |
|---|------|-----------------|
| A1–A2 | Canonical apex + papillary hint | Closing and Simpson disagree |
| A3–A4 | MA snap / gate / cine cleaned stats | Garbage MA accepted |
| B1–B4 | Fusion uses two-pass + gated vote | Fusion worse than center-only |
| B5 | `enabled: false` in shipped manifest | Users get 5× ONNX without a proven gain |
| C | Rotation + re-bench, then maybe enable | Premature |

A is the next coding slice. B is a correctness patch on code that already runs when the flag is on. C is research against gold.
