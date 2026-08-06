# DICOM / MP4 — Lazy Loading & Performance Optimization Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the performance gap on low-end systems (Win 10, AMD FX-4350, 16 GB RAM, GTX 660) vs high-end (Debian 12, i5-12400, 32 GB RAM, RTX 4060) by adopting Weasis-inspired lazy loading, smart caching, and system-adaptive threading.

**Root cause:** Current code decodes ALL frames of a DICOM/MP4 upfront (`decode_all_frames()`, `VideoDecodeWorker` reading all frames into `np.stack`). On a weak system this means 100% CPU for 30–60 s before first interaction. Weasis decodes ONLY the requested frame — zero work until user scrolls.

**Approach:** 4 priority levels (P0–P3). Each level is self-contained and independently releasable.

**Reference analysis:**
- [`docs/superpowers/plans/2026-06-29-dicom-mp4-lazy-loading.md`](2026-06-29-dicom-mp4-lazy-loading.md) (this file)
- Weasis architecture comparison in AGENTS.md / session context

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/echo_personal_tool/infrastructure/dicom_session.py` | Rewrite | Lazy per-frame decode, raw-byte fast path, parallel decode fallback |
| `src/echo_personal_tool/infrastructure/dicom_reader.py` | Modify | Frame-level LRU cache (`_DecodedPixelCache`) |
| `src/echo_personal_tool/infrastructure/video_reader.py` | Rewrite | Indexed frame access (keyframe index), ring buffer, sequential read optimization |
| `src/echo_personal_tool/application/frame_cache.py` | Rewrite | Sparse dict store, pin/unpin, soft eviction, `require_full_cine()` |
| `src/echo_personal_tool/application/workers/dicom_decode_worker.py` | Modify | Emit first frame only; full decode only on explicit demand |
| `src/echo_personal_tool/application/workers/video_decode_worker.py` | Rewrite | Index video, emit first frame; per-frame load via `FrameLoaderWorker` |
| `src/echo_personal_tool/application/workers/frame_loader_worker.py` | Modify | Accept cancellation token, support priority |
| `src/echo_personal_tool/application/app_controller.py` | Modify | New frame request flow, leading static frame skip, prefetch logic |
| `src/echo_personal_tool/infrastructure/system_profiler.py` | Create | CPU cores, RAM, GPU detection for adaptive config |
| `src/echo_personal_tool/presentation/viewer_widget.py` | Modify | Scroll debounce, cancel in-flight on fast scroll |
| `tests/unit/test_frame_cache.py` | Create | Sparse cache, pin/unpin, eviction, full cine guard |
| `tests/unit/test_dicom_session.py` | Create | Lazy decode, single frame, parallel decode |
| `tests/unit/test_video_reader.py` | Create | Index building, random access, ring buffer |
| `tests/unit/test_system_profiler.py` | Create | Adaptive config values per detected profile |

---

## P0 — Lazy Frame Decoding (DICOM + MP4)

**Problem:** Every file decode reads ALL frames. On a 2000-frame DICOM with JPEG-2000 compression this takes 30–60 s on a GTX 660 system. On RTX 4060 it is 5 s but still wasteful.

**Solution:** Decode only the requested frame on first access. Full decode only when speckle tracking or export requires it (via `require_full_cine()`).

### P0a. `dicom_session.py` — lazy per-frame decode

- `open(path)` → read raw bytes, parse metadata (`stop_before_pixels=True`), detect transfer syntax (uncompressed vs compressed)
- For **uncompressed** (`1.2.840.10008.1.2`, `1.2.840.10008.1.2.1`, `1.2.840.10008.1.2.2`): pre-compute frame byte slices. `decode_first_frame()` slices raw bytes. `decode_single_frame(index)` slices raw bytes — **zero parsing overhead** beyond the first metadata read.
- For **compressed** (JPEG, JPEG-2000, RLE): parse encapsulated fragments, cache fragment list. `decode_single_frame(index)` → `cv2.imdecode(fragment)` for that frame only. `_MAX_DECODE_WORKERS = 4` applies only if parallel decode is explicitly requested.
- `decode_all_frames()` → parallel decode via `ThreadPoolExecutor` — **only called on explicit demand** (speckle tracking, export, or user-initiated full load).
- Remove `stack_pixel_array()` — frames are stored individually, not as a pre-allocated single ndarray.

### P0b. `dicom_decode_worker.py` — first-frame-only by default

- `run()` → session.open(), `decode_first_frame()`, emit `first_frame_ready`, **done**.
- No `decode_all_frames()` call unless `self._full_decode_requested = True` (set by controller when full cine needed).
- New signal `full_decode_finished(request_id, path, dict[int, np.ndarray])` for optional bulk load.

### P0c. `video_reader.py` — indexed random access

- **Two-pass approach:**
  1. **Index pass** (fast): open `cv2.VideoCapture`, scan keyframes using `CAP_PROP_POS_AVI_RATIO` + frame type detection. Build `_keyframe_index: list[int]` — positions of I-frames.
  2. **Data pass** (lazy): `read_frame(index)` → seek to nearest keyframe, decode forward to target frame. Cache result in ring buffer.
- Ring buffer: increase from 100 to **500 frames**. Sequential read optimization (track `_last_read_index` for O(1) sequential access).
- `build_index(path)` → returns frame count, FPS, keyframe positions.

### P0d. `video_decode_worker.py` — index-only, no bulk decode

- `run()` → open video, build index, read first frame only, emit `first_frame_ready`, emit `index_ready(frame_count, fps, keyframes)`, **done**.
- Per-frame loading delegated to `FrameLoaderWorker`.

### P0e. `app_controller.py` — new load flow

```
On instance select:
  if media_format == "dicom":
      launch DicomDecodeWorker(first_frame_only=True)
  elif media_format == "mp4":
      launch VideoDecodeWorker(build_index_only=True)

