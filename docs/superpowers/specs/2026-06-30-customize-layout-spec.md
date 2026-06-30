# Customize Layout — Design Specification

**Date:** 2026-06-30  
**Status:** Draft  
**Type:** UI / Layout  
**Domain:** Workspace layout customization  
**Related:** `plans/customize-layout.md`

---

## 1. Executive Summary

Add a VS Code-inspired **Customize Layout** system to the EchoPAC main window. Five toggleable modes (Swap Places, Horizontal Gallery, Activity Bar, Status Bar, Multiview) accessed via a popup menu from a single toolbar button. Layout state persists between sessions via `QSettings`.

---

## 2. Goals and Non-Goals

### 2.1 Goals

| Goal | Success criterion |
|------|-------------------|
| All 5 layout toggles functional | Each config combination renders without widget leaks or crashes |
| `_rebuild_layout()` idempotent | Calling twice with same config produces identical widget tree |
| Multiview independent scrolling | Two viewers show different frames, each with independent play/pause and timeline |
| Active viewer focus | Click on viewer → Space toggles that viewer's playback |
| Ctrl+click loads into viewer2 | Ctrl+click thumbnail → inactive viewer loads that instance |
| Persistence | Layout state survives app restart |
| No visual glitches | No flicker during swap; animations optional, instant transitions acceptable |

### 2.2 Non-Goals

- Drag-to-resize panel widths (splitter sizes already supported, not part of this spec)
- Floating/undocked panels
- Save/restore splitter positions
- Per-study layout presets
- Customizable Activity Bar icons (placeholders only)

---

## 3. Architecture

### 3.1 Data Structures

```python
@dataclass
class LayoutConfig:
    """Immutable snapshot — always replace, never mutate in place."""
    swap_places: bool = False
    gallery_horizontal: bool = False
    activity_bar: bool = False
    status_bar_visible: bool = True
    multiview: bool = False
```

### 3.2 State Ownership

`LayoutConfig` lives as `MainWindow._layout_config`. Persisted via `UserPreferences.layout_state_json` (JSON-serialized). `MainWindow` owns `_rebuild_layout()` and all child widget references.

### 3.3 Persistence

```python
# user_preferences.py
@dataclass
class UserPreferences:
    ...
    layout_state_json: str = ""  # json.dumps(asdict(LayoutConfig()))

# main_window.py
def _save_layout_state(self) -> None:
    self._user_preferences.layout_state_json = json.dumps(asdict(self._layout_config))
    save_user_preferences(self._user_preferences)

def _load_layout_state(self) -> LayoutConfig:
    raw = self._user_preferences.layout_state_json
    if not raw:
        return LayoutConfig()
    try:
        return LayoutConfig(**json.loads(raw))
    except (json.JSONDecodeError, TypeError, ValueError):
        return LayoutConfig()
```

### 3.4 Widget Tree Ownership

| Widget | Owner | Created | Destroyed |
|--------|-------|---------|-----------|
| `gallery` | `MainWindow` | `__init__` | Never |
| `viewer1` | `MainWindow` | `__init__` | Never |
| `viewer2` | `MainWindow` | Lazy, on first multiview enable | Never (hidden) |
| `tool_panel` | `MainWindow` | `__init__` | Never |
| `activity_bar` | `MainWindow` | Lazy, on first activity bar enable | Never (hidden) |
| `bottom_container` | `MainWindow` | Per `_rebuild_layout()` if needed | Removed on layout change |

All permanent widgets are created once, never deleted — only reparented.

---

## 4. `_rebuild_layout()` — Detailed Specification

### 4.1 Pseudocode

