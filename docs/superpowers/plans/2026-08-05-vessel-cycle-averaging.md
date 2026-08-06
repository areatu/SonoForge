# Vessel PSV/EDV ECG-free Cycle Averaging + Manual PSV Correction — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make vessel PSV/EDV averaging work without ECG (cycles derived from the spectral envelope), make it artifact-safe (median instead of mean), make EDV a window-average before the next systolic upstroke, and add a manual PSV correction mode (`←`/`→` to pick a cycle, `Enter` to assign its peak).

**Architecture:** Extend the existing domain/presentation layer (option A). New pure functions live in `domain/services/cardiac_cycle_service.py` (`detect_cycles_from_envelope`, `_edv_window_indices`, `_edv_idx_before_upstroke`) and the snapping functions are extended to carry the window-average EDV value. `presentation/doppler_overlay.py` switches to median and stores per-cycle PSV candidates plus the cycle list; `presentation/viewer_widget.py` handles the correction-mode keys and labels. No new modules.

**Tech Stack:** Python 3.11, numpy, scipy (`scipy.signal.find_peaks`, already a dependency `scipy>=1.11`), PySide6 + pyqtgraph (Qt), pytest/pytest-qt.

## Global Constraints

- `CardiacCycle` is a frozen dataclass `CardiacCycle(start_ms, end_ms, r_peak_ms, ed_ms, es_ms, source, confidence, rr_ms=None)`; `source` is `"ecg"` or `"envelope"`.
- Existing constants to keep: `_CYCLE_EDV_FRACTION = 0.25`, `_MIN_CYCLE_POINTS = 3`, `_MIN_PROFILE_SAMPLES = 5`. New constants: `_MIN_PEAK_DISTANCE_MS = 300.0`, `_EDV_WINDOW_MS = 30.0`, `_EDV_WINDOW_MAX_POINTS = 10`.
- `DopplerAxisMapping.time_ms_from_x` / `x_from_time_ms` / `velocity_cm_s_from_y` / `y_from_velocity_cm_s` are the only unit-conversion entry points; `velocity_cm_s_from_y` is affine, so `velocity_cm_s_from_y(mean(y)) == mean(velocity_cm_s_from_y(y))`.
- `get_cycles` returns homogeneous-source cycles per call (`"ecg"` XOR `"envelope"`), never mixed.
- ruff: `line-length = 120`, `select = ["E","F","I","UP"]`, `ignore = ["F821","E402","F841","E501","UP042","E741"]`.
- pytest: `addopts = "-q -m 'not interactive'"`, timeout 60s, `gui` marker used by Qt tests.
- Run Python via `.venv/bin/python`, ruff via `.venv/bin/ruff`.
- Known pre-existing failures NOT caused by this feature (do not "fix" them): `tests/unit/test_doppler_axis.py::TestDopplerAxisMappingDefaults::test_poc_default`, `tests/unit/test_measurement_tools_panel.py` (hardcoded `/tmp/test.dcm`), and full-suite-in-one-process Qt segfault (run test files/classes, not the whole `tests/unit` directory in one go).
- Russian UI literals inside `doppler_overlay.py` are the established pattern (`_build_vessel_text` already emits `"Проверьте точки"`); new on-plot labels are literals, viewer labels go through `tr()` with keys added to BOTH `ru.json` and `en.json` (parity enforced by `tests/unit/test_i18n.py::test_locale_key_parity`).

---

### Task 1: ECG-free cycle detection (`detect_cycles_from_envelope` + `get_cycles` fallback)

**Files:**
- Modify: `src/echo_personal_tool/domain/services/cardiac_cycle_service.py` (add function at module level after `_snap_in_cycle`; restructure `get_cycles`, lines 226-297)
- Modify: `src/echo_personal_tool/presentation/viewer_widget.py:2321-2353` (`_doppler_cardiac_cycles`)
- Test: `tests/unit/test_cardiac_cycle_service.py`

**Interfaces:**
- Consumes: `CardiacCycle`, `np.ndarray`, `scipy.signal.find_peaks`.
- Produces:
  ```python
  def detect_cycles_from_envelope(
      times_ms: np.ndarray,
      velocities: np.ndarray,
      *,
      max_cycles: int = 5,
      min_peak_prominence: float = 0.15,
  ) -> list[CardiacCycle]
  ```
  Returns `CardiacCycle(..., source="envelope", confidence=1.0)` cycles spanning consecutive systolic peaks; `[]` for flat/weak/malformed input. `get_cycles` now falls back to envelope cycles when the ECG is absent/unusable, returning `"envelope"`-source cycles instead of `[]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_cardiac_cycle_service.py` (module level, after `_synthetic_profile`):

```python
def _pulsatile_profile(
    peaks_ms: tuple[float, ...] = (500.0, 1500.0),
    span_ms: float = 2000.0,
    n: int = 400,
    sigma: float = 60.0,
    noise_peaks_ms: tuple[float, ...] = (),
) -> tuple[np.ndarray, np.ndarray]:
    t = np.linspace(0.0, span_ms, n)
    vel = np.zeros(n)
    for center in peaks_ms:
        vel += np.exp(-0.5 * ((t - center) / sigma) ** 2)
    for center in noise_peaks_ms:
        vel += 0.05 * np.exp(-0.5 * ((t - center) / sigma) ** 2)
    return t, vel


class TestDetectCyclesFromEnvelope:
    def test_detects_cycles_from_pulsatile_profile(self) -> None:
        t, vel = _pulsatile_profile()
        cycles = detect_cycles_from_envelope(t, vel)
        assert len(cycles) == 1
        cycle = cycles[0]
        assert cycle.source == "envelope"
        assert cycle.start_ms == pytest.approx(500.0, abs=20.0)
        assert cycle.end_ms == pytest.approx(1500.0, abs=20.0)
        assert cycle.rr_ms == pytest.approx(1000.0, abs=40.0)
        assert cycle.confidence == 1.0

    def test_flat_profile_returns_empty(self) -> None:
        t = np.linspace(0.0, 2000.0, 400)
        assert detect_cycles_from_envelope(t, np.full(400, 0.5)) == []

    def test_filters_close_peaks_by_min_distance(self) -> None:
        t, vel = _pulsatile_profile(peaks_ms=(500.0, 600.0, 1500.0))
        cycles = detect_cycles_from_envelope(t, vel)
        assert len(cycles) == 1
        assert cycles[0].end_ms == pytest.approx(1500.0, abs=20.0)

    def test_filters_small_prominence_noise(self) -> None:
        t, vel = _pulsatile_profile(peaks_ms=(500.0, 1500.0), noise_peaks_ms=(1000.0,))
        assert len(detect_cycles_from_envelope(t, vel)) == 1

    def test_respects_max_cycles(self) -> None:
        t, vel = _pulsatile_profile(peaks_ms=(400.0, 900.0, 1400.0, 1900.0), span_ms=2400.0)
        assert len(detect_cycles_from_envelope(t, vel, max_cycles=2)) == 2

    def test_mismatched_sizes_returns_empty(self) -> None:
        t = np.linspace(0.0, 2000.0, 400)
        assert detect_cycles_from_envelope(t, np.ones(200)) == []
```

Update the import block at the top of the file to include `detect_cycles_from_envelope`.

Replace `TestGetCycles.test_returns_empty_without_ecg` (currently lines 119-128):

```python
    def test_falls_back_to_envelope_without_ecg(self) -> None:
        t, profile = _synthetic_profile()
        cycles = CardiacCycleService().get_cycles(
            ecg=None,
            spectrogram_time_axis_ms=t,
            fallback_signal=profile,
        )
        assert len(cycles) >= 1
        assert all(c.source == "envelope" for c in cycles)
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_cardiac_cycle_service.py::TestDetectCyclesFromEnvelope tests/unit/test_cardiac_cycle_service.py::TestGetCycles::test_falls_back_to_envelope_without_ecg -v`
Expected: FAIL with `ImportError: cannot import name 'detect_cycles_from_envelope'`.

