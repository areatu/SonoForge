# Samsung Calibration Fixes — ROI, M-mode time, velocity wizard

**Date:** 2026-08-11
**Status:** Approved
**Scope:** Three calibration fixes for Samsung RS85 composite frames
(Doppler ROI/base-line, M-mode time auto-scale, spectral velocity wizard).

## Background

Real Samsung RS85 files in `/home/areatu/ECHO2026_src/Новая папка` come in two
composite layouts:

1. **M-mode files** (e.g. `12/14/15/63.dcm`): an SF=1 B-mode region plus an
   SF=2 M-mode region with usable `PhysicalDeltaX` time tags.
2. **Mis-tagged PW/CW files** (e.g. `17/18/19/61/62.dcm`): only SF=1 regions
   treated as B-mode; no usable time tags.

Three user-reported gaps were confirmed against the codebase and real data.

## Problem 1 — Doppler ROI mis-detection (measurement & baseline affected)

`detect_spectrogram_roi` (domain/services/spectrogram_detector.py) currently:
- Scans a fixed bottom band `search_top_fraction=0.35` – `search_bottom_fraction=0.95`.
- Picks the *largest* contiguous dark block inside that band.

Verified behavior on real files (884×1180):

| file | DICOM region (SF=1) | actual dark band | detected ROI |
|------|--------------------|-----------------|--------------|
| 17   | (0,100,1179,473)   | y≈451–624        | (1,450,1158,633) — ~ok |
| 18   | (0,100,1179,473)   | y≈454–561, y≈704–843 | `None` → full-frame fallback (wrong) |
| 19   | (0,100,1179,473)   | y≈457–555, y≈690–843 | `None` → full-frame fallback (wrong) |
| 61   | (0,100,1179,393)   | y≈351–418, y≈621–841 | (1,612,1168,838) — picks lower band |
| 62   | (0,100,1179,393)   | y≈351–442, y≈625–842 | (1,611,1168,838) — picks lower band |

The ROI is structurally required: `build_axis_mapping()`
(doppler_calibration.py) sets `plot_width/height/origin` from the ROI, so
every `velocity_cm_s_from_y` / `time_ms_from_x` conversion depends on it.
A wrong ROI yields a wrong cm·s⁻¹/px scale AND a wrong baseline seed
(`detect_baseline_y` searches within the ROI), which blocks measurements.

### Decision (user-approved)

Improve the auto-detection of the Doppler ROI. The ROI stays the mapping
basis (cannot be removed); the detector must locate the real spectrogram band.

### Design

Replace the fixed-window “largest dark block” heuristic in
`detect_spectrogram_roi` with a **panel-aware band selection**:

1. **Strong prior from DICOM region bounds when available.** For Samsung
   mis-tagged PW/CW files the SF=1 region bbox (e.g. y100–473) marks the
   *upper* area; the real Doppler panel lies at the bottom of the composite.
   Use the region bbox as the horizontal prior and constrain the band search
   to rows at or below the region (Doppler sits under the B-mode strip).
2. **Full-height dark-band profile scan** (drop the fixed 35–95% window):
   - Compute row-mean profile over the whole frame.
   - Enumerate contiguous dark bands (`row_mean < dark_threshold`).
   - Score each band: width, height ≥ 15% frame height, and **proximity to a
     bright ruler/scale zone below it** (the sweep-time ruler).
   - Prefer the **lower** dark band when ambiguous (Doppler panels sit at the
     bottom of the composite).
3. **Falls back in order:** best scored band → DICOM region bounds → full frame.
   When falling back to full frame, do **not** seed the baseline from the ROI
   center if a bright baseline line is visible elsewhere; leave baseline for
   the long-standing `detect_baseline_y`/`detect_baseline_line_y` chain on the
   resolved ROI.
4. **Baseline** unchanged: `detect_baseline_y` on the corrected ROI, otherwise
   center (last resort only when no band/line evidence exists).

### Testing