On frame request (scroll / playback):
  FrameCache.get(index) → hit → emit frame
  miss → FrameLoaderWorker.load(path, index) → emit frame
  FrameCache prefetches ±5 frames asynchronously

On speckle tracking:
  FrameCache.require_full_cine() → if incomplete, trigger full decode
```

**Key additions to `AppController`:**
- `_pending_frame_requests: dict[int, FrameLoaderWorker]` — track in-flight requests by frame index
- `_cancel_frame_request(index)` — cancel and remove from dict
- `prefetch_frames(center, radius=5)` — background load adjacent frames (via low-priority `QThreadPool`)

### Acceptance criteria (P0)

1. Open 2000-frame DICOM → visible first frame in < 500 ms on any system
2. Open 2000-frame MP4 → visible first frame in < 500 ms
3. Scroll through frames → no freeze, frames load progressively
4. Playback → smooth at 30 fps after ring buffer warms up
5. Memory: only decoded frames in eviction window (~80 frames) resident at rest

---

## P1 — Smart Cache with Pin/Unpin

### P1a. `frame_cache.py` rewrite

```python
class FrameCache:
    _store: dict[int, np.ndarray]  # frame_index → pixels
    _pinned: set[int]  # indices protected from eviction
    _total_frames: int
    _current_index: int
    _evict_window: int = 40  # default (adaptive: system_profiler)
    _max_memory_bytes: int = 512 * 2**20
```

**Pin/Unpin:**
- `pin(index)` — adds to `_pinned`, never evicted until unpinned
- `unpin(index)` — removes from `_pinned`
- `set_current(index)` → pin new, unpin previous, trigger `_evict()`
- `_evict()` skips pinned indices, drops oldest-first among unpinned ones outside window

**Soft (memory-based) eviction:**
- `memory_bytes()` compared to `_max_memory_bytes` on each `put()`
- If exceeded, evict unpinned frames farthest from `_current_index` until under 80 % threshold

**Full cine guard:**
- `require_full_cine()` → raises `IncompleteCineError` if `len(_store) < _total_frames`
- Loads missing frames via `FrameLoaderWorker` when auto-recovery is enabled

### P1b. Wire pin/unpin in `viewer_widget.py`

- `show_frame()` / `show_frame_fast()` → emit `frame_pinned(index)`
- `AppController` → `frame_cache.set_current(index)` → pins visible frame, unpins previous

### P1c. Scroll debounce in `viewer_widget.py`

- Mouse wheel → 50 ms debounce timer → emit `frame_selected(value)` only after debounce fires
- Cancel in-flight `FrameLoaderWorker` for stale frame indices

### Acceptance criteria (P1)

1. Rapid scroll (wheel) → only last frame actually loads, no backlog of cancelled workers
2. Visible frame is never evicted from cache (always in `_pinned`)
3. `require_full_cine()` raises a clear `IncompleteCineError` when frames are missing
4. Cache memory stays under configured budget

---

## P2 — System-Adaptive Configuration

### P2a. `system_profiler.py`

```python
@dataclass(frozen=True)
class SystemProfile:
    cpu_cores: int  # os.cpu_count()
    total_ram_gb: float  # psutil.virtual_memory().total / 1e9
    has_gpu: bool  # try: cv2.cuda.getCudaEnabledDeviceCount()
    gpu_vram_gb: float  # nvidia-smi, pyadl, or 0
    is_low_end: bool  # cores <= 4 OR ram <= 16 OR no GPU
