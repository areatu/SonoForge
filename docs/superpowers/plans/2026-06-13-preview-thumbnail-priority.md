# Preview-Only Thumbnail Priority Loading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Make folder workflow usable quickly by rendering only lightweight preview thumbnails first (64-96 px), prioritizing visible/selected items, while keeping main viewer loading independent from thumbnail backlog.

**Architecture:** Add a dedicated thumbnail scheduler with priority queue + dedup/in-flight tracking, integrate it into `AppController`, and switch `LocalBrowserWidget` to visibility-driven thumbnail requests instead of eager all-series scheduling.

**Tech Stack:** Python 3.11+, PySide6, NumPy, pytest, pytest-qt.

**Spec:** [2026-06-13-preview-thumbnail-priority-design.md](../specs/2026-06-13-preview-thumbnail-priority-design.md)

---

## File map

- Create: `src/echo_personal_tool/application/thumbnail_scheduler.py` — priority queue, dedup, bounded dispatch for preview tasks.
- Modify: `src/echo_personal_tool/application/app_controller.py` — scheduler integration, thumbnail dispatch API, worker budget.
- Modify: `src/echo_personal_tool/presentation/local_browser.py` — visible-range driven thumbnail requests.
- Modify: `src/echo_personal_tool/application/workers/thumbnail_loader_worker.py` — preview size mode (default 96 px).
- Create: `tests/unit/test_thumbnail_scheduler.py` — scheduler behavior unit tests.
- Modify: `tests/unit/test_thumbnail_qimage.py` — preview-size coverage.
- Create: `tests/unit/test_local_browser_thumbnail_requesting.py` — lazy/visible scheduling tests.
- Modify: `tests/unit/test_app_controller_dicom_cache.py` (or create dedicated controller thumbnail test) — non-blocking viewer-load behavior.
- Modify: `CHANGELOG_SESSION.md` — concise entry for logic change.

---

### Task 1: Build thumbnail scheduler core

**Files:**
- Create: `src/echo_personal_tool/application/thumbnail_scheduler.py`
- Create: `tests/unit/test_thumbnail_scheduler.py`

- [x] **Step 1: Write failing tests for priority + dedup + in-flight**

Add tests that verify:

```python
def test_scheduler_dispatches_p0_before_p1_and_p2(): ...
def test_scheduler_deduplicates_same_uid(): ...
def test_scheduler_respects_max_in_flight_limit(): ...
def test_scheduler_marks_done_and_dispatches_next(): ...
```

- [x] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/unit/test_thumbnail_scheduler.py -v`  
Expected: FAIL (module or symbols missing).

- [x] **Step 3: Implement scheduler module**

Implement:

```python
from dataclasses import dataclass
from enum import IntEnum
import heapq

class ThumbnailPriority(IntEnum):
    P0_VISIBLE_SELECTED = 0
    P1_NEAR_VISIBLE = 1
    P2_BACKGROUND = 2

@dataclass(frozen=True)
class ThumbnailTask:
    sop_instance_uid: str
    priority: ThumbnailPriority
    generation: int

class ThumbnailScheduler:
    def enqueue(self, uid: str, priority: ThumbnailPriority) -> bool: ...
    def next_batch(self, limit: int) -> list[ThumbnailTask]: ...
    def mark_done(self, uid: str) -> None: ...
    def mark_failed(self, uid: str) -> None: ...
    def reprioritize(self, uids: list[str], priority: ThumbnailPriority) -> None: ...
```

Behavior requirements:
- no duplicate queue entries for same UID,
- in-flight guard,
- higher priority wins,
- bounded dispatch count.

- [x] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/unit/test_thumbnail_scheduler.py -v`  
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/echo_personal_tool/application/thumbnail_scheduler.py tests/unit/test_thumbnail_scheduler.py
git commit -m "feat: add priority thumbnail scheduler for preview tasks"
```

---

### Task 2: Add preview-only behavior in thumbnail worker

**Files:**
- Modify: `src/echo_personal_tool/application/workers/thumbnail_loader_worker.py`
- Modify: `tests/unit/test_thumbnail_qimage.py`

- [x] **Step 1: Write failing tests for preview sizing**

Add tests for:

```python
def test_numpy_pixels_to_qimage_preview_uses_requested_size(): ...
def test_preview_default_size_is_96(): ...
```

- [x] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/unit/test_thumbnail_qimage.py -v`  
Expected: FAIL on missing preview size path/default.

- [x] **Step 3: Implement preview mode (single pass only)**

Add constructor options:

```python
class ThumbnailLoaderWorker(QRunnable):
    def __init__(..., preview_size: int = 96, preview_only: bool = True, ...):
        self._preview_size = preview_size
        self._preview_only = preview_only
```

Use only preview render path in `run()`:

```python
image = numpy_pixels_to_qimage(pixels, size=self._preview_size)
```

No final HQ re-render scheduling in this task.

- [x] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/unit/test_thumbnail_qimage.py tests/unit/test_thumbnail_frame_index.py -v`  
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/echo_personal_tool/application/workers/thumbnail_loader_worker.py tests/unit/test_thumbnail_qimage.py
git commit -m "feat: switch thumbnail worker to preview-only sized rendering"
```

---

### Task 3: Integrate scheduler into AppController

**Files:**
- Modify: `src/echo_personal_tool/application/app_controller.py`
- Modify/Create: `tests/unit/test_app_controller_thumbnail_priority.py`

- [x] **Step 1: Write failing tests for non-blocking load + priority dispatch**

Add tests that assert:

```python
def test_load_instance_not_blocked_by_thumbnail_backlog(): ...
def test_p0_thumbnail_request_preempts_background(): ...
def test_pending_thumbnail_set_replaced_by_scheduler_state(): ...
```

