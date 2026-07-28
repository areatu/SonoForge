# Task 4 Report: Enable edge snap for closed polygons

**Status:** DONE

## What I implemented

1. **`outward_normal_at_index_closed()`** — A variant of `outward_normal_at_index` that uses modular indexing (`% n`) for neighbors. This avoids the `IndexError` that occurs when calling `outward_normal_at_index` on the last point of a closed polygon (the original function accesses `points[index + 1]` without bounds checking).

2. **`snap_closed_polygon()`** — Iterates over all vertices of a closed polygon, computing outward normals via `outward_normal_at_index_closed`, then snaps each point to the nearest edge using `snap_magnetic_point`. Returns a new list of snapped coordinates.

## Test results

**TDD RED:** Tests failed with `ImportError: cannot import name 'outward_normal_at_index_closed'` — correct.

**TDD GREEN:** All 35 tests pass (28 existing + 7 new).

New test classes:
- `TestOutwardNormalAtIndexClosed` — 2 tests (wraps at end, wraps at start)
- `TestSnapClosedPolygon` — 5 tests (same length, returns tuples, empty points, too few points, with config)

## Files changed

- `src/echo_personal_tool/domain/services/contour_edge_snap.py` — Added `outward_normal_at_index_closed` and `snap_closed_polygon` functions
- `tests/unit/test_contour_edge_snap.py` — Added imports and 7 new tests across 2 new test classes

## Self-review

No concerns. The implementation exactly matches the plan spec:
- Modular indexing `% n` prevents IndexError on first/last points
- Centroid-based outward direction logic is identical to the original function
- `snap_closed_polygon` uses `snap_magnetic_point` with the config from the plan
- Edge case handling (empty list, < 3 points) returns original points
