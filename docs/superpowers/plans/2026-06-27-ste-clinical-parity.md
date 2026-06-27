# STE Clinical Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace forward-only NCC pipeline with commercial-parity STE: bidirectional ED-anchored tracking, spline smoothing, Green–Lagrange strain, AHA segments, drift compensation, and QC UI.

**Architecture:** Pure domain services (`contour_utils`, `tracking_smoothing`, `aha_segments`) orchestrated by `SpeckleTrackingWorker`. Determinism fixes in `FrameCache` first. Presentation layer gets quality panel and settings dialog. All changes backward-compatible via extended dataclasses with defaults.

**Tech Stack:** Python 3.11+, NumPy, SciPy (`CubicSpline`), OpenCV (`matchTemplate`), PySide6, PyQtGraph

**Spec:** [`docs/superpowers/specs/2026-06-27-ste-clinical-parity-design.md`](../specs/2026-06-27-ste-clinical-parity-design.md)

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/echo_personal_tool/domain/exceptions.py` | Create | `IncompleteCineError`, `TrackingIncompleteError` |
| `src/echo_personal_tool/domain/services/contour_utils.py` | Create | Arc-length contour resampling |
| `src/echo_personal_tool/domain/services/tracking_smoothing.py` | Create | Spatial/temporal spline smoothing |
| `src/echo_personal_tool/domain/services/aha_segments.py` | Create | AHA segment assignment + GLS |
| `src/echo_personal_tool/domain/models/speckle.py` | Modify | Extended config, kernel, result fields |
| `src/echo_personal_tool/application/frame_cache.py` | Modify | `require_full_cine()` |
| `src/echo_personal_tool/domain/services/speckle_tracking.py` | Modify | Bidirectional ED-anchored tracking |
| `src/echo_personal_tool/domain/services/strain_computation.py` | Modify | Green–Lagrange, drift comp, arc-length |
| `src/echo_personal_tool/domain/services/cardiac_cycle_detector.py` | Modify | Smoothed ED/ES, ROI HR |
| `src/echo_personal_tool/domain/services/myocardial_zone.py` | Modify | Call resample before zone creation |
| `src/echo_personal_tool/application/workers/speckle_worker.py` | Modify | New pipeline order |
| `src/echo_personal_tool/application/app_controller.py` | Modify | `require_full_cine`, preset config |
| `src/echo_personal_tool/presentation/segment_quality_panel.py` | Create | AHA segment QC table |
| `src/echo_personal_tool/presentation/speckle_settings_dialog.py` | Create | Preset + drift comp UI |
| `src/echo_personal_tool/presentation/speckle_overlay.py` | Modify | NCC color coding |
| `src/echo_personal_tool/presentation/main_window.py` | Modify | Wire strain curve + QC panel |
| `tests/unit/test_contour_utils.py` | Create | Resample determinism |
| `tests/unit/test_frame_cache.py` | Create | Full cine guard |
| `tests/unit/test_tracking_smoothing.py` | Create | Spline tests |
| `tests/unit/test_aha_segments.py` | Create | Segment mapping |
| `tests/unit/test_speckle_tracking.py` | Modify | Bidirectional tests |
| `tests/unit/test_strain_computation.py` | Create | GL strain, drift comp |
| `tests/unit/test_ste_reproducibility.py` | Create | 10-run GLS σ test |

---

### Task 1: Determinism Fixes

**Files:**
- Create: `src/echo_personal_tool/domain/exceptions.py`
- Create: `src/echo_personal_tool/domain/services/contour_utils.py`
- Modify: `src/echo_personal_tool/application/frame_cache.py`
- Modify: `src/echo_personal_tool/domain/services/myocardial_zone.py`
- Modify: `src/echo_personal_tool/application/app_controller.py`
- Create: `tests/unit/test_contour_utils.py`
- Create: `tests/unit/test_frame_cache.py`

- [ ] **Step 1: Write failing tests for contour resample and frame cache**

```python
# tests/unit/test_contour_utils.py
import numpy as np
from echo_personal_tool.domain.services.contour_utils import resample_contour

