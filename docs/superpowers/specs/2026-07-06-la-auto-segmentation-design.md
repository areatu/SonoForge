# LA Auto Segmentation v1 — LAV 4C A4C ES (Fine-Tune)

**Date:** 2026-07-06  
**Status:** Approved (brainstorming)  
**Depends on:** `2026-07-06-lv-auto-commercial-parity-design.md` (shared ROI, bench, gold UX patterns)  
**Scope:** **Left atrium (LA)** automatic endocardial contour on **A4C ES** → **LAV 4C** (Simpson monoplane). Primary method: **fine-tune segmentation on LA gold**.

**Umbrella (future, not this spec):** RA auto (RAV 4C ES), RV auto (FAC ED+ES) — same gold/bench patterns under `gold/ra_<uid>.json`, `gold/rv_<uid>.json`.

---

## Goal

**LAV 4C Auto** with **minimal manual correction**: user on A4C end-systole frame → auto LA contour → review → Enter → LAV 4C / LAVi in overlay.

**Clinical use today:** atrial volume (LAVi), diastology context.  
**Future use:** seed boundary for **LA strain (LAS)** — per-frame LA contour is **necessary but not sufficient**; full LAS needs STE/temporal pipeline (see `2026-06-27-ste-clinical-parity-design.md`).

---

## Success gates (Tier-1 LA, ≥30 DICOM studies, A4C ES)

Gold = expert LA open arc (32 nodes) + MV landmarks + roof apex; **LAV_gold** from same `chamber_simpson` monoplane A4C ES.

| Gate | Metric | Release target | Stretch |
|------|--------|----------------|---------|
| **A** | \|ΔLAV\| vs gold Simpson | **< 8%** relative **or** **< 5 ml** absolute (pass if either met) | < 5% / < 3 ml |
| **B** | IoU (filled contour vs gold) | **> 0.78** | > 0.85 |
| **B′** | MV endpoint error (septal, lateral) | **< 12 px** @ native | < 8 px |
| **C** | Zero-edit accept (Enter as-is) | **≥ 55%** | ≥ 70% |
| **C′** | Light-edit (≤2 edits: R and/or drag) | **≥ 80%** | ≥ 90% |
| **Reject budget** | Hard reject with message | **< 20%** | < 15% |

**Accept (bench + product):** zero-edit if IoU ≥ 0.75 **or** \|ΔLAV\| gate met; light-edit same after ≤2 user actions.

---

## Explicitly out of scope (v1)

| Item | Version |
|------|---------|
| LAV **biplane** / **A2C ES** | v1.1 |
| RA / RV auto segmentation | separate specs |
| LA strain / STE integration | after LA per-frame gates |
| Temporal fusion on LA | not v1 |
| ONNX multi-class LV+LA single head | deferred; separate LA model v1 |

---

## Approach: fine-tune segmentation on LA gold (chosen)

**Not** landmark-only v1 (rejected as primary). Optional **classical fallback** only when ONNX unavailable or mask fails QC.

### Rationale

- LA cavity shape on A4C ES differs from LV; EchoNet-LV mask does not generalize.
- Existing manual path uses **elliptical open arc** (`_warp_elliptical_open_arc` in `mbs_lite_service.py`) — post-process fits template to **LA-specific mask**, not LV `open_arc_from_cavity_mask`.
- User will collect **LA gold** in parallel with LV; 30+ ES frames sufficient for **light decoder fine-tune** (frozen ResNet backbone, train head 20–40 epochs).

### Optional pretrain

- EchoNet-Dynamic / public cardiac US datasets if LA labels exist — **not required** for v1.
- Warm-start from **LV fine-tuned weights** (if available) as experiment; promote only if bench improves.

---

## Architecture

```
User: A4C ES frame → LAV 4C Auto
  → ROI v2 (DICOM, shared with LV)
  → LA ONNX (224×224, echonet_la_* manifest slot)
  → binary LA cavity mask
  → la_mask_to_contour (MV band + roof apex → ellipse resample 32 nodes)
  → refine_open_arc_contour (chamber=LA)
  → explain_la_auto_reject_reason
  → Contour(chamber=LA, phase=ES, view=A4C, review_pending=True)
  → Enter → chamber_simpson → LAV 4C
```

