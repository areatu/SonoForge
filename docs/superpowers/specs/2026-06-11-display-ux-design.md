# Display UX — Browser, Color, W/L+DR, Thumbnails

**Date:** 2026-06-11  
**Status:** Approved (continuation of UI feedback sprint)  
**Scope:** Items 1, 3, 7, 8 from original UI feedback  
**Depends on:** DICOM Performance (`FrameCache`, `DicomSession`) — complete

---

## Problems

| # | Issue | Root cause |
|---|-------|------------|
| 1 | DICOM names in browser show SOP UID prefix | `_instance_label` special-cases `media_format == "dicom"` |
| 3 | DICOM shown as grayscale | `stack_pixel_array` strips RGB to channel 0; no PALETTE COLOR handling |
| 7 | Limited contrast control | W/L sliders only; no explicit dynamic-range (percentile) clipping |
| 8 | Thumbnails too small | `THUMBNAIL_SIZE = 64`; default `QTreeWidget` icon size |

## Goals

1. All instances in the browser tree show **disk filename** (`path.name`) plus frame count.
2. DICOM RGB / PALETTE COLOR ultrasound displays in **color** in viewer and thumbnails when source is color.
3. Grayscale DICOM retains **Window / Level** plus new **DR low / DR high** percentile sliders (0–100) to clip display range before W/L.
4. Sidebar thumbnails default to **128×128** px with matching `QTreeWidget.iconSize`.

## Non-goals

- Measurement tools (item 9), ED/ES workflow (items 5–6)
- ONNX / segmentation changes
- DICOM performance / caching changes beyond color-shaped arrays in `FrameCache`

---

## Architecture

```
DicomSession.decode → (N,H,W) or (N,H,W,3)
FrameCache          → same shapes
ViewerWidget        → show_frame: color path if (H,W,3); else W/L+DR on grayscale
LocalBrowser        → path.name labels; iconSize 128
ThumbnailLoader     → THUMBNAIL_SIZE 128; color QImage path unchanged
```

## Component changes

### 1. Browser labels (`local_browser.py`)

- `_instance_label`: always use `instance.path.name` when `path` is set; fallback to shortened UID only if no path.
- Format: `{filename} ({N} frames)` or `{filename} (1 frame)`.

### 2. DICOM color (`dicom_session.py`, `frame_cache.py`, `pixel_utils.py`)

- `stack_pixel_array`: preserve trailing RGB/A dimensions → `(N,H,W,3)`; do **not** take `[..., 0]` for color.
- `read_frame`: return `(H,W)` or `(H,W,3)` uint8/float as decoded.
- `FrameCache.load`: accept `ndim==3` `(N,H,W)` or `ndim==4` `(N,H,W,C)` where `C in (3,4)`.
- Add `infrastructure/dicom_color.py` with `frame_to_display_bgr(frame, dataset_meta)` if needed for PALETTE COLOR via pydicom `apply_color_lut` (infrastructure only).
- Synthetic fixture: `write_synthetic_rgb_dicom` with `PhotometricInterpretation="RGB"`, `SamplesPerPixel=3`.

### 3. Thumbnails (`thumbnail_loader_worker.py`, `local_browser.py`)

- `THUMBNAIL_SIZE = 128`
- `LocalBrowserWidget.__init__`: `self.setIconSize(QSize(128, 128))`

### 4. Window / Level + Dynamic Range (`viewer_widget.py`)

On grayscale `show_frame`:

- Store raw frame and compute `_dr_low_pct`, `_dr_high_pct` (default 0, 100).
- Compute display bounds: `vmin/vmax` from percentiles of frame data, then apply W/L to get `setLevels((low, high))`.
- Add sliders **DR min %** and **DR max %** (0–100, default 0/100) below W/L row.
- Color frames: DR/W/L disabled (as today).

Percentile function in `pixel_utils.py`:

```python
def percentile_range(frame: np.ndarray, low_pct: float, high_pct: float) -> tuple[float, float]:
    ...
```

## Testing

| Test file | Cases |
|-----------|-------|
| `test_local_browser_labels.py` | DICOM shows filename not UID |
| `test_dicom_session.py` | RGB synthetic DICOM → `(N,H,W,3)` |
| `test_frame_cache.py` | load/get 4D color stack |
| `test_thumbnail_qimage.py` | size 128; color preserved |
| `test_viewer_display_range.py` | DR percentiles change levels (unit test logic, optional Qt-off) |

## Success criteria

- [ ] Browser shows `study.dcm (45 frames)` not UID prefix
- [ ] RGB DICOM renders in color in viewer
- [ ] Thumbnails visibly larger (128px) in sidebar
- [ ] DR sliders adjust grayscale contrast; W/L still works
- [ ] All pytest pass; ruff clean
