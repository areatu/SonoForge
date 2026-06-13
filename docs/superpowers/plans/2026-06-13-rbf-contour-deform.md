# RBF Contour Deformation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace index-based `drag_node_local` with Gaussian RBF cursor-weighted displacement for all contour types; visible nodes remain drag handles; MA endpoints pinned on open-arc; active nodes highlighted during drag.

**Architecture:** Pure-domain functions in `contour_geometry.py` (weights, displacement, σ from view range); `ViewerWidget` owns drag session state, calls domain on each mouse-move increment, highlights nodes with `w > 0.1`, resamples on release.

**Tech Stack:** Python 3.11+, NumPy, SciPy (`splprep`/`splev` unchanged), PySide6/PyQtGraph, pytest, pytest-qt.

**Spec:** [2026-06-13-rbf-contour-deform-design.md](../specs/2026-06-13-rbf-contour-deform-design.md)

---

## File map

| File | Responsibility |
|------|----------------|
| `src/echo_personal_tool/domain/services/contour_geometry.py` | RBF constants, `sigma_from_view_range`, `gaussian_weights`, `apply_gaussian_displacement`; remove `drag_node_local` |
| `src/echo_personal_tool/presentation/viewer_widget.py` | `_drag_session`, RBF drag/finalize, node highlight, σ from `_view` |
| `tests/unit/test_rbf_contour_deform.py` | Domain unit tests (new) |
| `tests/unit/test_contour_geometry.py` | Remove `drag_node_local` import/test |
| `tests/unit/test_spline_editor.py` | Viewer integration tests for open-arc + closed RBF drag |
| `CHANGELOG_SESSION.md` | One-line session entry after implementation |

---

### Task 1: RBF constants and `sigma_from_view_range`

**Files:**
- Create: `tests/unit/test_rbf_contour_deform.py`
- Modify: `src/echo_personal_tool/domain/services/contour_geometry.py` (after `DEFAULT_NODE_COUNT`)

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_rbf_contour_deform.py`:

```python
"""Unit tests for Gaussian RBF contour deformation."""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.services.contour_geometry import (
    SIGMA_SCREEN_PX,
    sigma_from_view_range,
)


def test_sigma_from_view_range_scales_with_view_range() -> None:
    narrow = sigma_from_view_range(100.0, 200.0, sigma_screen_px=40.0)
    wide = sigma_from_view_range(400.0, 200.0, sigma_screen_px=40.0)
    assert narrow == pytest.approx(20.0)
    assert wide == pytest.approx(80.0)
    assert wide == pytest.approx(4.0 * narrow)


