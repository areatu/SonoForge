# LV Auto Commercial Parity v2 — DICOM-First Segmentation & LVEF

**Date:** 2026-07-06  
**Status:** Approved (brainstorming)  
**Supersedes:** extends `2026-07-05-lv-auto-onnx-quality-design.md` (v1.5) and `2026-07-05-lv-auto-temporal-fusion-design.md` (v1.6)  
**Scope:** A4C LV Auto → Simpson monoplane EDV/ESV → LVEF on **native DICOM**, approaching commercial-grade accuracy (10–15 y.o. systems) via measurable gates, Tier-1 bench, pipeline v2, optional fine-tune.

---

## Goal

Reliable **LV endocardial segmentation** and **automatic LVEF** (Simpson monoplane A4C) with **minimal manual correction** — median LVEF error and contour quality comparable to legacy commercial echo software, achievable with modern open-source models + domain adaptation.

**Primary user workflow unchanged:** user seeks ED/ES frames → LV Auto EDV/ESV → review → Enter → LVEF in overlay.

**Chamber roadmap:** LV v2.0 (this spec) → LA quick contour v2.1+ (out of scope here).

---

## Success gates (Tier-1 bench, ≥50 DICOM studies)

Gold reference = **expert contours + MA** on selected ED/ES frames; LVEF_gold computed with **same** `lvef_simpson` monoplane A4C in-app. Standard comparison optional later (`echopac_lvef` field); **not required** for release gate.

| Gate | Metric | Release target | Stretch |
|------|--------|----------------|---------|
| **A** | median \|ΔLVEF\| vs gold Simpson | **< 5%** | < 3% |
| **B** | Mask IoU vs gold endo | **> 0.82** | > 0.88 |
| **B′** | Annulus endpoint error (each) | **< 10 px** @ native | < 6 px |
| **C** | Zero-edit accept (Enter as-is) | **≥ 60%** frames (ED+ES pooled) | ≥ 75% |
| **C′** | Light-edit accept (≤2 edits: R and/or drag) | **≥ 85%** | ≥ 90% |
| **Reject budget** | Hard reject with clear message | **< 15%** on typical A4C ED/ES | < 10% |

**Accept definition (bench + product):**

- **Zero-edit:** Auto contour → Enter without drag/R → \|ΔLVEF\| ≤ 5% vs gold **or** IoU ≥ 0.80.
- **Light-edit:** ≤2 user actions (R-refine counts as 1; each drag session on a node group counts as 1) → same thresholds.

**Failure philosophy:** Reject with actionable Russian/English message **better than** showing a clinically wrong contour.

---

## Annotation strategy (Tier-1 vs Tier-2)

### Tier-1 (required) — 50+ studies × ED + ES

- **Priority over** dense per-frame labeling on few loops.
- **Minimum per frame:** open-arc endo points (32 nodes), MA septal + lateral, `frame_index`, `phase`, `study_uid`, `sop_instance_uid`.
- **Workflow:** manual or AI-assisted (LV Auto → R → drag → Enter) then **Save as gold**.
- **Diversity:** maximize scanner/vendor/patient spread; avoid >3 studies from same machine model if possible.
- **Fine-tune input:** ~100 frames (50 ED + 50 ES) sufficient for light decoder fine-tune.

### Tier-2 (optional, after Tier-1 gates) — 3–5 loops × 8–12 frames

- Dense temporal labels for STE / fusion v2 research **only after** per-frame Gate A stable.
- **Not a substitute** for Tier-1 diversity (7–10 loops alone overfits).

---

## Explicitly out of scope (v2.0)

| Item | Reason |
|------|--------|
| LA / RA auto segmentation | v2.1+ |
| STE as required path to LVEF | Per-frame must work first |
| Temporal fusion default-on | Off until Gate A met; v1.6 remains flag |
| Standard import / SR parsing | Optional manifest field only |
| int8 ONNX / TTA ensemble | After fp32 gates pass |
| A2C auto model | Separate spec |
| Full ED→ES tracking | Future |

---

## Architecture overview

```
[DICOM A4C instance]
  → View/quality pre-gate (future: heuristic; v2.0: existing reject paths)
  → ROI v2 (SequenceOfUltrasoundRegions + guarded sector trim)
  → Seg model v2 (224×224 fp32, crop_mode from bench winner)
  → Mask post-process (v1.5 phase-aware + long_axis_hint)
  → Landmark layer (mask geometry primary; classical fallback if MA fail)
  → open_arc_from_cavity_mask → papillary → refine_open_arc_contour
  → Quality gate v2 (mask px, arc depth, MA span vs spacing)
  → Contour(review_pending=True)  OR  reject + explain_lv_auto_reject_reason
  → User review (Enter / R / drag)
  → lvef_simpson.calculate() monoplane A4C
```