- Unit tests with synthetic Samsung-like frames (dark Doppler band + bright
  ruler below; B-mode strip above) reproducing the four modes:
  - 17-like (single low dark band) → ROI ≈ band.
  - 18/19-like (two dark bands, ambiguous) → picks the lower panel band.
  - 61/62-like (upper B-mode strip + lower panel) → picks the panel.
  - no visible band → graceful full-frame fallback (never crashes).
- Real-file regression asserting returned ROI contains the measured dark band
  and baseline falls inside the ROI.

## Problem 2 — M-mode time/HR ignores the auto time scale

M-mode files with an SF=2 region already auto-calibrate in
`restore_mmode_state(None)` → `try_apply_mmode_from_dicom_or_heuristic()`
(verified: `horizontal_ms_per_pixel=4.17 ms/px`, `is_mmode_calibrated()=True`).

The standalone menu path `_on_mmode_time_hr_from_menu`
(main_window.py:1930) → `start_mmode_time_calibration` →
`_prompt_mmode_time_span` (viewer_widget.py:5633) **always** opens the “enter
ms” dialog and ignores an existing auto-computed time scale.

### Decision (user-approved)

Use the auto time scale when present; only prompt for ms when the scale is
missing.

### Design

- In `_prompt_mmode_time_span`: when the current M-mode state already has
  `horizontal_ms_per_pixel` (>0) and it applies to the current ROI,
  **return early** using that value (no `QInputDialog`). The dialog opens only
  when the time scale is genuinely absent.
- `start_mmode_time_calibration` reports (bool) whether it was standalone or
  auto-resolved, so the caller can show the correct status string.
- Preserve current behavior when no auto scale exists (dialog still shown).

### Testing

- GUI test: with an auto-calibrated M-mode state, `_on_mmode_time_hr_from_menu`
  performs the time/HR measurement without invoking `QInputDialog`.
- GUI test: without a time scale, the dialog is still shown (existing path).

## Problem 3 — Spectral velocity wizard: baseline also starts the segment

Manual spectral velocity calibration currently takes 3 clicks:
1. baseline/zero line,
2. first point of the vertical segment (always the zero line again),
3. top of the scale.

Then `_prompt_spectral_velocity_span(length)` computes the span.

### Decision (user-approved)

The baseline click doubles as the first point of the vertical segment →
**2 clicks** total.

### Design

- In `_handle_doppler_calibration_click` (viewer_widget.py:3093, step
  `"baseline"`): the click sets both `_doppler_pending_baseline_y = y` and
  `_calibration_start_y = y` before `_begin_doppler_velocity_calibration()`.
- The next click (top of scale) immediately satisfies the length check
  (`abs(y - start_y) >= 1`) and calls `_prompt_spectral_velocity_span`.
- Update the step status strings (en/ru i18n) so the workflow reads
  “1 click = baseline + start of scale, 2nd click = top of scale”.
- Keep `calibration_from_roi_and_baseline` semantics unchanged.

### Testing

- GUI test: after the baseline click, `_calibration_start_y == baseline y`
  and the velocity sub-flow starts with the segment origin already set.
- GUI test: a second click on the top of the scale triggers
  `_prompt_spectral_velocity_span` with `length = |top − baseline|`.

## Files touched

- `src/echo_personal_tool/domain/services/spectrogram_detector.py` (P1)
- `src/echo_personal_tool/presentation/viewer_widget.py` (P1 baseline chain,
  P2, P3)
- `src/echo_personal_tool/presentation/main_window.py` (P2 status flow)
- `src/echo_personal_tool/infrastructure/locales/{en,ru}.json` (P2/P3 hints)
- Tests: `tests/unit/test_spectrogram_detector.py` (or existing detector test),
  `tests/unit/test_viewer_widget.py`, `tests/unit/test_main_window_doppler.py`

## Out of scope

- Removing the ROI (still required for pixel ↔ physical mapping).
- Auto-trace (VTI auto-trace already exists; not reworked).
- Non-Samsung vendor ROI detection.