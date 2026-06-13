# Simpson Open Arc Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade manual Simpson to EchoPAC/QLAB-style open endocardial arc (septum → apex → lateral, base on mitral annulus line) with B-spline display, equal arc-length node spacing on drag, and correct MA→apex long axis for 20-disk volume.

**Architecture:** Extend `Contour` with optional `mitral_annulus` (septal, lateral). New pure-domain module `contour_geometry.py` handles B-spline evaluation, equal arc-length resampling, apex/long-axis helpers. `lvef_simpson.py` uses closed polygon (arc + MA chord) with perpendicular widths along MA-midpoint→apex axis. `ViewerWidget` gains staged click workflow (MA septal → MA lateral → arc clicks) and resamples on every node drag.

**Tech Stack:** Python 3.11, NumPy, SciPy (`scipy.interpolate.splprep`/`splev`), PySide6/pyqtgraph (presentation only).

---

## File map

| File | Responsibility |
|------|----------------|
| `domain/models/contour.py` | Add `mitral_annulus`, `num_nodes`, helpers `is_open_arc`, `closed_polygon_points` |
| `domain/services/contour_geometry.py` | Spline, resample, drag-node, apex, long axis |
| `domain/calculations/lvef_simpson.py` | MA→apex axis, perpendicular disk widths |
| `domain/services/segmentation_service.py` | `closed_polygon_to_open_arc` for AI contours |
| `presentation/viewer_widget.py` | Staged drawing, arc+chord render, drag resample |
| `tests/unit/test_contour_geometry.py` | Geometry unit tests |
| `tests/unit/test_lvef_simpson.py` | Updated Simpson tests with open arcs |
| `tests/unit/test_contour.py`, `test_spline_editor.py` | Viewer integration updates |

**Backward compatibility:** `mitral_annulus is None` → legacy closed-polygon Simpson (bounding-box axis) for existing tests/AI until converted.

---

### Task 1: Domain `contour_geometry` — equal arc-length resampling

**Files:**
- Create: `src/echo_personal_tool/domain/services/contour_geometry.py`
- Create: `tests/unit/test_contour_geometry.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_contour_geometry.py
"""Unit tests for open-arc contour geometry."""

from __future__ import annotations

import math

import numpy as np
import pytest

from echo_personal_tool.domain.services.contour_geometry import (
    DEFAULT_NODE_COUNT,
    apex_point,
    long_axis_endpoints,
    move_node_and_resample,
    resample_open_arc,
    sample_spline,
)


def _semicircle_arc(num: int = 5) -> list[tuple[float, float]]:
    """Open arc: (0,0) septal → semicircle → (10,0) lateral."""
    angles = np.linspace(math.pi, 0.0, num)
    return [(5.0 + 5.0 * math.cos(a), 5.0 * math.sin(a)) for a in angles]


def test_resample_open_arc_preserves_endpoints_and_count() -> None:
    arc = _semicircle_arc(4)
    result = resample_open_arc(arc, num_nodes=8)
    assert len(result) == 8
    assert result[0] == pytest.approx(arc[0], abs=1e-3)
    assert result[-1] == pytest.approx(arc[-1], abs=1e-3)


def test_resample_open_arc_equal_spacing() -> None:
    arc = _semicircle_arc(4)
    result = resample_open_arc(arc, num_nodes=9)
    seg_lens = [
        math.hypot(result[i + 1][0] - result[i][0], result[i + 1][1] - result[i][1])
        for i in range(len(result) - 1)
    ]
    assert max(seg_lens) - min(seg_lens) == pytest.approx(0.0, abs=0.5)


def test_move_node_and_resample_moves_interior_point() -> None:
    arc = resample_open_arc(_semicircle_arc(5), num_nodes=DEFAULT_NODE_COUNT)
    moved = move_node_and_resample(arc, node_index=DEFAULT_NODE_COUNT // 2, x=5.0, y=8.0)
    assert len(moved) == DEFAULT_NODE_COUNT
    mid = DEFAULT_NODE_COUNT // 2
    assert moved[mid][1] == pytest.approx(8.0, abs=0.5)


def test_apex_point_farthest_from_annulus() -> None:
    arc = _semicircle_arc(7)
    annulus = (arc[0], arc[-1])
    apex = apex_point(arc, annulus)
    assert apex[1] == pytest.approx(5.0, abs=0.2)


def test_long_axis_endpoints_mid_annulus_to_apex() -> None:
    arc = _semicircle_arc(7)
    annulus = (arc[0], arc[-1])
    base, tip = long_axis_endpoints(arc, annulus)
    assert base == pytest.approx((5.0, 0.0), abs=0.2)
    assert tip[1] > base[1]


def test_sample_spline_returns_dense_curve() -> None:
    arc = _semicircle_arc(5)
    dense = sample_spline(arc, num_samples=50)
    assert len(dense) == 50
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd <worktree> && python -m pytest tests/unit/test_contour_geometry.py -v`
Expected: FAIL — `ModuleNotFoundError: contour_geometry`

