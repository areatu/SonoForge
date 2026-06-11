# DICOM Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decode each DICOM cine once on instance open, cache all frames in memory, and serve play/scrub from O(1) cache lookups at ≥15 fps.

**Architecture:** `DicomSession` (infrastructure) decodes `(N,H,W)` once per file. `DicomDecodeWorker` runs decode on `QThreadPool` when user selects a DICOM instance. `FrameCache` (application) holds the current instance's frames. `AppController` emits `frame_loaded` synchronously from cache — no per-frame `FrameLoaderWorker` for DICOM. MP4/JPEG/PNG unchanged.

**Tech Stack:** Python 3.11, PySide6, pydicom, NumPy, pytest, pytest-qt

**Spec:** `docs/superpowers/specs/2026-06-11-dicom-performance-design.md`

---

## File map

| File | Responsibility |
|------|----------------|
| `infrastructure/dicom_session.py` | Open DICOM once, decode all frames, slice by index |
| `infrastructure/dicom_reader.py` | Delegate `read_pixels` to session (backward compat) |
| `application/frame_cache.py` | In-memory store for current DICOM instance |
| `application/workers/dicom_decode_worker.py` | Background full decode |
| `application/app_controller.py` | Decode-on-open, fast path, playback |
| `domain/models/viewer_state.py` | `decode_in_progress` flag |
| `application/state_manager.py` | Track/decode flag in snapshot |
| `presentation/viewer_widget.py` | Disable play/slider while decoding |
| `tests/fixtures/generate_synthetic_dicom.py` | Multiframe test fixture |

---

### Task 1: Multiframe fixture + DicomSession

**Files:**
- Modify: `tests/fixtures/generate_synthetic_dicom.py`
- Create: `src/echo_personal_tool/infrastructure/dicom_session.py`
- Modify: `src/echo_personal_tool/infrastructure/dicom_reader.py`
- Create: `tests/unit/test_dicom_session.py`

- [ ] **Step 1: Add multiframe fixture**

Add to `tests/fixtures/generate_synthetic_dicom.py`:

```python
def write_synthetic_multiframe_dicom(
    path: Path,
    *,
    frame_count: int = 10,
    rows: int = 64,
    cols: int = 64,
    study_uid: str | None = None,
    series_uid: str | None = None,
    sop_uid: str | None = None,
    series_description: str = "Synthetic multiframe A4C",
) -> Path:
    """Write a multiframe grayscale US DICOM file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    study_uid = study_uid or generate_uid()
    series_uid = series_uid or generate_uid()
    sop_uid = sop_uid or generate_uid()

    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = pydicom.uid.UltrasoundImageStorage
    file_meta.MediaStorageSOPInstanceUID = sop_uid
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds: FileDataset = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\0" * 128)
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    ds.SOPClassUID = pydicom.uid.UltrasoundImageStorage
    ds.SOPInstanceUID = sop_uid
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series_uid
    ds.Modality = "US"
    ds.SeriesDescription = series_description
    ds.StudyDate = "20240601"
    ds.StudyTime = "120000"
    ds.PatientName = "Synthetic^Patient"
    ds.PatientID = "SYN001"
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.Rows = rows
    ds.Columns = cols
    ds.BitsAllocated = 8
    ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0
    ds.PixelSpacing = [0.3, 0.3]
    ds.NumberOfFrames = frame_count

    frames = []
    for frame_index in range(frame_count):
        gradient = np.linspace(0, 255, cols, dtype=np.uint8)
        frame = np.tile(gradient, (rows, 1))
        frame[0, 0] = frame_index  # unique marker per frame
        frames.append(frame)
    stacked = np.stack(frames, axis=0)
    ds.PixelData = stacked.tobytes()
    ds.save_as(path, write_like_original=False)
    return path
```

- [ ] **Step 2: Write failing tests**

Create `tests/unit/test_dicom_session.py`:

