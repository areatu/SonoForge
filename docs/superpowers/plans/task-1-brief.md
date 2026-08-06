# Task 1: M-mode Model Enhancement

**Files:**
- Modify: `src/echo_personal_tool/domain/models/frame_panels.py:88-109`
- Test: `tests/unit/test_mmode_calibration.py`

**Interfaces:**
- Consumes: `DopplerSpectrogramRoi` (existing)
- Produces: `MmodeCalibrationState` with new methods: `is_partial()`, `has_depth_scale()`, `has_time_scale()`, `is_dicom_trusted()`, `has_depth_from_dicom()`, `has_time_from_dicom()`

## Steps

### Step 1: Write failing tests for new methods

Add to `tests/unit/test_mmode_calibration.py`:

```python
class TestMmodeCalibrationStateEnhanced:
    def test_is_partial_depth_only(self):
        """State with depth but no time → is_partial=True."""
        state = MmodeCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50),
            vertical_mm_per_pixel=0.5,
            horizontal_ms_per_pixel=None,
        )
        assert state.is_partial() is True
        assert state.has_depth_scale() is True
        assert state.has_time_scale() is False

    def test_is_partial_time_only(self):
        """State with time but no depth → is_partial=True."""
        state = MmodeCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50),
            vertical_mm_per_pixel=None,
            horizontal_ms_per_pixel=10.0,
        )
        assert state.is_partial() is True
        assert state.has_depth_scale() is False
        assert state.has_time_scale() is True

    def test_is_complete_both_axes(self):
        """State with both axes → is_complete=True, is_partial=False."""
        state = MmodeCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50),
            vertical_mm_per_pixel=0.5,
            horizontal_ms_per_pixel=10.0,
        )
        assert state.is_complete() is True
        assert state.is_partial() is False

    def test_has_depth_from_dicom_with_flag(self):
        """depth_from_dicom_tags=True + valid depth → has_depth_from_dicom=True."""
        state = MmodeCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50),
            vertical_mm_per_pixel=0.5,
            depth_from_dicom_tags=True,
        )
        assert state.has_depth_from_dicom() is True

    def test_has_depth_from_dicom_without_depth(self):
        """depth_from_dicom_tags=True but no depth → has_depth_from_dicom=False."""
        state = MmodeCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50),
            vertical_mm_per_pixel=None,
            depth_from_dicom_tags=True,
        )
        assert state.has_depth_from_dicom() is False

    def test_has_time_from_dicom_with_flag(self):
        """time_from_dicom_tags=True + valid time → has_time_from_dicom=True."""
        state = MmodeCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50),
            horizontal_ms_per_pixel=10.0,
            time_from_dicom_tags=True,
        )
        assert state.has_time_from_dicom() is True

    def test_has_time_from_dicom_without_time(self):
        """time_from_dicom_tags=True but no time → has_time_from_dicom=False."""
        state = MmodeCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50),
            horizontal_ms_per_pixel=None,
            time_from_dicom_tags=True,
        )
        assert state.has_time_from_dicom() is False

    def test_is_dicom_trusted_full(self):
        """from_dicom_tags=True + both axes → is_dicom_trusted=True."""
        state = MmodeCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50),
            vertical_mm_per_pixel=0.5,
            horizontal_ms_per_pixel=10.0,
            from_dicom_tags=True,
        )
        assert state.is_dicom_trusted() is True

    def test_is_dicom_trusted_partial(self):
        """from_dicom_tags=True but missing one axis → is_dicom_trusted=False."""
        state = MmodeCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50),
            vertical_mm_per_pixel=0.5,
            horizontal_ms_per_pixel=None,
            from_dicom_tags=True,
        )
        assert state.is_dicom_trusted() is False

    def test_is_dicom_trusted_manual(self):
        """from_dicom_tags=False → is_dicom_trusted=False."""
        state = MmodeCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50),
            vertical_mm_per_pixel=0.5,
            horizontal_ms_per_pixel=10.0,
            from_dicom_tags=False,
        )
        assert state.is_dicom_trusted() is False
```

