# Micro-UX — hover/press, dialogs, focus, loading

**Дата:** 2026-07-04  
**Статус:** Approved (brainstorming)  
**Предшественник:** [2026-06-30-ui-enhancement.md](../plans/2026-06-30-ui-enhancement.md) (частично выполнен)

---

## Цель

Довести tactile feedback и accessibility до уровня modern desktop apps (VS Code / Fluent) **без** смены цветовой палитры.

### Explicitly cancelled (не входит)

- Darcula / warm palette migration (§1 UI Enhancement)
- Gallery large size, fullscreen F11, panel collapse (отдельные задачи)
- LV Lamé template, MBS Advanced

---

## Текущее состояние (audit)

| Элемент | Статус | Файл |
|---------|--------|------|
| Theme fade 150ms | ✅ | `echopac_theme.py` |
| Gallery collapse slide | ✅ | `thumbnail_gallery.py` |
| Measures accordion 180ms | ✅ | `measures_menu.py` |
| Inter / JetBrains fonts | ✅ | `bundled_fonts.py` |
| SystemBar SVG icons | ✅ | `resources/icons/` |
| QSS `:hover` / `:pressed` | ✅ instant | `echopac_theme.py` |
| Hover color lerp 100ms | ❌ | — |
| Dialog open fade+scale | ❌ | — |
| Context menu animation | ❌ | — |
| Tooltip fade | ❌ | — |
| Focus ring (keyboard) | ❌ | — |
| Disabled opacity | ❌ | — |
| Loading in async buttons | ❌ | — |
| 8px spacing grid | ~ partial | QSS margins inconsistent |

---

## Архитектура

Новый модуль **`presentation/ui_animations.py`** — pure Qt helpers, без бизнес-логики.

```
ui_animations.py
    animate_widget_opacity(widget, from, to, ms, easing)
    show_dialog_animated(dialog)      # fade + scale 0.95→1.0, 200ms OutCubic
    hide_dialog_animated(dialog, on_done)
    HoverColorButton(QPushButton)     # optional subclass OR event filter

echopac_theme.py
    + global QSS: :focus, :disabled
    apply_theme() unchanged

Concrete dialogs / bars
    inherit or call show_dialog_animated in exec path
```

**Принцип:** QSS не поддерживает CSS transitions → hover lerp через `QTimer` (16ms ticks) или `QPropertyAnimation` на custom property `backgroundColor` (если используем styled widget).

---

## Scope v1

### 1. Hover / press lerp (100ms)

**Target widgets:** SystemBar buttons, ActivityBar, ToolPanel section buttons, MeasuresMenu headers.

**Implementation (recommended):** `HoverButtonMixin` via `QObject` event filter:

- `Enter` → animate bg from normal → hover over 100ms linear
- `Leave` → reverse
- `Press` → snap to pressed color (instant OK)
- Read base colors from current theme palette dict (`echopac_theme.get_palette()`)

**Не трогаем:** viewer canvas, thumbnail cells (performance).

### 2. Dialog animations

**Target dialogs:**

- `OrthancStudyDialog`
- `DicomUploadDialog`
- `ServerSettingsDialog` / `ServerProfileDialog`
- `UserPreferencesDialog`
- `SpeckleSettingsDialog`

**Open:** opacity 0→1 + geometry scale 95%→100%, 200ms `OutCubic`  
**Close:** opacity 1→0, 120ms linear → then `accept/reject`

Wrap `exec()`:

```python
def exec_animated(dialog: QDialog) -> int:
    show_dialog_animated(dialog)
    return dialog.exec()
```

### 3. Global QSS states

```css
QPushButton:focus, QToolButton:focus {
    outline: 2px solid {accent};
    outline-offset: 2px;
}
QWidget:disabled {
    opacity: 0.45;
}
```

Tab order: verify SystemBar → ActivityBar → ToolPanel on key widgets.

### 4. Loading button state

**`LoadingButtonHelper`** (composition, not base class):

```python
with loading_button(btn, tr("orthanc.searching")):
    worker.run()
```

- Disable button, show `QProgressIndicator` or text «…»
- Restore on signal finished/failed

**Apply to:**

- Orthanc «Search» / «Download»
- Dicom Upload «Send» — **Note:** QProgressDialog with cancel = acceptable v1; loading_button on OK is optional enhancement
- Server Settings «Test C-ECHO»

### 5. Context menu + tooltip (optional v1.1)

Lower priority; include if time permits:

- `QMenu` showEvent → fade in 120ms
- `QToolTip` — Qt default; custom fade requires event filter on app level

---

## Non-goals (v1)

- Gallery slide animation (already has width anim)
- Ripple effects / Material motion
- Per-widget spring physics
- Light theme re-audit (apply same rules)

---

## Файлы

| Файл | Действие |
|------|----------|
| `presentation/ui_animations.py` | **Create** |
| `presentation/echopac_theme.py` | focus/disabled QSS; export `get_palette()` |
| `presentation/system_bar.py` | Hover mixin on buttons |
| `presentation/activity_bar.py` | Hover mixin |
| `presentation/tool_panel.py` | Hover on section titles |
| `presentation/orthanc_study_dialog.py` | animated exec + loading search |
| `presentation/dicom_upload_dialog.py` | animated exec + loading |
| `presentation/server_settings_dialog.py` | animated exec + C-ECHO loading |
| `tests/unit/test_ui_animations.py` | opacity end values, no crash on fast close |

---

## Performance constraints

- Max 1 active `QPropertyAnimation` per widget
- Stop animation on widget destroy
- No animations during playback (viewer) — UI panels only
- Disable animations if `UserPreferences.reduce_motion` (new bool, default False) — accessibility

---

## Testing

- Unit: `test_ui_animations.py` — mock timer, assert final opacity
- Manual checklist: Tab through SystemBar shows focus ring; disabled upload button at 45% opacity; dialog open/close smooth on 1080p

---

## Порядок реализации

| # | Задача |
|---|--------|
| 1 | `ui_animations.py` core + tests |
| 2 | Global focus/disabled QSS |
| 3 | `HoverButtonMixin` + SystemBar |
| 4 | ActivityBar + ToolPanel |
| 5 | `exec_animated` + 3 main dialogs |
| 6 | `LoadingButtonHelper` on search/upload/C-ECHO |
| 7 | `reduce_motion` preference (optional) |

---

## Связь с UI Enhancement plan

Update `2026-06-30-ui-enhancement.md`:

- §1 Palette → **CANCELLED**
- §2 Fonts → **DONE**
- §4 Animations → superseded by this spec (narrower scope)
- §5 Layout ergonomics → unchanged / separate

---

Implementation plan via `writing-plans` → `docs/superpowers/plans/2026-07-04-micro-ux-implementation.md`.
