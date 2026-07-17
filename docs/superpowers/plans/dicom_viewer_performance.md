# DICOM Viewer Performance Improvement Plan

## Context

Research into DICOM viewers (Cornerstone3D, OHIF, DWV, pydicom patterns) combined with analysis of our current architecture. The goal is to improve playback smoothness, scroll responsiveness, and memory efficiency in our PyQt/PyQtGraph echocardiography viewer.

**Current pipeline**: DICOM file → DicomSession (thread-local, ThreadPoolExecutor 4) → FrameCache (sparse dict, LRU) → AppController (playback timer + prefetch) → ViewerWidget (pyqtgraph ImageItem).

---

## Phase 1 — Data Structure Fixes (2h, zero risk)

### 1.1 `deque` for VideoReader ring buffer
**File**: `src/echo_personal_tool/infrastructure/video_reader.py:194`
- `list.pop(0)` is O(n) per eviction. Replace `_buffer_order: list` with `deque`, use `.popleft()`.
- ~1500 element shifts/sec at 30fps with 50-slot buffer.

### 1.2 Memoize `FrameCache.frames` property
**File**: `src/echo_personal_tool/application/frame_cache.py:29-35`
- Stacks all cached frames into numpy array on every call. No caching.
- Add `_cached_full` attribute, invalidate on `put()`/`_evict()`/`clear()`/`load()`.

### 1.3 Eliminate double-copy in DICOM batch loading
**File**: `src/echo_personal_tool/application/workers/frame_loader_worker.py`
- `read_frame()` returns `.copy()`, then `_run_batch()` wraps in `np.ascontiguousarray()`.
- Call `decode_single_frame()` directly — always contiguous, no copy needed.

### 1.4 Optimize `_evict()` with sorted keys
**File**: `src/echo_personal_tool/application/frame_cache.py:141-149`
- Iterates all cached frames on every tick. Maintain `_sorted_keys` list with `bisect.insort`.
- Eviction becomes O(log n + k) where k = frames to drop, instead of O(n).

---

## Phase 2 — Rendering Path (3h, low risk)

### 2.1 ~~Skip float64 during fast playback~~ [ALREADY DONE]
The latest code at `viewer_widget.py:1449-1455` already passes uint8 directly to PyQtGraph. No action needed.

### 2.2 Cache color conversion across identical frames
**File**: `src/echo_personal_tool/presentation/viewer_widget.py:1439-1446`
- `to_display_rgb()` creates new RGB array every frame even when buffer is unchanged.
- Track buffer identity via `id(frame)` or `frame.ctypes.data`, skip if unchanged.

### 2.3 Double-next frame skip on cache miss
**File**: `src/echo_personal_tool/application/app_controller.py` (playback tick)
- When `next_idx` is missing but `next_idx+1` is loaded, skip forward by 2 to avoid poll-loop stutter.

---

## Phase 3 — Decode Parallelism (4h, medium risk)

### 3.1 Multi-threaded DICOM batch decode
**File**: `src/echo_personal_tool/application/workers/frame_loader_worker.py`
- Batch decode loops sequentially. Parallelize with `ThreadPoolExecutor(4)`.
- Each thread uses `get_thread_dicom_session()` (thread-local). `_raw_bytes` is immutable — safe for concurrent reads.
- Must call `open()` from main worker thread first to build encapsulated frame index.

### 3.2 Adaptive prefetch sizing
**File**: `src/echo_personal_tool/application/app_controller.py`
- `batch_size` is fixed at startup. Measure each batch wall-clock time.
- Dynamically adjust: increase by 2 if avg < 10ms, decrease by 1 if avg > 60ms. Clamp [2, 16].

---

## Phase 4 — Architecture (8h, medium risk)

### 4.1 Extract FrameRenderer from ViewerWidget
**New file**: `presentation/frame_renderer.py`
- Extract `show_frame()`/`show_frame_fast()` hot paths (~170 lines + ~30 instance vars).
- ViewerWidget keeps `self._renderer` and delegates rendering. Overlays/contours stay in ViewerWidget.

### 4.2 Extract PlaybackEngine from AppController
**New file**: `application/playback_engine.py`
- Extract timer, prefetch, warm-up, lag-skip logic (~15 instance variables).
- AppController wires `self._playback_engine.tick()` via signal connection.

---

## Phase 5 — Optional (10h+, only after profiling Phases 1-3)

- **5.1** float32 for W/L grayscale (halve memory vs float64)
- **5.2** Direct QImage construction bypassing ImageItem (high risk)
- **5.3** Memory-mapped frame store for large cines > 300 frames

---

## Measurement Strategy

Before any changes, establish baselines with `ECHO_PROFILE=1`:
1. Playback FPS (actual vs target interval)
2. Prefetch batch latency (start → callback)
3. `_evict()` cost (1000 calls with 200-frame cache)
4. `show_frame_fast` p50/p95/p99

After each phase, re-run benchmarks and record delta.

## Verification

- Run existing test suite after each phase
- Visual comparison of B-mode and color Doppler cine playback
- Manual test with large (> 300 frame) and small (< 30 frame) cines
- Memory monitoring during extended playback sessions

## Implementation Order

```
Phase 1 (all) → test suite → commit
Phase 2 (2.2-2.3) → visual check → commit
Phase 3 (3.1-3.2) → benchmark → commit
Phase 4.1 (FrameRenderer) → tests → commit
Phase 4.2 (PlaybackEngine) → tests → commit
Phase 5 only if profiling justifies
```
