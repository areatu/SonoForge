# Task 1: M-mode Model Enhancement — Report

## Status: DONE

## What Was Implemented

Enhanced `MmodeCalibrationState` with a parallel API to `DopplerCalibrationState`:

**New fields:**
- `depth_from_dicom_tags: bool = False`
- `time_from_dicom_tags: bool = False`

**New methods:**
- `is_partial()` — True when exactly one axis (depth or time) is calibrated
- `has_depth_scale()` — True when `vertical_mm_per_pixel` is set and > 0
- `has_time_scale()` — True when `horizontal_ms_per_pixel` is set and > 0
- `has_depth_from_dicom()` — True when `depth_from_dicom_tags` and valid depth
- `has_time_from_dicom()` — True when `time_from_dicom_tags` and valid time
- `is_dicom_trusted()` — True when `from_dicom_tags` and both axes complete

**Changed behavior:**
- `is_complete()` now requires **both** depth and time axes (previously only depth). This aligns M-mode with Doppler's completion semantics.

## Commits

- `dd4a19f` — `feat(mmode): enhance MmodeCalibrationState with parallel API to Doppler`

## Test Results

- 27/27 passing in `test_mmode_calibration.py`
- Ruff: all checks passed

### TDD Evidence

**RED:** All 10 new tests failed with `AttributeError: 'MmodeCalibrationState' object has no attribute 'is_partial'` (as expected — methods didn't exist yet).

**GREEN:** After implementation, all 27 tests pass (10 new + 17 existing, with 3 existing tests updated for the `is_complete()` semantic change).

## Files Changed

- `src/echo_personal_tool/domain/models/frame_panels.py` — Added fields and methods to `MmodeCalibrationState`
- `tests/unit/test_mmode_calibration.py` — Added `TestMmodeCalibrationStateEnhanced` (10 tests), updated 3 existing tests

## Self-Review Findings

**No concerns.** The implementation:
- Follows the exact plan specification
- Matches `DopplerCalibrationState` API pattern
- Existing callers of `is_complete()` in `viewer_widget.py` and `main_window.py` will see the new behavior (M-mode now requires both axes for "complete"), which is the intended semantic alignment
- `mmode_state_from_panel()` populates both axes from the panel, so normal flow is unaffected
