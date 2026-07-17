# Anatomical M-Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add anatomical M-mode to the echocardiography viewer — a scan line tool that extracts pixel intensities along an arbitrary line across frames and displays them as a scrolling time-motion strip below the 2D viewer.

**Architecture:** New domain models and extractor service, new PyQtGraph MModeWidget panel, new MModeScanLineItem for the 2D viewer, vertical QSplitter layout in MainWindow, coordination via AppController. Follows existing patterns: domain/presentation separation, PyQtGraph for all rendering, Signal-based communication.

**Tech Stack:** PySide6, PyQtGraph, NumPy, SciPy (ndimage.map_coordinates)

## Global Constraints

- Python >= 3.11, PySide6 >= 6.6, pyqtgraph >= 0.13, numpy >= 1.26 < 2.0, scipy >= 1.11
- All rendering via PyQtGraph (`pg.ImageItem`, `pg.PlotWidget`, `pg.ViewBox`)
- Domain models: `@dataclass(frozen=True)`, no mutable state in domain
- Tests: `pytest` + `qtbot`, session-scoped `QApplication` fixture
- i18n: `tr()` from `echo_personal_tool.infrastructure.i18n`
- No comments unless requested. Follow existing code style exactly.
- Hotkey `Shift+M` for M-mode toggle (note: plain `M` is taken by MBS-lite contour mode)

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `src/echo_personal_tool/domain/models/mmode.py` | `MModeScanLine`, `MModeState`, `MModeCaliperMeasurement` dataclasses |
| `src/echo_personal_tool/domain/services/mmode_extractor.py` | `extract_mmode_column()` — bilinear interpolation along a line |
| `src/echo_personal_tool/presentation/mmode_widget.py` | `MModeWidget` — PyQtGraph panel with pg.ImageItem for M-mode strip |
| `src/echo_personal_tool/presentation/mmode_scan_line.py` | `MModeScanLineItem` — dashed line + draggable endpoint markers on 2D viewer |
| `src/echo_personal_tool/presentation/mmode_caliper.py` | `MModeCaliperTool` — distance/time calipers on M-mode panel |
| `tests/unit/test_mmode_extractor.py` | Unit tests for extraction algorithm |
| `tests/unit/test_mmode_widget.py` | Unit tests for MModeWidget buffer and rendering |
| `tests/unit/test_mmode_scan_line.py` | Unit tests for scan line item |

### Modified Files

| File | Changes |
|------|---------|
| `src/echo_personal_tool/presentation/viewer_widget.py` | Add M-mode line signals, `_mmode_scan_line_item`, call extract on frame load, hotkey `M` |
| `src/echo_personal_tool/presentation/main_window.py` | Vertical QSplitter for M-mode, toggle method, `_mmode_widget` |
| `src/echo_personal_tool/application/app_controller.py` | `mmode_active` state, `toggle_mmode()`, coordinate extraction |

---

## Task 1: Domain Models

**Files:**
- Create: `src/echo_personal_tool/domain/models/mmode.py`
- Test: `tests/unit/test_mmode_models.py`

**Interfaces:**
- Consumes: none (leaf module)
- Produces: `MModeScanLine`, `MModeState`, `MModeCaliperMeasurement` — used by all subsequent tasks

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_mmode_models.py
from echo_personal_tool.domain.models.mmode import (
    MModeCaliperMeasurement,
    MModeScanLine,
    MModeState,
)


def test_mmode_scan_line_creation() -> None:
    line = MModeScanLine(start=(10.0, 20.0), end=(100.0, 200.0))
    assert line.start == (10.0, 20.0)
    assert line.end == (100.0, 200.0)
    assert line.num_samples == 256


def test_mmode_scan_line_custom_samples() -> None:
    line = MModeScanLine(start=(0.0, 0.0), end=(50.0, 50.0), num_samples=128)
    assert line.num_samples == 128


def test_mmode_state_defaults() -> None:
    state = MModeState()
    assert state.active is False
    assert state.scan_line is None
    assert state.buffer_width == 512
    assert state.sweep_x == 0


def test_mmode_state_active() -> None:
    line = MModeScanLine(start=(10.0, 20.0), end=(100.0, 200.0))
    state = MModeState(active=True, scan_line=line)
    assert state.active is True
    assert state.scan_line is line


def test_mmode_caliper_distance() -> None:
    cal = MModeCaliperMeasurement(kind="distance", start=(10.0, 5.0), end=(10.0, 50.0))
    assert cal.kind == "distance"
    assert cal.value_mm is None


def test_mmode_caliper_with_values() -> None:
    cal = MModeCaliperMeasurement(
        kind="time", start=(10.0, 0.0), end=(100.0, 0.0), value_ms=320.0
    )
    assert cal.value_ms == 320.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_mmode_models.py -v`
Expected: FAIL — module `echo_personal_tool.domain.models.mmode` not found

- [ ] **Step 3: Write the implementation**

```python
# src/echo_personal_tool/domain/models/mmode.py
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MModeScanLine:
    start: tuple[float, float]
    end: tuple[float, float]
    num_samples: int = 256


@dataclass(frozen=True)
class MModeState:
    active: bool = False
    scan_line: MModeScanLine | None = None
    buffer_width: int = 512
    sweep_x: int = 0


