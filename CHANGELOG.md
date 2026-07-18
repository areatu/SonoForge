# CHANGELOG — ECHO Personal Tool

Все значимые изменения в хронологическом порядке. Формат: `[feat/fix/refactor/perf/docs/chore]: описание` (コミット-конвенция).

---

## 2026-07-18

### Features
- `feat(mmode)`: Teichholz LV function calculation from M-mode calipers — 3 sequential calipers (МЖП→КДР→ЗСЛЖ) с chain-логикой, ESV measurement после подсветки, results в overlay (КДО, КСО, ФВ, ОТС, ММЛЖ, ИММЛЖ)

### Fixes
- `fix(mmode)`: fix Teichholz overlay integration — use `app_controller._current_study_uid`, store measurements as LinearMeasurement objects

### Refactor
- `refactor`: replace commercial brand names (Standard, Research, Device, GE, Clinical) с generic-названиями в коде и документации
- `refactor`: rename `echopac_theme.py` → `dark_theme.py`, functions → `apply_clinical_theme`, `build_clinical_stylesheet`, `preset_standard`, `preset_research`

### Chore
- `chore`: project cleanup for trial release — удалены debug-логи, old/, orphan-директории, backup-файлы, кэши
- `chore`: dependencies fix — добавлены pyyaml, jsonschema, onnxruntime, reportlab, openpyxl в required; убран black; hatch version source
- `docs`: update README — актуализация возможностей, требований, установки
- `docs`: update ROADMAP — хронология major changes (июнь–июль 2026)
- `fix`: update tests for renamed methods (preset_standard → preset_standard, preset_research → preset_research)

---

## 2026-07-17

### Fixes
- `fix(constructor)`: save/reload + focus + validation + Enter key

---

## 2026-07-16

### Features
- `feat(mmode)`: smooth expand/collapse animation + 50% taller panel

### Fixes
- `fix(mmode)`: rebuild layout on deactivation + sweep speeds 25/37.5/50
- `fix(mmode)`: restart scan line placement after file switch
- `fix(mmode)`: reset M-mode on file switch — stop playback, clear scan line, clear buffer

### Docs
- `docs`: add LV-geometry, LA_volume, LV_linear_sizes images to references

---

## 2026-07-15

### Features
- `feat(mmode)`: post-processing pipeline — brightness, gamma, stronger smoothing (reverted)
- `feat(mmode)`: post-processing on frozen frames + sliders control M-mode strip (reverted)

### Fixes
- `fix(mmode)`: ensure tool_panel visible after M-mode deactivation
- `fix(mmode)`: find viewer index before reparenting to vertical splitter
- `fix`: remove stale vertical_lock_toggled connection + downgrade diagnostic logs to debug

---

## 2026-07-14

### Features
- `feat(mmode)`: heart rate (ЧСС) в horizontal measurement label
- `feat(mmode)`: horizontal lock для horizontal measurement + guide lines preview
- `feat(mmode)`: vertical lock + guide lines для vertical measurement
- `feat(mmode)`: perpendicular guide lines во время vertical lock mode
- `feat(mmode)`: vertical lock toggle button к MModeWidget

### Fixes
- `fix(mmode)`: simplify deactivate — directly manipulating splitter вместо full rebuild
- `fix(mmode)`: use detected depth ticks (5cm intervals) для depth calibration
- `fix(mmode)`: use vertical depth (dy × row_spacing) вместо Euclidean distance

---

## 2026-07-13

### Features
- `feat(mmode)`: measurement tools — vertical (depth), horizontal (time), arbitrary с guide lines к axes
- `feat(mmode)`: smart smoothing — log compression + spatial Gaussian + temporal EMA

### Fixes
- `fix(mmode)`: scale ImageItem к physical units чтобы axes показывали реальные mm/ms
- `fix(mmode)`: update image rect когда sweep speed меняется чтобы X axis rescale
- `fix(mmode)`: use M-mode specific calibration для depth axis
- `fix(mmode)`: use both X и Y pixel spacing для depth calibration
- `fix(mmode)`: store view ref чтобы properly remove old caliper nodes

---

## 2026-07-12

### Features
- `feat(mmode)`: show first caliper point с preview, allow multiple calipers в session
- `feat(mmode)`: close button (×) к M-mode panel
- `feat(mmode)`: DICOM calibration — vertical axis cm (from pixel_spacing), horizontal ms (from frame_time)
- `feat(mmode)`: status bar hints для M-mode activation и scan line placement

