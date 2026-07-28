# Task 7 Report: Remove is_open_arc guard from magnetic snap

**Status:** DONE

## What was implemented

Removed the `is_open_arc` guard from two methods in `viewer_widget.py` so that closed polygon contours (AREA, VOL) also receive magnetic edge snapping:

1. **`_apply_magnetic_snap_to_contour`**: Replaced early-return guard with if/else branch. Open arcs use the existing `apply_soft_magnetic_snap` + `_snap_open_arc_endpoints` path. Closed polygons use the new `snap_closed_polygon` from Task 4.

2. **`_auto_snap_new_contour`**: Removed the `if not contour.is_open_arc: return` guard. The method now delegates to `_apply_magnetic_snap_to_contour` for all contour types.

Also fixed two pre-existing ruff import sorting issues in the same file (unrelated to this task).

## Test results (TDD)

**RED:** Created `test_apply_magnetic_snap_to_contour_closed_polygon` — asserts `snap_closed_polygon` is called for closed polygon contours. Before the fix, it failed with `AssertionError: Expected 'snap_closed_polygon' to have been called once. Called 0 times.`

**GREEN:** After the fix, the test passes.

```
tests/unit/test_viewer_widget.py::TestMagneticSnap::test_apply_magnetic_snap_to_contour PASSED
tests/unit/test_viewer_widget.py::TestMagneticSnap::test_apply_magnetic_snap_to_contour_closed_polygon PASSED
```

Existing test suites all pass:
- `tests/unit/test_contour_edge_snap.py` — 37 passed
- `tests/unit/test_planimeter.py` — 19 passed

## Files changed

- `src/echo_personal_tool/presentation/viewer_widget.py` — replaced both methods, fixed lint
- `tests/unit/test_viewer_widget.py` — added one new test

## Commit

- `8646c1f` feat: enable magnetic snap for closed polygon contours (AREA/VOL)

## Self-review findings

No concerns. The change is minimal and surgical — the only behavioral change is that closed polygon contours now get edge snapping via `snap_closed_polygon` instead of being silently skipped. Open arc behavior is unchanged.
