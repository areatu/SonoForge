# UI Enhancement: читаемость, эргономика, анимации, тема

**Дата:** 2026-06-30  
**Тип:** design / ux  
**Статус:** partial — see [2026-07-04-micro-ux-design.md](../specs/2026-07-04-micro-ux-design.md)

---

## 1. 🎨 Цветовая схема — ~~уточнение палитры~~ **CANCELLED (2026-07-04)**

> Darcula / warm palette migration removed from roadmap. Current EchoPAC palette retained.

<!--
**Проблема:** Текущая тёмная тема использует холодный сине-серый (`#0a1018`)...
(Original section preserved in git history)
-->

## 2. 🔤 Шрифты — читаемость

**Проблема:** DejaVu Sans 12px — устаревший выбор. Мелкие подписи (11px в SystemBar) нечитабельны на HiDPI. Нет иерархии размеров.

### Новая шрифтовая система

| Элемент | Сейчас | → Станет |
|---|---|---|
| Основной UI | DejaVu Sans 12px | **Inter** 13px |
| Моноширинный | DejaVu Sans Mono 12px | **JetBrains Mono** 12px |
| SystemBar кнопки | DejaVu Sans 11px | Inter 12px semibold |
| ToolPanel кнопки | DejaVu Sans 11px | Inter 11px medium |
| Thumbnail index | DejaVu Sans 9pt bold | Inter 10px semibold |
| Результаты | DejaVu Sans Mono user-size | JetBrains Mono user-size |
| Заголовки секций | — (нет стиля) | Inter 13px semibold, `letter-spacing: 0.3px` |
| Метки измерений | 12px | Inter 12px medium |

### Почему Inter

- x-height на 12% больше, чем у DejaVu Sans
- При 11-12px Inter читается как DejaVu при 13-14px
- Встроенные `Inter Display` для крупных (>20px) и `Inter Text` для мелких
- Open-source (SIL OFL)

**Файлы:**
- `src/echo_personal_tool/resources/bundled_fonts.py` — подключить Inter .ttf
- `src/echo_personal_tool/presentation/echopac_theme.py` — заменить `FONT_FAMILY_UI`

---

## 3. 📐 Скругления — градуальная система

**Проблема:** Сейчас везде `4px` (кнопки) и `3px` (GroupBox). Нет иерархии.

### Новая система (Windows 11 + Material 3)

| Элемент | Сейчас | → Станет |
|---|---|---|
| Кнопки (в панелях) | 4px | **4px** |
| Кнопки (SystemBar) | 4px | **4px** |
| GroupBox | 3px | **6px** |
| Панели (ToolPanel, Gallery) | 0px | **8px** внутренние углы |
| QTab виджет | 0px | **8px** верхние углы active tab |
| Диалоги | 0px | **12px** |
| Результаты overlay | 5px | **8px** |
| Скроллбар handle | 4px | **6px** |
| Прогресс-бар | 0px | **4px** |

Правило: **4px для контролов, 8px для контейнеров, 12px для окон**.

**Файлы:** `src/echo_personal_tool/presentation/echopac_theme.py` — `build_echopac_stylesheet()`

---

## 4. 🎬 Анимации — добавляем микро-взаимодействия

**Сейчас:** ровно одна анимация — аккордеон меню (180ms OutCubic).

### Новые анимации

| Элемент | Тип | Длительность | Easing |
|---|---|---|---|
| Hover на кнопках | `background-color` переход | **100ms** | `linear` |
| Смена темы | `QGraphicsOpacityEffect` fade | **150ms** | `ease-in-out` |
| Контекстное меню open | Fade + slide Y (8px) | **120ms** | `OutCubic` |
| Контекстное меню close | Fade out | **80ms** | `linear` |
| Tooltip | Fade in | **80ms** | `linear` |
| Gallery show/hide | Slide left/right | **200ms** | `OutQuint` |
| Dialog open | Fade + scale (0.95→1.0) | **200ms** | `OutCubic` |
| Dialog close | Fade only | **120ms** | `linear` |

**Реализация:** `QPropertyAnimation` + `QGraphicsOpacityEffect`. Для кнопок — `QTimer` + смена стиля (т.к. QSS transition не поддерживается в PySide6).

**Файлы:**
- `src/echo_personal_tool/presentation/echopac_theme.py` — анимация темы
- `src/echo_personal_tool/presentation/measures_menu.py` — уже есть аккордеон (180ms OutCubic — OK)
- Новые файлы по необходимости

---

## 5. 🧭 Расположение элементов — эргономика

**Проблемы:**
1. Gallery слева — 2 колонки тесноваты, нет collapse
2. ToolPanel справа — 280px фикс, нет collapse
3. SystemBar кнопки — текстовые, нет иконок
4. Нет кнопки скрыть/показать результаты
5. Нет полноэкранного режима

### 5a. Gallery — три размера + collapse

