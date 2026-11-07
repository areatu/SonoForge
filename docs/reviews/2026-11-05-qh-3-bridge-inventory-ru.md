# QH-3 follow-up: инвентаризация мостов и обязанностей ViewerWidget

> **Снимок на 2026-11-05.** Документ фиксирует состояние на эту дату. Актуальное состояние —
> в коде и в `ROADMAP.md`. Issue: [#420](https://github.com/areatu/SonoForge/issues/420).
> Граница владельцев (что остаётся в `ViewerWidget`, что уходит в контроллеры) —
> `src/echo_personal_tool/presentation/viewer/target_boundary.py`.

## 1. Что измерено

Методика воспроизводима grep/AST-проходом по `src/echo_personal_tool` и `tests/`.

| Показатель | Значение |
|---|---|
| `presentation/viewer_widget.py` | ~10 358 строк |
| `presentation/main_window.py` | ~6 981 строк |
| Члены `ViewerWidget`, к которым обращаются файлы вне `viewer_widget.py` | 140 (в основном `MainWindow` и `presenter_view`) |
| Владельцы, зарегистрированные в `_all_qh3_controllers` | 9 |
| Из 9 — реально вызываются виджетом вне конструктора и регистрации | 3 (`ResultsOverlayController`, `MagnifierController`, `TagsOverlayController`), и то частично |
| Владельцы без вызовов из виджета (только создание и регистрация) | 6 (см. таблицу §2) |
| Места `hasattr(self, "_…controller")` внутри `ViewerWidget` | 3 |
| Функции `ViewerWidget`, читающие `self._controller_ref` | 4 (+2 места установки извне) |

## 2. Владельцы: кто что реально делает

| Владелец | Связь из `ViewerWidget` | Тесты | Состояние |
|---|---|---|---|
| `ResultsOverlayController` | `apply_style`, `is_pinned`; позиция/текст ведёт сам виджет | `test_qh3_*` | **Мост закрыт этим срезом** (`is_pinned`). Остаётся дубль `_custom_position` и логики репозиционирования, которую виджет не вызывает. |
| `MagnifierController` | `configure(...)` — копия `enabled/zoom/linear_persistent/reduce_motion` | `test_qh3_viewer_composition` | **Параллельный источник истины**: виджет держит свои `_magnifier_*` (≈20 строк обращений), контроллер — вторую копию. |
| `TagsOverlayController` | только `apply_style` | — | Частично: показ тегов ведёт виджет. |
| `FrameOverlayController` | нет | нет | Мёртвый владелец. |
| `DebugOverlayController` | нет | нет | Мёртвый владелец. |
| `ToolInteractionController` | нет | `test_qh3_controllers` | Мёртвый в виджете; тестируется изолированно. |
| `ContourEditingController` | нет | `test_qh3_controllers` | Мёртвый в виджете; тестируется изолированно. |
| `CalibrationController` | нет | `test_qh3_controllers` | Мёртвый в виджете; тестируется изолированно. |
| `WorkerBridge` | нет | `test_qh3_lifecycle` | Мёртвый в виджете. |

Вывод: фактическая логика живёт в `ViewerWidget`, а контроллеры либо дублируют её, либо не подключены.
Тест `test_50_cycles_controller_inventory_stable` ожидает ровно 9 владельцев, поэтому удаление мёртвых
владельцев — отдельный срез с обновлением этого теста.

## 3. Мосты (пересылка через виджет)

| Мост | Внешние вызовы | Статус |
|---|---|---|
| `ViewerWidget.is_results_overlay_pinned()` → `controller.is_pinned()` → `label._pinned` | 2 в `MainWindow` | **Удалён в этом срезе.** Вызовы переведены на `viewer.results_overlay_controller.is_pinned()`; контроллер читает публичный `pinned`, а не приватное `_pinned`. |
| `viewer._controller_ref` (ссылка на контроллер приложения) | `main_window.py` (установка), `presenter_view.py` (установка); чтение — 4 функции `ViewerWidget` (ROI автоматической сегментации, LA-assist ×2, слияние фаз) | **Открыт.** Следующий кандидат: заменить на явные узкие провайдеры, передаваемые извне. |
| `_all_qh3_controllers` (fan-out `set_context` и `dispose`) | внутренний | Существует только ради мёртвых владельцев; уйдёт вместе с ними. |

## 4. Что сделано в этом срезе

1. `ResultsOverlayController.is_pinned()` читает публичное свойство `ResultsOverlayLabel.pinned`
   (issue 327 seam) вместо приватного `_pinned`.
2. Из `ViewerWidget` удалён `is_results_overlay_pinned()` вместе с веткой «legacy fallback».
   Вместо него — только для чтения свойство `results_overlay_controller`, возвращающее владельца.
3. `MainWindow` (два места) переведён на `self._viewer.results_overlay_controller.is_pinned()`.
4. Тесты: `tests/unit/test_qh3_results_overlay_owner.py` — характеризация состояния закрепления
   (контроллер, обычный `QLabel`, отсутствие моста, поведение `MainWindow` с закреплением и без).

Поведение не меняется: `is_pinned()` возвращает то же значение, что и раньше.

## 5. Следующие срезы (отдельные issues после согласования)

1. **~~Магнитный лупа: один источник истины.~~ Сделано 2026-11-06** — контроллер стал единственным
   владельцем состояния, линзы и геометрии; виджет держит 0 полей состояния. Доказательства:
   `docs/reviews/2026-11-06-qh3-magnifier-owner-ru.md`, `tests/unit/test_qh3_magnifier_owner.py`.
2. **`_controller_ref` → узкие провайдеры.** Заменить ссылку на контроллер приложения на три явных
   callable (ROI, LA-assist, слияние) с тестами на каждый провайдер.
3. **Удаление мёртвых владельцев.** `FrameOverlay`, `DebugOverlay`, `Tool`, `Contour`, `Calibration`,
   `WorkerBridge` — либо подключить, либо удалить; обновить `test_50_cycles_controller_inventory_stable`.
4. **Дубль позиции результатов.** `ViewerWidget._results_overlay_custom_position` и
   `ResultsOverlayController._custom_position` — оставить одного владельца.

## 6. Ограничения

- Метрики — оценка по регулярным выражениям и AST; число внешних вызовов может отличаться на единицы.
- Тесты гоняются на offscreen-платформе; нативная проверка Windows/macOS по этому срезу не проводилась.