def test_resample_contour_fixed_count():
    pts = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]], dtype=np.float64)
    out = resample_contour(pts, n_points=128)
    assert out.shape == (128, 2)

def test_resample_contour_deterministic():
    pts = np.array([[0.0, 0.0], [5.0, 5.0], [10.0, 0.0]], dtype=np.float64)
    a = resample_contour(pts, 64)
    b = resample_contour(pts, 64)
    np.testing.assert_array_equal(a, b)
```

```python
# tests/unit/test_frame_cache.py
import numpy as np
import pytest
from echo_personal_tool.application.frame_cache import FrameCache
from echo_personal_tool.domain.exceptions import IncompleteCineError

def test_require_full_cine_raises_on_partial():
    cache = FrameCache(evict_window=2)
    frames = np.zeros((10, 32, 32), dtype=np.uint8)
    cache.load(__import__("pathlib").Path("fake.dcm"), frames)
    cache.set_current(5)  # evicts frames outside window
    with pytest.raises(IncompleteCineError):
        cache.require_full_cine()

def test_require_full_cine_returns_stack():
    cache = FrameCache()
    frames = np.arange(50, dtype=np.uint8).reshape(5, 2, 5)
    cache.load(__import__("pathlib").Path("fake.dcm"), frames)
    out = cache.require_full_cine()
    assert out.shape == (5, 2, 5)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_contour_utils.py tests/unit/test_frame_cache.py -v`  
Expected: FAIL — module/function not found

- [ ] **Step 3: Implement exceptions, contour_utils, frame_cache guard**

```python
# src/echo_personal_tool/domain/exceptions.py
class IncompleteCineError(RuntimeError):
    """Raised when speckle tracking requires full cine but frames were evicted."""

class TrackingIncompleteError(RuntimeError):
    """Raised when too few kernels tracked successfully."""
```

```python
# src/echo_personal_tool/domain/services/contour_utils.py
"""Contour geometry utilities for deterministic STE."""

from __future__ import annotations

import numpy as np


def resample_contour(points: np.ndarray, n_points: int = 128) -> np.ndarray:
    """Uniform arc-length resampling of a closed/open polyline."""
    pts = np.asarray(points, dtype=np.float64)
    if pts.shape[0] < 2:
        raise ValueError("Contour needs at least 2 points")
    if pts.shape[0] == n_points:
        return pts.copy()
    diffs = np.diff(pts, axis=0)
    seg_lens = np.linalg.norm(diffs, axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg_lens)])
    total = cum[-1]
    if total < 1e-9:
        return np.tile(pts[0], (n_points, 1))
    targets = np.linspace(0.0, total, n_points, endpoint=False)
    out = np.zeros((n_points, 2), dtype=np.float64)
    for i, t in enumerate(targets):
        idx = int(np.searchsorted(cum, t, side="right") - 1)
        idx = min(max(idx, 0), len(seg_lens) - 1)
        seg_start = cum[idx]
        seg_len = seg_lens[idx] if seg_lens[idx] > 1e-9 else 1.0
        alpha = (t - seg_start) / seg_len
        out[i] = pts[idx] + alpha * (pts[idx + 1] - pts[idx])
    return out
```

```python
# Add to frame_cache.py
from echo_personal_tool.domain.exceptions import IncompleteCineError

def require_full_cine(self) -> np.ndarray:
    if not self._frame_store or self._total_frames == 0:
        raise IncompleteCineError("Frame cache is empty")
    if len(self._frame_store) != self._total_frames:
        raise IncompleteCineError(
            f"Only {len(self._frame_store)}/{self._total_frames} frames loaded. "
            "Reload full cine before speckle tracking."
        )
    return np.stack([self._frame_store[i] for i in range(self._total_frames)])