- Добавить **3-й размер `"large"`** (176×132 px, cell 192×148)
- Добавить **collapse button** (◀/▶) — скрыть gallery, viewer на всю ширину
- Горячая клавиша `` ` `` (backtick) / Tab
- Шрифт меток: 9pt → 11px

### 5b. ToolPanel — collapse + QSplitter

- Кнопка collapse справа вверху (⏩/⏪)
- `QSplitter` вместо фиксированной ширины (возможность ресайзить)
- Иконки для 16 секций MeasureTab

### 5c. SystemBar — SVG-иконки

| Кнопка | Иконка (Material Symbols) |
|---|---|
| "Open folder..." | `folder_open` |
| "Загрузить с сервера..." | `cloud_download` |
| "Настройки" | `settings` |
| "Caliper" | `straighten` |
| "Calibration B-mode" | `tune` |
| "Calibration Doppler" | `show_chart` |
| "Нормативы" | `description` |
| "Reset" | `refresh` |

SVG-файлы в `src/echo_personal_tool/resources/icons/`.

### 5d. Полноэкранный режим

- Кнопка в правом верхнем углу viewer (`fullscreen`/`fullscreen_exit`)
- Горячая клавиша `F11`
- Скрывает Gallery и ToolPanel

### 5e. Timeline — step кнопки + крупнее

- Кнопки ⏮ / ⏭ (step back/forward)
- Счётчик "Frame X/Y"
- Высота ползунка: стандартная → ~24px

**Файлы:**
- `src/echo_personal_tool/presentation/main_window.py`
- `src/echo_personal_tool/presentation/system_bar.py`
- `src/echo_personal_tool/presentation/thumbnail_gallery.py`
- `src/echo_personal_tool/presentation/tool_panel.py`
- `src/echo_personal_tool/presentation/viewer_widget.py`

---

## 6. 🎯 Единая сетка отступов (8px baseline)

| Элемент | spacing |
|---|---|
| Межкнопочное расстояние | 8px |
| Padding внутри панелей | 8px |
| Padding GroupBox contents | 8px |
| Padding Tab contents | 12px |
| Margin между секциями | 16px |
| Padding диалогов | 16px |
| Padding кнопок (H/V) | 8px / 4px |
| Line-height текста | 1.4 (body), 1.0 (headings) |

**Файлы:** `src/echo_personal_tool/presentation/echopac_theme.py` — `build_echopac_stylesheet()`

---

## 7. 📦 Дополнительно: состояния и обратная связь

- **Disabled**: `opacity: 0.4` + `cursor: not-allowed` (не цветом, а прозрачностью — как VS Code)
- **Focus ring**: `2px solid accent` + `offset 2px` для Tab-навигации
- **Active section**: left-border indicator (3px solid accent)
- **Loading state**: спиннер внутри кнопки "Загрузить", "Найти"

---

## 8. 📋 Приоритеты и трудоёмкость

| # | Что | Трудоёмкость | Эффект |
|---|---|---|---|
| 1 | Inter шрифт + иерархия размеров | 1 день | ★★★★★ |
| 2 | Единая система скруглений (4/8/12) | 0.5 дня | ★★★★ |
| 3 | SVG-иконки в SystemBar | 1 день | ★★★★ |
| 4 | Collapse боковых панелей | 1 день | ★★★★ |
| 5 | Hover анимация кнопок (100ms) | 0.5 дня | ★★★ |
| 6 | Улучшенная палитра (тёплые тона) | 0.5 дня | ★★★ |
| 7 | Анимация смены темы (fade) | 0.5 дня | ★★ |
| 8 | Анимация диалогов (fade+scale) | 0.5 дня | ★★ |
| 9 | Единая сетка отступов (8px) | 0.5 дня | ★★★★ |
| 10 | Focus ring / Tab-навигация | 0.5 дня | ★★★ |
| 11 | Gallery — resize + large превью | 1 день | ★★★ |
| 12 | Timeline — step кнопки + крупный slider | 0.5 дня | ★★ |

---

## Исследование: референсы UI

Проведён анализ следующих источников:

### Medical DICOM viewers
- **Horos** — macOS-native, стандартные Aqua контролы, viewport 70-80% экрана
- **RadiAnt** — плоский toolbar, минимализм, "lightning fast" zoom/pan
- **OHIF Viewer** — React+Tailwind, тёмный viewport, полупрозрачный toolbar, контекстные режимы
- **Sectra IDS7** — worklist как центр навигации, тулзы скрыты до вызова
- **Visage Ease** — web-based, "consumer-grade" UX, плавные анимации, стриминг без ожидания

### Modern desktop apps (dark theme)
- **VS Code (Dark+)** — `#1E1E1E` фон, `#D4D4D4` текст, muted syntax coloring
- **JetBrains Darcula** — `#2B2B2B` тёплый фон, `#A9B7C6` текст — меньше устают глаза
- **Spotify** — `#121212` фон, капсульные кнопки, 4-8px скругления, hover 150ms
- **Discord** — три уровня surface (`#1E1F22`/`#2B2D31`/`#313338`), 4px скругления
- **Figma** — Inter шрифт, 11px uppercase лейблы, 6px скругления
- **Obsidian** — минимализм, контент-фокус, OKLCH цвета, CSS snippets

### Design guidelines
- **Material Design 3**: 4/8/12/28px скругления, elevation через тени, Surface `#121212`
- **Apple HIG**: SF Pro (optical sizing), 13px min для данных, 10-12pt скругления, spring-анимации
- **Windows 11 Fluent**: Segoe UI Variable, 4px контролы/8px контейнеры, Mica материал

### Цвета для эхо-приложения
```css
Background (main):        #111827  - тёплый тёмно-серый
Background (panels):      #1a2332  - чуть светлее
Background (toolbar):     #243044  - distinct elevation
Background (hover):       #2e4054  - подсветка
Text primary:             #f1f5f9  - тёплый белый
Text secondary:           #94a3b8  - серый для подписей
Accent (active tool):     #60a5fa  - голубой (не путать с Doppler)
Accent (measurement):     #fbbf24  - янтарный для измерений
Success/Warning/Error:    #34d399 / #fb923c / #f87171
Divider lines:            #334155
```
