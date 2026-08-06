# Carotid Doppler Tag Auto-Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make spectral Doppler auto-calibration correct on Samsung RS85 carotid files by reading baseline, time origin, and the signed velocity scale from DICOM ultrasound-region tags.

**Architecture:** `DopplerCalibrationState`/`DopplerAxisMapping` gain a signed per-pixel velocity scale (`velocity_per_pixel_cm_s = PhysicalDeltaY`). The parser converts `ReferencePixelY0` from region-relative to absolute baseline (`MinY0 + RefY0`), reads `ReferencePixelX0`/`ReferencePixelPhysicalValueX` into `time_origin_ms`, and sets the signed scale. The axis mapping uses the per-pixel scale directly (`v = (y - baseline) * per_pixel`), giving exact DICOM physics and correct handling of inverted spectra and off-center baselines.

**Tech Stack:** Python 3.11, pydicom, NumPy, PySide6/PyQtGraph, pytest, pytest-qt.

## Global Constraints

- No git commits without explicit user approval (project AGENTS.md). Every "Commit" step below means: **ask the user first**, then run.
- `DopplerCalibrationState` and `DopplerAxisMapping` are frozen dataclasses; all new fields must have defaults so existing call sites keep working.
- Velocity units whitelist stays `{6, 7}`; do not change `ultrasound_region_physics.py` unless a test forces it.
- Run tests with `./scripts/run_tests.sh <paths>` (sets `QT_QPA_PLATFORM=offscreen`).
- Do not fix the pre-existing failure `test_doppler_axis.py::TestDopplerAxisMappingDefaults::test_poc_default` (unrelated: default `time_span_ms=0.0` vs asserted 1000.0). Leave it untouched.
- Spec: `docs/superpowers/specs/2026-08-02-carotid-doppler-tags-design.md`.

---

### Task 1: Model — add `velocity_per_pixel_cm_s` field + update scale checks

**Files:**
- Modify: `src/echo_personal_tool/domain/models/doppler_roi.py`
- Test: `tests/unit/test_doppler_roi.py`

**Interfaces:**
- Produces: `DopplerCalibrationState.velocity_per_pixel_cm_s: float | None = None`; `has_velocity_scale()` and `has_velocity_scale_from_dicom()` return True when this field is set (or `velocity_span_cm_s > 0`). Later tasks rely on this field.

- [ ] **Step 1: Add failing tests**

Append to the `TestDopplerCalibrationState` class in `tests/unit/test_doppler_roi.py`:

```python
    def test_has_velocity_scale_with_per_pixel(self) -> None:
        roi = self._make_roi()
        state = DopplerCalibrationState(
            roi=roi,
            baseline_y_px=50.0,
            velocity_span_cm_s=0.0,
            velocity_per_pixel_cm_s=-0.5,
        )
        assert state.has_velocity_scale() is True

    def test_no_velocity_scale_without_per_pixel(self) -> None:
        roi = self._make_roi()
        state = DopplerCalibrationState(
            roi=roi,
            baseline_y_px=50.0,
            velocity_span_cm_s=0.0,
            velocity_per_pixel_cm_s=None,
        )
        assert state.has_velocity_scale() is False

    def test_has_velocity_scale_from_dicom_with_per_pixel(self) -> None:
        roi = self._make_roi()
        state = DopplerCalibrationState(
            roi=roi,
            baseline_y_px=50.0,
            velocity_from_dicom_tags=True,
            velocity_span_cm_s=0.0,
            velocity_per_pixel_cm_s=0.36,
        )
        assert state.has_velocity_scale_from_dicom() is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./scripts/run_tests.sh tests/unit/test_doppler_roi.py -k velocity_scale`
Expected: FAIL (3 new tests error with `TypeError: unexpected keyword argument 'velocity_per_pixel_cm_s'`).

- [ ] **Step 3: Implement**

In `src/echo_personal_tool/domain/models/doppler_roi.py`, add the field at the end of `DopplerCalibrationState`:

```python
    velocity_per_pixel_cm_s: float | None = None
```

Update the two methods:

