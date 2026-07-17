# Anatomical M-Mode — Design Spec

**Date:** 2026-07-15
**Status:** Approved
**Author:** opencode + user

---

## 1. Overview

Anatomical M-mode (also called "anatomic M-mode" or "guided M-mode") allows the user to place an arbitrary scan line on a 2D echocardiographic image. Pixel intensities along that line are extracted from every frame and displayed as a time-motion strip below the main viewer — just like a real M-mode trace from a phased-array transducer, but reconstructed from a standard 2D cine loop.

### Requirements Summary

| # | Requirement |
|---|-------------|
| R1 | Arbitrary-angle scan line (caliper-style, two clicks) |
| R2 | Scrolling sweep display (time horizontal left→right, depth vertical top→bottom) |
| R3 | Separate tool with hotkey `Shift+M` (plain `M` taken by MBS-lite contour mode) |
| R4 | M-mode calipers for distance (mm) and time (ms) on the M-mode panel |
| R5 | Full synchronization with 2D playback |
| R6 | Dashed line with endpoint markers on 2D viewer |
| R7 | Main viewer shrinks ~50%, M-mode panel appears below on activation |

---

## 2. Architecture

### 2.1 New Files

| File | Purpose |
|------|---------|
| `domain/models/mmode.py` | `MModeScanLine`, `MModeState`, `MModeCaliperMeasurement` |
| `domain/services/mmode_extractor.py` | `extract_mmode_column()` — bilinear interpolation along a line |
| `presentation/mmode_widget.py` | `MModeWidget` — PyQtGraph panel for M-mode strip display |
| `presentation/mmode_scan_line.py` | `MModeScanLineItem` — dashed line + markers on 2D viewer |
| `presentation/mmode_caliper.py` | `MModeCaliperTool` — distance/time calipers on M-mode panel |

### 2.2 Modified Files

| File | Changes |
|------|---------|
| `presentation/viewer_widget.py` | M-mode line handling, `extract_mmode_column` call on frame load, signals `mmode_column_ready`, `mmode_line_completed` |
| `presentation/main_window.py` | Vertical QSplitter for M-mode, toggle, synchronization |
| `application/app_controller.py` | M-mode state coordination, calibration delegation |

### 2.3 Data Flow

```
Frame loaded (scroll/playback)
  → ViewerWidget._on_frame_loaded()
    → emit mmode_column_ready(extract_mmode_column(frame, line))
      → MModeWidget.on_new_column(column)
        → update _image_buffer (circular)
        → pg.ImageItem.setImage()
        → move sweep line
```

---

## 3. Layout Changes

### Current Layout

```
[SystemBar]
[ThumbnailGallery | ViewerWidget | ToolPanel(280px)]
[StatusBar]
```

### M-Mode Layout

```
[SystemBar]
[ThumbnailGallery | QSplitter(V)                          | ToolPanel(280px)]
                  | [ViewerWidget ~50%]                    |
                  | [──────── splitter handle ───────────] |
                  | [MModeWidget ~50%]                     |
[StatusBar]
```

**Implementation:**
- `MainWindow._rebuild_layout()` checks `MModeState.active`
- When active: wraps ViewerWidget + MModeWidget in a vertical `QSplitter`
- Splitter handle width = 4px, initial proportions 50/50
- User can drag splitter to adjust
- When deactivated: removes vertical splitter, ViewerWidget returns to full size
- ViewerWidget internal layout is untouched — it simply receives less space

---

## 4. M-Mode Scan Line Tool

### Activation

- Hotkey `Shift+M` or toolbar button
- Cursor on 2D viewer changes to `Qt.CrossCursor`
- Status bar shows: "Click to set M-mode scan line start"

### Interaction (clicks on 2D viewer)

1. **Click 1** — set start point A
2. **Drag** — live preview: dashed line A→cursor + preview column in M-mode panel
3. **Click 2** — set end point B, line is fixed
4. **Drag endpoints** — `_MModeNodeItem` (like `_CaliperNodeItem`), line updates, M-mode recalculates for cached frames
5. **Escape / press Shift+M again** — deactivate M-mode

### Line Rendering on 2D Viewer

- `MModeScanLineItem(QObject)` — manages graphics items, holds state, delegates mouse events to `ViewerWidget`
- Line: `pg.PlotDataItem` with `pen=pg.mkPen(color='cyan', style=Qt.DashLine, width=1.5)`, Z=24
- Endpoint markers: `_MModeNodeItem(pg.ScatterPlotItem)` — circular (symbol="o", size=10, cyan), Z=30
- `_MModeNodeItem` pattern matches `_CaliperNodeItem`: holds back-reference to `ViewerWidget`, overrides `mousePressEvent`/`mouseDragEvent`/`mouseReleaseEvent`, calls `viewer_widget._begin_mmode_node_drag()` etc.
- All items added/removed via `self._view.addItem(item)` / `self._view.removeItem(item)`

### Extraction Algorithm

```python
def extract_mmode_column(
    frame: np.ndarray,          # shape (H, W), uint8 or uint16
    start: tuple[float, float], # (x1, y1) in pixels
    end: tuple[float, float],   # (x2, y2) in pixels
    num_samples: int = 256      # depth resolution
) -> np.ndarray:                # shape (num_samples,), same dtype as frame
    t = np.linspace(0, 1, num_samples)
    xs = start[0] + t * (end[0] - start[0])
    ys = start[1] + t * (end[1] - start[1])
    return scipy.ndimage.map_coordinates(
        frame.astype(np.float64), [ys, xs], order=1, mode='nearest'
    ).astype(frame.dtype)
```

**Performance:** < 1ms for 256 samples on a 512x512 frame.