```python
"""Unit tests for DicomSession."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from echo_personal_tool.infrastructure.dicom_session import (
    DicomSession,
    get_thread_dicom_session,
)
from tests.fixtures.generate_synthetic_dicom import (
    write_synthetic_dicom,
    write_synthetic_multiframe_dicom,
)


def test_decode_single_frame_dicom(tmp_path: Path) -> None:
    path = tmp_path / "single.dcm"
    write_synthetic_dicom(path)
    session = DicomSession()
    session.open(path)
    frames = session.decode_all_frames()
    assert frames.shape == (1, 64, 64)
    frame = session.read_frame(0)
    assert frame.shape == (64, 64)
    session.release()
    assert session.frame_count == 0


def test_decode_multiframe_dicom(tmp_path: Path) -> None:
    path = tmp_path / "multi.dcm"
    write_synthetic_multiframe_dicom(path, frame_count=5, rows=32, cols=32)
    session = DicomSession()
    session.open(path)
    frames = session.decode_all_frames()
    assert frames.shape == (5, 32, 32)
    assert frames[3, 0, 0] == 3
    assert session.read_frame(2)[0, 0] == 2
    session.release()


def test_read_frame_out_of_range_raises(tmp_path: Path) -> None:
    path = tmp_path / "multi.dcm"
    write_synthetic_multiframe_dicom(path, frame_count=3)
    session = DicomSession()
    session.open(path)
    session.decode_all_frames()
    with pytest.raises(IndexError):
        session.read_frame(3)
    session.release()


def test_get_thread_dicom_session_returns_same_instance() -> None:
    first = get_thread_dicom_session()
    second = get_thread_dicom_session()
    assert first is second
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_dicom_session.py -v
```

Expected: FAIL — `ModuleNotFoundError: dicom_session`

- [ ] **Step 4: Implement DicomSession**

Create `src/echo_personal_tool/infrastructure/dicom_session.py`:

```python
"""Thread-local DICOM session: open once, decode all frames."""

from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
import pydicom

_thread_local = threading.local()


def get_thread_dicom_session() -> DicomSession:
    session = getattr(_thread_local, "dicom_session", None)
    if session is None:
        session = DicomSession()
        _thread_local.dicom_session = session
    return session


class DicomSession:
    def __init__(self) -> None:
        self._open_path: Path | None = None
        self._frames: np.ndarray | None = None

    @property
    def frame_count(self) -> int:
        if self._frames is None:
            return 0
        return int(self._frames.shape[0])

    def open(self, path: Path | str) -> None:
        resolved = Path(path).resolve()
        if self._open_path == resolved and self._frames is not None:
            return
        self.release()
        self._open_path = resolved

    def decode_all_frames(self) -> np.ndarray:
        if self._open_path is None:
            raise RuntimeError("DICOM is not open; call open() first")
        dataset = pydicom.dcmread(self._open_path, force=True)
        pixel_array = dataset.pixel_array
        self._frames = stack_pixel_array(pixel_array)
        return self._frames

    def read_frame(self, frame_index: int) -> np.ndarray:
        if self._frames is None:
            raise RuntimeError("Frames not decoded; call decode_all_frames() first")
        if frame_index < 0 or frame_index >= self._frames.shape[0]:
            raise IndexError(
                f"Frame index {frame_index} out of range [0, {self._frames.shape[0]})"
            )
        return np.ascontiguousarray(self._frames[frame_index]).copy()

    def release(self) -> None:
        self._open_path = None
        self._frames = None


def stack_pixel_array(pixel_array: np.ndarray) -> np.ndarray:
    """Normalize pydicom pixel_array to shape (N, H, W)."""
    arr = np.asarray(pixel_array)
    if arr.ndim == 2:
        return np.ascontiguousarray(arr[np.newaxis, ...])
    if arr.ndim == 4:
        frames = arr
    elif arr.ndim == 3:
        if arr.shape[0] <= arr.shape[-1]:
            frames = arr
        else:
            frames = np.moveaxis(arr, -1, 0)
    else:
        raise ValueError(f"Unsupported pixel_array ndim: {arr.ndim}")

    if frames.ndim == 4 and frames.shape[-1] in (3, 4):
        frames = frames[..., 0]
    if frames.ndim != 3:
        raise ValueError(f"Expected (N,H,W) after normalization, got {frames.shape}")
    return np.ascontiguousarray(frames)
```

- [ ] **Step 5: Delegate DicomReaderImpl to DicomSession**

Replace body of `read_pixels` in `dicom_reader.py`:

```python
from echo_personal_tool.infrastructure.dicom_session import get_thread_dicom_session

def read_pixels(self, path: Path, frame_index: int = 0) -> np.ndarray:
    session = get_thread_dicom_session()
    session.open(path)
    if session.frame_count == 0:
        session.decode_all_frames()
    return session.read_frame(frame_index)
```

Remove duplicated frame-extraction logic from `dicom_reader.py`.

- [ ] **Step 6: Run tests**

```bash
uv run pytest tests/unit/test_dicom_session.py tests/unit/test_frame_loader_worker.py::test_frame_loader_reads_dicom -v
```

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add tests/fixtures/generate_synthetic_dicom.py \
  src/echo_personal_tool/infrastructure/dicom_session.py \
  src/echo_personal_tool/infrastructure/dicom_reader.py \
  tests/unit/test_dicom_session.py
git commit -m "feat: add DicomSession with decode-all-frames for multiframe DICOM"
```

---

### Task 2: FrameCache

**Files:**
- Create: `src/echo_personal_tool/application/frame_cache.py`
- Create: `tests/unit/test_frame_cache.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_frame_cache.py`:

```python
"""Unit tests for FrameCache."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from echo_personal_tool.application.frame_cache import FrameCache


def test_frame_cache_load_get_clear(tmp_path: Path) -> None:
    path = tmp_path / "clip.dcm"
    frames = np.arange(30, dtype=np.uint8).reshape(3, 2, 5)
    cache = FrameCache()

    assert not cache.is_ready(path)
    cache.load(path, frames)
    assert cache.is_ready(path)
    assert cache.frame_count() == 3
    assert cache.get(1)[0, 0] == 10
    assert cache.memory_bytes() == frames.nbytes

    cache.clear()
    assert not cache.is_ready(path)
    with pytest.raises(RuntimeError):
        cache.get(0)


def test_frame_cache_is_ready_requires_same_path(tmp_path: Path) -> None:
    path_a = tmp_path / "a.dcm"
    path_b = tmp_path / "b.dcm"
    frames = np.zeros((2, 4, 4), dtype=np.uint8)
    cache = FrameCache()
    cache.load(path_a, frames)
    assert cache.is_ready(path_a)
    assert not cache.is_ready(path_b)


def test_frame_cache_get_index_error(tmp_path: Path) -> None:
    path = tmp_path / "clip.dcm"
    cache = FrameCache()
    cache.load(path, np.zeros((2, 4, 4), dtype=np.uint8))
    with pytest.raises(IndexError):
        cache.get(5)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_frame_cache.py -v
```

Expected: FAIL — `ModuleNotFoundError: frame_cache`

- [ ] **Step 3: Implement FrameCache**

Create `src/echo_personal_tool/application/frame_cache.py`:

```python
"""In-memory frame store for the active DICOM instance."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