- [ ] **Step 3: Implement `detect_cycles_from_envelope` + `get_cycles` fallback**

In `src/echo_personal_tool/domain/services/cardiac_cycle_service.py`, add constants after `_MIN_CYCLE_POINTS`:

```python
_MIN_PEAK_DISTANCE_MS = 300.0
```

Add this function after `_snap_in_cycle` (i.e. before `derive_psv_edv_indices_with_cycles`):

```python
def detect_cycles_from_envelope(
    times_ms: np.ndarray,
    velocities: np.ndarray,
    *,
    max_cycles: int = 5,
    min_peak_prominence: float = 0.15,
) -> list[CardiacCycle]:
    """Detect cardiac cycles from the spectral envelope velocity profile.

    Each heartbeat produces a clear systolic peak, so cycles can be derived
    without any ECG. Peaks are found with :func:`scipy.signal.find_peaks`
    using a prominence floor of ``min_peak_prominence`` of the velocity range
    and a minimum peak distance of 300 ms. A cycle spans two consecutive
    peaks (mirroring the ECG-derived cycles). Flat/weak/malformed profiles
    yield ``[]``.
    """
    from scipy.signal import find_peaks

    times = np.asarray(times_ms, dtype=np.float64)
    velocities = np.asarray(velocities, dtype=np.float64)
    if times.ndim != 1 or velocities.ndim != 1 or times.size != velocities.size:
        return []
    if times.size < _MIN_PROFILE_SAMPLES:
        return []
    if np.isnan(velocities).any():
        return []

    order = np.argsort(times, kind="stable")
    times = times[order]
    velocities = velocities[order]

    if np.nanstd(velocities) <= 1e-9:
        return []
    span = float(np.max(velocities)) - float(np.min(velocities))
    if span <= 1e-9:
        return []

    dts = np.diff(times)
    sample_ms = float(np.median(dts)) if dts.size else 0.0
    min_distance = max(1, int(round(_MIN_PEAK_DISTANCE_MS / sample_ms))) if sample_ms > 0 else 1
    peaks, _ = find_peaks(velocities, prominence=min_peak_prominence * span, distance=min_distance)
    if peaks.size < 2:
        return []

    cycles: list[CardiacCycle] = []
    for i in range(peaks.size - 1):
        start = float(times[peaks[i]])
        end = float(times[peaks[i + 1]])
        rr = end - start
        cycles.append(
            CardiacCycle(
                start_ms=start,
                end_ms=end,
                r_peak_ms=start,
                ed_ms=end,
                es_ms=start + 0.35 * rr,
                source="envelope",
                confidence=1.0,
                rr_ms=rr,
            )
        )
        if len(cycles) >= max_cycles:
            break
    return cycles
```

Rewrite `CardiacCycleService.get_cycles` (replaces the body at lines 226-297) so every "ECG unusable" path falls back to the envelope instead of returning `[]`:

```python
    def get_cycles(
        self,
        *,
        ecg: EcgWaveform | None,
        spectrogram_time_axis_ms: np.ndarray | None = None,
        fallback_signal: np.ndarray | None = None,
        max_shift_ms: float = 1500.0,
    ) -> list[CardiacCycle]:
        """Return cardiac cycles in the spectrogram's local ms domain.

        Cycles come from the ECG R-peak train when a usable ECG is present
        and aligns to the fallback signal; otherwise they are derived from the
        envelope velocity profile itself (``source="envelope"``) so averaging
        works without ECG. Returns an empty list only when no signal is
        available or it carries no detectable peaks.
        """
        if spectrogram_time_axis_ms is None or fallback_signal is None:
            return []

        times = np.asarray(spectrogram_time_axis_ms, dtype=np.float64)
        signal = np.asarray(fallback_signal, dtype=np.float64)
        if times.ndim != 1 or signal.ndim != 1 or times.size != signal.size:
            return []
        if times.size < _MIN_PROFILE_SAMPLES:
            return []

        if ecg is None:
            return detect_cycles_from_envelope(times, signal)

        lead_data = primary_ecg_signal(ecg)
        if lead_data is None:
            return detect_cycles_from_envelope(times, signal)
        voltage, fs = lead_data

        r_peak_result = detect_r_peaks(voltage, fs)
        if len(r_peak_result.r_peak_indices) < 2:
            return detect_cycles_from_envelope(times, signal)
        if r_peak_result.confidence < _CYCLE_CONFIDENCE_THRESHOLD:
            return detect_cycles_from_envelope(times, signal)

        alignment = align_spectrogram_to_ecg(
            ecg,
            times,
            signal,
            max_shift_ms=max_shift_ms,
            r_peak_result=r_peak_result,
        )
        if alignment is None:
            return detect_cycles_from_envelope(times, signal)

        t0, t1 = float(np.min(times)), float(np.max(times))
        local_peaks = r_peak_result.r_peak_times_ms - alignment.offset_ms
        rr_intervals = r_peak_result.rr_intervals_ms

        cycles: list[CardiacCycle] = []
        for i, peak_local in enumerate(local_peaks):
            if i + 1 >= len(local_peaks):
                break
            next_local = float(local_peaks[i + 1])
            rr = float(rr_intervals[i]) if i < len(rr_intervals) else next_local - float(peak_local)
            start = max(float(peak_local), t0)
            end = min(next_local, t1)
            if end - start < 1.0:
                continue
            cycles.append(
                CardiacCycle(
                    start_ms=start,
                    end_ms=end,
                    r_peak_ms=float(peak_local),
                    ed_ms=float(peak_local),
                    es_ms=float(peak_local) + 0.35 * rr,
                    source="ecg",
                    confidence=min(float(r_peak_result.confidence), float(alignment.confidence)),
                    rr_ms=rr,
                )
            )
        return cycles
```

Also update the module docstring first line from "A single service that turns an ECG waveform (and, optionally, a spectral fallback signal) into..." to:

```python
"""Cardiac cycle detection with ECG-to-spectrogram time alignment.

A single service that turns an ECG waveform or, when the ECG is absent or
unusable, the spectral envelope itself into a list of
:class:`CardiacCycle` boundaries expressed in the spectrogram's local
millisecond domain. Used by the vessel Doppler auto-trace to snap PSV/EDV to
real cardiac cycles instead of relying on the raw ROI edges.
"""
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_cardiac_cycle_service.py -v`
Expected: PASS (all of `TestAlignSpectrogramToEcg`, `TestGetCycles` incl. the renamed fallback test, `TestDetectCyclesFromEnvelope`).

- [ ] **Step 5: Let the fallback reach the viewer**

In `src/echo_personal_tool/presentation/viewer_widget.py`, replace `_doppler_cardiac_cycles` (lines 2321-2353) — remove the `if ecg is None: return ()` early return and pass `ecg` (possibly `None`) into `get_cycles`:

```python
    def _doppler_cardiac_cycles(
        self,
        envelope: tuple[tuple[float, float], ...],
    ) -> tuple[object, ...]:
        """Build cardiac cycles aligned to the envelope's local time axis.

        Uses the ECG R-peak train when available; otherwise falls back to
        cycles detected from the envelope velocity profile itself.
        """
        instance = self._current_instance_metadata()
        if instance is None or instance.path is None:
            return ()
        from echo_personal_tool.infrastructure.dicom_session import read_ecg_waveform

        try:
            ecg = read_ecg_waveform(instance.path)
        except Exception:  # noqa: BLE001
            ecg = None
        from echo_personal_tool.domain.services.cardiac_cycle_service import (
            CardiacCycleService,
        )

        mapping = self._doppler.axis_mapping()
        times_ms = np.array([mapping.time_ms_from_x(p[0]) for p in envelope], dtype=np.float64)
        velocities = np.array(
            [mapping.velocity_cm_s_from_y(p[1]) for p in envelope],
            dtype=np.float64,
        )
        return tuple(
            CardiacCycleService().get_cycles(
                ecg=ecg,
                spectrogram_time_axis_ms=times_ms,
                fallback_signal=velocities,
            )
        )
```

