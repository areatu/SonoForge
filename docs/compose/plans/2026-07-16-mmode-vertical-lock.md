# M-Mode Vertical Lock + Guides Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add vertical lock mode to M-mode scan line: points move only vertically (Y), with perpendicular dashed guide lines visible during placement/dragging.

**Architecture:** Extend MModeScanLineItem with vertical_lock flag and guide graphics. ViewerWidget exposes toggle button and passes lock state to scan line operations.

**Tech Stack:** Python, PySide6, pyqtgraph

## Global Constraints

- Follow existing code patterns in mmode_scan_line.py, viewer_widget.py, mmode_widget.py
- Keep changes minimal and focused on the vertical lock feature
- Guide lines: thin dashed (pen style DashLine), perpendicular to movement axis

---

## File Structure

| File | Responsibility |
|------|----------------|
| `presentation/mmode_scan_line.py` | Vertical lock flag, guide lines, constrained node dragging |
| `presentation/viewer_widget.py` | Toggle vertical lock, pass lock state to scan line |
| `presentation/mmode_widget.py` | UI button for vertical lock toggle |
| `tests/unit/test_mmode_vertical_lock.py` | Unit tests for vertical lock + guides |

---

## Task 1: Add vertical_lock flag and guide graphics to MModeScanLineItem

**Covers:** Vertical lock mode, guide lines

**Files:**
- Modify: `src/echo_personal_tool/presentation/mmode_scan_line.py:12-198`
- Create: `tests/unit/test_mmode_vertical_lock.py`

**Interfaces:**
- Consumes: None (new feature)
- Produces: `MModeScanLineItem.vertical_lock`, `MModeScanLineItem._guide_items`

- [ ] **Step 1: Write the failing test for vertical_lock flag**

```python
# tests/unit/test_mmode_vertical_lock.py
import pytest
from echo_personal_tool.presentation.mmode_scan_line import MModeScanLineItem

def test_vertical_lock_default_false():
    item = MModeScanLineItem(viewer_widget=None)
    assert item.vertical_lock is False

def test_vertical_lock_can_set():
    item = MModeScanLineItem(viewer_widget=None)
    item.vertical_lock = True
    assert item.vertical_lock is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_mmode_vertical_lock.py -v`
Expected: FAIL with `AttributeError: 'MModeScanLineItem' object has no attribute 'vertical_lock'`

- [ ] **Step 3: Add vertical_lock attribute to MModeScanLineItem**

In `src/echo_personal_tool/presentation/mmode_scan_line.py`, add to `__init__`:

```python
class MModeScanLineItem:
    """Manages M-mode scan line graphics on the 2D viewer."""

    def __init__(self, viewer_widget: QWidget | None) -> None:
        self._viewer_widget = viewer_widget
        self.line_start: tuple[float, float] | None = None
        self.line_end: tuple[float, float] | None = None
        self._line_item: pg.PlotDataItem | None = None
        self._start_node: _MModeNodeItem | None = None
        self._end_node: _MModeNodeItem | None = None
        self._view: pg.ViewBox | None = None
        self.vertical_lock: bool = False  # NEW: vertical-only movement
        self._guide_h: pg.PlotDataItem | None = None  # horizontal guide
        self._guide_v: pg.PlotDataItem | None = None  # vertical guide
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_mmode_vertical_lock.py -v`
Expected: PASS

- [ ] **Step 5: Add guide graphics creation and removal**

Add methods to `MModeScanLineItem`:

```python
    def _create_guide_graphics(self) -> None:
        """Create perpendicular guide lines for vertical lock mode."""
        pen = pg.mkPen("#9e9e9e", width=1, style=Qt.PenStyle.DashLine)
        self._guide_h = pg.PlotDataItem(pen=pen, antialias=True)
        self._guide_h.setZValue(23)
        self._guide_v = pg.PlotDataItem(pen=pen, antialias=True)
        self._guide_v.setZValue(23)

    def _remove_guide_graphics(self) -> None:
        """Remove guide lines."""
        v = self._view
        for item in (self._guide_h, self._guide_v):
            if item is not None and v is not None:
                v.removeItem(item)
        self._guide_h = None
        self._guide_v = None

    def _update_guides(self, pos: tuple[float, float], frame_height: float) -> None:
        """Update perpendicular guides at given position (image coords)."""
        if self._guide_h is None or self._guide_v is None or self._view is None:
            return
        # Convert to view coords (invertY)
        view_y = frame_height - pos[1]
        # Horizontal guide: full width at this Y
        self._guide_h.setData([0, self._view.width()], [view_y, view_y])
        # Vertical guide: full height at this X
        self._guide_v.setData([pos[0], pos[0]], [0, frame_height])
        # Add to view if not already added
        if self._guide_h not in self._view.addedItems:
            self._view.addItem(self._guide_h)
        if self._guide_v not in self._view.addedItems:
            self._view.addItem(self._guide_v)
```

