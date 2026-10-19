# Токены оформления интерфейса

> [English version](ui_tokens.md)

Цвета SonoForge описаны один раз — как **семантические токены**, то есть роль
цвета, а не его оттенок. Сырые цвета темы живут в одном модуле; всё
остальное (таблицы стилей, делегаты, рисуемые виджеты) просит токен.

Система введена в UI-0 PR-1 (спека редизайна, §5) и дополняется следующими
PR пакета: области переносятся на токены по одной, прежняя палитра исчезает в
UI-8.

## Три слоя

| Слой | Модуль | Что хранит |
|------|--------|------------|
| Палитра | `presentation/theme/palettes.py` | Сырые цвета каждой темы. Единственное место, где допустим hex-литерал. |
| Токены | `presentation/theme/tokens.py` | Словарь: роль цвета и соответствие прежним ключам палитры. |
| Потребители | `presentation/theme/qss.py`, виджеты | Читают токены, а не цвета. |

`presentation/dark_theme.py` — фасад: он по-прежнему отдаёт прежние 28 ключей
(`get_theme_palette()`) и ту же таблицу стилей
(`build_clinical_stylesheet()`), поэтому места вызова переносятся по одной
области.

Правила контраста (WCAG 2.1 AA) лежат в `presentation/theme/contrast.py` — их
использует и CI-скрипт `scripts/check_contrast.py`, поэтому правило и проверка
не могут разойтись. Модуль `presentation/theme_tokens.py` оставлен фасадом
прежнего имени: он переэкспортирует пакет и исчезнет вместе с прежней
палитрой в UI-8.

## Группы токенов

| Группа | Токены | Значение |
|--------|--------|----------|
| `surface.*` | `surface.0` … `surface.3`, `surface.hover`, `surface.pressed` | Фоны, от окна до самого приподнятого элемента |
| `line.*` | `line.1`, `line.2` | Разделители и рамки контролов |
| `text.*` | `text.1`, `text.2`, `text.3`, `text.disabled` | Основной текст, вторичный текст, подсказки, недоступные элементы |
| `accent.*` | `accent`, `accent.text`, `accent.on`, `accent.tab`, `accent.selected` | Активный инструмент, основное действие, выбранный элемент |
| `state.*` | `state.ok`, `state.warn`, `state.err`, `state.info`, `state.attention.bg/text`, `state.danger.*` | Состояния интерфейса; фиксированная пара маркера следующего шага |
| `provenance.*` | `provenance.manual`, `.missing`, `.default`, `.warning` | Фиксированные цвета источника значения и предупреждений калькулятора |
| `focus.*` | `focus.ring` | Рамка фокуса клавиатуры |
| `progress.*`, `slider.*` | `progress.text`, `slider.track`, `slider.fill` | Полоса прогресса и ползунок |
| `paper.*` | `paper.surface`, `paper.text`, `paper.text.dim`, `paper.line`, `paper.highlight`, `paper.done` | Лист A4 отчёта и лист измерений; цвета бумаги одинаковы во всех темах |
| `overlay.*` | контуры, калиперы, подписи, точки, маркеры, разметка спектра допплера, лента маркеров multiview | Разметка на снимке; тема и акцентный цвет её не меняют |

Размеры — по сетке спеки: отступы 4 px, радиусы 4/6/8/10, высота контролов
28/32, иконки 16/18, размеры шрифта 11.5/12.5/13.5/15/24.

## Правила

1. **Никаких сырых цветов вне модуля палитр.** `scripts/check_ui_colors.py`
   считает hex-литералы в `presentation/`, `ui/` и `constructor/` и сравнивает
   число с `scripts/ui_colors_baseline.json`. Число может только убывать;
   новый литерал валит сборку.
2. **Контраст проверяется.** `scripts/check_contrast.py` сверяет пары токенов
   с WCAG 2.1 AA. У текста маркера следующего шага контраст с фоном 14,04:1
   во всех темах (минимум 4,5:1). Тема «Графит» — ошибка, прежние темы — отчёт:
   их цвета ни с кем не согласовывались.
3. **Прежние темы не меняются.** Таблица стилей navy, светлой и VS Code
   закреплена golden-файлами (`tests/fixtures/ui/stylesheet_*.golden.txt`):
   изменение — это изменение интерфейса, требующее решения, а не слияния.
4. **Разметка на снимке — не тема.** Цвета контуров и калиперов живут в группе
   `overlay.*`; тема их не меняет.

## Прежние ключи палитры

28 ключей `get_theme_palette()` вычисляются из токенов:

| Прежний ключ | Токен | Прежний ключ | Токен |
|--------------|-------|--------------|-------|
| `bg_dark` | `surface.0` | `reset_bg1` | `state.danger.bg` |
| `bg_panel` | `surface.1` | `reset_bg2` | `state.danger.bg2` |
| `bg_control` | `surface.2` | `reset_hov1` | `state.danger.bg.hover` |
| `bg_button` | `surface.3` | `reset_hov2` | `state.danger.bg2.hover` |
| `bg_button_hover` | `surface.hover` | `reset_pressed` | `state.danger.bg.pressed` |
| `bg_button_pressed` | `surface.pressed` | `reset_border` | `state.danger.border` |
| `accent` | `accent` | `reset_border_hov` | `state.danger.border.hover` |
| `accent_bright` | `accent.text` | `reset_text` | `state.danger.text` |
| `accent_tab` | `accent.tab` | `progress_text` | `progress.text` |
| `accent_selected` | `accent.selected` | `hover_btn1` | `surface.hover.alt` |
| `text` | `text.1` | `success` | `state.ok` |
| `text_dim` | `text.2` | `warning` | `state.warn` |
| `border` | `line.1` | `error` | `state.err` |
| `slider_track` | `slider.track` | | |
| `slider_fill` | `slider.fill` | | |

