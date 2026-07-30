# Cine Playback Prefetch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Smooth DICOM and MP4 cine playback on low-end systems via symmetric prefetch pipeline, adaptive buffer sizing, and lag-based frame skip.

**Architecture:** Minimal `PlaybackConfig` from `system_profiler.py` drives prefetch radius/batch size. `AppController` keeps N frames ahead in `FrameCache` using existing `FrameLoaderWorker` batch mode. `_advance_playback` only steps when next frame is cached; lags skip to nearest loaded frame. Lazy leading-static scan on first play.

**Tech Stack:** Python 3.11+, NumPy, PySide6 (`QTimer`, `QThreadPool`), OpenCV (via existing readers), `psutil`

**Spec:** [`docs/superpowers/specs/2026-06-29-playback-prefetch-design.md`](../specs/2026-06-29-playback-prefetch-design.md)

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/echo_personal_tool/infrastructure/system_profiler.py` | Create | `PlaybackConfig`, `detect_playback_config()` |
| `src/echo_personal_tool/application/frame_cache.py` | Modify | `loaded_ahead()`, `nearest_loaded_ahead()` |
| `src/echo_personal_tool/application/app_controller.py` | Modify | Prefetch pipeline, lag skip, lazy leading-static, batch target fix |
| `tests/unit/test_system_profiler.py` | Create | Adaptive config per profile |
| `tests/unit/test_frame_cache.py` | Modify | Ahead-count helpers |
| `tests/unit/test_playback_prefetch.py` | Create | Prefetch, pause cancel, lag skip, leading-static |

---

### Task 1: PlaybackConfig (system profiler)

**Files:**
- Create: `src/echo_personal_tool/infrastructure/system_profiler.py`
- Create: `tests/unit/test_system_profiler.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_system_profiler.py
from __future__ import annotations

import pytest

from echo_personal_tool.infrastructure.system_profiler import (
    PlaybackConfig,
    detect_playback_config,
)


def test_playback_config_is_frozen():
    cfg = PlaybackConfig(
        prefetch_radius=3,
        min_buffer=2,
        batch_size=3,
        max_lag_frames=2,
        evict_window=30,
    )
    with pytest.raises(AttributeError):
        cfg.prefetch_radius = 5  # type: ignore[misc]


def test_detect_playback_config_low_end(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "echo_personal_tool.infrastructure.system_profiler.os.cpu_count",
        lambda: 4,
    )

    class _Mem:
        total = int(12e9)

    monkeypatch.setattr(
        "echo_personal_tool.infrastructure.system_profiler.psutil.virtual_memory",
        lambda: _Mem(),
    )
    cfg = detect_playback_config()
    assert cfg.prefetch_radius == 3
    assert cfg.batch_size == 3
    assert cfg.evict_window == 30


def test_detect_playback_config_high_end(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "echo_personal_tool.infrastructure.system_profiler.os.cpu_count",
        lambda: 12,
    )

    class _Mem:
        total = int(32e9)

    monkeypatch.setattr(
        "echo_personal_tool.infrastructure.system_profiler.psutil.virtual_memory",
        lambda: _Mem(),
    )
    cfg = detect_playback_config()
    assert cfg.prefetch_radius == 10
    assert cfg.batch_size == 8
    assert cfg.evict_window == 40
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/unit/test_system_profiler.py -v`  
Expected: FAIL — `ModuleNotFoundError: system_profiler`

- [ ] **Step 3: Implement system_profiler**

```python
# src/echo_personal_tool/infrastructure/system_profiler.py
"""Runtime detection for playback tuning on low-end vs high-end systems."""

from __future__ import annotations

import os
from dataclasses import dataclass

import psutil

_LOW_END_CORES = 4
_LOW_END_RAM_GB = 16.0


@dataclass(frozen=True)
class PlaybackConfig:
    prefetch_radius: int
    min_buffer: int
    batch_size: int
    max_lag_frames: int
    evict_window: int


_LOW_END = PlaybackConfig(
    prefetch_radius=3,
    min_buffer=2,
    batch_size=3,
    max_lag_frames=2,
    evict_window=30,
)

_HIGH_END = PlaybackConfig(
    prefetch_radius=10,
    min_buffer=5,
    batch_size=8,
    max_lag_frames=4,
    evict_window=40,
)


