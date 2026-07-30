# Area Tool (Площадь) Advanced Modes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two drawing modes to the "Площадь" area measurement tool — click-polygon with edge snapping and freehand with edge snapping — switchable via a user preference.

**Architecture:** Extend the existing `UserPreferences` dataclass with an `area_tool_mode` field (`"click"` or `"freehand"`). Add a Douglas-Peucker point reduction utility for freehand input. Enable the existing `contour_edge_snap` infrastructure for closed polygons (currently restricted to open arcs). Branch the drawing logic in `ViewerWidget` based on the mode setting. Wire preferences through `MainWindow`.

**Tech Stack:** Python 3.12+, PySide6, numpy, scipy (ndimage already used), PyQtGraph, existing `contour_edge_snap.py` module.

## Global Constraints

- Python 3.12+, PySide6 >=6.6, numpy >=1.26 <2.0, scipy >=1.11
- QSettings persistence via `UserPreferences` dataclass (`infrastructure/user_preferences.py`)
- No new external dependencies
- All contour geometry uses `(col, row)` float tuples — not `(x, y)`
- Existing test framework: pytest, tests in `tests/unit/`
- i18n via `tr()` function from `infrastructure/i18n.py`
- Existing magnetic snap config: `EdgeSnapConfig` in `contour_edge_snap.py`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `infrastructure/user_preferences.py` | Modify | Add `area_tool_mode` field, load/save |
| `presentation/user_preferences_dialog.py` | Modify | Add QComboBox to Measurement tab |
| `domain/services/contour_edge_snap.py` | Modify | Add `snap_closed_polygon()` function |
| `domain/services/polygon_reduce.py` | **Create** | Douglas-Peucker point reduction |
| `presentation/viewer_widget.py` | Modify | Freehand recording, snap for closed polygons, mode branching |
| `presentation/main_window.py` | Modify | Wire `area_tool_mode` preference to viewer |
| `tests/unit/test_polygon_reduce.py` | **Create** | Tests for point reduction |
| `tests/unit/test_contour_edge_snap.py` | Modify | Tests for closed polygon snap |
| `tests/unit/test_user_preferences.py` | **Create** | Tests for new preference field |

---

### Task 1: Add `area_tool_mode` field to UserPreferences

**Files:**
- Modify: `src/echo_personal_tool/infrastructure/user_preferences.py` (`UserPreferences` dataclass and `load_user_preferences()`)
- Create: `tests/unit/test_user_preferences.py`

**Interfaces:**
- Consumes: existing `UserPreferences` dataclass, `_read_choice()` helper
- Produces: `UserPreferences.area_tool_mode: str` field (values: `"click"`, `"freehand"`)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_user_preferences.py`:

```python
"""Tests for UserPreferences area_tool_mode field."""

from __future__ import annotations

from echo_personal_tool.infrastructure.user_preferences import (
    UserPreferences,
    default_user_preferences,
)


class TestAreaToolMode:
    def test_default_is_click(self) -> None:
        prefs = default_user_preferences()
        assert prefs.area_tool_mode == "click"

    def test_click_valid(self) -> None:
        prefs = UserPreferences(area_tool_mode="click")
        assert prefs.area_tool_mode == "click"

    def test_freehand_valid(self) -> None:
        prefs = UserPreferences(area_tool_mode="freehand")
        assert prefs.area_tool_mode == "freehand"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_user_preferences.py -v`
Expected: FAIL with `AttributeError: 'UserPreferences' object has no attribute 'area_tool_mode'`

- [ ] **Step 3: Write minimal implementation**

In `src/echo_personal_tool/infrastructure/user_preferences.py`, add to `UserPreferences` dataclass after `length_display_unit: str = "mm"`:

```python
    area_tool_mode: str = "click"
