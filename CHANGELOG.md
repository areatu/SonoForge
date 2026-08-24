# CHANGELOG — SonoForge

Все значимые изменения в хронологическом порядке. Формат: `[feat/fix/refactor/perf/docs/chore]: описание` (コミット-конвенция).

---

## 2026-08-23

### Features
- `feat(tools)`: vessel stenosis measurements — %D (by diameter) and %S (by area) tools in Vessels section; tool panel fixes: BSA label alignment, custom tab scroll arrows with visibility logic, Properties tab translated to RU, stenosis label preview shows D1/D2, %S recalculation on contour edit, results renamed to `%D стеноз`/`%S стеноз`
- `feat(interface)`: Qt interface animations module — accordion chevrons, panel slides, tab crossfade, button feedback, status bar slide, skeleton pulse (`ui_animations.py`)
- `feat(reference)`: hover micro-interactions + lightbox scale animation
- `feat(reference)`: smooth pathology viewer animations — tab fade transitions, active state sync

### Fixes
- `fix(reference)`: white flash eliminated, tab-switch flicker reduced, theme sync, image zoom, contrast, transition timing
- `fix(dark-theme)`: VS Code Dark selection color preserved; new `accent_selected` color for selected menu items
- `fix(tool_panel)`: simplified tab crossfade prevents widgets stuck at opacity 0
- `fix(measures_menu)`: broken chevronRotation Q_PROPERTY animation replaced with simple chevron text swap
- `fix(dialog)`: RuntimeError guarded when emitting signals on deleted QObject
- `fix(ui_animations)`: missing QStatusBar import

---

## 2026-08-22

### Features
- `feat(reference)`: new parameter groups — vascular, thyroid, kidney, abdominal aorta, lymph nodes (+1073 lines, `docs/new_reference_parameters.yaml`)

### Refactor
- `refactor(reference)`: pathology gradations removed for anatomy sections, duplicate labels fixed

### Tests
- `fix(test)`: GC frozen during each test to prevent coverage segfault; stale `get_theme_palette` mock removed; BSA overlay tests updated
- `style`: ruff format (7 files)

---

## 2026-08-21

### Features
- `feat(design)`: DESIGN.md VUNO palette applied to main window
- `feat(viewer)`: vessel sensitivity overlay for auto-trace preset control
- `feat(reference)`: regurgitant fraction for MR/AR, pulmonary hypertension echo signs, 3D LVEF/SVi norms; preload dialog, full-name tooltips, norm columns hidden when gradations present
- `feat`: constructor light theme, web refs 4-theme CSS, BSA restore, STE smoothing overlay

### Refactor
- `refactor(references)`: LV mass + geometry merged, empty-parameter rows removed, pathology_desc rows dropped, missing gradations added

### Fixes
- `fix(reference)`: AS/AR/TR/PR gradations restructured, single norm column, diastolic name duplication fixed
- `fix(presentation)`: broken tables, tab contrast, theme refresh (web view palette)
- `fix(playback)`: short cines prefetched fully — looping and rewind restored
- `fix(doppler)`: 2-click manual calibration wizard restored, time scale kept on reset

---

## 2026-08-20

### Releases
- `feat(release)`: v0.2.4 — `--version` flag and status bar version label

---

## 2026-08-19

### Features
- `feat(reference)`: web-first dialog with inline edit mode
- `feat(reference)`: web view redesign — lightbox modal, tooltips, live reload

### Fixes
- `fix(reference)`: OpenGL contexts shared with QtWebEngine, double-click interval restored

---

## 2026-08-18

### Features
- `feat(ui)`: BSA row in measurement panel, context menu Edit, hover animations, i18n fixes
- `feat(reference)`: inline editing in Qt view + web view loading fix

### Fixes
- `fix(playback)`: frame-skip jumps on large RGB cines prevented (forward-arc eviction, continuous prefetch tail)
- `fix(doppler)`: manual velocity calibration takes priority over auto-detection
- `fix(roi)`: false-positive Doppler ROI rejected on bright B-mode frames
- `fix(area)`: completed contour persisted in area-compare mode
- `fix(ui)`: shorter double-click interval for faster contour point placement
- `chore(logs)`: startup debug print and multi-study warning dropped

---

## 2026-08-17

### Features
- `feat(reference)`: web-based structured reference viewer (QWebEngineView) with Qt fallback — bridge polling, retry-loop init, `setUrl` qrc loading, full content + interactions
- `feat(reference)`: interactive column resizing for all tables

### Fixes
- `fix(reference)`: signal emitted in `setCurrentRow`, test attribute name fixed

### CI/CD
- `ci`: ruff pinned to 0.16.0; format fixes after main merge

---

## 2026-08-16