---

## 5. MModeWidget — M-Mode Panel

### Visual Structure

```
┌──────────────────────────────────────────────────────┐
│  0 ms                                     1200 ms    │  ← time axis (top)
│  ┌────────────────────────────────────────────────┐  │
│  │ ▓▓▓▓░░░░▓▓▓▓▓▓░░░░░░▓▓▓▓▓▓▓▓░░░░▓▓▓▓▓▓▓▓▓ │  │
│  │ ▓▓▓▓▓░░░░░░░▓▓▓▓░░░░░░░░▓▓▓▓▓░░░░░░░▓▓▓▓▓ │  │
│  │ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │  │  ← M-mode image
│  │ ▓▓▓▓▓▓░░░░▓▓▓▓▓▓░░░░▓▓▓▓▓▓░░░░▓▓▓▓▓▓░░░░▓ │  │
│  │ ▓▓▓▓▓▓▓░░░░░░░▓▓▓▓▓░░░░░░▓▓▓▓░░░░░░░▓▓▓▓▓ │  │
│  └────────────────────────────────────────────────┘  │
│  0 mm                                     100 mm     │  ← depth axis (bottom)
│           ▲ sweep line (red vertical)                 │
└──────────────────────────────────────────────────────┘
```

### Implementation

- `MModeWidget(QWidget)` containing `pg.PlotWidget`
- `pg.ImageItem(axisOrder="row-major")` for the M-mode grayscale image
- Axes: top = time (ms), bottom = depth (mm)
- **Sweep line:** `pg.InfiniteLine(angle=90, color='red', movable=False)`
- **Circular buffer:** numpy array shape `(num_samples, buffer_width)`

### Buffer Management

- Initial `buffer_width` = 512 columns (≈17 sec at 30 fps)
- When video is longer: expand buffer to match total frame count
- Circular wrap: when `sweep_x` reaches `buffer_width`, wrap to 0
- Old data scrolls off left edge

### Column Update

```python
def on_new_column(self, column: np.ndarray):
    self._image_buffer[:, self._sweep_x] = column
    self._sweep_x = (self._sweep_x + 1) % self._buffer_width
    self._image_item.setImage(self._image_buffer, autoLevels=True)
    self._sweep_line.setValue(self._sweep_x)
```

### Axis Calibration

- **Vertical (depth, mm):** from `MmodeCalibrationState.vertical_mm_per_pixel` or DICOM `PhysicalDeltaX`
- **Horizontal (time, ms):** from DICOM `FrameTime` tag or manual calibration
- **Fallback:** pixel indices and frame numbers

---

## 6. M-Mode Calipers

### Types

**Vertical caliper (distance):**
- Click on M-mode panel → vertical line placed
- Second click → measurement fixed
- Display: "12.3 mm" (calibrated) or "45 px" (un calibrated)
- Use case: wall thickness, cavity dimension

**Horizontal caliper (time):**
- Click → horizontal line
- Second click → fixed
- Display: "320 ms" (calibrated) or "12 frames" (un calibrated)
- Use case: contraction time, intervals

### Visual

```
│         │
│    ─────┤  12.3 mm
│         │
```

- Lines: `pg.PlotDataItem` yellow
- Text: `pg.TextItem` 10pt
- Ends: `pg.ScatterPlotItem` draggable circles

### Storage

- Stored in `StudyMeasurementSession` (same as regular calipers)
- Associated with instance UID + scan line position

---

## 7. Synchronization

### During Playback/Scroll

1. `AppController` loads frame → `ViewerWidget.show_frame()`
2. Additionally: `MModeWidget.on_new_column(extract_mmode_column(frame, line))`
3. Sweep line moves to current frame position

### On File Change

- M-mode buffer cleared
- Scan line preserved (if same study/instance)
- Calibration recalculated from new DICOM tags

### On Scan Line Drag

- For ALL cached frames (FrameCache): recalculate columns
- M-mode panel updates instantly (< 10ms for 40 cached frames)
- Uncached frames fill in on next access

---

## 8. Edge Cases

| Situation | Behavior |
|-----------|----------|
| No DICOM calibration | Axes show pixels and frame numbers |
| Video < 10 frames | M-mode fills partially, sweep line stationary |
| Very long line | `num_samples` = line length in pixels (cap: 512) |
| Very short line | Minimum 32 samples, warning if shorter |
| No FrameTime in DICOM | Default 33ms (30 fps) |
| Multiview (two viewers) | M-mode binds to active viewer |
| Line outside image bounds | `map_coordinates` with `mode='nearest'` — safe |

---

## 9. Performance Budget

| Operation | Time |
|-----------|------|
| `extract_mmode_column` (256 pts, 512x512) | < 1ms |
| `pg.ImageItem.setImage` (512x256) | < 2ms |
| Recalculate 40 cached frames | < 40ms |
| **Total per-frame update** | **< 5ms** |

---

## 10. Testing Strategy

| Test | Type |
|------|------|
| `extract_mmode_column` with known gradient image | Unit |
| MModeWidget buffer fill/wrap | Unit |
| MModeWidget axis calibration display | Unit |
| M-mode caliper distance calculation | Unit |
| M-mode caliper time calculation | Unit |
| Scan line drag → M-mode recalculation | Integration |
| Toggle M-mode on/off layout change | Integration |
| Full playback → M-mode sweep fill | Integration |

---

## 11. Dependencies

- `scipy.ndimage.map_coordinates` — already a project dependency (`scipy>=1.11`)
- `pyqtgraph` — already used throughout (`pg.ImageItem`, `pg.PlotWidget`, etc.)
- No new external dependencies required