### Fixes
- `fix(mmode)`: complete anatomical M-mode implementation с integration tests
- `fix(mmode)`: C++ object lifecycle в activate/deactivate
- `fix(mmode)`: extract columns durante playback (show_frame_fast)
- `fix(mmode)`: use _rebuild_layout() на deactivate

---

## 2026-07-11

### Features
- `feat(mmode)`: MModeCaliperTool для distance/time measurements
- `feat(mmode)`: connect M-mode extraction pipeline в AppController и MainWindow
- `feat(mmode)`: scan line tool и column extraction к ViewerWidget
- `feat(mmode)`: vertical splitter layout toggle в MainWindow
- `feat(mmode)`: MModeWidget PyQtGraph panel с sweep display
- `feat(mmode)`: M-mode column extractor через bilinear interpolation
- `feat(mmode)`: domain models для anatomical M-mode

---

## 2026-07-10

### Features
- `feat`: StructuredReferenceWidget теперь использует tables вместо cards
- `feat`: column visibility toggles + units combined с values в reference viewer
- `feat`: reference constructor — visual editor для structured reference handbook
- `feat`: reference guide — default section, smart scaling, card layout

### Fixes
- `fix`: styled file dialogs с dark theme для navigation buttons
- `fix`: replace Unicode arrows с ASCII для лучшей font compatibility
- `fix`: validation — allow same param через gradations
- `fix`: image copy SameFileError + merge LA pathologies + restructure RV

---

## 2026-07-09

### Features
- `feat`: Properties panel показывает height, weight, BMI, frame time, frames count
- `feat`: auto-detect spectrogram ROI для Doppler fallback
- `feat`: overlay — color-coded out-of-range values + click-to-reference navigation

### Fixes
- `fix`: per-instance measurements, overlay isolation, playback reset
- `fix`: auto-fill height/weight от DICOM tags на каждом file switch
- `fix`: reference widget image scaling, context menu, gradation table
- `fix`: critical bugs + Doppler calibration overhaul

---

## 2026-07-08

### Features
- `feat(la)`: LA-2 finetune + LA-3 controller/UI + LA-4 bench
- `feat(la)`: LA-0 gold UX + LA-1 la_mask_to_contour + quality gate
- `feat(gold)`: per-instance deduplication + multi-DICOM study support
- `feat(gold)`: UI tab в preferences + ECHO_GOLD_EXPORT env var override
- `feat(lv-auto)`: commercial parity v2 — bench infra + pipeline upgrades (Phase 2a+2b)
- `feat(lv-auto)`: diagnostics generalization + temporal fusion v2 (Phase 2b.6 + 2e)
- `feat(onnx)`: debug ROI overlay — §1.4 spec