Токены, которых в прежней палитре не было, выводятся: `text.3` и
`text.disabled` — из `text.2`, `line.2` — из `line.1`, `focus.ring` и
`state.info` — из `accent`.

## Тема «Как в системе»

`presentation/theme/system_theme.py` определяет цветовую схему системы в одном
месте: Windows читает `AppsUseLightTheme` из реестра (`0` — система тёмная),
macOS спрашивает `defaults` о стиле интерфейса, остальные рабочие столы
оставляют тёмную тему приложения. Палитра и логотип следуют одному ответу:
раньше их спрашивали отдельно, и они расходились.

## Как использовать токен

```python
from echo_personal_tool.presentation.theme.palettes import get_palette_tokens

tokens = get_palette_tokens("graphite")
painter.setPen(QColor(tokens["accent"]))
```

Внутри виджета палитра текущей темы доступна через фасад:

```python
from echo_personal_tool.presentation.dark_theme import get_theme_palette

palette = get_theme_palette()  # прежние 28 ключей, вычисленные из токенов
```

Новый код не должен использовать прежние ключи: берите токен напрямую. Ключи
остаются до переноса областей (UI-0 PR-3…PR-7b).

## Состояние переноса

| PR | Область | Что сделано |
|----|---------|-------------|
| PR-3 | Верхняя панель и строка состояния | `dark_theme.get_theme_tokens()` — роли активной темы для виджетов; иконки полосы, вкладок и рейки берут `text.1`; подсветка «Нормативов» снята (шесть литералов), кнопка стала обычной кнопкой полосы; подписи строки состояния — `MainWindow.apply_status_bar_tokens()` (`state.warn`, `text.3`); в рейке исправлена непрозрачная чёрная подложка иконок (`fill(0)` → прозрачная заливка). Храповик: 378 → 367. |
| PR-4 | Панель и меню | Не механическое удаление десяти литералов: прежним семантическим цветам соответствуют фиксированные токены `state.attention.*`, `provenance.*`, `paper.highlight`/`paper.done` во всех темах. Вид маркера следующего шага сохранён; контраст — 14,04:1 (минимум 4,5:1). Храповик: 367 → 357. |
| PR-5 | Справочник | `structured_reference_widget`, `ase_reference_dialog` и web-справочник читают роли токенов (`surface.*`, `text.1/2`, `line.1`, `accent.tab`, `progress.text`, `state.*`); наведение кнопки закрытия — `state.danger.solid`/`state.danger.on`; web-мост отдаёт CSS-переменные из токенов. Оставлено: клинические цвета градаций (их владелец — UI-5; в UI-5 PR-1 они переехали в `presentation/reference_grades.py` и читаются оттуда и окном справочника, и карточкой S2), `#ffffff` на `accent.tab` (попиксельное совпадение navy) и поисковые шаблоны SVG-ассетов. Храповик: 367 → 359. |
| PR-6 | Orthanc и делегаты | scoped QSS загрузчика исследований, экран настроек сервера и диалог профилей читают роли; `build_loader_dialog_stylesheet()` по-прежнему принимает прежнюю 28-ключевую палитру. Делегат ряда берёт `surface.*`, `line.*`, `text.*`, `accent`, `state.*`; для letterbox миниатюры, галочки и текста на бейджах заведены пять фиксированных токенов. Храповик: 349 → 313. |
| PR-7 | Вьюер | `viewer_widget` переведён на `overlay.*`: контуры (ручной, авто, Симпсон), калиперы, подписи, текущая точка и маркеры КД/КС; группа получила значения во всех пяти палитрах. Храповик: 313 → 273. |
| PR-7b | Хвост оверлеев | `doppler_overlay`, `doppler_widget`, `speckle_overlay`, `multiview_marker_strip`, `mmode_measurement`, `mmode_scan_line`, `mmode_widget`, `ecg_strip_widget`, `strain_curve_widget` — 31 токен разметки спектра, трасс, интервалов, проверки трекинга, M-режима, кривых strain и ленты маркеров плюс цикл `overlay.multiview.markers` (`palettes.overlay_cycle`). Цвета не изменились ни на один. Оставлено сознательно: чипы и баннеры на снимке в `viewer_widget` (14) и `thumbnail_gallery` (14, переезжает вместе с лентой клипов UI-2 PR-4) — это хром поверх снимка, а не разметка; плавающие карточки `ste_sensitivity_overlay`, `vessel_sensitivity_overlay`, `study_loading_overlay` (15) — легаси-navy, их перевод на `surface.*`/`line.*`/`text.*` меняет вид в светлых темах и решается отдельно. Храповик: 273 → 210. |

Виджеты берут токены активной темы через фасад — так же, как рейка:

```python
from echo_personal_tool.presentation.dark_theme import get_theme_tokens

tokens = get_theme_tokens()   # роли текущей темы; словарь — копия
painter.setPen(QColor(tokens["text.1"]))
```

Смена темы — единственный механизм перекраски: ничего не нужно проверять на
«тёмная ли тема» в виджете.