- [ ] **Step 3: Implement `contour_geometry.py`**

```python
# src/echo_personal_tool/domain/services/contour_geometry.py
"""Open-arc endocardial contour geometry (pure NumPy/SciPy)."""

from __future__ import annotations

import math

import numpy as np
from scipy.interpolate import splprep, splev

DEFAULT_NODE_COUNT = 32


def resample_open_arc(
    points: list[tuple[float, float]],
    *,
    num_nodes: int = DEFAULT_NODE_COUNT,
) -> list[tuple[float, float]]:
    """Resample open arc to num_nodes with equal arc-length spacing; endpoints fixed."""
    if num_nodes <= 0:
        return []
    if not points:
        return []
    if len(points) == 1:
        return [points[0]] * num_nodes
    if len(points) == 2:
        return _resample_polyline(points, num_nodes=num_nodes)

    dense = sample_spline(points, num_samples=max(num_nodes * 8, 64))
    return _resample_polyline(dense, num_nodes=num_nodes)


def move_node_and_resample(
    points: list[tuple[float, float]],
    *,
    node_index: int,
    x: float,
    y: float,
    num_nodes: int = DEFAULT_NODE_COUNT,
) -> list[tuple[float, float]]:
    """Move one control node, fit spline, return equal-spaced resample."""
    if not points:
        return []
    updated = list(points)
    if node_index < 0 or node_index >= len(updated):
        return resample_open_arc(updated, num_nodes=num_nodes)
    updated[node_index] = (float(x), float(y))
    return resample_open_arc(updated, num_nodes=num_nodes)


def sample_spline(
    points: list[tuple[float, float]],
    *,
    num_samples: int = 100,
) -> list[tuple[float, float]]:
    """Evaluate cubic B-spline through control points (open curve)."""
    if len(points) < 2:
        return list(points)
    if len(points) == 2:
        return _resample_polyline(points, num_nodes=num_samples)

    coords = np.asarray(points, dtype=np.float64).T
    tck, _ = splprep(coords, s=0.0, k=min(3, len(points) - 1))
    u = np.linspace(0.0, 1.0, num_samples)
    x, y = splev(u, tck)
    return [(float(xi), float(yi)) for xi, yi in zip(x, y, strict=True)]


def apex_point(
    arc_points: list[tuple[float, float]],
    mitral_annulus: tuple[tuple[float, float], tuple[float, float]],
) -> tuple[float, float]:
    """Point on arc with maximum perpendicular distance from mitral annulus line."""
    septal, lateral = mitral_annulus
    if not arc_points:
        mid = ((septal[0] + lateral[0]) / 2.0, (septal[1] + lateral[1]) / 2.0)
        return mid
    best = arc_points[0]
    best_dist = _point_line_distance(best, septal, lateral)
    for point in arc_points[1:]:
        dist = _point_line_distance(point, septal, lateral)
        if dist > best_dist:
            best = point
            best_dist = dist
    return best


def long_axis_endpoints(
    arc_points: list[tuple[float, float]],
    mitral_annulus: tuple[tuple[float, float], tuple[float, float]],
) -> tuple[tuple[float, float], tuple[float, float]]:
    """MA midpoint (base) and apex (tip) for Simpson long axis."""
    septal, lateral = mitral_annulus
    base = ((septal[0] + lateral[0]) / 2.0, (septal[1] + lateral[1]) / 2.0)
    tip = apex_point(arc_points, mitral_annulus)
    return base, tip


def _resample_polyline(
    points: list[tuple[float, float]],
    *,
    num_nodes: int,
) -> list[tuple[float, float]]:
    if num_nodes <= 0:
        return []
    if len(points) == 1:
        return [points[0]] * num_nodes

    segments = np.diff(np.asarray(points, dtype=np.float64), axis=0)
    seg_lens = np.linalg.norm(segments, axis=1)
    cumulative = np.concatenate([[0.0], np.cumsum(seg_lens)])
    total = cumulative[-1]
    if total == 0.0:
        return [points[0]] * num_nodes

    targets = np.linspace(0.0, total, num_nodes)
    result: list[tuple[float, float]] = []
    for target in targets:
        idx = int(np.searchsorted(cumulative, target, side="right") - 1)
        idx = min(idx, len(points) - 2)
        start_len = cumulative[idx]
        end_len = cumulative[idx + 1]
        if end_len > start_len:
            alpha = (target - start_len) / (end_len - start_len)
        else:
            alpha = 0.0
        start = np.asarray(points[idx], dtype=np.float64)
        end = np.asarray(points[idx + 1], dtype=np.float64)
        pt = start + alpha * (end - start)
        result.append((float(pt[0]), float(pt[1])))
    return result


def _point_line_distance(
    point: tuple[float, float],
    line_a: tuple[float, float],
    line_b: tuple[float, float],
) -> float:
    ax, ay = line_a
    bx, by = line_b
    px, py = point
    dx = bx - ax
    dy = by - ay
    length = math.hypot(dx, dy)
    if length == 0.0:
        return math.hypot(px - ax, py - ay)
    return abs(dy * px - dx * py + bx * ay - by * ax) / length
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/unit/test_contour_geometry.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/domain/services/contour_geometry.py tests/unit/test_contour_geometry.py
git commit -m "feat: add open-arc contour geometry with equal spacing resample"
```