**Temporal fusion (`temporal_fusion.enabled`):** default **`false`** in v2.0 manifest until Tier-1 Gate A passes on baseline without fusion.

---

## 1. Tier-1 bench infrastructure

### 1.1 Directory layout

```
bench/
  tier1/
    manifest.yaml          # study list, paths, ed_frame, es_frame, tags
    gold/
      <study_id>.json      # ED + ES contours + metadata
    reports/
      baseline_v16.csv     # per-run bench output
      v2_pipeline.csv
```

### 1.2 Gold JSON schema (per study)

```json
{
  "study_id": "string",
  "instance_path": "relative/or/absolute",
  "sop_instance_uid": "string",
  "pixel_spacing_mm": [row, col],
  "frames": [
    {
      "frame_index": 12,
      "phase": "ED",
      "mitral_annulus": [[sx, sy], [lx, ly]],
      "points": [[x, y], ...],
      "source": "manual|ai_corrected",
      "annotator": "string",
      "annotated_at": "ISO8601"
    }
  ],
  "optional": {
    "scanner_vendor": "GE|Philips|Siemens|...",
    "echopac_lvef": null
  }
}
```

### 1.3 Bench runner

**Script:** `scripts/run_lv_auto_bench.py`

For each manifest entry × {ED, ES}:

1. Load DICOM frame (display buffer policy = production).
2. Run auto-segment pipeline (configurable manifest / model id).
3. Compute: mask IoU, annulus endpoint L2 error, LVEF_auto vs LVEF_gold, zero-edit accept, light-edit accept (simulated: optional gold+noise not used — real pipeline only).
4. Emit CSV + summary row (medians, accept rates, reject rate).

**Baseline run (Phase 2a):** current v1.6 before any v2 code — establishes delta.

### 1.4 Norm calibration

Extend `scripts/calibrate_echonet_norm.py` to consume Tier-1 manifest; write `fixed_mean/std` recommendation for `model_manifest.json`.

---

## 2. Pipeline v2 (inference)

### 2.1 Model upgrade — 224×224 ONNX

- Re-export EchoNet-Dynamic seg branch at **224×224** (Phase B from v1.5 spec).
- Manifest entry: same model id or `echonet_seg_resnet50_224`.
- `prepare_tensor` / crop / embed paths support 112 and 224 via manifest `input_shape`.
- **Promotion rule:** Tier-1 median \|ΔLVEF\| improves ≥0.5% vs 112 without IoU regression.

### 2.2 Crop mode A/B

- Compare `center_square` vs `full_roi` on Tier-1.
- Ship winner as default `inference.crop_mode`.
- Hypothesis: `full_roi` reduces «mask too small» on wide-sector DICOM.

### 2.3 ROI v2 (DICOM-first)

**File:** `domain/services/segment_roi.py`, `app_controller._resolve_segment_roi_bounds`

| Step | Action |
|------|--------|
| 1 | `SequenceOfUltrasoundRegions` bounds (unchanged primary) |
| 2 | Guarded sector trim: `_trim_sector_content_bounds` with **apex guard** — abort trim if removed area > 15% height or apex band empty |
| 3 | Lateral column trim inside B-mode strip (existing) |
| 4 | Debug: `_last_segment_roi_xyxy` overlay (already implemented) |

Cine/MP4 ROI improvements deferred to **v2.1** unless Tier-1 includes MP4 subset.

### 2.4 Landmark layer (v2.0 — no separate CNN required)

**Problem:** `open_arc_from_cavity_mask` raises «cannot locate mitral annulus» on fragmented ONNX masks.

**Layer order:**

1. **Primary:** existing mask geometry (`_annulus_and_apex_from_mask_pixels`).
2. **Fallback A:** largest cavity component re-fill + wider annulus band (12% → 18% height) once.
3. **Fallback B:** sector chord — widest horizontal span in basal 25% of ROI → provisional MA; apex = distal median of mask.
4. **Fallback C (optional v2.0.1):** 2-point MA regressor ONNX if Fallback A–B still >20% fail rate on Tier-1 **with mask_px ≥ threshold**.

Landmarks feed `open_arc`; fused temporal annulus logic unchanged when fusion disabled.

### 2.5 Quality gate v2

