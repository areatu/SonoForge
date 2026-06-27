# Speckle Tracking (2D Strain) — Implementation Plan

**Date:** 2026-06-24
**Status:** Draft
**Scope:** Block-matching speckle tracking, GLS + radial strain, ECG-free cardiac cycle detection

---

## Architecture Overview

```
infrastructure/                 domain/                         presentation/
┌─────────────────┐     ┌──────────────────────┐     ┌──────────────────────┐
│ FrameTimeVector  │────▶│ SpeckleTracker        │────▶│ SpeckleOverlay       │
│ parsing          │     │ (block match + NCC)   │     │ (scatter + colormap) │
└─────────────────┘     └──────────────────────┘     └──────────────────────┘
                              │                              │
                              ▼                              ▼
                        StrainComputer              StrainCurveWidget
                        (GLS, radial,               (PyQtGraph plot +
                         Green-Lagrange)             phase markers)
                              │
                              ▼
                        CardiacCycleDetector
                        (FFT HR + ED/ES auto)
```

All domain services are pure functions operating on `np.ndarray` + dataclasses. No PySide6 imports in domain/.

---

## Phase 1: Core Tracking Engine

### 1.1 Domain Model — `domain/models/speckle.py` (NEW)

```python
@dataclass(frozen=True)
class TrackingKernel:
    center: tuple[float, float]     # (x, y) in pixel coords
    radius: int = 10                # half-size of kernel (20x20 px default)
    node_index: int                 # which contour node this kernel tracks

@dataclass
class TrackingResult:
    frame_index: int
    displacements: np.ndarray       # (N, 2) — dx, dy per kernel (pixels)
    ncc_scores: np.ndarray          # (N,) — NCC confidence per kernel
    valid_mask: np.ndarray          # (N,) — bool, True if NCC > threshold
    kernel_positions: np.ndarray    # (N, 2) — updated (x,y) after tracking

@dataclass(frozen=True)
class SpeckleConfig:
    kernel_size: int = 20           # 20x20 px correlation block
    search_radius: int = 20         # 40x40 px search region
    pyramid_levels: int = 2         # Gaussian pyramid depth
    ncc_threshold: float = 0.5      # minimum NCC to accept match
    outlier_sigma: float = 3.0      # MAD-based outlier rejection (3σ)
    subpixel: bool = True           # parabolic interpolation
```

### 1.2 Core Tracker — `domain/services/speckle_tracking.py` (NEW)

**Key functions:**

```python
def build_gaussian_pyramid(frame: np.ndarray, levels: int) -> list[np.ndarray]
    """Returns list of downsampled frames: [original, 1/2, 1/4, ...]."""

def compute_ncc(kernel: np.ndarray, region: np.ndarray) -> float
    """Normalized cross-correlation between kernel and search region.
    Zero-mean, unit-variance normalization. Returns float in [-1, 1]."""

def block_match_single(
    reference_frame: np.ndarray,
    target_frame: np.ndarray,
    center: tuple[float, float],
    config: SpeckleConfig,
) -> tuple[float, float, float]:
    """Track one kernel from reference→target.
    Uses pyramidal coarse-to-fine: start at top level, refine at each level.
    Returns (dx, dy, ncc_score)."""

def track_frame_pair(
    reference: np.ndarray,
    target: np.ndarray,
    kernels: list[TrackingKernel],
    config: SpeckleConfig,
) -> TrackingResult:
    """Track all kernels from one frame to the next.
    Returns TrackingResult with displacements, NCC scores, valid_mask."""

def track_cine(
    frames: np.ndarray,              # (N, H, W) uint8 or float
    initial_kernels: list[TrackingKernel],
    config: SpeckleConfig,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[TrackingResult]:
    """Track kernels across entire cine loop (frame 0→1→2→...→N-1).
    Returns one TrackingResult per frame transition (N-1 results).
    Uses forward tracking with optional backward validation."""

def refine_subpixel(
    correlation_map: np.ndarray,
    peak: tuple[int, int],
) -> tuple[float, float]:
    """Parabolic interpolation on 3x3 neighborhood around correlation peak.
    Returns sub-pixel displacement offset."""
```

