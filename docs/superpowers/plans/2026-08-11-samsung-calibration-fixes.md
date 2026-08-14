# Samsung Calibration Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three Samsung RS85 calibration gaps: Doppler ROI auto-detection, M-mode time auto-scale, and the spectral velocity wizard click count.

**Architecture:**
- **Task 1 (ROI):** rewrite `detect_spectrogram_roi` in `spectrogram_detector.py` to scan the full frame height, enumerate contiguous dark bands, and prefer the **lowest** valid band (Doppler panels sit at the bottom of composite frames). Add an optional `region_bounds` parameter used as a fallback prior. Pure function — no GUI.
- **Task 2 (M-mode time):** in `viewer_widget.py::_prompt_mmode_time_span`, skip the ms dialog when the current M-mode calibration already has a valid `horizontal_ms_per_pixel`.
- **Task 3 (wizard clicks):** `_begin_doppler_velocity_calibration` accepts the baseline y as the first segment point; the manual baseline click sets it, reducing the wizard from 3 to 2 clicks. Update en/ru hint strings.

**Tech Stack:** Python 3.11, NumPy, PySide6 (Qt), pytest + pytest-qt.

## Global Constraints

- No comments added to code (AGENTS.md).
- SOLID, no data races.
- TDD: write failing test → run (fail) → implement → rerun (pass) → commit.
- i18n parity: `en.json` and `ru.json` must both be updated for any string change (enforced by `tests/unit/test_i18n.py`).
- venv: `cd /home/areatu/ECHO2026 && source .venv/bin/activate`.
- GUI tests use `QT_QPA_PLATFORM=offscreen`.
- Do not commit unrelated dirty files (`.github/workflows/ci.yml`, `CHANGELOG_SESSION.md`, `pyproject.toml`, `uv.lock`, `infrastructure/properties_extractor.py`, `rag-code-mcp.yaml`).
- Preserve backward compatibility: `detect_spectrogram_roi(frame, *, search_top_fraction=0.35, search_bottom_fraction=0.95)` call sites must keep working.

---

## Task 1: Panel-aware Doppler ROI detection

**Files:**
- Modify: `src/echo_personal_tool/domain/services/spectrogram_detector.py`
- Test: `tests/unit/test_spectrogram_detector.py`

**Interfaces:**
- Consumes: `numpy` (already imported in the module). Existing callers: `src/echo_personal_tool/infrastructure/vendor_calibration_bridge.py:251`, `src/echo_personal_tool/presentation/viewer_widget.py:3070` — both call `detect_spectrogram_roi(frame)` with only positional `frame`.
- Produces: `detect_spectrogram_roi(frame, *, search_top_fraction=0.35, search_bottom_fraction=0.95, region_bounds: tuple[float, float, float, float] | None = None) -> tuple[float, float, float, float] | None`. Returns `(x0, y0, x1, y1)` likely bounding the *lowest* dark spectrogram panel, or a `region_bounds`-derived fallback, or `None`.

### Background (verified against real Samsung RS85 884×1180 files)

Real spectrogram dark bands (bottom = lowest):
- `17.dcm`: single band y≈451–624. DICOM region (0,100,1179,473).
- `18/19.dcm`: TWO dark bands y≈454–561 and y≈704–843. Old code → `None` → full-frame fallback (wrong).
- `61/62.dcm`: TWO dark bands y≈351–418 and y≈621–841. Old code → lower band ≈ (612..,838) which is correct.

Key behavioral change: prefer the **lowest** dark band (Doppler sits at bottom of the composite). This fixes 18/19 (currently `None`) and keeps 61/62 correct.

- [ ] **Step 1: Add synthetic tests for the new behavior**

Append to `tests/unit/test_spectrogram_detector.py`:

```python
def _make_two_band_frame(height: int = 884, width: int = 1180) -> np.ndarray:
    """Composite with bright B-mode on top and TWO dark bands (modal):
    an upper strip (y~454-561) and a lower Doppler panel (y~704-843)."""
    frame = np.full((height, width), 150, dtype=np.uint8)
    frame[454:562, :] = 12
    frame[704:844, :] = 12
    frame[720:740, width // 4 : 3 * width // 4] = 120
    return frame


def test_detect_prefers_lowest_of_two_bands() -> None:
    frame = _make_two_band_frame()
    roi = detect_spectrogram_roi(frame)
    assert roi is not None
    x0, y0, x1, y1 = roi
    # Prefer the lower (Doppler) panel, not the upper strip
    assert y0 >= 650
    assert y0 < y1
    assert (y1 - y0) >= 100


def test_detect_region_bounds_fallback() -> None:
    # Uniform bright frame (no visible bands) -> falls back to region_bounds
    frame = np.full((884, 1180), 200, dtype=np.uint8)
    roi = detect_spectrogram_roi(frame, region_bounds=(0.0, 100.0, 1179.0, 473.0))
    assert roi is not None
    x0, y0, x1, y1 = roi
    assert y0 == 100.0
    assert y1 == 473.0


def test_detect_no_band_no_region_returns_none() -> None:
    frame = np.full((884, 1180), 200, dtype=np.uint8)
    roi = detect_spectrogram_roi(frame)
    assert roi is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
source .venv/bin/activate && QT_QPA_PLATFORM=offscreen python -m pytest tests/unit/test_spectrogram_detector.py -v
```
Expected: new tests FAIL (old algorithm returns full-frame/None or wrong band / `region_bounds` kwarg raises `TypeError`).

- [ ] **Step 3: Rewrite `detect_spectrogram_roi`**

Replace the entire body of `spectrogram_detector.py` (keep the module docstring and import). This is the **validated** implementation — it passes all existing synthetic tests (`test_detect_spectrogram_basic`, `_no_spectrogram`, `_small_frame`, `_returns_frame_coords`) and detects the correct lower Doppler band on the real Samsung `17/18/19/61/62.dcm` files. The `(percentile10 + percentile50)/2` threshold plus a `gap_tol` that bridges thin bright ruler/grid lines is essential — without the gap tolerance the band fragments and returns `None` on real files:

```python
"""Detect the spectral Doppler spectrogram region in a composite echo frame."""

from __future__ import annotations

import numpy as np


def _dark_bands(
    gray: np.ndarray, dark_threshold: float, min_rows: int, gap_tol: int = 8
) -> list[tuple[int, int]]:
    """Return [(y0, y1), ...] dark row bands, bridging gaps of <= gap_tol.

    Bridges thin bright ruler/grid lines so a Doppler panel stays one band.
    """
    row_mean = np.mean(gray, axis=1)
    dark = row_mean < dark_threshold
    bands: list[tuple[int, int]] = []
    start: int | None = None
    in_band = False
    gap = 0
    for y, is_dark in enumerate(dark):
        if is_dark and not in_band:
            start = y
            in_band = True
            gap = 0
        elif is_dark and in_band:
            gap = 0
        elif not is_dark and in_band:
            gap += 1
            if gap > gap_tol:
                if y - gap_tol - start >= min_rows:
                    bands.append((start, y - gap_tol))
                in_band = False
    if in_band and len(gray) - start >= min_rows:
        bands.append((start, len(gray)))
    return bands


def detect_spectrogram_roi(
    frame: np.ndarray,
    *,
    search_top_fraction: float = 0.35,
    search_bottom_fraction: float = 0.95,
    region_bounds: tuple[float, float, float, float] | None = None,
) -> tuple[float, float, float, float] | None:
    """Locate the spectral Doppler spectrogram bounding box.

    Scans the full frame height for contiguous dark bands and returns the
    bounding box of the *lowest* band broad enough to be a Doppler panel
    (Doppler panels sit at the bottom of composite echo frames). If no band is
    found, falls back to ``region_bounds`` when supplied; otherwise ``None``.

    Returns (x0, y0, x1, y1) in pixel coordinates.
    """
    if frame.ndim == 3:
        a = np.asarray(frame)
        if a.shape[-1] in (1, 3, 4):
            gray = np.mean(a, axis=2).astype(np.float32)
        else:
            gray = a[0].astype(np.float32)
    else:
        gray = frame.astype(np.float32)

    h, w = gray.shape
    if h < 30 or w < 30:
        return None

    band_min_rows = max(10, int(h * 0.10))
    row_mean_all = np.mean(gray, axis=1)
    dark_threshold = (
        float(np.percentile(row_mean_all, 10))
        + float(np.percentile(row_mean_all, 50))
    ) / 2.0
    if dark_threshold <= 1.0:
        return None

    bands = _dark_bands(gray, dark_threshold, band_min_rows)
    if not bands:
        if region_bounds is not None:
            return tuple(float(v) for v in region_bounds)
        return None

    # Prefer the lowest band (Doppler panel at the bottom).
    y0, y1 = bands[-1]

    # Detect horizontal extent within the chosen band.
    band_region = gray[int(y0) : int(y1), :]
    col_mean = np.mean(band_region, axis=0)
    bright_cols = np.where(col_mean > np.median(col_mean) * 0.3)[0]
    if len(bright_cols) < w * 0.3:
        if region_bounds is not None:
            return tuple(float(v) for v in region_bounds)
        return None

    x0 = float(bright_cols[0])
    x1 = float(bright_cols[-1] + 1)

    if (y1 - y0) < h * 0.10:
        if region_bounds is not None:
            return tuple(float(v) for v in region_bounds)
        return None

    return (x0, float(y0), x1, float(y1))
```