@dataclass
class FrameCache:
    source_path: Path | None = field(default=None, repr=False)
    frames: np.ndarray | None = field(default=None, repr=False)

    def is_ready(self, path: Path) -> bool:
        return (
            self.source_path is not None
            and self.frames is not None
            and self.source_path.resolve() == Path(path).resolve()
        )

    def load(self, path: Path, frames: np.ndarray) -> None:
        arr = np.ascontiguousarray(frames)
        if arr.ndim != 3:
            raise ValueError(f"Expected frames shape (N,H,W), got {arr.shape}")
        self.source_path = Path(path).resolve()
        self.frames = arr

    def get(self, index: int) -> np.ndarray:
        if self.frames is None:
            raise RuntimeError("Frame cache is empty")
        if index < 0 or index >= self.frames.shape[0]:
            raise IndexError(
                f"Frame index {index} out of range [0, {self.frames.shape[0]})"
            )
        return np.ascontiguousarray(self.frames[index]).copy()

    def clear(self) -> None:
        self.source_path = None
        self.frames = None

    def frame_count(self) -> int:
        if self.frames is None:
            return 0
        return int(self.frames.shape[0])

    def memory_bytes(self) -> int:
        if self.frames is None:
            return 0
        return int(self.frames.nbytes)
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/test_frame_cache.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/application/frame_cache.py tests/unit/test_frame_cache.py
git commit -m "feat: add FrameCache for decoded DICOM frames"
```

---

### Task 3: DicomDecodeWorker

**Files:**
- Create: `src/echo_personal_tool/application/workers/dicom_decode_worker.py`
- Create: `tests/unit/test_dicom_decode_worker.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_dicom_decode_worker.py`:

```python
"""Unit tests for DicomDecodeWorker."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication, QWidget

from echo_personal_tool.application.workers.dicom_decode_worker import DicomDecodeWorker
from tests.fixtures.generate_synthetic_dicom import write_synthetic_multiframe_dicom

pytest.importorskip("pytestqt")


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def test_dicom_decode_worker_emits_all_frames(
    qapp: QApplication, qtbot, tmp_path: Path
) -> None:
    parent = QWidget()
    path = tmp_path / "multi.dcm"
    write_synthetic_multiframe_dicom(path, frame_count=4, rows=16, cols=16)

    finished: list[tuple[int, Path, np.ndarray]] = []
    worker = DicomDecodeWorker(path, request_id=7, parent=parent)
    worker.signals.finished.connect(
        lambda request_id, decoded_path, frames: finished.append(
            (request_id, decoded_path, frames)
        )
    )
    QThreadPool.globalInstance().start(worker)
    qtbot.waitUntil(lambda: len(finished) == 1, timeout=10000)

    request_id, decoded_path, frames = finished[0]
    assert request_id == 7
    assert decoded_path.resolve() == path.resolve()
    assert frames.shape == (4, 16, 16)
    assert frames[2, 0, 0] == 2


def test_dicom_decode_worker_emits_failed_for_missing_file(
    qapp: QApplication, qtbot, tmp_path: Path
) -> None:
    parent = QWidget()
    path = tmp_path / "missing.dcm"
    errors: list[tuple[int, str]] = []
    worker = DicomDecodeWorker(path, request_id=1, parent=parent)
    worker.signals.failed.connect(
        lambda request_id, message: errors.append((request_id, message))
    )
    QThreadPool.globalInstance().start(worker)
    qtbot.waitUntil(lambda: len(errors) == 1, timeout=5000)
    assert errors[0][0] == 1
    assert errors[0][1]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_dicom_decode_worker.py -v
```

Expected: FAIL — module not found

- [ ] **Step 3: Implement DicomDecodeWorker**

Create `src/echo_personal_tool/application/workers/dicom_decode_worker.py`:

```python
"""Background worker that decodes all frames from a DICOM file."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from echo_personal_tool.infrastructure.dicom_session import get_thread_dicom_session


class DicomDecodeSignals(QObject):
    finished = Signal(int, object, object)  # request_id, path, frames ndarray
    failed = Signal(int, str)


class DicomDecodeWorker(QRunnable):
    def __init__(
        self,
        path: Path,
        request_id: int,
        parent: QObject | None = None,
    ) -> None:
        super().__init__()
        self._path = Path(path)
        self._request_id = request_id
        self.signals = DicomDecodeSignals(parent)
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        try:
            session = get_thread_dicom_session()
            session.open(self._path)
            frames = session.decode_all_frames()
            self.signals.finished.emit(
                self._request_id,
                self._path,
                np.ascontiguousarray(frames).copy(),
            )
        except Exception as exc:  # noqa: BLE001
            self.signals.failed.emit(self._request_id, str(exc))
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/test_dicom_decode_worker.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/application/workers/dicom_decode_worker.py \
  tests/unit/test_dicom_decode_worker.py
