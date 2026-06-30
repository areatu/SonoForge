# Customize Layout — план реализации

## 1. UI

Одна кнопка **≡ Layout** в `SystemBar` между `Reset` и `Minimize`.

```
[...Open][Server][StudyLabel...Status...] | [Settings][Caliper]...[Reset] [≡ Layout] | [_][▢][X]
```

По клику — выезжающее popup-меню (`QMenu` или кастомный `QWidget`) с 5 checkable пунктами:

| Пункт | Тип | Назначение |
|-------|-----|------------|
| Swap Places | check | Меняет местами thumbnail gallery и tool panel |
| Horizontal Gallery | check | Thumbnails снизу, 2 ряда, горизонтальный скролл |
| Activity Bar | check | ToolPanel → узкая панель кнопок (48px) |
| Status Bar | check | Показать/скрыть полосу статуса внизу |
| Multiview | check | Дубликат viewer справа, независимая прокрутка |

---

## 2. Состояние

### `LayoutConfig` dataclass (в `main_window.py`)

```python
@dataclass
class LayoutConfig:
    swap_places: bool = False
    gallery_horizontal: bool = False
    activity_bar: bool = False
    status_bar_visible: bool = True
    multiview: bool = False
```

### Персистентность

В `UserPreferences` добавить:
```python
layout_state_json: str = ""
```
Сериализация: `json.dumps(asdict(config))` / `json.loads(...)`.

Сохранение при каждом `_rebuild_layout()`. Загрузка в `__init__`.

---

## 3. `_rebuild_layout()` — центральный метод

### Логика зон

```
[ left_zone ] [ center_zone ] [ right_zone ]
[ bottom_zone ]  (только если gallery_horizontal)
[ status_bar ]   (если status_bar_visible)
```

```
def decide_left(config):
    if config.activity_bar and config.swap_places: return activity_bar
    if config.swap_places:                         return tool_panel
    if config.gallery_horizontal:                  return None
    return gallery

def decide_center(config):
    if config.multiview:    return QSplitter([viewer1, viewer2])
    return viewer1

def decide_right(config):
    if config.activity_bar and not config.swap_places: return activity_bar
    if config.activity_bar and config.swap_places:     return None
    if config.swap_places:                             return gallery
    if config.gallery_horizontal:                      return tool_panel
    return tool_panel

def decide_bottom(config):
    return gallery if config.gallery_horizontal else None
```

### Алгоритм

1. Очистить `content_layout` (QHBoxLayout)
2. Удалить bottom-панель из `root_layout` если есть
3. Создать left/center/right виджеты по `decide_*` функциям
4. Добавить их в `content_layout`
5. Если `gallery_horizontal`: создать bottom-контейнер, вставить gallery, добавить в `root_layout` (под content, над statusBar)
6. `self.statusBar().setVisible(config.status_bar_visible)`
7. `_save_layout_state()`

---

## 4. Детали кнопок

### 4.1 Swap Places

- Инвертирует `config.swap_places`
- `_rebuild_layout()`
- Если активен Activity Bar — Activity Bar переезжает на противоположную сторону

### 4.2 Horizontal Gallery

- Инвертирует `config.gallery_horizontal`
- `_rebuild_layout()`
- Gallery в horizontal mode:
  - `setFixedWidth(16777215)` — снять фикс. ширину
  - `setFixedHeight(cell_h * 2 + spacing)` — 2 ряда
  - `setWrapping(True)`, `setFlow(LeftToRight)`
  - `setHorizontalScrollBarPolicy(ScrollBarAsNeeded)`
  - `setVerticalScrollBarPolicy(ScrollBarAlwaysOff)`
- При отключении: вернуть вертикальный режим, фикс. ширину

### 4.3 Activity Bar

- Инвертирует `config.activity_bar`
- `_rebuild_layout()`
- Создать `_activity_bar` (QWidget):
  - `QVBoxLayout`, фикс. ширина 48px
  - 3 `QPushButton` (checkable): Measures, Controls, DICOM
  - SVG-заглушки в `resources/icons/` (`activity_measures.svg`, `activity_controls.svg`, `activity_dicom.svg`)
- Поведение:
  - Клик → ToolPanel показывается с этим tab
  - Клик на другую кнопку → ToolPanel переключает tab
  - Клик на активную → ToolPanel прячется
  - ToolPanel появляется рядом с Activity Bar (справа от него)

### 4.4 Status Bar

- Инвертирует `config.status_bar_visible`
- `self.statusBar().setVisible(config.status_bar_visible)`
- `_save_layout_state()`

### 4.5 Multiview

- Инвертирует `config.multiview`
- `_rebuild_layout()`
- При активации:
  - Создать `self._viewer2 = ViewerWidget()` если ещё не создан
  - Поместить `[viewer1, viewer2]` в QSplitter
  - viewer2 клонирует состояние viewer1 (instance + frame)
- Независимая прокрутка:
  - У каждого viewer свой `_current_frame_index`
  - Активный viewer (frame с фокусом) реагирует на Space (Play/Pause)
  - При клике на viewer — он становится активным
  - `_viewer.focus_enter` → `set_active_viewer(viewer)`
  - Space → `active_viewer.toggle_playback()`
- Загрузка другого файла:
  - Ctrl+click на thumbnail → загружает instance во второй viewer
  - Drag'n'drop thumbnail на viewer2 → загружает туда
  - viewer1 не меняется
- Независимые overlays: контуры, калиперы, измерения — у каждого свои
- Архитектура: viewer2 имеет свой instance_uid + frame_index
- При отключении: viewer2 убирается, viewer1 возвращается на всю центральную зону

---

## 5. Изменяемые файлы

| Файл | Что меняем |
|------|------------|
| `main_window.py` | `LayoutConfig`, `_rebuild_layout()`, 5 обработчиков, `_layout_menu_popup`, `_active_viewer`, multiview routing |
| `system_bar.py` | Одна кнопка "≡ Layout" между Reset и Minimize, signal `layout_customize_requested` |
| `thumbnail_gallery.py` | `set_horizontal_mode(bool)`, сигнал `ctrl_clicked(InstanceMetadata)` |
| `viewer_widget.py` | Метод `set_frame_for_viewer(frame_index)`, поддержка независимого состояния, фокус |
| `infrastructure/user_preferences.py` | Поле `layout_state_json` + load/save |
| `resources/icons/` | 3 SVG-заглушки Activity Bar + 1 иконка Layout |

---

## 6. Порядок выполнения

1. **LayoutConfig** + каркас `_rebuild_layout()` (без activity bar / multiview)
2. **Кнопка ≡ Layout** в SystemBar + popup меню
3. **Status Bar** toggle (самое простое)
4. **Swap Places**
5. **Horizontal Gallery** (режим в thumbnail_gallery)
6. **Activity Bar** + 3 SVG-заглушки
7. **Multiview** (независимые viewer + активный viewer по фокусу)
8. **Персистентность** в UserPreferences
9. **Тестирование** комбинаций
