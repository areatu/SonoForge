# Task 3: FrameTime Fallback for M-mode Time Axis

**Files:**
- Modify: `src/echo_personal_tool/domain/services/mmode_calibration.py:12-20`
- Test: `tests/unit/test_mmode_calibration.py`

**Interfaces:**
- Consumes: `frame_time_ms: float | None` parameter
- Produces: `MmodeCalibrationState` with `time_from_dicom_tags` set correctly

## Steps

### Step 1: Write failing tests for FrameTime fallback

Add to `tests/unit/test_mmode_calibration.py`:

```python
class TestMmodeStateFromPanelFrameTime:
    def test_frame_time_fallback_when_no_dicom_time(self):
        """Panel without PhysicalDeltaX + FrameTime → time from FrameTime."""
        panel = UltrasoundPanel(
            kind=PanelKind.M_MODE,
            bounds=DopplerSpectrogramRoi(x0=0, y0=0, width=200, height=60),
            physical_delta_y=0.05,
            physical_units_y=2,
        )
        state = mmode_state_from_panel(panel, frame_time_ms=500.0)
        assert state is not None
        assert state.horizontal_ms_per_pixel == 2.5  # 500ms / 200px
        assert state.time_from_dicom_tags is False
        assert state.depth_from_dicom_tags is True

    def test_dicom_time_takes_priority_over_frame_time(self):
        """Panel with PhysicalDeltaX + FrameTime → time from DICOM (not FrameTime)."""
        panel = UltrasoundPanel(
            kind=PanelKind.M_MODE,
            bounds=DopplerSpectrogramRoi(x0=0, y0=0, width=200, height=60),
            physical_delta_x=0.01,
            physical_delta_y=0.05,
            physical_units_x=3,
            physical_units_y=2,
        )
        state = mmode_state_from_panel(panel, frame_time_ms=500.0)
        assert state is not None
        assert state.horizontal_ms_per_pixel is not None
        assert state.time_from_dicom_tags is True

    def test_no_frame_time_no_dicom_time(self):
        """Panel without PhysicalDeltaX and no FrameTime → no time."""
        panel = UltrasoundPanel(
            kind=PanelKind.M_MODE,
            bounds=DopplerSpectrogramRoi(x0=0, y0=0, width=200, height=60),
            physical_delta_y=0.05,
            physical_units_y=2,
        )
        state = mmode_state_from_panel(panel, frame_time_ms=None)
        assert state is not None
        assert state.horizontal_ms_per_pixel is None
        assert state.time_from_dicom_tags is False

    def test_frame_time_zero_ignored(self):
        """FrameTime=0 → ignored, no time."""
        panel = UltrasoundPanel(
            kind=PanelKind.M_MODE,
            bounds=DopplerSpectrogramRoi(x0=0, y0=0, width=200, height=60),
            physical_delta_y=0.05,
            physical_units_y=2,
        )
        state = mmode_state_from_panel(panel, frame_time_ms=0.0)
        assert state is not None
        assert state.horizontal_ms_per_pixel is None

    def test_frame_time_negative_ignored(self):
        """FrameTime<0 → ignored, no time."""
        panel = UltrasoundPanel(
            kind=PanelKind.M_MODE,
            bounds=DopplerSpectrogramRoi(x0=0, y0=0, width=200, height=60),
            physical_delta_y=0.05,
            physical_units_y=2,
        )
        state = mmode_state_from_panel(panel, frame_time_ms=-100.0)
        assert state is not None
        assert state.horizontal_ms_per_pixel is None

    def test_frame_time_zero_width_ignored(self):
        """FrameTime with width=0 → ignored, no time."""
        panel = UltrasoundPanel(
            kind=PanelKind.M_MODE,
            bounds=DopplerSpectrogramRoi(x0=0, y0=0, width=0, height=60),
            physical_delta_y=0.05,
            physical_units_y=2,
        )
        state = mmode_state_from_panel(panel, frame_time_ms=500.0)
        assert state is not None
        assert state.horizontal_ms_per_pixel is None
```

### Step 2: Run tests to verify they fail

Run: `/home/areatu/ECHO2026/.venv/bin/python -m pytest tests/unit/test_mmode_calibration.py::TestMmodeStateFromPanelFrameTime -v`
Expected: FAIL with `TypeError: mmode_state_from_panel() got an unexpected keyword argument 'frame_time_ms'`

### Step 3: Implement FrameTime fallback

Modify `src/echo_personal_tool/domain/services/mmode_calibration.py`:

```python
"""Build M-mode calibration from ultrasound panels."""

from __future__ import annotations

from echo_personal_tool.domain.models.frame_panels import (
    MmodeCalibrationState,
    PanelKind,
    UltrasoundPanel,
)


def mmode_state_from_panel(
    panel: UltrasoundPanel,
    frame_time_ms: float | None = None,  # NEW
) -> MmodeCalibrationState | None:
    if panel.kind is not PanelKind.M_MODE:
        return None
    
    # Try DICOM tags first
    horizontal_ms = panel.horizontal_ms_per_pixel
    time_from_dicom = horizontal_ms is not None
    
    # FrameTime fallback: only if no DICOM time and FrameTime is valid
    if horizontal_ms is None and frame_time_ms is not None and frame_time_ms > 0.0 and panel.bounds.width > 0:
        horizontal_ms = frame_time_ms / panel.bounds.width
        time_from_dicom = False
    
    return MmodeCalibrationState(
        roi=panel.bounds,
        vertical_mm_per_pixel=panel.vertical_mm_per_pixel,
        horizontal_ms_per_pixel=horizontal_ms,
        from_dicom_tags=panel.horizontal_ms_per_pixel is not None and panel.vertical_mm_per_pixel is not None,
        depth_from_dicom_tags=panel.vertical_mm_per_pixel is not None,
        time_from_dicom_tags=time_from_dicom,
    )


def horizontal_ms_from_frame_time(
    frame_time_ms: float | None, roi_width_px: float
) -> float | None:
    """Fallback time scale from dataset-level FrameTime tag.

    For single-frame M-mode strips: entire width = sweep duration.
    """
    if frame_time_ms is None or frame_time_ms <= 0.0:
        return None
    if roi_width_px <= 0.0:
        return None
    return float(frame_time_ms) / roi_width_px
```

### Step 4: Run tests to verify they pass

Run: `/home/areatu/ECHO2026/.venv/bin/python -m pytest tests/unit/test_mmode_calibration.py -v`
Expected: All PASS

### Step 5: Commit

```bash
git add src/echo_personal_tool/domain/services/mmode_calibration.py tests/unit/test_mmode_calibration.py
git commit -m "feat(mmode): add FrameTime fallback for M-mode time axis

- mmode_state_from_panel accepts frame_time_ms parameter
- FrameTime fallback when no PhysicalDeltaX
- DICOM time takes priority over FrameTime
- Set time_from_dicom_tags correctly for each source"
```

## Report

Write your report to `/home/areatu/ECHO2026/docs/superpowers/plans/task-3-report.md` with:
- Status: DONE, DONE_WITH_CONCERNS, NEEDS_CONTEXT, or BLOCKED
- Commits made
- Test results
- Any concerns