def test_sigma_from_view_range_default_screen_constant() -> None:
    result = sigma_from_view_range(800.0, 400.0)
    assert result == pytest.approx(SIGMA_SCREEN_PX * 2.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_rbf_contour_deform.py::test_sigma_from_view_range_scales_with_view_range -v`

Expected: FAIL with `ImportError` or `cannot import name 'sigma_from_view_range'`

- [ ] **Step 3: Write minimal implementation**

In `contour_geometry.py`, after `DEFAULT_NODE_COUNT = 32`, add:

```python
SIGMA_SCREEN_PX = 40.0
SENSITIVITY_K = 1.5
WEIGHT_ACTIVE_THRESHOLD = 0.1
MIN_DELTA_NORM = 1e-3


def sigma_from_view_range(
    view_range_width: float,
    viewport_width_px: float,
    *,
    sigma_screen_px: float = SIGMA_SCREEN_PX,
) -> float:
    """Image-space Gaussian σ for a constant screen-brush radius."""
    viewport = max(float(viewport_width_px), 1.0)
    scale = float(view_range_width) / viewport
    return sigma_screen_px * scale
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_rbf_contour_deform.py -v`

Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_rbf_contour_deform.py src/echo_personal_tool/domain/services/contour_geometry.py
git commit -m "feat: add RBF sigma constants and view-range scaling"
```

---

### Task 2: `gaussian_weights`

**Files:**
- Modify: `tests/unit/test_rbf_contour_deform.py`
- Modify: `src/echo_personal_tool/domain/services/contour_geometry.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_rbf_contour_deform.py`:

```python
import numpy as np

from echo_personal_tool.domain.services.contour_geometry import gaussian_weights


def test_gaussian_weights_peak_at_cursor() -> None:
    points = [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)]
    weights = gaussian_weights(points, cursor=(10.0, 0.0), sigma=5.0)
    assert weights[1] == pytest.approx(1.0)
    assert weights[0] < weights[1]
    assert weights[2] < weights[1]


def test_gaussian_weights_decay_monotonic_on_line() -> None:
    points = [(0.0, 0.0), (5.0, 0.0), (10.0, 0.0), (15.0, 0.0)]
    weights = gaussian_weights(points, cursor=(5.0, 0.0), sigma=5.0)
    assert weights[1] == pytest.approx(1.0)
    assert weights[0] < weights[2] < weights[3]


def test_gaussian_weights_pinned_indices_zero() -> None:
    points = [(0.0, 0.0), (5.0, 5.0), (10.0, 0.0)]
    weights = gaussian_weights(
        points,
        cursor=(5.0, 5.0),
        sigma=5.0,
        pinned_indices=frozenset({0, 2}),
    )
    assert weights[0] == pytest.approx(0.0)
    assert weights[2] == pytest.approx(0.0)
    assert weights[1] == pytest.approx(1.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_rbf_contour_deform.py::test_gaussian_weights_peak_at_cursor -v`

Expected: FAIL with `ImportError: cannot import name 'gaussian_weights'`

- [ ] **Step 3: Write minimal implementation**

Add to `contour_geometry.py` (after `sigma_from_view_range`):

```python
def gaussian_weights(
    points: Sequence[tuple[float, float]],
    cursor: tuple[float, float],
    sigma: float,
    pinned_indices: frozenset[int] = frozenset(),
) -> np.ndarray:
    """Vectorized Gaussian RBF weights from control points to cursor."""
    if not points:
        return np.array([], dtype=np.float64)

    coords = np.asarray(points, dtype=np.float64)
    cursor_xy = np.asarray(cursor, dtype=np.float64)
    diff = coords - cursor_xy
    distances_sq = np.sum(diff * diff, axis=1)

    safe_sigma = max(float(sigma), 1e-6)
    weights = np.exp(-distances_sq / (2.0 * safe_sigma * safe_sigma))

    if pinned_indices:
        for index in pinned_indices:
            if 0 <= index < len(weights):
                weights[index] = 0.0
    return weights
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_rbf_contour_deform.py -v`

Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_rbf_contour_deform.py src/echo_personal_tool/domain/services/contour_geometry.py
git commit -m "feat: add vectorized gaussian_weights for contour RBF"
```

---

### Task 3: `apply_gaussian_displacement`

**Files:**
- Modify: `tests/unit/test_rbf_contour_deform.py`
- Modify: `src/echo_personal_tool/domain/services/contour_geometry.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_rbf_contour_deform.py`:

```python
from echo_personal_tool.domain.services.contour_geometry import (
    SENSITIVITY_K,
    apply_gaussian_displacement,
)


def test_apply_gaussian_displacement_moves_weighted_points() -> None:
    points = [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)]
    weights = np.array([0.0, 1.0, 0.5])
    moved = apply_gaussian_displacement(
        points,
        delta=(0.0, 2.0),
        weights=weights,
        sensitivity_k=1.0,
    )
    assert moved[0] == (0.0, 0.0)
    assert moved[1] == (10.0, 2.0)
    assert moved[2] == (20.0, 1.0)