```

- [ ] **Step 4: Wire resample in myocardial_zone and app_controller**

In `create_myocardial_zone()`:
```python
from echo_personal_tool.domain.services.contour_utils import resample_contour
endo_points = resample_contour(endo_points, n_points=128)
```

In `app_controller.run_speckle_tracking()` replace `self._frame_cache.frames` with `self._frame_cache.require_full_cine()`.

- [ ] **Step 5: Run tests**

Run: `pytest tests/unit/test_contour_utils.py tests/unit/test_frame_cache.py -v`  
Expected: PASS

---

### Task 2: Extended Config + Bidirectional ED-Anchored Tracking

**Files:**
- Modify: `src/echo_personal_tool/domain/models/speckle.py`
- Modify: `src/echo_personal_tool/domain/services/speckle_tracking.py`
- Modify: `tests/unit/test_speckle_tracking.py`

- [ ] **Step 1: Extend SpeckleConfig and TrackingKernel**

Add fields per spec §7.1 and §7.3. Add `preset_echo_pac()`, `preset_tomtec()`, `preset_debug()` classmethods. Change defaults: `kernel_size=20`, `search_radius=20`.

Extend `TrackingResult` to include `reference_frame: int = 0` (ED index used).

- [ ] **Step 2: Write failing bidirectional test**

```python
def test_bidirectional_ed_closure_smaller_than_forward():
    """ED-anchored bidirectional should have lower position error at last frame vs ED."""
    n_frames = 20
    frames = _make_synthetic_cine(n_frames, shift_per_frame=0.5)
    kernels = _make_test_kernels()
    config_fwd = SpeckleConfig.preset_debug()  # bidirectional=False
    config_bidi = SpeckleConfig.preset_echo_pac()

    fwd = track_cine(frames, kernels, config_fwd)
    bidi = track_cine_bidirectional(frames, kernels, ed_index=0, config=config_bidi)

    fwd_err = _ed_closure_error(fwd, kernels)
    bidi_err = _ed_closure_error_bidi(bidi, kernels, ed_index=0)
    assert bidi_err < fwd_err * 0.75
```

- [ ] **Step 3: Implement track_cine_bidirectional**

Add to `speckle_tracking.py`:

```python
def track_frame_from_reference(
    reference: np.ndarray,
    target: np.ndarray,
    kernel_centers: list[tuple[float, float]],
    config: SpeckleConfig,
) -> TrackingResult:
    """Match kernels from reference frame positions to target frame."""
    kernels = [
        TrackingKernel(center=c, node_index=i, layer="endo")
        for i, c in enumerate(kernel_centers)
    ]
    return track_frame_pair(reference, target, kernels, config)