```

**Adaptive config mapping:**

| Parameter | Low-end | High-end |
|-----------|---------|----------|
| `MAX_DECODE_WORKERS` | 2 | 4 |
| `EVICT_WINDOW` | 30 | 200 |
| `FRAME_CACHE_MAX_MB` | 256 | 1024 |
| `RING_BUFFER_SIZE` | 200 | 1000 |
| `PRELOAD_RADIUS` | 2 | 10 |
| `THREAD_POOL_MAX` | `cores` | `cores * 2` |

### P2b. Adaptive thread pool

- Replace default `QThreadPool` with custom size derived from `SystemProfile`:
  ```
  IO pool:    max(2, min(cores * 2, ram_gb * 10))
  CPU pool:   max(1, min(cores + 1, ram_gb * 3))
  ```
- `CallerRunsPolicy` equivalent: if queue is full, execute the task on the calling thread (backpressure)

### Acceptance criteria (P2)

1. Low-end system detected → conservative cache / thread settings applied
2. High-end system detected → aggressive preloading enabled
3. Thread pool never exceeds safe memory budget
4. No regression on current Debian 12 / RTX 4060 setup

---

## P3 — Timeout, Cancellation & Soft Metadata

### P3a. Timeout on decode

- `FrameLoaderWorker` → internal `QTimer` for 30 s timeout
- On timeout → emit `failed("Decode timeout")`, clean up session
- `AppController` → track in-flight workers, reset state on timeout

### P3b. Cancellation

- `FrameLoaderWorker` → accept `cancel_token: threading.Event`
- On cancel → `session.release()`, skip frame processing, emit nothing
- `AppController._pending_frame_requests` → on new request for same index, cancel old one first

### P3c. Soft-reference metadata cache

- `dicom_reader.py` → store parsed pydicom `Dataset` in `WeakValueDictionary` keyed by resolved path
- On cache hit → skip `pydicom.dcmread(stop_before_pixels=True)`
- On cache miss (GC reclaimed) → re-read from disk

### Acceptance criteria (P3)

1. Corrupt DICOM file → timeout after 30 s, no UI freeze
2. Rapid scroll → previous frame requests are cancelled, not stacked
3. Re-opening same file → metadata served from cache, faster open

---

## Risks & Mitigations

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| cv2 keyframe index unreliable on some codecs | Medium | Fall back to sequential scan on index build failure; cache index to disk |
| `require_full_cine()` called before frames loaded | Low | Clear `IncompleteCineError` + auto-trigger full decode with progress bar |
| Memory spikes during parallel full decode | Low | Throttle `MAX_DECODE_WORKERS` based on `SystemProfile` |
| Regression on high-end system | Medium | Profile on RTX 4060 before / after; same or better performance expected |
| Race condition on `_pending_frame_requests` | Medium | Controller mutates dict on main thread only; use `QMetaObject.invokeMethod` for cross-thread additions |

---

## Test Plan

| Test file | Covers |
|-----------|--------|
| `tests/unit/test_dicom_session.py` | Lazy decode, single frame, parallel fallback, raw-byte fast path |
| `tests/unit/test_frame_cache.py` | Sparse store, pin/unpin, eviction, `require_full_cine()`, `memory_bytes()` |
| `tests/unit/test_video_reader.py` | Keyframe index, ring buffer, sequential read, random seek |
| `tests/unit/test_system_profiler.py` | Adaptive config values per detected profile |
| Manual: open 2000-frame DICOM on Win 10 / GTX 660 | First frame < 500 ms, scroll responsive |
| Manual: playback 2000-frame MP4 on Win 10 | Smooth 30 fps after warm-up |