def test_apply_gaussian_displacement_open_arc_endpoints_pinned() -> None:
    points = [(0.0, 0.0), (5.0, 5.0), (10.0, 0.0)]
    weights = gaussian_weights(
        points,
        cursor=(5.0, 5.0),
        sigma=5.0,
        pinned_indices=frozenset({0, 2}),
    )
    moved = apply_gaussian_displacement(
        points,
        delta=(1.0, 2.0),
        weights=weights,
        sensitivity_k=SENSITIVITY_K,
    )
    assert moved[0] == (0.0, 0.0)
    assert moved[2] == (10.0, 0.0)
    assert moved[1][1] > 5.0


def test_apply_gaussian_displacement_empty_points() -> None:
    assert apply_gaussian_displacement([], delta=(1.0, 1.0), weights=np.array([])) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_rbf_contour_deform.py::test_apply_gaussian_displacement_moves_weighted_points -v`

Expected: FAIL with `ImportError`

- [ ] **Step 3: Write minimal implementation**

Add to `contour_geometry.py`:

```python
def apply_gaussian_displacement(
    points: Sequence[tuple[float, float]],
    delta: tuple[float, float],
    weights: np.ndarray,
    *,
    sensitivity_k: float = SENSITIVITY_K,
) -> list[tuple[float, float]]:
    """Apply incremental cursor delta with per-point Gaussian weights."""
    if not points:
        return []

    coords = np.asarray(points, dtype=np.float64)
    delta_xy = np.asarray(delta, dtype=np.float64) * float(sensitivity_k)
    shifted = coords + weights[:, np.newaxis] * delta_xy
    return [(float(x), float(y)) for x, y in shifted]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_rbf_contour_deform.py -v`

Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_rbf_contour_deform.py src/echo_personal_tool/domain/services/contour_geometry.py
git commit -m "feat: add apply_gaussian_displacement for RBF contour drag"
```

---

### Task 4: Remove `drag_node_local`

**Files:**
- Modify: `src/echo_personal_tool/domain/services/contour_geometry.py`
- Modify: `tests/unit/test_contour_geometry.py`

- [ ] **Step 1: Delete obsolete test**

In `tests/unit/test_contour_geometry.py`:
- Remove `drag_node_local` from imports
- Delete entire `test_drag_node_local_moves_primary_node_most` function

- [ ] **Step 2: Remove `drag_node_local` from domain**

Delete lines 61–92 (`drag_node_local` function) from `contour_geometry.py`.

- [ ] **Step 3: Run tests to verify nothing else breaks**

Run: `uv run pytest tests/unit/test_contour_geometry.py tests/unit/test_rbf_contour_deform.py -v`

Expected: PASS (7 + 8 tests)

- [ ] **Step 4: Commit**

```bash
git add src/echo_personal_tool/domain/services/contour_geometry.py tests/unit/test_contour_geometry.py
git commit -m "refactor: remove drag_node_local superseded by RBF displacement"
```

---

### Task 5: Node highlight API on `_ContourNodeItem`

**Files:**
- Modify: `src/echo_personal_tool/presentation/viewer_widget.py`

- [ ] **Step 1: Add highlight method and store base pen**

In `_ContourNodeItem.__init__`, after `self._point_index = point_index`, add:

```python
        self._base_pen = pen
```

Add method to `_ContourNodeItem` class (before `mouseDragEvent`):

```python
    def set_rbf_highlight(self, *, active: bool) -> None:
        if active:
            highlight = pg.mkPen("#4caf50", width=2)
            self.setPen(highlight)
            self.setBrush(pg.mkBrush("#4caf50"))
            self.setSize(12)
        else:
            self.setPen(self._base_pen)
            self.setBrush(pg.mkBrush(self._base_pen.color()))
            self.setSize(10)
```

- [ ] **Step 2: Manual smoke check (optional)**

No automated test yet; syntax check only.

Run: `uv run python -c "from echo_personal_tool.presentation.viewer_widget import ViewerWidget"`

Expected: no ImportError

- [ ] **Step 3: Commit**

```bash
git add src/echo_personal_tool/presentation/viewer_widget.py
git commit -m "feat: add RBF active-node highlight styling on contour nodes"
```

---