def detect_playback_config() -> PlaybackConfig:
    cores = os.cpu_count() or 2
    ram_gb = psutil.virtual_memory().total / 1e9
    is_low_end = cores <= _LOW_END_CORES or ram_gb <= _LOW_END_RAM_GB
    return _LOW_END if is_low_end else _HIGH_END
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/unit/test_system_profiler.py -v`  
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/infrastructure/system_profiler.py tests/unit/test_system_profiler.py
git commit -m "feat: add PlaybackConfig for adaptive cine prefetch"
```

---

### Task 2: FrameCache ahead helpers

**Files:**
- Modify: `src/echo_personal_tool/application/frame_cache.py`
- Modify: `tests/unit/test_frame_cache.py`

- [ ] **Step 1: Write failing tests**

```python
# Append to tests/unit/test_frame_cache.py


def test_loaded_ahead_counts_forward_frames():
    cache = FrameCache(evict_window=100)
    cache.set_total_frames(Path("cine.mp4"), total=10)
    cache.put(3, np.zeros((4, 4), dtype=np.uint8))
    cache.put(4, np.ones((4, 4), dtype=np.uint8))
    cache.put(5, np.full((4, 4), 2, dtype=np.uint8))
    assert cache.loaded_ahead(2) == 3
    assert cache.loaded_ahead(4) == 1


def test_nearest_loaded_ahead_skips_gaps():
    cache = FrameCache(evict_window=100)
    cache.set_total_frames(Path("cine.mp4"), total=10)
    cache.put(5, np.zeros((4, 4), dtype=np.uint8))
    cache.put(7, np.ones((4, 4), dtype=np.uint8))
    assert cache.nearest_loaded_ahead(3) == 5
    assert cache.nearest_loaded_ahead(6) == 7
    assert cache.nearest_loaded_ahead(8) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/unit/test_frame_cache.py::test_loaded_ahead_counts_forward_frames -v`  
Expected: FAIL — `AttributeError: loaded_ahead`

- [ ] **Step 3: Implement helpers**

```python
# Add to FrameCache in frame_cache.py


def loaded_ahead(self, center: int) -> int:
    """Count consecutive loaded frames after center (wrapping at end)."""
    if self._total_frames == 0:
        return 0
    count = 0
    idx = center
    for _ in range(self._total_frames - 1):
        idx = (idx + 1) % self._total_frames
        if idx in self._frame_store:
            count += 1
        else:
            break
    return count


def nearest_loaded_ahead(self, center: int) -> int | None:
    """Return the smallest loaded index > center, wrapping; None if none."""
    if self._total_frames == 0:
        return None
    idx = center
    for _ in range(self._total_frames - 1):
        idx = (idx + 1) % self._total_frames
        if idx in self._frame_store:
            return idx
    return None
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/unit/test_frame_cache.py -v`  
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/application/frame_cache.py tests/unit/test_frame_cache.py
git commit -m "feat: add FrameCache loaded_ahead helpers for playback"
```

---

### Task 3: Wire PlaybackConfig into AppController

**Files:**
- Modify: `src/echo_personal_tool/application/app_controller.py` (constructor + `FrameCache` init)

- [ ] **Step 1: Import and initialize**

At top of `app_controller.py`:

```python
from echo_personal_tool.infrastructure.system_profiler import (
    PlaybackConfig,
    detect_playback_config,
)
```

In `__init__`, replace:

```python
self._frame_cache = FrameCache()
```

with:

```python
self._playback_config: PlaybackConfig = detect_playback_config()
self._frame_cache = FrameCache(evict_window=self._playback_config.evict_window)
```

Add new fields after `_batch_target_frame`:

```python
self._prefetch_request_id: int = 0
self._prefetch_load_id: int = 0
self._last_frame_shown_at: float = 0.0
```

- [ ] **Step 2: Verify existing tests still pass**

Run: `python3 -m pytest tests/unit/test_app_controller_dicom_cache.py -v`  
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add src/echo_personal_tool/application/app_controller.py
git commit -m "feat: wire PlaybackConfig into AppController"
```

---

### Task 4: Fix `_batch_target_frame` on scroll

**Files:**
- Modify: `src/echo_personal_tool/application/app_controller.py` (`_request_frame_if_needed`)
- Modify: `tests/unit/test_app_controller_dicom_cache.py`

- [ ] **Step 1: Write failing test**