### Mask → contour (`la_mask_to_contour`)

New pure function in `domain/services/la_segmentation_service.py`:

1. Largest connected component; min area gate.
2. **Basal band** (inferior 15–20% of mask bbox): widest horizontal span → **MV septal / lateral** (same logic family as LV annulus, tuned for LA).
3. **Superior margin** median → **roof apex** landmark.
4. `fit_contour_from_landmarks(chamber=LA, phase=ES, view=A4C, num_nodes=32)` or direct `_warp_elliptical_open_arc` resampled to 32 nodes.
5. Endpoints forced to MV landmarks.

Fallback if mask QC fails: reject (no silent LV-style papillary path).

### Quality gate (`explain_la_auto_reject_reason`)

| Check | Reject message gist |
|-------|---------------------|
| Mask area < threshold | LA cavity too small |
| MV span < 3 mm (spacing-aware) | MV landmarks implausible |
| Apex above MV chord (image Y) | inverted LA geometry |
| Ellipse fit residual high | mask too irregular |

Residual = `1 − IoU(mask, filled contour polygon)`; reject if `> 0.35`.
| Centroid outside ROI | ROI misalignment |

---

## Gold annotation & storage

### Directory layout (shared studies with LV)

```
<gold_root>/                    # same QSettings path as LV
  gold/
    lv_<study_uid>.json
    la_<study_uid>.json         # v1 LA
    ra_<study_uid>.json         # future
    rv_<study_uid>.json         # future
  manifest.json                 # auto-updated on Save Gold (LV + LA)
```

- **Studies** (DICOM paths) referenced in `manifest.json` — **same `instance_path`** as LV tier-1 when from same loop.
- **LA gold file** is independent of LV JSON; one study may have only `la_<uid>.json` until LV gold added.

### LA gold JSON (extends Tier-1 schema)

```json
{
  "study_id": "StudyInstanceUID",
  "chamber": "LA",
  "instance_path": "optional provenance",
  "sop_instance_uid": "string",
  "pixel_spacing_mm": [row, col],
  "frames": [
    {
      "frame_index": 98,
      "phase": "ES",
      "view": "A4C",
      "chamber": "LA",
      "mitral_annulus": [[sx, sy], [lx, ly]],
      "apex_landmark": [ax, ay],
      "points": [[x, y], ...],
      "source": "manual|ai_corrected",
      "annotator": "",
      "annotated_at": "ISO8601"
    }
  ]
}
```

**Annotation workflow:** LAV 4C manual (3 clicks) → R/drag → Enter → **Save gold** (context menu, gold mode on) → writes `gold/la_<study_uid>.json`.

**Target:** ≥30 studies × **1 frame** (A4C ES); same studies as LV tier-1 when possible.

### Save Gold UX (extension)

- Reuse `gold_annotation_enabled` + `gold_dataset_path` from preferences.
- Filename from `gold_filename(study_uid, chamber)` → `la_<study_uid>.json` under `gold/`.
- Context menu item when accepted **LA** contour on current frame.
- `save_gold_annotation`: `chamber` parameter; **LA rejects** non-`ES` phase and non-`A4C` view.

---

## Training & ONNX export

### Script

`scripts/finetune_la_seg.py` (new):

- Input: `gold_root/gold/la_*.json` + `instance_path` + `frame_index`.
- Rasterize gold `points` → binary mask (fill polygon).
- Crop: same `crop_frame_for_echonet` + ROI as inference.
- Augment: horizontal flip (A4C), gamma, speckle noise — **no vertical flip**.
- Loss: BCE + Dice on LA mask.
- Export: `models/echonet_la_resnet50_224.onnx` + manifest entry `echonet_la_resnet50_224`.

### Manifest slot

```json
"echonet_la_resnet50_224": {
  "id": "echonet_la_resnet50_224",
  "filename": "echonet_la_resnet50_224.onnx",
  "description": "LA cavity segmentation A4C ES (fine-tuned)",
  "onnx": { "input_shape": [1, 3, 224, 224], ... }
},
"la_inference": {
  "active_model": "echonet_la_resnet50_224",
  "crop_mode": "full_roi",
  "auto_refine_after_segment": true
}
```