### Fixes
- `fix(gold)`: auto-update manifest.json на Save Gold
- `fix(gold)`: show 1-based frame number в save message
- `fix(gold)`: per-frame instance_path + update on merge от different file
- `fix(onnx)): temporal fusion P0+P1 — hang, wrong annulus ref, missing refine
- `fix(onnx)`: temporal fusion P2+P3 — apex ratio, alignment, i18n, G key
- `fix(onnx)`: fusion_result sync, partial early-exit, new tests
- `fix(onnx)`: cine ROI cached от first loaded frame, не только frame 0
- `fix(onnx)`: revert crop_mode к center_square + per_frame normalization

---

## 2026-07-07

### Features
- `feat(onnx)`: temporal fusion — neighbor-aware contour на frame N
- `feat(onnx)`: LV Auto quality v1.5 — per-frame segmentation improvements

### Fixes
- `fix(onnx)`: temporal fusion callback signature — mask как first positional arg
- `fix(onnx)`: v1.5 deviations — long_axis_hint, upscale_mask, spec notes

---

## 2026-07-06

### Features
- `feat`: add structured reference browser к AseReferenceDialog
- `feat`: add images для AK и LV pathologies, improve image scaling
- `feat`: multi-image support, image navigation, и real pathology images
- `feat(ste)`: Phase 11 — Save/Export Deformation Data
- `feat(ste)`: Phase 10 — Manual Kernel Correction
- `feat(ste)`: Phase 9 — Quality Control Checkboxes
- `feat(ste)`: Phase 8 — Display Mode Toggle (Deformation/SR/Peak)
- `feat(ste)`: Phase 7 — Strain Curves View
- `feat(ste)`: Phase 6 — Summary Table (clinical-style)
- `feat(ste)`: Phase 5 — Bull's Eye Plot (17-segment polar map)
- `feat(ste)`: Phase 4 — Myocardial Contour + Kernels + Labels + ECG
- `feat(ste)`: Phase 3 — Strain Window Shell + Quad-View Layout
- `feat(ste)`: Phase 2 — Quality-Weighted GLS Computation
- `feat(ste)`: Phase 1 — Quality Threshold Gate

### Fixes
- `fix(ste)`: critical blockers — n_kernels + quality gate + QC checkboxes
- `fix(ste)`: QC checkboxes — make _qc_group и _qc_layout proper attributes
- `fix(ste)`: spline degree check — prevent crash с few frames
- `fix(ste)`: use cached frames directly — avoid main thread blocking
- `fix(ste)`: auto-load all frames перед speckle tracking

---

## 2026-07-05

### Fixes
- `fix`: contextMenuEvent wrong super call + finetune experiments
- `fix`: bench — exclude 7 bad gold files + fix finetune normalisation + engine crop_mode
- `fix`: invisible checkboxes в tree widgets через все themes
- `fix`: controls slider desync + overlay persistence на file switch

### Bench
- `bench`: Add temporal smoothing к bench contour pipeline
- `bench`: Add bench report — temporal smoothing results (105 instances)
- `bench`: Add LVEF reject gate (|ΔLVEF| > 15%)
- `bench`: Add LV segmentation fine-tune script (decoder head training)
- `bench`: Improve annulus boundary snap — use MA midpoint split + wider search radius

---

## 2026-07-04

### Features
- `feat(micro-UX)`: focus/disabled QSS, reduce_motion, caliper chain, gray frame fix
- `feat`: properties panel, i18n, multiview fixes
- `feat`: DIMSE Phase 2 — C-GET, C-MOVE, DIMSE-only, TLS

### Fixes
- `fix`: DIMSE Phase 2 minor gaps — wiring, auto ping, C-MOVE SCP
- `fix`: critical issues K1-K6, properties panel, i18n, multiview

---

## 2026-07-03

### Features
- `feat`: comprehensive benchmark suite — 52 benchmarks через 6 categories
- `feat`: server profiles — save/load/delete named connection presets
- `feat`: STOW/DIMSE upload UI, live Orthanc tests, query_source persist

### Fixes
- `fix`: auto-check series на study expand — load button now enables immediately
- `fix`: DICOM Rows error, activity bar text buttons с i18n
- `fix`: benchmark cache-hit bug, add Linux/Windows comparison

---

## 2026-07-02

### Features
- `feat`: Ctrl+Scroll zoom, reference tab close, STOW batch upload, FPS benchmarks
- `feat`: i18n complete — measurement_tools, system_bar, activity_bar, tool_panel, doppler, indexed
- `feat`: references dialog rewrite, caliper fixes, auto-play guard

### Fixes
- `fix`: i18n keys — measures_menu stores keys не strings
- `fix`: references dialog — visible title bar buttons, keyboard nav, ctrl+scroll zoom

---

## 2026-07-01

### Features
- `feat`: frameless Load from Server dialog, connected caliper sequence для IVSd-LVEDD-LVPWd
- `feat`: profiling instrumentation, playback optimizations, color Doppler fix

### Performance
- `perf`: Phase 1 micro-optimizations — deque ring buffer, memoize frames, faster eviction
- `perf`: Phase 2 — RGB identity cache для color Doppler, double-next skip
- `perf`: Phase 3 — parallel DICOM batch decode, adaptive prefetch batch sizing
- `perf`: Phase 4 — small-loop full prefetch, directional scroll neighbors
- `perf`: Phase 5 — zero-copy uncompressed DICOM frame decode

---

## 2026-06-30

### Features
- `feat`: activity bar icons, auto-play, overlay context menu
- `feat`: caliper drag/release, Windows geometry, playback warm-up, overlay study-pin
- `feat`: display quality — debug overlay, smooth scaling, zoom modes
- `feat`: i18n infrastructure + partial UI translation
- `feat`: i18n bulk translation — viewer, main_window, dialogs, formatters
- `feat`: i18n app_controller speckle status messages

### Fixes
- `fix`: caliper drag correction, i18n, monochrome themes, UI fixes
- `fix`: emit decode_finished на first frame, use DicomSession в FrameLoaderWorker
- `fix`: viewer2 — independent frame navigation через FrameCache

---

## 2026-06-29

### Features
- `feat`: DICOM auto-fill patient height/weight, Play/Pause fixed width
- `feat`: frameless window — VS Code style title bar
- `feat`: VS Code layout system — 5 toggleable modes

### Performance
- `perf(dicom)`: P0 scroll — debounce, two-phase load, fast display
- `perf(dicom)`: P1 BOT index через pydicom.encaps для JPEG multiframe
- `perf(dicom)`: JPEG-2000 frame index с openjpeg и EOT support
- `perf(mp4)): keyframe index и scroll min_buffer prefetch