```python
def _rebuild_layout(self) -> None:
    cfg = self._layout_config

    # 1. Clear content_layout (QHBoxLayout)
    self._clear_layout(self.content_layout)  # helper: removeWidget + delete later

    # 2. Remove bottom panel if exists
    if self._bottom_container is not None:
        self.root_layout.removeWidget(self._bottom_container)
        self._bottom_container.deleteLater()
        self._bottom_container = None

    # 3. Build center zone
    if cfg.multiview:
        self._ensure_viewer2()
        center = QSplitter(Qt.Horizontal)
        center.addWidget(self._viewer)
        center.addWidget(self._viewer2)
        center.setHandleWidth(2)
    else:
        center = self._viewer
        if self._viewer2 is not None:
            self._viewer2.hide()
            self._viewer2.setParent(None)  # detach but keep alive

    # 4. Decide left zone
    left = self._decide_left(cfg)
    # 5. Decide right zone
    right = self._decide_right(cfg)

    # 6. Assemble content_layout
    if left is not None:
        left.show()
        self.content_layout.addWidget(left)
    if center is not None:
        if isinstance(center, QWidget):
            center.show()
        self.content_layout.addWidget(center, stretch=1)
    if right is not None:
        right.show()
        self.content_layout.addWidget(right)

    # 7. Bottom zone
    if cfg.gallery_horizontal:
        self._gallery.set_horizontal_mode(True)
        self._bottom_container = QWidget()
        bottom_layout = QHBoxLayout(self._bottom_container)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.addWidget(self._gallery)
        self.root_layout.insertWidget(
            self.root_layout.indexOf(self.statusBar()) if self.statusBar() else -1,
            self._bottom_container,
        )
    else:
        self._gallery.set_horizontal_mode(False)

    # 8. Status bar
    self.statusBar().setVisible(cfg.status_bar_visible)

    # 9. Activity bar visibility
    if cfg.activity_bar:
        self._ensure_activity_bar()
        self._activity_bar.show()
    elif self._activity_bar is not None:
        self._activity_bar.hide()

    # 10. Tool panel visibility
    if cfg.activity_bar:
        self._tool_panel.hide()  # shown on activity bar button click
    elif not cfg.activity_bar:
        self._tool_panel.show()

    self._save_layout_state()
```

### 4.2 Zone Decision Matrix

| Condition | Left | Center | Right | Bottom |
|-----------|------|--------|-------|--------|
| Default | gallery | viewer1 | tool_panel | — |
| Swap | tool_panel | viewer1 | gallery | — |
| Horizontal | — | viewer1 | tool_panel | gallery |
| Horizontal + Swap | — | viewer1 | tool_panel | gallery |
| Activity Bar | gallery | viewer1 | activity_bar | — |
| Activity Bar + Swap | activity_bar | viewer1 | gallery | — |
| Multiview | gallery | split(v1,v2) | tool_panel | — |
| Multiview + Swap | tool_panel | split(v1,v2) | gallery | — |
| All but Status | *(per above)* | | | *(per above)* |

Note: `gallery_horizontal + swap` swaps the viewer and tool_panel left/right when gallery is at bottom. In the table above, Horizontal + Swap is same as Horizontal because gallery is at bottom — the swap only affects if there's something left vs right. Actually let me reconsider...

When gallery is at bottom and swap is on: should the viewer and tool_panel swap? The user said "Swap меняет left/right всего" — so yes, when gallery is at bottom:
- Without swap: [viewer | tool_panel], gallery at bottom
- With swap: [tool_panel | viewer], gallery at bottom

Updated table:

| Condition | Left | Center | Right | Bottom |
|-----------|------|--------|-------|--------|
| Horizontal | viewer1 | — | tool_panel | gallery |
| Horizontal + Swap | tool_panel | — | viewer1 | gallery |

So in Horizontal mode, the viewer and tool_panel are in left/right positions (no center zone), and swap exchanges them.

Let me revise the logic:

```python
def decide_left(cfg):
    if cfg.activity_bar and cfg.swap_places:  return activity_bar
    if cfg.swap_places:
        if cfg.gallery_horizontal:             return tool_panel  # left side
        return tool_panel
    if cfg.gallery_horizontal:                 return viewer1
    if cfg.activity_bar:                       return gallery
    return gallery

def decide_center(cfg):
    if cfg.multiview:   return QSplitter([viewer1, viewer2])
    if cfg.gallery_horizontal:   return None
    return viewer1

def decide_right(cfg):
    if cfg.activity_bar and not cfg.swap_places:  return activity_bar
    if cfg.activity_bar and cfg.swap_places:      return gallery
    if cfg.swap_places:
        if cfg.gallery_horizontal:                 return viewer1
        return gallery
    if cfg.gallery_horizontal:                     return tool_panel
    return tool_panel

def decide_bottom(cfg):
    return gallery if cfg.gallery_horizontal else None
```

Let me verify all combinations:

**Default:** left=gallery, center=viewer1, right=tool_panel, bottom=None ✓
**Swap:** left=tool_panel, center=viewer1, right=gallery, bottom=None ✓
**Horizontal:** left=viewer1, center=None, right=tool_panel, bottom=gallery ✓
**Horizontal+Swap:** left=tool_panel, center=None, right=viewer1, bottom=gallery ✓
**Activity Bar:** left=gallery, center=viewer1, right=activity_bar, bottom=None ✓
**Activity Bar+Swap:** left=activity_bar, center=viewer1, right=gallery, bottom=None ✓
**Multiview:** left=gallery, center=split(v1,v2), right=tool_panel, bottom=None ✓
**Multiview+Swap:** left=tool_panel, center=split(v1,v2), right=gallery, bottom=None ✓
**Activity Bar+Multiview:** left=gallery, center=split(v1,v2), right=activity_bar ✓
**Activity Bar+Multiview+Swap:** left=activity_bar, center=split(v1,v2), right=gallery ✓
**Horizontal+Multiview:** left=viewer1, center=viewer2, right=tool_panel, bottom=gallery
  - Hmm, multiview uses center zone. viewer1 goes left, viewer2 goes center.
  - Should multiview change in horizontal mode? Might be edge case; probably just put both viewers side by side in center, with tool_panel on right.

---

## 5. Component Specifications

### 5.1 SystemBar — Layout Button

```python
# New signal
layout_customize_requested = Signal()

# Button (between btn_reset and self._btn_minimize)
self._btn_layout = QPushButton()
self._btn_layout.setIcon(_load_icon("layout"))
self._btn_layout.setToolTip("Customize Layout")
self._btn_layout.clicked.connect(self.layout_customize_requested.emit)
```

### 5.2 Popup Menu

```python
def _show_layout_menu(self) -> None:
    """Show checkable popup menu below the layout button."""
    menu = QMenu(self._system_bar._btn_layout)
    menu.setObjectName("layoutMenu")

    items = [
        ("Swap Places",     "swap_places",       "⇄  Менять местами Gallery и Tools"),
        ("Horizontal Gallery", "gallery_horizontal", "⊞  Миниатюры снизу, 2 ряда"),
        ("Activity Bar",    "activity_bar",      "≡  Узкая панель инструментов"),
        ("Status Bar",      "status_bar_visible", "_  Полоса статуса"),
        ("Multiview",       "multiview",          "▭  Два независимых окна просмотра"),
    ]
    for label, attr, tooltip in items:
        action = menu.addAction(tooltip)
        action.setCheckable(True)
        action.setChecked(getattr(self._layout_config, attr))
        action.triggered.connect(lambda checked, a=attr: self._on_layout_toggle(a, checked))

    menu.exec(self._system_bar._btn_layout.mapToGlobal(
        QPoint(0, self._system_bar._btn_layout.height())
    ))
```

### 5.3 ThumbnailGallery — Horizontal Mode

```python
def set_horizontal_mode(self, enabled: bool) -> None:
    if enabled:
        self._saved_width = self.width()  # for restore
        self.setFixedWidth(16777215)      # remove fixed width constraint
        self.setFixedHeight(self._cell_h * 2 + self._cell_spacing + 4)
        self.setWrapping(True)
        self.setFlow(QListWidget.Flow.LeftToRight)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    else:
        self.setFixedWidth(_gallery_width(self._cell_w))
        self.setFixedHeight(16777215)  # restore
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
    self._horizontal_mode = enabled
```

### 5.4 Activity Bar

```python
class ActivityBar(QWidget):
    """Vertical icon bar (VS Code style, ~48px)."""
    tab_activated = Signal(str)    # "measures" | "controls" | "dicom"
    tab_deactivated = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(48)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._buttons: dict[str, QPushButton] = {}
        for name, icon_file in [
            ("measures", "activity_measures.svg"),
            ("controls", "activity_controls.svg"),
            ("dicom",    "activity_dicom.svg"),
        ]:
            btn = QPushButton()
            btn.setIcon(_load_icon(icon_file.replace(".svg", "")))
            btn.setCheckable(True)
            btn.setToolTip(name.capitalize())
            btn.clicked.connect(lambda _, n=name: self._on_click(n))
            layout.addWidget(btn)
            self._buttons[name] = btn
        layout.addStretch(1)

    def _on_click(self, name: str) -> None:
        btn = self._buttons[name]
        if btn.isChecked():
            # Uncheck all others
            for n, b in self._buttons.items():
                if n != name:
                    b.setChecked(False)
            self.tab_activated.emit(name)
        else:
            self.tab_deactivated.emit(name)

    def set_active(self, name: str | None) -> None:
        for n, b in self._buttons.items():
            b.setChecked(n == name)
```