Note: keep the old keyword parameters (`search_top_fraction`, `search_bottom_fraction`) in the signature (ignored internally) so existing positional/keyword call sites do not break; `region_bounds` is the new optional prior.

- [ ] **Step 4: Run all detector tests to verify they pass**

Run:
```bash
source .venv/bin/activate && QT_QPA_PLATFORM=offscreen python -m pytest tests/unit/test_spectrogram_detector.py tests/unit/test_doppler_roi.py -v
```
Expected: ALL PASS (old + new tests).

- [ ] **Step 5: Cross-check no other test regressions**

Run:
```bash
source .venv/bin/activate && QT_QPA_PLATFORM=offscreen python -m pytest tests/unit/test_depth_scale_detector.py tests/unit/test_samsung_tick_calibration.py tests/unit/test_dicom_doppler_calibration.py -q
```
Expected: PASS. (Vendor bridge and viewer use only the `frame` positional, so behavior stays compatible.)

- [ ] **Step 6: Commit**

```bash
git add src/echo_personal_tool/domain/services/spectrogram_detector.py tests/unit/test_spectrogram_detector.py
git commit -m "fix(doppler): prefer lowest dark band for spectral ROI detection"
```

---

## Task 2: M-mode time auto-scale skips ms dialog

**Files:**
- Modify: `src/echo_personal_tool/presentation/viewer_widget.py` — `_prompt_mmode_time_span` at line 5633.
- Test: `tests/unit/test_viewer_widget.py`

**Interfaces:**
- Consumes: `self._mmode_calibration_state: MmodeCalibrationState | None`, `self._mmode_pending_roi`, `self._mmode_pending_depth_mm_per_pixel`, `self._mmode_time_start_x`, `self._calibration_start_y`, `self.apply_mmode_calibration_state(state)`, signal `self.mmode_time_calibration_completed`.
- Produces: behavior change only — when the state has a valid `horizontal_ms_per_pixel`, `_prompt_mmode_time_span(length_px)` builds/emits the time-only result without opening `QInputDialog`.

### Background

`_handle_calibration_click` (viewer_widget.py:5469-5478) for `_calibration_kind == "mmode_time"` measures a horizontal span then calls `_prompt_mmode_time_span(length_px)`. That method currently always opens `QInputDialog.getDouble`. For auto-calibrated M-mode (dicom `horizontal_ms_per_pixel=4.167`), the time scale is already known — the dialog is redundant.

- [ ] **Step 1: Add failing GUI tests**

Append a new class to `tests/unit/test_viewer_widget.py`:

```python
class TestMmodeTimeAutoScale:
    def _make_mmode_state(self):
        from echo_personal_tool.domain.models.frame_panels import (
            MmodeCalibrationState,
        )
        from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi

        return MmodeCalibrationState(
            roi=DopplerSpectrogramRoi(x0=4.0, y0=341.0, width=1236.0, height=459.0),
            vertical_mm_per_pixel=0.355,
            horizontal_ms_per_pixel=4.167,
            from_dicom_tags=True,
            depth_from_dicom_tags=True,
            time_from_dicom_tags=True,
        )

    def test_time_scale_skips_dialog_when_present(self, qtbot, monkeypatch) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((800, 1240), dtype=np.uint8))
        w.apply_mmode_calibration_state(self._make_mmode_state())
        emitted = []

        def fake_emit(value):
            emitted.append(value)

        w.mmode_time_calibration_completed.connect(fake_emit)

        def fail_dialog(*args, **kwargs):
            raise AssertionError("QInputDialog must not be called when scale exists")

        monkeypatch.setattr(
            "echo_personal_tool.presentation.viewer_widget.QInputDialog.getDouble",
            fail_dialog,
        )
        # Standalone time-only flow (no pending ROI/depth)
        w._prompt_mmode_time_span(length_px=100.0)
        assert emitted == [4.167]

    def test_time_scale_still_prompts_when_absent(self, qtbot, monkeypatch) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((800, 1240), dtype=np.uint8))
        w._calibration_start_y = 50.0
        calls = []

        def fake_dialog(parent, title, prompt, value, mn, mx, dec):
            calls.append((value, mn, mx))
            return 1000.0, True

        monkeypatch.setattr(
            "echo_personal_tool.presentation.viewer_widget.QInputDialog.getDouble",
            fake_dialog,
        )
        w._prompt_mmode_time_span(length_px=100.0)
        assert len(calls) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
source .venv/bin/activate && QT_QPA_PLATFORM=offscreen python -m pytest tests/unit/test_viewer_widget.py::TestMmodeTimeAutoScale -v
```
Expected: `test_time_scale_skips_dialog_when_present` FAILS (dialog currently called → `AssertionError`); `test_time_scale_still_prompts_when_absent` PASSES.