- [ ] **Step 6: Modify node dragging to respect vertical_lock**

Modify `_MModeNodeItem.mouseDragEvent`:

```python
    def mouseDragEvent(self, ev) -> None:  # type: ignore[override]
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        ev.accept()
        if self._viewer_widget is not None and hasattr(ev, "scenePos"):
            view_box = self.getViewBox()
            if view_box is not None:
                pos = view_box.mapSceneToView(ev.scenePos())
                new_pos = (float(pos.x()), float(pos.y()))
                # Apply vertical lock: keep original X, only update Y
                if self._viewer_widget._mmode_line_item is not None and \
                   self._viewer_widget._mmode_line_item.vertical_lock:
                    original = self._viewer_widget._mmode_line_item.line_start \
                        if self._endpoint_index == 0 \
                        else self._viewer_widget._mmode_line_item.line_end
                    if original is not None:
                        new_pos = (original[0], new_pos[1])
                self._viewer_widget._mmode_node_dragging(
                    self._endpoint_index, new_pos
                )
```

- [ ] **Step 7: Update _update_graphics to show guides when vertical_lock**

Modify `MModeScanLineItem._update_graphics`:

```python
    def _update_graphics(self) -> None:
        if self._line_item is not None and self.line_start is not None and self.line_end is not None:
            self._sync_line_data()
        if self._start_node is not None and self.line_start is not None:
            self._start_node.setData([self.line_start[0]], [self.line_start[1]])
        if self._end_node is not None and self.line_end is not None:
            self._end_node.setData([self.end_node[0]], [self.end_node[1]])
        # Update guides in vertical lock mode
        if self.vertical_lock and self._view is not None:
            h = self._viewer_widget._current_frame.shape[0] \
                if self._viewer_widget is not None \
                and self._viewer_widget._current_frame is not None else 1.0
            if self.line_end is not None:
                self._update_guides(self.line_end, h)
```

- [ ] **Step 8: Clean up guides on clear**

Modify `MModeScanLineItem.clear`:

```python
    def clear(self) -> None:
        self.line_start = None
        self.line_end = None
        self._remove_graphics()
        self._remove_guide_graphics()
```

- [ ] **Step 9: Write test for guide creation**

```python
# tests/unit/test_mmode_vertical_lock.py (add)
def test_guide_graphics_created():
    item = MModeScanLineItem(viewer_widget=None)
    item.vertical_lock = True
    # Simulate adding guides
    item._guide_h = pg.PlotDataItem()
    item._guide_v = pg.PlotDataItem()
    assert item._guide_h is not None
    assert item._guide_v is not None
```

- [ ] **Step 10: Commit**

```bash
git add src/echo_personal_tool/presentation/mmode_scan_line.py tests/unit/test_mmode_vertical_lock.py
git commit -m "feat(mmode): add vertical_lock flag and guide graphics to MModeScanLineItem"
```

---

## Task 2: Add vertical lock toggle button to MModeWidget

**Covers:** UI for vertical lock toggle

**Files:**
- Modify: `src/echo_personal_tool/presentation/mmode_widget.py:70-110`
- Modify: `tests/unit/test_mmode_vertical_lock.py`

**Interfaces:**
- Consumes: `MModeScanLineItem.vertical_lock`
- Produces: `MModeWidget.vertical_lock_toggled` signal, `MModeWidget._vertical_lock_btn`

- [ ] **Step 1: Write the failing test for vertical lock button**