### 5.5 Activity Bar → ToolPanel

```python
# In MainWindow:
def _on_activity_tab_activated(self, tab: str) -> None:
    tab_map = {"measures": 0, "controls": 1, "dicom": 2}
    if tab in tab_map:
        self._tool_panel._tabs.setCurrentIndex(tab_map[tab])
    # Position tool panel next to activity bar
    activity_on_right = (
        self._layout_config.activity_bar and not self._layout_config.swap_places
    )
    # tool_panel is already in the layout if decide_right returned None for activity_bar+swap
    # Actually tool_panel should appear as an overlay or insert next to activity bar
    self._tool_panel.show()

def _on_activity_tab_deactivated(self, tab: str) -> None:
    self._tool_panel.hide()
```

The tool panel positioning when using activity bar:

- `activity_bar + default (right)`: activity_bar is in `content_layout` right zone. Tool panel is hidden. When tab activated → tool panel appears to the right of activity_bar (as an overlay or by inserting into layout).
- `activity_bar + swap (left)`: activity_bar is in left zone. Tool panel appears to the right of activity_bar when activated.

Implementation: when activity bar is active, `_tool_panel` is NOT in `content_layout`. Instead:
- When tab activated: `_tool_panel` is inserted into `content_layout` immediately after the activity bar (or before, depending on position). Fixed width 280px.
- When tab deactivated: `_tool_panel` is removed from `content_layout`.

### 5.6 Multiview — Independent Viewers

```python
# In MainWindow.__init__:
self._viewer = ViewerWidget()
self._viewer2: ViewerWidget | None = None
self._active_viewer: ViewerWidget = self._viewer
self._viewer.installEventFilter(self)  # track focus

def _ensure_viewer2(self) -> None:
    if self._viewer2 is not None:
        return
    self._viewer2 = ViewerWidget()
    self._viewer2.installEventFilter(self)
    # Sync initial state from viewer1
    self._viewer2.set_state(self._controller.state_manager.snapshot)

def eventFilter(self, obj, event) -> bool:
    if event.type() == QEvent.Type.MouseButtonPress:
        if obj is self._viewer or obj is self._viewer2:
            self._active_viewer = obj
    return super().eventFilter(obj, event)

# Play/pause uses active viewer:
def _toggle_playback_shortcut(self) -> None:
    if self._active_viewer is self._viewer2 and self._viewer2 is not None:
        # viewer2 has its own playback state
        self._controller.toggle_viewer2_playback()
    else:
        self._controller.toggle_playback()

# Ctrl+click on thumbnail → load into viewer2
def _on_instance_selected(self, selected) -> None:
    # Check if Ctrl is held
    modifiers = QApplication.keyboardModifiers()
    if modifiers & Qt.KeyboardModifier.ControlModifier and self._viewer2 is not None:
        self._load_instance_into_viewer2(selected)
        return
    # Normal behavior: load into viewer1
    ...
```

### 5.7 Multiview — Data Loading

`viewer2` needs its own frame loading and state. Two approaches:

**Approach A — Shared StateManager, separate frame_index:**
- Single `StateManager` tracks `instance` (shared) but `viewer2` tracks its own `current_frame_index`.
- `_controller.load_frame_for_viewer(viewer_id, instance, frame_index)` → decodes and pushes to that viewer.

**Approach B — Two StateManagers:**
- Each viewer has its own `StateManager`. Controller maintains both.

Approach A is simpler. For fully independent instance loading (Ctrl+click), viewer2 needs its own instance_uid separate from `StateManager`. Implementation:

```python
# In MainWindow:
_viewer2_instance: InstanceMetadata | None = None
_viewer2_frame: int = 0

def _load_instance_into_viewer2(self, instance: InstanceMetadata) -> None:
    self._viewer2_instance = instance
    self._viewer2_frame = 0
    self._controller.load_instance_for_viewer(
        self._viewer2, instance, frame_index=0
    )
```