Separate from LV `active_model` — controller selects LA engine when `request_la_auto_segment`.

---

## Application integration

### Entry points

| UI | Action |
|----|--------|
| Measures → **LAV 4C Auto** (new) or LAV 4C long-press | `request_la_auto_segment()` |
| Review | Enter / Esc / R (same as LV AI review) |

### Controller

- `request_la_auto_segment()` — mirrors LV path: phase=ES, view=A4C, chamber=LA.
- `_on_la_auto_segment_finished` — `la_mask_to_contour` → refine → reject gate → `review_pending`.
- No temporal fusion.

### Files (new / changed)

| File | Change |
|------|--------|
| `domain/services/la_segmentation_service.py` | **Create** — mask→contour, LA QC |
| `domain/calculations/chamber_simpson.py` or new | `explain_la_auto_reject_reason` |
| `infrastructure/onnx_engine.py` or `la_onnx_engine.py` | LA model load |
| `application/app_controller.py` | LA auto segment + gold chamber prefix |
| `domain/services/gold_store.py` | optional `chamber` field validation |
| `presentation/main_window.py` | LAV 4C Auto menu action |
| `scripts/finetune_la_seg.py` | **Create** |
| `scripts/run_la_auto_bench.py` | **Create** (or `run_lv_auto_bench.py --chamber LA`) |
| `models/model_manifest.json` | LA model slot |
| `tests/unit/test_la_segmentation_service.py` | **Create** |
| `tests/unit/test_gold_store.py` | LA schema cases |

---

## Bench

`scripts/run_la_auto_bench.py --gold-root <gold_root>`

Per study: load A4C ES frame → LA auto pipeline → IoU, MV errors, LAV vs gold (absolute mL and relative %) → CSV summary. Gate A: median \|ΔLAV\| **< 5 ml** or median relative **< 8%**; per-study pass rate reported separately.

**Baseline:** before fine-tune, report `reject_rate=100%` or landmark-only stub — documents delta.

---

## Testing

### Unit

- `la_mask_to_contour` on synthetic ellipse masks.
- Gold LA JSON round-trip with `chamber: LA`.
- `explain_la_auto_reject_reason` edge cases (incl. ellipse-fit residual vs mask).
- Save gold writes to `gold/la_<uid>.json`.

### Manual

1. DICOM A4C ES: LAV 4C Auto → plausible oval LA → Enter → LAV 4C reasonable.
2. Save gold → `gold/la_<uid>.json` valid.
3. Re-open study → bench row for study.

---

## Implementation phases

| Phase | Deliverable |
|-------|-------------|
| **LA-0** | Gold UX: `gold/la_<uid>.json`, LA Save Gold, shared `manifest.json` |
| **LA-1** | `la_mask_to_contour` + QC + unit tests (synthetic masks) |
| **LA-2** | `finetune_la_seg.py` + export ONNX (after ≥10 gold) |
| **LA-3** | Controller + LAV 4C Auto UI + review UX |
| **LA-4** | Bench + gates on ≥30 gold; iterate fine-tune |
| **LA-1.1** | A2C ES + LAV biplane (separate spec) |

**Dependency:** LV ROI v2 from commercial parity spec should land first or in parallel (shared ROI code).

---

## Relation to other specs

| Spec | Relation |
|------|----------|
| `2026-07-06-lv-auto-commercial-parity-design.md` | Shared gold_root, ROI, bench patterns |
| `2026-06-27-ste-clinical-parity-design.md` | LAS uses LA contour as future seed |
| `2026-06-22-rv-fac-design.md` | RV manual; auto RV later |
| Chamber roadmap in LV commercial parity | LA v1 = this spec |

---

## Risks

| Risk | Mitigation |
|------|------------|
| LA mask confused with LV cavity | Train LA-only; QC on mask position (superior to LV) |
| ES frame choice variable | Gold on user-selected ES; bench uses manifest `es_frame` |
| Small LA on foreshortened views | Reject + manual; expand gold diversity |
| <30 gold studies | Start bench at N=10; gate at N≥30 |

---

Implementation plan via `writing-plans` → `docs/superpowers/plans/2026-07-06-la-auto-segmentation.md`.