@dataclass(frozen=True)
class MModeCaliperMeasurement:
    kind: str  # "distance" | "time"
    start: tuple[float, float]
    end: tuple[float, float]
    value_mm: float | None = None
    value_ms: float | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_mmode_models.py -v`
Expected: all 6 PASS

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/domain/models/mmode.py tests/unit/test_mmode_models.py
git commit -m "feat(mmode): add domain models for anatomical M-mode"
```

---

## Task 2: M-Mode Extractor

**Files:**
- Create: `src/echo_personal_tool/domain/services/mmode_extractor.py`
- Test: `tests/unit/test_mmode_extractor.py`

**Interfaces:**
- Consumes: none (pure function on numpy arrays)
- Produces: `extract_mmode_column(frame, start, end, num_samples) -> np.ndarray` — used by ViewerWidget and MModeWidget

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_mmode_extractor.py
import numpy as np
import pytest

from echo_personal_tool.domain.services.mmode_extractor import extract_mmode_column


def test_extract_horizontal_line_from_uniform_frame() -> None:
    frame = np.full((100, 100), 128, dtype=np.uint8)
    col = extract_mmode_column(frame, (10.0, 50.0), (90.0, 50.0), num_samples=64)
    assert col.shape == (64,)
    assert col.dtype == np.uint8
    np.testing.assert_array_equal(col, 128)


def test_extract_vertical_line_gradient() -> None:
    frame = np.zeros((100, 100), dtype=np.uint8)
    for y in range(100):
        frame[y, :] = y
    col = extract_mmode_column(frame, (50.0, 0.0), (50.0, 99.0), num_samples=100)
    assert col.shape == (100,)
    assert col[0] == 0
    assert col[-1] == 99


def test_extract_diagonal_line() -> None:
    frame = np.zeros((100, 100), dtype=np.uint8)
    for i in range(100):
        frame[i, i] = 255
    col = extract_mmode_column(frame, (0.0, 0.0), (99.0, 99.0), num_samples=100)
    assert col.shape == (100,)
    assert col[0] == 255
    assert col[-1] == 255


def test_extract_preserves_dtype_uint16() -> None:
    frame = np.full((64, 64), 1000, dtype=np.uint16)
    col = extract_mmode_column(frame, (10.0, 32.0), (50.0, 32.0), num_samples=32)
    assert col.dtype == np.uint16
    np.testing.assert_array_equal(col, 1000)


def test_extract_short_line_minimum_samples() -> None:
    frame = np.full((64, 64), 200, dtype=np.uint8)
    col = extract_mmode_column(frame, (30.0, 30.0), (35.0, 30.0), num_samples=16)
    assert col.shape == (16,)


def test_extract_out_of_bounds_clamps() -> None:
    frame = np.full((64, 64), 50, dtype=np.uint8)
    col = extract_mmode_column(frame, (-10.0, 32.0), (70.0, 32.0), num_samples=32)
    assert col.shape == (32,)
    assert all(v == 50 for v in col)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_mmode_extractor.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Write the implementation**

```python
# src/echo_personal_tool/domain/services/mmode_extractor.py
from __future__ import annotations

import numpy as np
from scipy.ndimage import map_coordinates


def extract_mmode_column(
    frame: np.ndarray,
    start: tuple[float, float],
    end: tuple[float, float],
    num_samples: int = 256,
) -> np.ndarray:
    t = np.linspace(0.0, 1.0, num_samples)
    xs = start[0] + t * (end[0] - start[0])
    ys = start[1] + t * (end[1] - start[1])
    coords = np.array([ys, xs])
    result = map_coordinates(
        frame.astype(np.float64),
        coords,
        order=1,
        mode="nearest",
    )
    return result.astype(frame.dtype)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_mmode_extractor.py -v`
Expected: all 6 PASS

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/domain/services/mmode_extractor.py tests/unit/test_mmode_extractor.py
git commit -m "feat(mmode): add M-mode column extractor via bilinear interpolation"
```

---

## Task 3: MModeWidget

**Files:**
- Create: `src/echo_personal_tool/presentation/mmode_widget.py`
- Test: `tests/unit/test_mmode_widget.py`

**Interfaces:**
- Consumes: `MModeCaliperMeasurement` from Task 1, `extract_mmode_column` from Task 2
- Produces: `MModeWidget` — PyQtGraph widget with `on_new_column()`, `set_scan_line()`, `clear_buffer()`, signals `caliper_measurement_added`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_mmode_widget.py
from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from echo_personal_tool.presentation.mmode_widget import MModeWidget


def test_mmode_widget_creation(qtbot) -> None:
    w = MModeWidget()
    qtbot.addWidget(w)
    assert w._image_buffer is not None
    assert w._sweep_x == 0


def test_mmode_widget_on_new_column(qtbot) -> None:
    w = MModeWidget()
    qtbot.addWidget(w)
    col = np.full(256, 128, dtype=np.uint8)
    w.on_new_column(col)
    assert w._sweep_x == 1
    np.testing.assert_array_equal(w._image_buffer[:, 0], 128)


def test_mmode_widget_buffer_wraps(qtbot) -> None:
    w = MModeWidget(buffer_width=10)
    qtbot.addWidget(w)
    for i in range(15):
        col = np.full(256, i, dtype=np.uint8)
        w.on_new_column(col)
    assert w._sweep_x == 5


def test_mmode_widget_clear_buffer(qtbot) -> None:
    w = MModeWidget()
    qtbot.addWidget(w)
    col = np.full(256, 200, dtype=np.uint8)
    w.on_new_column(col)
    assert w._sweep_x == 1
    w.clear_buffer()
    assert w._sweep_x == 0
    assert w._image_buffer.sum() == 0


def test_mmode_widget_set_scan_line(qtbot) -> None:
    w = MModeWidget()
    qtbot.addWidget(w)
    w.set_scan_line((10.0, 20.0), (100.0, 200.0), num_samples=128)
    assert w._num_samples == 128
    assert w._image_buffer.shape[0] == 128


def test_mmode_widget_recalculate(qtbot) -> None:
    w = MModeWidget(buffer_width=10)
    qtbot.addWidget(w)
    for i in range(5):
        col = np.full(256, i * 10, dtype=np.uint8)
        w.on_new_column(col)
    frames = [np.full((64, 64), i * 10, dtype=np.uint8) for i in range(5)]
    w.recalculate_from_frames(frames, (0.0, 32.0), (63.0, 32.0))
    assert w._sweep_x == 5


def test_mmode_widget_time_calibration(qtbot) -> None:
    w = MModeWidget()
    qtbot.addWidget(w)
    w.set_time_calibration_ms_per_pixel(3.3)
    assert w._time_ms_per_pixel == 3.3


def test_mmode_widget_depth_calibration(qtbot) -> None:
    w = MModeWidget()
    qtbot.addWidget(w)
    w.set_depth_calibration_mm_per_pixel(0.15)
    assert w._depth_mm_per_pixel == 0.15


@pytest.fixture(scope="session", autouse=True)
def _qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_mmode_widget.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Write the implementation**

```python
# src/echo_personal_tool/presentation/mmode_widget.py
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout

from echo_personal_tool.domain.services.mmode_extractor import extract_mmode_column


class MModeWidget(QWidget):
    caliper_measurement_added = Signal(object)

    def __init__(self, buffer_width: int = 512, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._buffer_width = buffer_width
        self._num_samples = 256
        self._sweep_x = 0
        self._scan_start: tuple[float, float] | None = None
        self._scan_end: tuple[float, float] | None = None
        self._time_ms_per_pixel: float | None = None
        self._depth_mm_per_pixel: float | None = None

        self._image_buffer = np.zeros(
            (self._num_samples, self._buffer_width), dtype=np.uint8
        )

        self._plot = pg.PlotWidget()
        self._plot.setLabel("bottom", "Time", units="px")
        self._plot.setLabel("left", "Depth", units="px")
        self._plot.showGrid(x=True, y=True, alpha=0.3)
        self._plot.setMinimumHeight(150)

        self._view_box = self._plot.getPlotItem().getViewBox()
        self._image_item = pg.ImageItem(axisOrder="row-major")
        self._view_box.addItem(self._image_item)
        self._image_item.setImage(self._image_buffer, autoLevels=True)

        self._sweep_line = pg.InfiniteLine(
            angle=90, pen=pg.mkPen("red", width=1, style=Qt.DashLine), movable=False
        )
        self._view_box.addItem(self._sweep_line)
        self._sweep_line.setValue(0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._plot)

    def set_scan_line(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        num_samples: int = 256,
    ) -> None:
        self._scan_start = start
        self._scan_end = end
        if num_samples != self._num_samples:
            self._num_samples = num_samples
            self._image_buffer = np.zeros(
                (self._num_samples, self._buffer_width), dtype=np.uint8
            )
            self._sweep_x = 0
            self._image_item.setImage(self._image_buffer, autoLevels=True)
            self._sweep_line.setValue(0)

    def on_new_column(self, column: np.ndarray) -> None:
        n = min(column.shape[0], self._num_samples)
        self._image_buffer[:n, self._sweep_x] = column[:n]
        self._sweep_x = (self._sweep_x + 1) % self._buffer_width
        self._image_item.setImage(self._image_buffer, autoLevels=True)
        self._sweep_line.setValue(self._sweep_x)

    def clear_buffer(self) -> None:
        self._image_buffer[:] = 0
        self._sweep_x = 0
        self._image_item.setImage(self._image_buffer, autoLevels=True)
        self._sweep_line.setValue(0)

    def recalculate_from_frames(
        self,
        frames: list[np.ndarray],
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> None:
        self.clear_buffer()
        self._scan_start = start
        self._scan_end = end
        for frame in frames:
            col = extract_mmode_column(frame, start, end, self._num_samples)
            self.on_new_column(col)

    def set_time_calibration_ms_per_pixel(self, ms_per_pixel: float) -> None:
        self._time_ms_per_pixel = ms_per_pixel
        self._plot.setLabel("bottom", "Time", units="ms")

    def set_depth_calibration_mm_per_pixel(self, mm_per_pixel: float) -> None:
        self._depth_mm_per_pixel = mm_per_pixel
        self._plot.setLabel("left", "Depth", units="mm")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_mmode_widget.py -v`
Expected: all 8 PASS

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/presentation/mmode_widget.py tests/unit/test_mmode_widget.py
git commit -m "feat(mmode): add MModeWidget PyQtGraph panel with sweep display"
```

---

## Task 4: MModeScanLineItem

**Files:**
- Create: `src/echo_personal_tool/presentation/mmode_scan_line.py`
- Test: `tests/unit/test_mmode_scan_line.py`

**Interfaces:**
- Consumes: `MModeScanLine` from Task 1
- Produces: `MModeScanLineItem(QObject)` — manages `pg.PlotDataItem` (dashed line) + `_MModeNodeItem(pg.ScatterPlotItem)` (draggable markers), added to ViewerWidget's ContourViewBox via `view.addItem()`
- Pattern: follows `_CaliperNodeItem` / `_ContourNodeItem` conventions (back-reference to ViewerWidget, mouse events delegate to viewer handlers)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_mmode_scan_line.py
from __future__ import annotations

import pytest
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

from echo_personal_tool.presentation.mmode_scan_line import MModeScanLineItem, _MModeNodeItem


def test_scan_line_is_qobject(qtbot) -> None:
    item = MModeScanLineItem(viewer_widget=None)
    assert isinstance(item, QObject)


def test_scan_line_creation(qtbot) -> None:
    item = MModeScanLineItem(viewer_widget=None)
    assert item.line_start is None
    assert item.line_end is None
    assert not item.is_complete


def test_scan_line_set_start(qtbot) -> None:
    item = MModeScanLineItem(viewer_widget=None)
    item.set_start((10.0, 20.0))
    assert item.line_start == (10.0, 20.0)
    assert not item.is_complete


def test_scan_line_set_end(qtbot) -> None:
    item = MModeScanLineItem(viewer_widget=None)
    item.set_start((10.0, 20.0))
    item.set_end((100.0, 200.0))
    assert item.line_end == (100.0, 200.0)
    assert item.is_complete


def test_scan_line_get_endpoints(qtbot) -> None:
    item = MModeScanLineItem(viewer_widget=None)
    item.set_start((10.0, 20.0))
    item.set_end((100.0, 200.0))
    start, end = item.get_endpoints()
    assert start == (10.0, 20.0)
    assert end == (100.0, 200.0)


def test_scan_line_move_endpoints(qtbot) -> None:
    item = MModeScanLineItem(viewer_widget=None)
    item.set_start((10.0, 20.0))
    item.set_end((100.0, 200.0))
    item.move_start_to((15.0, 25.0))
    item.move_end_to((95.0, 195.0))
    start, end = item.get_endpoints()
    assert start == (15.0, 25.0)
    assert end == (95.0, 195.0)


def test_scan_line_clear(qtbot) -> None:
    item = MModeScanLineItem(viewer_widget=None)
    item.set_start((10.0, 20.0))
    item.set_end((100.0, 200.0))
    item.clear()
    assert item.line_start is None
    assert item.line_end is None
    assert item._line_item is None
    assert item._start_node is None
    assert item._end_node is None


def test_scan_line_preview(qtbot) -> None:
    item = MModeScanLineItem(viewer_widget=None)
    item.set_start((10.0, 20.0))
    item.update_preview((50.0, 50.0))
    assert item.line_start == (10.0, 20.0)
    assert item.line_end == (50.0, 50.0)


def test_scan_line_graphics_created_on_set_end(qtbot) -> None:
    item = MModeScanLineItem(viewer_widget=None)
    item.set_start((10.0, 20.0))
    item.set_end((100.0, 200.0))
    assert item._line_item is not None
    assert item._start_node is not None
    assert item._end_node is not None


def test_mmode_node_item_is_scatter(qtbot) -> None:
    node = _MModeNodeItem(viewer_widget=None, endpoint_index=0, position=(10.0, 20.0))
    import pyqtgraph as pg
    assert isinstance(node, pg.ScatterPlotItem)


@pytest.fixture(scope="session", autouse=True)
def _qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_mmode_scan_line.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Write the implementation**

```python
# src/echo_personal_tool/presentation/mmode_scan_line.py
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget
import pyqtgraph as pg


class _MModeNodeItem(pg.ScatterPlotItem):
    """Single draggable M-mode scan line endpoint node."""

    def __init__(
        self,
        viewer_widget: QWidget | None,
        endpoint_index: int,
        position: tuple[float, float],
    ) -> None:
        super().__init__(symbol="o", size=10, pen=pg.mkPen("cyan"), brush=pg.mkBrush("cyan"))
        self._viewer_widget = viewer_widget
        self._endpoint_index = endpoint_index
        self.setZValue(30)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setAcceptHoverEvents(True)
        self.setData([position[0]], [position[1]])

    def mousePressEvent(self, ev: object) -> None:
        if self._viewer_widget is not None:
            self._viewer_widget._begin_mmode_node_drag(self._endpoint_index)
        ev.accept()

    def mouseDragEvent(self, ev: object) -> None:
        if self._viewer_widget is not None and hasattr(ev, 'scenePos'):
            view_box = self.getViewBox()
            if view_box is not None:
                pos = view_box.mapSceneToView(ev.scenePos())
                self._viewer_widget._mmode_node_dragging(self._endpoint_index, (pos.x(), pos.y()))
        ev.accept()

    def mouseReleaseEvent(self, ev: object) -> None:
        if self._viewer_widget is not None:
            self._viewer_widget._end_mmode_node_drag(self._endpoint_index)
        ev.accept()


class MModeScanLineItem:
    """Manages M-mode scan line graphics on the 2D viewer.

    Not a QWidget — created by ViewerWidget and added to ContourViewBox via view.addItem().
    Follows the _CaliperNodeItem pattern: PlotDataItem for line, ScatterPlotItem for endpoints.
    """

    def __init__(self, viewer_widget: QWidget | None) -> None:
        self._viewer_widget = viewer_widget
        self.line_start: tuple[float, float] | None = None
        self.line_end: tuple[float, float] | None = None
        self._line_item: pg.PlotDataItem | None = None
        self._start_node: _MModeNodeItem | None = None
        self._end_node: _MModeNodeItem | None = None

    @property
    def is_complete(self) -> bool:
        return self.line_start is not None and self.line_end is not None

    def set_start(self, pos: tuple[float, float]) -> None:
        self.line_start = pos
        self.line_end = None
        self._remove_graphics()

    def set_end(self, pos: tuple[float, float]) -> None:
        self.line_end = pos
        self._create_graphics()

    def get_endpoints(self) -> tuple[tuple[float, float], tuple[float, float]]:
        assert self.line_start is not None and self.line_end is not None
        return self.line_start, self.line_end

    def move_start_to(self, pos: tuple[float, float]) -> None:
        self.line_start = pos
        self._update_graphics()

    def move_end_to(self, pos: tuple[float, float]) -> None:
        self.line_end = pos
        self._update_graphics()

    def clear(self) -> None:
        self.line_start = None
        self.line_end = None
        self._remove_graphics()

    def update_preview(self, mouse_pos: tuple[float, float]) -> None:
        if self.line_start is not None:
            self.line_end = mouse_pos
            self._update_graphics()

    def add_to_view(self, view: pg.ViewBox) -> None:
        if self._line_item is not None:
            view.addItem(self._line_item)
        if self._start_node is not None:
            view.addItem(self._start_node)
        if self._end_node is not None:
            view.addItem(self._end_node)

    def remove_from_view(self, view: pg.ViewBox) -> None:
        self._remove_graphics(view)

    def _create_graphics(self) -> None:
        self._remove_graphics()
        pen = pg.mkPen(color="cyan", style=Qt.PenStyle.DashLine, width=1.5)
        self._line_item = pg.PlotDataItem(
            pen=pen,
            symbol=None,
            antialias=True,
        )
        self._line_item.setZValue(24)
        self._start_node = _MModeNodeItem(self._viewer_widget, 0, self.line_start)
        self._end_node = _MModeNodeItem(self._viewer_widget, 1, self.line_end)
        self._sync_line_data()

    def _update_graphics(self) -> None:
        if self._line_item is not None and self.line_start is not None and self.line_end is not None:
            self._sync_line_data()
        if self._start_node is not None and self.line_start is not None:
            self._start_node.setData([self.line_start[0]], [self.line_start[1]])
        if self._end_node is not None and self.line_end is not None:
            self._end_node.setData([self.line_end[0]], [self.line_end[1]])

    def _sync_line_data(self) -> None:
        if self._line_item is not None and self.line_start is not None and self.line_end is not None:
            self._line_item.setData(
                [self.line_start[0], self.line_end[0]],
                [self.line_start[1], self.line_end[1]],
            )

    def _remove_graphics(self, view: pg.ViewBox | None = None) -> None:
        for item in (self._line_item, self._start_node, self._end_node):
            if item is not None and view is not None:
                view.removeItem(item)
        self._line_item = None
        self._start_node = None
        self._end_node = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_mmode_scan_line.py -v`
Expected: all 10 PASS

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/presentation/mmode_scan_line.py tests/unit/test_mmode_scan_line.py
git commit -m "feat(mmode): add MModeScanLineItem with draggable nodes on ViewBox"
```

---

## Task 5: Layout Integration (MainWindow)

**Files:**
- Modify: `src/echo_personal_tool/presentation/main_window.py`

**Interfaces:**
- Consumes: `MModeWidget` from Task 3
- Produces: `MainWindow._mmode_widget`, `MainWindow._toggle_mmode()`, vertical splitter in layout

- [ ] **Step 1: Add MModeWidget import and instance variable**

In `main_window.py`, add after existing imports (around line 71):

```python
from echo_personal_tool.presentation.mmode_widget import MModeWidget
```

In `MainWindow.__init__`, add after `self._viewer` creation (around line 155):

```python
self._mmode_widget: MModeWidget | None = None
self._mmode_active = False
self._mmode_vertical_splitter: QSplitter | None = None
```

- [ ] **Step 2: Add toggle method**

Add to `MainWindow` class:

```python
    def _toggle_mmode(self) -> None:
        self._mmode_active = not self._mmode_active
        if self._mmode_active:
            self._activate_mmode()
        else:
            self._deactivate_mmode()

    def _activate_mmode(self) -> None:
        if self._mmode_widget is None:
            self._mmode_widget = MModeWidget()
        self._mmode_vertical_splitter = QSplitter(Qt.Vertical)
        self._mmode_vertical_splitter.setHandleWidth(4)
        self._mmode_vertical_splitter.addWidget(self._viewer)
        self._mmode_vertical_splitter.addWidget(self._mmode_widget)
        self._mmode_vertical_splitter.setSizes([500, 500])
        self._mmode_vertical_splitter.setStretchFactor(0, 1)
        self._mmode_vertical_splitter.setStretchFactor(1, 1)

        index = self._content_splitter.indexOf(self._viewer)
        if index >= 0:
            self._content_splitter.insertWidget(index, self._mmode_vertical_splitter)
            self._content_splitter.setStretchFactor(index, 1)
            self._mmode_vertical_splitter.show()

    def _deactivate_mmode(self) -> None:
        if self._mmode_vertical_splitter is None:
            return
        index = self._content_splitter.indexOf(self._mmode_vertical_splitter)
        if index >= 0:
            self._content_splitter.insertWidget(index, self._viewer)
            self._content_splitter.setStretchFactor(index, 1)
        self._mmode_vertical_splitter.deleteLater()
        self._mmode_vertical_splitter = None
        if self._mmode_widget is not None:
            self._mmode_widget.clear_buffer()
```

- [ ] **Step 3: Connect hotkey**

In `MainWindow.__init__`, after existing shortcuts are set up (around line 200):

```python
        m_shortcut = QShortcut(QKeySequence("Shift+M"), self)
        m_shortcut.activated.connect(self._toggle_mmode)
```

- [ ] **Step 4: Run existing tests to verify no regressions**

Run: `pytest tests/unit/test_linear_caliper_click_click.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/presentation/main_window.py
git commit -m "feat(mmode): add vertical splitter layout toggle in MainWindow"
```

---

## Task 6: Viewer Integration (Scan Line on 2D Viewer)

**Files:**
- Modify: `src/echo_personal_tool/presentation/viewer_widget.py`

**Interfaces:**
- Consumes: `MModeScanLineItem` from Task 4, `extract_mmode_column` from Task 2, `MModeWidget` from Task 3
- Produces: `ViewerWidget.mmode_column_ready` signal, `start_mmode_line()`, `_handle_mmode_line_click()`, integration with `show_frame()`

- [ ] **Step 1: Add signals and state to ViewerWidget**

In `ViewerWidget.__init__` state variables (around line 640):

```python
        self._mmode_line_active = False
        self._mmode_line_item: MModeScanLineItem | None = None
        self._mmode_line_click_step: Literal["start", "end"] | None = None
```

Add new signals after existing signals (around line 595):

```python
    mmode_column_ready = Signal(object, object)  # (column: np.ndarray, frame_index: int)
    mmode_line_completed = Signal(object, object)  # (start: tuple, end: tuple)
```

- [ ] **Step 2: Add start_mmode_line method**

Add to `ViewerWidget` class:

```python
    def start_mmode_line(self) -> None:
        from echo_personal_tool.presentation.mmode_scan_line import MModeScanLineItem
        self._mmode_line_active = True
        self._mmode_line_click_step = "start"
        if self._mmode_line_item is not None:
            self._mmode_line_item.remove_from_view(self._view)
        self._mmode_line_item = MModeScanLineItem(viewer_widget=self)
        self.setCursor(Qt.CrossCursor)
```

- [ ] **Step 3: Add cancel_mmode_line method**

```python
    def cancel_mmode_line(self) -> None:
        if self._mmode_line_item is not None:
            self._mmode_line_item.remove_from_view(self._view)
        self._mmode_line_active = False
        self._mmode_line_click_step = None
        self._mmode_line_item = None
        self.setCursor(Qt.ArrowCursor)
```

- [ ] **Step 4: Add click handler for M-mode line**

Add to ContourViewBox.mousePressEvent or ViewerWidget event handling:

```python
    def _handle_mmode_line_click(self, x: float, y: float) -> bool:
        if not self._mmode_line_active or self._mmode_line_item is None:
            return False
        if self._mmode_line_click_step == "start":
            self._mmode_line_item.set_start((x, y))
            self._mmode_line_click_step = "end"
            return True
        elif self._mmode_line_click_step == "end":
            self._mmode_line_item.set_end((x, y))
            self._mmode_line_item.add_to_view(self._view)
            self._mmode_line_active = False
            self._mmode_line_click_step = None
            self.setCursor(Qt.ArrowCursor)
            self.mmode_line_completed.emit(*self._mmode_line_item.get_endpoints())
            return True
        return False
```

Add drag handler methods (called by `_MModeNodeItem`):

```python
    def _begin_mmode_node_drag(self, endpoint_index: int) -> None:
        pass  # drag state managed by ContourViewBox existing drag flow

    def _mmode_node_dragging(self, endpoint_index: int, pos: tuple[float, float]) -> None:
        if self._mmode_line_item is None:
            return
        if endpoint_index == 0:
            self._mmode_line_item.move_start_to(pos)
        else:
            self._mmode_line_item.move_end_to(pos)
        self.mmode_line_completed.emit(*self._mmode_line_item.get_endpoints())

    def _end_mmode_node_drag(self, endpoint_index: int) -> None:
        if self._mmode_line_item is not None:
            self.mmode_line_completed.emit(*self._mmode_line_item.get_endpoints())
```

- [ ] **Step 5: Hook into show_frame to emit column**

In `show_frame()` method (around line 1461), after `self._current_frame = ...`:

```python
        if self._mmode_line_item is not None and self._mmode_line_item.is_complete and self._current_frame is not None:
            start, end = self._mmode_line_item.get_endpoints()
            col = extract_mmode_column(self._current_frame, start, end, num_samples=256)
            self.mmode_column_ready.emit(col, self._current_state.current_frame_index if self._current_state else 0)
```

Also add import at top of file:

```python
from echo_personal_tool.domain.services.mmode_extractor import extract_mmode_column
```

- [ ] **Step 6: Run existing tests to verify no regressions**

Run: `pytest tests/unit/test_linear_caliper_click_click.py -v`
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add src/echo_personal_tool/presentation/viewer_widget.py
git commit -m "feat(mmode): add scan line tool and column extraction to ViewerWidget"
```

---

## Task 7: AppController Coordination

**Files:**
- Modify: `src/echo_personal_tool/application/app_controller.py`

**Interfaces:**
- Consumes: `MModeWidget` from Task 3, signals from ViewerWidget
- Produces: `AppController.toggle_mmode()`, connects frame_loaded to MModeWidget

- [ ] **Step 1: Add MMode state to AppController**

In `AppController.__init__` (around line 100):

```python
        self._mmode_active = False
```

- [ ] **Step 2: Add toggle method**

```python
    def toggle_mmode(self) -> None:
        self._mmode_active = not self._mmode_active
```

- [ ] **Step 3: Connect in MainWindow**

In `MainWindow.__init__`, after connecting other signals (around line 228):

```python
        self._viewer.mmode_column_ready.connect(self._on_mmode_column_ready)
```

Add handler:

```python
    def _on_mmode_column_ready(self, column: object, frame_index: object) -> None:
        if self._mmode_widget is not None and self._mmode_active:
            self._mmode_widget.on_new_column(column)
```

- [ ] **Step 4: Connect mmode_line_completed to recalculate**

```python
    def _on_mmode_line_completed(self, start: object, end: object) -> None:
        if self._mmode_widget is not None:
            cached_frames = self._controller.get_cached_frames() if hasattr(self._controller, 'get_cached_frames') else []
            if cached_frames:
                self._mmode_widget.recalculate_from_frames(cached_frames, start, end)
```

- [ ] **Step 5: Run existing tests**

Run: `pytest tests/unit/test_linear_caliper_click_click.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add src/echo_personal_tool/application/app_controller.py src/echo_personal_tool/presentation/main_window.py
git commit -m "feat(mmode): connect M-mode extraction pipeline in AppController and MainWindow"
```

---

## Task 8: M-Mode Caliper Tool

**Files:**
- Create: `src/echo_personal_tool/presentation/mmode_caliper.py`
- Test: `tests/unit/test_mmode_caliper.py`

**Interfaces:**
- Consumes: `MModeCaliperMeasurement` from Task 1, `MModeWidget` from Task 3
- Produces: `MModeCaliperTool` — calipers on M-mode panel for distance/time

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_mmode_caliper.py
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from echo_personal_tool.presentation.mmode_caliper import MModeCaliperTool


def test_caliper_tool_creation(qtbot) -> None:
    tool = MModeCaliperTool()
    qtbot.addWidget(tool)
    assert tool.measurements == []


def test_caliper_tool_start_distance(qtbot) -> None:
    tool = MModeCaliperTool()
    qtbot.addWidget(tool)
    tool.start_distance_caliper()
    assert tool._active_mode == "distance"


def test_caliper_tool_start_time(qtbot) -> None:
    tool = MModeCaliperTool()
    qtbot.addWidget(tool)
    tool.start_time_caliper()
    assert tool._active_mode == "time"


def test_caliper_tool_click_distance(qtbot) -> None:
    tool = MModeCaliperTool()
    qtbot.addWidget(tool)
    tool.start_distance_caliper()
    tool.on_click(10.0, 5.0)
    assert tool._first_click == (10.0, 5.0)
    tool.on_click(10.0, 50.0)
    assert len(tool.measurements) == 1
    assert tool.measurements[0].kind == "distance"
    assert tool._active_mode is None


def test_caliper_tool_click_time(qtbot) -> None:
    tool = MModeCaliperTool()
    qtbot.addWidget(tool)
    tool.start_time_caliper()
    tool.on_click(5.0, 10.0)
    tool.on_click(100.0, 10.0)
    assert len(tool.measurements) == 1
    assert tool.measurements[0].kind == "time"


def test_caliper_tool_clear(qtbot) -> None:
    tool = MModeCaliperTool()
    qtbot.addWidget(tool)
    tool.start_distance_caliper()
    tool.on_click(10.0, 5.0)
    tool.on_click(10.0, 50.0)
    tool.clear()
    assert tool.measurements == []


def test_caliper_tool_with_calibration(qtbot) -> None:
    tool = MModeCaliperTool(depth_mm_per_pixel=0.15, time_ms_per_pixel=3.3)
    qtbot.addWidget(tool)
    tool.start_distance_caliper()
    tool.on_click(10.0, 5.0)
    tool.on_click(10.0, 50.0)
    assert tool.measurements[0].value_mm is not None
    assert tool.measurements[0].value_mm == pytest.approx(6.75, rel=0.01)


@pytest.fixture(scope="session", autouse=True)
def _qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_mmode_caliper.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Write the implementation**

```python
# src/echo_personal_tool/presentation/mmode_caliper.py
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget
import pyqtgraph as pg

from echo_personal_tool.domain.models.mmode import MModeCaliperMeasurement


class MModeCaliperTool(QWidget):
    measurement_added = Signal(object)

    def __init__(
        self,
        depth_mm_per_pixel: float | None = None,
        time_ms_per_pixel: float | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._depth_mm_per_pixel = depth_mm_per_pixel
        self._time_ms_per_pixel = time_ms_per_pixel
        self._active_mode: str | None = None
        self._first_click: tuple[float, float] | None = None
        self.measurements: list[MModeCaliperMeasurement] = []

    def start_distance_caliper(self) -> None:
        self._active_mode = "distance"
        self._first_click = None

    def start_time_caliper(self) -> None:
        self._active_mode = "time"
        self._first_click = None

    def on_click(self, x: float, y: float) -> None:
        if self._active_mode is None:
            return
        if self._first_click is None:
            self._first_click = (x, y)
            return
        cal = MModeCaliperMeasurement(
            kind=self._active_mode,
            start=self._first_click,
            end=(x, y),
        )
        if cal.kind == "distance" and self._depth_mm_per_pixel is not None:
            dist_px = abs(y - self._first_click[1])
            cal = MModeCaliperMeasurement(
                kind="distance",
                start=self._first_click,
                end=(x, y),
                value_mm=dist_px * self._depth_mm_per_pixel,
            )
        elif cal.kind == "time" and self._time_ms_per_pixel is not None:
            time_px = abs(x - self._first_click[0])
            cal = MModeCaliperMeasurement(
                kind="time",
                start=self._first_click,
                end=(x, y),
                value_ms=time_px * self._time_ms_per_pixel,
            )
        self.measurements.append(cal)
        self._first_click = None
        self._active_mode = None
        self.measurement_added.emit(cal)

    def clear(self) -> None:
        self.measurements.clear()
        self._first_click = None
        self._active_mode = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_mmode_caliper.py -v`
Expected: all 7 PASS

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/presentation/mmode_caliper.py tests/unit/test_mmode_caliper.py
git commit -m "feat(mmode): add MModeCaliperTool for distance/time measurements"
```

---

## Task 9: End-to-End Integration

**Files:**
- Modify: `src/echo_personal_tool/presentation/main_window.py`
- Test: `tests/unit/test_mmode_integration.py`

**Interfaces:**
- Consumes: all previous tasks
- Produces: Full M-mode flow: hotkey M → scan line → playback → M-mode sweep

- [ ] **Step 1: Write integration test**

```python
# tests/unit/test_mmode_integration.py
from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.domain.models import InstanceMetadata
from echo_personal_tool.domain.models.viewer_state import ViewerState
from echo_personal_tool.presentation.main_window import MainWindow
from echo_personal_tool.presentation.mmode_widget import MModeWidget
from echo_personal_tool.presentation.mmode_scan_line import MModeScanLineItem
from echo_personal_tool.domain.services.mmode_extractor import extract_mmode_column


def _sample_instance() -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid="1.2.3.4.5",
        series_uid="1.2.3.4.6",
        modality="US",
        number_of_frames=10,
        pixel_spacing=(0.5, 0.5),
        frame_time_ms=33.3,
        series_description="Test",
        path=None,
    )


def test_mmode_toggle_creates_widget(qtbot) -> None:
    controller = AppController()
    controller.state_manager.set_instance(
        _sample_instance(), total_frames=10, frame_time_ms=33.3,
    )
    window = MainWindow(controller=controller)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    window._toggle_mmode()
    assert window._mmode_active
    assert window._mmode_widget is not None
    window._toggle_mmode()
    assert not window._mmode_active


def test_mmode_extraction_pipeline() -> None:
    frame = np.zeros((100, 100), dtype=np.uint8)
    for y in range(100):
        frame[y, :] = y
    col = extract_mmode_column(frame, (50.0, 0.0), (50.0, 99.0), num_samples=50)
    assert col.shape == (50,)
    assert col[0] == 0
    assert col[-1] == 99


def test_mmode_widget_recieves_columns(qtbot) -> None:
    widget = MModeWidget(buffer_width=20)
    qtbot.addWidget(widget)
    for i in range(10):
        col = np.full(256, i * 10, dtype=np.uint8)
        widget.on_new_column(col)
    assert widget._sweep_x == 10
    assert widget._image_buffer[0, 0] == 0
    assert widget._image_buffer[0, 9] == 90


def test_mmode_scan_line_endpoints() -> None:
    item = MModeScanLineItem()
    item.set_start((20.0, 30.0))
    item.set_end((80.0, 70.0))
    start, end = item.get_endpoints()
    assert start == (20.0, 30.0)
    assert end == (80.0, 70.0)
    assert item.is_complete


def test_mmode_caliper_with_full_pipeline() -> None:
    from echo_personal_tool.presentation.mmode_caliper import MModeCaliperTool
    tool = MModeCaliperTool(depth_mm_per_pixel=0.2, time_ms_per_pixel=5.0)
    tool.start_distance_caliper()
    tool.on_click(10.0, 10.0)
    tool.on_click(10.0, 60.0)
    assert tool.measurements[0].value_mm == pytest.approx(10.0)
    tool.start_time_caliper()
    tool.on_click(5.0, 30.0)
    tool.on_click(65.0, 30.0)
    assert tool.measurements[1].value_ms == pytest.approx(300.0)


@pytest.fixture(scope="session", autouse=True)
def _qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app
```

- [ ] **Step 2: Run all tests**

Run: `pytest tests/unit/test_mmode_models.py tests/unit/test_mmode_extractor.py tests/unit/test_mmode_widget.py tests/unit/test_mmode_scan_line.py tests/unit/test_mmode_caliper.py tests/unit/test_mmode_integration.py -v`
Expected: all PASS

- [ ] **Step 3: Run full test suite for regressions**

Run: `pytest tests/ -v --timeout=60`
Expected: all existing tests still PASS

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat(mmode): complete anatomical M-mode implementation"
```