Extend `explain_lv_auto_reject_reason` and pre-open-arc checks:

| Check | Action |
|-------|--------|
| `mask_pixels < 80` (native) | Reject: mask too small |
| MA length < 3 mm (spacing-aware) | Reject: annulus implausible |
| Arc depth < 0.15 × MA length | Reject: collapsed cavity |
| Mask centroid outside ROI | Reject: ROI misalignment |

Log all rejects in bench CSV with reason code.

### 2.6 Post-process

Retain v1.5: adaptive Otsu, embed order=1, phase papillary, auto_refine, long_axis_hint closing.

### 2.7 Diagnostics

Generalize `cine_segment_diagnostics.py` → `segment_diagnostics.py` with `media_format=dicom`; used by bench runner and CLI `scripts/diagnose_dicom_segment.py`.

---

## 3. Fine-tune (Phase 2d, conditional)

**Entry condition:** After pipeline v2 inference, Tier-1 fails Gate A (<5%) **or** Gate C (<60%) **and** error analysis shows systematic mask bias (not ROI-only).

**Data:** Tier-1 gold ~100 masks; optional EchoNet-Dynamic / CAMUS pretrain.

**Training:**

- Freeze ResNet backbone; train DeepLab decoder + optional last backbone blocks.
- Augment: flip (A4C-safe horizontal), gamma, light speckle noise.
- Export ONNX 224 → manifest slot `echonet_seg_resnet50_ft`.
- Re-run bench; promote if gates pass.

**Script:** `scripts/finetune_echonet_seg.py` (new).

---

## 4. UX — gold annotation & review

### 4.1 Gold export — инструменты, путь, включение

#### Чем размечаете (те же инструменты, что в продукте)

| Шаг | Инструмент в приложении |
|-----|-------------------------|
| Контур ЛЖ | **LV Manual** (open arc) **или** **LV Auto EDV/ESV** → при необходимости **R** (refine) + drag узлов |
| MA | Входит в open arc: septal + lateral при завершении контура (или из AI после Enter) |
| Калибровка | Существующая B-mode калибровка (нужна для mm/px в gold JSON) |
| Принятие | **Enter** — контур должен быть **принят** (`review_pending=false`) перед Save Gold |

Отдельного «редактора разметки» нет — вы работаете в обычном viewer, gold пишется поверх принятого контура.

#### Куда записывается

```
<gold_root>/
  manifest.yaml              # список studies (создаётся/дополняется автоматически)
  gold/
    <study_id>.json          # ED + ES (и др. фазы) для одного исследования/loop
```

- **По умолчанию `gold_root`** = `{repo}/bench/tier1` при разработке; в настройках — **любая папка** (например вне git: `~/ECHO2026-gold/`).
- **`<study_id>`** = `StudyInstanceUID` (или hash path, если UID недоступен).
- **Формат** — JSON из §1.2; одна запись `frames[]` на каждый сохранённый кадр (merge по `frame_index` + `phase`).
- Bench-скрипт `scripts/run_lv_auto_bench.py` читает тот же `manifest.yaml`.

#### Как включается режим

**Да — через настройки**, не только env:

| Способ | Назначение |
|--------|------------|
| **Настройки → «Разметка gold (Tier-1)»** | Основной для вас: чекбокс + поле «Папка набора» |
| `ECHO_GOLD_EXPORT=1` | Override для CI/скриптов без UI |
| Сохраняется в `QSettings` (`gold_annotation_enabled`, `gold_dataset_path`) | Переживает перезапуск |

Пока режим **выключен**, пункт Save Gold в меню **не показывается** (обычные пользователи не видят).

#### Как вызвать Save Gold

**Да — контекстное меню на окне просмотра** (ПКМ по изображению в `ViewerWidget`), когда:

1. `gold_annotation_enabled == true`
2. Открыт **DICOM** loop
3. На **текущем кадре** есть **принятый** LV contour A4C (`review_pending=false`, `chamber=LV`)
4. Задан phase context (ED/ES из Simpson workflow или phase на контуре)

**Пункты меню (RU):**

- «Сохранить gold — ED (кадр N)»
- «Сохранить gold — ES (кадр N)»
- или один пункт «Сохранить gold для текущего кадра», если phase уже на контуре

После сохранения: status bar «Gold сохранён: …/gold/<study_id>.json (ED, frame 12)».

**Не в v2.0:** отдельное контекстное меню на thumbnail/gallery (можно добавить позже).

**Опционально v2.0.1:** после Enter на AI-контуре — немodal «Сохранить в gold?» (можно отключить в настройках).

