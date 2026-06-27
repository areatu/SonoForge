# TDA-Enhanced Speckle Tracking — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add topological data analysis (persistent homology) to the existing NCC block-matching pipeline for (1) adaptive kernel placement and (2) outlier rejection.

**Architecture:** Minimal changes to existing domain services. New `topological_analysis.py` module wraps `ripser` PH computations. `myocardial_zone.py` gains an optional `tda_quality_filter` path that scores candidates by persistence entropy. `speckle_tracking.py` adds a PH-based decorrelation detector as a second-stage outlier filter after NCC+MAD.

**Tech Stack:** Python 3.11+, NumPy, OpenCV, `ripser>=0.6`, `persim>=0.3`. No GPU required.

## Global Constraints

- All new code must handle `ImportError` for `ripser` gracefully (fall back to current behaviour).
- No changes to existing function signatures without adding backward-compatible defaults.
- TDA features are **opt-in** via `SpeckleConfig` flags (default `False` for zero impact on existing behaviour).
- All new functions must have unit tests.

---

### Task 1: Install and verify `ripser`

- [ ] **Step 1: Check installation**

```bash
python3 -c "import ripser; print(ripser.__version__)" 
```

Expected output:
```
Traceback (most recent call last): ...
ModuleNotFoundError: No module named 'ripser'
```

- [ ] **Step 2: Install ripser and persim**

```bash
pip install ripser persim --break-system-packages 2>&1 | tail -5
```

Expected to see `Successfully installed ripser-0.6.* persim-0.3.*`

- [ ] **Step 3: Verify import works**

```bash
python3 -c "import ripser; from persim import PersistenceImager; print('ok')"
```

Expected: `ok`

---

### Task 2: Add `SpeckleConfig` TDA fields

**Files:**
- Modify: `src/echo_personal_tool/domain/models/speckle.py`

- [ ] **Step 1: Read current file**

```bash
cat src/echo_personal_tool/domain/models/speckle.py
```

- [ ] **Step 2: Add three TDA fields to `SpeckleConfig` dataclass**

Find `@dataclass` class `SpeckleConfig` and add after `subpixel: bool = True`:

```python
# Topological Data Analysis (TDA) flags
tda_quality_filter: bool = False        # adaptive kernel placement via PH
tda_outlier_rejection: bool = False     # PH-based decorrelation detector
tda_decorrelation_threshold: float = 0.3  # max bottleneck distance for valid track
```

- [ ] **Step 3: Verify refactoring didn't break anything**

```bash
python3 -c "from echo_personal_tool.domain.models.speckle import SpeckleConfig; c = SpeckleConfig(); print(c.tda_quality_filter, c.tda_outlier_rejection)"
```

Expected: `False False`

---

### Task 3: Create `topological_analysis.py` module

**Files:**
- Create: `src/echo_personal_tool/domain/services/topological_analysis.py`
- Test: `tests/unit/test_topological_analysis.py`

**Interfaces:**
- Consumes: `numpy.ndarray` patches (H×W, float32)
- Produces: `persistence_entropy(patch) → float`, `persistence_score(patch) → float`, `topological_similarity(ref, tgt) → float`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for topological_analysis module."""

import numpy as np
import pytest

from echo_personal_tool.domain.services.topological_analysis import (
    local_maxima_point_cloud,
    persistence_entropy,
    persistence_score,
    topological_similarity,
)


def test_local_maxima_point_cloud_returns_points():
    patch = np.random.rand(12, 12).astype(np.float32)
    points = local_maxima_point_cloud(patch, threshold_rel=0.3)
    assert isinstance(points, np.ndarray)
    assert points.ndim == 2
    assert points.shape[1] == 2


def test_local_maxima_point_cloud_uniform():
    patch = np.full((12, 12), 0.5, dtype=np.float32)
    points = local_maxima_point_cloud(patch, threshold_rel=0.3)
    assert len(points) == 0


def test_persistence_entropy_returns_scalar():
    patch = np.random.rand(12, 12).astype(np.float32)
    e = persistence_entropy(patch)
    assert isinstance(e, float)
    assert 0.0 <= e < 10.0


def test_persistence_entropy_uniform():
    patch = np.full((12, 12), 0.5, dtype=np.float32)
    e = persistence_entropy(patch)
    assert e == 0.0


def test_persistence_score_returns_scalar():
    patch = np.random.rand(12, 12).astype(np.float32)
    s = persistence_score(patch)
    assert isinstance(s, float)
    assert 0.0 <= s <= 1.0


def test_topological_similarity_identical():
    patch = np.random.rand(12, 12).astype(np.float32)
    sim = topological_similarity(patch, patch)
    assert isinstance(sim, float)
    assert sim >= 0.0


def test_topological_similarity_different():
    ref = np.random.rand(12, 12).astype(np.float32)
    tgt = np.random.rand(12, 12).astype(np.float32)
    sim = topological_similarity(ref, tgt)
    assert isinstance(sim, float)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/areatu/ECHO2026 && python3 -m pytest tests/unit/test_topological_analysis.py -v 2>&1 | head -30
```

Expected: FAIL with `ModuleNotFoundError: No module named '...topological_analysis'`

- [ ] **Step 3: Write the implementation**

```python
"""Topological data analysis utilities for speckle tracking.