**Algorithm detail — pyramidal block matching:**

1. Build 2-level Gaussian pyramid: `level 0` (original), `level 1` (1/2x)
2. At top level (level 1): coarse search over 40x40 px → find best match by NCC
3. Project displacement down to level 0 (×2), refine in ±4 px neighborhood
4. Sub-pixel refinement via parabolic fit on 3x3 NCC values around peak
5. Accept if NCC ≥ 0.5; mark invalid otherwise

**Performance targets (100 frames, 32 kernels):**
- `compute_ncc`: ~0.01 ms per call (vectorized with numpy slicing)
- `block_match_single`: ~0.5 ms (2 levels × ~25 candidate positions × NCC)
- `track_frame_pair`: ~16 ms (32 kernels × 0.5 ms)
- `track_cine`: ~1.6 s for 100 frames — well within 5s budget

### 1.3 Infrastructure — `infrastructure/dicom_metadata_mapper.py` (MODIFY)

Add FrameTimeVector parsing to `_frame_time_ms`:

```python
def _frame_time_ms(dataset: Dataset) -> float | None:
    # Existing: scalar FrameTime
    # NEW: also parse FrameTimeVector → per-frame timing
    if hasattr(dataset, 'FrameTimeVector'):
        vector = dataset.FrameTimeVector  # numpy array of ms deltas
        return float(np.mean(vector))     # average for strain rate
    ...

def _frame_time_vector(dataset: Dataset) -> list[float] | None:
    """Parse FrameTimeVector → list of per-frame deltas (ms).
    Returns None if tag absent."""
    if not hasattr(dataset, 'FrameTimeVector'):
        return None
    return [float(x) for x in dataset.FrameTimeVector]
```

### 1.4 Domain Model — `domain/models/metadata.py` (MODIFY)

Add optional per-frame timing to `InstanceMetadata`:

```python
@dataclass(frozen=True)
class InstanceMetadata:
    # ... existing fields ...
    frame_time_vector: tuple[float, ...] | None = None  # per-frame ms deltas

    @property
    def effective_frame_time_ms(self) -> float:
        """Returns per-frame timing if available, else scalar frame_time_ms."""
        if self.frame_time_vector:
            return float(np.mean(self.frame_time_vector))
        return self.frame_time_ms or 33.0  # default 30fps
```

### 1.5 Kernel Initialization from Contour

```python
def kernels_from_contour(contour: Contour, pixel_spacing: tuple[float, float]) -> list[TrackingKernel]:
    """Sample tracking kernels along the endocardial border.
    Uses contour.points (32 nodes) as kernel centers.
    Kernel radius = 10 px (half of 20x20)."""

def resample_contour_for_tracking(
    contour: Contour,
    num_kernels: int = 64,
) -> list[TrackingKernel]:
    """Spline-resample contour to uniform spacing for denser tracking.
    Default: 64 kernels along the arc (vs 32 nodes)."""
```

---

## Phase 2: Strain Computation + Cardiac Cycle Detection

### 2.1 Strain Computer — `domain/services/strain_computation.py` (NEW)

```python
def compute_lagrangian_strain(
    reference_positions: np.ndarray,    # (N, 2) at frame 0
    current_positions: np.ndarray,      # (N, 2) at frame t
    reference_length: float,            # initial inter-node distance (mm)
) -> np.ndarray:
    """Green-Lagrange strain: E = 0.5 * ((L/L0)^2 - 1).
    Returns strain per kernel pair (N-1 values)."""

def compute_longitudinal_strain(
    tracking_results: list[TrackingResult],
    kernels: list[TrackingKernel],
    pixel_spacing: tuple[float, float],
    frame_time_vector: list[float] | None = None,
) -> np.ndarray:
    """Compute longitudinal strain curve over time.
    Uses inter-node distances along the arc.
    Returns (num_frames,) array of strain values (%)."""

def compute_radial_strain(
    tracking_results: list[TrackingResult],
    kernels: list[TrackingKernel],
    pixel_spacing: tuple[float, float],
) -> np.ndarray:
    """Compute radial (circumferential) strain from tracking.
    Returns (num_frames,) array of strain values (%)."""

def compute_gls(
    longitudinal_strain: np.ndarray,
    ed_index: int,
    es_index: int,
) -> float:
    """Global Longitudinal Strain: peak negative strain between ED→ES.
    Returns GLS as negative percentage (e.g., -18.5%)."""

def compute_strain_rate(
    strain_curve: np.ndarray,
    frame_times_ms: list[float],
) -> np.ndarray:
    """Time derivative of strain curve. Returns strain rate in %/s."""
```