```

In `load_user_preferences()` (search for `despeckle_enabled=_read_bool` in that function), add after it:

```python
area_tool_mode = (_read_choice(store.value("area_tool_mode"), "click", {"click", "freehand"}),)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_user_preferences.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/infrastructure/user_preferences.py tests/unit/test_user_preferences.py
git commit -m "feat: add area_tool_mode preference field (click/freehand)"
```

---

### Task 2: Add area tool mode selector to preferences dialog

**Files:**
- Modify: `src/echo_personal_tool/presentation/user_preferences_dialog.py` (Measurement tab setup and `_on_accept`)

**Interfaces:**
- Consumes: `UserPreferences.area_tool_mode` from Task 1
- Produces: `self._area_tool_mode_combo` QComboBox accessible in `_on_accept`

- [ ] **Step 1: Add combo box to Measurement tab**

In `user_preferences_dialog.py`, in the Measurement tab setup, after the `_length_unit` combo setup (search for `self._length_unit`), add:

```python
        self._area_tool_mode_combo = QComboBox()
        self._area_tool_mode_combo.addItem(tr("preferences.area_mode_click"), "click")
        self._area_tool_mode_combo.addItem(tr("preferences.area_mode_freehand"), "freehand")
        area_mode_index = self._area_tool_mode_combo.findData(current.area_tool_mode)
        self._area_tool_mode_combo.setCurrentIndex(max(area_mode_index, 0))
