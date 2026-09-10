# Changelog — SonoForge v0.3.0

Released: 2026-09-10

## Summary

SonoForge 0.3.0 is a major release introducing a web-based reference viewer with inline editing, a high-performance DICOM playback pipeline (per-frame decoding, priority-gated decode queue, memory-mapped pixel data), and polished UI animations across the entire interface. Calibration and Doppler modules received significant hardening, especially for Samsung and GE vendor paths. The release also includes vessel stenosis measurements, evidence-fusion baseline detection, and expanded reference library coverage.

> **Note:** Two splash-screen features (`da804c0`, `c28b02c`) were introduced and subsequently reverted (`93d4ccb`, `a35c1f8`); they are excluded from this changelog.

---

## Features

### Reference
- Add web-based reference viewer with Qt fallback (`a82a27c`)
- Populate web UI with full content and interactions (`1c15e09`)
- Inline editing in Qt view + fix web view loading (`53933bd`)
- Web view redesign, lightbox modal, tooltips, live reload (`ed033e2`)
- Web-first dialog with inline edit mode (`f787daf`)
- Preload dialog, full-name tooltips, hide norm columns with gradations (`7c2f777`)
- Add RF for MR/AR, PH echo signs, 3D LVEF and SVi norms (`7ebd989`)
- Translate reference to English (`f41c909`)
- Add vascular, thyroid, kidney, abdominal, aorta, lymph node parameters (`d7b00d3`)
- Add smooth animations to pathology reference viewer (`0a8d546`)
- Add hover micro-interactions and lightbox scale animation (`12a0701`)
- Update vertebral artery reference: rename hemodynamics to diameter features, add diameter parameters (`afed25e`)

### UI / Interface
- Add Qt interface animations (accordion chevron, panel slide, tab crossfade, button feedback, status bar slide, skeleton pulse) (`cd65f6b`)
- Apply DESIGN.md VUNO palette to main window (`4993b3f`)
- Apply DESIGN.md to web view + fix UI issues (`26847af`)
- BSA in measurement panel, context menu Edit, hover anim, i18n fixes (`3262807`)
- Cherry-pick theme, animations, icons, locales from arena (`362bca9`)
- Constructor light theme, web refs 4-theme CSS, BSA restore (`d270102`)

### Viewer
- Vessel sensitivity overlay for auto-trace preset control (`09a3019`)

### Doppler
- Wire evidence-fusion baseline into Samsung tick path (`54255d9`)
- Evidence-fusion baseline detector for tag-less Samsung frames (`c6cef59`)

### LV (Left Ventricle)
- Two-pass Simpson with rigid alignment and canonical apex (`4e57f69`)

### Tools
- Add vessel stenosis measurements and fix tool panel issues (`fb782b6`)

### Domain
- Cherry-pick arena improvements + fix Doppler false-positive (`687a447`)

### Release
- Bump to 0.2.4, add --version flag and status bar label (`57d8e65`)

---

## Bug Fixes

### Doppler / Calibration
- Restore 2-click manual calibration, keep time scale on reset (`a0163a1`)
- Manual velocity calibration takes priority over auto-detection (`09b4fc7`)
- Make Vpeak draggable (`952fc6e`)
- Constrain auto-trace and add peak guides (`a9f3dbe`)
- Restore viewer_widget baseline clamping and frame_cache from main (`4d037f6`)
- Restore GE baseline formula, velocity_sign, and i18n labels (`dd4336a`)
- High-threshold tick retry for luminance-washed rulers (`cd159dd`)
- Propagate velocity_sign through tick detection path (`22cad8f`)
- Close calibration review regressions (`dafb614`)
- Fix/calibrate 1 (`0b1b40e`)
- Fix/calibrate 2 (`28368d3`)

### Reference
- Share OpenGL contexts with QtWebEngine, restore double-click interval (`b05da24`)
- Add web→Qt fallback and bridge polling (`37cffc4`)
- Use setUrl instead of setHtml to fix qrc:/// loading (`331e4d6`)
- Theme sync, image zoom, contrast, transition timing (`7bee801`)
- Smooth pathology tab transitions with fade and sync active state (`668767b`)
- Eliminate white flash and reduce tab-switch flicker (`e6eec54`)
- Web gradation colors, light theme CSS, accent_selected key (`258ab66`)
- Restore gradation colors, tab highlighting, and language switching (`1acf62c`)
- Restructure AS/AR/TR/PR gradations, fix diastolic name duplication, add single norm column (`a880fe0`)
- Fix web reference handbook implementation bugs (`d4a3f94`)
- Fix broken tables, tab contrast, theme refresh (`c23f784`)

### Playback
- Prefetch short cines fully to restore looping and rewind (`ee7a81a`)
- Prevent frame-skip jumps on large RGB cines (`8a47a44`)
- Restore require_full_cine partial check from main (`4e164e4`)

### UI / Interface
- Shorten double-click interval for faster contour point placement (`4091c81`)
- Theme title bar, web_ref locale keys, fade transition (`9e6bbb3`)
- Keep VS Code Dark selection color unchanged (`74e84a1`)
- Add accent_selected color for better contrast on selected menu items (`660f2fe`)
- Simplify tab crossfade to prevent widgets stuck at opacity 0 (`2034179`)
- Remove broken chevronRotation Q_PROPERTY animation, use simple chevron text swap (`d8e0a35`)
- Add missing QStatusBar import (`12f2fcf`)

