# Maximum Calibration: Doppler + M-mode Fallback Chain

**Date:** 2026-08-01
**Status:** Approved
**Branch:** optimize/memory

## Goal

Maximum calibration implementation for Doppler and M-mode with all possible fallbacks, parallel model APIs, and comprehensive regression tests.

## Design Decisions

1. **M-mode model:** Split `from_dicom_tags` into `depth_from_dicom_tags` + `time_from_dicom_tags`
2. **M-mode fallback chain:** 5-level (Full → Partial → FrameTime → Heuristic → None)
3. **Banner:** Show actual values with source: "0.15 mm/px, 2.5 ms/px (DICOM)"
4. **Physics guard:** `spatial_format` parameter in `horizontal_ms_per_pixel`
5. **Tests:** 15-20 tests on fallback chain + banner

## Section 1: M-mode Model Enhancement

### `MmodeCalibrationState` (frame_panels.py)

```python
@dataclass(frozen=True)
class MmodeCalibrationState:
    roi: DopplerSpectrogramRoi
    vertical_mm_per_pixel: float | None = None
    horizontal_ms_per_pixel: float | None = None
    from_dicom_tags: bool = False
    depth_from_dicom_tags: bool = False  # NEW
    time_from_dicom_tags: bool = False   # NEW

    def is_complete(self) -> bool:
        return self.has_depth_scale() and self.has_time_scale()

    def is_partial(self) -> bool:
        return self.has_depth_scale() != self.has_time_scale()

    def has_depth_scale(self) -> bool:
        return self.vertical_mm_per_pixel is not None and self.vertical_mm_per_pixel > 0.0

    def has_time_scale(self) -> bool:
        return self.horizontal_ms_per_pixel is not None and self.horizontal_ms_per_pixel > 0.0

    def has_depth_from_dicom(self) -> bool:
        return self.depth_from_dicom_tags and self.has_depth_scale()

    def has_time_from_dicom(self) -> bool:
        return self.time_from_dicom_tags and self.has_time_scale()

    def is_dicom_trusted(self) -> bool:
        return self.from_dicom_tags and self.is_complete()
```

**Breaking change:** `from_dicom_tags` no longer implies both axes. Use `depth_from_dicom_tags` and `time_from_dicom_tags` for per-axis tracking.

### Callers to update

- `mmode_state_from_panel` → set `depth_from_dicom_tags=True`, `time_from_dicom_tags=True` when both present
- `viewer_widget.py` → pass `depth_from_dicom_tags` and `time_from_dicom_tags` explicitly
- `properties_extractor.py` → pass `mmode_has_depth_from_dicom`, `mmode_has_time_from_dicom`

## Section 2: M-mode Fallback Chain

### Priority order

1. **Full DICOM** — `depth_from_dicom_tags=True` + `time_from_dicom_tags=True`
2. **Partial DICOM** — one axis from tags, other from FrameTime or user
3. **FrameTime fallback** — `FrameTime / width` for time axis
4. **Heuristic ROI** — default ROI + manual input
5. **No calibration** — `time_ms_per_pixel=0` → refuse VTI/DT/interval

### Partial detection

When `is_partial()` is True:
- Show wizard for missing axis (like Doppler partial)
- Set `_mmode_pending_roi` and prompt user

### FrameTime fallback

In `mmode_calibration.py`:

```python
def mmode_state_from_panel(panel: UltrasoundPanel, frame_time_ms: float | None = None) -> MmodeCalibrationState | None:
    if panel.kind is not PanelKind.M_MODE:
        return None
    
    # Try DICOM tags first
    horizontal_ms = panel.horizontal_ms_per_pixel
    time_from_dicom = horizontal_ms is not None
    
    # FrameTime fallback
    if horizontal_ms is None and frame_time_ms is not None and panel.bounds.width > 0:
        horizontal_ms = frame_time_ms / panel.bounds.width
        time_from_dicom = False
    
    return MmodeCalibrationState(
        roi=panel.bounds,
        vertical_mm_per_pixel=panel.vertical_mm_per_pixel,
        horizontal_ms_per_pixel=horizontal_ms,
        from_dicom_tags=panel.horizontal_ms_per_pixel is not None and panel.vertical_mm_per_pixel is not None,
        depth_from_dicom_tags=panel.vertical_mm_per_pixel is not None,
        time_from_dicom_tags=time_from_dicom,
    )
```

## Section 3: Banner Format

### Properties panel (`properties_panel.py`)