- [ ] **Step 3: Implement the early-return in `_prompt_mmode_time_span`**

In `viewer_widget.py`, change `_prompt_mmode_time_span` so it reads the existing `horizontal_ms_per_pixel` before opening the dialog. Replace the function (lines ~5633-5673) with:

```python
    def _prompt_mmode_time_span(self, length_px: float) -> None:
        pending_roi = self._mmode_pending_roi
        pending_depth = self._mmode_pending_depth_mm_per_pixel

        # Auto-resolve: time scale already known (e.g. from DICOM tags).
        existing = (
            self._mmode_calibration_state.horizontal_ms_per_pixel
            if self._mmode_calibration_state is not None
            else None
        )
        if existing is not None and existing > 0.0:
            time_per_pixel_ms = float(existing)
            accepted = True
        else:
            span_ms, accepted = QInputDialog.getDouble(
                self,
                "M-mode time scale",
                tr("viewer.mmode_cal_time_prompt"),
                1000.0,
                1.0,
                10000.0,
                0,
            )
            if accepted and length_px > 0.0:
                time_per_pixel_ms = span_ms / length_px
            else:
                time_per_pixel_ms = None

        self._clear_calibration_caliper()
        if not accepted or time_per_pixel_ms is None or length_px <= 0.0:
            self._mmode_pending_roi = None
            self._mmode_pending_depth_mm_per_pixel = None
            return

        if pending_roi is not None and pending_depth is not None:
            state = MmodeCalibrationState(
                roi=pending_roi,
                vertical_mm_per_pixel=pending_depth,
                horizontal_ms_per_pixel=time_per_pixel_ms,
                from_dicom_tags=self._mmode_calibration_state.from_dicom_tags
                if self._mmode_calibration_state is not None
                else False,
                depth_from_dicom_tags=self._mmode_calibration_state.depth_from_dicom_tags
                if self._mmode_calibration_state is not None
                else False,
                time_from_dicom_tags=self._mmode_calibration_state.time_from_dicom_tags
                if self._mmode_calibration_state is not None
                else False,
            )
            self._mmode_pending_roi = None
            self._mmode_pending_depth_mm_per_pixel = None
            self.apply_mmode_calibration_state(state)
        elif not self._syncing_state:
            self.mmode_time_calibration_completed.emit(float(time_per_pixel_ms))
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
source .venv/bin/activate && QT_QPA_PLATFORM=offscreen python -m pytest tests/unit/test_viewer_widget.py::TestMmodeTimeAutoScale -v
```
Expected: BOTH PASS.

- [ ] **Step 5: Check for other regressions in M-mode tests**

Run:
```bash
source .venv/bin/activate && QT_QPA_PLATFORM=offscreen python -m pytest tests/unit/test_viewer_widget.py -q -k "mmode or Mmode"
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/echo_personal_tool/presentation/viewer_widget.py tests/unit/test_viewer_widget.py
git commit -m "fix(mmode): use auto time scale, skip ms dialog when present"
```

---

## Task 3: Spectral velocity wizard — baseline doubles as first point (2 clicks)

**Files:**
- Modify: `src/echo_personal_tool/presentation/viewer_widget.py` — `_begin_doppler_velocity_calibration` (line 3121), `_handle_doppler_calibration_click` (line 3093).
- Modify: `src/echo_personal_tool/infrastructure/locales/en.json`, `src/echo_personal_tool/infrastructure/locales/ru.json`.
- Test: `tests/unit/test_viewer_widget.py`