### ROI (Region of Interest)
- Reject false-positive Doppler ROI on bright B-mode frames (`5dc6252`)
- Improve Doppler ROI detection and restore reference data (`78f7ce4`)

### M-Mode
- Restore partial state for panels without vertical calibration (`266f6d4`)

### Area
- Persist completed contour in area-compare mode (`180cd15`)

### DICOM / Session
- Break ABBA deadlock in DicomSession.open() (`320c934`)
- Fallback to pydicom parse for encapsulated frame count (`a27f9f1`)
- Handle SR files without pixel data (`7d21a2e`)
- Loader hardening per review (H1-H2, M1-M4, L1-L3, L5) (`65dc50a`)

### Dialog
- Don't close shared httpx client while background query is in-flight (`f77266b`)
- Catch RuntimeError when emitting signal on deleted QObject (`db5f37d`)

### Settings
- Persist language/theme on startup and prepare release defaults (`d5d191e`)
- Wrap server tab in scroll area to prevent DIMSE field clipping (`72ab64e`)

### Smoothing
- Guard NaN/negative spline s (`7d21a2e`)

### Tests / CI
- Adapt tests for EN default + remove dead static_noise_filter refs (`dca6144`)
- Update test contours to A4C orientation and fix manifest check (`7522ace`)
- Resolve ruff lint errors (F401, F811, I001) (`aaf6446`)
- Remove parallel flag from Coveralls upload (`72a142d`)
- Update test_preset_standard tracking_mode to border (`dab418f`)
- Remove test_presentation_viewer_widget (tests arena-only viewer API) (`0ba791a`)
- Restore test files from main for orthanc/DICOM compatibility (`7af39c1`)
- Update segment_roi tests for Doppler-only ROI detection (`c213b56`)
- Resolve lint import order and 4 failing tests (`9508647`)
- Freeze GC during each test to prevent segfault in coverage (`e0104cf`)
- Remove stale get_theme_palette mock from constructor tests, fix F541 lint (`848f5d3`)
- Update test_with_indexed to match BSA removal from overlay (`a9314ca`)
- Remove redundant parens in vendor_calibration_bridge.py (`17e490f`)

### Repo
- Resolve merge conflicts — remove duplicate tests, format bridge (`2bef6c3`)
- Resolve merge conflict: accept remote version of references_structured.yaml (`7b8947b`)

---

## Performance

- Per-frame decoding, thumbnail isolation, unified error (`3bfd7ae`)
- Stop background gc and thread churn during playback (`ff950d3`)
- Cut the first-frame path on weak machines (`b466957`)
- Map cine pixel data and tune the cache to the loaded cine (`e8c1a4d`)
- Size prefetch and eviction from the observed frame cost (`031e9d6`)
- Serialise decodes per file behind a priority gate (`f6097c6`)
- Cache window/level transforms and skip full-frame re-uploads (`e6c9254`)
- Pace the cine timer from the frame time, not a fixed interval (`9faf000`)
- Share one warm DICOM session per file across workers (`5778a97`)

---

## Refactoring

- Simplify bridge init with retry loop (`e3dd20e`)
- L4 — share one web/DIMSE client across dialog stack (`644063c`)
- Remove redundant pathology_desc, fix web table alignment, add ICA/ECA/CCA/vertebral stenosis (`c695957`)
- Rename Abdominal Organs to Abdomen, reorder tricuspid stenosis, remove pulmonary trunk dilation (`5251d46`)
- Remove pathology gradations for anatomy sections, fix duplicate labels (`330d3b3`)
- Remove pathology_desc rows, add missing gradations (`59b5a1e`)
- Remove 7 empty-parameter rows (`2b52a3e`)
- Merge LV mass + geometry, simplify gradations, remove empty rows (`19a1176`)
- Optimize toolbar, context menu, and adapt for Windows 125% (`ad54f07`)

---

## Documentation

- Record measured playback results, run the 720p cine bench in CI (`0dd8146`)
- Audit 720p cine playback and add the measurement harness (`95b6834`)
- Update session changelog (`434ad7e`, `7c961d2`)
- Update README with August features, add August changelog (`6c27c02`)

---

## Chores / Style

- Clean up tracked files, bump version to 0.3.0 (`a0e36a1`)
- Remove temp benchmark script (`1a34561`)
- Drop startup debug print and multi-study warning (`1b793c6`)
- Re-serialize references_structured.yaml in flow style (`e859649`)
- Remove build-macos-intel job (`16a79d4`)
- Apply ruff 0.16.0 formatting to 15 files (`5196204`)
- Apply ruff format to LV core files (`2d88e71`)
- Fix import sorting in test_segmentation_service.py (`f7276fa`)
- Ruff format web_reference_bridge.py (`f2db6b7`)
- Format vendor bridge after merge (`b056d31`)
- Format overlay tests (`2437f18`)
- Format calibration modules (`71077ce`)
- Format bridge module (`495b8e2`)
- Apply ruff format to 3 unformatted files (`f219339`)
- Apply ruff format to 7 files (`643865f`)
- Add Samsung velocity scale and DICOM ROI tests (`3f84bf3`)
- Make two playback tests platform-independent (`0a64ac7`)
- Measure the prefetch round trip and gate 720p cine in CI (`b7bfba5`)
