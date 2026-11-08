# QH-3 follow-up, срез 2 (часть 1): удаление мёртвых оверлей-владельцев

> **Снимок на 2026-11-08.** Документ фиксирует состояние на эту дату и не обновляется вслед за кодом:
> актуальное состояние — в коде, `README.md`, HELP и открытых issues. Issue:
> [#420](https://github.com/areatu/SonoForge/issues/420). Предыдущий срез — `_controller_ref` → узкие
> провайдеры (`docs/reviews/2026-11-07-qh3-controller-ref-providers-ru.md`), §5 п. 2. Источник
> инвентаризации — `docs/reviews/2026-11-05-qh-3-bridge-inventory-ru.md` §2 и §5 п. 3.

## 1. Что было не так

`ViewerWidget._all_qh3_controllers` регистрировал 9 владельцев ради единого fan-out `set_context`/
`dispose` и ради счётчика в `test_50_cycles_controller_inventory_stable`. Из них 6 не вызывались
виджетом ни разу за пределами конструктора. Для двух — `FrameOverlayController` и
`DebugOverlayController` — это была полная мертвечина: ни одного теста, ни одного внешнего вызова,
ни одной ссылки где-либо в `src/`, кроме создания и регистрации.

Реальное поведение всё это время жило прямо в `ViewerWidget`:

- калибровочный баннер / «авто-ОК» / построчный текст по кадру в левом верхнем углу управлялся
  напрямую через `self._overlay_label` (видимость, текст, позиционирование — всё инлайн в `ViewerWidget`);
- диагностический оверлей (размер вьюпорта, масштаб, ROI) — через `self._debug_overlay_label` и
  отдельный флаг `self._debug_overlay_visible`, тоже инлайн.

`FrameOverlayController`/`DebugOverlayController` держали ровно такую же логику (`append`/`_refresh`/
`_position`, `toggle`/`update_text`) — вторую, нигде не используемую копию, которая существовала только
чтобы быть посчитанной в lifecycle-инвентаре.

Остальные четыре «мёртвых в виджете» владельца — `ToolInteractionController`, `ContourEditingController`,
`CalibrationController`, `WorkerBridge` — качественно другой случай: у них есть полноценное
протестированное поведение как отдельных модулей (`tests/unit/test_qh3_controllers.py`, QH-3.2 / #185),
просто `ViewerWidget` его не использует. «Подключить или удалить» для них требует отдельного решения
по каждому — см. §4.

## 2. Что сделано

| Решение | Где |
|---|---|
| Классы `FrameOverlayController` и `DebugOverlayController` удалены целиком | `presentation/viewer/overlay_controller.py` |
| Экспорт обоих классов убран из публичного API пакета | `presentation/viewer/__init__.py` |
| Конструирование (`self._frame_overlay_controller = …`, `self._debug_overlay_controller = …`) и их записи в `_all_qh3_controllers` удалены; импорт сужен до `ResultsOverlayController`, `TagsOverlayController` | `presentation/viewer_widget.py` |
| Единственный стандалон-тест на `FrameOverlayController` (`test_frame_overlay_append_and_clear`) удалён вместе с импортом класса; `DebugOverlayController` тестов не имел | `tests/unit/test_qh3_viewer_composition.py` |
| Счётчики владельцев обновлены 9 → 7 в обоих местах; добавлена явная проверка, что удалённые имена отсутствуют в инвентаре (а не просто «тест не упал по случайности») | `tests/unit/test_qh3_lifecycle.py` |

Поведение `self._overlay_label` и `self._debug_overlay_label`/`self._debug_overlay_visible` не менялось —
это была и осталась прямая логика `ViewerWidget`, которую контроллеры никогда не замещали.

## 3. Числа

| Показатель | До | После |
|---|---|---|
| Владельцев в `_all_qh3_controllers` | 9 | 7 |
| Строк в `presentation/viewer/overlay_controller.py` | 303 | ~225 |
| Длина `ViewerWidget.__init__` (ретчет `check_function_length.py`) | 436 | 425 |
| GUI-тестов, упоминающих удалённые классы | 1 (`test_frame_overlay_append_and_clear`) | 0 |

## 4. Что осталось от #420

Четыре «мёртвых в виджете», но протестированных как отдельные модули владельца —
`ToolInteractionController`, `ContourEditingController`, `CalibrationController`, `WorkerBridge` — **не
решены в этом срезе**. Удалить их означало бы выбросить рабочую, протестированную логику QH-3.2 (#185);
подключить — значит переписать реальные пути мыши/инструментов/контуров/калибровки/воркеров в
`ViewerWidget` на делегирование этим контроллерам, то есть крупный рискованный рефакторинг живого
поведения, который нельзя проверить в этой песочнице (нет GUI-прогона). Решение по каждому из четырёх —
отдельный issue с явным выбором «подключить или удалить»: [#466](https://github.com/areatu/SonoForge/issues/466).

## 5. Тесты

- `tests/unit/test_qh3_lifecycle.py` — `test_controllers_are_owner_scoped_and_dispose_is_idempotent` и
  `test_50_cycles_controller_inventory_stable` обновлены на 7 владельцев; первая дополнительно проверяет
  отсутствие `"FrameOverlayController"`/`"DebugOverlayController"` в `qh3_controller_inventory()`.
- `tests/unit/test_qh3_viewer_composition.py` — `test_frame_overlay_append_and_clear` удалён вместе с
  неиспользуемым импортом; `test_tags_overlay_show_hide` (соседний живой контроллер) не затронут.
- `ruff check src tests` — чисто.
- Прогнаны все локально исполнимые ретчеты репозитория: `check_function_length.py` (база обновлена:
  `ViewerWidget.__init__` 436 → 425), `check_ui_colors.py` (ложное срабатывание на `#420` внутри
  docstring — литерал похож на 3-значный hex-цвет; переписано как «issue 420» по образцу остального
  кода), `check_doc_links.py`, `check_id_references.py`, `check_layer_directions.py`,
  `check_test_private_access.py`, `check_test_signal.py` (9617 → 9616 тестов), `check_type_ignores.py`,
  `check_typecheck_matrix.py` — все проходят.
- Базовая линия разбиения pytest обновлена вручную (`total 10294 → 10293`, `gui 4134 → 4133`,
  `gui_files` без изменений — файл не удалялся, одна функция внутри него) — см. ограничение ниже.

## 6. Ограничения

- **В этой песочнице не было возможности запустить набор GUI-тестов**: нет `libGL`/`libEGL`/X11-стека, а
  сеть ограничена `github.com`/`pypi.org`/`npmjs.org`. Проверка ограничилась `ruff check`, всеми локально
  исполнимыми AST-ретчетами репозитория и построчным прослеживанием кода (каждая ссылка на оба удалённых
  класса найдена через `grep -rn` по всему репозиторию, включая `.py` и `.md`, до и после правки).
  Базовая линия pytest-партиции посчитана вручную, а не скриптом `update_pytest_baseline.py --fix`.
  **CI обязателен для подтверждения.**
- Нативная проверка Windows/macOS по этому срезу не проводилась (как и у предыдущих срезов).
