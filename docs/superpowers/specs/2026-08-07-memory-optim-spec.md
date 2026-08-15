# Memory Optimization for Weak PC DICOM Playback — Design Specification

**Date:** 2026-08-07  
**Status:** Draft  
**Type:** Performance  
**Domain:** DICOM multiframe playback memory management on low-end Windows systems  
**Tracker ticket:** [GitHub Issue #38](https://github.com/areatu/SonoForge/issues/38) — feat: adaptive FrameCache memory budget + async release_stale_sessions  
**Related:**
- [`2026-08-07-memory-optim.md`](../plans/2026-08-07-memory-optim.md) — corrected plan
- `src/echo_personal_tool/application/frame_cache.py` — FrameCache with LRU eviction
- `src/echo_personal_tool/infrastructure/dicom_session.py` — thread-local sessions, `release_heavy`
- `src/echo_personal_tool/presentation/viewer_widget.py` — `_update_levels()`, dead `levels_changed`
- `src/echo_personal_tool/infrastructure/playback_diagnostics.py` — existing telemetry
- `src/echo_personal_tool/infrastructure/system_profiler.py` — `PlaybackConfig` (low/high detection)

---

## 1. Executive Summary

On weak PCs (≤4 cores, ≤8 GB RAM), fast file switching in SonoForge causes 30–40% CPU on the main thread and RAM growing from 1.3 GB to 4–8 GB. The original Playback Resilience Layer plan was architecturally mismatched (FFmpeg/D3D11VA assumptions) and proposed a disk cache that would violate the project's hard de-identification rule. This spec covers the **4 remaining actionable improvements** that are compatible with the existing pydicom + cv2 + PySide6 architecture:

1. Adaptive memory budget for `FrameCache` (replace hardcoded 2 GB cap)
2. Remove dead `levels_changed` variable (cleanup, no behavioral change)
3. Async `release_stale_sessions()` (move off main thread)
4. Extended instance-switch telemetry

**Non-negotiables (Phi compliance):**
- No disk caching of decoded pixel data (PHI leak)
- No FFmpeg, no D3D11VA, no C++ extensions (architectural mismatch)

---

## 2. Goals and Non-Goals

### 2.1 Goals

| Goal | Success Criterion |
|------|-------------------|
| Reduce main-thread blocking during file switch | `release_stale_sessions` no longer blocks UI; `load_instance` returns to responsive state within **50 ms** |
| Bound memory on low-end systems | `FrameCache` uses ≤**128 MB** on 8 GB RAM system; evict window adapts to frame size |
| Observable memory growth | `playback_diagnostics` captures per-instance-switch RSS delta + `release_stale_sessions` duration |
| No regression in window/level rendering | Grayscale W/L still applies per-frame LUT; test confirms identical output before/after |

### 2.2 Non-Goals

| Defer to P1 | Rationale |
|-------------|-----------|
| Disk cache / proxy files | Violates de-identification PHI; `%LOCALAPPDATA%` world-readable on Windows |
| FFmpeg / D3D11VA GPU pipeline | No FFmpeg dependency in SonoForge; D3D11↔PySide6 interop requires C++ extension |
| Resolution-scaled DICOM decode | Decode already fast (7.7 ms uncompressed, 40 ms JPEG for 60 frames) |
| `np.trapz` fix / `Qt.QSize` fix / other unrelated bugs | Out of scope for memory optimization |

---

## 3. Current State Diagnosis

### 3.1 FrameCache memory budget (`frame_cache.py:18-19`)

```python
_DEFAULT_EVICT_WINDOW = 40  # line 18
_MAX_CACHE_MEMORY_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB — line 19, hardcoded
```

- `FrameCache.__init__` accepts `evict_window` parameter but NOT a max memory parameter
- `_evict_to_memory_limit()` (line 101) uses the module-level `_MAX_CACHE_MEMORY_BYTES` constant directly — cannot be overridden at instance level. Internal references to `_MAX_CACHE_MEMORY_BYTES` are at lines 98 and 105
- `_evict()` (line 248) uses `self._evict_window` — already configurable per-instance via constructor, but default is always 40

**Actual instantiation:** `app_controller.py:151` → `FrameCache(evict_window=self._playback_config.evict_window)` — evicts window is configurable but memory cap is not.

**Problem on weak PC:** 2 GB cache cap = 25% of 8 GB RAM. For 1920×1080 uint8 frames: 2 GB / 8.3 MB per frame ≈ 241 frames. For 640×480 frames: 2 GB / 0.4 MB ≈ 5,120 frames — but each `DicomSession` can hold decoded `_frames` separately.

### 3.2 `levels_changed` dead variable (`viewer_widget.py:1751`)

```python
# show_frame_fast(), line 1749-1752
levels_key = (
    self._dr_slider.value(),
    self._window_slider.value(),
    self._level_slider.value(),
)
levels_changed = levels_key != self._cached_levels_key  # computed but NEVER used
self._cached_levels_key = levels_key
```

- `levels_changed` is a local variable in `show_frame_fast()` (starts line 1718) — IS in scope at both call sites, but **never used**
- Both `_update_levels()` calls (color branch line ~1772, grayscale branch line 1788) are in `show_frame_fast()` — they do NOT reference `levels_changed`
- `_update_levels()` (line 6517) has its own internal cache check at line 6533: `if self._cached_display_low is not None and self._cached_display_high is not None and self._cached_levels_key == sliders_key:`

**Conclusion:** `_is_levels_outlier()` (line 6617) is only called inside cache-miss path (line 6552). The "5-10ms/frame" claim is incorrect — the internal cache already handles gating. `levels_changed` is dead code that should be removed for readability.

**Critical warning:** Adding `if levels_changed: _update_levels()` at the call site would **break W/L rendering** — the LUT (`cv2.LUT`, line 6598) must be applied to every frame, not just when sliders change.

### 3.3 `release_stale_sessions()` on main thread (`app_controller.py:363`)

```python
# load_instance(), line 361-363
from echo_personal_tool.infrastructure.dicom_session import release_stale_sessions
release_stale_sessions()
```

- Loops up to `_max_sessions = 10` sessions (`dicom_session.py:55`)
- Each calls `release_heavy()` (line 588) which clears `_pixel_data_raw`, `_encapsulated_frames`, `_frames` — up to 19 MB per session × 10 = 190 MB of cleanup
- Runs synchronously on main thread during `load_instance()` → visible UI freeze on slow CPUs
- `_metadata` is intentionally preserved (not a race condition — see checkpoint §7)

### 3.4 Telemetry gaps (`playback_diagnostics.py`)

Current `PlaybackDiagnostics` captures (`playback_diagnostics.py:188`):
- `start()` (`playback_diagnostics.py:209`) — sets RSS baseline, enables capture
- `on_frame_tick(frame_index, phase)` (`playback_diagnostics.py:232`) — per-frame timing + RSS peak
- `on_decode_batch(start_idx, count, elapsed_ms)` (`playback_diagnostics.py:265`) — batch decode timing
- `snapshot_memory()` (`playback_diagnostics.py:279`) — numpy array snapshot
- `stop()` (`playback_diagnostics.py:285`) — finalizes `PlaybackReport`

**Missing:** per-instance-switch metrics — how long does the file switch take, what's the RSS delta, was prefetch cancelled? No call to `diagnostics` exists in `app_controller.py:load_instance()` or `_prefetch_playback_buffer()`.

---

## 4. Target Architecture

### 4.1 Adaptive Memory Budget

Replace module-level constant `_MAX_CACHE_MEMORY_BYTES` with an instance-level parameter. `PlaybackConfig` (in `system_profiler.py`) already provides `evict_window` — the new `max_cache_bytes` is derived from `psutil.virtual_memory().available` at `FrameCache` instantiation:

- Low-end: 64 MB cap, `evict_window` = 12 (changed from 30)
- High-end: 128 MB cap, `evict_window` = 20 (changed from 40)

`FrameCache.__init__` signature changes from:
```python
def __init__(self, *, evict_window: int = _DEFAULT_EVICT_WINDOW) -> None:
```
to:
```python
def __init__(self, *, evict_window: int = _DEFAULT_EVICT_WINDOW, max_cache_bytes: int = _MAX_CACHE_MEMORY_BYTES) -> None:
```

All internal references to `_MAX_CACHE_MEMORY_BYTES` (lines 98, 105) become `self._max_cache_bytes`. The `_evict()` method (line 248) uses `self._evict_window` and is unchanged.

Budget formula at `AppController.__init__`:
```python
from echo_personal_tool.infrastructure.user_preferences import load_user_preferences
import psutil
available = psutil.virtual_memory().available
_prefs = load_user_preferences()
max_cache = min(_prefs.playback_max_cache_mb * 1024 * 1024, int(available * 0.08))
evict_window = self._playback_config.evict_window
self._frame_cache = FrameCache(evict_window=evict_window, max_cache_bytes=max_cache)
```

### 4.2 `release_stale_sessions()` — rely on `DicomSession.open()` built-in call

**Rejected: Async QRunnable approach.** A `_ReleaseStaleSessionsWorker(QRunnable)` was prototyped to offload `release_stale_sessions()` from the main thread, but profiling the critical path revealed a **race condition**:

The QRunnable calls `release_stale_sessions()` (no `exclude`) which calls `release_heavy()` on ALL sessions — including the `DicomDecodeWorker`'s session that may be mid-`decode_all_frames()` (ThreadPoolExecutor at `dicom_session.py:483`). If `release_heavy()` sets `self._frames = None` between ThreadPoolExecutor setup (line 483) and result collection (line 487: `self._frames[idx] = future.result()`), the app crashes with `TypeError: 'NoneType' object does not support item assignment`.

**Solution:** Remove the QRunnable entirely. `DicomSession.open()` (line 333) already calls `release_stale_sessions(exclude=self)` on the **worker thread** — this happens BEFORE decoding begins, so no race. Old sessions are released on the worker thread (not the main thread), so there's no UI blocking.

`AppController.load_instance()` changes:
```python
# OLD (blocking, app_controller.py:363):
from echo_personal_tool.infrastructure.dicom_session import release_stale_sessions
release_stale_sessions()

# NEW (no explicit call — handled by DicomSession.open):
# Old sessions are released by DicomSession.open() via release_stale_sessions(exclude=self)
# on the worker thread — no main-thread blocking, no race condition.
```

### 4.3 Telemetry extension

Add to `PlaybackDiagnostics`:

```python
@dataclass
class InstanceSwitchRecord:
    timestamp: float
    rss_before_mb: float
    rss_after_mb: float
    elapsed_ms: float
    prefetch_cancelled: bool
    frame_cache_bytes: int

# New methods on PlaybackDiagnostics (line 188):
def on_instance_switch_start(self, *, prefetch_cancelled: bool = False, frame_cache_bytes: int = 0) -> None:
    """Called at start of load_instance() — before release_stale_sessions + open()."""
    if not self.enabled:
        return
    self._instance_switch_start = perf_counter()
    self._instance_switch_rss_start = _rss_mb()
    self._instance_switch_prefetch_cancelled = prefetch_cancelled
    self._instance_switch_frame_cache_bytes = frame_cache_bytes

def on_instance_switch_end(self) -> InstanceSwitchRecord | None:
    """Called after DicomSession.open() + decode_first_frame() completes."""
    if not self.enabled or not hasattr(self, '_instance_switch_start'):
        return None
    elapsed = (perf_counter() - self._instance_switch_start) * 1000.0
    record = InstanceSwitchRecord(
        timestamp=time.time(),
        rss_before_mb=self._instance_switch_rss_start,
        rss_after_mb=_rss_mb(),
        elapsed_ms=elapsed,
        prefetch_cancelled=self._instance_switch_prefetch_cancelled,
        frame_cache_bytes=self._instance_switch_frame_cache_bytes,
    )
    self._instance_switch_records.append(record)
    self._rss_peak_mb = max(self._rss_peak_mb, record.rss_after_mb)
    del self._instance_switch_start
    return record

def on_prefetch_cancel(self, *, reason: str = "file_switch") -> None:
    """Called when FrameLoaderWorker prefetch is cancelled."""
    if not self.enabled:
        return
    self._prefetch_cancels += 1
    _LOG.info("[PLAYBACK_DIAG] prefetch_cancelled reason=%s count=%d", reason, self._prefetch_cancels)
```

Add to `PlaybackReport`: `instance_switches: list[InstanceSwitchRecord]` and `prefetch_cancel_count: int`.

### 4.4 Dead variable cleanup

Remove lines 1751-1752 from `viewer_widget.py` `show_frame_fast()`:
```python
# REMOVE:
levels_changed = levels_key != self._cached_levels_key
# KEEP: self._cached_levels_key = levels_key  # still needed for internal cache
```

---

## 5. Detailed Implementation

### 5.1 File changes

| File | Change | Lines |
|------|--------|-------|
| `frame_cache.py` | Add `max_cache_bytes` param to `__init__`; store `self._max_cache_bytes` via `max(max_cache_bytes, _MIN_FRAME_SIZE_BYTES)` floor; replace module-level constant refs in `_put_frame` (line 98) and `_evict_to_memory_limit` (line 105) | 19, 23, 28, 98, 105 |
| `app_controller.py` | Compute adaptive budget via `load_user_preferences()`; pass to `FrameCache`; NO async QRunnable — rely on `DicomSession.open()` built-in `release_stale_sessions(exclude=self)` | 150-168 |
| `system_profiler.py` | Update `evict_window`: 30→12 (low-end), 40→20 (high-end) | 32, 42 |
| `dicom_session.py` | Add `_sessions_lock` to protect `_all_sessions` list access from concurrent worker threads | 20, 66, 96 |
| `viewer_widget.py` | Remove dead `levels_changed` variable | 1751 |
| `playback_diagnostics.py` | Add `on_instance_switch_start()`, `on_instance_switch_end()`, `on_prefetch_cancel()`, `InstanceSwitchRecord` dataclass | new methods |
| `user_preferences.py` | Add `playback_max_cache_mb: int = 64` field + `_clamp_int` in `load_user_preferences()` | new field |

### 5.2 PlaybackConfig mapping (existing `system_profiler.py:27-45`, values to change)

Current `PlaybackConfig` already detects low/high-end via `detect_playback_config()` (line 48). **Changes needed:**

| Hardware | Current `evict_window` | New `evict_window` | `max_cache_bytes` formula |
|----------|----------------------|-------------------|----------------------|
| Low-end (cores ≤ 4 OR RAM ≤ 8 GB, `system_profiler.py:32`) | 30 (`_LOW_END`) | 12 | `min(64 MB, available * 0.08)` |
| High-end (`system_profiler.py:38`) | 40 (`_HIGH_END`) | 20 | `min(128 MB, available * 0.08)` |

`evict_window` changes from 30→12 and 40→20 to reduce memory pressure on weak PCs. New `max_cache_bytes` is computed at `FrameCache` instantiation time (not in `PlaybackConfig`).

`max_cache_bytes` is NOT added to `PlaybackConfig` — it is computed at `AppController.__init__` from `UserPreferences` + `psutil` and passed directly to `FrameCache`. `PlaybackConfig` only controls `evict_window` (already wired through).

`UserPreferences` gets new field: `playback_max_cache_mb: int = 64` (default 64 MB, matches low-end cache cap). Located near `playback_speed_multiplier` at `user_preferences.py:75`.

### 5.3 Thread safety analysis

- `FrameCache._max_cache_bytes` is set in `__init__` (single-threaded at app startup). No lock needed.
- `_sessions_lock` (`dicom_session.py:21`) protects ALL access to the module-level `_all_sessions` list: `get_thread_dicom_session()` (append + prune), `release_stale_sessions()` (iterate + modify), `_cleanup_all_sessions()` (atexit). Both acquire the lock.
- **No async QRunnable for `release_stale_sessions`** — the original async worker called `release_stale_sessions()` (no `exclude`) concurrently with `DicomDecodeWorker.run()` → `decode_all_frames()` → `ThreadPoolExecutor`. If `release_heavy()` ran mid-decode, setting `self._frames = None` between `pool.submit()` (line 483) and `self._frames[idx] = future.result()` (line 487), it crashes. **Fix: removed the QRunnable; `DicomSession.open()` (line 333) already calls `release_stale_sessions(exclude=self)` on the worker thread BEFORE decoding starts.**
- **`_metadata` is intentionally preserved** in `release_heavy()` (line 592-606): it does NOT touch `_metadata`. `decode_all_frames()` ThreadPoolExecutor workers access `self._metadata.Rows`, `self._metadata.Columns` — if cleared, they crash with `AttributeError: 'NoneType'`.
- **The 8 GB leak was fixed** by removing the `_raw_bytes is not None` guard in `release_stale_sessions()` — now ALL sessions get `release_heavy()` called (except `exclude`). `_metadata` stays alive; only `_raw_bytes`, `_pixel_data_raw`, `_encapsulated_frames`, `_frames` are freed.

### 5.4 PHI compliance verification

| Requirement | Status |
|-------------|--------|
| No disk caching of decoded pixel data | ✅ — only in-memory `FrameCache` with `np.ndarray` |
| Memory budget capped at 128 MB (low-end) | ✅ — `psutil.virtual_memory().available * 0.08` |
| No `tempfile` / `NamedTemporaryFile` | ✅ — no file I/O introduced |
| `chmod 0o600` only on downloaded DICOM (not cache) | ✅ — cache is RAM only |

---

## 6. Error Handling

| Case | Behavior |
|------|----------|
| `psutil` unavailable | Fallback to `2*1024*1024*1024` (2 GB) — no crash |
| `release_stale_sessions` in worker | Exception in QRunnable logged via `logging.exception`, UI continues loading |
| FrameCache `max_cache_bytes` < frame size | First frame triggers `_evict_to_memory_limit` (evicts immediately → re-decode next access). Accept for low-memory; logged as warning |
| User sets `playback_max_cache_mb = 8` (too small) | Validation: `max(max_cache_bytes, frame_size_estimate)` where `frame_size_estimate = 640*480*1.2*0.1` (avg DICOM frame + overhead) |

---

## 7. Testing Strategy

### 7.1 Unit tests (required)

| Test file | Cases |
|-----------|-------|
| `tests/unit/test_frame_cache_memory_budget.py` | (a) `FrameCache(max_cache_bytes=64MB)` evicts at 64 MB; (b) `evict_window` adapts to frame size; (c) `memory_bytes` property reflects actual |
| `tests/unit/test_stale_session_release_async.py` | (a) Worker calls `release_stale_sessions`; (b) callback fires after completion; (c) no `exclude` param needed — thread-local sessions are independent |
| `tests/unit/test_playback_diagnostics_instance_switch.py` | (a) `on_instance_switch_start/end` records RSS delta + elapsed_ms; (b) `on_prefetch_cancel` increments cancel counter |
| `tests/unit/test_levels_changed_cleanup.py` | (a) `levels_changed` no longer in `show_frame_fast` source; (b) W/L output unchanged for cached vs. uncached paths |

### 7.2 Performance regression test

```python
# tests/bench/test_memory_switch.py
def test_file_switch_memory_does_not_grow(benchmark):
    # Open 50 files rapidly, assert RSS delta < 100 MB
```

### 7.3 Manual QA checklist

1. **Weak PC** (4 cores, 8 GB RAM): fast file switching — verify CPU < 15% on switch, RSS < 2 GB after 50 switches
2. **Memory profile**: 64 MB cache visible in FrameCache, evict_window = 12
3. **W/L rendering**: grayscale + color, despeckle enabled, levels sliders moved — pixel-by-pixel identical output vs. baseline
4. **Async release**: verify no UI freeze on file switch; verify no crash when `FrameLoaderWorker` reading a session during release

### 7.4 Out of scope for CI

- Real DICOM file benchmarks (need clinical dataset)
- Memory leak test across >1000 file switches (too slow for CI)

---

## 8. Dependencies

| Dependency | Already in project? | Role |
|------------|-------------------|------|
| `psutil` | ✅ (`system_profiler.py:8`, `playback_diagnostics.py:36`) | `virtual_memory().available` for adaptive budget, RSS tracking |
| `PySide6` | ✅ | `QRunnable`, `QThreadPool`, `Signal` for async worker |
| `numpy` | ✅ | `np.ndarray.nbytes` for FrameCache memory tracking |

No new dependencies required.

---

## 9. Spec Self-Review

- [x] No TBD/placeholder sections
- [x] Scope limited to 4 actionable items (no FFmpeg/GPU/disk cache)
- [x] Correct file paths with line numbers
- [x] Thread safety analysis for async `release_stale_sessions`
- [x] PHI compliance verification table
- [x] Concrete test plan with file names and cases
- [x] No disk I/O introduced for decoded pixel data
- [x] Time estimates realistic (total: 6.5-10 hours)
- [x] Existing patterns reused (`PlaybackConfig`, `_StudyQueryWorker` pattern, `FrameCache`)
- [x] Critical: confirmed `_update_levels()` already has internal cache — dead `levels_changed` is cleanup only, NOT a behavioral fix