Run the auto-trace viewer tests to confirm nothing regressed:
Run: `.venv/bin/python -m pytest tests/unit/test_presentation_viewer_widget.py::TestVesselAutoTrace -v`
Expected: PASS (the synthetic test frames produce an envelope whose peaks, if any, still yield a `"done"` vessel state).

- [ ] **Step 6: Commit**

```bash
git add src/echo_personal_tool/domain/services/cardiac_cycle_service.py src/echo_personal_tool/presentation/viewer_widget.py tests/unit/test_cardiac_cycle_service.py
git commit -m "feat(doppler): ECG-free cardiac cycle detection from envelope"
```

---

### Task 2: EDV as an adaptive window before the systolic upstroke

**Files:**
- Modify: `src/echo_personal_tool/domain/services/cardiac_cycle_service.py` (`_edv_window_indices`, `_edv_idx_before_upstroke`, `_snap_in_cycle`, `derive_psv_edv_indices_with_cycles`, `derive_psv_edv_indices_per_cycle`)
- Modify: `src/echo_personal_tool/presentation/doppler_overlay.py` (`apply_auto_trace` lines 461-488, `apply_averaged_vessel` lines 573-584) — minimal adaptation to the new return shapes
- Test: `tests/unit/test_cardiac_cycle_service.py`

**Interfaces:**
- Consumes: `CardiacCycle`, `_CYCLE_EDV_FRACTION`.
- Produces:
  ```python
  def _snap_in_cycle(times, ys, cycle, *, below_baseline=False) -> tuple[int, int, float] | None
      # (psv_idx, edv_idx, edv_value) — edv_value in the same units as ys (window mean)
  def derive_psv_edv_indices_with_cycles(...) -> tuple[int, int, float] | None
  def derive_psv_edv_indices_per_cycle(...) -> list[tuple[int, int, float, int]]
      # (psv_idx, edv_idx, edv_value, cycle_index)
  def _edv_idx_before_upstroke(times, ys, cycle, psv_idx) -> int   # marker index
  def _edv_window_indices(times, min_idx, *, min_time, window_ms=30.0, max_window_points=10) -> tuple[tuple[int, ...], int]
      # (window_indices, midpoint_idx)
  ```
  EDV marker index is the window midpoint; `edv_value` is the window mean (or the single minimum when the window has < 2 points). Window walks backward from the diastolic minimum, ≤ 30 ms or ≤ 10 points, never before `max(eff_start, times[psv_idx])`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_cardiac_cycle_service.py` (extend the import block to include the private helpers `_edv_idx_before_upstroke`, `_edv_window_indices`, `_snap_in_cycle`):

```python
class TestEdvWindow:
    def test_window_indices_truncated_at_min_time(self) -> None:
        times = np.arange(0.0, 2000.0)
        window, midpoint_idx = _edv_window_indices(
            times, 1200, min_time=1180.0, window_ms=100.0, max_window_points=100
        )
        assert window[0] == 1180
        assert window[-1] == 1200
        assert midpoint_idx == 1190

    def test_edv_before_upstroke_plateau_uses_midpoint(self) -> None:
        times = np.arange(0.0, 2000.0, 1.0)
        ys = np.full(2000, 50.0)
        ys[1000:1100] = 10.0
        ys[1100:2000] = 90.0
        cycle = CardiacCycle(0.0, 2000.0, 0.0, 0.0, 2000.0, "ecg", 0.9)
        idx = _edv_idx_before_upstroke(times, ys, cycle, 1000)
        # diastolic min at t=1500; 10-point window midpoint lands before it
        assert times[idx] != 1500.0
        assert 1470.0 <= times[idx] <= 1500.0

    def test_edv_before_upstroke_sparse_falls_back_to_minimum(self) -> None:
        times = np.arange(0.0, 2000.0, 200.0)
        ys = np.array([70.0, 60, 45, 30, 18, 8, 30, 55, 68, 62])
        cycle = CardiacCycle(0.0, 2000.0, 0.0, 0.0, 2000.0, "ecg", 0.9)
        assert _edv_idx_before_upstroke(times, ys, cycle, 5) == 8

    def test_snap_in_cycle_returns_edv_value(self) -> None:
        times = np.arange(0.0, 2000.0, 200.0)
        ys = np.array([70.0, 60, 45, 30, 18, 8, 30, 55, 68, 62])
        cycle = CardiacCycle(0.0, 2000.0, 0.0, 0.0, 2000.0, "ecg", 0.9)
        assert _snap_in_cycle(times, ys, cycle) == (5, 8, 68.0)

    def test_derived_edv_is_window_midpoint_and_mean(self) -> None:
        mapping = _time_mapping(2000.0)
        times = np.arange(0.0, 2000.0, 10.0)
        ys = np.full(200, 50.0)
        ys[50:100] = 10.0
        ys[125:] = 70.0
        envelope = tuple((t * 0.5, y) for t, y in zip(times, ys))
        cycle = CardiacCycle(0.0, 2000.0, 0.0, 0.0, 2000.0, "ecg", 0.9)
        psv_idx, edv_idx, edv_value = derive_psv_edv_indices_with_cycles(
            envelope, (cycle,), mapping
        )
        assert psv_idx == 50
        assert edv_idx != 150  # not the raw minimum (t=1500)
        assert edv_value == pytest.approx(70.0)
        # window spans t=1470..1500, midpoint t=1485, nearest sample is 1480/1490
        assert 1470.0 <= times[edv_idx] <= 1500.0
```

Update the two existing derive tests to the new return shapes:

`TestDerivePsvEdvIndicesWithCycles.test_snaps_edv_to_selected_cycle_diastole` (lines 184-188) becomes:

```python
        psv_idx, edv_idx, edv_value = derive_psv_edv_indices_with_cycles(envelope, cycles, mapping)
        # PSV at time 1000 (y=8); EDV in last 25% of the SAME cycle (y=68 at t=1600),
        # not the global end-of-envelope minimum velocity (y=95 at t=3600).
        assert psv_idx == 5
        assert edv_idx == 8
        assert edv_value == pytest.approx(68.0)
```

`TestDerivePsvEdvIndicesPerCycle.test_returns_snapped_indices_per_cycle` (lines 226-231) becomes:

```python
        per_cycle = derive_psv_edv_indices_per_cycle(envelope, cycles, mapping)
        assert len(per_cycle) == 2
        # cycle 0: PSV at t=1000 (idx 5), EDV at t=1600 (idx 8), value 68
        assert per_cycle[0] == (5, 8, 68.0, 0)
        # cycle 1: PSV at t=2200 (idx 11), EDV at t=3600 (idx 18), value 95
        assert per_cycle[1] == (11, 18, 95.0, 1)
```

`TestDerivePsvEdvIndicesPerCycle.test_skips_sparse_cycles` (lines 240-246) becomes:

```python
        per_cycle = derive_psv_edv_indices_per_cycle(envelope, cycles, mapping)
        assert len(per_cycle) == 1
        assert per_cycle[0] == (0, 9, 9.0, 1)
```

- [ ] **Step 2: Run the new/updated tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_cardiac_cycle_service.py::TestEdvWindow -v`
Expected: FAIL with `ImportError: cannot import name '_edv_window_indices'`.

- [ ] **Step 3: Implement the EDV window in the domain layer**

In `src/echo_personal_tool/domain/services/cardiac_cycle_service.py`, add constants after `_MIN_PEAK_DISTANCE_MS`:

```python
_EDV_WINDOW_MS = 30.0
_EDV_WINDOW_MAX_POINTS = 10
```

Replace the whole `_snap_in_cycle` function (lines 130-160) and add the two new helpers just above it:

```python
def _edv_window_indices(
    times: np.ndarray,
    min_idx: int,
    *,
    min_time: float,
    window_ms: float = _EDV_WINDOW_MS,
    max_window_points: int = _EDV_WINDOW_MAX_POINTS,
) -> tuple[tuple[int, ...], int]:
    """Return ``(window_indices, midpoint_idx)`` for the EDV averaging window.

    The window ends at *min_idx* (the diastolic minimum) and walks backward in
    time, collecting at most ``window_ms`` ms or ``max_window_points`` points
    and never before *min_time*. *midpoint_idx* is the envelope index nearest
    the window's midpoint in time.
    """
    window = [int(min_idx)]
    t_min = float(times[min_idx])
    for i in range(min_idx - 1, -1, -1):
        if float(times[i]) < min_time:
            break
        if t_min - float(times[i]) > window_ms or len(window) >= max_window_points:
            break
        window.append(i)
    window.sort()
    mid_t = (float(times[window[0]]) + float(times[window[-1]])) * 0.5
    midpoint_idx = int(np.argmin(np.abs(times - mid_t)))
    return tuple(window), midpoint_idx


def _edv_idx_before_upstroke(
    times: np.ndarray,
    ys: np.ndarray,
    cycle: CardiacCycle,
    psv_idx: int,
) -> int:
    """Index of the EDV marker just before the next systolic upstroke.

    Locates the diastolic minimum (maximum plot-y in the last quarter of the
    cycle) and returns the midpoint index of the adaptive averaging window
    ending there (backward, ≤ 30 ms / 10 points, truncated to the cycle start
    and to the PSV). Falls back to the minimum index when the window holds
    fewer than two points.
    """
    t_lo, t_hi = float(np.min(times)), float(np.max(times))
    eff_start = max(float(cycle.start_ms), t_lo)
    eff_end = min(float(cycle.end_ms), t_hi)
    if eff_end - eff_start < 1.0:
        return int(np.argmax(ys))
    span = eff_end - eff_start
    edv_search_start = eff_start + (1.0 - _CYCLE_EDV_FRACTION) * span
    in_cycle = (times >= eff_start) & (times <= eff_end)
    in_diastole = in_cycle & (times >= edv_search_start)
    if int(in_diastole.sum()) == 0:
        in_diastole = in_cycle
    diastole_indices = np.nonzero(in_diastole)[0]
    edv_min_idx = int(diastole_indices[int(np.argmax(ys[diastole_indices]))])
    min_time = max(eff_start, float(times[psv_idx]))
    window, midpoint_idx = _edv_window_indices(times, edv_min_idx, min_time=min_time)
    if len(window) < 2:
        return edv_min_idx
    return midpoint_idx


def _snap_in_cycle(
    times: np.ndarray,
    ys: np.ndarray,
    cycle: CardiacCycle,
    *,
    below_baseline: bool = False,
) -> tuple[int, int, float] | None:
    """Return ``(psv_idx, edv_idx, edv_value)`` snapped inside a cycle.

    PSV is the minimum envelope point (after optional baseline reflection);
    EDV is the mean of the adaptive window before the diastolic minimum, with
    the marker index at the window's midpoint. *edv_value* is in the same
    units as ``ys``; the caller converts to cm/s.
    """
    work = -ys if below_baseline else ys
    t_lo, t_hi = float(np.min(times)), float(np.max(times))
    eff_start = max(float(cycle.start_ms), t_lo)
    eff_end = min(float(cycle.end_ms), t_hi)
    if eff_end - eff_start < 1.0:
        return None

    in_cycle = (times >= eff_start) & (times <= eff_end)
    if int(in_cycle.sum()) < _MIN_CYCLE_POINTS:
        return None

    indices = np.nonzero(in_cycle)[0]
    psv_idx = int(indices[int(np.argmin(work[indices]))])

    span = eff_end - eff_start
    edv_search_start = eff_start + (1.0 - _CYCLE_EDV_FRACTION) * span
    in_diastole = in_cycle & (times >= edv_search_start)
    if int(in_diastole.sum()) == 0:
        in_diastole = in_cycle
    diastole_indices = np.nonzero(in_diastole)[0]
    edv_min_idx = int(diastole_indices[int(np.argmax(work[diastole_indices]))])

    min_time = max(eff_start, float(times[psv_idx]))
    window, midpoint_idx = _edv_window_indices(times, edv_min_idx, min_time=min_time)
    if len(window) < 2:
        return psv_idx, edv_min_idx, float(ys[edv_min_idx])
    edv_value = float(np.mean(ys[window]))
    return psv_idx, midpoint_idx, edv_value
```

Update `derive_psv_edv_indices_with_cycles` (lines 163-191): return type is now `tuple[int, int, float] | None`, pass original-space `ys` plus `below_baseline` to `_snap_in_cycle`:

```python
def derive_psv_edv_indices_with_cycles(
    envelope: tuple[tuple[float, float], ...],
    cycles: Sequence[CardiacCycle],
    axis_mapping: DopplerAxisMapping,
    *,
    below_baseline: bool = False,
) -> tuple[int, int, float] | None:
    """Snap PSV/EDV to the ECG cycle that contains the systolic peak.

    Envelope points are plot coordinates ``(x_px, y_px)`` with velocity
    increasing upward. Times are derived through the axis mapping. PSV is the
    highest-velocity point (minimum y); EDV is the adaptive window mean before
    the diastolic minimum of the last quarter of the selected cycle. Returns
    ``(psv_idx, edv_idx, edv_value)`` or ``None`` when no cycle contains the
    systolic peak or the cycle is too sparse.
    """
    if not envelope or not cycles:
        return None
    times = np.asarray([axis_mapping.time_ms_from_x(p[0]) for p in envelope], dtype=np.float64)
    ys = np.asarray([p[1] for p in envelope], dtype=np.float64)
    if ys.size < _MIN_CYCLE_POINTS:
        return None

    ys_eff = -ys if below_baseline else ys
    psv_idx = int(np.argmin(ys_eff))
    psv_t = float(times[psv_idx])
    cycle = next((c for c in cycles if c.start_ms <= psv_t <= c.end_ms), None)
    if cycle is None:
        return None
    return _snap_in_cycle(times, ys, cycle, below_baseline=below_baseline)
```

Update `derive_psv_edv_indices_per_cycle` (lines 194-220): return `list[tuple[int, int, float, int]]` including the contributing cycle's index:

```python
def derive_psv_edv_indices_per_cycle(
    envelope: tuple[tuple[float, float], ...],
    cycles: Sequence[CardiacCycle],
    axis_mapping: DopplerAxisMapping,
    *,
    below_baseline: bool = False,
    max_cycles: int = 3,
) -> list[tuple[int, int, float, int]]:
    """Return per-cycle ``(psv_idx, edv_idx, edv_value, cycle_index)`` tuples.

    Up to *max_cycles* cycles are considered; cycles too sparse or falling
    outside the envelope time range are skipped. Used for multi-beat PSV/EDV
    averaging and the manual cycle-selection correction mode.
    """
    if not envelope or not cycles:
        return []
    times = np.asarray([axis_mapping.time_ms_from_x(p[0]) for p in envelope], dtype=np.float64)
    ys = np.asarray([p[1] for p in envelope], dtype=np.float64)
    if ys.size < _MIN_CYCLE_POINTS:
        return []

    results: list[tuple[int, int, float, int]] = []
    for i, cycle in enumerate(cycles[:max_cycles]):
        snapped = _snap_in_cycle(times, ys, cycle, below_baseline=below_baseline)
        if snapped is not None:
            psv_idx, edv_idx, edv_value = snapped
            results.append((psv_idx, edv_idx, edv_value, i))
    return results
```

- [ ] **Step 4: Adapt the overlay call sites (keep the suite green)**

In `src/echo_personal_tool/presentation/doppler_overlay.py`, `apply_auto_trace` (lines 470-488) becomes:

```python
        if cycle_snapped is not None:
            psv_idx, edv_idx, edv_value = cycle_snapped
            self._vessel_cycle_source = "ecg"
        else:
            psv_idx, edv_idx = derive_psv_edv_indices(
                envelope,
                below_baseline=below_baseline,
            )
            self._vessel_cycle_source = "image"
            edv_value = envelope[edv_idx][1]
        psv_x, psv_y = envelope[psv_idx]
        edv_x = envelope[edv_idx][0]
        psv = self._axis_mapping.velocity_cm_s_from_y(psv_y)
        edv = self._axis_mapping.velocity_cm_s_from_y(edv_value)

        self._vessel_mode = "done"
        self._vessel_psv_px = (psv_x, psv_y)
        self._vessel_edv_px = (edv_x, edv_value)
        self._redraw_vessel_graphics()
        return psv, edv
```

