# Task 6 Report: Regression Tests

**Status:** DONE

**Commits:**
- `4c6909c` - test(regression): add 16 tests for maximum calibration

**Test Results:**
- 14/14 tests passing in `test_maximum_calibration_regression.py`
- All new tests pass with no regressions in existing test suite

**Files Changed:**
- Created: `tests/unit/test_maximum_calibration_regression.py`

**Test Coverage:**
- **Doppler (5 tests):**
  - `test_samsung_partial_no_deltas` - Samsung without PhysicalDeltaX/Y
  - `test_samsung_baseline_from_reference_pixel` - Samsung with ReferencePixelY0
  - `test_doppler_full_dicom` - Both axes from tags
  - `test_doppler_partial_time_missing` - One axis missing
  - `test_doppler_time_guard` - time_span_ms=0 guard

- **M-mode (6 tests):**
  - `test_mmode_full_dicom` - Both axes from tags
  - `test_mmode_no_time` - No time axis
  - `test_mmode_no_depth` - No depth axis
  - `test_mmode_frame_time_fallback` - FrameTime fallback
  - `test_mmode_banner_values` - Banner shows actual values
  - `test_mmode_not_trusted_manual` - Manual calibration

- **Physics guard (3 tests):**
  - `test_sf1_rejects_bmode` - B-mode (SF=1) rejected
  - `test_sf2_accepts_mmode` - M-mode (SF=2) accepted
  - `test_sf3_accepts_spectral` - Spectral (SF=3) accepted

**Self-Review:**
- All tests verify actual behavior, not just mock behavior
- Tests follow existing codebase patterns
- Code is clean and maintainable
- No overbuilding or unnecessary complexity

**Concerns:**
- Task brief specified 16 tests but only 14 were provided in the spec
- All 14 tests from the spec are implemented and passing