Uses persistent homology (via ripser) to measure speckle pattern richness
and detect decorrelation between frames.
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import gaussian_filter, maximum_filter

try:
    import ripser as _ripser
    from persim import bottleneck

    _HAS_TDA = True
except ImportError:
    _HAS_TDA = False


def local_maxima_point_cloud(
    patch: np.ndarray,
    threshold_rel: float = 0.3,
    sigma: float = 1.0,
) -> np.ndarray:
    """Extract 2D point cloud of local maxima from an image patch.

    Applies Gaussian blur, then detects pixels that are maximal in their
    3×3 neighbourhood. Returns their (x, y) coordinates as an (N, 2) array.

    Args:
        patch: (H, W) image patch (float32).
        threshold_rel: minimum intensity as fraction of max.
        sigma: Gaussian blur sigma before peak detection.

    Returns:
        (N, 2) array of (x, y) peak coordinates. Empty if no peaks found.
    """
    if patch.size == 0 or patch.max() == patch.min():
        return np.empty((0, 2), dtype=np.float32)

    smoothed = gaussian_filter(patch.astype(np.float32), sigma=sigma)
    threshold = smoothed.max() * threshold_rel

    footprint = np.ones((3, 3), dtype=bool)
    local_max = maximum_filter(smoothed, footprint=footprint)
    peaks = (smoothed == local_max) & (smoothed >= threshold)

    ys, xs = np.where(peaks)
    return np.column_stack([xs.astype(np.float32), ys.astype(np.float32)])


def _safe_ripser(points: np.ndarray) -> float:
    """Compute persistence entropy of H1 diagram, or 0.0 on failure."""
    if not _HAS_TDA or len(points) < 4:
        return 0.0
    try:
        diagrams = _ripser.ripser(points, maxdim=1)["diagrams"]
        h1 = diagrams[1]
        if len(h1) == 0:
            return 0.0
        lifetimes = h1[:, 1] - h1[:, 0]
        lifetimes = lifetimes[lifetimes > 1e-10]
        if lifetimes.sum() == 0:
            return 0.0
        probs = lifetimes / lifetimes.sum()
        return float(-np.sum(probs * np.log(probs + 1e-10)))
    except Exception:
        return 0.0


def persistence_entropy(patch: np.ndarray, threshold_rel: float = 0.3) -> float:
    """Compute persistence entropy of H1 features in a patch.

    Higher values indicate topologically rich speckle patterns
    (desirable for tracking). Zero means uniform or noisy pattern.

    Args:
        patch: (H, W) image patch.
        threshold_rel: relative threshold for peak detection.

    Returns:
        Persistence entropy (scalar, >= 0).
    """
    points = local_maxima_point_cloud(patch, threshold_rel=threshold_rel)
    return _safe_ripser(points)


def persistence_score(patch: np.ndarray, threshold_rel: float = 0.3) -> float:
    """Normalised topological quality score for adaptive kernel placement.

    Maps persistence_entropy to [0, 1] via sigmoid normalisation.
    Patches with entropy > 2.0 get score near 1.0 (excellent tracking target).

    Args:
        patch: (H, W) image patch.
        threshold_rel: relative threshold for peak detection.

    Returns:
        Score in [0, 1].
    """
    e = persistence_entropy(patch, threshold_rel=threshold_rel)
    return float(1.0 / (1.0 + np.exp(-(e - 1.5))))


