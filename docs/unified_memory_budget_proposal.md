# Unified Memory Budget Model (P1.1 #545)

## Current State (Isolated)
1. **Frame Cache & Decode/Render** (`FrameCacheBudget` / `FrameCache`)
   - `ram_cap_bytes`: 8% of available RAM (or fallback 2 GiB).
   - `max_cache_bytes`: Min of `playback_max_cache_mb` (default 64 MiB) and `ram_cap_bytes`.
   - `full_cine_reservation_bytes`: `ram_cap_bytes` (separate ceiling for `require_full_cine`).
   - `DecodeGate`: Bounded by `_DEFAULT_MAX_PENDING_BYTES` (512 MiB) and frame counts.
2. **Comparison** (`ComparisonMemoryBudget` in `study_comparison.py`)
   - `cap_bytes`: Independent ceiling for two decoded comparison frames (pane-based reservation).
   - No integration with `FrameCacheBudget`.
3. **Clinical Memory** (`TabClinicalMemory` in `tab_clinical_memory.py`)
   - RAM-only storage of typed values (studies, manual inputs, heart rates, frame time overrides, strain studies).
   - No explicit byte budget; lifetime tied to tab.
4. **Tracking & Render** (`SpeckleConfig` / `MmodeCalibrationState`)
   - Speckle tracking: `require_full_cine()` checks `_max_full_cine_bytes` (same as `ram_cap_bytes`).
   - Render: Implicitly bound by `FrameCache` or UI thread allocations.

## Proposed Unified Model (P1.1)
Consolidate all memory accounting into `AppServices.unified_budget` (replacing `FrameCacheBudget` and `ComparisonMemoryBudget`).

### 1. UnifiedMemoryBudget Structure
```python
@dataclass(frozen=True)
class UnifiedMemoryBudget:
    """Global concurrent memory accounting for cache, decode, render, and tracking."""

    # Base caps (derived from system RAM)
    ram_cap_bytes: int           # 8% of available RAM (shared pool)

    # Allocation buckets (dynamic, sum <= ram_cap_bytes)
    max_cache_bytes: int         # FrameCache sparse window (formerly FrameCacheBudget.max_cache_bytes)
    full_cine_bytes: int         # Full cine reservation (decode/render/tracking)
    comparison_bytes: int        # Comparison frames (formerly ComparisonMemoryBudget.cap_bytes)
    clinical_bytes: int          # TabClinicalMemory estimated footprint (optional, RAM-only)
    decode_gate_bytes: int       # DecodeGate pending bytes (formerly _DEFAULT_MAX_PENDING_BYTES)

    # Playback tuning (unchanged)
    playback_config: PlaybackConfig

    # Helper: remaining capacity for tracking/render overhead
    @property
    def tracking_render_overhead(self) -> int:
        used = (self.max_cache_bytes + self.full_cine_bytes +
                self.comparison_bytes + self.decode_gate_bytes + self.clinical_bytes)
        return max(0, self.ram_cap_bytes - used)
```

### 2. Integration Points
- **`composition.py`**:
  - Replace `FrameCacheBudget` with `UnifiedMemoryBudget`.
  - `build_app_services` computes `UnifiedMemoryBudget` from `available_ram_bytes` and `preferences`.
  - `FrameCache` initialized with `max_cache_bytes` and `max_full_cine_bytes` from `UnifiedMemoryBudget`.
  - `ComparisonMemoryBudget` instantiated from `UnifiedMemoryBudget.comparison_bytes`.
  - `DecodeGate` initialized with `max_pending_bytes` from `UnifiedMemoryBudget.decode_gate_bytes`.
  - `TabClinicalMemory` footprint estimation (optional) tracked via `UnifiedMemoryBudget.clinical_bytes`.
- **`frame_cache.py`**:
  - `FrameCache` retains `memory_budget` and `full_cine_reservation_bytes` properties but delegates limits to `UnifiedMemoryBudget`.
- **`decode_gate.py`**:
  - `DecodeGate` constructor accepts `max_pending_bytes` from `UnifiedMemoryBudget`.
- **`study_comparison.py`**:
  - `ComparisonMemoryBudget` uses `UnifiedMemoryBudget.comparison_bytes` as `cap_bytes`.
- **`tab_clinical_memory.py`**:
  - Optional: Estimate RAM footprint of `TabClinicalMemory` and report to `UnifiedMemoryBudget`.
- **`speckle.py` / `MmodeCalibrationState`**:
  - Tracking/Render allocations (e.g., `require_full_cine`) check `UnifiedMemoryBudget.full_cine_bytes` and `tracking_render_overhead`.