**Interfaces:**
- Consumes: current `_handle_doppler_calibration_click` baseline branch (sets `_doppler_pending_baseline_y`, builds partial state, calls `_begin_doppler_velocity_calibration`).
- Produces: `_begin_doppler_velocity_calibration(start_y: float | None = None)` — when `start_y` is given, `self._calibration_start_y = start_y` (instead of `None`). The subsequent click in `_handle_calibration_mouse_press`'s doppler branch (length check at line 5497, handler defined at 5454) immediately calls `_prompt_spectral_velocity_span`.

### Background

Baseline step (`_handle_doppler_calibration_click`, 3103-3117) records the baseline then calls `_begin_doppler_velocity_calibration()`, which forces `_calibration_start_y = None` (line 3142). The velocity step then requires a second zero-line click. Fix: the baseline click supplies the segment origin.

- [ ] **Step 1: Add failing GUI tests**

NOTE (pre-flight validated): the view is auto-scaled to fit, so click view-coordinates are NOT identity-mapped to pixel coordinates (e.g. a click at (100,80) maps to ≈(-3,32)). The tests must therefore assert the *propagation invariant* (`_calibration_start_y == _doppler_pending_baseline_y`, and the prompted span equals the mapped difference), not hardcoded pixel values.

Append to `tests/unit/test_viewer_widget.py` inside `class TestDopplerCalibrationClick`:

```python
    def test_baseline_sets_velocity_segment_origin(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((200, 200), dtype=np.uint8))
        assert w.start_doppler_calibration()
        assert w._doppler_cal_step == "baseline"
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QMouseEvent

        event = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(100, 80),
            QPointF(100, 80),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        result = w._handle_doppler_calibration_click(event)
        assert result is True
        assert w._doppler_cal_step is None
        assert w._doppler_pending_baseline_y is not None
        assert w._calibration_start_y == w._doppler_pending_baseline_y

    def test_velocity_click_after_baseline_prompts_span(self, qtbot, monkeypatch) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((200, 200), dtype=np.uint8))
        assert w.start_doppler_calibration()
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QMouseEvent

        def click(x, y):
            return QMouseEvent(
                QEvent.Type.MouseButtonPress,
                QPointF(x, y),
                QPointF(x, y),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )

        w._handle_doppler_calibration_click(click(100, 80))
        assert w._calibration_start_y == w._doppler_pending_baseline_y
        baseline = w._calibration_start_y
        assert baseline is not None

        promoted = []
        monkeypatch.setattr(
            w,
            "_prompt_spectral_velocity_span",
            lambda length_px: promoted.append(length_px),
        )
        result = w._handle_calibration_mouse_press(click(100, 30))
        assert result is True
        assert promoted == [abs(w._map_view_event(click(100, 30))[1] - baseline)]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
source .venv/bin/activate && QT_QPA_PLATFORM=offscreen python -m pytest tests/unit/test_viewer_widget.py::TestDopplerCalibrationClick -v
```
Expected: `test_baseline_sets_velocity_segment_origin` FAILS (`_calibration_start_y` is `None`, not `80.0`); `test_velocity_click_after_baseline_prompts_span` FAILS (`promoted == []`).

- [ ] **Step 3: Implement `start_y` propagation**

Change `_begin_doppler_velocity_calibration` signature and body:

```python
    def _begin_doppler_velocity_calibration(self, start_y: float | None = None) -> None:
        if self._current_frame is None:
            return
        width = self._current_frame.shape[1]
        self._doppler_cal_step = None
        self._calibration_kind = "doppler_velocity"
        self._calibration_active = True
        roi = self._doppler_pending_roi
        if roi is not None:
            self._calibration_x = min(roi.x1 - 4.0, float(width - 5))
            self._doppler_grid_line_positions = detect_doppler_grid_lines(
                self._current_frame,
                x0=int(roi.x0),
                y0=int(roi.y0),
                width=int(roi.width),
                height=int(roi.height),
            )
        else:
            self._calibration_x = min(float(width) * 0.96, float(width - 5))
            self._doppler_grid_line_positions = []
        self._calibration_start_y = start_y
        self._measurement_label.setText(_DOPPLER_CAL_VELOCITY_KEY)
```

Update the baseline branch of `_handle_doppler_calibration_click` (lines 3103-3117) to pass the clicked y:

```python
        if self._doppler_cal_step == "baseline":
            self._doppler_pending_baseline_y = y
            height, width = self._current_frame.shape[:2]
            roi = self._doppler_pending_roi or DopplerSpectrogramRoi(
                x0=0.0, y0=0.0, width=float(width), height=max(1.0, float(height))
            )
            partial = calibration_from_roi_and_baseline(
                roi,
                y,
                time_span_ms=0.0,
                kind=self._doppler_cal_kind,
            )
            self._doppler.set_axis_mapping(build_axis_mapping(partial))
            self._begin_doppler_velocity_calibration(start_y=y)
            return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
source .venv/bin/activate && QT_QPA_PLATFORM=offscreen python -m pytest tests/unit/test_viewer_widget.py -q -k "DopplerCalibrationClick or MmodeTimeAutoScale"
```
Expected: ALL PASS.

- [ ] **Step 5: Update i18n hint strings (en + ru)**

In `en.json` (lines ~771, 778, 816), update the velocity/baseline hints so the workflow reads as 2 clicks (baseline = also the start of the scale):

```json
  "viewer.doppler.cal_baseline": "Doppler calibration: click zero-velocity baseline (also 1st point of velocity scale)",
  "viewer.doppler_cal_velocity": "Doppler calibration: click TOP of velocity scale at spectrum edge (baseline already set)",
  "viewer.spectral_click_end": "Spectrum: click TOP of velocity scale (baseline already set)",
```

In `ru.json` (lines ~771, 778, 816), the matching translations:

```json
  "viewer.doppler.cal_baseline": "Doppler калибровка: клик на линию нулевой скорости (baseline) (также 1-я точка шкалы скорости)",
  "viewer.doppler_cal_velocity": "Doppler калибровка: клик ВЕРХ шкалы скорости на краю спектра (baseline уже задан)",
  "viewer.spectral_click_end": "Спектр: клик ВЕРХ шкалы скорости (baseline уже задан)",
```

- [ ] **Step 6: Run i18n parity test**

Run:
```bash
source .venv/bin/activate && python -m pytest tests/unit/test_i18n.py -q
```
Expected: PASS (en and ru have matching keys).

- [ ] **Step 7: Run full affected test suites**

Run:
```bash
source .venv/bin/activate && QT_QPA_PLATFORM=offscreen python -m pytest tests/unit/test_viewer_widget.py tests/unit/test_main_window_doppler.py tests/unit/test_i18n.py -q
```
Expected: ALL PASS.

- [ ] **Step 8: Commit**

```bash
git add src/echo_personal_tool/presentation/viewer_widget.py src/echo_personal_tool/infrastructure/locales/en.json src/echo_personal_tool/infrastructure/locales/ru.json tests/unit/test_viewer_widget.py
git commit -m "feat(doppler): baseline doubles as first velocity point (2-click wizard)"
```

---

## Task 4: Regression on real Samsung data (manual verification)

**Files:**
- Read-only: `/home/areatu/ECHO2026_src/Новая папка/*.dcm`

**Interfaces:**
- Consumes: the completed Task 1-3 changes plus existing `echo` CLI / viewer.
- Produces: confirmation that real-world files now detect/use the correct scales.

- [ ] **Step 1: Run the project test suite**

Run:
```bash
source .venv/bin/activate && QT_QPA_PLATFORM=offscreen python -m pytest -q
```
Expected: ALL PASS.

- [ ] **Step 2: Verify ROI on real mis-tagged files (17/18/19/61/62)**

Run a one-liner against the real frames (adjust import path as used by the project's scripts):

```bash
source .venv/bin/activate && QT_QPA_PLATFORM=offscreen python - <<'PY'
import numpy as np
import pydicom
from echo_personal_tool.domain.services.spectrogram_detector import detect_spectrogram_roi
import glob, os
d = "/home/areatu/ECHO2026_src/Новая папка"
for f in sorted(glob.glob(os.path.join(d, "*.dcm"))):
    ds = pydicom.dcmread(f)
    arr = ds.pixel_array
    roi = detect_spectrogram_roi(arr)
    print(os.path.basename(f), arr.shape, "->", roi)
PY
```
Expected: `17.dcm` → band ≈ (.., 450ish, .., 624/625); `18.dcm`, `19.dcm` → the LOWER band (y0 ≈ 700, y1 ≈ 843), no longer `None`; `61.dcm`, `62.dcm` → lower band (y0 ≈ 620, y1 ≈ 840). No file returns full-frame fallback for a real Doppler.

- [ ] **Step 3: Report results back to the user (no commit)**

Summarize the four files' ROI output and confirm behavior. Do not commit anything from this task.
