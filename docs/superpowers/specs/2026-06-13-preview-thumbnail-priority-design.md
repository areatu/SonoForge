# Preview-Only Thumbnail Priority Loading Design Spec

**Date:** 2026-06-13  
**Status:** Draft for review  
**Context:** Folder open latency is currently ~22s until full thumbnail draw and practical readiness.

## Goal

Make study folders usable quickly while preserving the clinical workflow where the user must visually identify cardiac position from thumbnails before opening the instance in the main viewer.

The MVP in this spec is **preview-only thumbnails** (64-96 px). No second high-quality thumbnail pass is included.

## User workflow constraints (approved)

1. User navigates chronologically and may need to start from an arbitrary item (for example, around item 15).
2. Thumbnail visibility is mandatory to confirm required view (for example, 4C vs LAX LV) before loading into the main window.
3. Device export can include still first-frame files before each cine; these files remain in the folder and cannot be removed.
4. "Ready to work" means:
   - thumbnails in visible region are quickly usable,
   - selected file can load into main viewer immediately without waiting for full-folder thumbnail completion.

## Scope

### In scope (MVP)

- Priority queue for thumbnail preview jobs.
- Lazy and visibility-driven thumbnail scheduling.
- Preview-only generation (64-96 px; default 96 px).
- Non-blocking main-viewer file loading.
- Dedup/in-flight guard for thumbnail tasks.

### Out of scope (MVP)

- High-quality thumbnail second pass.
- Automatic hiding/grouping of Device still duplicates.
- Persistent thumbnail cache on disk.
- Major DICOM decode backend replacement.

## Problem statement in current architecture

1. Browser population eagerly requests series thumbnails for all expanded series.
2. DICOM thumbnail path can trigger heavy decode behavior (full-frame decode path), creating high startup cost when many cine instances exist.
3. Main readiness is coupled to broad thumbnail work instead of visible/selected priorities.
4. Scanner reads are not yet optimized for repeated metadata calls on same DICOM path (separate optimization track).

## Target architecture

### High-level data flow

1. Folder scan returns study/series/instance metadata.
2. UI tree is populated immediately from metadata.
3. Thumbnail scheduler enqueues preview jobs with priorities:
   - `P0`: selected instance and currently visible tree rows.
   - `P1`: window around visible rows (for example, +/-20).
   - `P2`: remaining instances in background chronological order.
4. Scheduler runs a small worker budget for preview jobs (for example, 2 concurrent jobs).
5. Each completed preview updates browser icon cache and repaints only affected rows.
6. File selection triggers main-viewer load immediately; this path is never blocked by preview backlog.

### Priority policy

- Selected item is always highest priority.
- Visible range is next highest priority.
- On scroll/expand, priorities are recalculated and stale low-priority jobs are deprioritized or dropped if not started.
- Existing preview cache or in-flight job prevents duplicate scheduling.

### Readiness policy

Folder is considered ready for interaction when:
- tree is shown,
- visible rows have preview thumbnails (or are in immediate P0 processing),
- selecting an instance starts main-viewer loading immediately.

## Detailed component changes

### `src/echo_personal_tool/presentation/local_browser.py`

- Remove eager all-series thumbnail requests at initial populate.
- Add viewport-aware scheduling hooks:
  - on populate complete,
  - on scroll,
  - on item expand,
  - on selection.
- Request previews via controller with explicit priority class (`P0`, `P1`, `P2` intent).

### `src/echo_personal_tool/application/app_controller.py`

- Introduce thumbnail scheduling API instead of direct worker fire-and-forget.
- Maintain thumbnail task state:
  - queued,
  - in-flight,
  - completed cache.
- Enforce preview worker concurrency limit independent from main frame loading responsiveness.
- Ensure instance load path has effective priority over thumbnail background work.

### `src/echo_personal_tool/application/workers/thumbnail_loader_worker.py`

- Add preview mode configuration:
  - size 64-96 px (default 96),
  - lightweight conversion path.
- Keep representative frame policy for cine/DICOM (middle frame) for preview consistency.
- Keep output signal contract unchanged to minimize integration risk.

### New module: `src/echo_personal_tool/application/thumbnail_scheduler.py`

- Responsibility:
  - priority queue management,
  - dedup and in-flight guard,
  - bounded dispatch.
- No UI rendering logic and no decode logic in this module.

### `src/echo_personal_tool/presentation/main_window.py` (integration)

- Keep existing browser-controller wiring.
- Trigger initial visible-region preview scheduling after studies loaded.
- Do not wait for global thumbnail completion before allowing selection and load.

## Error handling

- Preview failure for one instance does not fail folder load.
- Failed thumbnail task is marked and can be retried on explicit user revisit (scroll/select).
- If decode fails for selected instance, show existing load error pathway; this remains independent of thumbnail queue.

## Performance targets (MVP)

For dataset profile similar to current report (51 files, 14 cine):

1. Initial tree render: under 2s on baseline machine.
2. First visible-window previews: under 3s after tree appears.
3. Selecting any visible item starts main-viewer load immediately (no dependency on remaining preview queue).
4. Full-folder preview completion may continue in background and is not a readiness gate.

## Metrics and instrumentation

Add lightweight timing logs/counters for:
- scan duration,
- tree populate duration,
- time-to-first-visible-preview,
- queue depth by priority,
- time from item click to frame load signal.

These metrics are required to verify improvements against the current ~22s workflow delay.

## Test strategy

### Unit tests

1. Thumbnail scheduler:
   - P0 before P1/P2,
   - dedup behavior,
   - bounded concurrency dispatch,
   - stale low-priority drop/deprioritize behavior.
2. Browser scheduling:
   - populate does not enqueue all instances immediately,
   - visible range drives requests,
   - scroll changes request set.
3. Controller behavior:
   - selected instance load path not blocked by thumbnail backlog.

### Integration-style tests (existing Qt test setup)

- Simulate tree with many instances:
  - verify previews appear first in visible region,
  - verify selecting off-screen/just-scrolled item can still load in main viewer without waiting for global thumbnail completion.

## Risks and mitigations

1. **Risk:** UI churn from frequent scroll-based rescheduling.  
   **Mitigation:** Debounce viewport-change events (short interval).
2. **Risk:** Queue complexity introduces race conditions.  
   **Mitigation:** Single-owner scheduler state in controller thread; workers remain stateless.
3. **Risk:** Preview quality insufficient for clinical identification in edge cases.  
   **Mitigation:** Size configurable (64/80/96); default 96 for safer recognition.

## Acceptance criteria

1. User can scroll to an arbitrary position (for example, item ~15), quickly see meaningful preview thumbnails, and select the target view.
2. Main viewer load starts immediately on selection even if many thumbnails are still pending.
3. No full-quality thumbnail pass exists in MVP; only preview thumbnails are generated.
4. No regression in existing load error handling and thumbnail signal wiring.

## Implementation follow-up

After this spec is approved:
- create detailed task plan with `writing-plans`,
- implement MVP preview-only scheduler path first,
- evaluate whether Device still/cine dedup UX should be next-phase spec.