def topological_similarity(
    patch_ref: np.ndarray,
    patch_tgt: np.ndarray,
    threshold_rel: float = 0.3,
) -> float:
    """Bottleneck distance between H1 persistence diagrams of two patches.

    Lower values mean the speckle topology is preserved (good track).
    Values > 0.5 suggest decorrelation (out-of-plane motion or large deformation).

    Args:
        patch_ref: reference patch (first frame).
        patch_tgt: target patch (tracked frame).
        threshold_rel: relative threshold for peak detection.

    Returns:
        Bottleneck distance (scalar, >= 0). Returns large value (99.0) on failure.
    """
    if not _HAS_TDA:
        return 0.0

    points_ref = local_maxima_point_cloud(patch_ref, threshold_rel=threshold_rel)
    points_tgt = local_maxima_point_cloud(patch_tgt, threshold_rel=threshold_rel)

    if len(points_ref) < 4 or len(points_tgt) < 4:
        return 99.0  # cannot compare — flag as decorrelated

    try:
        dgms_ref = _ripser.ripser(points_ref, maxdim=1)["diagrams"]
        dgms_tgt = _ripser.ripser(points_tgt, maxdim=1)["diagrams"]
        h1_ref = dgms_ref[1]
        h1_tgt = dgms_tgt[1]
        if len(h1_ref) == 0 and len(h1_tgt) == 0:
            return 0.0
        if len(h1_ref) == 0 or len(h1_tgt) == 0:
            return 99.0
        return float(bottleneck(h1_ref, h1_tgt))
    except Exception:
        return 99.0
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /home/areatu/ECHO2026 && python3 -m pytest tests/unit/test_topological_analysis.py -v 2>&1
```

Expected: 7 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/domain/services/topological_analysis.py \
       tests/unit/test_topological_analysis.py \
       src/echo_personal_tool/domain/models/speckle.py
git commit -m "feat: add topological analysis module (PH-based speckle quality and similarity)"
```

---

### Task 4: Adaptive kernel placement via TDA quality filter

**Files:**
- Modify: `src/echo_personal_tool/domain/services/myocardial_zone.py`
- Test: `tests/unit/test_myocardial_zone.py`

**Interfaces:**
- Consumes: `persistence_score(patch) → float` from Task 3
- Produces: `sample_kernels_in_zone()` — new optional `frames` and `tda_quality_filter` params; kernel placement favours high-PH-score locations

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_myocardial_zone.py`:

```python
def test_sample_kernels_in_zone_tda_filter():
    """TDA quality filter retains only top-k candidates."""
    zone = create_myocardial_zone(
        _make_dummy_contour(num_points=36),
        pixel_spacing=(0.5, 0.5),
        thickness_mm=8.0,
    )
    frames = np.random.rand(10, 200, 200).astype(np.float32)
    kernels = sample_kernels_in_zone(
        zone,
        num_kernels_per_ring=8,
        num_rings=3,
        frames=frames,
        tda_quality_filter=True,
    )
    assert len(kernels) == 8 * 3  # exactly 24
    # All kernels should have valid centers
    for k in kernels:
        assert 0 <= k.center[0] < 200
        assert 0 <= k.center[1] < 200
        assert k.radius == 10
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/areatu/ECHO2026 && python3 -m pytest tests/unit/test_myocardial_zone.py::test_sample_kernels_in_zone_tda_filter -v 2>&1
```

Expected: FAIL — `sample_kernels_in_zone() got unexpected keyword argument 'frames'`

- [ ] **Step 3: Modify `sample_kernels_in_zone`**

Replace the existing function in `myocardial_zone.py`:

```python
def sample_kernels_in_zone(
    zone: MyocardialZone,
    num_kernels_per_ring: int = 32,
    num_rings: int = 3,
    frames: np.ndarray | None = None,
    tda_quality_filter: bool = False,
) -> list[TrackingKernel]:
    """Sample tracking kernels within the myocardial zone.

    When tda_quality_filter=True and frames is provided, generates 3× candidates
    and keeps the top num_kernels_per_ring per ring by topological richness.

    Args:
        zone: MyocardialZone with endo and epi contours.
        num_kernels_per_ring: kernels per ring along the contour.
        num_rings: number of concentric rings (default 3: endo, mid, epi).
        frames: (N, H, W) cine loop — used for PH-based quality scoring.
        tda_quality_filter: if True, use persistence entropy to select best locations.

    Returns:
        List of TrackingKernel instances.
    """
    n_endo = len(zone.endo_points)
    n_epi = len(zone.epi_points)
    n_pts = max(n_endo, n_epi)

    # If TDA filter is active, generate 3× candidates and score them
    if tda_quality_filter and frames is not None and _HAS_TDA:
        return _sample_kernels_with_tda(
            zone, n_endo, n_epi, n_pts,
            num_kernels_per_ring, num_rings,
            frames[0],  # first frame (ED)
        )

    # Original uniform sampling (unchanged)
    kernels: list[TrackingKernel] = []
    for ring in range(num_rings):
        t = ring / max(num_rings - 1, 1)
        for i in range(num_kernels_per_ring):
            idx = int(i * n_pts / num_kernels_per_ring) % n_pts
            endo_idx = int(i * n_endo / num_kernels_per_ring) % n_endo
            epi_idx = int(i * n_epi / num_kernels_per_ring) % n_epi

            pt_endo = zone.endo_points[endo_idx]
            pt_epi = zone.epi_points[epi_idx]
            center = pt_endo + t * (pt_epi - pt_endo)

            layer = "endo" if ring == 0 else ("epi" if ring == num_rings - 1 else "mid")
            kernels.append(
                TrackingKernel(
                    center=(float(center[0]), float(center[1])),
                    radius=10,
                    node_index=idx,
                    layer=layer,
                )
            )
    return kernels