#### Поля в gold JSON

`points`, `mitral_annulus`, `apex_landmark`, `frame_index`, `phase`, `view`, `study_uid`, `sop_instance_uid`, `pixel_spacing_mm`, `source` (`manual` | `ai_corrected`), `annotator` (из настроек или OS user), `annotated_at`.

### 4.2 Annotation workflow (recommended)

1. Open DICOM A4C loop in app.
2. Seek ED → LV Auto EDV (or manual LV open arc).
3. R-refine + minimal drag → Enter.
4. Save gold (ED).
5. Repeat ES → ESV.
6. Next study.

**Target:** 50 studies × 2 frames ≈ **100 gold frames** over 2–4 weeks parallel with pipeline work.

### 4.3 User-facing reject messages

Map internal codes → existing i18n keys; add if missing:

| Code | User message (RU gist) |
|------|------------------------|
| `mask_too_small` | Маска слишком мала — проверьте A4C ED/ES, gain, ROI (debug G) |
| `ma_not_found` | Не найдено митральное кольцо — ручной контур или другой кадр |
| `arc_collapsed` | Контур слишком плоский — возможно ES или не тот view |
| `roi_misalign` | ROI не совпадает с сектором — сообщите в debug overlay |

Bench records machine-readable `reject_code`.

### 4.4 Review UX (unchanged)

Enter accept, Esc discard, R refine, drag nodes — no new hotkeys for v2.0.

---

## 5. Testing

### 5.1 Unit tests

| Area | Tests |
|------|-------|
| ROI v2 apex guard | trim skipped when apex band clipped |
| Landmark fallbacks | synthetic masks: fragmented → Fallback A succeeds |
| Quality gate v2 | spacing-aware MA length reject |
| 224 embed roundtrip | mask shape preserved |
| Gold JSON I/O | round-trip export/import |

### 5.2 Bench (CI optional, local required)

```bash
python scripts/run_lv_auto_bench.py --manifest bench/tier1/manifest.yaml --report bench/tier1/reports/latest.csv
```

**CI:** smoke on 3 synthetic/small gold fixtures; full Tier-1 run manual pre-release.

### 5.3 Manual checklist

1. 10 diverse DICOM A4C: ED Auto → contour plausible → Enter → LVEF reasonable vs prior manual.
2. Same 10 ES: smaller cavity, fewer papillary notches after v2.
3. Debug overlay: ROI excludes UI, includes LV apex.
4. Reject cases: PLAX loop → clear message, no garbage contour.
5. Gold export: one study → JSON valid → bench picks it up.

---

## 6. Implementation phases

| Phase | Deliverable | Depends on |
|-------|-------------|------------|
| **2a** | Tier-1 manifest template, gold schema, export hook, `run_lv_auto_bench.py`, **baseline report v1.6** | — |
| **2b** | 224 export, crop A/B, ROI v2, landmark fallbacks, gate v2, diagnostics | 2a baseline |
| **2c** | Tier-1 annotation (50+ studies, parallel) | 2a export |
| **2d** | Fine-tune + ft ONNX if gates fail | 2b + 2c |
| **2e** | Tier-2 dense (optional), temporal fusion re-enable eval | Gate A pass |

**Manifest v2.0 defaults:**

```json
"inference": {
  "crop_mode": "full_roi",
  "auto_refine_after_segment": true
},
"temporal_fusion": {
  "enabled": false
}
```

(Crop mode final value set by Tier-1 A/B.)

---

## 7. Relation to other specs

| Spec | Relation |
|------|----------|
| `2026-07-05-lv-auto-onnx-quality-design.md` | v1.5 — retained post-process |
| `2026-07-05-lv-auto-temporal-fusion-design.md` | v1.6 — disabled by default until gates |
| `2026-06-19-onnx-lv-auto-segment-design.md` | v1 base UX |
| `2026-06-27-ste-clinical-parity-design.md` | STE after per-frame parity |

---

## 8. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| 50 gold studies slow to collect | Start 2a bench at N=10, extrapolate; fine-tune at N≥30 if trend clear |
| 224 model slower | Accept for accuracy; int8 later |
| Sector trim clips apex | Apex guard + A/B on Tier-1 |
| Fine-tune overfits 50 studies | Strong aug + frozen backbone + hold-out 10 studies |
| No Standard | Gold Simpson LVEF is primary gate; Standard optional later |

---

Implementation plan via `writing-plans` → `docs/superpowers/plans/2026-07-06-lv-auto-commercial-parity.md`.