```python
    def has_velocity_scale(self) -> bool:
        return (
            self.roi.width > 0.0
            and self.roi.height > 0.0
            and (self.velocity_span_cm_s > 0.0 or self.velocity_per_pixel_cm_s is not None)
        )

    def has_velocity_scale_from_dicom(self) -> bool:
        return (
            self.velocity_from_dicom_tags
            and self.roi.height > 0.0
            and (self.velocity_span_cm_s > 0.0 or self.velocity_per_pixel_cm_s is not None)
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./scripts/run_tests.sh tests/unit/test_doppler_roi.py`
Expected: PASS (all existing + 3 new tests).

- [ ] **Step 5: Commit (ask user first)**

```bash
git add src/echo_personal_tool/domain/models/doppler_roi.py tests/unit/test_doppler_roi.py
git commit -m "feat(doppler): add signed per-pixel velocity scale to calibration state"
```

---

### Task 2: Axis mapping — per-pixel velocity conversions

**Files:**
- Modify: `src/echo_personal_tool/domain/models/doppler_axis.py`
- Test: `tests/unit/test_doppler_axis.py`

**Interfaces:**
- Consumes: Task 1 field name `velocity_per_pixel_cm_s`.
- Produces: `DopplerAxisMapping.velocity_per_pixel_cm_s: float | None = None`; `velocity_cm_s_from_y(y)` returns `(y - baseline_y_px) * velocity_per_pixel_cm_s` when set; `y_from_velocity_cm_s(v)` returns `baseline_y_px + v / velocity_per_pixel_cm_s` when set.

- [ ] **Step 1: Add failing tests**

Append a new class to `tests/unit/test_doppler_axis.py`:

```python
class TestVelocityPerPixelScale:
    def test_velocity_cm_s_from_y_uses_per_pixel(self) -> None:
        m = DopplerAxisMapping(baseline_y_px=100.0, velocity_per_pixel_cm_s=-0.5)
        # (50 - 100) * -0.5 = +25 → above baseline is positive (inverted spectrum)
        assert m.velocity_cm_s_from_y(50.0) == pytest.approx(25.0)

    def test_velocity_cm_s_from_y_positive_delta(self) -> None:
        m = DopplerAxisMapping(baseline_y_px=100.0, velocity_per_pixel_cm_s=0.36)
        # (50 - 100) * 0.36 = -18 → above baseline is negative (positive down)
        assert m.velocity_cm_s_from_y(50.0) == pytest.approx(-18.0)

    def test_velocity_at_baseline_is_zero(self) -> None:
        m = DopplerAxisMapping(baseline_y_px=100.0, velocity_per_pixel_cm_s=-0.5)
        assert m.velocity_cm_s_from_y(100.0) == pytest.approx(0.0)

    def test_y_from_velocity_uses_per_pixel(self) -> None:
        m = DopplerAxisMapping(baseline_y_px=100.0, velocity_per_pixel_cm_s=-0.5)
        assert m.y_from_velocity_cm_s(25.0) == pytest.approx(50.0)

    def test_roundtrip_per_pixel(self) -> None:
        m = DopplerAxisMapping(baseline_y_px=100.0, velocity_per_pixel_cm_s=0.36)
        for v in (-50.0, -10.0, 0.0, 30.0, 80.0):
            y = m.y_from_velocity_cm_s(v)
            assert m.velocity_cm_s_from_y(y) == pytest.approx(v)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./scripts/run_tests.sh tests/unit/test_doppler_axis.py -k TestVelocityPerPixelScale`
Expected: FAIL (`TypeError: unexpected keyword argument 'velocity_per_pixel_cm_s'`).

- [ ] **Step 3: Implement**

In `src/echo_personal_tool/domain/models/doppler_axis.py`, add the field after `baseline_y_px`:

```python
    velocity_per_pixel_cm_s: float | None = None
```

Replace `velocity_cm_s_from_y` with:

```python
    def velocity_cm_s_from_y(self, y: float) -> float:
        if self.plot_height <= 0.0:
            return 0.0
        if self.velocity_per_pixel_cm_s is not None and self.baseline_y_px is not None:
            return (y - self.baseline_y_px) * self.velocity_per_pixel_cm_s
        if self.baseline_y_px is not None and self.velocity_span_cm_s > 0.0:
            pixels_per_cm_s = self.plot_height / self.velocity_span_cm_s
            return -(y - self.baseline_y_px) / pixels_per_cm_s
        # Fallback: zero at ROI center
        local_y = y - self.plot_origin_y
        span = self.velocity_max_cm_s - self.velocity_min_cm_s
        return self.velocity_max_cm_s - (local_y / self.plot_height) * span
```