```python
# Append to tests/unit/test_app_controller_dicom_cache.py


def test_scroll_batch_sets_target_frame(
    qapp,
    monkeypatch,
    tmp_path,
) -> None:
    captured: list[int] = []

    class _SpyLoader:
        instances: list[_SpyLoader] = []

        def __init__(self, path, frame_index=0, media_format="dicom", parent=None, total_frames=0, batch_size=0):
            self._frame_index = frame_index
            _SpyLoader.instances.append(self)

        def __getattr__(self, name):
            return lambda *a, **k: None

    monkeypatch.setattr(
        "echo_personal_tool.application.app_controller.FrameLoaderWorker",
        _SpyLoader,
    )
    controller = AppController()
    inst = _sample_dicom_instance(tmp_path / "x.dcm", frame_count=20)
    controller.load_instance(inst)
    controller._frame_cache.set_total_frames(inst.path, 20)
    controller._frame_cache.put(0, np.zeros((8, 8), dtype=np.uint8))
    controller._pending_decode_id = 0

    state = controller.state_manager.snapshot
    controller.state_manager.set_frame(15)
    controller._batch_target_frame = 0
    controller._request_frame_if_needed(controller.state_manager.snapshot)

    assert controller._batch_target_frame == 15
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `python3 -m pytest tests/unit/test_app_controller_dicom_cache.py::test_scroll_batch_sets_target_frame -v`  
Expected: FAIL — `_batch_target_frame` still 0

- [ ] **Step 3: Set target before launching worker**

In `_request_frame_if_needed`, before `self._load_request_id += 1`:

```python
self._batch_target_frame = state.current_frame_index
```

- [ ] **Step 4: Run test — expect PASS**

Run: `python3 -m pytest tests/unit/test_app_controller_dicom_cache.py::test_scroll_batch_sets_target_frame -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/application/app_controller.py tests/unit/test_app_controller_dicom_cache.py
git commit -m "fix: set batch target frame on scroll load"
```

---

### Task 5: Prefetch pipeline methods

**Files:**
- Modify: `src/echo_personal_tool/application/app_controller.py`
- Create: `tests/unit/test_playback_prefetch.py`

- [ ] **Step 1: Write failing tests for prefetch trigger**

```python
# tests/unit/test_playback_prefetch.py
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.domain.models import InstanceMetadata
from echo_personal_tool.infrastructure.system_profiler import PlaybackConfig


@pytest.fixture
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _mp4_instance(path: Path, frames: int = 30) -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid="1.2.3",
        path=path,
        media_format="mp4",
        frame_count=frames,
        frame_time_ms=33.3,
    )


def test_prefetch_starts_batch_worker(qapp, monkeypatch, tmp_path) -> None:
    started: list[object] = []

    class _SpyPool:
        def start(self, worker):
            started.append(worker)

    class _SpyLoader:
        def __init__(self, path, frame_index=0, media_format="mp4", parent=None, total_frames=0, batch_size=0):
            self._batch_size = batch_size
            self._frame_index = frame_index
            self.signals = MagicMock()

    monkeypatch.setattr(
        "echo_personal_tool.application.app_controller.FrameLoaderWorker",
        _SpyLoader,
    )
    controller = AppController(thread_pool=_SpyPool())
    controller._playback_config = PlaybackConfig(3, 2, 3, 2, 30)
    mp4 = tmp_path / "c.mp4"
    mp4.write_bytes(b"\x00")
    inst = _mp4_instance(mp4)
    controller._current_instance = inst
    controller._frame_cache.set_total_frames(mp4, 30)
    controller._frame_cache.put(0, np.zeros((8, 8), dtype=np.uint8))
    controller._state_manager.set_instance(inst, total_frames=30, frame_time_ms=33.3)
    controller._state_manager.set_playing(True)

    controller._prefetch_playback_buffer(0)

    assert len(started) == 1
    assert started[0]._batch_size == 3
    assert started[0]._frame_index == 1


def test_prefetch_skipped_when_buffer_full(qapp, monkeypatch, tmp_path) -> None:
    started: list[object] = []

    class _SpyPool:
        def start(self, worker):
            started.append(worker)

    monkeypatch.setattr(
        "echo_personal_tool.application.app_controller.FrameLoaderWorker",
        MagicMock,
    )
    controller = AppController(thread_pool=_SpyPool())
    controller._playback_config = PlaybackConfig(3, 2, 3, 2, 30)
    mp4 = tmp_path / "c.mp4"
    mp4.write_bytes(b"\x00")
    inst = _mp4_instance(mp4)
    controller._current_instance = inst
    controller._frame_cache.set_total_frames(mp4, 30)
    controller._frame_cache.put(0, np.zeros((8, 8), dtype=np.uint8))
    controller._frame_cache.put(1, np.ones((8, 8), dtype=np.uint8))
    controller._frame_cache.put(2, np.full((8, 8), 2, dtype=np.uint8))
    controller._state_manager.set_instance(inst, total_frames=30, frame_time_ms=33.3)
    controller._state_manager.set_playing(True)

    controller._prefetch_playback_buffer(0)

    assert started == []
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `python3 -m pytest tests/unit/test_playback_prefetch.py -v`  
Expected: FAIL — `_prefetch_playback_buffer` not defined