### 3. Allocation Logic (Proposal)
- **Initial Split** (based on `compute_frame_cache_budget`):
  - `cache_max_bytes`: 50% of `ram_cap_bytes` (default 64 MiB, capped by RAM).
  - `full_cine_bytes`: 40% of `ram_cap_bytes` (default 1 GiB, capped by RAM).
  - `comparison_bytes`: 5% of `ram_cap_bytes` (default 100 MiB, capped by RAM).
  - `decode_gate_bytes`: 5% of `ram_cap_bytes` (default 100 MiB, capped by RAM).
  - `clinical_bytes`: Remaining (estimated, e.g., 1% or fixed overhead).
- **Dynamic Adjustment**:
  - `AppController._tune_playback_cache` adjusts `cache_max_bytes` within `UnifiedMemoryBudget` limits.
  - `ComparisonMemoryBudget.reserve` checks against `UnifiedMemoryBudget.comparison_bytes`.
  - `DecodeGate` checks `pending_bytes` against `UnifiedMemoryBudget.decode_gate_bytes`.
  - `FrameCache.require_full_cine` checks `UnifiedMemoryBudget.full_cine_bytes`.

## Implementation Steps
1. **Define `UnifiedMemoryBudget`** in `composition.py`.
2. **Update `compute_frame_cache_budget`** (rename to `compute_unified_budget`) to return `UnifiedMemoryBudget`.
3. **Update `AppServices`** to hold `unified_budget` instead of `cache_budget`.
4. **Update `build_app_services`** and `in_memory_app_services` to construct `UnifiedMemoryBudget`.
5. **Update `AppController`** to pass `unified_budget` components to `FrameCache`, `DecodeGate`, and `ComparisonMemoryBudget`.
6. **Update `FrameCache`** initialization and `require_full_cine` logic.
7. **Update `DecodeGate`** initialization with `max_pending_bytes` from `UnifiedMemoryBudget`.
8. **Update `study_comparison.py`** to use `UnifiedMemoryBudget.comparison_bytes`.
9. **Update `tab_clinical_memory.py`** (optional) to report footprint.
10. **Update `speckle.py` / `MmodeCalibrationState`** integration (tracking/render overhead).

## Acceptance Criteria
- Unified accounting registers every isolated limit in one place (stage 1), then replaces the isolated enforcers in follow-up slices.
- `AppServices` holds `UnifiedMemoryBudget` and the legacy `cache_budget` view.
- `FrameCache` is sized from the unified budget; `DecodeGate`, `ComparisonMemoryBudget` and `SpeckleTrackingWorker` are the remaining migration points.
- Tracking/Render allocations respect `tracking_render_overhead` once their migration lands.
- Tests and all CI gates pass (P1.1 #545, P1.2 #547).

## Implementation status (stage 1, this PR)

The first slice registers the ceilings in one place without changing playback sizing:

- `AppServices.unified_budget` is the single source of truth; `AppServices.cache_budget`
  is a compatibility view (`FrameCacheBudget.from_unified`).
- `compute_frame_cache_budget` keeps its original RAM-share math;
  `compute_unified_memory_budget` derives the full-cine, comparison and decode-gate
  reservations from the same share.
- `build_app_services` and `in_memory_app_services` construct `FrameCache` from the
  unified budget; `FrameCache` exposes `set_full_cine_reservation_bytes` plus the
  M-mode calibration hooks, and `AppController._tune_playback_cache` applies the
  full-cine reservation when services are attached.
- `AppController` forwards M-mode time/state calibration changes to `FrameCache`
  (P1.2 #547) while the 200-line/1 500-line ratchets keep the god object from growing.

Follow-up slices enforce `comparison_bytes` in `ComparisonMemoryBudget`,
`decode_gate_bytes` in `DecodeGate`, and the tracking/render headroom in
`SpeckleTrackingWorker`. The legacy caps stay intact until those consumers are
migrated, so the existing playback/prefetch and bench contracts do not regress.

## Notes
- `TabClinicalMemory` footprint estimation is optional for P1.1 but recommended for completeness.
- `ComparisonMemoryBudget` should be instantiated in `AppController` or `StudyComparisonService` using `UnifiedMemoryBudget.comparison_bytes`.
- `DecodeGate` should be initialized in `AppController` with `UnifiedMemoryBudget.decode_gate_bytes`.
- `FrameCache` should be initialized in `build_app_services` with `UnifiedMemoryBudget.max_cache_bytes` and `UnifiedMemoryBudget.full_cine_bytes`.