try:
    from echo_personal_tool.domain.services.topological_analysis import persistence_score as _tda_score
    _HAS_TDA = True
except ImportError:
    _HAS_TDA = False


def _sample_kernels_with_tda(
    zone: MyocardialZone,
    n_endo: int,
    n_epi: int,
    n_pts: int,
    num_kernels_per_ring: int,
    num_rings: int,
    reference_frame: np.ndarray,
) -> list[TrackingKernel]:
    """Generate 3× candidates, score by persistence entropy, keep top-N."""
    half_kernel = 6  # 12×12 patch
    candidates_multiplier = 3
    num_candidates = candidates_multiplier * num_kernels_per_ring
    half = (num_candidates - 1) / 2.0

    kernels: list[TrackingKernel] = []

    for ring in range(num_rings):
        t = ring / max(num_rings - 1, 1)
        scored: list[tuple[float, TrackingKernel]] = []

        for i in range(num_candidates):
            idx = int(i * n_pts / num_candidates) % n_pts
            endo_idx = int(i * n_endo / num_candidates) % n_endo
            epi_idx = int(i * n_epi / num_candidates) % n_epi

            pt_endo = zone.endo_points[endo_idx]
            pt_epi = zone.epi_points[epi_idx]
            center = pt_endo + t * (pt_epi - pt_endo)

            cx, cy = int(round(center[0])), int(round(center[1]))
            # Extract patch from reference frame
            x0 = max(0, cx - half_kernel)
            y0 = max(0, cy - half_kernel)
            x1 = min(reference_frame.shape[1], cx + half_kernel)
            y1 = min(reference_frame.shape[0], cy + half_kernel)

            if x1 - x0 < 12 or y1 - y0 < 12:
                score = 0.0
            else:
                patch = reference_frame[y0:y1, x0:x1]
                score = _tda_score(patch)

            layer = "endo" if ring == 0 else ("epi" if ring == num_rings - 1 else "mid")
            kernel = TrackingKernel(
                center=(float(center[0]), float(center[1])),
                radius=10,
                node_index=idx,
                layer=layer,
            )
            scored.append((score, kernel))

        scored.sort(key=lambda x: -x[0])
        kernels.extend(k for _, k in scored[:num_kernels_per_ring])

    return kernels
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /home/areatu/ECHO2026 && python3 -m pytest tests/unit/test_myocardial_zone.py::test_sample_kernels_in_zone_tda_filter -v 2>&1
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/domain/services/myocardial_zone.py
git commit -m "feat: adaptive kernel placement via persistent homology scoring"
```

---

### Task 5: PH-based outlier rejection

**Files:**
- Modify: `src/echo_personal_tool/domain/services/speckle_tracking.py`
- Test: `tests/unit/test_speckle_tracking.py`

**Interfaces:**
- Consumes: `topological_similarity(ref, tgt) → float` from Task 3
- Produces: `track_frame_pair()` — second-stage outlier filter using PH when `config.tda_outlier_rejection=True`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_speckle_tracking.py`:

```python
def test_track_frame_pair_tda_outlier_rejection():
    """TDA outlier rejection filters decorrelated kernels."""
    frame = np.random.rand(100, 100).astype(np.float32)
    kernels = [
        TrackingKernel(center=(50.0, 50.0), radius=10, node_index=0, layer="mid"),
    ]
    config = SpeckleConfig(
        kernel_size=12, search_radius=15, pyramid_levels=1,
        ncc_threshold=0.0,  # accept any NCC
        outlier_sigma=0.0,  # disable MAD filter
        tda_outlier_rejection=True,
        tda_decorrelation_threshold=0.3,
    )
    result = track_frame_pair(frame, frame, kernels, config)
    assert result.valid_mask[0]  # identical frames → good track
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/areatu/ECHO2026 && python3 -m pytest tests/unit/test_speckle_tracking.py::test_track_frame_pair_tda_outlier_rejection -v 2>&1
```

Expected: FAIL — `TrackingKernel() got unexpected keyword argument 'tda_outlier_rejection'` (already fixed in Task 2) or the tracker doesn't use it

- [ ] **Step 3: Implement TDA outlier rejection in `track_frame_pair`**

Add import at top of `speckle_tracking.py`:

```python
try:
    from echo_personal_tool.domain.services.topological_analysis import (
        topological_similarity as _tda_similarity,
    )
    _HAS_TDA = True
except ImportError:
    _HAS_TDA = False
```

Replace the outlier rejection block at the end of `track_frame_pair()` (lines 214-220):

```python
    # First-stage: NCC threshold
    valid_mask = ncc_scores >= config.ncc_threshold

    # Second-stage: MAD-based displacement outlier
    if config.outlier_sigma > 0 and valid_mask.sum() > 3:
        median_disp = np.median(displacements[valid_mask], axis=0)
        mad = np.median(np.abs(displacements[valid_mask] - median_disp), axis=0)
        mad[mad < 0.1] = 0.1
        outlier = np.any(np.abs(displacements - median_disp) > config.outlier_sigma * mad, axis=1)
        valid_mask &= ~outlier

    # Third-stage: TDA topological similarity filter
    if config.tda_outlier_rejection and _HAS_TDA and valid_mask.sum() > 1:
        half = config.kernel_size // 2
        for i in range(n):
            if not valid_mask[i]:
                continue
            # Reference patch at original center
            ref_center = kernels[i].center
            patch_ref = _extract_patch(reference, ref_center[0], ref_center[1], half)
            # Target patch at tracked position
            tgt_x = float(kernel_positions[i, 0])
            tgt_y = float(kernel_positions[i, 1])
            patch_tgt = _extract_patch(target, tgt_x, tgt_y, half)
            if patch_ref is None or patch_tgt is None:
                valid_mask[i] = False
                continue
            sim = _tda_similarity(patch_ref, patch_tgt)
            if sim > config.tda_decorrelation_threshold:
                valid_mask[i] = False

    return TrackingResult(
        frame_index=0,
        displacements=displacements,
        ncc_scores=ncc_scores,
        valid_mask=valid_mask,
        kernel_positions=kernel_positions,
    )
```

Note: also rename `positions` variable to `kernel_positions` near line 201 for clarity (or use `positions` consistently — check existing code):

Actually, the variable is already `positions`. Let me verify:

Looking at the code: line 201: `positions = np.zeros((n, 2), dtype=np.float64)` and line 210: `kernel_positions=positions`. So `positions` is the local variable. Let me use `kernel_positions` for clarity.

Wait, the return already uses `kernel_positions=positions`. Let me adjust:

Change:
```python
    positions = np.zeros((n, 2), dtype=np.float64)
```
to:
```python
    kernel_positions = np.zeros((n, 2), dtype=np.float64)
```