### Task 6: Viewer RBF drag session and `_drag_contour_point`

**Files:**
- Modify: `src/echo_personal_tool/presentation/viewer_widget.py`

- [ ] **Step 1: Update imports**

Replace `drag_node_local` import with:

```python
from echo_personal_tool.domain.services.contour_geometry import (
    DEFAULT_NODE_COUNT,
    MIN_DELTA_NORM,
    WEIGHT_ACTIVE_THRESHOLD,
    apply_gaussian_displacement,
    gaussian_weights,
    resample_open_arc,
    sample_spline,
    sigma_from_view_range,
)
```

- [ ] **Step 2: Add session state in `__init__`**

After `self._syncing_state = False`, add:

```python
        self._drag_session: tuple[int, float, float] | None = None
```

- [ ] **Step 3: Add helper methods on `ViewerWidget`**

Add before `_drag_contour_point`:

```python
    def _sigma_for_contour_drag(self) -> float:
        x_range, _y_range = self._view.viewRange()
        return sigma_from_view_range(x_range[1] - x_range[0], self._view.width())

    def _pinned_indices_for_contour(self, contour: Contour) -> frozenset[int]:
        if contour.is_open_arc and len(contour.points) >= 2:
            return frozenset({0, len(contour.points) - 1})
        return frozenset()

    def _snap_open_arc_endpoints(self, contour: Contour) -> None:
        if not contour.is_open_arc or contour.mitral_annulus is None:
            return
        septal, lateral = contour.mitral_annulus
        contour.points[0] = septal
        contour.points[-1] = lateral

    def _update_contour_node_highlights(
        self,
        contour_index: int,
        weights: np.ndarray,
    ) -> None:
        if contour_index < 0 or contour_index >= len(self._contour_nodes):
            return
        for idx, node in enumerate(self._contour_nodes[contour_index]):
            active = idx < len(weights) and weights[idx] > WEIGHT_ACTIVE_THRESHOLD
            node.set_rbf_highlight(active=active)

    def _clear_contour_node_highlights(self, contour_index: int) -> None:
        if contour_index < 0 or contour_index >= len(self._contour_nodes):
            return
        for node in self._contour_nodes[contour_index]:
            node.set_rbf_highlight(active=False)

    def _clear_drag_session(self) -> None:
        self._drag_session = None

    def _apply_rbf_drag_step(
        self,
        contour_index: int,
        x: float,
        y: float,
        *,
        force: bool = False,
    ) -> bool:
        """Return True if displacement was applied."""
        if contour_index < 0 or contour_index >= len(self._contours):
            return False
        contour = self._contours[contour_index]

        if self._drag_session is None or self._drag_session[0] != contour_index:
            self._drag_session = (contour_index, x, y)
            return False

        last_x, last_y = self._drag_session[1], self._drag_session[2]
        delta = (x - last_x, y - last_y)
        if not force and math.hypot(delta[0], delta[1]) < MIN_DELTA_NORM:
            return False

        sigma = self._sigma_for_contour_drag()
        cursor = (x, y)
        pinned = self._pinned_indices_for_contour(contour)
        weights = gaussian_weights(contour.points, cursor, sigma, pinned_indices=pinned)
        updated = apply_gaussian_displacement(contour.points, delta, weights)
        contour.points[:] = updated
        self._snap_open_arc_endpoints(contour)

        for idx, point in enumerate(contour.points):
            self._contour_nodes[contour_index][idx].setData([point[0]], [point[1]])
        self._update_contour_node_highlights(contour_index, weights)
        self._refresh_rendered_contour_geometry(contour_index)
        self._drag_session = (contour_index, x, y)
        return True
```

Add `import math` at top of `viewer_widget.py` if not already present.

- [ ] **Step 4: Replace `_drag_contour_point` body**

Replace entire `_drag_contour_point` method with:

```python
    def _drag_contour_point(
        self,
        contour_index: int,
        point_index: int,
        x: float,
        y: float,
    ) -> None:
        if contour_index < 0 or contour_index >= len(self._contours):
            return
        contour = self._contours[contour_index]
        if point_index < 0 or point_index >= len(contour.points):
            return
        self._apply_rbf_drag_step(contour_index, x, y)
```

- [ ] **Step 5: Run existing viewer tests**

Run: `uv run pytest tests/unit/test_spline_editor.py -v`

Expected: Some tests may fail until Task 7 finalize changes; note failures for next task.

- [ ] **Step 6: Commit**

```bash
git add src/echo_personal_tool/presentation/viewer_widget.py
git commit -m "feat: wire RBF drag session and displacement in ViewerWidget"
```

---

### Task 7: Finalize drag, session cleanup, contour delete safety

**Files:**
- Modify: `src/echo_personal_tool/presentation/viewer_widget.py`
- Modify: `tests/unit/test_spline_editor.py`

- [ ] **Step 1: Write failing integration test for open-arc RBF**

Append to `tests/unit/test_spline_editor.py`:

```python
from echo_personal_tool.domain.services.contour_geometry import DEFAULT_NODE_COUNT, resample_open_arc


def test_open_arc_rbf_drag_moves_neighbors_not_ma(qtbot) -> None:
    annulus = ((10.0, 40.0), (50.0, 40.0))
    arc = [(10.0, 40.0), (30.0, 10.0), (50.0, 40.0)]
    contour = Contour(
        phase="ED",
        mitral_annulus=annulus,
        points=resample_open_arc(arc, num_nodes=DEFAULT_NODE_COUNT),
        num_nodes=DEFAULT_NODE_COUNT,
        source="manual",
    )
    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    viewer.show_frame(np.zeros((64, 64), dtype=np.uint8))
    viewer.apply_contours([contour])

    mid = DEFAULT_NODE_COUNT // 2
    y_before = contour.points[mid][1]
    y_neighbor = contour.points[mid + 1][1]

    viewer._drag_contour_point(0, mid, 30.0, 8.0)  # init session
    viewer._drag_contour_point(0, mid, 30.0, 5.0)  # apply delta dy=-3

    assert contour.points[0] == annulus[0]
    assert contour.points[-1] == annulus[1]
    assert contour.points[mid][1] < y_before
    assert contour.points[mid + 1][1] < y_neighbor


def test_closed_contour_rbf_drag_moves_multiple_points(qtbot) -> None:
    contour = Contour(
        phase="ED",
        points=[(2.0, 2.0), (8.0, 2.0), (8.0, 7.0), (2.0, 7.0)],
        source="manual",
    )
    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    viewer.show_frame(np.zeros((32, 32), dtype=np.uint8))
    viewer.apply_contours([contour])

    x1_before = contour.points[1][0]
    x2_before = contour.points[2][0]

    viewer._drag_contour_point(0, 1, 8.0, 2.0)  # init
    viewer._drag_contour_point(0, 1, 10.0, 2.0)  # dx=+2

    assert contour.points[1][0] > x1_before
    assert contour.points[2][0] > x2_before
```

- [ ] **Step 2: Run test to verify open-arc test passes (closed may pass too)**

Run: `uv run pytest tests/unit/test_spline_editor.py::test_open_arc_rbf_drag_moves_neighbors_not_ma -v`

Expected: PASS after Task 6; if FAIL, complete Task 6 first.

- [ ] **Step 3: Update `_finalize_contour_point_drag`**

Replace `_finalize_contour_point_drag` with:

```python
    def _finalize_contour_point_drag(
        self,
        contour_index: int,
        point_index: int,
        x: float,
        y: float,
    ) -> None:
        if contour_index < 0 or contour_index >= len(self._contours):
            self._clear_drag_session()
            return
        self._apply_rbf_drag_step(contour_index, x, y, force=True)
        contour = self._contours[contour_index]
        if contour.is_open_arc:
            num_nodes = contour.num_nodes or DEFAULT_NODE_COUNT
            resampled = resample_open_arc(contour.points, num_nodes=num_nodes)
            contour.points[:] = resampled
            if contour.mitral_annulus is not None:
                contour.mitral_annulus = (resampled[0], resampled[-1])
            for idx, point in enumerate(resampled):
                self._contour_nodes[contour_index][idx].setData([point[0]], [point[1]])
            self._refresh_rendered_contour_geometry(contour_index)
        self._clear_contour_node_highlights(contour_index)
        self._clear_drag_session()
        self._upsert_stored_contour(contour)
        self.contours_changed.emit(self.contours())
        current_frame = self._contour_frame_index()
        if (
            contour.chamber.upper() == "LV"
            and contour.frame_index == current_frame
        ):
            self._refresh_lv_frame_overlay()
```

- [ ] **Step 4: Clear session on contour removal**

In `_remove_rendered_contour`, at the start of the method add:

```python
        if self._drag_session is not None and self._drag_session[0] == contour_index:
            self._clear_drag_session()
        elif self._drag_session is not None and self._drag_session[0] > contour_index:
            idx, lx, ly = self._drag_session
            self._drag_session = (idx - 1, lx, ly)
```

- [ ] **Step 5: Run integration tests**

Run: `uv run pytest tests/unit/test_spline_editor.py -v`

Expected: PASS (all tests in file)

- [ ] **Step 6: Commit**

```bash
git add src/echo_personal_tool/presentation/viewer_widget.py tests/unit/test_spline_editor.py
git commit -m "feat: finalize RBF drag with resample, highlights reset, integration tests"
```

---

### Task 8: Spec status, changelog, full verification

**Files:**
- Modify: `docs/superpowers/specs/2026-06-13-rbf-contour-deform-design.md`
- Modify: `CHANGELOG_SESSION.md`

- [ ] **Step 1: Mark spec approved**

In spec front matter, change:

```markdown
**Status:** Approved
```

- [ ] **Step 2: Add changelog entry**

Append to `CHANGELOG_SESSION.md`:

```markdown
## [2026-06-13] RBF Gaussian contour drag (QLAB-style)
- **Тип:** feature
- **Файлы:** `contour_geometry.py`, `viewer_widget.py`, `tests/unit/test_rbf_contour_deform.py`, `tests/unit/test_spline_editor.py`, `tests/unit/test_contour_geometry.py`
- **Суть:** Drag узлов контура через Gaussian RBF от курсора; MA-концы pinned; σ от zoom viewRange; подсветка активных узлов; заменён drag_node_local.
```

- [ ] **Step 3: Full verification**

Run:

```bash
uv run pytest tests/unit/test_rbf_contour_deform.py tests/unit/test_contour_geometry.py tests/unit/test_spline_editor.py -v
uv run pytest tests/unit -q
uv run ruff check src tests
```

Expected: all tests PASS; ruff clean.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-06-13-rbf-contour-deform-design.md CHANGELOG_SESSION.md
git commit -m "docs: approve RBF contour deform spec and changelog"
```

---

## Spec coverage checklist (self-review)

| Spec requirement | Task |
|------------------|------|
| Gaussian RBF weights | Task 2 |
| Incremental cursor delta | Task 6 `_apply_rbf_drag_step` |
| MA pinned w=0 | Task 2 + Task 6 `_pinned_indices_for_contour` |
| σ zoom-adaptive | Task 1 + Task 6 `_sigma_for_contour_drag` |
| All contours (open + closed) | Task 6 (unified path) |
| Node highlight w>0.1 | Task 5 + Task 6 |
| Remove drag_node_local | Task 4 |
| Session on first move | Task 6 |
| Resample on release (open-arc) | Task 7 |
| contours_changed on release only | Task 7 |
| Contour delete clears session | Task 7 |
| Domain vectorized numpy | Tasks 2–3 |
| Integration tests | Task 7 |

No placeholders. All function names consistent across tasks.

---

**Plan complete and saved to `docs/superpowers/plans/2026-06-13-rbf-contour-deform.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