In `apply_averaged_vessel` (lines 575-584) update the per-cycle unpacking and EDV source:

```python
        psv_values = [
            self._axis_mapping.velocity_cm_s_from_y(envelope[psv_idx][1]) for psv_idx, _, _, _ in per_cycle
        ]
        edv_values = [
            self._axis_mapping.velocity_cm_s_from_y(edv_value) for _, _, edv_value, _ in per_cycle
        ]
        psv_mean = sum(psv_values) / len(psv_values)
        edv_mean = sum(edv_values) / len(edv_values)
        psv_time = envelope[per_cycle[0][0]][0]
        edv_time = envelope[per_cycle[0][1]][0]
```

- [ ] **Step 5: Run the domain + overlay tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_cardiac_cycle_service.py tests/unit/test_presentation_doppler_overlay.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/echo_personal_tool/domain/services/cardiac_cycle_service.py src/echo_personal_tool/presentation/doppler_overlay.py tests/unit/test_cardiac_cycle_service.py
git commit -m "feat(doppler): EDV as adaptive window before systolic upstroke"
```

---

### Task 3: Median PSV/EDV averaging + per-cycle candidates in `apply_averaged_vessel`

**Files:**
- Modify: `src/echo_personal_tool/presentation/doppler_overlay.py` (`apply_averaged_vessel` lines 542-592, `apply_auto_trace` line 472, `clear_vessel` lines 419-427, `__init__` lines 109-117)
- Test: `tests/unit/test_presentation_doppler_overlay.py`

**Interfaces:**
- Consumes: `derive_psv_edv_indices_per_cycle` 4-tuples from Task 2.
- Produces:
  - `apply_averaged_vessel` returns `(psv_median, edv_median)` and sets:
    - `self._vessel_cycles: tuple[CardiacCycle, ...]` — the cycles that contributed
    - `self._vessel_cycle_psv_candidates: tuple[tuple[float, float], ...]` — `(time_ms, velocity_cm_s)` per contributing cycle
    - `self._vessel_cycle_index: int` (starts 0), `self._vessel_cycle_selection: bool` (True after averaging)
    - `self._vessel_cycle_source` = `cycles[0].source` (`"ecg"` or `"envelope"`)
  - `apply_auto_trace` sets `_vessel_cycle_source` from `cycles[0].source`.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_presentation_doppler_overlay.py`, add a new test class after `TestAveragedVessel`:

```python
class TestAveragedVesselMedian:
    def _artifact_envelope(self):
        # velocities = 100 - y; cycle2 PSV is an artifact spike (y=0 -> 100 cm/s)
        return (
            (100.0, 50.0), (200.0, 50.0), (300.0, 10.0), (400.0, 50.0), (500.0, 90.0),
            (600.0, 50.0), (700.0, 50.0), (800.0, 0.0), (900.0, 50.0), (1000.0, 90.0),
            (1100.0, 50.0), (1200.0, 50.0), (1300.0, 10.0), (1400.0, 50.0), (1500.0, 90.0),
        )

    def _three_cycles(self):
        from echo_personal_tool.domain.services.cardiac_cycle_service import CardiacCycle

        return (
            CardiacCycle(0.0, 1000.0, 0.0, 0.0, 1000.0, "ecg", 0.9),
            CardiacCycle(1000.0, 2000.0, 1000.0, 1000.0, 2000.0, "ecg", 0.9),
            CardiacCycle(2000.0, 3000.0, 2000.0, 2000.0, 3000.0, "ecg", 0.9),
        )

    def test_median_ignores_artifact_cycle(self, overlay, mock_plot):
        overlay.set_axis_mapping(_vessel_mapping_with_time())
        result = overlay.apply_averaged_vessel(self._artifact_envelope(), cycles=self._three_cycles())
        assert result is not None
        psv, edv = result
        # mean would be (90 + 100 + 90)/3 = 93.3; median stays 90
        assert psv == pytest.approx(90.0)
        assert edv == pytest.approx(10.0)

    def test_stores_cycles_and_candidates(self, overlay, mock_plot):
        overlay.set_axis_mapping(_vessel_mapping_with_time())
        overlay.apply_averaged_vessel(self._artifact_envelope(), cycles=self._three_cycles())
        assert len(overlay._vessel_cycles) == 3
        assert overlay._vessel_cycle_index == 0
        assert overlay._vessel_cycle_selection is True
        # cycle 1 artifact candidate at t=1600, 100 cm/s
        assert overlay._vessel_cycle_psv_candidates[1] == (1600.0, 100.0)

    def test_envelope_cycles_set_envelope_source(self, overlay, mock_plot):
        from echo_personal_tool.domain.services.cardiac_cycle_service import CardiacCycle

        overlay.set_axis_mapping(_vessel_mapping_with_time())
        envelope = ((100.0, 70.0), (200.0, 40.0), (300.0, 30.0), (400.0, 55.0),
                    (500.0, 65.0), (600.0, 35.0), (700.0, 25.0), (800.0, 50.0),
                    (900.0, 60.0), (1000.0, 70.0))
        cycle = CardiacCycle(0.0, 2000.0, 0.0, 0.0, 2000.0, "envelope", 1.0)
        overlay.apply_averaged_vessel(envelope, cycles=(cycle,))
        assert overlay.vessel_cycle_source() == "envelope"
```

Also update `TestAveragedVessel.test_averages_psv_edv_across_cycles` (lines 621-647): the 200 ms-spaced envelope triggers the single-minimum EDV fallback, so the expected values are unchanged, but add the selection-state assertions at the end of the test:

```python
        assert overlay.vessel_cycle_source() == "ecg"
        assert overlay.vessel_averaged_cycles() == 2
        assert overlay.vessel_status() == "done"
        assert overlay._vessel_cycle_selection is True
        assert len(overlay._vessel_cycles) == 2
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_presentation_doppler_overlay.py::TestAveragedVesselMedian -v`
Expected: FAIL — `assert psv == approx(90.0)` fails (`93.333...` from the mean), and `overlay._vessel_cycle_selection` does not exist yet (AttributeError).

- [ ] **Step 3: Implement median averaging + candidate storage**

In `src/echo_personal_tool/presentation/doppler_overlay.py`:
- Add `import statistics` after the `from __future__ import annotations` block (before `import numpy as np`).
- In `__init__`, after line 114 (`self._vessel_averaged_cycles: int = 1`), add:

```python
        self._vessel_cycles: tuple[CardiacCycle, ...] = ()
        self._vessel_cycle_psv_candidates: tuple[tuple[float, float], ...] = ()
        self._vessel_cycle_index: int = 0
        self._vessel_cycle_selection: bool = False
```

- Replace `apply_averaged_vessel` (lines 542-592) with:

```python
    def apply_averaged_vessel(
        self,
        envelope: tuple[tuple[float, float], ...],
        *,
        cycles: tuple[CardiacCycle, ...] = (),
        max_beats: int = 3,
    ) -> tuple[float, float] | None:
        """Average PSV/EDV across up to *max_beats* cardiac cycles.

        Per-cycle PSV/EDV are derived inside each cycle's own diastolic window;
        the PSV and EDV are the MEDIANS across the contributing cycles, which
        makes the result robust to one corrupted (artifact) beat. Markers are
        placed at the median velocities on the first beat's times. Stores the
        contributing cycles and per-cycle PSV candidates and activates the
        manual cycle-selection correction mode. Returns ``(psv, edv)`` in cm/s
        or ``None`` when no cycle yields a valid snapshot.
        """
        self._clear_auto_envelope()
        if not envelope or len(envelope) < 2 or not cycles:
            return None
        xs = [p[0] for p in envelope]
        ys = [p[1] for p in envelope]
        item = pg.PlotDataItem(xs, ys, pen=pg.mkPen("#00e5ff", width=2))
        item.setZValue(24)
        self._plot.addItem(item)
        self._auto_envelope_item = item

        per_cycle = derive_psv_edv_indices_per_cycle(
            envelope,
            cycles,
            self._axis_mapping,
            below_baseline=self._envelope_below_baseline(envelope),
            max_cycles=max_beats,
        )
        if not per_cycle:
            return None
        psv_entries = [
            (
                self._axis_mapping.time_ms_from_x(envelope[psv_idx][0]),
                self._axis_mapping.velocity_cm_s_from_y(envelope[psv_idx][1]),
            )
            for psv_idx, _, _, _ in per_cycle
        ]
        edv_values = [
            self._axis_mapping.velocity_cm_s_from_y(edv_value) for _, _, edv_value, _ in per_cycle
        ]
        psv_median = statistics.median(entry[1] for entry in psv_entries)
        edv_median = statistics.median(edv_values)
        psv_time = envelope[per_cycle[0][0]][0]
        edv_time = envelope[per_cycle[0][1]][0]

        self._vessel_mode = "done"
        self._vessel_psv_px = (psv_time, self._axis_mapping.y_from_velocity_cm_s(psv_median))
        self._vessel_edv_px = (edv_time, self._axis_mapping.y_from_velocity_cm_s(edv_median))
        self._vessel_cycle_source = cycles[0].source
        self._vessel_averaged_cycles = len(per_cycle)
        self._vessel_cycles = tuple(cycles[idx] for _, _, _, idx in per_cycle)
        self._vessel_cycle_psv_candidates = tuple(psv_entries)
        self._vessel_cycle_index = 0
        self._vessel_cycle_selection = True
        self._redraw_vessel_graphics()
        return psv_median, edv_median
```

- In `apply_auto_trace`, change line 472 `self._vessel_cycle_source = "ecg"` to:

```python
            self._vessel_cycle_source = cycles[0].source
```

- Replace `clear_vessel` (lines 419-427) with:

```python
    def clear_vessel(self) -> None:
        self._vessel_mode = "none"
        self._vessel_psv_px = None
        self._vessel_edv_px = None
        self._vessel_drag_target = None
        self._vessel_cycle_source = None
        self._vessel_averaged_cycles = 1
        self._vessel_cycles = ()
        self._vessel_cycle_psv_candidates = ()
        self._vessel_cycle_index = 0
        self._vessel_cycle_selection = False
        self._clear_auto_envelope()
        self._redraw_vessel_graphics()
```

- [ ] **Step 4: Run the overlay tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_presentation_doppler_overlay.py -v`
Expected: PASS (incl. `TestAutoTraceWithCycles`, which verifies source still resolves correctly).

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/presentation/doppler_overlay.py tests/unit/test_presentation_doppler_overlay.py
git commit -m "feat(doppler): median PSV/EDV averaging with per-cycle candidates"
```

---

### Task 4: Manual PSV correction mode — overlay layer (band highlight + state)

**Files:**
- Modify: `src/echo_personal_tool/presentation/doppler_overlay.py` (`__init__`, `_redraw_vessel_graphics`, new methods)
- Test: `tests/unit/test_presentation_doppler_overlay.py`

**Interfaces:**
- Consumes: `_vessel_cycles`, `_vessel_cycle_psv_candidates`, `_vessel_cycle_index`, `_vessel_cycle_selection` (from Task 3).
- Produces (all on `DopplerOverlayTools`):
  ```python
  def vessel_cycle_selection_active(self) -> bool
  def vessel_cycle_count(self) -> int
  def vessel_cycle_index(self) -> int
  def vessel_cycle_candidate(self) -> float | None           # velocity cm/s of current cycle
  def move_vessel_cycle(self, delta: int) -> bool            # wraps; redraws band; returns True if moved
  def assign_vessel_cycle_psv(self) -> bool                  # sets PSV to current candidate, exits mode
  def cancel_vessel_cycle_selection(self) -> bool            # exits mode, PSV unchanged
  ```
  Draws a semi-transparent vertical band over the selected cycle's `start_ms..end_ms` plus a `"PSV кандидат: X.X cm/s"` text item; both cleared when selection is off.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_presentation_doppler_overlay.py`:

```python
class TestVesselCycleCorrection:
    def _averaged(self, overlay, mock_plot):
        overlay.set_axis_mapping(_vessel_mapping_with_time())
        envelope = ((100.0, 70.0), (200.0, 40.0), (300.0, 30.0), (400.0, 55.0),
                    (500.0, 65.0), (600.0, 35.0), (700.0, 25.0), (800.0, 50.0),
                    (900.0, 60.0), (1000.0, 70.0))
        from echo_personal_tool.domain.services.cardiac_cycle_service import CardiacCycle

        cycles = (
            CardiacCycle(0.0, 1000.0, 0.0, 0.0, 1000.0, "envelope", 1.0),
            CardiacCycle(1000.0, 2000.0, 1000.0, 1000.0, 2000.0, "envelope", 1.0),
        )
        overlay.apply_averaged_vessel(envelope, cycles=cycles)
        return envelope

    def test_draws_band_on_selected_cycle(self, overlay, mock_plot):
        self._averaged(overlay, mock_plot)
        assert overlay._vessel_cycle_band is not None
        assert overlay._vessel_cycle_band in mock_plot.items
        assert overlay._vessel_cycle_text is not None

    def test_arrow_moves_index_and_redraws(self, overlay, mock_plot):
        self._averaged(overlay, mock_plot)
        assert overlay.vessel_cycle_index() == 0
        assert overlay.move_vessel_cycle(1) is True
        assert overlay.vessel_cycle_index() == 1
        assert overlay.vessel_cycle_candidate() == pytest.approx(75.0)

    def test_arrow_wraps_around(self, overlay, mock_plot):
        self._averaged(overlay, mock_plot)
        overlay.move_vessel_cycle(-1)
        assert overlay.vessel_cycle_index() == 1

    def test_assign_applies_candidate_and_exits(self, overlay, mock_plot):
        self._averaged(overlay, mock_plot)
        overlay.move_vessel_cycle(1)
        assert overlay.assign_vessel_cycle_psv() is True
        assert overlay.vessel_cycle_selection_active() is False
        psv, edv = overlay.get_vessel_values()
        assert psv == pytest.approx(75.0)
        assert edv == pytest.approx(32.5)
        assert overlay.vessel_status() == "done"

    def test_cancel_keeps_median_psv(self, overlay, mock_plot):
        self._averaged(overlay, mock_plot)
        median_psv, _ = overlay.get_vessel_values()
        overlay.move_vessel_cycle(1)
        assert overlay.cancel_vessel_cycle_selection() is True
        psv, _ = overlay.get_vessel_values()
        assert psv == pytest.approx(median_psv)
        assert overlay._vessel_cycle_band is None

    def test_candidate_none_when_inactive(self, overlay, mock_plot):
        overlay.set_axis_mapping(_vessel_mapping())
        assert overlay.vessel_cycle_candidate() is None

    def test_clear_vessel_resets_selection(self, overlay, mock_plot):
        self._averaged(overlay, mock_plot)
        overlay.clear_vessel()
        assert overlay.vessel_cycle_selection_active() is False
        assert overlay.vessel_cycle_count() == 0
        assert overlay._vessel_cycle_band is None
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_presentation_doppler_overlay.py::TestVesselCycleCorrection -v`
Expected: FAIL with `AttributeError` (`_vessel_cycle_band` / `vessel_cycle_selection_active` missing).

- [ ] **Step 3: Implement the correction mode in the overlay**

In `src/echo_personal_tool/presentation/doppler_overlay.py`, `__init__` after line 117 (`self._auto_envelope_item`) add:

```python
        self._vessel_cycle_band: pg.PlotDataItem | None = None
        self._vessel_cycle_text: pg.TextItem | None = None
```

At the end of `_redraw_vessel_graphics` (after the `if self._vessel_text_item ... addItem` block, i.e. after line 639) add a call:

```python
        self._redraw_vessel_cycle_graphics()
```