And update all uses. Actually, to keep diff minimal, I'll just use `positions` in the TDA block:

```python
            tgt_x = float(positions[i, 0])
            tgt_y = float(positions[i, 1])
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /home/areatu/ECHO2026 && python3 -m pytest tests/unit/test_speckle_tracking.py::test_track_frame_pair_tda_outlier_rejection -v 2>&1
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/domain/services/speckle_tracking.py
git commit -m "feat: PH-based outlier rejection for decorrelation detection"
```

---

### Task 6: Integration — wire TDA flags through the pipeline

**Files:**
- Modify: `src/echo_personal_tool/application/app_controller.py`
- Modify: `src/echo_personal_tool/application/workers/speckle_worker.py`

- [ ] **Step 1: Read current files**

```bash
cat src/echo_personal_tool/application/app_controller.py | head -30
cat src/echo_personal_tool/application/workers/speckle_worker.py | head -30
```

- [ ] **Step 2: Wire TDA config into `SpeckleConfig` creation in `app_controller.py`**

Find where `SpeckleConfig` is instantiated. Add after existing fields:

```python
config = SpeckleConfig(
    # existing fields...
    tda_quality_filter=settings.get("tda_quality_filter", False),
    tda_outlier_rejection=settings.get("tda_outlier_rejection", False),
    tda_decorrelation_threshold=settings.get("tda_decorrelation_threshold", 0.3),
)
```

- [ ] **Step 3: Pass `frames` to `sample_kernels_in_zone` from `speckle_worker.py`**

Find where `sample_kernels_in_zone()` is called. Add `frames` and `tda_quality_filter`:

```python
kernels = sample_kernels_in_zone(
    zone,
    num_kernels_per_ring=config.num_kernels_per_ring,
    num_rings=config.num_rings,
    frames=frames if config.tda_quality_filter else None,
    tda_quality_filter=config.tda_quality_filter,
)
```

- [ ] **Step 4: Verify no import errors**

```bash
cd /home/areatu/ECHO2026 && python3 -c "from echo_personal_tool.application.app_controller import AppController; print('ok')"
```

Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/application/app_controller.py \
       src/echo_personal_tool/application/workers/speckle_worker.py
git commit -m "feat: wire TDA flags through application layer"
```

---

### Task 7: Run full test suite

- [ ] **Step 1: Run all unit tests**

```bash
cd /home/areatu/ECHO2026 && python3 -m pytest tests/unit/ -v 2>&1
```

Expected: All PASS (including 3 new TDA tests, no regressions)

- [ ] **Step 2: Verify graceful fallback without ripser**

```bash
cd /home/areatu/ECHO2026 && python3 -c "
import sys
sys.modules['ripser'] = None  # simulate missing ripser  
import importlib
import echo_personal_tool.domain.services.topological_analysis
importlib.reload(echo_personal_tool.domain.services.topological_analysis)
from echo_personal_tool.domain.services.topological_analysis import persistence_entropy
import numpy as np
patch = np.random.rand(12, 12).astype(np.float32)
e = persistence_entropy(patch)
print(f'entropy={e} (should be 0.0 without ripser)')
"
```

Expected: `entropy=0.0 (should be 0.0 without ripser)`

- [ ] **Step 3: Commit any fixes**

```bash
git commit -m "test: add TDA fallback verification and full suite pass"
```

---

### Self-Review Checklist

- [ ] **Spec coverage:** Does every requirement from the brainstorm design spec have a corresponding task?
  - Adaptive kernel placement → Task 4 ✓
  - PH outlier rejection → Task 5 ✓
  - Config flags → Task 2 ✓
  - Graceful fallback → Task 3 (try/except) + Task 7 (test) ✓

- [ ] **Placeholder scan:** Any "TBD", "TODO", or "implement later" in the plan? None.

- [ ] **Type consistency:** 
  - `persistence_score` returns `float` → used in Task 4 as comparison value ✓
  - `topological_similarity` returns `float` → used in Task 5 compared to threshold ✓
  - `tda_decorrelation_threshold: float` in Task 2 → used in Task 5 ✓
  - `frames: np.ndarray | None` in Task 4 → `frames[0]` (first frame) passed ✓