Replace `y_from_velocity_cm_s` with:

```python
    def y_from_velocity_cm_s(self, velocity_cm_s: float) -> float:
        if self.plot_height <= 0.0:
            return self.plot_origin_y
        if self.velocity_per_pixel_cm_s is not None and self.baseline_y_px is not None:
            return self.baseline_y_px + velocity_cm_s / self.velocity_per_pixel_cm_s
        if self.baseline_y_px is not None and self.velocity_span_cm_s > 0.0:
            pixels_per_cm_s = self.plot_height / self.velocity_span_cm_s
            return self.baseline_y_px - velocity_cm_s * pixels_per_cm_s
        # Fallback: zero at ROI center
        span = self.velocity_max_cm_s - self.velocity_min_cm_s
        if span <= 0.0:
            return self.plot_origin_y + self.plot_height * 0.5
        fraction = (self.velocity_max_cm_s - velocity_cm_s) / span
        return self.plot_origin_y + fraction * self.plot_height
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./scripts/run_tests.sh tests/unit/test_doppler_axis.py`
Expected: PASS (existing tests + new `TestVelocityPerPixelScale`; the pre-existing `test_poc_default` failure remains and is out of scope).

- [ ] **Step 5: Commit (ask user first)**

```bash
git add src/echo_personal_tool/domain/models/doppler_axis.py tests/unit/test_doppler_axis.py
git commit -m "feat(doppler): use signed per-pixel velocity scale in axis mapping"
```

---

### Task 3: `build_axis_mapping` — asymmetric edge velocities + constructor param

**Files:**
- Modify: `src/echo_personal_tool/domain/services/doppler_calibration.py`
- Test: `tests/unit/test_doppler_calibration.py`

**Interfaces:**
- Consumes: `DopplerCalibrationState.velocity_per_pixel_cm_s` (Task 1), `DopplerAxisMapping.velocity_per_pixel_cm_s` (Task 2).
- Produces: `build_axis_mapping(state)` computes `velocity_min/max_cm_s` from ROI edge velocities when per-pixel is set; `calibration_from_roi_and_baseline(..., velocity_per_pixel_cm_s=None)` accepts the new kwarg. Task 4 (parser) passes the signed delta into the constructor.

- [ ] **Step 1: Add `import pytest`**

`tests/unit/test_doppler_calibration.py` currently has no `pytest` import. Add at the top:

```python
import pytest
```

- [ ] **Step 2: Add failing tests**

Append to `tests/unit/test_doppler_calibration.py`:

```python
class TestBuildAxisMappingPerPixel:
    def test_edge_velocities_inverted(self) -> None:
        roi = DopplerSpectrogramRoi(x0=4.0, y0=554.0, width=1139.0, height=319.0)
        state = DopplerCalibrationState(
            roi=roi,
            baseline_y_px=793.0,
            velocity_span_cm_s=161.71,
            velocity_per_pixel_cm_s=-0.5069,
        )
        mapping = build_axis_mapping(state)
        # v_top = (554-793)*-0.5069 = +121.15 ; v_bot = (873-793)*-0.5069 = -40.55
        assert mapping.velocity_max_cm_s == pytest.approx(121.15, rel=1e-3)
        assert mapping.velocity_min_cm_s == pytest.approx(-40.55, rel=1e-3)
        assert mapping.velocity_per_pixel_cm_s == -0.5069

    def test_edge_velocities_positive_delta(self) -> None:
        roi = DopplerSpectrogramRoi(x0=4.0, y0=554.0, width=1139.0, height=319.0)
        state = DopplerCalibrationState(
            roi=roi,
            baseline_y_px=793.0,
            velocity_span_cm_s=115.5,
            velocity_per_pixel_cm_s=0.3621,
        )
        mapping = build_axis_mapping(state)
        # v_top = (554-793)*0.3621 = -86.54 ; v_bot = (873-793)*0.3621 = +28.97
        assert mapping.velocity_max_cm_s == pytest.approx(28.97, rel=1e-3)
        assert mapping.velocity_min_cm_s == pytest.approx(-86.54, rel=1e-3)

    def test_without_per_pixel_stays_symmetric(self) -> None:
        state = _make_state()
        mapping = build_axis_mapping(state)
        assert mapping.velocity_min_cm_s == -100.0
        assert mapping.velocity_max_cm_s == 100.0
        assert mapping.velocity_per_pixel_cm_s is None


class TestCalibrationFromRoiAndBaselinePerPixel:
    def test_accepts_velocity_per_pixel_kwarg(self) -> None:
        roi = _make_roi()
        result = calibration_from_roi_and_baseline(
            roi,
            40.0,
            velocity_per_pixel_cm_s=0.36,
        )
        assert result.velocity_per_pixel_cm_s == pytest.approx(0.36)

    def test_default_per_pixel_none(self) -> None:
        roi = _make_roi()
        result = calibration_from_roi_and_baseline(roi, 40.0)
        assert result.velocity_per_pixel_cm_s is None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `./scripts/run_tests.sh tests/unit/test_doppler_calibration.py -k PerPixel`
Expected: FAIL (`TypeError`).

- [ ] **Step 4: Implement**

In `src/echo_personal_tool/domain/services/doppler_calibration.py`, replace `build_axis_mapping`:

```python
def build_axis_mapping(state: DopplerCalibrationState) -> DopplerAxisMapping:
    """Map plot pixels inside ROI to time (ms) and signed velocity (cm/s)."""
    roi = state.roi
    half = state.velocity_span_cm_s / 2.0
    velocity_min = -half
    velocity_max = half
    if state.velocity_per_pixel_cm_s is not None:
        v_top = (roi.y0 - state.baseline_y_px) * state.velocity_per_pixel_cm_s
        v_bot = (roi.y1 - state.baseline_y_px) * state.velocity_per_pixel_cm_s
        velocity_min = min(v_top, v_bot)
        velocity_max = max(v_top, v_bot)
    return DopplerAxisMapping(
        roi=roi,
        baseline_y_px=state.baseline_y_px,
        time_origin_ms=state.time_origin_ms,
        time_span_ms=state.time_span_ms,
        velocity_span_cm_s=state.velocity_span_cm_s,
        velocity_min_cm_s=velocity_min,
        velocity_max_cm_s=velocity_max,
        velocity_per_pixel_cm_s=state.velocity_per_pixel_cm_s,
        plot_width=roi.width,
        plot_height=roi.height,
        plot_origin_x=roi.x0,
        plot_origin_y=roi.y0,
    )