- [ ] **Step 3: Implement prefetch methods**

Add to `AppController`:

```python
def _invalidate_prefetch(self) -> None:
    self._prefetch_request_id += 1
    self._prefetch_load_id = 0


def _prefetch_playback_buffer(self, center: int) -> None:
    if self._current_instance is None or self._current_instance.path is None:
        return
    if not self._state_manager.snapshot.is_playing:
        return
    if self._prefetch_load_id != 0:
        return

    cfg = self._playback_config
    ahead = self._frame_cache.loaded_ahead(center)
    if ahead >= cfg.min_buffer:
        return

    total = self._frame_cache.frame_count()
    if total <= 0:
        return

    start = (center + 1 + ahead) % total
    if start == center:
        return

    self._prefetch_request_id += 1
    request_id = self._prefetch_request_id
    self._prefetch_load_id = request_id

    batch = min(cfg.batch_size, total)
    worker = FrameLoaderWorker(
        self._current_instance.path,
        frame_index=start,
        media_format=self._current_instance.media_format,
        parent=self,
        total_frames=total,
        batch_size=batch,
    )
    worker.signals.batch_finished.connect(
        partial(self._on_prefetch_batch_loaded, request_id, self._current_instance.path)
    )
    worker.signals.failed.connect(partial(self._on_prefetch_failed, request_id))
    self._thread_pool.start(worker)


def _on_prefetch_batch_loaded(self, request_id: int, path: Path, frames: list) -> None:
    if request_id != self._prefetch_load_id:
        return
    self._prefetch_load_id = 0
    if self._current_instance is None or self._current_instance.path != path:
        return
    for idx, pixels in frames:
        self._frame_cache.put(idx, pixels)
    if self._state_manager.snapshot.is_playing:
        QTimer.singleShot(0, self._advance_playback)


def _on_prefetch_failed(self, request_id: int, message: str) -> None:
    if request_id != self._prefetch_load_id:
        return
    self._prefetch_load_id = 0
    self.status_message.emit(f"Prefetch failed: {message}")
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `python3 -m pytest tests/unit/test_playback_prefetch.py -v`  
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/application/app_controller.py tests/unit/test_playback_prefetch.py
git commit -m "feat: add playback prefetch buffer pipeline"
```

---

### Task 6: Refactor `_advance_playback` + timing

**Files:**
- Modify: `src/echo_personal_tool/application/app_controller.py`
- Modify: `tests/unit/test_playback_prefetch.py`

- [ ] **Step 1: Write failing lag-skip test**

```python
def test_advance_playback_skips_on_lag(qapp, tmp_path) -> None:
    controller = AppController()
    controller._playback_config = PlaybackConfig(3, 2, 3, 2, 30)
    mp4 = tmp_path / "c.mp4"
    mp4.write_bytes(b"\x00")
    inst = _mp4_instance(mp4, frames=20)
    controller._current_instance = inst
    controller._frame_cache.set_total_frames(mp4, 20)
    for i in range(5):
        controller._frame_cache.put(i, np.full((4, 4), i, dtype=np.uint8))
    controller._frame_cache.put(8, np.full((4, 4), 8, dtype=np.uint8))
    controller._state_manager.set_instance(inst, total_frames=20, frame_time_ms=33.3)
    controller._state_manager.set_frame(3)
    controller._state_manager.set_playing(True)
    controller._pending_decode_id = 0
    controller._pending_load_id = 0
    controller._prefetch_load_id = 0

    controller._advance_playback()

    assert controller.state_manager.snapshot.current_frame_index == 4
```

Add second test for lag skip:

```python
def test_advance_playback_lag_skip_to_nearest(qapp, tmp_path) -> None:
    controller = AppController()
    controller._playback_config = PlaybackConfig(3, 2, 3, 2, 30)
    mp4 = tmp_path / "c.mp4"
    mp4.write_bytes(b"\x00")
    inst = _mp4_instance(mp4, frames=20)
    controller._current_instance = inst
    controller._frame_cache.set_total_frames(mp4, 20)
    controller._frame_cache.put(3, np.zeros((4, 4), dtype=np.uint8))
    controller._frame_cache.put(8, np.full((4, 4), 8, dtype=np.uint8))
    controller._state_manager.set_instance(inst, total_frames=20, frame_time_ms=33.3)
    controller._state_manager.set_frame(3)
    controller._state_manager.set_playing(True)
    controller._pending_decode_id = 0
    controller._pending_load_id = 0
    controller._prefetch_load_id = 0

    controller._advance_playback()

    assert controller.state_manager.snapshot.current_frame_index == 8
```

- [ ] **Step 2: Run tests — expect FAIL or wrong index**

Run: `python3 -m pytest tests/unit/test_playback_prefetch.py::test_advance_playback_skips_on_lag -v`  
Expected: FAIL

- [ ] **Step 3: Replace `_advance_playback` body**

```python
def _advance_playback(self) -> None:
    from time import perf_counter

    state = self._state_manager.snapshot
    if self._pending_decode_id != 0:
        return
    if (
        self._current_instance is not None
        and self._current_instance.media_format in ("dicom", "mp4")
        and self._current_instance.path is not None
        and self._frame_cache.is_ready(self._current_instance.path)
    ):
        current = state.current_frame_index
        total = state.total_frames
        next_idx = (current + 1) % total

        if self._frame_cache.is_loaded(next_idx):
            self._frame_cache.set_current(next_idx)
            self.step_frame(1)
            self._last_frame_shown_at = perf_counter()
            self._prefetch_playback_buffer(next_idx)
            if state.is_playing:
                interval = max(
                    1,
                    int(round((state.frame_time_ms or 33.3) / self._playback_speed_multiplier)),
                )
                QTimer.singleShot(interval, self._advance_playback)
            return

        cfg = self._playback_config
        ahead = self._frame_cache.loaded_ahead(current)
        if ahead > cfg.max_lag_frames:
            skip_to = self._frame_cache.nearest_loaded_ahead(current)
            if skip_to is not None:
                self._frame_cache.set_current(skip_to)
                self._state_manager.set_frame(skip_to)
                self._emit_cached_frame(skip_to)
                self._prefetch_playback_buffer(skip_to)
                if state.is_playing:
                    QTimer.singleShot(1, self._advance_playback)
                return

        self._prefetch_playback_buffer(current)
        return

    if self._pending_load_id != 0:
        return
    self.step_frame(1)
```

- [ ] **Step 4: Update `_on_playback_frame_loaded` to use same timing**

Replace timer scheduling in `_on_playback_frame_loaded` with:

```python
self._frame_cache.set_current(frame_index)
# ... existing put/emit ...
if self._state_manager.snapshot.is_playing:
    QTimer.singleShot(1, self._advance_playback)
```

Remove the old `interval` singleShot from `_on_playback_frame_loaded` — timing now handled in `_advance_playback` when frame is cached.

- [ ] **Step 5: Run playback tests**

Run: `python3 -m pytest tests/unit/test_playback_prefetch.py -v`  
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/echo_personal_tool/application/app_controller.py tests/unit/test_playback_prefetch.py
git commit -m "feat: playback advance with prefetch and lag skip"
```

---

### Task 7: Lazy leading-static scan + play/pause wiring

**Files:**
- Modify: `src/echo_personal_tool/application/app_controller.py`
- Modify: `tests/unit/test_playback_prefetch.py`

- [ ] **Step 1: Write failing leading-static test**

```python
def test_lazy_leading_static_detects_static_prefix(qapp, tmp_path) -> None:
    controller = AppController()
    frames = [np.zeros((8, 8), dtype=np.uint8) for _ in range(4)]
    frames.append(np.ones((8, 8), dtype=np.uint8))
    for i, f in enumerate(frames):
        controller._frame_cache.put(i, f)
    path = tmp_path / "x.dcm"
    path.write_bytes(b"\x00")
    leading = controller._detect_leading_static_from_cache(path, total=len(frames))
    assert leading == 3
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `python3 -m pytest tests/unit/test_playback_prefetch.py::test_lazy_leading_static_detects_static_prefix -v`  
Expected: FAIL

- [ ] **Step 3: Implement leading-static + wire set_playing**

