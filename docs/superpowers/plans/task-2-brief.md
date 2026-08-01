# Task 2: Physics Guard for horizontal_ms_per_pixel

**Files:**
- Modify: `src/echo_personal_tool/domain/services/ultrasound_region_physics.py:49-58`
- Test: `tests/unit/test_ultrasound_region_physics.py`

**Interfaces:**
- Consumes: `spatial_format` parameter (int | None)
- Produces: `horizontal_ms_per_pixel` returns None for SF=1 (B-mode)

## Steps

### Step 1: Write failing tests for guard

Add to `tests/unit/test_ultrasound_region_physics.py`:

```python
def test_horizontal_ms_per_pixel_rejects_bmode_sf1() -> None:
    """B-mode region (SF=1) with SEC units → None (guard)."""
    assert horizontal_ms_per_pixel(0.024, PHYSICAL_UNIT_SEC, spatial_format=1) is None


def test_horizontal_ms_per_pixel_accepts_mmode_sf2() -> None:
    """M-mode region (SF=2) with SEC units → valid value."""
    assert horizontal_ms_per_pixel(0.024, PHYSICAL_UNIT_SEC, spatial_format=2) == 24.0


def test_horizontal_ms_per_pixel_accepts_spectral_sf3() -> None:
    """Spectral region (SF=3) with SEC units → valid value."""
    assert horizontal_ms_per_pixel(0.024, PHYSICAL_UNIT_SEC, spatial_format=3) == 24.0


def test_horizontal_ms_per_pixel_no_spatial_format() -> None:
    """No spatial_format provided → no guard, returns value."""
    assert horizontal_ms_per_pixel(0.024, PHYSICAL_UNIT_SEC) == 24.0
```

### Step 2: Run tests to verify they fail

Run: `/home/areatu/ECHO2026/.venv/bin/python -m pytest tests/unit/test_ultrasound_region_physics.py::test_horizontal_ms_per_pixel_rejects_bmode_sf1 -v`
Expected: FAIL with `AssertionError: assert 24.0 is None`

### Step 3: Implement guard in horizontal_ms_per_pixel

Modify `src/echo_personal_tool/domain/services/ultrasound_region_physics.py`:

```python
def horizontal_ms_per_pixel(
    delta_x: float,
    units_x: int,
    spatial_format: int | None = None,  # NEW
) -> float | None:
    """M-mode / spectral sweep: milliseconds per pixel on the time axis."""
    # Reject B-mode regions (SF=1)
    if spatial_format is not None and spatial_format == 1:  # SPATIAL_2D
        return None
    
    if delta_x <= 0.0:
        return None
    if units_x == PHYSICAL_UNIT_SEC:
        return delta_x * 1000.0
    # Vendor quirk: time increment mis-tagged as Hz while value is seconds/pixel.
    if units_x == PHYSICAL_UNIT_HZ and delta_x < 1.0:
        return delta_x * 1000.0
    return None
```

### Step 4: Run tests to verify they pass

Run: `/home/areatu/ECHO2026/.venv/bin/python -m pytest tests/unit/test_ultrasound_region_physics.py -v`
Expected: All PASS

### Step 5: Commit

```bash
git add src/echo_personal_tool/domain/services/ultrasound_region_physics.py tests/unit/test_ultrasound_region_physics.py
git commit -m "feat(physics): add spatial_format guard to horizontal_ms_per_pixel

- Reject B-mode regions (SF=1) even with SEC units
- Accept M-mode (SF=2) and spectral (SF=3) regions
- Backward compatible: no spatial_format → no guard"
```

## Report

Write your report to `/home/areatu/ECHO2026/docs/superpowers/plans/task-2-report.md` with:
- Status: DONE, DONE_WITH_CONCERNS, NEEDS_CONTEXT, or BLOCKED
- Commits made
- Test results
- Any concerns