git commit -m "feat: add DicomDecodeWorker for background full decode"
```

---

### Task 4: ViewerState.decode_in_progress + ViewerWidget UX

**Files:**
- Modify: `src/echo_personal_tool/domain/models/viewer_state.py`
- Modify: `src/echo_personal_tool/application/state_manager.py`
- Modify: `src/echo_personal_tool/presentation/viewer_widget.py`
- Modify: `tests/unit/test_state_manager.py`
- Modify: `tests/unit/test_measurement_panel.py` (if ViewerState constructor needs new arg)

- [ ] **Step 1: Write failing test for decode flag**

Add to `tests/unit/test_state_manager.py`:

```python
def test_set_decode_in_progress(qtbot, instance_metadata: InstanceMetadata) -> None:
    manager = StateManager()
    manager.set_instance(instance_metadata, total_frames=10, frame_time_ms=33.3)
    assert manager.snapshot.decode_in_progress is False

    manager.set_decode_in_progress(True)
    assert manager.snapshot.decode_in_progress is True

    manager.set_decode_in_progress(False)
    assert manager.snapshot.decode_in_progress is False
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_state_manager.py::test_set_decode_in_progress -v
```

Expected: FAIL — no `set_decode_in_progress`

- [ ] **Step 3: Add field to ViewerState**

In `viewer_state.py`, add after `measurement_snapshot`:

```python
decode_in_progress: bool = False
```

- [ ] **Step 4: Update StateManager**

Add `self._decode_in_progress = False` in `__init__`.

Include `decode_in_progress=self._decode_in_progress` in `snapshot`.

Reset `self._decode_in_progress = False` in `set_instance`.

Add method:

```python
def set_decode_in_progress(self, in_progress: bool) -> None:
    if self._decode_in_progress == in_progress:
        return
    self._decode_in_progress = in_progress
    self._emit_state()
