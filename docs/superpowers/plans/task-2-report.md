# Task 2: Physics Guard for horizontal_ms_per_pixel

## Status: DONE

## What I implemented
Added a `spatial_format` parameter to `horizontal_ms_per_pixel()` that rejects B-mode regions (SF=1) even when they have SEC units, returning `None` instead of a computed value.

## Files changed
- `src/echo_personal_tool/domain/services/ultrasound_region_physics.py:49-66` — added `spatial_format: int | None = None` parameter and guard logic
- `tests/unit/test_ultrasound_region_physics.py` — added 4 new tests

## TDD Evidence

### RED
```bash
$ python -m pytest tests/unit/test_ultrasound_region_physics.py::test_horizontal_ms_per_pixel_rejects_bmode_sf1 -v
FAILED: TypeError: horizontal_ms_per_pixel() got an unexpected keyword argument 'spatial_format'
```
Expected failure — function didn't have the parameter yet.

### GREEN
```bash
$ python -m pytest tests/unit/test_ultrasound_region_physics.py -v
12 passed
```

All tests pass, including the 4 new guard tests.

## Test results
- 12/12 passing in `test_ultrasound_region_physics.py`
- 58/59 passing in the broader related test set (1 pre-existing failure in `test_doppler_axis.py::test_poc_default` unrelated to this change)

## Self-review
- **Completeness:** All 4 tests from the brief implemented and passing.
- **Quality:** Guard logic is minimal and clear. Uses existing `SPATIAL_2D` constant reference in comment.
- **Discipline:** No overbuilding. Parameter defaults to `None` for full backward compatibility.
- **Testing:** Tests cover B-mode rejection, M-mode acceptance, spectral acceptance, and no-spatial-format backward compat.

## Commits
- `9a65c11` feat(physics): add spatial_format guard to horizontal_ms_per_pixel