Add the new public methods after `vessel_averaged_cycles` (line 598):

```python
    def vessel_cycle_selection_active(self) -> bool:
        return self._vessel_cycle_selection

    def vessel_cycle_count(self) -> int:
        return len(self._vessel_cycles)

    def vessel_cycle_index(self) -> int:
        return self._vessel_cycle_index

    def vessel_cycle_candidate(self) -> float | None:
        if not self._vessel_cycle_psv_candidates:
            return None
        if self._vessel_cycle_index < 0 or self._vessel_cycle_index >= len(self._vessel_cycle_psv_candidates):
            return None
        return self._vessel_cycle_psv_candidates[self._vessel_cycle_index][1]

    def move_vessel_cycle(self, delta: int) -> bool:
        if not self._vessel_cycle_selection or not self._vessel_cycles:
            return False
        count = len(self._vessel_cycles)
        self._vessel_cycle_index = (self._vessel_cycle_index + delta) % count
        self._redraw_vessel_cycle_graphics()
        self._emit_vessel_changed()
        return True

    def assign_vessel_cycle_psv(self) -> bool:
        if not self._vessel_cycle_selection or not self._vessel_cycle_psv_candidates:
            return False
        if self._vessel_cycle_index < 0 or self._vessel_cycle_index >= len(self._vessel_cycle_psv_candidates):
            return False
        time_ms, velocity_cm_s = self._vessel_cycle_psv_candidates[self._vessel_cycle_index]
        self._vessel_psv_px = (
            self._axis_mapping.x_from_time_ms(time_ms),
            self._axis_mapping.y_from_velocity_cm_s(velocity_cm_s),
        )
        self._vessel_cycle_selection = False
        self._redraw_vessel_graphics()
        self._emit_vessel_changed()
        return True

    def cancel_vessel_cycle_selection(self) -> bool:
        if not self._vessel_cycle_selection:
            return False
        self._vessel_cycle_selection = False
        self._redraw_vessel_graphics()
        return True

    def _clear_vessel_cycle_graphics(self) -> None:
        if self._vessel_cycle_band is not None:
            try:
                self._plot.removeItem(self._vessel_cycle_band)
            except Exception:  # noqa: BLE001
                pass
            self._vessel_cycle_band = None
        if self._vessel_cycle_text is not None:
            try:
                self._plot.removeItem(self._vessel_cycle_text)
            except Exception:  # noqa: BLE001
                pass
            self._vessel_cycle_text = None

    def _redraw_vessel_cycle_graphics(self) -> None:
        self._clear_vessel_cycle_graphics()
        if not self._vessel_cycle_selection or not self._vessel_cycles:
            return
        index = min(max(self._vessel_cycle_index, 0), len(self._vessel_cycles) - 1)
        cycle = self._vessel_cycles[index]
        x_start = self._axis_mapping.x_from_time_ms(cycle.start_ms)
        x_end = self._axis_mapping.x_from_time_ms(cycle.end_ms)
        top = -1.0
        bottom = self._axis_mapping.plot_height + 1.0
        band = pg.PlotDataItem(
            [x_start, x_end],
            [top, top],
            pen=pg.mkPen(255, 235, 59, 40),
            brush=pg.mkBrush(255, 235, 59, 40),
        )
        band.setZValue(23)
        band.setFillLevel(bottom)
        self._plot.addItem(band)
        self._vessel_cycle_band = band
        candidate = self.vessel_cycle_candidate()
        if candidate is not None:
            label = pg.TextItem(f"PSV кандидат: {candidate:.1f} cm/s", anchor=(0.0, 0.0), fill=(0, 0, 0, 200))
            label.setZValue(30)
            label.setPos(x_start, top + 2)
            self._plot.addItem(label)
            self._vessel_cycle_text = label
```

- [ ] **Step 4: Run the overlay tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_presentation_doppler_overlay.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/presentation/doppler_overlay.py tests/unit/test_presentation_doppler_overlay.py
git commit -m "feat(doppler): cycle selection highlight for manual PSV correction"
```

---

### Task 5: Manual PSV correction mode — viewer keys + i18n texts

**Files:**
- Modify: `src/echo_personal_tool/presentation/viewer_widget.py` (`average_vessel_cycles` lines 2391-2414, new `_update_vessel_cycle_selection_label` / `_restore_vessel_average_label`, `keyPressEvent` lines 6270-6330)
- Modify: `src/echo_personal_tool/infrastructure/locales/ru.json` (lines 584, 771 + new key)
- Modify: `src/echo_personal_tool/infrastructure/locales/en.json` (lines 584, 771 + new key)
- Test: `tests/unit/test_presentation_viewer_widget.py`

**Interfaces:**
- Consumes: overlay methods from Task 4 (`vessel_cycle_selection_active`, `vessel_cycle_count`, `vessel_cycle_index`, `vessel_cycle_candidate`, `move_vessel_cycle`, `assign_vessel_cycle_psv`, `cancel_vessel_cycle_selection`).
- Produces: `viewer._update_vessel_cycle_selection_label()`, `viewer._restore_vessel_average_label()`; key handling — `←`/`→` move the selection (only when active), `Enter` assigns the candidate then accepts, `Esc` cancels the mode keeping the median PSV.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_presentation_viewer_widget.py`:

```python
class TestVesselCycleCorrection:
    def _cycles(self):
        from echo_personal_tool.domain.services.cardiac_cycle_service import CardiacCycle

        return (
            CardiacCycle(0.0, 1000.0, 0.0, 0.0, 1000.0, "envelope", 1.0),
            CardiacCycle(1000.0, 2000.0, 1000.0, 1000.0, 2000.0, "envelope", 1.0),
        )

    def _averaged(self, viewer):
        from echo_personal_tool.domain.models.doppler_roi import DopplerCalibrationState, DopplerSpectrogramRoi
        from echo_personal_tool.domain.services.doppler_calibration import build_axis_mapping

        viewer._current_frame = np.zeros((200, 1000), dtype=np.uint8)
        state = DopplerCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0.0, y0=0.0, width=1000.0, height=200.0),
            baseline_y_px=100.0,
            velocity_span_cm_s=200.0,
            time_span_ms=2000.0,
        )
        viewer._doppler_calibration_state = state
        viewer._doppler.set_axis_mapping(build_axis_mapping(state))
        envelope = ((100.0, 70.0), (200.0, 40.0), (300.0, 30.0), (400.0, 55.0),
                    (500.0, 65.0), (600.0, 35.0), (700.0, 25.0), (800.0, 50.0),
                    (900.0, 60.0), (1000.0, 70.0))
        from unittest.mock import patch

        with patch.object(viewer, "_extract_doppler_envelope", return_value=envelope), patch.object(
            viewer, "_doppler_cardiac_cycles", return_value=self._cycles()
        ):
            assert viewer.average_vessel_cycles() is True

    def _key(self, key):
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QKeyEvent

        return QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)

    def test_average_activates_selection(self, viewer):
        self._averaged(viewer)
        assert viewer._doppler.vessel_cycle_selection_active() is True
        assert viewer._doppler.vessel_cycle_count() == 2
        assert "PSV" in viewer._measurement_label.text()

    def test_left_right_moves_selection(self, viewer):
        self._averaged(viewer)
        viewer.keyPressEvent(self._key(Qt.Key.Key_Right))
        assert viewer._doppler.vessel_cycle_index() == 1
        viewer.keyPressEvent(self._key(Qt.Key.Key_Left))
        assert viewer._doppler.vessel_cycle_index() == 0

    def test_enter_assigns_candidate_and_accepts(self, viewer):
        from PySide6.QtCore import Qt

        self._averaged(viewer)
        viewer.keyPressEvent(self._key(Qt.Key.Key_Right))
        candidate = viewer._doppler.vessel_cycle_candidate()
        accepted = []
        viewer.vessel_accept_requested.connect(accepted.append)
        from unittest.mock import patch

        with patch.object(viewer, "_current_instance_uid", return_value="uid"):
            viewer.keyPressEvent(self._key(Qt.Key.Key_Return))
        assert len(accepted) == 1
        assert accepted[0].psv_cm_s == pytest.approx(candidate)
        assert viewer._doppler.vessel_status() == "none"

    def test_escape_cancels_keeps_median(self, viewer):
        from PySide6.QtCore import Qt

        self._averaged(viewer)
        median_psv, _ = viewer._doppler.get_vessel_values()
        viewer.keyPressEvent(self._key(Qt.Key.Key_Right))
        viewer.keyPressEvent(self._key(Qt.Key.Key_Escape))
        assert viewer._doppler.vessel_cycle_selection_active() is False
        psv, _ = viewer._doppler.get_vessel_values()
        assert psv == pytest.approx(median_psv)
        assert viewer._doppler.vessel_status() == "done"
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_presentation_viewer_widget.py::TestVesselCycleCorrection -v`
Expected: FAIL — `viewer._update_vessel_cycle_selection_label` not invoked / `average_vessel_cycles` leaves no prompt, or `AttributeError` on the missing viewer methods.