Controller side:
```python
def load_instance_for_viewer(self, viewer, instance, frame_index):
    # Load decoded frame data directly into viewer
    frame = self._frame_cache.get(instance.sop_instance_uid, frame_index)
    if frame is not None:
        viewer.show_frame(np.asarray(frame))
    else:
        self._decode_and_send(viewer, instance, frame_index)
```

---

## 6. SVG Placeholder Icons

Four new SVG icons in `src/echo_personal_tool/resources/icons/`:

1. **layout.svg** — grid/layout icon (for the main layout button)
2. **activity_measures.svg** — circle with ruler (placeholder)
3. **activity_controls.svg** — circle with slider (placeholder)
4. **activity_dicom.svg** — circle with D (placeholder)

Simple 24×24 SVG viewBox, monochrome, using `currentColor` for theme support.

---

## 7. Edge Cases

| Case | Behavior |
|------|----------|
| Toggle Multiview off while viewer2 is loaded | viewer2 content discarded, viewer1 unaffected |
| Toggle Activity Bar while tool panel is open | Tool panel hidden; activity bar takes its place |
| Swap Places + Activity Bar | Activity bar moves to opposite side |
| Horizontal Gallery + Multiview | gallery at bottom, both viewers in left/center (or center split) |
| All 5 toggles on simultaneously | gallery at bottom, activity bar in left zone, multiview split center, tool panel shown on activity click, status bar visible |
| Ctrl+click without Multiview | Ctrl+click loads into viewer1 (normal behavior, no special handling) |
| viewer2 playback reaches end | Stops; user clicks viewer2 → Space restarts |
| Rapid toggling | `_rebuild_layout()` wraps in `setUpdatesEnabled(False)` / `True` + single-shot QTimer debounce if needed |

---

## 8. Testing

### 8.1 Unit Tests

| Test | What it verifies |
|------|------------------|
| `test_layout_config_defaults` | All fields False/True |
| `test_layout_config_serialize_roundtrip` | `json.dumps` → `LayoutConfig(**json.loads(...))` identity |
| `test_gallery_horizontal_mode_switch` | FixedWidth → FixedHeight, scrollbar policy change |
| `test_activity_bar_buttons_checkable` | Exactly one button checked at a time |
| `test_layout_persistence` | Save → restart app → same layout state |

### 8.2 Integration Tests (pytest-qt)

| Test | What it verifies |
|------|------------------|
| `test_swap_places` | gallery and tool_panel exchange positions in content_layout |
| `test_horizontal_gallery` | gallery parent is bottom_container, width is 16777215 |
| `test_activity_bar_shows` | activity_bar visible, tool_panel hidden |
| `test_activity_bar_tab_switch` | Click Measure → Measure tab active in tool_panel |
| `test_multiview_enable` | viewer2 created and visible, QSplitter as parent |
| `test_multiview_disable` | viewer2 hidden, viewer1 back in center |
| `test_active_viewer_focus` | Click viewer2 → Space controls viewer2 |
| `test_ctrl_click_viewer2` | Ctrl+click loads instance into viewer2 |
| `test_all_combinations_no_crash` | Cycle through all 32 config combinations |

### 8.3 Manual Testing Checklist

- [ ] Each toggle individually
- [ ] Swap + Horizontal + Activity Bar
- [ ] Multiview with independent scrolling
- [ ] Ctrl+click into viewer2
- [ ] Play/pause on active viewer
- [ ] Restart app → layout restored
- [ ] No visual artifacts when toggling

---

## 9. Dependencies

| Dependency | Reason |
|------------|--------|
| Python 3.10+ | `dataclass` + `from __future__ import annotations` |
| PySide6 | Qt widgets |
| `json` (stdlib) | Serialization |
| `QSettings` | Persistence |

No new external dependencies.

---

## 10. Open Questions

1. **Multiview frame cache:** Should `FrameCache` support two concurrent playback positions, or do we load frames independently for viewer2?
2. **Activity Bar overlay:** Tool panel shown next to activity bar — should it push content (add to layout, resizing viewer) or float over (overlay Z-order)?
3. **ctypes/win32:** Frameless window drag on dual-monitor — already handled; no change needed.
