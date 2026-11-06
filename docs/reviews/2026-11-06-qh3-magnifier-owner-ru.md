# QH-3 follow-up, срез 2: единственный владелец магнитной лупы

> **Снимок на 2026-11-06.** Документ фиксирует состояние на эту дату и не обновляется вслед за кодом:
> актуальное состояние — в коде, `README.md`, HELP и открытых issues. Issue:
> [#420](https://github.com/areatu/SonoForge/issues/420). Предыдущий срез — инвентаризация мостов
> (`docs/reviews/2026-11-05-qh-3-bridge-inventory-ru.md`), §5 п. 1.

## 1. Что было не так

Инвентаризация 2026-11-05 зафиксировала у `MagnifierController` два вида сцепления с `ViewerWidget`:

1. **Параллельный источник истины.** Виджет держал `_magnifier_enabled`, `_magnifier_zoom`,
   `_magnifier_radius_px`, `_magnifier_linear_persistent`, `_magnifier_held`,
   `_magnifier_persistent_active`, `_magnifier_lens` и `_reduce_motion`; контроллер — свои копии тех же
   значений. `apply_user_preferences()` обновляла сначала копию виджета, потом (через `hasattr`-защиту)
   контроллер, поэтому расхождение было вопросом времени, а не гипотезой.
2. **Дубль геометрии.** Позиционирование линзы (`set_lens_diameter`, `set_crop`, смещение
   «слева-сверху», клампинг в границы виджета, `set_anchor_delta`) существовало дважды:
   `ViewerWidget._update_magnifier_loupe` и `MagnifierController._update_loupe_impl`. Рабочим был
   виджетный вариант, контроллерный — мёртвым.

## 2. Что сделано

| Решение | Где |
|---|---|
| Вся настройка (`enabled`, `zoom`, `radius_px`, `linear_persistent`, `reduce_motion`) живёт в контроллере; в виджете не осталось ни одного поля состояния | `viewer_widget.py` |
| Публичный шов `viewer.magnifier_controller` — единственный способ добраться до состояния и линзы | `viewer_widget.py` |
| `apply_user_preferences()` — один вызов `configure(...)`, без локальной копии | `viewer_widget.py` |
| Удержание клавиши: `keyPress` → `set_held(True)`, `keyRelease` → `set_held(False)` (скрытие линзы и «persistent» — в контроллере) | `viewer_widget.py` |
| Точка контура/калипера: `notify_point_placed()` вместо ручного сброса флагов и `hide_animated()` | `viewer_widget.py` |
| Предикат «постоянной лупы» (только линейные B/M, не Doppler, не сосуды) — `sync_persistent(...)` контроллера | `viewer_widget.py` |
| Геометрия линзы — одна реализация; виджет передаёт `display` и `view_mapping` | `magnifier_controller.py` |
| Линза создаётся фабрикой `_create_magnifier_lens` и принадлежит контроллеру (родитель — виджет, §7.3) | оба файла |
| Однообразные `try/except RuntimeError` вокруг линзы свёрнуты в `_live_lens` / `_configure_lens` / `_hide_lens` | `magnifier_controller.py` |
| Новое свойство `linear_persistent` (наблюдаемость без приватных полей) | `magnifier_controller.py` |

Поведенческая правка по ходу среза: раньше ветка «выключить лупу» внутри `configure()` была вложена
в `if zoom is not None`, то есть выключение магнификатора без смены зума не гасило уже видимую линзу
(виджет компенсировал это своей копией). Теперь выключение гасит линзу всегда — это закреплено тестом.

## 3. Числа

| Показатель | До | После |
|---|---|---|
| `presentation/viewer_widget.py` | 10 358 строк | 10 304 строки |
| Ссылки на `_magnifier_*` в виджете | 69 | 21 (все — вызовы владельца, ни одного поля состояния) |
| Полей состояния магнификатора в виджете | 8 | 0 |
| Реализаций геометрии линзы | 2 | 1 |
| `presentation/viewer/magnifier_controller.py` | 332 строки | 338 строк |

## 4. Тесты

- `tests/unit/test_qh3_magnifier_owner.py` (новый, 8 GUI-случаев): виджет не держит второго набора
  состояния; настройки доходят до лупы одним `configure`; выключение гасит видимую линзу; зум
  клампится владельцем; маршрутизация движения сцены вызывает владельца с `display` и `view_mapping`;
  hold/release меняют только состояние владельца; предикат «постоянной лупы» принадлежит контроллеру;
  `dispose()` идемпотентен и обнуляет линзу и флаги.
- `tests/unit/test_magnifier_trigger.py` переведён с приватных полей виджета на публичный шов
  `viewer.magnifier_controller` (сценарии Z-hold, постоянная лупа, Doppler/сосуды сохранены).
- Локальный прогон (offscreen, Python 3.11):
  `tests/unit/test_qh3_magnifier_owner.py tests/unit/test_magnifier_trigger.py` — 15 passed;
  `-k "magnifier or loupe or preferences or viewer"` в `tests/unit` — 870 passed;
  `tests/unit/test_qh3_controllers.py`, `test_qh3_viewer_composition.py`,
  `test_qh3_results_overlay_owner.py`, `test_qh3_lifecycle.py` — 59 passed.
- `ruff check` / `ruff format --check` по изменённым файлам — чисто.
- Baseline разбиения тестов обновлён штатным скриптом:
  `total 9940 → 9948, gui 3992 → 4000, gui_files 209 → 210`.

## 5. Что осталось от #420 (отдельные срезы)

1. `_controller_ref` → три узких провайдера (ROI автоматической сегментации, LA-assist ×2, слияние фаз).
2. Мёртвые владельцы: `FrameOverlay`, `DebugOverlay`, `ToolInteraction`, `ContourEditing`,
   `Calibration`, `WorkerBridge` — подключать или удалять; правка
   `test_50_cycles_controller_inventory_stable` (ожидает ровно 9 владельцев).
3. Дубль позиции оверлея результатов (`ViewerWidget._results_overlay_custom_position` против
   `ResultsOverlayController._custom_position`).

## 6. Ограничения

- Тесты выполнены на offscreen-платформе; нативная проверка Windows/macOS по этому срезу не проводилась
  (поведение клавиатуры и позиционирование линзы у курсора — то, что стоит проверить руками при
  следующей нативной приёмке).
- Ветка на момент среза не содержит изменений `main` после `094af70`; CI-прогон выполняется на PR.