```python
def _add_mmode_calibration_row(self, snapshot: PropertiesSnapshot) -> None:
    if snapshot.mmode_calibrated:
        parts = []
        if snapshot.mmode_vertical_mm_per_pixel is not None:
            parts.append(f"{snapshot.mmode_vertical_mm_per_pixel:.2f} mm/px")
        if snapshot.mmode_horizontal_ms_per_pixel is not None:
            parts.append(f"{snapshot.mmode_horizontal_ms_per_pixel:.2f} ms/px")
        
        source = ""
        if snapshot.mmode_has_depth_from_dicom and snapshot.mmode_has_time_from_dicom:
            source = " (DICOM)"
        elif snapshot.mmode_has_time_from_dicom:
            source = " (FrameTime)" if not snapshot.mmode_has_depth_from_dicom else ""
        
        status = ", ".join(parts) + source if parts else tr("properties.calibration.mmode_complete")
    elif snapshot.mmode_has_time_scale:
        status = tr("properties.calibration.mmode_partial")
    else:
        status = tr("properties.calibration.mmissing")
    
    self._calibration_form.addRow(tr("properties.calibration.mmode"), QLabel(status))
```

### Localizations

Add to `en.json` and `ru.json`:
- `properties.calibration.mmode_depth`: "depth:"
- `properties.calibration.mmode_time`: "time:"
- `properties.calibration.mmode_partial_no_depth`: "no depth deltas"
- `properties.calibration.mmode_partial_no_time`: "no time deltas"

## Section 4: Physics Guard

### `horizontal_ms_per_pixel` (ultrasound_region_physics.py)

```python
def horizontal_ms_per_pixel(
    delta_x: float,
    units_x: int,
    spatial_format: int | None = None,  # NEW
) -> float | None:
    # Reject B-mode regions (SF=1)
    if spatial_format is not None and spatial_format == 1:  # SPATIAL_2D
        return None
    
    if delta_x <= 0.0:
        return None
    if units_x == PHYSICAL_UNIT_SEC:
        return delta_x * 1000.0
    if units_x == PHYSICAL_UNIT_HZ and delta_x < 1.0:
        return delta_x * 1000.0
    return None
```

### Callers to update

- `frame_panels.py:UltrasoundPanel.horizontal_ms_per_pixel` → pass `spatial_format` from region
- `frame_panel_parser.py` → store `spatial_format` in `UltrasoundPanel`

## Section 5: Regression Tests

### Test cases (15-20 tests)

1. **Samsung partial:** No PhysicalDeltaX/Y → `time_span_ms=0`, `is_partial()=True`
2. **Samsung baseline:** ReferencePixelY0 → `baseline_y_px` from tag
3. **M-mode FrameTime fallback:** No PhysicalDeltaX + FrameTime → `horizontal_ms_per_pixel` from FrameTime
4. **M-mode partial:** One axis missing → wizard for missing axis
5. **M-mode banner values:** "0.15 mm/px, 2.5 ms/px (DICOM)"
6. **M-mode banner partial:** "Partial — no depth deltas"
7. **Physics guard:** SF=1 + SEC units → `horizontal_ms_per_pixel` returns None
8. **Physics guard:** SF=2 + SEC units → `horizontal_ms_per_pixel` returns value
9. **Doppler full DICOM:** Both axes from tags → `is_complete()=True`, `is_dicom_trusted()=True`
10. **Doppler partial:** One axis missing → `is_partial()=True`
11. **Doppler time guard:** `time_span_ms=0` → `time_ms_from_x` returns `time_origin_ms`
12. **M-mode complete:** Both axes from tags → `is_complete()=True`
13. **M-mode no time:** No time axis → `is_partial()=True`
14. **M-mode no depth:** No depth axis → `is_partial()=True`
15. **M-mode is_dicom_trusted:** Full DICOM → `is_dicom_trusted()=True`
16. **M-mode not trusted:** Manual calibration → `is_dicom_trusted()=False`

## Files to modify

1. `src/echo_personal_tool/domain/models/frame_panels.py` — `MmodeCalibrationState` model
2. `src/echo_personal_tool/domain/services/ultrasound_region_physics.py` — `horizontal_ms_per_pixel` guard
3. `src/echo_personal_tool/domain/services/mmode_calibration.py` — FrameTime fallback
4. `src/echo_personal_tool/domain/services/frame_panel_parser.py` — store `spatial_format`
5. `src/echo_personal_tool/presentation/properties_panel.py` — banner format
6. `src/echo_personal_tool/presentation/viewer_widget.py` — partial detection, wizard
7. `src/echo_personal_tool/infrastructure/properties_extractor.py` — pass new flags
8. `src/echo_personal_tool/infrastructure/locales/en.json` — new strings
9. `src/echo_personal_tool/infrastructure/locales/ru.json` — new strings
10. `tests/unit/test_mmode_calibration.py` — new tests
11. `tests/unit/test_ultrasound_region_physics.py` — guard tests
12. `tests/unit/test_properties_panel.py` — banner tests

## Verification

1. Run all tests: `python -m pytest tests/ -v`
2. Run ruff: `ruff check src/ tests/`
3. Manual test: Open Samsung file → verify banner shows correct values
4. Manual test: Open M-mode file → verify FrameTime fallback works