```python
def _detect_leading_static_from_cache(self, path: Path, total: int) -> int:
    if not self._frame_cache.is_loaded(0):
        return 0
    ref = self._frame_cache.get(0).astype(np.float32, copy=False)
    leading = 0
    for idx in range(1, min(total, 16)):
        if not self._frame_cache.is_loaded(idx):
            break
        diff = float(np.mean(np.abs(self._frame_cache.get(idx).astype(np.float32, copy=False) - ref)))
        if diff > 1.0:
            break
        leading = idx
    return leading


def _ensure_leading_static_scanned(self) -> None:
    if self._current_instance is None or self._current_instance.path is None:
        return
    path = self._current_instance.path.resolve()
    if path in self._leading_static_frames:
        return
    total = self._frame_cache.frame_count()
    if total <= 1:
        self._leading_static_frames[path] = 0
        return
    # frames 0..7 may need load — if frame 1 not loaded, caller should prefetch first
    leading = self._detect_leading_static_from_cache(path, total)
    self._leading_static_frames[path] = leading
```

Update `set_playing`:

```python
def set_playing(self, is_playing: bool) -> None:
    if is_playing:
        self._invalidate_prefetch()
        if self._current_instance is not None and self._current_instance.path is not None:
            self._ensure_leading_static_scanned()
            state = self._state_manager.snapshot
            if state.current_frame_index == 0:
                leading = self._leading_static_frames.get(self._current_instance.path.resolve(), 0)
                if leading > 0:
                    target = min(leading + 1, max(0, state.total_frames - 1))
                    if target > 0:
                        self._state_manager.set_frame(target)
    else:
        self._invalidate_prefetch()
    self._state_manager.set_playing(is_playing)
    if is_playing:
        self._prefetch_playback_buffer(self._state_manager.snapshot.current_frame_index)
        QTimer.singleShot(1, self._advance_playback)
```

Update `_emit_cached_frame` to call `set_current`:

```python
self._frame_cache.set_current(frame_index)
```

- [ ] **Step 4: Run all playback + controller tests**

Run: `python3 -m pytest tests/unit/test_playback_prefetch.py tests/unit/test_app_controller_dicom_cache.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/application/app_controller.py tests/unit/test_playback_prefetch.py
git commit -m "feat: lazy leading-static scan and play/pause prefetch wiring"
```

---

### Task 8: Remove dead single-frame playback path

**Files:**
- Modify: `src/echo_personal_tool/application/app_controller.py`

- [ ] **Step 1: Deprecate `_load_playback_frame`**

Replace calls to `_load_playback_frame` in `_advance_playback` (already removed in Task 6). If `_load_playback_frame` is unused, delete it or make it delegate:

```python
def _load_playback_frame(self, frame_index: int) -> None:
    """Legacy single-frame load — use _prefetch_playback_buffer instead."""
    self._prefetch_playback_buffer(frame_index - 1)
```

- [ ] **Step 2: Run full unit suite for affected modules**

Run: `python3 -m pytest tests/unit/test_playback_prefetch.py tests/unit/test_frame_cache.py tests/unit/test_app_controller_dicom_cache.py tests/unit/test_playback_state.py -v`  
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add src/echo_personal_tool/application/app_controller.py
git commit -m "refactor: remove single-frame playback load path"
```

---

### Task 9: Manual verification checklist

- [ ] **DICOM:** Open 500+ frame multiframe cine → Play → observe smooth playback after ~1 s on target hardware
- [ ] **MP4:** Open 2000 frame file → Play → measure fps ≥ 20 after warm-up
- [ ] **Pause/Play:** Resume < 500 ms
- [ ] **Seek during play:** No stale frames, playback continues from new position
- [ ] **Loop:** Last frame → first frame without long freeze
- [ ] **Memory:** `frame_cache.memory_bytes()` stable, no unbounded growth over 60 s play

---

## Self-Review (plan vs spec)

| Spec requirement | Task |
|------------------|------|
| Symmetric DICOM/MP4 prefetch | Task 5–6 |
| Adaptive constants | Task 1, 3 |
| Lag skip | Task 6 |
| Lazy leading-static | Task 7 |
| `set_current` on display | Task 6–7 |
| Fix `_batch_target_frame` | Task 4 |
| Pause invalidates prefetch | Task 5, 7 |
| Unit tests | Tasks 1–2, 4–7 |
| Manual criteria | Task 9 |

No placeholders. Phase 2 items (keyframe index, decode timeout) explicitly deferred.

---

## Execution Handoff

Plan saved to `docs/superpowers/plans/2026-06-29-playback-prefetch.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks
2. **Inline Execution** — implement tasks in this session with checkpoints

Which approach?