### 2.2 Cardiac Cycle Detector — `domain/services/cardiac_cycle_detector.py` (NEW)

```python
def estimate_heart_rate_fft(
    frames: np.ndarray,                # (N, H, W)
    roi: np.ndarray | None = None,     # optional myocardial ROI mask
    fps: float = 30.0,
) -> float:
    """Estimate heart rate from mean myocardial intensity over time.
    1. For each frame, compute mean intensity within ROI (or full image)
    2. Apply Hanning window → FFT
    3. Find dominant frequency in 40-200 BPM range
    4. Return HR in BPM."""

def auto_detect_ed_es(
    frames: np.ndarray,
    kernels: list[TrackingKernel],
    tracking_results: list[TrackingResult],
) -> tuple[int, int]:
    """Auto-detect ED and ES frame indices from tissue motion.
    ED = frame with maximum LV area (or maximum mean displacement from centroid).
    ES = frame with minimum LV area (or minimum centroid distance).
    Returns (ed_index, es_index)."""

def detect_cardiac_phases(
    frames: np.ndarray,
    tracking_results: list[TrackingResult],
    heart_rate_bpm: float,
    fps: float,
) -> dict[str, int]:
    """Map all frame indices to cardiac phases.
    Returns dict: {"ED": 0, "ES": 12, "MD": 18, ...} with phase labels."""
```

### 2.3 Kernel Position Tracking Integration

After `track_cine()` produces per-frame displacements, propagate kernel positions:

```python
def propagate_kernel_positions(
    initial_kernels: list[TrackingKernel],
    tracking_results: list[TrackingResult],
) -> np.ndarray:
    """Cumulative positions across all frames.
    Returns (num_frames, num_kernels, 2) array of absolute (x,y) positions."""
```

---

## Phase 3: UI Integration

### 3.1 Speckle Overlay — `presentation/speckle_overlay.py` (NEW)

```python
class SpeckleOverlay(QObject):
    """Renders tracking kernels + displacement vectors on the viewer."""

    def __init__(self, view_box: ContourViewBox): ...

    def show_kernels(
        self,
        kernels: list[TrackingKernel],
        valid_mask: np.ndarray,
        ncc_scores: np.ndarray,
    ) -> None:
        """Draw kernel centers as scatter points, color-coded by NCC quality.
        Green: NCC > 0.8, Yellow: 0.5-0.8, Red: < 0.5."""

    def show_displacements(
        self,
        kernels: list[TrackingKernel],
        displacements: np.ndarray,
        scale: float = 5.0,
    ) -> None:
        """Draw quiver arrows showing displacement direction/magnitude."""

    def show_strain_map(
        self,
        kernels: list[TrackingKernel],
        strain_values: np.ndarray,
    ) -> None:
        """Color-coded strain map along the endocardial border.
        Blue → negative (shortening), Red → positive (stretching)."""

    def clear(self) -> None: ...
```

### 3.2 Strain Curve Widget — `presentation/strain_curve_widget.py` (NEW)

```python
class StrainCurveWidget(QWidget):
    """PyQtGraph plot showing strain curves over the cardiac cycle."""

    def __init__(self, parent=None): ...

    def set_strain_data(
        self,
        time_ms: np.ndarray,
        longitudinal_strain: np.ndarray,
        radial_strain: np.ndarray,
        phases: dict[str, int],
        frame_times_ms: list[float],
    ) -> None:
        """Plot longitudinal (blue) and radial (red) strain curves.
        Vertical dashed lines at ED/ES. GLS annotation on plot."""

    def set_gls_value(self, gls: float) -> None:
        """Display GLS value as text annotation."""

    def clear(self) -> None: ...
```