---

### Task 2: Extend `Contour` domain model

**Files:**
- Modify: `src/echo_personal_tool/domain/models/contour.py`
- Modify: `tests/unit/test_contour.py`

- [ ] **Step 1: Write failing test**

```python
def test_contour_open_arc_helpers() -> None:
    from echo_personal_tool.domain.models import Contour

    annulus = ((0.0, 0.0), (10.0, 0.0))
    contour = Contour(
        phase="ED",
        mitral_annulus=annulus,
        points=[(0.0, 0.0), (5.0, 5.0), (10.0, 0.0)],
    )
    assert contour.is_open_arc is True
    closed = contour.closed_polygon_points()
    assert closed[0] == (0.0, 0.0)
    assert closed[-1] == (10.0, 0.0)
    assert len(closed) >= 3

def test_contour_legacy_closed_polygon() -> None:
    contour = Contour(phase="ED", points=[(0, 0), (1, 0), (1, 1)])
    assert contour.is_open_arc is False
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `python -m pytest tests/unit/test_contour.py::test_contour_open_arc_helpers -v`

- [ ] **Step 3: Update `contour.py`**

```python
@dataclass
class Contour:
    phase: str
    view: str = "A4C"
    points: list[tuple[float, float]] = field(default_factory=list)
    source: str = "manual"
    mitral_annulus: tuple[tuple[float, float], tuple[float, float]] | None = None
    num_nodes: int = 32

    @property
    def is_open_arc(self) -> bool:
        return self.mitral_annulus is not None

    def closed_polygon_points(self) -> list[tuple[float, float]]:
        """Arc points; for open arc the MA chord closes the cavity base."""
        return list(self.points)
```

- [ ] **Step 4: Run tests — PASS**

Run: `python -m pytest tests/unit/test_contour.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/domain/models/contour.py tests/unit/test_contour.py
git commit -m "feat: extend Contour with mitral annulus open-arc model"
```

---

### Task 3: Simpson calculation with MA→apex long axis

**Files:**
- Modify: `src/echo_personal_tool/domain/calculations/lvef_simpson.py`
- Modify: `tests/unit/test_lvef_simpson.py`

- [ ] **Step 1: Write failing test for open arc**

```python
def open_arc_contour(
    *,
    phase: str,
    view: str,
    width_px: float,
    height_px: float,
) -> Contour:
    """Semicircle-like open arc on mitral line y=0."""
    import math
    n = 9
    annulus = ((0.0, 0.0), (width_px, 0.0))
    angles = [math.pi - i * math.pi / (n - 1) for i in range(n)]
    points = [
        (width_px / 2 + (width_px / 2) * math.cos(a), height_px * math.sin(a))
        for a in angles
    ]
    return Contour(phase=phase, view=view, mitral_annulus=annulus, points=points)


def test_calculate_open_arc_monoplan() -> None:
    contours = (
        open_arc_contour(phase="ed", view="A4C", width_px=100.0, height_px=50.0),
        open_arc_contour(phase="es", view="A4C", width_px=80.0, height_px=40.0),
    )
    result = calculate(contours, (0.5, 0.5))
    assert result is not None
    assert result.method == "simpson_monoplan"
    assert result.edv_ml == pytest.approx(49.087385, rel=0.05)
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Update `lvef_simpson.py`**

Key changes:
- Import `long_axis_endpoints` from `contour_geometry`
- `_contour_to_mm` passes through `mitral_annulus`
- `_simpson_volume_ml` accepts optional `mitral_annulus`
- If `mitral_annulus` set: axis from `long_axis_endpoints`, 20 disks along axis, width via `_find_width_perpendicular_to_axis`
- Else: legacy `_find_width_at_y` with min/max y

Add helper `_find_width_perpendicular_to_axis(polygon, axis_base, axis_tip, t)` where t in [0,1] along axis.

