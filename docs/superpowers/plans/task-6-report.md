# Task 6 Report: Wire preferences → viewer in MainWindow

## What Was Implemented

Added a single line to `_apply_user_preferences()` in `main_window.py`:

```python
self._viewer.set_area_tool_mode(preferences.area_tool_mode)
```

This ensures the `area_tool_mode` preference (click/freehand) is applied to the viewer both on startup and when the user clicks "Apply" in the preferences dialog.

## Tests and Results

### TDD RED
- Tests `test_applies_freehand_mode` and `test_applies_click_mode` written first
- Both failed with: `AssertionError: expected call not found. Expected: set_area_tool_mode('click') Actual: not called.`

### TDD GREEN
- Added the one-line wiring after `set_magnetic_snap_enabled` call
- Both tests now pass

### Regression
- Full test file: 61/61 passed (including 2 new tests)
- Import check: `from echo_personal_tool.presentation.main_window import MainWindow` — OK

## Files Changed

| File | Change |
|------|--------|
| `src/echo_personal_tool/presentation/main_window.py` | Added `set_area_tool_mode` call in `_apply_user_preferences` |
| `tests/unit/test_presentation_main_window.py` | Added `TestApplyAreaToolMode` class (2 tests) |

## Self-Review

No concerns. The change is minimal and follows the exact pattern of existing `set_magnetic_snap_enabled` wiring.