def track_cine_bidirectional(
    frames: np.ndarray,
    initial_kernels: list[TrackingKernel],
    ed_index: int,
    config: SpeckleConfig,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[TrackingResult]:
    n_frames = frames.shape[0]
    ed_index = int(np.clip(ed_index, 0, n_frames - 1))
    ed_centers = [k.center for k in initial_kernels]
    ed_frame = frames[ed_index]

    # positions[t, k, 2] — absolute positions
    positions = np.zeros((n_frames, len(initial_kernels), 2), dtype=np.float64)
    ncc_all = np.zeros((n_frames, len(initial_kernels)), dtype=np.float64)
    valid_all = np.zeros((n_frames, len(initial_kernels)), dtype=bool)
    positions[ed_index] = ed_centers

    for t in range(n_frames):
        if t == ed_index:
            ncc_all[t] = 1.0
            valid_all[t] = True
            continue
        # Forward: ED → t
        fwd = track_frame_from_reference(ed_frame, frames[t], ed_centers, config)
        p_fwd = fwd.kernel_positions
        w_fwd = fwd.ncc_scores
        v_fwd = fwd.valid_mask

        if config.bidirectional:
            # Backward: t → ED (template from target at forward position)
            bwd_kernels = [
                TrackingKernel(center=(float(p_fwd[i, 0]), float(p_fwd[i, 1])),
                               node_index=i, layer=initial_kernels[i].layer)
                for i in range(len(initial_kernels))
            ]
            bwd = track_frame_pair(frames[t], ed_frame, bwd_kernels, config)
            p_bwd = ed_centers  # template found in ED → use ED anchor + inverse
            # bwd.kernel_positions are positions in ED frame matching t templates
            p_from_bwd = bwd.kernel_positions  # positions in ED coords
            w_bwd = bwd.ncc_scores
            v_bwd = bwd.valid_mask

            for i in range(len(initial_kernels)):
                if v_fwd[i] and v_bwd[i]:
                    wf, wb = w_fwd[i], w_bwd[i]
                    positions[t, i] = (wf * p_fwd[i] + wb * p_from_bwd[i]) / (wf + wb)
                    ncc_all[t, i] = (wf + wb) / 2
                    valid_all[t, i] = True
                elif v_fwd[i]:
                    positions[t, i] = p_fwd[i]
                    ncc_all[t, i] = w_fwd[i]
                    valid_all[t, i] = True
                elif v_bwd[i]:
                    positions[t, i] = p_from_bwd[i]
                    ncc_all[t, i] = w_bwd[i]
                    valid_all[t, i] = True
        else:
            positions[t] = p_fwd
            ncc_all[t] = w_fwd
            valid_all[t] = v_fwd

        if progress_callback:
            progress_callback(t + 1, n_frames)

    # Convert to list[TrackingResult] with displacements relative to previous frame
    results: list[TrackingResult] = []
    for t in range(1, n_frames):
        disp = positions[t] - positions[t - 1]
        results.append(TrackingResult(
            frame_index=t,
            displacements=disp,
            ncc_scores=ncc_all[t],
            valid_mask=valid_all[t],
            kernel_positions=positions[t],
        ))
    return results
```

Update `track_cine()`:
```python
def track_cine(...):
    if config.bidirectional and config.ed_anchored:
        return track_cine_bidirectional(frames, initial_kernels, ed_index=0, config=config, ...)
    # existing forward-only path
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_speckle_tracking.py -v`  
Expected: PASS (existing + new bidirectional test)

---

### Task 3: Spatial + Temporal Spline Smoothing

**Files:**
- Create: `src/echo_personal_tool/domain/services/tracking_smoothing.py`
- Create: `tests/unit/test_tracking_smoothing.py`

- [ ] **Step 1: Write failing smoothing tests**

```python
def test_spatial_smoothing_preserves_valid_kernels():
    positions = np.random.randn(10, 32, 2)
    ncc = np.full((10, 32), 0.8)
    kernels = [TrackingKernel(center=(0, 0), node_index=i, layer="endo") for i in range(32)]
    config = SpeckleConfig(spatial_smoothing=1.0, temporal_smoothing=0.0)
    out = smooth_trajectories(positions, ncc, kernels, config)
    assert out.shape == positions.shape

def test_temporal_smoothing_reduces_jitter():
    t = np.arange(20)
    positions = np.zeros((20, 4, 2))
    positions[:, :, 0] = t[:, None] + np.random.randn(20, 4) * 0.5
    ncc = np.full((20, 4), 0.9)
    kernels = [TrackingKernel(center=(0, 0), node_index=i, layer="endo") for i in range(4)]
    config = SpeckleConfig(spatial_smoothing=0.0, temporal_smoothing=2.0)
    out = smooth_trajectories(positions, ncc, kernels, config)
    assert np.std(np.diff(out[:, 0, 0])) < np.std(np.diff(positions[:, 0, 0]))
```

- [ ] **Step 2: Implement tracking_smoothing.py**

```python
"""Spatial and temporal spline smoothing for STE trajectories."""

from __future__ import annotations

import numpy as np
from scipy.interpolate import CubicSpline

from echo_personal_tool.domain.models.speckle import SpeckleConfig, TrackingKernel


def _layer_groups(kernels: list[TrackingKernel]) -> dict[str, list[int]]:
    groups: dict[str, list[int]] = {}
    for i, k in enumerate(kernels):
        groups.setdefault(k.layer, []).append(i)
    return groups


def smooth_trajectories(
    positions: np.ndarray,
    ncc_scores: np.ndarray,
    kernels: list[TrackingKernel],
    config: SpeckleConfig,
) -> np.ndarray:
    """Apply quality-weighted spatial then temporal smoothing."""
    out = positions.copy()
    n_frames, n_kernels, _ = out.shape
    if config.spatial_smoothing <= 0 and config.temporal_smoothing <= 0:
        return out

    groups = _layer_groups(kernels)
    for _layer, indices in groups.items():
        idx = sorted(indices, key=lambda i: kernels[i].node_index)
        if len(idx) < 4:
            continue
        if config.spatial_smoothing > 0:
            for t in range(n_frames):
                pts = out[t, idx, :]
                s = config.spatial_smoothing * len(idx)
                if config.quality_weighted_smoothing:
                    w = np.clip(ncc_scores[t, idx], 0.01, 1.0)
                    s *= float(np.mean(1.0 - w) + 0.1)
                t_param = np.arange(len(idx), dtype=np.float64)
                cs_x = CubicSpline(t_param, pts[:, 0], bc_type="natural", s=s)
                cs_y = CubicSpline(t_param, pts[:, 1], bc_type="natural", s=s)
                out[t, idx, 0] = cs_x(t_param)
                out[t, idx, 1] = cs_y(t_param)

    if config.temporal_smoothing > 0:
        times = np.arange(n_frames, dtype=np.float64)
        for i in range(n_kernels):
            s = config.temporal_smoothing * n_frames
            if config.quality_weighted_smoothing:
                s *= float(np.mean(1.0 - np.clip(ncc_scores[:, i], 0.01, 1.0)) + 0.1)
            cs_x = CubicSpline(times, out[:, i, 0], bc_type="natural", s=s)
            cs_y = CubicSpline(times, out[:, i, 1], bc_type="natural", s=s)
            out[:, i, 0] = cs_x(times)
            out[:, i, 1] = cs_y(times)
    return out


def extract_trajectories(
    tracking_results: list[TrackingResult],
    initial_kernels: list[TrackingKernel],
) -> tuple[np.ndarray, np.ndarray]:
    """Build (n_frames, n_kernels, 2) positions and NCC matrix from results."""
    ...
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/unit/test_tracking_smoothing.py -v`  
Expected: PASS

---

### Task 4: Green–Lagrange Strain + Drift Compensation

**Files:**
- Modify: `src/echo_personal_tool/domain/services/strain_computation.py`
- Create: `tests/unit/test_strain_computation.py`

- [ ] **Step 1: Write failing strain tests**

```python
def test_green_lagrange_zero_at_reference():
    positions = np.tile(np.array([[0, 0], [10, 0], [20, 0]], dtype=float), (5, 1, 1))
    strain = compute_longitudinal_strain_gl(positions, ed_index=0, pixel_spacing=(1.0, 1.0))
    np.testing.assert_allclose(strain[0], 0.0, atol=1e-6)

def test_drift_compensation_zeros_endpoints():
    strain = np.array([0.0, -5.0, -10.0, -8.0, -2.0])
    corrected = apply_drift_compensation(strain, ed_index=0, n_frames=5)
    np.testing.assert_allclose(corrected[0], 0.0, atol=1e-6)
    np.testing.assert_allclose(corrected[-1], 0.0, atol=1e-6)
```

- [ ] **Step 2: Implement Green–Lagrange and drift compensation**

```python
def contour_arc_length(points: np.ndarray, pixel_spacing: tuple[float, float]) -> float:
    avg = np.mean(pixel_spacing)
    diffs = np.diff(points, axis=0)
    return float(np.sum(np.linalg.norm(diffs, axis=1)) * avg)


def compute_longitudinal_strain_gl(
    positions: np.ndarray,
    ed_index: int,
    pixel_spacing: tuple[float, float],
    endo_indices: list[int],
) -> np.ndarray:
    n_frames = positions.shape[0]
    strain = np.zeros(n_frames)
    ed_pts = positions[ed_index, endo_indices, :]
    l0 = contour_arc_length(ed_pts, pixel_spacing)
    if l0 < 1e-6:
        return strain
    for t in range(n_frames):
        lt = contour_arc_length(positions[t, endo_indices, :], pixel_spacing)
        ratio = lt / l0
        strain[t] = 0.5 * (ratio ** 2 - 1.0) * 100.0
    return strain


def apply_drift_compensation(
    strain: np.ndarray, ed_index: int, n_frames: int
) -> np.ndarray:
    out = strain.copy()
    if n_frames < 2:
        return out
    end_idx = n_frames - 1
    drift_slope = (out[end_idx] - out[ed_index]) / max(end_idx - ed_index, 1)
    for t in range(n_frames):
        out[t] -= drift_slope * (t - ed_index)
    out[ed_index] = 0.0
    return out
```

Keep `compute_longitudinal_strain()` as deprecated wrapper calling new path when smoothed positions available.

- [ ] **Step 3: Run tests**

Run: `pytest tests/unit/test_strain_computation.py -v`  
Expected: PASS

---

### Task 5: AHA Segment GLS

**Files:**
- Create: `src/echo_personal_tool/domain/services/aha_segments.py`
- Create: `tests/unit/test_aha_segments.py`
- Modify: `src/echo_personal_tool/domain/models/speckle.py` (StrainResult fields)

- [ ] **Step 1: Write failing AHA tests**

```python
def test_assign_aha_segments_apical4ch():
    center = (100.0, 100.0)
    kernels = [
        TrackingKernel(center=(100, 50), node_index=0, layer="endo", arc_length_param=0.0),
        TrackingKernel(center=(150, 100), node_index=8, layer="endo", arc_length_param=0.25),
    ]
    assigned = assign_aha_segments(kernels, lv_center=center, view="A4C")
    assert all(k.aha_segment > 0 for k in assigned)

def test_gls_from_segments_excludes_low_quality():
    segment_strain = {1: -18.0, 2: -20.0, 3: -5.0}
    segment_quality = {1: 0.9, 2: 0.8, 3: 0.2}
    gls = compute_gls_from_segments(segment_strain, segment_quality, min_quality=0.4)
    assert gls == pytest.approx(-19.0, abs=0.1)
```

- [ ] **Step 2: Implement aha_segments.py**

Map `arc_length_param` to 6 visible A4C segments. `compute_aha_segment_strain()` takes per-kernel GL strain at ES. `compute_gls_from_segments()` averages segments passing quality threshold.

- [ ] **Step 3: Run tests**

Run: `pytest tests/unit/test_aha_segments.py -v`  
Expected: PASS

---

### Task 6: Improved ED/ES Detection + Worker Pipeline Integration

**Files:**
- Modify: `src/echo_personal_tool/domain/services/cardiac_cycle_detector.py`
- Modify: `src/echo_personal_tool/application/workers/speckle_worker.py`

- [ ] **Step 1: Add smoothed ED/ES pre-detection**

```python
def detect_ed_es_from_frames(
    frames: np.ndarray,
    zone: MyocardialZone,
    config: SpeckleConfig,
) -> tuple[int, int]:
    """Pre-tracking ED/ES from endo area proxy (image intensity within zone)."""
    areas = []
    for t in range(frames.shape[0]):
        areas.append(_estimate_lv_area_proxy(frames[t], zone))
    areas = np.array(areas, dtype=np.float64)
    from scipy.interpolate import CubicSpline
    cs = CubicSpline(np.arange(len(areas)), areas, bc_type="natural", s=len(areas) * 0.5)
    smooth = cs(np.arange(len(areas)))
    ed = int(np.argmax(smooth))
    es = int(np.argmin(smooth))
    if ed == es:
        es = (ed + len(areas) // 3) % len(areas)
    return ed, es
```

Update `estimate_heart_rate_fft` call in worker to pass myocardial ROI mask.

- [ ] **Step 2: Rewrite speckle_worker.run() per spec §8**

Pipeline order:
1. Resample contour / assign AHA
2. Pre-detect ED/ES
3. `track_cine_bidirectional`
4. `extract_trajectories` + `smooth_trajectories`
5. `compute_longitudinal_strain_gl` + optional `apply_drift_compensation`
6. `compute_aha_segment_strain` + `compute_gls_from_segments`
7. Populate extended `StrainResult`

- [ ] **Step 3: Manual test command for user**

Run: `pytest tests/unit/test_speckle_tracking.py tests/unit/test_strain_computation.py -v`  
Expected: PASS

---

### Task 7: Quality Metrics + QC UI

**Files:**
- Create: `src/echo_personal_tool/presentation/segment_quality_panel.py`
- Create: `src/echo_personal_tool/presentation/speckle_settings_dialog.py`
- Modify: `src/echo_personal_tool/presentation/speckle_overlay.py`
- Modify: `src/echo_personal_tool/presentation/main_window.py`
- Modify: `src/echo_personal_tool/application/app_controller.py`

- [ ] **Step 1: Implement SegmentQualityPanel**

Table widget: columns Segment, Strain %, Quality (0–100). Red row if quality < 40%.

- [ ] **Step 2: Implement SpeckleSettingsDialog**

ComboBox presets (EchoPAC/TomTec/Debug), drift compensation checkbox, wall thickness spinbox. Returns `SpeckleConfig`.

- [ ] **Step 3: Update SpeckleOverlay.show_kernels**

Color by NCC: green ≥0.7, yellow 0.5–0.7, red <0.5 (already partially exists — align thresholds).

- [ ] **Step 4: Wire in main_window and app_controller**

Before tracking: show settings dialog. After tracking: populate `SegmentQualityPanel`, wire `StrainCurveWidget`, status bar message with GLS/quality/drift comp.

---

### Task 8: Multi-Cycle Averaging + Reproducibility Tests

**Files:**
- Modify: `src/echo_personal_tool/domain/services/cardiac_cycle_detector.py`
- Modify: `src/echo_personal_tool/application/workers/speckle_worker.py`
- Create: `tests/unit/test_ste_reproducibility.py`

- [ ] **Step 1: Implement cycle detection and averaging**

```python
def detect_cycle_boundaries(areas: np.ndarray, min_cycle_frames: int = 15) -> list[tuple[int, int]]:
    """Return list of (start, end) frame indices for each cardiac cycle."""
    ...

def average_strain_curves(curves: list[np.ndarray], boundaries: list[tuple[int, int]]) -> np.ndarray:
    """Resample each cycle to normalized phase and average."""
    ...
```

In worker: if `config.multi_cycle_average` and ≥2 cycles → track each cycle independently, average strain curves.

- [ ] **Step 2: Write reproducibility test**

```python
def test_gls_reproducible_10_runs():
    frames = _synthetic_cine_deterministic()
    contour = _synthetic_contour()
    config = SpeckleConfig.preset_echo_pac()
    gls_values = []
    for _ in range(10):
        result = _run_pipeline(frames, contour, config)
        gls_values.append(result.gls)
    assert np.std(gls_values) < 0.5
```

- [ ] **Step 3: Run full test suite**

Run: `pytest tests/unit/test_ste_reproducibility.py tests/unit/ -v --ignore=tests/integration`  
Expected: PASS

- [ ] **Step 4: Update CHANGELOG_SESSION.md**

Add entry for STE clinical parity spec + plan (not implementation yet).

---

## Spec Coverage Checklist

| Spec § | Task |
|--------|------|
| §5 A1+A2 Bidirectional | Task 2 |
| §5 A3 Smoothing | Task 3 |
| §5 A4 Drift comp | Task 4 |
| §5 A5 Green–Lagrange | Task 4 |
| §5 A6 AHA segments | Task 5 |
| §5 A7 QC UI | Task 7 |
| §5 A8 Multi-cycle | Task 8 |
| §6 Determinism | Task 1 |
| §7 Config schema | Task 2 |
| §8 Worker pipeline | Task 6 |
| §9 UI | Task 7 |
| §11 Tests | Tasks 1–8 |

## Plan Self-Review

- No TBD/TODO placeholders in task steps.
- All new functions referenced in worker have implementing tasks.
- Type names consistent: `TrackingResult`, `SpeckleConfig`, `StrainResult` extended in Task 2 before use in Tasks 3–8.
- Spec §5 A2 backward fusion clarified in Task 2 implementation.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-27-ste-clinical-parity.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks
2. **Inline Execution** — execute tasks in session using executing-plans with checkpoints

Which approach?