### Step 2: Run tests to verify they fail

Run: `/home/areatu/ECHO2026/.venv/bin/python -m pytest tests/unit/test_mmode_calibration.py::TestMmodeCalibrationStateEnhanced -v`
Expected: FAIL with `AttributeError: 'MmodeCalibrationState' object has no attribute 'is_partial'`

### Step 3: Implement new methods in MmodeCalibrationState

Modify `src/echo_personal_tool/domain/models/frame_panels.py`:

```python
@dataclass(frozen=True)
class MmodeCalibrationState:
    """Per-instance M-mode strip calibration (vertical depth scale)."""

    roi: DopplerSpectrogramRoi
    vertical_mm_per_pixel: float | None = None
    horizontal_ms_per_pixel: float | None = None
    from_dicom_tags: bool = False
    depth_from_dicom_tags: bool = False  # NEW
    time_from_dicom_tags: bool = False   # NEW

    def is_complete(self) -> bool:
        return self.has_depth_scale() and self.has_time_scale()

    def is_partial(self) -> bool:
        return self.has_depth_scale() != self.has_time_scale()

    def has_depth_scale(self) -> bool:
        return self.vertical_mm_per_pixel is not None and self.vertical_mm_per_pixel > 0.0

    def has_time_scale(self) -> bool:
        return self.horizontal_ms_per_pixel is not None and self.horizontal_ms_per_pixel > 0.0

    def has_depth_from_dicom(self) -> bool:
        return self.depth_from_dicom_tags and self.has_depth_scale()

    def has_time_from_dicom(self) -> bool:
        return self.time_from_dicom_tags and self.has_time_scale()

    def is_dicom_trusted(self) -> bool:
        return self.from_dicom_tags and self.is_complete()
```

### Step 4: Run tests to verify they pass

Run: `/home/areatu/ECHO2026/.venv/bin/python -m pytest tests/unit/test_mmode_calibration.py -v`
Expected: All PASS

### Step 5: Update existing tests that use old API

The existing test `test_from_dicom_flags` uses `from_dicom_tags=True` and expects both `has_depth_from_dicom()` and `has_time_from_dicom()` to return True. This test needs to be updated to use the new `depth_from_dicom_tags` and `time_from_dicom_tags` flags.

Update `tests/unit/test_mmode_calibration.py::TestMmodeCalibrationStatePartial::test_from_dicom_flags`:

```python
def test_from_dicom_flags(self):
    """depth_from_dicom_tags and time_from_dicom_tags propagate to helper methods."""
    state = MmodeCalibrationState(
        roi=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50),
        vertical_mm_per_pixel=0.5,
        horizontal_ms_per_pixel=10.0,
        from_dicom_tags=True,
        depth_from_dicom_tags=True,
        time_from_dicom_tags=True,
    )
    assert state.has_depth_from_dicom() is True
    assert state.has_time_from_dicom() is True
```

### Step 6: Run all mmode calibration tests

Run: `/home/areatu/ECHO2026/.venv/bin/python -m pytest tests/unit/test_mmode_calibration.py -v`
Expected: All PASS

### Step 7: Commit

```bash
git add src/echo_personal_tool/domain/models/frame_panels.py tests/unit/test_mmode_calibration.py
git commit -m "feat(mmode): enhance MmodeCalibrationState with parallel API to Doppler

- Add is_partial(), has_depth_scale(), has_time_scale()
- Add has_depth_from_dicom(), has_time_from_dicom()
- Add is_dicom_trusted()
- Split from_dicom_tags into depth_from_dicom_tags + time_from_dicom_tags"
```

## Report

Write your report to `/home/areatu/ECHO2026/docs/superpowers/plans/task-1-report.md` with:
- Status: DONE, DONE_WITH_CONCERNS, NEEDS_CONTEXT, or BLOCKED
- Commits made
- Test results
- Any concerns