```

- [ ] **Step 5: Disable play/slider in ViewerWidget**

In `viewer_widget.set_state`, after setting timeline range:

```python
controls_enabled = (
    viewer_state.total_frames > 1 and not viewer_state.decode_in_progress
)
self._timeline_slider.setEnabled(controls_enabled)
self._play_button.setEnabled(
    viewer_state.total_frames > 1 and not viewer_state.decode_in_progress
)
```

Remove the old line that only checked `viewer_state.total_frames > 1` for slider.

- [ ] **Step 6: Fix any ViewerState(...) call sites in tests**

Grep `ViewerState(` in tests; frozen dataclass with default means existing calls still work. Run:

```bash
uv run pytest tests/unit/test_state_manager.py tests/unit/test_measurement_panel.py -v
```

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/echo_personal_tool/domain/models/viewer_state.py \
  src/echo_personal_tool/application/state_manager.py \
  src/echo_personal_tool/presentation/viewer_widget.py \
  tests/unit/test_state_manager.py
git commit -m "feat: add decode_in_progress flag and disable playback while decoding"
```

---

### Task 5: AppController wiring

**Files:**
- Modify: `src/echo_personal_tool/application/app_controller.py`
- Create: `tests/unit/test_app_controller_dicom_cache.py`

- [ ] **Step 1: Write failing integration tests**

Create `tests/unit/test_app_controller_dicom_cache.py`:

```python
"""AppController tests for DICOM FrameCache fast path."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.domain.models import InstanceMetadata
from tests.fixtures.generate_synthetic_dicom import write_synthetic_multiframe_dicom

pytest.importorskip("pytestqt")


class _FakeDecodeSignal:
    def __init__(self) -> None:
        self._callbacks = []

    def connect(self, callback) -> None:
        self._callbacks.append(callback)

    def emit(self, *args) -> None:
        for callback in list(self._callbacks):
            callback(*args)


class _FakeDecodeWorker:
    def __init__(self, path, request_id, parent=None) -> None:
        self.path = Path(path)
        self.request_id = request_id
        self.signals = SimpleNamespace(
            finished=_FakeDecodeSignal(),
            failed=_FakeDecodeSignal(),
        )


class _RecordingThreadPool:
    def __init__(self) -> None:
        self.started = []

    def start(self, worker) -> None:
        self.started.append(worker)


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _dicom_instance(path: Path, *, frames: int = 5) -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid="1.2.3.4.5",
        series_uid="1.2.3.4.6",
        modality="US",
        number_of_frames=frames,
        pixel_spacing=(0.3, 0.3),
        frame_time_ms=40.0,
        series_description="Test",
        path=path,
        media_format="dicom",
    )


def test_load_instance_starts_dicom_decode_worker(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "echo_personal_tool.application.app_controller.DicomDecodeWorker",
        _FakeDecodeWorker,
    )
    path = tmp_path / "multi.dcm"
    write_synthetic_multiframe_dicom(path, frame_count=5)
    pool = _RecordingThreadPool()
    controller = AppController(thread_pool=pool)
    controller.load_instance(_dicom_instance(path))

    assert len(pool.started) == 1
    assert controller.state_manager.snapshot.decode_in_progress is True


def test_cached_dicom_frame_change_emits_without_frame_loader(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "echo_personal_tool.application.app_controller.DicomDecodeWorker",
        _FakeDecodeWorker,
    )
    frame_loader_calls = {"count": 0}
    original_worker = __import__(
        "echo_personal_tool.application.workers.frame_loader_worker",
        fromlist=["FrameLoaderWorker"],
    ).FrameLoaderWorker

    class _SpyFrameLoader(original_worker):
        def __init__(self, *args, **kwargs):
            frame_loader_calls["count"] += 1
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(
        "echo_personal_tool.application.app_controller.FrameLoaderWorker",
        _SpyFrameLoader,
    )

    path = tmp_path / "multi.dcm"
    write_synthetic_multiframe_dicom(path, frame_count=4, rows=8, cols=8)
    pool = _RecordingThreadPool()
    controller = AppController(thread_pool=pool)
    instance = _dicom_instance(path, frames=4)
    controller.load_instance(instance)

    worker = pool.started[0]
    frames = np.stack(
        [np.full((8, 8), index, dtype=np.uint8) for index in range(4)],
        axis=0,
    )
    worker.signals.finished.emit(1, path, frames)

    received = []
    controller.frame_loaded.connect(received.append)
    controller.state_manager.set_frame(2)

    assert len(received) == 1
    assert received[0][0, 0] == 2
    assert frame_loader_calls["count"] == 0
    assert controller.state_manager.snapshot.decode_in_progress is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_app_controller_dicom_cache.py -v
```

Expected: FAIL

- [ ] **Step 3: Wire AppController**

Add imports:

```python
from echo_personal_tool.application.frame_cache import FrameCache
from echo_personal_tool.application.workers.dicom_decode_worker import DicomDecodeWorker
```

In `__init__`, add:

```python
self._frame_cache = FrameCache()
self._decode_request_id = 0
self._pending_decode_id = 0
```

Add constant at module level:

```python
_FRAME_CACHE_WARN_BYTES = 512 * 1024 * 1024
```

Replace `load_instance` body logic after metadata read:

```python
self._frame_cache.clear()
self._loaded_source_path = None
self._loaded_frame_index = None
self._pending_source_path = None
self._pending_frame_index = None
self._current_frame_pixels = None
self._segment_in_progress = False
self._state_manager.set_instance(instance, total_frames=total_frames, frame_time_ms=frame_time_ms)
if frame_index != 0:
    self._state_manager.set_frame(frame_index)

if instance.media_format == "dicom":
    self._state_manager.set_decode_in_progress(True)
    self._decode_request_id += 1
    request_id = self._decode_request_id
    self._pending_decode_id = request_id
    self.status_message.emit(
        f"Decoding {instance.path.name}… ({total_frames} frames)"
    )
    worker = DicomDecodeWorker(instance.path, request_id=request_id, parent=self)
    worker.signals.finished.connect(self._on_dicom_decoded)
    worker.signals.failed.connect(self._on_dicom_decode_failed)
    self._thread_pool.start(worker)
    return

# non-DICOM: existing frame load via state change
self._request_frame_if_needed(self._state_manager.snapshot)
```

Add handlers:

```python
def _on_dicom_decoded(self, request_id: int, path: object, frames: object) -> None:
    if request_id != self._pending_decode_id:
        return
    if self._current_instance is None or self._current_instance.path != path:
        return
    if not isinstance(frames, np.ndarray):
        return

    self._pending_decode_id = 0
    self._frame_cache.load(Path(path), frames)
    if self._frame_cache.memory_bytes() > _FRAME_CACHE_WARN_BYTES:
        self.status_message.emit(
            f"Large DICOM cache: {self._frame_cache.memory_bytes() // (1024 * 1024)} MB"
        )

    decoded_count = self._frame_cache.frame_count()
    if decoded_count != self._state_manager.snapshot.total_frames:
        metadata = self._current_instance
        self._state_manager.set_instance(
            metadata,
            total_frames=decoded_count,
            frame_time_ms=self._state_manager.snapshot.frame_time_ms,
        )

    self._state_manager.set_decode_in_progress(False)
    self._emit_cached_frame(self._state_manager.snapshot.current_frame_index)
    self.status_message.emit("Ready")

def _on_dicom_decode_failed(self, request_id: int, message: str) -> None:
    if request_id != self._pending_decode_id:
        return
    self._pending_decode_id = 0
    self._frame_cache.clear()
    self._state_manager.set_decode_in_progress(False)
    self._current_frame_pixels = None
    self.status_message.emit(f"Load failed: {message}")
    self.frame_load_failed.emit(message)

def _emit_cached_frame(self, frame_index: int) -> None:
    if self._current_instance is None or self._current_instance.path is None:
        return
    if not self._frame_cache.is_ready(self._current_instance.path):
        return
    pixels = self._frame_cache.get(frame_index)
    self._loaded_source_path = self._current_instance.path
    self._loaded_frame_index = frame_index
    self._current_frame_pixels = pixels
    self.frame_loaded.emit(pixels)
```

Update `_request_frame_if_needed`:

```python
def _request_frame_if_needed(self, state: ViewerState) -> None:
    if self._current_instance is None or self._current_instance.path is None:
        return

    if (
        self._current_instance.media_format == "dicom"
        and state.decode_in_progress
    ):
        return

    if (
        self._current_instance.media_format == "dicom"
        and self._frame_cache.is_ready(self._current_instance.path)
    ):
        if (
            self._loaded_source_path == self._current_instance.path
            and self._loaded_frame_index == state.current_frame_index
        ):
            return
        self._emit_cached_frame(state.current_frame_index)
        return

    # existing FrameLoaderWorker path unchanged below...
```

Update `_advance_playback`:

```python
def _advance_playback(self) -> None:
    state = self._state_manager.snapshot
    if (
        self._current_instance is not None
        and self._current_instance.media_format == "dicom"
        and self._frame_cache.is_ready(self._current_instance.path)
    ):
        self.step_frame(1)
        return
    if self._pending_load_id != 0:
        return
    self.step_frame(1)
```

When starting new DICOM decode in `load_instance`, cancel stale decode:

```python
self._pending_decode_id = request_id  # already there
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/test_app_controller_dicom_cache.py tests/unit/test_playback_state.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/application/app_controller.py \
  tests/unit/test_app_controller_dicom_cache.py
git commit -m "feat: wire DICOM decode-on-open and FrameCache fast path"
```

---

### Task 6: Full regression + performance smoke

**Files:**
- Modify: `tests/unit/test_frame_cache.py` (optional perf test)

- [ ] **Step 1: Add performance smoke test**

Append to `tests/unit/test_frame_cache.py`:

```python
def test_frame_cache_random_access_is_fast(tmp_path: Path) -> None:
    import time

    path = tmp_path / "clip.dcm"
    frames = np.zeros((50, 64, 64), dtype=np.uint8)
    cache = FrameCache()
    cache.load(path, frames)

    start = time.perf_counter()
    for _ in range(100):
        cache.get(int(np.random.randint(0, 50)))
    elapsed = time.perf_counter() - start
    assert elapsed < 0.1
```

- [ ] **Step 2: Run full test suite**

```bash
uv run pytest -v
```

Expected: all tests PASS

- [ ] **Step 3: Run linter**

```bash
uv run ruff check src tests
```

Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_frame_cache.py
git commit -m "test: add FrameCache random access performance smoke"
```

---

## Spec coverage checklist

| Spec requirement | Task |
|------------------|------|
| DicomSession thread-local | Task 1 |
| FrameCache one instance | Task 2 |
| DicomDecodeWorker | Task 3 |
| decode_in_progress UX | Task 4 |
| AppController fast path | Task 5 |
| No per-frame worker for cached DICOM | Task 5 |
| Playback without pending_load gate | Task 5 |
| MP4/JPEG/PNG unchanged | Task 5 (branch in load_instance) |
| Multiframe fixture | Task 1 |
| 512 MB warning | Task 5 |
| Full pytest pass | Task 6 |

## Success criteria (manual smoke)

1. Open folder with multiframe DICOM → status shows "Decoding…" → first frame appears → slider enabled.
2. Drag slider rapidly → frames update without multi-second lag.
3. Press Play → smooth advance at native FPS.
4. Open MP4 → behavior unchanged from before.
