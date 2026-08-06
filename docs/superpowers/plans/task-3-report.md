# Task 3 Report: FrameTime Fallback for M-mode Time Axis

## Status: DONE

## Commits
- `0b2c91f` — feat(mmode): add FrameTime fallback for M-mode time axis

## What was implemented
- `mmode_state_from_panel` now accepts an optional `frame_time_ms: float | None` parameter
- When DICOM time (`PhysicalDeltaX`) is absent and `frame_time_ms > 0` with `width > 0`, time is derived from FrameTime
- DICOM time always takes priority over FrameTime
- `time_from_dicom_tags` flag correctly reflects the source of the time scale

## TDD Evidence

### RED
```
pytest tests/unit/test_mmode_calibration.py::TestMmodeStateFromPanelFrameTime -v
FAILED: TypeError: mmode_state_from_panel() got an unexpected keyword argument 'frame_time_ms'
(6/6 failed)
```

### GREEN
```
pytest tests/unit/test_mmode_calibration.py -v
33/33 passed
```

## Files changed
- `src/echo_personal_tool/domain/services/mmode_calibration.py` — added `frame_time_ms` parameter and fallback logic
- `tests/unit/test_mmode_calibration.py` — added `TestMmodeStateFromPanelFrameTime` class (6 tests)

## Test results
- 59/59 unit tests passing (mmode + doppler + physics), output pristine

## Self-review findings
- No concerns. Implementation is minimal, follows existing patterns, all edge cases (zero, negative, zero width) handled correctly.