```

Replace `calibration_from_roi_and_baseline` with:

```python
def calibration_from_roi_and_baseline(
    roi: DopplerSpectrogramRoi,
    baseline_y_px: float,
    *,
    velocity_span_cm_s: float | None = None,
    time_span_ms: float = 0.0,
    time_origin_ms: float = 0.0,
    kind: DopplerKind = DopplerKind.SPECTRAL,
    velocity_per_pixel_cm_s: float | None = None,
) -> DopplerCalibrationState:
    span = velocity_span_cm_s if velocity_span_cm_s is not None else kind.default_velocity_span_cm_s
    return DopplerCalibrationState(
        roi=roi,
        baseline_y_px=baseline_y_px,
        time_origin_ms=time_origin_ms,
        time_span_ms=time_span_ms,
        velocity_span_cm_s=span,
        kind=kind,
        velocity_per_pixel_cm_s=velocity_per_pixel_cm_s,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./scripts/run_tests.sh tests/unit/test_doppler_calibration.py`
Expected: PASS.

- [ ] **Step 6: Commit (ask user first)**

```bash
git add src/echo_personal_tool/domain/services/doppler_calibration.py tests/unit/test_doppler_calibration.py
git commit -m "feat(doppler): asymmetric edge velocities in axis mapping from per-pixel scale"
```

---

### Task 4: Parser — absolute baseline, signed deltaY, time origin, consistency check

**Files:**
- Modify: `src/echo_personal_tool/infrastructure/dicom_doppler_calibration.py`
- Test: `tests/unit/test_dicom_doppler_calibration.py`

**Interfaces:**
- Consumes: `calibration_from_roi_and_baseline(..., velocity_per_pixel_cm_s=...)` (Task 3).
- Produces: parser now sets `baseline_y_px = MinY0 + ReferencePixelY0`, `velocity_per_pixel_cm_s = signed PhysicalDeltaY`, `time_origin_ms` from reference tags, and logs a warning when velocity full-scale is outside 10–400 cm/s.

- [ ] **Step 1: Add imports to test file**

Add at the top of `tests/unit/test_dicom_doppler_calibration.py`:

```python
import pytest
```

Add to the existing import block:

```python
from echo_personal_tool.domain.services.doppler_calibration import build_axis_mapping
```

- [ ] **Step 2: Update existing baseline test + add failing tests**

Replace `test_samsung_baseline_from_reference_pixel_y0` with:

```python
def test_samsung_baseline_from_reference_pixel_y0() -> None:
    """Samsung ReferencePixelY0 is region-relative → baseline = MinY0 + RefY0."""
    ds = Dataset()
    ds.SequenceOfUltrasoundRegions = [
        _samsung_like_region(dtype=3, ref_pixel_y0=180.0),
    ]
    state = try_parse_from_dataset(ds)
    assert state is not None
    assert state.baseline_y_px == 50.0 + 180.0
```

Append new tests:

```python
def test_negative_delta_y_inverted_spectrum() -> None:
    """Negative PhysicalDeltaY → signed per-pixel scale."""
    ds = Dataset()
    ds.SequenceOfUltrasoundRegions = [
        _doppler_region(dtype=3, delta_y=-0.507, units_y=7),
    ]
    state = try_parse_from_dataset(ds)
    assert state is not None
    assert state.velocity_per_pixel_cm_s == pytest.approx(-0.507)
    assert state.velocity_span_cm_s == pytest.approx(400.0 * 0.507)


def test_velocity_axis_mapping_physics() -> None:
    """velocity_cm_s_from_y equals (y - baseline) * per_pixel."""
    ds = Dataset()
    ds.SequenceOfUltrasoundRegions = [
        _doppler_region(dtype=3, delta_y=-0.5, units_y=7),
    ]
    state = try_parse_from_dataset(ds)
    assert state is not None
    assert state.baseline_y_px == pytest.approx(250.0)  # MinY0=50 + center 200
    mapping = build_axis_mapping(state)
    assert mapping.velocity_cm_s_from_y(50.0) == pytest.approx((50.0 - 250.0) * -0.5)
    assert mapping.velocity_cm_s_from_y(250.0) == pytest.approx(0.0)


def test_time_origin_from_reference_pixel_x0() -> None:
    """time_origin_ms derived from ReferencePixelX0 and ReferencePixelPhysicalValueX."""
    region = _doppler_region(dtype=3, delta_x=0.02, units_x=3, delta_y=0.5, units_y=6)
    region.ReferencePixelX0 = 100
    region.ReferencePixelPhysicalValueX = 1.0  # 1 second
    ds = Dataset()
    ds.SequenceOfUltrasoundRegions = [region]
    state = try_parse_from_dataset(ds)
    assert state is not None
    # time_span = width(1000) * 0.02 s/px * 1000 = 20000 ms → ms_per_px = 20
    # time_origin_ms = RefValueX*1000 - RefX0*ms_per_px = 1000 - 100*20 = -1000
    assert state.time_origin_ms == pytest.approx(-1000.0)


def test_baseline_relative_to_region_origin() -> None:
    """Baseline absolute = RegionLocationMinY0 + ReferencePixelY0."""
    ds = Dataset()
    ds.SequenceOfUltrasoundRegions = [
        _samsung_like_region(dtype=3, ref_pixel_y0=239.0),
    ]
    state = try_parse_from_dataset(ds)
    assert state is not None
    assert state.baseline_y_px == 50.0 + 239.0


def test_roundtrip_inverse_consistency() -> None:
    """y_from_velocity(velocity_from_y(y)) == y for per-pixel mapping."""
    ds = Dataset()
    ds.SequenceOfUltrasoundRegions = [
        _doppler_region(dtype=3, delta_y=-0.5, units_y=7),
    ]
    state = try_parse_from_dataset(ds)
    assert state is not None
    mapping = build_axis_mapping(state)
    for y in (50.0, 120.0, 250.0, 350.0, 450.0):
        v = mapping.velocity_cm_s_from_y(y)
        assert mapping.y_from_velocity_cm_s(v) == pytest.approx(y)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `./scripts/run_tests.sh tests/unit/test_dicom_doppler_calibration.py -k "baseline or delta_y or origin or roundtrip or physics"`
Expected: FAIL (baseline assertions get 180/239 instead of 230/289; `velocity_per_pixel_cm_s` missing).

- [ ] **Step 4: Implement**

In `src/echo_personal_tool/infrastructure/dicom_doppler_calibration.py`:

Replace `_extract_samsung_baseline` with:

```python
def _extract_samsung_baseline(region: Dataset) -> float | None:
    """Absolute baseline: ReferencePixelY0 is region-relative → add RegionLocationMinY0."""
    ref_y = region.get("ReferencePixelY0")
    if ref_y is None:
        return None
    try:
        min_y = region.get("RegionLocationMinY0", 0) or 0
        return float(min_y) + float(ref_y)
    except (TypeError, ValueError):
        return None
```

In `try_parse_from_dataset`, after the `time_span_ms` block and the `velocity_span` block, compute the signed per-pixel scale and time origin. Add immediately after the `velocity_span` computation:

```python
        raw_delta_y = region.get("PhysicalDeltaY")
        velocity_per_pixel = None
        if velocity_span is not None and raw_delta_y is not None:
            try:
                velocity_per_pixel = float(raw_delta_y)
            except (TypeError, ValueError):
                velocity_per_pixel = None

        time_origin_ms = 0.0
        ref_x0 = region.get("ReferencePixelX0")
        ref_value_x = region.get("ReferencePixelPhysicalValueX")
        if time_span_ms is not None and roi.width > 0.0 and (ref_x0 is not None or ref_value_x is not None):
            ms_per_px = time_span_ms / roi.width
            time_origin_ms = (float(ref_value_x or 0) * 1000.0) - (float(ref_x0 or 0) * ms_per_px)
```

After the baseline is determined (the block ending with the `detect_baseline_y` / `_detect_baseline_fallback` handling), add the consistency check:

```python
        if velocity_per_pixel is not None:
            v_top = (roi.y0 - baseline_y) * velocity_per_pixel
            v_bot = (roi.y1 - baseline_y) * velocity_per_pixel
            full_scale = abs(v_top - v_bot)
            if full_scale < 10.0 or full_scale > 400.0:
                logger.warning(
                    "Doppler velocity full-scale %.1f cm/s outside expected 10..400 cm/s; check tags",
                    full_scale,
                )
```

Update the candidate build to pass the new values:

```python
        candidate = calibration_from_roi_and_baseline(
            roi,
            baseline_y,
            velocity_span_cm_s=velocity_span,
            time_span_ms=time_span_ms if time_span_ms is not None else 0.0,
            time_origin_ms=time_origin_ms,
            kind=region_kind,
            velocity_per_pixel_cm_s=velocity_per_pixel,
        )
        candidate = DopplerCalibrationState(
            roi=candidate.roi,
            baseline_y_px=candidate.baseline_y_px,
            time_origin_ms=candidate.time_origin_ms,
            time_span_ms=candidate.time_span_ms,
            velocity_span_cm_s=candidate.velocity_span_cm_s,
            kind=candidate.kind,
            from_dicom_tags=True,
            time_from_dicom_tags=time_span_ms is not None,
            velocity_from_dicom_tags=velocity_span is not None,
            velocity_per_pixel_cm_s=candidate.velocity_per_pixel_cm_s,
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./scripts/run_tests.sh tests/unit/test_dicom_doppler_calibration.py`
Expected: PASS (all tests including updated baseline test).

- [ ] **Step 6: Verify on real carotid files**

Run:

```bash
ECHO_CAROTID_DICOM_DIR="/home/areatu/ECHO2026_src/carotid doppler" ./scripts/run_tests.sh tests/unit/test_dicom_doppler_calibration.py::test_parse_user_download_dicom_when_available
```

If the dir-agnostic test still passes, run a one-off sanity check:

```bash
cd /home/areatu/ECHO2026 && ECHO_CAROTID_DICOM_DIR="/home/areatu/ECHO2026_src/carotid doppler" .venv/bin/python - <<'EOF'
import os
from pathlib import Path
from echo_personal_tool.infrastructure.dicom_doppler_calibration import try_parse_from_path
root = Path(os.environ["ECHO_CAROTID_DICOM_DIR"])
for f in sorted(root.glob("*.dcm")):
    st = try_parse_from_path(f)
    print(f.name[:20], "baseline=%.1f" % st.baseline_y_px, "per_px=%.4f" % st.velocity_per_pixel_cm_s,
          "span=%.1f" % st.velocity_span_cm_s, "time_origin=%.1f" % st.time_origin_ms)
EOF
```

Expected: baseline values 793/733/663 (not raw RefY0), `per_px` matches `PhysicalDeltaY` sign and magnitude, `time_origin` 0.0.

- [ ] **Step 7: Commit (ask user first)**

```bash
git add src/echo_personal_tool/infrastructure/dicom_doppler_calibration.py tests/unit/test_dicom_doppler_calibration.py
git commit -m "fix(doppler): absolute baseline, signed deltaY, and time origin from DICOM tags"
```

---

### Task 5: Viewer — preserve `velocity_per_pixel_cm_s` when applying state

**Files:**
- Modify: `src/echo_personal_tool/presentation/viewer_widget.py` (~line 2250)
- Test: `tests/unit/test_viewer_widget.py`

**Interfaces:**
- Consumes: `DopplerCalibrationState.velocity_per_pixel_cm_s` (Task 1).
- Produces: `apply_doppler_calibration_state` rebuild keeps the per-pixel field so `build_axis_mapping` sees it.

- [ ] **Step 1: Add failing test**

Append to `TestDopplerCalibrationState` in `tests/unit/test_viewer_widget.py`:

```python
    def test_apply_doppler_calibration_state_preserves_per_pixel(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        from echo_personal_tool.domain.models.doppler_roi import (
            DopplerCalibrationState,
            DopplerSpectrogramRoi,
        )

        roi = DopplerSpectrogramRoi(x0=10, y0=10, width=50, height=30)
        state = DopplerCalibrationState(
            roi=roi,
            baseline_y_px=25.0,
            velocity_span_cm_s=100.0,
            velocity_per_pixel_cm_s=-0.5,
        )
        w.apply_doppler_calibration_state(state, persist=False)
        assert w._doppler_calibration_state is not None
        assert w._doppler_calibration_state.velocity_per_pixel_cm_s == -0.5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./scripts/run_tests.sh tests/unit/test_viewer_widget.py -k preserves_per_pixel`
Expected: FAIL (assertion — field is `None`).

- [ ] **Step 3: Implement**

In `src/echo_personal_tool/presentation/viewer_widget.py`, in `apply_doppler_calibration_state`, add the field to the rebuilt `DopplerCalibrationState` (right after `velocity_from_dicom_tags`):

```python
                velocity_per_pixel_cm_s=getattr(state, 'velocity_per_pixel_cm_s', None),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./scripts/run_tests.sh tests/unit/test_viewer_widget.py -k DopplerCalibrationState`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit (ask user first)**

```bash
git add src/echo_personal_tool/presentation/viewer_widget.py tests/unit/test_viewer_widget.py
git commit -m "fix(viewer): preserve per-pixel velocity scale when applying calibration state"
```

---

### Task 6: Full regression run

**Files:** none (verification only)

- [ ] **Step 1: Run the affected test suites**

Run:

```bash
./scripts/run_tests.sh tests/unit/test_doppler_roi.py tests/unit/test_doppler_axis.py tests/unit/test_doppler_calibration.py tests/unit/test_dicom_doppler_calibration.py tests/unit/test_viewer_widget.py
```

Expected: only the pre-existing `test_poc_default` failure remains (out of scope).

- [ ] **Step 2: Run the wider Doppler + regression suites**

Run:

```bash
./scripts/run_tests.sh tests/unit/test_doppler_controller.py tests/unit/test_doppler_metrics.py tests/unit/test_doppler_overlay.py tests/unit/test_presentation_doppler_overlay.py tests/regression/test_doppler_regression.py tests/unit/test_maximum_calibration_regression.py
```

Expected: PASS.

- [ ] **Step 3: Commit (ask user first) — only if there are uncommitted changes**

```bash
git status --short
```

---

## Self-Review Notes

- Spec §3.2.1 (baseline) → Task 4 Step 4 `_extract_samsung_baseline`.
- Spec §3.2.2 (signed ΔY) → Task 4 `raw_delta_y`/`velocity_per_pixel`.
- Spec §3.2.3 (time origin) → Task 4 `time_origin_ms`.
- Spec §3.2.4 (consistency) → Task 4 warning.
- Spec §3.3 (axis mapping) → Tasks 2 and 3.
- Spec §3.4 (viewer) → Task 5.
- Spec §4 (tests) → Tasks 1–5 test steps.
- Spec §3.5 (no changes to `ultrasound_region_physics.py`) → respected; `region_physical_deltas` untouched.
- DoD (CHANGELOG_SESSION.md entry) → record at end of session, not per task.
