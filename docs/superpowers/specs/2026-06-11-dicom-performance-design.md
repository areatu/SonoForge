# DICOM Performance — Decode-on-open + FrameCache

**Date:** 2026-06-11  
**Status:** Approved  
**Scope:** UI performance for DICOM cine loops (items 2 and 4 from UI feedback)  
**Out of scope:** Color rendering, thumbnails, measurement tools, window/level enhancements

---

## Problem

DICOM frame access currently calls `pydicom.dcmread()` and decodes the full `pixel_array` on **every** frame request (`DicomReaderImpl.read_pixels`). Playback and timeline scrubbing each spawn a `FrameLoaderWorker`, so the UI achieves less than 1 fps. MP4 already uses a thread-local `VideoReader` with a ring buffer; DICOM has no equivalent session or cache.

## Goal

After a one-time decode when the user selects a DICOM instance:

- Sequential playback (Play) at **≥15 fps** (native FPS capped by timer interval).
- Timeline scrubbing with **instant** frame display (no per-frame worker).
- First-open latency acceptable with a clear “Decoding…” status; slider disabled until ready.

## Chosen Approach

**Decode-on-open + in-memory `FrameCache`** (Approach 1).

Rejected alternatives:

- **Ring buffer only** — fast forward play but slow random scrub.
- **Per-frame GDCM decode** — transfer-syntax dependent, high complexity, does not meet scrub requirement without a full cache.

## Architecture

```
ViewerWidget / Slider
        ↓ frame_selected / timer
   AppController
        ↓                    ↓
  StateManager          FrameCache  ←── DicomDecodeWorker
        ↓                    ↑              ↓
   (frame index)         O(1) get      DicomSession
        ↓
  frame_loaded → ViewerWidget.show_frame()
```

**Key rule:** When `FrameCache` is ready for the current DICOM instance, `AppController` must **not** dispatch `FrameLoaderWorker` per frame. It emits `frame_loaded` synchronously from the cache.

MP4, JPEG, and PNG keep the existing `FrameLoaderWorker` path unchanged.

## Components

### 1. `DicomSession` (infrastructure)

**File:** `src/echo_personal_tool/infrastructure/dicom_session.py`

Responsibilities:

- Open a DICOM file once (`open(path)`).
- Decode all frames into a contiguous `np.ndarray` of shape `(N, H, W)` (grayscale; RGB handling unchanged from current `DicomReaderImpl` for this sprint).
- Expose `read_frame(index) -> np.ndarray` as a view/copy of one frame.
- `release()` to drop references.

Thread-local accessor (mirror `get_thread_video_reader`):

```python
def get_thread_dicom_session() -> DicomSession: ...
```

`DicomReaderImpl.read_pixels` may delegate to `DicomSession` for backward compatibility in workers, or workers call `DicomSession` directly — implementation choice; behavior must not regress single-frame reads in tests.

Frame extraction logic moves from `DicomReaderImpl.read_pixels` into `DicomSession._extract_frame(pixel_array, frame_index)` to avoid duplication.

### 2. `FrameCache` (application)

**File:** `src/echo_personal_tool/application/frame_cache.py`

```python
@dataclass
class FrameCache:
    source_path: Path | None = None
    frames: np.ndarray | None = None  # (N, H, W)

    def is_ready(self, path: Path) -> bool: ...
    def load(self, path: Path, frames: np.ndarray) -> None: ...
    def get(self, index: int) -> np.ndarray: ...
    def clear(self) -> None: ...
    def frame_count(self) -> int: ...
    def memory_bytes(self) -> int: ...
```

- Holds frames for **one** instance at a time.
- `clear()` on instance switch or load failure.
- `get()` raises `IndexError` for out-of-range indices (caller validates against `StateManager`).

### 3. `DicomDecodeWorker` (application/workers)

**File:** `src/echo_personal_tool/application/workers/dicom_decode_worker.py`

- Input: `path: Path`, `request_id: int`
- Runs on `QThreadPool`.
- Uses thread-local `DicomSession`: `open(path)` → decode all frames → emit `(request_id, path, frames)`.
- Signals: `finished(request_id, path, frames)`, `failed(request_id, message)`.
- Parent QObject pattern matches `FrameLoaderWorker`.

### 4. `AppController` changes

**File:** `src/echo_personal_tool/application/app_controller.py`

`load_instance` for `media_format == "dicom"`:

1. `FrameCache.clear()`
2. Reset loaded/pending frame tracking (as today).
3. `StateManager.set_instance(...)` — timeline disabled via viewer state until decode completes (see UX).
4. Increment decode request id; start `DicomDecodeWorker`.
5. Status: `Decoding {filename}… ({N} frames)`

On `DicomDecodeWorker.finished` (stale-request guard same as frame loader):

1. `FrameCache.load(path, frames)`
2. If `memory_bytes > 512 * 1024 * 1024`: status warning (non-blocking).
3. Set `_loaded_source_path`, `_loaded_frame_index`, emit frame 0 (or current `current_frame_index`).
4. Status: `Ready`

On decode `failed`: `frame_load_failed`, `FrameCache.clear()`.

`_request_frame_if_needed`:

- If DICOM and `FrameCache.is_ready(current path)`:
  - Copy frame from cache, update `_loaded_*`, `frame_loaded.emit()` — **no worker**.
