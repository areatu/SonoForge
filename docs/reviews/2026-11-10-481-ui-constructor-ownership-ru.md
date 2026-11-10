# Снимок выполнения #481 — владение `ui/` и `constructor/`, обнуление `ui>presentation` и i18n через `application`

> **Снимок на 2026-11-10.** Документ фиксирует состояние на эту дату и не обновляется вслед за кодом: актуальное состояние — в коде, `README.md`, HELP и открытых issues.

Задача: `#481` (фаза 3 эпика `#485`, закрывает отложенное решение из `#419`; `docs/reviews/2026-11-09-weakness-analysis-ru.md`, §2.3)

## 1. Решение о владении `constructor/` (вариант «a»)

Зафиксировано архитектурное решение **вариант (a)**:

- `src/echo_personal_tool/constructor/` является **внутриприложенческим UI-пакетом настольной оболочки** (целевое логическое место — фича-подпакет `presentation/reference_constructor/`), а не отдельным CLI-инструментом или библиотечным слоем.
- Причина: конструктор справочника вызывается напрямую из `presentation/ase_reference_dialog.py` и `presentation/reference_window.py` внутри Full-профиля и обязан разделять с основным окном тему (`dark_theme`), загрузку SVG-иконок (`icon_loader`) и стилизованные файловые диалоги (`styled_dialogs`).
- Прямые импорты `constructor -> infrastructure` запрещены и доведены до **0** (`15 → 0`): локализация переведена на `application.localization`, безопасная категоризация ошибок — на `application.diagnostics`.
- Оставшиеся **14** импортов `constructor -> presentation` (`dark_theme`, `icon_loader`, `styled_dialogs` в 9 файлах) заморожены в `tests/architecture/layer_direction_allowlist.json` и контролируются `scripts/check_layer_directions.py`; маркер `"NOT DECIDED"` удалён, а повторное появление `"NOT DECIDED"` отклоняется валидатором allowlist.

## 2. Миграция общих примитивов в `ui/` (`ui>presentation`: `6 → 0`)

Примитивы, которые листовые виджеты STE (`ui/`) ранее тянули вверх из `presentation/`, перенесены в `src/echo_personal_tool/ui/` с сохранением тонких реэкспортов в `presentation/` по разрешённому направлению `presentation > ui`:

| Примитив | Новый владелец | Совместимость для `presentation/` |
|---|---|---|
| Короткие и полные названия сегментов AHA | `ui/segment_labels.py` | Реэкспорт в `presentation/segment_labels.py` |
| Расчёт якорей подписей сегментов на контуре | `ui/segment_label_anchors.py` | Импорт в `presentation/speckle_overlay.py` |
| Метрики шрифтов и размеров элементов управления | `ui/ui_metrics.py` | Реэкспорт в `presentation/ui_metrics.py` |
| Чистая геометрия фазовой полосы кино | `ui/cine_phase_geometry.py` | Реэкспорт в `presentation/cine_phase_geometry.py` |
| Виджет `CinePhaseStrip` | `ui/cine_phase_strip.py` (провайдер дизайн-токенов + `QPalette`-fallback без `#hex` литералов) | Регистрация `get_theme_tokens` в `presentation/dark_theme.py` и реэкспорт в `presentation/cine_phase_strip.py` |

## 3. Сводка рёбер `check_layer_directions.py` до и после

| Направление | До `#481` | После `#481` | Статус |
|---|---:|---:|---|
| `ui>presentation` | 6 | **0** | Обнулено и под запретом |
| `ui>infrastructure` | 12 | **0** | Обнулено (`localization`, `diagnostics`, `profile_settings`) и под запретом |
| `constructor>infrastructure` | 15 (не отслеживалось) | **0** | Заморожено на `0` в `FORBIDDEN` |
| `constructor>presentation` | 14 (не отслеживалось) | **14** | Заморожено пофайлово в allowlist (`#481`) |
| `infrastructure>application` | 11 | **11** | Без изменений (`#419`) |