```

In the form layout section (search for `measure_form.addRow(tr("preferences.length_display_unit")`), add after it:

```python
        measure_form.addRow(tr("preferences.area_tool_mode"), self._area_tool_mode_combo)
```

- [ ] **Step 2: Wire into _on_accept**

In `_on_accept()` (search for `length_display_unit=str(self._length_unit.currentData())`), add after it:

```python
area_tool_mode = (str(self._area_tool_mode_combo.currentData()),)
```

- [ ] **Step 3: Add i18n keys**

In `src/echo_personal_tool/infrastructure/locales/ru.json`, add:

```json
"preferences.area_tool_mode": "Режим инструмента Площадь",
"preferences.area_mode_click": "Полигон (клики)",
"preferences.area_mode_freehand": "Свободное рисование"
```

In `src/echo_personal_tool/infrastructure/locales/en.json`, add:

```json
"preferences.area_tool_mode": "Area tool mode",
"preferences.area_mode_click": "Polygon (clicks)",
"preferences.area_mode_freehand": "Freehand drawing"
```

- [ ] **Step 4: Verify dialog builds**

Run: `python -c "from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog; print('OK')"`
Expected: OK (no import errors)

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/presentation/user_preferences_dialog.py src/echo_personal_tool/infrastructure/locales/ru.json src/echo_personal_tool/infrastructure/locales/en.json
git commit -m "feat: add area tool mode selector to preferences dialog"
```

---

### Task 3: Create Douglas-Peucker point reduction utility

**Files:**
- Create: `src/echo_personal_tool/domain/services/polygon_reduce.py`
- Create: `tests/unit/test_polygon_reduce.py`

**Interfaces:**
- Consumes: `list[tuple[float, float]]` (raw freehand points)
- Produces: `list[tuple[float, float]]` (reduced points, preserving shape)
- Later used by: `viewer_widget.py` freehand mode (Task 5)

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_polygon_reduce.py`:

```python
"""Tests for polygon_reduce (Douglas-Peucker point reduction)."""

from __future__ import annotations

from echo_personal_tool.domain.services.polygon_reduce import reduce_polygon_points


class TestReducePolygonPoints:
    def test_empty_list(self) -> None:
        assert reduce_polygon_points([]) == []

    def test_single_point(self) -> None:
        assert reduce_polygon_points([(1.0, 2.0)]) == [(1.0, 2.0)]

    def test_two_points(self) -> None:
        assert reduce_polygon_points([(0.0, 0.0), (10.0, 10.0)]) == [(0.0, 0.0), (10.0, 10.0)]

    def test_collinear_points_reduced(self) -> None:
        points = [(0.0, 0.0), (5.0, 5.0), (10.0, 10.0), (15.0, 15.0)]
        result = reduce_polygon_points(points, epsilon=1.0)
        assert len(result) < len(points)
        assert result[0] == (0.0, 0.0)
        assert result[-1] == (15.0, 15.0)

    def test_corner_preserved(self) -> None:
        points = [(0.0, 0.0), (5.0, 0.1), (10.0, 0.0), (10.0, 10.0)]
        result = reduce_polygon_points(points, epsilon=1.0)
        assert (10.0, 10.0) in result
        assert (0.0, 0.0) in result

    def test_closed_polygon_preserves_first_last(self) -> None:
        points = [(0.0, 0.0), (5.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
        result = reduce_polygon_points(points, epsilon=1.0, closed=True)
        assert result[0] == result[-1]

    def test_epsilon_zero_no_reduction(self) -> None:
        points = [(0.0, 0.0), (5.0, 5.0), (10.0, 0.0)]
        result = reduce_polygon_points(points, epsilon=0.0)
        assert len(result) == len(points)

    def test_large_epsilon_minimal_points(self) -> None:
        points = [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (3.0, 0.0), (10.0, 10.0)]
        result = reduce_polygon_points(points, epsilon=5.0)
        assert len(result) <= 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_polygon_reduce.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'echo_personal_tool.domain.services.polygon_reduce'`

- [ ] **Step 3: Write minimal implementation**

Create `src/echo_personal_tool/domain/services/polygon_reduce.py`:

```python
"""Douglas-Peucker polygon point reduction."""

from __future__ import annotations


def _perpendicular_distance(
    point: tuple[float, float],
    line_start: tuple[float, float],
    line_end: tuple[float, float],
) -> float:
    dx = line_end[0] - line_start[0]
    dy = line_end[1] - line_start[1]
    length_sq = dx * dx + dy * dy
    if length_sq < 1e-12:
        return ((point[0] - line_start[0]) ** 2 + (point[1] - line_start[1]) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((point[0] - line_start[0]) * dx + (point[1] - line_start[1]) * dy) / length_sq))
    proj_x = line_start[0] + t * dx
    proj_y = line_start[1] + t * dy
    return ((point[0] - proj_x) ** 2 + (point[1] - proj_y) ** 2) ** 0.5


def _douglas_peucker(
    points: list[tuple[float, float]],
    epsilon: float,
) -> list[tuple[float, float]]:
    if len(points) <= 2:
        return list(points)

    max_dist = 0.0
    max_index = 0
    for i in range(1, len(points) - 1):
        dist = _perpendicular_distance(points[i], points[0], points[-1])
        if dist > max_dist:
            max_dist = dist
            max_index = i

    if max_dist > epsilon:
        left = _douglas_peucker(points[: max_index + 1], epsilon)
        right = _douglas_peucker(points[max_index:], epsilon)
        return left[:-1] + right

    return [points[0], points[-1]]


def reduce_polygon_points(
    points: list[tuple[float, float]],
    *,
    epsilon: float = 2.0,
    closed: bool = False,
) -> list[tuple[float, float]]:
    """Reduce polygon points using Douglas-Peucker algorithm.

    Args:
        points: Raw polygon vertices.
        epsilon: Maximum perpendicular distance for point removal.
        closed: If True, ensure first and last points are identical.
    """
    if len(points) <= 2:
        return list(points)

    reduced = _douglas_peucker(points, epsilon)

    if closed and len(reduced) >= 2:
        if reduced[0] != reduced[-1]:
            reduced.append(reduced[0])

    return reduced
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_polygon_reduce.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/domain/services/polygon_reduce.py tests/unit/test_polygon_reduce.py
git commit -m "feat: add Douglas-Peucker polygon point reduction utility"
```

---

### Task 4: Enable edge snap for closed polygons

**Files:**
- Modify: `src/echo_personal_tool/domain/services/contour_edge_snap.py` (add new functions before private helpers)
- Modify: `tests/unit/test_contour_edge_snap.py`

**Interfaces:**
- Consumes: existing `EdgeMap`, `snap_magnetic_point()`, `outward_normal_at_index()`
- Produces: `snap_closed_polygon()` — snaps all points of a closed polygon to nearest edges
- Later used by: `viewer_widget.py` for both click and freehand modes (Task 5)

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_contour_edge_snap.py` (add to existing import block):

```python
from echo_personal_tool.domain.services.contour_edge_snap import (
    snap_closed_polygon,
    outward_normal_at_index_closed,
)


class TestSnapClosedPolygon:
    def test_returns_same_length(self) -> None:
        em = _make_edge_map()
        points = [(10.0, 10.0), (30.0, 10.0), (30.0, 30.0), (10.0, 30.0)]
        result = snap_closed_polygon(points, em)
        assert len(result) == len(points)

    def test_returns_tuples(self) -> None:
        em = _make_edge_map()
        points = [(10.0, 10.0), (30.0, 10.0), (30.0, 30.0)]
        result = snap_closed_polygon(points, em)
        for pt in result:
            assert isinstance(pt, tuple)
            assert len(pt) == 2

    def test_empty_points(self) -> None:
        em = _make_edge_map()
        assert snap_closed_polygon([], em) == []

    def test_too_few_points(self) -> None:
        em = _make_edge_map()
        points = [(10.0, 10.0), (20.0, 20.0)]
        assert snap_closed_polygon(points, em) == points

    def test_with_config(self) -> None:
        em = _make_edge_map()
        cfg = EdgeSnapConfig(search_radius_px=5.0, min_edge_strength=0.0)
        points = [(10.0, 10.0), (30.0, 10.0), (30.0, 30.0), (10.0, 30.0)]
        result = snap_closed_polygon(points, em, config=cfg)
        assert len(result) == len(points)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_contour_edge_snap.py::TestSnapClosedPolygon -v`
Expected: FAIL with `ImportError: cannot import name 'snap_closed_polygon'`

- [ ] **Step 3: Write minimal implementation**

Add a closed-polygon variant of `outward_normal_at_index` at the end of `src/echo_personal_tool/domain/services/contour_edge_snap.py` (before the private helper functions `_to_grayscale` etc.):

```python
def outward_normal_at_index_closed(
    points: Sequence[Sequence[float]],
    index: int,
) -> tuple[float, float]:
    """Unit outward normal for a closed polygon (wraps around at ends)."""
    n = len(points)
    previous = points[(index - 1) % n]
    current = points[index]
    following = points[(index + 1) % n]
    tangent_x = following[0] - previous[0]
    tangent_y = following[1] - previous[1]
    length = float(np.hypot(tangent_x, tangent_y))
    if length <= 1e-6:
        return (0.0, -1.0)
    tangent_x /= length
    tangent_y /= length
    normal_x = -tangent_y
    normal_y = tangent_x
    centroid_x = sum(float(point[0]) for point in points) / len(points)
    centroid_y = sum(float(point[1]) for point in points) / len(points)
    to_interior_x = centroid_x - current[0]
    to_interior_y = centroid_y - current[1]
    if normal_x * to_interior_x + normal_y * to_interior_y > 0.0:
        normal_x = -normal_x
        normal_y = -normal_y
    return (normal_x, normal_y)


def snap_closed_polygon(
    points: list[tuple[float, float]],
    edge_map: EdgeMap,
    *,
    config: EdgeSnapConfig | None = None,
) -> list[tuple[float, float]]:
    """Snap each vertex of a closed polygon toward the nearest edge.

    Uses outward normals directed away from the polygon centroid.
    Uses outward_normal_at_index_closed (modular indexing) to avoid
    IndexError on the last point.
    """
    if len(points) < 3:
        return list(points)

    cfg = config or EdgeSnapConfig(
        search_radius_px=10.0,
        inward_only=False,
        outward_only=True,
        intensity_fallback=True,
        min_edge_strength=0.0,
    )
    updated = list(points)
    for index in range(len(points)):
        normal = outward_normal_at_index_closed(points, index)
        snapped = snap_magnetic_point(
            edge_map,
            points[index][0],
            points[index][1],
            normal,
            cfg,
        )
        if snapped is not None:
            updated[index] = snapped
    return updated
```

Also add `outward_normal_at_index_closed` to the test imports in `tests/unit/test_contour_edge_snap.py` and add a test:

```python
class TestOutwardNormalAtIndexClosed:
    def test_wraps_at_end(self) -> None:
        points = [(0.0, 0.0), (50.0, 0.0), (50.0, 50.0), (0.0, 50.0)]
        nx, ny = outward_normal_at_index_closed(points, 3)
        length = np.hypot(nx, ny)
        assert length == pytest.approx(1.0, abs=0.01)

    def test_wraps_at_start(self) -> None:
        points = [(0.0, 0.0), (50.0, 0.0), (50.0, 50.0), (0.0, 50.0)]
        nx, ny = outward_normal_at_index_closed(points, 0)
        length = np.hypot(nx, ny)
        assert length == pytest.approx(1.0, abs=0.01)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_contour_edge_snap.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/domain/services/contour_edge_snap.py tests/unit/test_contour_edge_snap.py
git commit -m "feat: add snap_closed_polygon for closed polygon edge snapping"
```

---

### Task 5: Wire area_tool_mode into ViewerWidget

**Files:**
- Modify: `src/echo_personal_tool/presentation/viewer_widget.py` (state init, near `__init__` variables around line 700)
- Modify: `src/echo_personal_tool/presentation/viewer_widget.py` (`start_generic_area_contour` method)
- Modify: `src/echo_personal_tool/presentation/viewer_widget.py` (`_handle_contour_mouse_click` method)
- Modify: `src/echo_personal_tool/presentation/viewer_widget.py` (`GraphicsView.mouseReleaseEvent` method)
- Modify: `src/echo_personal_tool/presentation/viewer_widget.py` (`handle_contour_click` method — polygon branch)
- Modify: `src/echo_personal_tool/presentation/viewer_widget.py` (`_finish_closed_contour` method)
- Modify: `src/echo_personal_tool/presentation/viewer_widget.py` (`_clear_active_contour_drawing` method)
- Modify: `src/echo_personal_tool/presentation/viewer_widget.py` (`_on_scene_mouse_moved` method)

**Note:** Line numbers shift during edits. Always locate methods by their `def` signature, not by line number.

**Interfaces:**
- Consumes: `UserPreferences.area_tool_mode` (Task 1), `reduce_polygon_points` (Task 3), `snap_closed_polygon` (Task 4)
- Produces: mode-aware contour drawing in viewer

- [ ] **Step 1: Add freehand state variables**

In `viewer_widget.py`, in the `__init__` method, after the line `self._active_arc_points: list[tuple[float, float]] = []` (search for this exact line), add:

```python
        self._freehand_recording = False
        self._freehand_points: list[tuple[float, float]] = []
        self._area_tool_mode: str = "click"
```

- [ ] **Step 2: Add setter/getter for area_tool_mode**

After the `set_magnetic_snap_enabled` method (search for `def set_magnetic_snap_enabled`), add:

```python
def set_area_tool_mode(self, mode: str) -> None:
    if mode in ("click", "freehand"):
        self._area_tool_mode = mode


def area_tool_mode(self) -> str:
    return self._area_tool_mode
```

- [ ] **Step 3: Branch start_generic_area_contour on mode**

Replace `start_generic_area_contour` (search for `def start_generic_area_contour`) with:

```python
    def start_generic_area_contour(self) -> bool:
        """Closed polygon planimeter (Площадь1, Площадь2, …)."""
        if not self._start_contour_drawing(
            mode_kind="closed",
            pen=self._contour_pen_manual,
            phase="GEN",
            view="A4C",
            chamber=GENERIC_AREA_CHAMBER,
        ):
            return False
        if self._area_tool_mode == "freehand":
            self._freehand_recording = True
            self._freehand_points = []
            self._measurement_label.setText(tr("viewer.area_freehand_prompt"))
        else:
            self._measurement_label.setText(tr("viewer.area_contour_prompt"))
        return True
```

- [ ] **Step 4: Add freehand recording to _handle_contour_mouse_click**

Replace `_handle_contour_mouse_click` (referenced by method name in `viewer_widget.py`) with:

```python
    def _handle_contour_mouse_click(self, ev) -> bool:
        if not self._contour_mode_active:
            return False
        if ev.button() != Qt.MouseButton.LeftButton:
            return False

        ev.accept()
        if self._area_tool_mode == "freehand" and self._freehand_recording:
            if ev.double():
                self._finish_freehand_contour()
                return True
            return True  # single clicks ignored in freehand mode

        if ev.double():
            self.finish_contour()
            return True

        point = self._view.mapSceneToView(ev.scenePos())
        self.handle_contour_click((float(point.x()), float(point.y())))
        return True
```

Also add freehand finish-on-release in the GraphicsView `mouseReleaseEvent`. In the `GraphicsView.mouseReleaseEvent` method (referenced by class name in `viewer_widget.py`), add the freehand check **before all existing handlers**. The full method should be:

```python
    def mouseReleaseEvent(self, ev) -> None:  # type: ignore[override]
        if (
            self._viewer_widget is not None
            and self._viewer_widget._freehand_recording
            and self._viewer_widget._contour_mode_active
            and ev.button() == Qt.MouseButton.LeftButton
            and len(self._viewer_widget._freehand_points) >= 3
        ):
            self._viewer_widget._finish_freehand_contour()
            ev.accept()
            return
        if self._viewer_widget is not None and self._viewer_widget._handle_caliper_drag_release(ev):
            ev.accept()
            return
        if self._viewer_widget is not None and self._viewer_widget._handle_doppler_trace_release(ev):
            ev.accept()
            return
        if self._viewer_widget is not None and self._viewer_widget._handle_contour_drag_release(ev):
            ev.accept()
            return
        if self._viewer_widget is not None and self._viewer_widget._handle_contour_zone_release(ev):
            ev.accept()
            return
        super().mouseReleaseEvent(ev)
```

- [ ] **Step 5: Add freehand mouse tracking to _on_scene_mouse_moved**

In `_on_scene_mouse_moved` (search for `def _on_scene_mouse_moved`), insert the freehand block **after** the `if self._drag_session is not None:` block (which ends with `return`) and **before** the `if mapped is None:` check:

```python
        if self._freehand_recording and self._contour_mode_active:
            if mapped is not None:
                pt = (float(mapped.x()), float(mapped.y()))
                if not self._freehand_points or self._distance(self._freehand_points[-1], pt) > 2.0:
                    self._freehand_points.append(pt)
                    self._update_freehand_preview()
            return
```

- [ ] **Step 6: Add _distance and _update_freehand_preview helpers**

Add after `_handle_contour_mouse_click`:

```python
@staticmethod
def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _update_freehand_preview(self) -> None:
    if self._active_contour_item is None or not self._freehand_points:
        return
    xs = [p[0] for p in self._freehand_points]
    ys = [p[1] for p in self._freehand_points]
    self._active_contour_item.setData(xs, ys)
```

- [ ] **Step 7: Add _finish_freehand_contour method**

Add after `finish_contour` (search for `def finish_contour`):

```python
    def _finish_freehand_contour(self) -> bool:
        if len(self._freehand_points) < 3:
            self._clear_active_contour_drawing()
            return False

        from echo_personal_tool.domain.services.polygon_reduce import reduce_polygon_points
        from echo_personal_tool.domain.services.contour_edge_snap import (
            snap_closed_polygon,
        )

        reduced = reduce_polygon_points(self._freehand_points, epsilon=2.0, closed=False)

        if self._magnetic_snap_enabled:
            edge_map = self._get_edge_map()
            if edge_map is not None:
                reduced = snap_closed_polygon(reduced, edge_map)

        chamber = self._active_contour_chamber
        chamber_key = chamber.upper()
        measurement_label = None
        if chamber_key == GENERIC_AREA_CHAMBER:
            measurement_label = next_area_label(tuple(self._stored_contours))

        contour = Contour(
            phase=self._active_contour_phase or "GEN",
            view=self._active_contour_view,
            chamber=chamber,
            points=reduced,
            frame_index=self._contour_frame_index(),
            measurement_label=measurement_label,
        )
        self._freehand_recording = False
        self._freehand_points = []
        self._clear_active_contour_drawing()
        self.set_contour_from_domain(contour)
        self.contour_completed.emit(contour)
        return True
```

- [ ] **Step 8: Clean up freehand state in _clear_active_contour_drawing**

In `_clear_active_contour_drawing` (search for `def _clear_active_contour_drawing`), add after `self._active_arc_points = []`:

```python
        self._freehand_recording = False
        self._freehand_points = []
```

- [ ] **Step 9: Add snap to click-mode _finish_closed_contour**

Replace `_finish_closed_contour` (search for `def _finish_closed_contour`) with:

```python
    def _finish_closed_contour(self) -> bool:
        if len(self._active_arc_points) < 3:
            return False

        from echo_personal_tool.domain.services.contour_edge_snap import snap_closed_polygon

        points = list(self._active_arc_points)

        if self._magnetic_snap_enabled:
            edge_map = self._get_edge_map()
            if edge_map is not None:
                points = snap_closed_polygon(points, edge_map)

        chamber = self._active_contour_chamber
        chamber_key = chamber.upper()
        measurement_label = None
        if chamber_key == GENERIC_AREA_CHAMBER:
            measurement_label = next_area_label(tuple(self._stored_contours))
        elif chamber_key == GENERIC_VOLUME_CHAMBER:
            measurement_label = next_volume_label(tuple(self._stored_contours))

        contour = Contour(
            phase=self._active_contour_phase or "GEN",
            view=self._active_contour_view,
            chamber=chamber,
            points=points,
            frame_index=self._contour_frame_index(),
            measurement_label=measurement_label,
        )
        self._clear_active_contour_drawing()
        self.set_contour_from_domain(contour)
        self.contour_completed.emit(contour)
        return True
```

- [ ] **Step 10: Add snap per-click in handle_contour_click for polygon stage**

In `handle_contour_click` (search for `def handle_contour_click`), find the `elif self._contour_stage == "polygon":` branch and replace it with:

```python
        elif self._contour_stage == "polygon":
            self._active_arc_points.append(click)
            if self._magnetic_snap_enabled and len(self._active_arc_points) >= 5:
                edge_map = self._get_edge_map()
                if edge_map is not None:
                    from echo_personal_tool.domain.services.contour_edge_snap import (
                        snap_magnetic_point,
                        outward_normal_at_index_closed,
                    )
                    idx = len(self._active_arc_points) - 1
                    normal = outward_normal_at_index_closed(self._active_arc_points, idx)
                    snapped = snap_magnetic_point(
                        edge_map,
                        self._active_arc_points[idx][0],
                        self._active_arc_points[idx][1],
                        normal,
                    )
                    if snapped is not None:
                        self._active_arc_points[idx] = snapped
```

- [ ] **Step 11: Add i18n key for freehand prompt**

In `src/echo_personal_tool/infrastructure/locales/ru.json`, add:

```json
"viewer.area_freehand_prompt": "Площадь (свободное): ведите мышь, отпустите или двойной щелчок — завершить"
```

In `src/echo_personal_tool/infrastructure/locales/en.json`, add:

```json
"viewer.area_freehand_prompt": "Area (freehand): drag to draw, release or double-click to finish"
```

- [ ] **Step 12: Verify no import errors**

Run: `python -c "from echo_personal_tool.presentation.viewer_widget import ViewerWidget; print('OK')"`
Expected: OK

- [ ] **Step 13: Commit**

```bash
git add src/echo_personal_tool/presentation/viewer_widget.py src/echo_personal_tool/infrastructure/locales/ru.json src/echo_personal_tool/infrastructure/locales/en.json
git commit -m "feat: wire area_tool_mode into ViewerWidget (click+snap and freehand+snap)"
```

---

### Task 6: Wire preferences → viewer in MainWindow

**Files:**
- Modify: `src/echo_personal_tool/presentation/main_window.py` (method that applies preferences — search for `set_magnetic_snap_enabled`)

**Interfaces:**
- Consumes: `UserPreferences.area_tool_mode` (Task 1), `ViewerWidget.set_area_tool_mode()` (Task 5)
- Produces: preference applied to viewer on load and on change

**Note:** Line numbers shift during edits. Locate by method name.

- [ ] **Step 2: Apply on preferences reload**

In `main_window.py`, find the method that applies preferences (search for `_apply_preferences` or the method containing `self._viewer.set_magnetic_snap_enabled`). After the line `self._viewer.set_magnetic_snap_enabled(preferences.magnetic_snap_enabled)`, add:

```python
        self._viewer.set_area_tool_mode(preferences.area_tool_mode)
```

This ensures the mode is applied both on startup and when the user clicks "Apply" in the preferences dialog (the dialog calls this method via `on_apply` callback).

Note: No separate signal handler is needed — the combo box is only in the dialog (not a persistent tool panel widget). The value is saved by the dialog's `_on_accept()` and applied on the next `_apply_preferences()` call.

- [ ] **Step 3: Verify no import errors**

Run: `python -c "from echo_personal_tool.presentation.main_window import MainWindow; print('OK')"`
Expected: OK

- [ ] **Step 4: Commit**

```bash
git add src/echo_personal_tool/presentation/main_window.py
git commit -m "feat: wire area_tool_mode preference from MainWindow to ViewerWidget"
```

---

### Task 7: Remove is_open_arc guard from magnetic snap (cleanup)

**Files:**
- Modify: `src/echo_personal_tool/presentation/viewer_widget.py` (`_apply_magnetic_snap_to_contour` method)
- Modify: `src/echo_personal_tool/presentation/viewer_widget.py` (`_auto_snap_new_contour` method)

**Note:** Line numbers shift during edits. Locate methods by their `def` signature.

**Interfaces:**
- Consumes: `snap_closed_polygon` (Task 4)
- Produces: magnetic snap works for closed polygon contours (AREA, VOL) in addition to open arcs

- [ ] **Step 1: Update _apply_magnetic_snap_to_contour**

Replace the method (search for `def _apply_magnetic_snap_to_contour`) with:

```python
def _apply_magnetic_snap_to_contour(
    self,
    contour_index: int,
    weights: np.ndarray,
    *,
    grab_index: int | None = None,
) -> None:
    if not self._magnetic_snap_enabled:
        return
    edge_map = self._get_edge_map()
    if edge_map is None:
        return
    if contour_index < 0 or contour_index >= len(self._contours):
        return
    contour = self._contours[contour_index]
    if contour.is_open_arc:
        snap_cfg = magnetic_edge_snap_config_for_source(contour.source)
        pinned = self._pinned_indices_for_contour(contour)
        snapped = apply_soft_magnetic_snap(
            list(contour.points),
            weights,
            edge_map,
            strength=self._magnetic_snap_release_strength,
            max_radial_px=self._magnetic_snap_release_max_radial_px,
            weight_threshold=self._magnetic_snap_weight_threshold,
            config=snap_cfg,
            pinned_indices=pinned,
            grab_index=grab_index,
        )
        contour.points[:] = snapped
        self._snap_open_arc_endpoints(contour)
    else:
        from echo_personal_tool.domain.services.contour_edge_snap import snap_closed_polygon

        snapped = snap_closed_polygon(list(contour.points), edge_map)
        contour.points[:] = snapped
```

- [ ] **Step 2: Update _auto_snap_new_contour**

Replace the method (search for `def _auto_snap_new_contour`) with:

```python
    def _auto_snap_new_contour(self, contour: Contour) -> None:
        """Apply magnetic edge snap to a freshly placed contour."""
        if not self._magnetic_snap_enabled:
            return
        frame_index = self._contour_frame_index()
        instance_uid = self._current_instance_uid()
        for i, c in enumerate(self._contours):
            if (c is contour or (c.frame_index == frame_index and c.chamber == contour.chamber)) and (
                instance_uid is None or c.sop_instance_uid is None or c.sop_instance_uid == instance_uid
            ):
                self._apply_magnetic_snap_to_contour(
                    i,
                    np.ones(len(contour.points)),
                    grab_index=None,
                )
                self._refresh_rendered_contour_geometry(i)
                break
```

- [ ] **Step 3: Verify no import errors**

Run: `python -c "from echo_personal_tool.presentation.viewer_widget import ViewerWidget; print('OK')"`
Expected: OK

- [ ] **Step 4: Run existing tests**

Run: `pytest tests/unit/test_contour_edge_snap.py tests/unit/test_planimeter.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/presentation/viewer_widget.py
git commit -m "feat: enable magnetic snap for closed polygon contours (AREA/VOL)"
```

---

### Task 8: Integration smoke test

**Files:**
- Run: all existing tests
- Manual verification checklist

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/unit/ -v`
Expected: ALL PASS

- [ ] **Step 2: Run linter/typecheck**

Run: `ruff check src/ tests/` and `mypy src/echo_personal_tool/domain/services/polygon_reduce.py src/echo_personal_tool/domain/services/contour_edge_snap.py`
Expected: No errors

- [ ] **Step 3: Manual verification checklist**

Verify the following scenarios work:
1. Preferences dialog shows "Режим инструмента Площадь" combo with "Полигон (клики)" and "Свободное рисование"
2. Click mode: click-click-click polygon, each point snaps to nearest edge (after 5+ points), double-click to finish, area displayed
3. Freehand mode: hold and drag to draw, release mouse button or double-click to finish, points reduced and snapped, area displayed
4. Magnetic snap toggle off: both modes work without snapping
5. Existing open-arc contours (LV endo) still work with magnetic snap

- [ ] **Step 4: Final commit (if any fixes needed)**

```bash
git add -A
git commit -m "fix: integration fixes for area tool advanced modes"
```