- Else if DICOM and decode in progress: no-op (wait).
- Else: existing `FrameLoaderWorker` path (MP4/JPEG/PNG).

`_advance_playback`:

- For cached DICOM: do **not** block on `_pending_load_id` (there is none per frame).
- For MP4: keep existing pending-load gate.

### 5. `ViewerWidget` / timeline UX

**File:** `src/echo_personal_tool/presentation/viewer_widget.py`

- Timeline slider and Play button disabled while DICOM decode is in progress.
- Option A (preferred): add `decode_in_progress: bool` to `ViewerState`.
- Option B: `total_frames > 0` but `instance` set with a new flag on metadata — avoid; use `ViewerState`.

**File:** `src/echo_personal_tool/domain/models/viewer_state.py`

Add field:

```python
decode_in_progress: bool = False
```

`StateManager.set_instance` sets `decode_in_progress=True` for DICOM until controller clears it after cache load. MP4/JPEG/PNG: `False`.

## Data Flow

### Open DICOM instance

1. User clicks instance in browser.
2. `AppController.load_instance` → `decode_in_progress=True` → UI disables scrub/play.
3. `DicomDecodeWorker` decodes in background.
4. Cache populated → first frame shown → `decode_in_progress=False` → scrub/play enabled.

### Scrub / Play (cache ready)

1. `StateManager.set_frame(index)` or timer tick.
2. `AppController._request_frame_if_needed` → `FrameCache.get(index)` → `frame_loaded`.
3. `ViewerWidget.show_frame` — same as today.

### Switch instance

1. New decode starts; old `FrameCache` cleared immediately to free memory.

## Error Handling

| Case | Behavior |
|------|----------|
| Corrupt / unreadable DICOM | `failed` signal → `QMessageBox` via existing `frame_load_failed` |
| User switches instance during decode | Stale `request_id` ignored (same pattern as `_on_frame_loaded`) |
| `NumberOfFrames` mismatch | Trust decoded array length; update `total_frames` if needed |
| Out-of-memory during decode | Catch exception, fail with message, clear cache |

## Memory

- One cache per active DICOM instance only.
- Typical echo: 30–60 frames × 800×600 × 2 bytes ≈ 30–60 MB — acceptable.
- Warn in status bar if estimated size exceeds 512 MB; still decode (no hard reject in v1).

## Testing

### New fixtures

**File:** `tests/fixtures/generate_synthetic_dicom.py`

Add `write_synthetic_multiframe_dicom(path, frame_count=10, rows=64, cols=64)` using `NumberOfFrames` and multi-frame `PixelData`.

### Unit tests

| File | Cases |
|------|-------|
| `tests/unit/test_dicom_session.py` | open/release; multiframe shape; frame index bounds; thread-local isolation |
| `tests/unit/test_frame_cache.py` | load/get/clear/is_ready; memory_bytes |
| `tests/unit/test_dicom_decode_worker.py` | qtbot worker finished/failed signals |
| `tests/unit/test_app_controller_dicom_cache.py` | after decode, frame change does not start FrameLoaderWorker; stale request ignored |

### Regression

- Existing `test_frame_loader_worker.py` — DICOM path still works for uncached reads (thumbnails).
- `pytest` full suite must pass.

### Performance smoke (optional, not CI-gated)

- 50-frame synthetic cine: 100 random `FrameCache.get` calls complete in <100 ms total.

## Files to Create / Modify

| Action | Path |
|--------|------|
| Create | `src/echo_personal_tool/infrastructure/dicom_session.py` |
| Create | `src/echo_personal_tool/application/frame_cache.py` |
| Create | `src/echo_personal_tool/application/workers/dicom_decode_worker.py` |
| Modify | `src/echo_personal_tool/infrastructure/dicom_reader.py` |
| Modify | `src/echo_personal_tool/application/app_controller.py` |
| Modify | `src/echo_personal_tool/domain/models/viewer_state.py` |
| Modify | `src/echo_personal_tool/application/state_manager.py` |
| Modify | `src/echo_personal_tool/presentation/viewer_widget.py` |
| Modify | `tests/fixtures/generate_synthetic_dicom.py` |
| Create | `tests/unit/test_dicom_session.py` |
| Create | `tests/unit/test_frame_cache.py` |
| Create | `tests/unit/test_dicom_decode_worker.py` |
| Create | `tests/unit/test_app_controller_dicom_cache.py` |

## Implementation Tasks (for plan)

1. **T1** — `DicomSession` + multiframe fixture + tests  
2. **T2** — `FrameCache` + tests  
3. **T3** — `DicomDecodeWorker` + tests  
4. **T4** — `ViewerState.decode_in_progress` + viewer disable UX  
5. **T5** — `AppController` wiring (decode on load, fast path, playback)  
6. **T6** — Integration tests + full `pytest` run  

## Success Criteria

- [ ] Selecting a multiframe DICOM shows “Decoding…” then first frame without per-frame reload delay.
- [ ] Scrubbing timeline after decode updates viewer immediately (no visible lag at ≥15 fps effective).
- [ ] Play advances at native FPS (timer interval from `frame_time_ms`).
- [ ] MP4/JPEG/PNG behavior unchanged.
- [ ] All existing and new unit tests pass.