### Features
- `feat(reference)`: unified table with color-coded gradations, no-scroll layout; sex radio buttons removed — both norm columns always shown
- `feat(constructor)`: Excel-like context menu (insert/delete/merge/split cells), gradation-aware preview, toolbar consolidation
- `feat(data)`: `ParameterGradationRef` model + gradation data for all parameters in YAML
- `feat(lav)`: LA volume auto-segmentation and contour edge snap (#51)
- `feat(doppler)`: velocity scale auto-calibration on single baseline click (#45/#50)
- `perf`: adaptive FrameCache memory budget + async `release_stale_sessions` (#40/#43/#49)
- `fix(orthanc)`: download reliability — error propagation, thread-local clients, exponential backoff, interruptible sleeps (#44/#48)
- `fix(ci)`: orthanc dialog teardown segfault + properties panel fixes (#46/#47)

### Refactor
- `refactor(reference)`: two-column pathology panel, fixed row height, thumbnails restored, gradation names shortened, table panel expanded, column widths saved

### Docs
- `docs`: reference redesign design spec + implementation plan

---

## 2026-08-14

### Features
- `feat(measure)`: Simpson biplane from combined 4C+2C contours; buttons renamed, E/e′ mean label

### Fixes
- `fix(roi)`: Doppler ROI validation unified — recurring false positives prevented
- `fix(ci)`: ruff format, import sorting, flaky baseline test

---

## 2026-08-13

### Tests
- `test`: end-to-end integration tests for `autovti_region` flow

### Fixes
- `fix`: rolling median spike filter replaces fixed-threshold filter
- `fix(ci)`: FileNotFoundError and Qt event loop pollution in unit tests resolved
- `fix(autovti)`: band clear deferred, tuple return type fixed
- `fix(i18n)`: missing `layout.status_bar_mode` translation added

---

## 2026-08-12

### Features
- `feat(doppler)`: new Auto VTI (1 cycle) — two-click region selection + click-side direction detection
- `feat(doppler)`: spike filtering for Auto VTI envelope traces (clamp ±400 cm/s)
- `feat(doppler)`: inter-file measurement persistence within a study — E peak on mitral inflow file + e′ peaks on TDI file → mean E/e′ in overlay
- `feat(doppler)`: ROI skipped on B-mode without grid lines; vessel direction Up/Down toggle
- `feat`: Doppler PGmean fix + experimental features flag

### Fixes
- `fix(doppler)`: s′ПЖ (RV s′ prime) tissue Doppler measurement implemented end-to-end
- `fix(vti)`: VTI always returns absolute value
- `fix(doppler)`: auto time scale flag kept through manual velocity recalibration
- `fix`: M-mode Time/HR caliper, interval line thickness, TRpeak label, «Insufficient data» overlay removed

---

## 2026-08-11

### Features
- `feat(samsung)`: linear tick calibration for sweep speed (spacing = frequency/5), K-constant calibration builder, tick fallback auto-enables time scale for mis-tagged PW/CW
- `feat(doppler)`: baseline doubles as first velocity point — 2-click wizard
- `feat`: vendor profiles architecture + download to disk

### Fixes
- `fix(samsung)`: color-space handling, input validation, named constants
- `fix(mmode)`: auto time scale used, ms dialog skipped when present
- `fix(doppler)`: lowest dark band preferred for spectral ROI detection
- `i18n`: doppler calibration wizard hints clarified

### Docs
- `docs`: Samsung tick calibration design spec + implementation plan

---

## 2026-08-10

### Fixes
- `fix(ci)`: doppler/cache regressions from Phase A resolved, SF=1 physics guard ordering
- `test(ci)`: global QThreadPool drained after each test — Qt SIGSEGV race eliminated
- `style(lint)`: repo-wide `ruff check --fix` + `ruff format`

---

## 2026-08-07

### Fixes
- `fix`: Time/HR button starts horizontal caliper in current viewer window (no anatomical M-mode panel activation); eventFilter guard against uninitialized `_graphics`

---

## 2026-08-06

### Features
- `feat`: Orthanc study dialog — date filter (All/1/3/30 days), DD.MM.YYYY format, themed checkbox indicators, single-click expand
- `perf`: async study/series loading in Orthanc dialog — instant open, background queries (QRunnable/QThreadPool)
- `feat`: Settings dialog restructured — consolidated tabs into grouped blocks
- `feat`: ✓/✗ icons on OK/Cancel buttons + theme-contrast shortcut labels (all dialogs)
- `feat`: simplified manual Doppler calibration — baseline-first flow, ROI step skipped

### Fixes
- `fix`: file duplication prevented when loading study from Orthanc server
- `perf`: CPU usage during video playback and Windows 10 memory consumption reduced
- `perf(dicom)`: full cine released from thread-local sessions — multi-GB memory growth fixed
- `fix`: np.trapezoid compatibility, formula audit fixes, download diagnostics
- `fix`: display_form UnboundLocalError, styled_dialogs QSize bug, «Серии» error on study click
- `fix`: HTTP timeout 30→10 s; query errors surfaced instead of silent empty results

---

## 2026-08-05

### Features
- `feat(doppler)`: ECG-free cardiac cycle detection from envelope; EDV as adaptive window before systolic upstroke; median PSV/EDV averaging with per-cycle candidates
- `feat(doppler)`: cycle-selection highlight for manual PSV correction (←/→, Enter/Esc)
- `feat(doppler)`: below-baseline vessel envelopes auto-detected and traced

### Fixes
- `fix`: instance downloads retried up to 3× on transient failures
- `fix`: DICOM filename fallback decode after raw bytes freed; vessel state cleared on measurement clear
- `fix`: ECG strip height capped; ECG-sync doppler refinement, VTI units, trace label output

---

## 2026-08-04

### Features
- `feat`: vessel envelope auto-trace with sensitivity presets
- `feat`: EDV searched at diastolic minimum in Doppler auto-trace
- `feat`: ECG cardiac-cycle service + ECG-snapped PSV/EDV in vessel auto-trace
- `feat`: ECG-first CINE ED/ES detection with image fallback

### Fixes
- `fix`: on-screen text ignored in Doppler envelope auto-trace

---

## 2026-08-03

### Features
- `feat`: Vessels measurement section — PSV/EDV manual workflow: `VesselMeasurement` model, RI/S/D/MV metrics, study-session merge/filter, Measures menu section, hotkeys, report/panel integration
- `feat(doppler)`: baseline detected via visible color line (priority: line → tag → intensity)

### Fixes
- `fix`: carotid Doppler auto-calibration from Samsung correct tags
- `fix`: file extension appended in constructor/custom save dialogs
- `fix`: pixel bytes reloaded when re-opening released DICOM session
- `fix`: explicit error reported when frame save fails (silent failure on Windows)

---

## 2026-08-01

### Features
- `feat(mmode)`: maximum calibration chain — ROI tick depth detection, FrameTime fallback, parallel API to Doppler, banner with actual values + sources, M-mode group buttons in Measures menu (Time/HR, Teichholz ED/ES)
- `feat(doppler)`: Phase A — time axis first-class, no silent 1000 ms default
- `feat`: Samsung Doppler mis-tagging fix + M-mode vertical caliper

### Fixes
- `fix`: Samsung B-mode regions rejected as Doppler fallback
- `fix(viewer)`: DICOM flags preserved when rebuilding MmodeCalibrationState
- `fix(physics)`: SPATIAL_2D constant replaces magic number

### Tests
- `test(regression)`: 16 tests for maximum calibration

---

## 2026-07-31

### Performance
- `perf`: double setImage fixed, OpenGL improvements, Windows timer + playback diagnostics

---

## 2026-07-30

### Fixes
- `fix(macos)`: split Intel/Apple Silicon builds + DMG instead of zip — separate CI jobs for `macos-13` (Intel) and `macos-latest` (ARM64), `.app` bundle via BUNDLE, DMG via `hdiutil`
- `fix(ci)`: resolve CI failures — ruff F401, pixel cache test, release-drafter permissions
- `fix(i18n)`: remove dead `layout.swap` key and duplicate `research_use_only` from `en.json`

### Performance
- `perf`: memory optimization + video FPS improvements
- `perf(playback)`: fix LOW_END misclassification + optimize frame cache with bisect

---

## 2026-07-29

### Features
- `feat(measure)`: implement Area Compare tool — `%S` contour comparison с click/freehand modes

### Fixes
- `fix(measure)`: area compare — store `%S` in linear measurements, freehand/click-mode visualization fixes
- `fix(measure)`: diameter compare bugs — `%D` in overlays, `display_text`, cancel safety
- `fix(measure)`: freehand point filtering, area-compare S1/S2 vs Площадь dedup, overlay fixes

---

## 2026-07-28

### Features
- `feat(measure)`: diameter/area compare — `DIAMETER_COMPARE` и `AREA_COMPARE` в `MeasurementAction`, buttons в `MeasurementToolsPanel`, menu entries в `MeasuresMenu`
- `feat(measure)`: diameter comparison logic в `ViewerWidget` + unit tests
- `feat(measure)`: Area Compare tool — `%S` contour comparison, wire actions в `MainWindow`
- `feat(measure)`: area tool mode — `click`/`freehand` selector в preferences dialog, `area_tool_mode` preference field
- `feat(measure)`: magnetic snap для closed polygon contours (AREA/VOL) — `snap_closed_polygon` utility, Douglas-Peucker point reduction

### Fixes
- `fix(measure)`: comparison label, measurement preservation, constraint bypass
- `fix(measure)`: connect `area_compare_requested` signal к action dispatch chain
- `fix(measure)`: enable Area Compare в MeasuresMenu и revert broken signal bridge

### CI/CD
- `ci`: bump `actions/dependency-review-action` 4 → 5
- `ci`: bump `actions/upload-artifact` 4 → 7
- `ci`: bump `github/codeql-action` 3 → 4
- `ci`: bump `release-drafter/release-drafter` 6 → 7
- `ci`: bump `actions/setup-python` 5 → 7

### Style
- `style`: fix ruff formatting в 12 files

### Tests
- `test`: unit tests для diameter comparison logic

---

## 2026-07-27

### Docs
- `docs`: add demo videos и updated screenshots
- `docs`: add Disclaimer, update Installation, add status bar warning
- `docs`: fix screenshot placement в Cardiac Measurements table
- `docs`: remove screenshots из README_RU.md

---

## 2026-07-26

### Releases
- `chore(release)`: v0.2.3 — CI fixes (Windows unit tests, ruff format), macOS build + source tarball in Release workflow

### i18n
- `i18n`: translate domain layer and infrastructure to English
- `i18n`: translate presentation layer to English
- `i18n`: translate constructor module to English
- `i18n`: translate strain window and curves to English
- `i18n`: add all missing locale keys для full English translation

### Docs
- `docs`: add CODE_OF_CONDUCT.md и issue template config
- `docs`: update README и SECURITY с new features

### Features
- `feat(test)`: comprehensive verification test suite — 8 new test categories (security, regression, migration, acceptance, system, exploratory, compat, bench) с 520+ тестами
- `feat(test)`: security fuzzing — DICOM input fuzzing (truncated, corrupt, nested sequences), API response fuzzing (malformed JSON, SQL injection, XSS payloads)
- `feat(test)`: security verification — credential storage audit, HTTPS enforcement, ONNX model integrity (SHA256), PHI anonymization, network timeouts
- `feat(test)`: acceptance tests — E2E workflows: open/measure/export, Orthanc, auto-segment, strain, constructor, preferences
- `feat(test)`: regression baselines — contour, Doppler, M-mode, pixel spacing, report formatting exact-match tests
- `feat(test)`: data migration tests — gold schema versioning, backward compatibility, repair script, manifest generation, annotation merge
- `feat(test)`: exploratory testing — hypothesis property-based tests (planimeter, BSA, Simpson), input fuzzing for DICOM UIDs
- `feat(test)`: OS compatibility tests — Windows paths (Cyrillic, UNC, spaces), display server (offscreen, xcb)
- `feat(test)`: benchmark expansion — ONNX inference latency, full pipeline, gold store I/O benchmarks
- `feat(test)`: 7 new pytest markers (acceptance, security, regression, migration, system, compat, bench)
- `feat(test)`: pytest-timeout 60s per-test timeout to prevent CI hangs
- `feat(ci)`: restored full GUI test coverage in CI (removed `-m 'not gui'` from coverage workflow)

### Fixes
- `fix(ui)`: tab scroll arrows now visible in settings dialog and tool panel — replaced Unicode ◀▶ with ASCII < >, set minimumWidth(28) on QToolButton scroll buttons
- `fix(security)`: DICOM UID validator now rejects pure-dot UIDs (`...`), strings >64 chars, and dot-prefixed/suffixed UIDs per PS3.5 §6.1
- `fix(security)`: ONNX `_verify_model_integrity` now raises `ModelIntegrityError` on SHA256 mismatch instead of just logging a warning — corrupted models are no longer loaded
- `fix(test)`: ConstructorDialog.closeEvent uses `_skip_close_prompt` flag to prevent blocking QMessageBox during programmatic close (pytest-qt teardown)
- `fix(test)`: restore i18n translations after locale-loading tests to prevent suite-wide pollution (`Unknown language 'ru'` cascade)
- `fix(ci)`: macOS/Windows CI runs exclude GUI tests (`-m 'not gui'`) — no xvfb, Qt crashes with SIGABRT
- `fix(test)`: ruff formatting — 75 files auto-formatted, 185 lint errors fixed
- `fix(test)`: smoke test version mismatch (0.2.1 → 0.2.2), comprehensive import smoke tests for all modules

### Chore
- `chore`: added dev dependencies: bandit, safety, syrupy, hypothesis, pytest-timeout
- `chore`: created test directory structure: tests/{acceptance,security,regression,migration,system,exploratory,compat}/

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