---

## 2026-06-28

### Features
- `feat`: context menus — save frame как JPEG/PNG с overlays, thumbnail export DICOM/MP4

### Performance
- `perf`: skip DICOM I/O durante playback, pin current frame

### Fixes
- `fix`: measurement overlay accumulation

---

## 2026-06-27

### Features
- `feat`: caliper inline labels, B-mode snap, auto depth calibration
- `feat`: cine playback prefetch pipeline — adaptive buffer, timing compensation, loop wrap

---

## 2026-06-26

### Performance
- `perf`: DICOM decode 86x faster first-frame — raw-byte extraction, cv2 fast path

### Features
- `feat`: lazy DICOM/MP4 frame decoding — instant first frame, on-demand scroll, adaptive playback

---

## 2026-06-25

### Features
- `feat`: UI improvements — theme support, STE popup, cine contour fixes
- `feat`: STE quality improvements — iterative refinement, weighted smoothing, motion model
- `feat`: STE clinical parity — progressive zone deformation, preprocessing, outlier interpolation

### Fixes
- `fix`: Orthanc multi-study download, play freeze, DICOM/MP4 performance

---

## 2026-06-24

### Features
- `feat`: NCC block-matching speckle tracking с dual-contour zone и strain computation
- `feat`: speckle tracking result storage, launch menu, overlay improvements
- `feat`: per-instance WADO-RS downloads, parallel loading, progressive decode

### Refactor
- `refactor`: replace Lamé LV contour с Bézier cubic spline (ED S-shape, ES smooth)

---

## 2026-06-23

### Features
- `feat`: DICOMweb Orthanc integration — QIDO-RS, WADO-RS, session cache, mock offline
- `feat`: Orthanc download worker, study browser dialog, server settings
- `feat`: RV FAC workflow с crescent template

### Fixes
- `fix`: Orthanc download cancel, cumulative progress, client lifecycle
- `fix`: parse series instance count от QIDO tag 00201209

---

## 2026-06-22

### Features
- `feat`: measurement workflow sprint — planimeter, ASE norms, PDF report, cine ROI
- `feat`: Orthanc DICOMweb domain DTOs и port

---

## 2026-06-21

### Features
- `feat`: merge Clinical UI в ONNX LV Auto branch
- `feat`: stabilize ONNX LV auto-contour pipeline для DICOM A4C

---

## 2026-06-20

### Features
- `feat`: measurement workflow sprint — planimeter, ASE norms, PDF report, cine ROI

---

## 2026-06-19

### Features
- `feat`: ONNX auto-segment pipeline с review_pending и LV Auto gating
- `feat`: LV Auto buttons trigger ONNX; Enter accepts AI contour
- `feat`: optional auto R-refine после ONNX segment
- `feat`: ASE papillary concavity exclusion на open arc
- `feat`: papillary mask cleanup для ONNX LV segment
- `feat`: gate Simpson на accepted AI contours через review_pending

---

## 2026-06-18

### Features
- `feat`: Phase 2 Clinical UI, ASE metrics, gradient refine, ONNX e2e

---

## 2026-06-17

### Features
- `feat`: Phase 1 MVP (#3) — viewer, ручные измерения

---

## 2026-06-16

### Features
- `chore`: record EchoNet ONNX export в model manifest

---

## 2026-06-15

### Features
- `feat`: bootstrap echo_personal_tool и DICOM viewer PoC (Phase 0 + S1)

---

## 2026-06-14

### Features
- `feat`: Initial commit