- [x] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/unit/test_app_controller_thumbnail_priority.py -v`  
Expected: FAIL (new behavior absent).

- [x] **Step 3: Implement controller integration**

Add fields in `AppController.__init__`:

```python
self._thumbnail_scheduler = ThumbnailScheduler()
self._thumbnail_max_in_flight = 2
self._thumbnail_in_flight: dict[str, ThumbnailPriority] = {}
```

Add APIs:

```python
def request_thumbnail_preview(self, instance: InstanceMetadata, priority: ThumbnailPriority) -> None: ...
def request_thumbnail_previews(self, instances: list[InstanceMetadata], priority: ThumbnailPriority) -> None: ...
def _pump_thumbnail_queue(self) -> None: ...
```

On worker completion/failure:
- call `mark_done/mark_failed`,
- remove from in-flight,
- pump next tasks.

Keep `load_instance()` path untouched by thumbnail queue waits.

- [x] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/unit/test_app_controller_thumbnail_priority.py tests/unit/test_app_controller_dicom_cache.py -v`  
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/echo_personal_tool/application/app_controller.py tests/unit/test_app_controller_thumbnail_priority.py
git commit -m "feat: integrate priority thumbnail scheduler into app controller"
```

---

### Task 4: Make LocalBrowser visibility-driven (lazy)

**Files:**
- Modify: `src/echo_personal_tool/presentation/local_browser.py`
- Create: `tests/unit/test_local_browser_thumbnail_requesting.py`

- [x] **Step 1: Write failing tests for request behavior**

Add tests:

```python
def test_populate_does_not_request_all_thumbnails_immediately(qtbot): ...
def test_selection_requests_p0_for_clicked_instance(qtbot): ...
def test_expand_or_scroll_requests_visible_window(qtbot): ...
```

Use a fake loader callback recording requested UID + priority.

- [x] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/unit/test_local_browser_thumbnail_requesting.py -v`  
Expected: FAIL (current eager behavior).

- [x] **Step 3: Implement browser lazy scheduling hooks**

Required changes:
- remove eager full-series requests in `populate()`,
- add helper methods:

```python
def request_visible_previews(self) -> None: ...
def _collect_visible_instances(self) -> list[InstanceMetadata]: ...
def _collect_nearby_instances(self, padding: int = 20) -> list[InstanceMetadata]: ...
```

- on selection: request selected item with P0,
- on expand/scroll: request visible + nearby windows.

If scrolling signal is unavailable directly, connect to vertical scrollbar value change.

- [x] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/unit/test_local_browser_thumbnail_requesting.py tests/unit/test_local_browser_labels.py -v`  
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/echo_personal_tool/presentation/local_browser.py tests/unit/test_local_browser_thumbnail_requesting.py
git commit -m "feat: lazy visibility-based thumbnail preview requests in local browser"
```

---

### Task 5: Wire MainWindow trigger + instrumentation + changelog

**Files:**
- Modify: `src/echo_personal_tool/presentation/main_window.py`
- Modify: `src/echo_personal_tool/application/app_controller.py`
- Modify: `CHANGELOG_SESSION.md`

- [x] **Step 1: Add initial visible-window trigger after studies load**

In `_on_studies_loaded`, after `populate(...)` call:

```python
self._browser.request_visible_previews()
```

- [x] **Step 2: Add lightweight timing metrics logs**

Add timing checkpoints:
- scan start/end,
- studies populated,
- first preview emitted,
- click-to-frame-loaded.

Implementation can use monotonic timestamps and `status_message` or logger output.

- [x] **Step 3: Add/adjust tests**

Add targeted tests (or extend Task 3/4 tests) to ensure initial visible preview request is called once after populate.

Run: `uv run pytest tests/unit/test_local_browser_thumbnail_requesting.py tests/unit/test_app_controller_thumbnail_priority.py -v`  
Expected: PASS.

- [x] **Step 4: Update changelog**

Append entry:

```markdown
## [2026-06-13 HH:MM] Preview-only приоритизация миниатюр
- **Тип:** feature
- **Файлы:** `app_controller.py`, `local_browser.py`, `thumbnail_loader_worker.py`, `thumbnail_scheduler.py`, `tests/...`
- **Суть:** Ускорена готовность папки: lazy/priority preview (64–96 px), видимая область и выбранный файл обслуживаются первыми, загрузка в главное окно не блокируется хвостом миниатюр.
```

- [x] **Step 5: Final verification**

Run:

```bash
uv run pytest tests/unit/test_thumbnail_scheduler.py tests/unit/test_thumbnail_qimage.py tests/unit/test_local_browser_thumbnail_requesting.py tests/unit/test_app_controller_thumbnail_priority.py -v
uv run pytest tests/unit -q
uv run ruff check src tests
```

Expected: all tests pass; ruff clean.

- [x] **Step 6: Commit**

```bash
git add src/echo_personal_tool/presentation/main_window.py src/echo_personal_tool/application/app_controller.py CHANGELOG_SESSION.md
git commit -m "feat: finalize preview-only thumbnail priority loading workflow"
```

---

## Spec coverage checklist

- Priority queue + dedup + in-flight: Task 1, Task 3
- Preview-only thumbnails 64-96 px: Task 2
- Visible/selected first: Task 3, Task 4, Task 5
- Main-viewer load not blocked by thumbnail backlog: Task 3
- No HQ second pass in MVP: Task 2
- Instrumentation for time-to-readiness: Task 5

---

## Execution notes for subagent-driven workflow

- Execute tasks strictly in order.
- For each task: implementer subagent -> spec reviewer subagent -> code quality reviewer subagent.
- Do not run parallel implementer subagents on these tasks.
- If spec reviewer flags gap, fix and re-review before quality review.