- [ ] **Step 3: Implement viewer keys + labels + locale**

In `src/echo_personal_tool/presentation/viewer_widget.py`:

Update `average_vessel_cycles` (lines 2408-2413) to activate the correction-mode prompt after success:

```python
        psv, edv = result
        count = self._doppler.vessel_averaged_cycles()
        self._measurement_label.setText(
            tr("viewer.vessel_average_done", psv=psv, edv=edv, count=count)
        )
        self._measurement_label.show()
        if self._doppler.vessel_cycle_selection_active():
            self._update_vessel_cycle_selection_label()
        return True
```

Add two helper methods after `average_vessel_cycles` (before `accept_vessel_measurement`):

```python
    def _update_vessel_cycle_selection_label(self) -> None:
        candidate = self._doppler.vessel_cycle_candidate()
        index = self._doppler.vessel_cycle_index()
        count = self._doppler.vessel_cycle_count()
        if candidate is None:
            return
        self._measurement_label.setText(
            tr("viewer.vessel_cycle_candidate", value=candidate, index=index + 1, count=count)
        )
        self._measurement_label.show()

    def _restore_vessel_average_label(self) -> None:
        values = self._doppler.get_vessel_values()
        if values is None:
            self._measurement_label.hide()
            return
        psv, edv = values
        count = self._doppler.vessel_averaged_cycles()
        self._measurement_label.setText(
            tr("viewer.vessel_average_done", psv=psv, edv=edv, count=count)
        )
        self._measurement_label.show()
```

In `keyPressEvent` (lines 6270-6330), REPLACE the existing Enter branch (lines 6281-6289) with the block below. The existing branch also handled the freehand-contour finish, so it MUST be preserved (do not drop it):

```python
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self._doppler.vessel_cycle_selection_active() and self._doppler.assign_vessel_cycle_psv():
                self.accept_vessel_measurement()
                event.accept()
                return
            if self._doppler.vessel_status() == "done" and self.is_vessel_available():
                self.accept_vessel_measurement()
                event.accept()
                return
            if self._freehand_recording and self._contour_mode_active:
                if self._finish_freehand_contour():
                    event.accept()
                    return
```

Add the Escape branch by REPLACING the existing vessel-clear Escape branch (lines 6290-6294):

```python
        if event.key() == Qt.Key.Key_Escape:
            if self._doppler.vessel_cycle_selection_active():
                self._doppler.cancel_vessel_cycle_selection()
                self._restore_vessel_average_label()
                event.accept()
                return
            if self._doppler.vessel_status() != "none":
                self.clear_vessel_measurement()
                event.accept()
                return
```

Add the `←`/`→` branch just before `super().keyPressEvent(event)` (line 6330):

```python
        if not event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.key() == Qt.Key.Key_Left and self._doppler.vessel_cycle_selection_active():
                if self._doppler.move_vessel_cycle(-1):
                    self._update_vessel_cycle_selection_label()
                    event.accept()
                    return
            if event.key() == Qt.Key.Key_Right and self._doppler.vessel_cycle_selection_active():
                if self._doppler.move_vessel_cycle(1):
                    self._update_vessel_cycle_selection_label()
                    event.accept()
                    return
```

In `src/echo_personal_tool/infrastructure/locales/ru.json`:
- Line 584: `"status.vessel_average"` value → `"Сосуды: усреднено по циклам"`
- Line 771: `"viewer.vessel_average_failed"` value → `"Сосуды: не удалось определить циклы для усреднения"`
- Add after line 771:
  `"viewer.vessel_cycle_candidate": "Цикл {index}/{count}: PSV кандидат {value:.1f} cm/s (←/→ — выбор, Enter — принять, Esc — отмена)"`

In `src/echo_personal_tool/infrastructure/locales/en.json`:
- Line 584: `"status.vessel_average"` value → `"Vessels: averaged across cycles"`
- Line 771: `"viewer.vessel_average_failed"` value → `"Vessels: could not identify cycles for averaging"`
- Add after line 771:
  `"viewer.vessel_cycle_candidate": "Cycle {index}/{count}: PSV candidate {value:.1f} cm/s (←/→ select, Enter — accept, Esc — cancel)"`

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_presentation_viewer_widget.py::TestVesselCycleCorrection tests/unit/test_i18n.py::test_locale_key_parity -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/presentation/viewer_widget.py src/echo_personal_tool/infrastructure/locales/ru.json src/echo_personal_tool/infrastructure/locales/en.json tests/unit/test_presentation_viewer_widget.py
git commit -m "feat(doppler): wire cycle-selection keys and i18n texts"
```

---

### Task 6: Full regression + lint

**Files:** none (verification only; run-fix-commit only if a regression is found).

- [ ] **Step 1: Run the touched test files**

Run: `.venv/bin/python -m pytest tests/unit/test_cardiac_cycle_service.py tests/unit/test_presentation_doppler_overlay.py tests/unit/test_presentation_viewer_widget.py tests/unit/test_i18n.py -q`
Expected: PASS (run these four files in one process is fine; do NOT add `tests/unit` whole-directory runs — known Qt segfault in one process).

- [ ] **Step 2: Run the surrounding suites**

Run: `.venv/bin/python -m pytest tests/unit/test_viewer_widget.py tests/unit/test_dicom_session.py tests/unit/test_presentation_viewer_widget.py -q`
Expected: PASS except the two known pre-existing failures (`test_doppler_axis` POC default, `test_measurement_tools_panel` hardcoded `/tmp/test.dcm`) which are unrelated.

- [ ] **Step 3: Run ruff on the changed files**

Run: `.venv/bin/ruff check src/echo_personal_tool/domain/services/cardiac_cycle_service.py src/echo_personal_tool/presentation/doppler_overlay.py src/echo_personal_tool/presentation/viewer_widget.py tests/unit/test_cardiac_cycle_service.py tests/unit/test_presentation_doppler_overlay.py tests/unit/test_presentation_viewer_widget.py`
Expected: `All checks passed!`

- [ ] **Step 4: Confirm the spec's edge-case matrix**

Manually verify against the design spec (`docs/superpowers/specs/2026-08-05-vessel-cycle-averaging-design.md`):
- 1 cycle → `derive_psv_edv_indices_per_cycle` returns one tuple → median = that value → correction mode with 1 cycle works (`vessel_cycle_count() == 1`).
- No peaks → `detect_cycles_from_envelope` → `[]` → `apply_averaged_vessel` returns `None` → `viewer.vessel_average_failed` label (text no longer mentions ECG).
- Sparse cycles → skipped by `derive_psv_edv_indices_per_cycle` (cycle_index reflects the contributing cycle).
- EDV window < 2 points → single-minimum fallback (`_snap_in_cycle`).
- Frame/instance switch → `clear_measurements` → `clear_vessel` resets selection state + band.
- Accept saves `cycle_source` = `"envelope"` or `"ecg"` from `cycles[0].source`.

- [ ] **Step 5: No commit unless a regression was fixed** (fix + commit in the same style as the touching task if needed).