- [ ] **Step 4: Run all lvef tests — PASS** (keep legacy rectangle tests passing)

Run: `python -m pytest tests/unit/test_lvef_simpson.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/domain/calculations/lvef_simpson.py tests/unit/test_lvef_simpson.py
git commit -m "feat: Simpson volume uses MA-to-apex axis for open arcs"
```

---

### Task 4: ViewerWidget — staged open-arc drawing

**Files:**
- Modify: `src/echo_personal_tool/presentation/viewer_widget.py`
- Modify: `tests/unit/test_contour.py`

**UX workflow (hotkey `C`):**
1. Click 1: septal mitral annulus
2. Click 2: lateral mitral annulus (draw dashed MA chord)
3. Clicks 3+: interior arc points (minimum 1 = apex)
4. Enter or double-click: `resample_open_arc` → `Contour` with `mitral_annulus` + `num_nodes` points → emit

State machine: `_contour_stage: Literal["idle","ma_septal","ma_lateral","arc","editing"]`

Rendering:
- `_contour_xy`: if `is_open_arc`, use `sample_spline` for dense display; draw MA chord as second `PlotDataItem` (dashed)
- Do NOT close arc with duplicate first point in line data

- [ ] **Step 1: Update tests for staged workflow**

```python
def test_viewer_widget_open_arc_finish(qtbot) -> None:
    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    viewer.show_frame(np.zeros((64, 64), dtype=np.uint8))
    completed: list[Contour] = []
    viewer.contour_completed.connect(completed.append)
    viewer.start_contour()
    viewer.handle_contour_click((10.0, 40.0))  # septal
    viewer.handle_contour_click((50.0, 40.0))  # lateral
    viewer.handle_contour_click((30.0, 10.0))  # apex
    assert viewer.finish_contour()
    c = completed[0]
    assert c.is_open_arc
    assert c.mitral_annulus is not None
    assert len(c.points) == 32
```

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement staged drawing in viewer_widget.py**

- [ ] **Step 4: Run contour + spline tests — PASS**

Run: `python -m pytest tests/unit/test_contour.py tests/unit/test_spline_editor.py -v`

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: staged open-arc contour drawing in viewer"
```

---

### Task 5: Node drag with equal spacing resample

**Files:**
- Modify: `src/echo_personal_tool/presentation/viewer_widget.py`
- Modify: `tests/unit/test_spline_editor.py`

- [ ] **Step 1: Write failing test**

```python
def test_update_contour_point_resamples_open_arc(qtbot) -> None:
    from echo_personal_tool.domain.services.contour_geometry import DEFAULT_NODE_COUNT
    annulus = ((10.0, 40.0), (50.0, 40.0))
    arc = [(10.0, 40.0), (30.0, 10.0), (50.0, 40.0)]
    from echo_personal_tool.domain.services.contour_geometry import resample_open_arc
    contour = Contour(
        phase="ED",
        mitral_annulus=annulus,
        points=resample_open_arc(arc, num_nodes=DEFAULT_NODE_COUNT),
        num_nodes=DEFAULT_NODE_COUNT,
    )
    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    viewer.show_frame(np.zeros((64, 64), dtype=np.uint8))
    viewer.apply_contours([contour])
    mid = DEFAULT_NODE_COUNT // 2
    viewer._update_contour_point(0, mid, 30.0, 5.0)
    updated = viewer.contours()[0]
    assert len(updated.points) == DEFAULT_NODE_COUNT
    assert updated.points[mid][1] == pytest.approx(5.0, abs=1.0)
```

- [ ] **Step 2–4: Implement `_update_contour_point` to call `move_node_and_resample` when `is_open_arc`**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: equal arc-length resample on open-arc node drag"
```

---

### Task 6: AI segmentation → open arc conversion

**Files:**
- Modify: `src/echo_personal_tool/domain/services/segmentation_service.py`
- Modify: `tests/unit/test_segmentation_service.py`

Add `closed_polygon_to_open_arc(points, *, num_nodes=32)`:
- Find widest pair of points near bottom of polygon as mitral annulus (min y pair with max x separation, or extremal points on convex hull base)
- Split polygon into septal→apex→lateral arc
- Return `(mitral_annulus, resampled_arc_points)`

Wire in `AppController` auto-segment handler to set `mitral_annulus` on AI `Contour`.

- [ ] **Steps: TDD + commit**

```bash
git commit -m "feat: convert AI closed mask contour to open arc"
```

---

### Task 7: Full test suite + docs touch-up

- [ ] Run: `python -m pytest tests/unit -q`
- [ ] Run: `ruff check src tests`
- [ ] Update `simpsonCC.md` §1 note: open arc implemented
- [ ] Commit: `docs: note open-arc Simpson in simpsonCC`