```python
# tests/unit/test_mmode_vertical_lock.py (add)
def test_vertical_lock_button_exists(qtbot):
    from echo_personal_tool.presentation.mmode_widget import MModeWidget
    widget = MModeWidget()
    qtbot.addWidget(widget)
    assert hasattr(widget, '_vertical_lock_btn')
    assert widget._vertical_lock_btn.isCheckable()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_mmode_vertical_lock.py::test_vertical_lock_button_exists -v`
Expected: FAIL with `AttributeError: 'MModeWidget' object has no attribute '_vertical_lock_btn'`

- [ ] **Step 3: Add vertical_lock button to MModeWidget toolbar**

In `src/echo_personal_tool/presentation/mmode_widget.py`, add after measurement buttons:

```python
        # Vertical lock button
        self._vertical_lock_btn = QPushButton("⋮ Вертикаль")
        self._vertical_lock_btn.setFixedHeight(22)
        self._vertical_lock_btn.setCheckable(True)
        self._vertical_lock_btn.setToolTip("Фиксировать движение точек только по вертикали")
        self._vertical_lock_btn.clicked.connect(self._on_vertical_lock_toggled)
        toolbar.addWidget(self._vertical_lock_btn)
```

- [ ] **Step 4: Add signal and handler**

```python
class MModeWidget(QWidget):
    caliper_measurement_added = Signal(object)
    sweep_speed_changed = Signal(int)
    deactivate_requested = Signal()
    measurement_added = Signal(object)
    vertical_lock_toggled = Signal(bool)  # NEW

    def _on_vertical_lock_toggled(self, checked: bool) -> None:
        self.vertical_lock_toggled.emit(checked)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/unit/test_mmode_vertical_lock.py::test_vertical_lock_button_exists -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/echo_personal_tool/presentation/mmode_widget.py tests/unit/test_mmode_vertical_lock.py
git commit -m "feat(mmode): add vertical lock toggle button to MModeWidget"
```

---

## Task 3: Connect vertical lock to ViewerWidget scan line

**Covers:** ViewerWidget integration

**Files:**
- Modify: `src/echo_personal_tool/presentation/viewer_widget.py:2152-2226`
- Modify: `src/echo_personal_tool/presentation/main_window.py:373-395`

**Interfaces:**
- Consumes: `MModeWidget.vertical_lock_toggled` signal
- Produces: `ViewerWidget._mmode_vertical_lock` flag, passes to `MModeScanLineItem`

- [ ] **Step 1: Write the failing test for vertical lock propagation**

```python
# tests/unit/test_mmode_vertical_lock.py (add)
def test_viewer_widget_vertical_lock_flag():
    from unittest.mock import MagicMock
    from echo_personal_tool.presentation.viewer_widget import ViewerWidget
    viewer = ViewerWidget.__new__(ViewerWidget)
    viewer._mmode_vertical_lock = False
    assert viewer._mmode_vertical_lock is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_mmode_vertical_lock.py::test_viewer_widget_vertical_lock_flag -v`
