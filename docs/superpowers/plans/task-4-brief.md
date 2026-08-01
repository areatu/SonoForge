# Task 4: Banner Format with Actual Values

**Files:**
- Modify: `src/echo_personal_tool/presentation/properties_panel.py:241-251`
- Modify: `src/echo_personal_tool/infrastructure/properties_snapshot.py` (add new fields)
- Modify: `src/echo_personal_tool/infrastructure/properties_extractor.py` (pass new flags)
- Test: `tests/unit/test_properties_panel.py`

**Interfaces:**
- Consumes: `PropertiesSnapshot` with new fields: `mmode_vertical_mm_per_pixel`, `mmode_horizontal_ms_per_pixel`, `mmode_has_depth_from_dicom`, `mmode_has_time_from_dicom`
- Produces: Banner text like "0.15 mm/px, 2.5 ms/px (DICOM)"

## Steps

### Step 1: Add new fields to PropertiesSnapshot

Modify `src/echo_personal_tool/infrastructure/properties_snapshot.py`:

```python
@dataclass(frozen=True)
class PropertiesSnapshot:
    # ... existing fields ...
    mmode_calibrated: bool = False
    mmode_has_time_scale: bool = False
    mmode_vertical_mm_per_pixel: float | None = None  # NEW
    mmode_horizontal_ms_per_pixel: float | None = None  # NEW
    mmode_has_depth_from_dicom: bool = False  # NEW
    mmode_has_time_from_dicom: bool = False  # NEW
    # ... rest of fields ...
```

### Step 2: Update properties_extractor to pass new flags

Modify `src/echo_personal_tool/infrastructure/properties_extractor.py`:

```python
def extract_properties_snapshot(
    path: Path,
    *,
    depth_ok: bool = False,
    mmode_calibrated: bool = False,
    mmode_has_time_scale: bool = False,
    mmode_vertical_mm_per_pixel: float | None = None,  # NEW
    mmode_horizontal_ms_per_pixel: float | None = None,  # NEW
    mmode_has_depth_from_dicom: bool = False,  # NEW
    mmode_has_time_from_dicom: bool = False,  # NEW
    doppler_calibrated: bool = False,
    doppler_has_time_from_dicom: bool = False,
    doppler_has_velocity_from_dicom: bool = False,
    doppler_partial: bool = False,
) -> PropertiesSnapshot:
    # ... existing code ...
    return PropertiesSnapshot(
        # ... existing fields ...
        mmode_calibrated=mmode_calibrated,
        mmode_has_time_scale=mmode_has_time_scale,
        mmode_vertical_mm_per_pixel=mmode_vertical_mm_per_pixel,
        mmode_horizontal_ms_per_pixel=mmode_horizontal_ms_per_pixel,
        mmode_has_depth_from_dicom=mmode_has_depth_from_dicom,
        mmode_has_time_from_dicom=mmode_has_time_from_dicom,
        # ... rest of fields ...
    )
```

### Step 3: Update caller in main_window.py

Modify `src/echo_personal_tool/presentation/main_window.py` where `extract_properties_snapshot` is called:

```python
# Find the call site and add new parameters
snapshot = extract_properties_snapshot(
    path,
    depth_ok=depth_ok,
    mmode_calibrated=mmode.is_complete() if mmode else False,
    mmode_has_time_scale=mmode.has_time_scale() if mmode else False,
    mmode_vertical_mm_per_pixel=mmode.vertical_mm_per_pixel if mmode else None,
    mmode_horizontal_ms_per_pixel=mmode.horizontal_ms_per_pixel if mmode else None,
    mmode_has_depth_from_dicom=mmode.has_depth_from_dicom() if mmode else False,
    mmode_has_time_from_dicom=mmode.has_time_from_dicom() if mmode else False,
    # ... other parameters ...
)
```

### Step 4: Write failing tests for banner format

Add to `tests/unit/test_properties_panel.py` (or create if not exists):

```python
def test_mmode_banner_with_values_and_dicom_source():
    """M-mode banner shows actual values with DICOM source."""
    from echo_personal_tool.infrastructure.properties_snapshot import PropertiesSnapshot
    from echo_personal_tool.presentation.properties_panel import PropertiesPanel
    
    snapshot = PropertiesSnapshot(
        modality="US",
        mmode_calibrated=True,
        mmode_has_time_scale=True,
        mmode_vertical_mm_per_pixel=0.15,
        mmode_horizontal_ms_per_pixel=2.5,
        mmode_has_depth_from_dicom=True,
        mmode_has_time_from_dicom=True,
    )
    
    panel = PropertiesPanel()
    panel.update_from_snapshot(snapshot)
    
    # Find the M-mode row and check text
    mmode_row = panel.findChild(QLabel, "mmode_calibration")
    assert mmode_row is not None
    assert "0.15 mm/px" in mmode_row.text()
    assert "2.5 ms/px" in mmode_row.text()
    assert "(DICOM)" in mmode_row.text()


def test_mmode_banner_partial_no_depth():
    """M-mode banner shows partial status when no depth."""
    from echo_personal_tool.infrastructure.properties_snapshot import PropertiesSnapshot
    from echo_personal_tool.presentation.properties_panel import PropertiesPanel
    
    snapshot = PropertiesSnapshot(
        modality="US",
        mmode_calibrated=False,
        mmode_has_time_scale=True,
        mmode_has_depth_from_dicom=False,
        mmode_has_time_from_dicom=True,
    )
    
    panel = PropertiesPanel()
    panel.update_from_snapshot(snapshot)
    
    mmode_row = panel.findChild(QLabel, "mmode_calibration")
    assert mmode_row is not None
    assert "Partial" in mmode_row.text()
```

### Step 5: Run tests to verify they fail

Run: `/home/areatu/ECHO2026/.venv/bin/python -m pytest tests/unit/test_properties_panel.py -v`
Expected: FAIL with `AssertionError` or `AttributeError`

### Step 6: Implement banner format

Modify `src/echo_personal_tool/presentation/properties_panel.py`:

```python
def _add_mmode_calibration_row(self, snapshot: PropertiesSnapshot) -> None:
    """Add M-mode calibration status row."""
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
        status = tr("properties.calibration.missing")
    
    self._calibration_form.addRow(tr("properties.calibration.mmode"), QLabel(status))
```

### Step 7: Run tests to verify they pass

Run: `/home/areatu/ECHO2026/.venv/bin/python -m pytest tests/unit/test_properties_panel.py -v`
Expected: All PASS

### Step 8: Commit

```bash
git add src/echo_personal_tool/infrastructure/properties_snapshot.py src/echo_personal_tool/infrastructure/properties_extractor.py src/echo_personal_tool/presentation/main_window.py src/echo_personal_tool/presentation/properties_panel.py tests/unit/test_properties_panel.py
git commit -m "feat(banner): show actual M-mode calibration values with source

- Add mmode_vertical_mm_per_pixel, mmode_horizontal_ms_per_pixel to snapshot
- Add mmode_has_depth_from_dicom, mmode_has_time_from_dicom to snapshot
- Banner shows '0.15 mm/px, 2.5 ms/px (DICOM)' format
- Partial status shows 'Partial — no depth deltas'"
```

## Report

Write your report to `/home/areatu/ECHO2026/docs/superpowers/plans/task-4-report.md` with:
- Status: DONE, DONE_WITH_CONCERNS, NEEDS_CONTEXT, or BLOCKED
- Commits made
- Test results
- Any concerns
