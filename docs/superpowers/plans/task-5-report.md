# Task 5 Report: Wire area_tool_mode into ViewerWidget

## Status: DONE

## What Was Implemented

### State variables (Step 1)
- Added `_freehand_recording`, `_freehand_points`, and `_area_tool_mode` to `ViewerWidget.__init__` after `_active_arc_points`

### Getter/setter (Step 2)
- Added `set_area_tool_mode(mode)` and `area_tool_mode()` methods after `magnetic_snap_enabled()` in `viewer_widget.py`

### start_generic_area_contour branching (Step 3)
- Modified `start_generic_area_contour()` to check `_area_tool_mode == "freehand"` and set `_freehand_recording = True` / clear points / show freehand prompt

### _handle_contour_mouse_click freehand (Step 4)
- Added freehand early-return for single clicks (ignored) and double-click (finishes contour) before existing click-mode logic

### _distance and _update_freehand_preview (Step 5)
- Added `_distance(a, b)` static method for Euclidean distance
- Added `_update_freehand_preview()` to update the active contour plot item with freehand points

### _finish_freehand_contour (Step 6)
- New method: reduces points via `reduce_polygon_points()`, applies `snap_closed_polygon()` if snap enabled, creates `Contour` with AREA chamber, emits `contour_completed`

### _clear_active_contour_drawing cleanup (Step 7)
- Added `_freehand_recording = False` and `_freehand_points = []` cleanup in `_clear_active_contour_drawing()`

### _finish_closed_contour snap (Step 8)
- Modified `_finish_closed_contour()` to import and call `snap_closed_polygon(points, edge_map)` when `_magnetic_snap_enabled` is True

### Per-click snap in polygon stage (Step 9)
- Modified `handle_contour_click()` polygon branch to call `snap_magnetic_point()` and `outward_normal_at_index_closed()` when 5+ points exist and snap is enabled

### Freehand mouse tracking (Step 10)
- Added freehand recording block in `_on_scene_mouse_moved()` after drag session check: appends points with minimum 2px distance, calls `_update_freehand_preview()`

### Freehand finish-on-release (Step 11)
- Added freehand check at the top of `ContourViewBox.mouseReleaseEvent()` to finish contour on mouse release with 3+ points

### i18n keys (Step 12)
- Added `viewer.area_freehand_prompt` in both `ru.json` and `en.json`

## Files Changed

| File | Change |
|------|--------|
| `src/echo_personal_tool/presentation/viewer_widget.py` | All viewer logic changes |
| `src/echo_personal_tool/infrastructure/locales/ru.json` | Added `viewer.area_freehand_prompt` |
| `src/echo_personal_tool/infrastructure/locales/en.json` | Added `viewer.area_freehand_prompt` |
| `tests/unit/test_area_tool_mode_wiring.py` | New test file (19 tests) |

## Test Results

### TDD RED Phase
All 19 tests failed with `AttributeError` for missing features — correct RED behavior.

### TDD GREEN Phase
All 19 tests pass after implementation.

### Regression Check
All 459 existing tests in `test_contour.py`, `test_presentation_viewer_widget.py`, and `test_viewer_widget.py` continue to pass.

## Self-Review Findings

No concerns. All changes follow existing patterns:
- Local imports for `reduce_polygon_points`, `snap_closed_polygon`, `snap_magnetic_point`, `outward_normal_at_index_closed` match the pattern used elsewhere in the file
- i18n keys follow existing naming convention
- Test patterns match existing `test_contour.py` and `test_presentation_viewer_widget.py`