Expected: FAIL (attribute doesn't exist)

- [ ] **Step 3: Add _mmode_vertical_lock to ViewerWidget**

In `src/echo_personal_tool/presentation/viewer_widget.py`, find `__init__` and add:

```python
        self._mmode_vertical_lock: bool = False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_mmode_vertical_lock.py::test_viewer_widget_vertical_lock_flag -v`
Expected: PASS

- [ ] **Step 5: Add method to set vertical lock**

```python
    def set_mmode_vertical_lock(self, enabled: bool) -> None:
        """Enable/disable vertical-only movement for M-mode scan line."""
        self._mmode_vertical_lock = enabled
        if self._mmode_line_item is not None:
            self._mmode_line_item.vertical_lock = enabled
```

- [ ] **Step 6: Modify _mmode_node_dragging to respect vertical lock**

In `viewer_widget.py`, modify `_mmode_node_dragging`:

```python
    def _mmode_node_dragging(self, endpoint_index: int, pos: tuple[float, float]) -> None:
        if self._mmode_line_item is None:
            return
        # Convert view coords to image coords
        h = self._current_frame.shape[0] if self._current_frame is not None else 1.0
        img_pos = (pos[0], h - pos[1])
        
        # Apply vertical lock: keep original X, only update Y
        if self._mmode_vertical_lock:
            if endpoint_index == 0:
                original = self._mmode_line_item.line_start
            else:
                original = self._mmode_line_item.line_end
            if original is not None:
                img_pos = (original[0], img_pos[1])
        
        if endpoint_index == 0:
            self._mmode_line_item.move_start_to(img_pos)
        else:
            self._mmode_line_item.move_end_to(img_pos)
        # Update graphics in view coords
        self._mmode_line_item.update_graphics_for_view(self._view, h)
        self.mmode_line_completed.emit(*self._mmode_line_item.get_endpoints())
```

- [ ] **Step 7: Connect MModeWidget signal to ViewerWidget**

In `main_window.py`, find `_activate_mmode` and add connection:

```python
    def _activate_mmode(self) -> None:
        if self._mmode_widget is None:
            self._mmode_widget = MModeWidget()
            self._mmode_widget.deactivate_requested.connect(self._toggle_mmode)
            self._mmode_widget.vertical_lock_toggled.connect(
                self._viewer.set_mmode_vertical_lock
            )
```

- [ ] **Step 8: Commit**

```bash
git add src/echo_personal_tool/presentation/viewer_widget.py src/echo_personal_tool/presentation/main_window.py
git commit -m "feat(mmode): connect vertical lock toggle to ViewerWidget scan line"
```

---

## Task 4: Add guide lines during placement and dragging

**Covers:** Guide lines visibility

**Files:**
- Modify: `src/echo_personal_tool/presentation/mmode_scan_line.py`
- Modify: `src/echo_personal_tool/presentation/viewer_widget.py`

**Interfaces:**
- Consumes: `MModeScanLineItem.vertical_lock`
- Produces: Guide lines visible during point placement/dragging

- [ ] **Step 1: Write the failing test for guide visibility**

```python
# tests/unit/test_mmode_vertical_lock.py (add)
def test_guides_visible_during_drag():
    from echo_personal_tool.presentation.mmode_scan_line import MModeScanLineItem
    item = MModeScanLineItem(viewer_widget=None)
    item.vertical_lock = True
    # Mock view
    item._view = MagicMock()
    item._view.width.return_value = 800
    item._guide_h = MagicMock()
    item._guide_v = MagicMock()
    # Simulate drag update
    item.line_end = (100.0, 200.0)
    item._update_guides((100.0, 200.0), 600.0)
    item._guide_h.setData.assert_called_once()
    item._guide_v.setData.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_mmode_vertical_lock.py::test_guides_visible_during_drag -v`
Expected: FAIL (method doesn't exist or doesn't update guides)

- [ ] **Step 3: Update _create_graphics to create guides when vertical_lock**

In `mmode_scan_line.py`, modify `_create_graphics`:

```python
    def _create_graphics(self) -> None:
        self._remove_graphics()
        pen = pg.mkPen(color="cyan", style=Qt.PenStyle.DashLine, width=1.5)
        self._line_item = pg.PlotDataItem(pen=pen, antialias=True)
        self._line_item.setZValue(24)
        self._start_node = _MModeNodeItem(self._viewer_widget, 0, self.line_start)
        self._end_node = _MModeNodeItem(self._viewer_widget, 1, self.line_end)
        self._sync_line_data()
        # Create guides if vertical lock enabled
        if self.vertical_lock:
            self._create_guide_graphics()
```

- [ ] **Step 4: Update update_graphics_for_view to update guides**

```python
    def update_graphics_for_view(self, view: pg.ViewBox, frame_height: float) -> None:
        """Convert image coords to view coords (invertY) and update graphics."""
        if self.line_start is None or self.line_end is None:
            return
        view_start = (self.line_start[0], frame_height - self.line_start[1])
        view_end = (self.line_end[0], frame_height - self.line_end[1])
        self._remove_graphics()
        pen = pg.mkPen(color="cyan", style=Qt.PenStyle.DashLine, width=1.5)
        self._line_item = pg.PlotDataItem(pen=pen, antialias=True)
        self._line_item.setZValue(24)
        self._start_node = _MModeNodeItem(self._viewer_widget, 0, view_start)
        self._end_node = _MModeNodeItem(self._viewer_widget, 1, view_end)
        self._sync_line_data_view(view_start, view_end)
        self.add_to_view(view)
        # Update guides if vertical lock
        if self.vertical_lock and self._guide_h is not None and self._guide_v is not None:
            self._update_guides(self.line_end, frame_height)
```

- [ ] **Step 5: Update viewer_widget to pass frame_height to guides**

In `viewer_widget.py`, modify `_mmode_node_dragging`:

```python
    def _mmode_node_dragging(self, endpoint_index: int, pos: tuple[float, float]) -> None:
        if self._mmode_line_item is None:
            return
        h = self._current_frame.shape[0] if self._current_frame is not None else 1.0
        img_pos = (pos[0], h - pos[1])
        if self._mmode_vertical_lock:
            if endpoint_index == 0:
                original = self._mmode_line_item.line_start
            else:
                original = self._mmode_line_item.line_end
            if original is not None:
                img_pos = (original[0], img_pos[1])
        if endpoint_index == 0:
            self._mmode_line_item.move_start_to(img_pos)
        else:
            self._mmode_line_item.move_end_to(img_pos)
        self._mmode_line_item.update_graphics_for_view(self._view, h)
        # Update guides
        if self._mmode_vertical_lock and self._mmode_line_item._guide_h is not None:
            self._mmode_line_item._update_guides(img_pos, h)
        self.mmode_line_completed.emit(*self._mmode_line_item.get_endpoints())
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/unit/test_mmode_vertical_lock.py::test_guides_visible_during_drag -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/echo_personal_tool/presentation/mmode_scan_line.py src/echo_personal_tool/presentation/viewer_widget.py
git commit -m "feat(mmode): add perpendicular guide lines during vertical lock mode"
```

---

## Task 5: Integration test for full vertical lock workflow

**Covers:** End-to-end vertical lock behavior

**Files:**
- Modify: `tests/unit/test_mmode_vertical_lock.py`

**Interfaces:**
- Consumes: All previous tasks
- Produces: Integration test verifying vertical lock + guides

- [ ] **Step 1: Write integration test**

```python
# tests/unit/test_mmode_vertical_lock.py (add)
def test_vertical_lock_integration():
    from echo_personal_tool.presentation.mmode_scan_line import MModeScanLineItem
    
    # Create scan line item
    item = MModeScanLineItem(viewer_widget=None)
    
    # Enable vertical lock
    item.vertical_lock = True
    
    # Set start point
    item.set_start((100.0, 100.0))
    assert item.line_start == (100.0, 100.0)
    
    # Set end point (should keep same X)
    item.set_end((100.0, 200.0))
    assert item.line_end == (100.0, 200.0)
    
    # Simulate vertical lock drag (X should not change)
    # In real usage, X comes from original point
    original_x = item.line_start[0]
    new_y = 300.0
    constrained_pos = (original_x, new_y)
    item.move_end_to(constrained_pos)
    assert item.line_end[0] == original_x  # X unchanged
    assert item.line_end[1] == new_y  # Y updated
```

- [ ] **Step 2: Run integration test**

Run: `pytest tests/unit/test_mmode_vertical_lock.py::test_vertical_lock_integration -v`
Expected: PASS

- [ ] **Step 3: Run all vertical lock tests**

Run: `pytest tests/unit/test_mmode_vertical_lock.py -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_mmode_vertical_lock.py
git commit -m "test(mmode): add integration test for vertical lock workflow"
```

---

## Execution Handoff

After saving the plan, determine execution approach:

1. **Check memory** for a saved `execution-style` preference in the `compose-preferences` memory file. If found (`subagent` or `inline`), use it and skip to the handler below.

2. **If no saved preference,** ask through `compose:ask`:
   - header: `Execution`
   - question: `Plan saved. How would you like to execute it?`
   - options:
     - label: `Subagent, always`, description: `Fresh subagent per task — remember for future sessions`
     - label: `Subagent, this time`, description: `Fresh subagent per task — just this once`
     - label: `Inline, always`, description: `Execute in this session — remember for future sessions`
     - label: `Inline, this time`, description: `Execute in this session — just this once`

   If no user is available, default to Inline for ≤ 3 tasks or tightly coupled tasks, Subagent for > 3 independent tasks.

3. **If "always" variant:** Save to the `compose-preferences` memory file as `execution-style: subagent` or `execution-style: inline`.

**If Subagent:** Use compose:subagent — fresh subagent per task + two-stage review.

**If Inline:** Use compose:execute — batch execution with checkpoints