### 3.3 Viewer Integration — `presentation/viewer_widget.py` (MODIFY)

Add speckle tracking state and controls:

```python
# New signals
speckle_tracking_requested = Signal()
strain_computed = Signal(object)  # StrainResultDTO

# New methods
def _on_speckle_tracking_requested(self) -> None:
    """Get current contour → create kernels → run tracking in worker."""

def _show_speckle_results(self, result: SpeckleTrackingResult) -> None:
    """Update overlay + strain curve widget."""

def toggle_speckle_overlay(self, visible: bool) -> None: ...
```

### 3.4 Application Controller — `application/app_controller.py` (MODIFY)

Add tracking orchestration:

```python
def run_speckle_tracking(
    self,
    contour: Contour,
    config: SpeckleConfig | None = None,
) -> None:
    """Launch SpeckleTrackingWorker in background thread.
    On completion: store results, update viewer overlay + strain widget."""
```

### 3.5 Background Worker — `application/workers/speckle_worker.py` (NEW)

```python
class SpeckleTrackingWorker(QRunnable):
    """Background worker for speckle tracking + strain computation."""

    def __init__(
        self,
        frames: np.ndarray,
        kernels: list[TrackingKernel],
        pixel_spacing: tuple[float, float],
        frame_time_ms: float,
        config: SpeckleConfig,
    ): ...

    def run(self) -> None:
        """Execute tracking → strain → cardiac cycle detection.
        Emit results via signals on main thread."""
```

---

## Phase Integration Points

| Component | Reads from | Writes to |
|-----------|-----------|-----------|
| `speckle_tracking.py` | FrameCache.frames, Contour.points | TrackingResult |
| `strain_computation.py` | TrackingResult, pixel_spacing | StrainCurve |
| `cardiac_cycle_detector.py` | FrameCache.frames, TrackingResult | ED/ES indices, HR |
| `speckle_overlay.py` | TrackingResult, kernels | ViewBox graphics |
| `strain_curve_widget.py` | StrainCurve, phases | PyQtGraph plot |
| `speckle_worker.py` | FrameCache, Contour, config | All results via signals |

---

## File Summary

| # | File | Action | Lines (est.) |
|---|------|--------|--------------|
| 1 | `domain/models/speckle.py` | NEW | ~80 |
| 2 | `domain/services/speckle_tracking.py` | NEW | ~250 |
| 3 | `domain/services/strain_computation.py` | NEW | ~150 |
| 4 | `domain/services/cardiac_cycle_detector.py` | NEW | ~120 |
| 5 | `infrastructure/dicom_metadata_mapper.py` | MODIFY | +15 |
| 6 | `domain/models/metadata.py` | MODIFY | +8 |
| 7 | `presentation/speckle_overlay.py` | NEW | ~200 |
| 8 | `presentation/strain_curve_widget.py` | NEW | ~150 |
| 9 | `presentation/viewer_widget.py` | MODIFY | +40 |
| 10 | `application/app_controller.py` | MODIFY | +30 |
| 11 | `application/workers/speckle_worker.py` | NEW | ~80 |
| 12 | `domain/ports.py` | MODIFY | +8 |
| **Total** | | **8 new, 5 modified** | **~1,130** |

---

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| NCC too low on noisy echo | Adaptive kernel size;降低 ncc_threshold to 0.3 with warning |
| Drift accumulation over 100+ frames | Periodic re-anchoring to contour (re-initialize kernels every 10 frames) |
| Papillary muscle interference | Mask out papillary regions from tracking ROI |
| Frame timing unavailable | Fallback: assume uniform frame_time_ms, warn user |
| Performance on slow machines | Pyramid level 1 (not 2); reduce kernels to 32 |
