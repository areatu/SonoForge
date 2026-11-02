# Vessel PSV/EDV: ECG-free cycle averaging + artifact-safe median + manual PSV correction

Date: 2026-08-05

## Problem

The "Average 3 cycles" vessel button is bound to an embedded ECG waveform.
Routine vessel Doppler is performed **without** ECG, so the button fails with
"no ECG cycles available for averaging" for the common case. Additionally,
when an artifact corrupts one cycle, the current arithmetic mean is skewed by
it, and EDV is taken as a single envelope point (sensitive to spectral
discretization gaps).

## Goals

1. **ECG-free cycle detection** — derive cardiac cycles from the spectral
   envelope velocity profile itself (peaks = systoles), so averaging works
   without ECG and also when ECG cycles are weak.
2. **Artifact-safe averaging** — PSV/EDV = **median** across cycles, not the
   arithmetic mean.
3. **Clinically-correct EDV** — end-diastolic velocity just before the next
   systolic upstroke, averaged over a small window preceding it (smooths
   vertical spectral bands / discretization gaps).
4. **Manual PSV correction mode** — after averaging, a cycle-selection mode
   lets the diagnostician pick a cycle with `←`/`→` and assign its peak as the
   new PSV (`Enter`), per ASE/AIUM practice of re-measuring on a clean beat.

## Design

Architecture option A: extend the existing service/presentation layer.

### 1. ECG-free cycle detection (`cardiac_cycle_service.py`)

New pure function:

```python
def detect_cycles_from_envelope(
    times_ms: np.ndarray,
    velocities: np.ndarray,
    *,
    max_cycles: int = 5,
    min_peak_prominence: float = 0.15,
) -> list[CardiacCycle]
```

- Uses `scipy.signal.find_peaks` on the velocity profile (each heartbeat
  produces a clear systolic peak).
- `prominence >= 15%` of (max − min) velocity; minimum peak distance ~300 ms
  (guards against noise/extra false peaks in tachycardia).
- Builds `CardiacCycle(..., source="envelope")` with `start_ms`/`end_ms` from
  the surrounding peaks.
- Flat/weak profiles → `[]`.

**Fallback in `CardiacCycleService.get_cycles`:** when the ECG is absent, the
R-peaks are weak, or correlation is below threshold — call
`detect_cycles_from_envelope(times, signal)` instead of returning `[]`. This
makes `_doppler_cardiac_cycles` (viewer_widget.py:2347) return cycles without
ECG.

### 2. EDV via adaptive window before systolic upstroke

New pure function in `cardiac_cycle_service.py`:

```python
def _edv_idx_before_upstroke(
    times: np.ndarray,
    ys: np.ndarray,
    cycle: CardiacCycle,
    psv_idx: int,
) -> int
```

Replaces the single-point EDV in `_snap_in_cycle`:

1. **Diastolic minimum candidate** — as today: `argmax(ys)` within the last
   25% of the cycle (clinically the point just before the next upstroke).
2. **EDV window** — average envelope values over a window **before** the
   minimum (backward in time, ~30 ms or up to 10 points), truncated to the
   cycle start. This smooths vertical spectral bands / discretization gaps.
   If the window has < 2 points, fall back to the single minimum point.

EDV value = window average; the EDV marker is placed at the window's midpoint
in time. Applies to `_snap_in_cycle`, `derive_psv_edv_indices_with_cycles`,
and `derive_psv_edv_indices_per_cycle`.

### 3. Median averaging (`doppler_overlay.py::apply_averaged_vessel`)

- Replace `sum(psv_values)/len` with `statistics.median`.
- PSV/EDV markers: median velocity values; marker time from the first cycle
  (as today).
- `apply_averaged_vessel` also returns the cycle list and per-cycle peak
  velocity candidates (for the correction mode) alongside `(psv, edv)`.

### 4. Manual PSV correction mode (`viewer_widget.py` + `doppler_overlay.py`)

- New overlay state: `_vessel_cycles`, `_vessel_cycle_psv_candidates`,
  `_vessel_cycle_index`, `_vessel_cycle_selection`.
- Mode activates **automatically** after successful averaging.
- **Visualization:** semi-transparent vertical band between the selected
  cycle's `start_ms`/`end_ms`; label shows the candidate peak
  (`PSV кандидат: XX cm/s`).
- **Keys** (`keyPressEvent`, viewer_widget.py:6270):
  - `←`/`→` — move `_vessel_cycle_index`; update band + candidate.
  - `Enter` — assign candidate as the new PSV, exit mode, proceed to accept.
  - `ESC` — exit mode without changing PSV (median PSV stays).
- Outside the mode, `←`/`→` scroll frames as usual.

### 5. Error handling / edge cases

- 1 cycle → averaging works (median = its value); correction mode works too.
- No peaks (flat profile) → `[]` → `apply_averaged_vessel` returns `None` →
  existing `viewer.vessel_average_failed` label. No crash.
- Too-short/sparse cycles → skipped by `derive_psv_edv_indices_per_cycle`.
- EDV window truncated at cycle start; < 2 points → fallback to minimum.
- Frame/instance switch during mode → `clear_measurements`/`clear_vessel`
  reset the mode state (no stuck mode).
- On accept: `averaged_cycles` and `cycle_source` saved — now
  `"envelope"` or `"ecg"` depending on the cycle source.

## Testing

**Unit (`cardiac_cycle_service.py`):**
1. `detect_cycles_from_envelope` — synthetic pulsatile profile → expected cycle
   count; flat profile → `[]`; noisy profile → peaks found with min distance.
2. `_edv_idx_before_upstroke` — diastolic plateau → window average before
   upstroke (not a single point); window at cycle edge → truncated; window
   < 2 points → fallback to minimum.
3. `CardiacCycleService.get_cycles` without ECG → returns envelope cycles.
4. Median: averaging with an artifact spike in one cycle → median not skewed.

**Correction mode (Qt, `test_viewer_widget.py` / `test_presentation_doppler_overlay.py`):**
5. After averaging `_vessel_cycle_selection == True`, cycles + candidates set.
6. `←`/`→` change `_vessel_cycle_index` and the highlight.
7. `Enter` assigns the candidate as PSV, exits mode, proceeds to accept.
8. `ESC` exits mode without changing PSV.
9. Frame switch / `clear_measurements` resets the mode.

**Regression:** update existing averaging tests (mean → median, EDV → window
average). Run doppler/viewer/main-window suites + ruff.
