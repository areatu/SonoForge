# Task 4 Report: Banner Format with Actual Values

**Status:** DONE

## What was implemented

Updated the M-mode calibration banner in `PropertiesPanel` to show actual calibration values with source indicator instead of just "Complete/Partial/Missing".

### Changes

1. **`src/echo_personal_tool/domain/models/properties_snapshot.py`**
   - Added 4 new fields with defaults (placed at end to avoid dataclass ordering issues):
     - `mmode_vertical_mm_per_pixel: float | None = None`
     - `mmode_horizontal_ms_per_pixel: float | None = None`
     - `mmode_has_depth_from_dicom: bool = False`
     - `mmode_has_time_from_dicom: bool = False`

2. **`src/echo_personal_tool/infrastructure/properties_extractor.py`**
   - Added 4 new keyword parameters to `extract_properties_snapshot()`
   - Passes them through to `PropertiesSnapshot`

3. **`src/echo_personal_tool/presentation/main_window.py`**
   - Updated call site to pass M-mode calibration values from `mmode` state object
   - Fixed `mmode_has_time_scale` to use `has_time_scale()` instead of `has_time_from_dicom()`

4. **`src/echo_personal_tool/presentation/properties_panel.py`**
   - Updated `_add_mmode_calibration_row()` to:
     - Show actual values: `"0.15 mm/px, 2.50 ms/px"`
     - Show source indicator: `(DICOM)` when both depth and time from DICOM
     - Fallback to `"Complete"` text if no values available despite calibrated flag
   - Added `setObjectName("mmode_calibration")` to M-mode QLabel for testability

5. **`tests/unit/test_properties_extractor.py`**
   - Added `test_extract_mmode_calibration_values`: verifies new fields are passed through
   - Added `test_extract_mmode_calibration_defaults`: verifies defaults are `None`/`False`

6. **`tests/unit/test_presentation_extended.py`**
   - Added `test_mmode_banner_with_values_and_dicom_source`: full DICOM calibration shows values + "(DICOM)"
   - Added `test_mmode_banner_partial_no_depth`: partial calibration shows "Partial"
   - Added `test_mmode_banner_values_only_no_source`: values without DICOM source show no source tag

## TDD Evidence

### RED
```bash
$ python -m pytest tests/unit/test_presentation_extended.py::TestPropertiesPanel::test_mmode_banner_with_values_and_dicom_source -v
# Initially failed: TypeError: non-default argument 'doppler_calibrated' follows default argument
# (Fields with defaults placed before fields without defaults in frozen dataclass)
```

After fixing field ordering:
```bash
# Failed with: NameError: name 'QLabel' is not defined (test import issue)
# After fixing imports: assert '2.5 ms/px' in '0.15 mm/px, 2.50 ms/px (DICOM)'
# (Expected format didn't match actual format with 2 decimal places)
```

### GREEN
```bash
$ python -m pytest tests/unit/test_properties_extractor.py tests/unit/test_presentation_extended.py::TestPropertiesPanel -v
# 32 passed, 2 pre-existing failures (unrelated)
```

## Pre-existing test failures (unrelated to this task)
- `test_bmi_calculation`: expects `>= 8` rows but gets 7 (legacy API count mismatch)
- `test_update_instance_all_fields`: same root cause

## Files changed
- `src/echo_personal_tool/domain/models/properties_snapshot.py`
- `src/echo_personal_tool/infrastructure/properties_extractor.py`
- `src/echo_personal_tool/presentation/main_window.py`
- `src/echo_personal_tool/presentation/properties_panel.py`
- `tests/unit/test_properties_extractor.py`
- `tests/unit/test_presentation_extended.py`
