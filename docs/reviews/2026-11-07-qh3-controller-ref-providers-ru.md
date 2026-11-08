# QH-3 follow-up, срез 1: `_controller_ref` → три узких провайдера

> **Снимок на 2026-11-07.** Документ фиксирует состояние на эту дату и не обновляется вслед за кодом:
> актуальное состояние — в коде, `README.md`, HELP и открытых issues. Issue:
> [#420](https://github.com/areatu/SonoForge/issues/420). Предыдущий срез — единственный владелец
> позиции оверлея результатов (`docs/reviews/2026-11-07-qh3-results-overlay-position-owner-ru.md`), §5 п. 1.

## 1. Что было не так

`MainWindow` и `PresenterView` писали напрямую в непубличное поле виджета:

```python
self._viewer._controller_ref = self._controller          # main_window.py
viewer._controller_ref = self._host._controller            # presenter_view.py
```

Поле нигде не объявлялось и не типизировалось — оно появлялось на экземпляре только после этой
записи. `ViewerWidget` читал его обратно в четырёх местах через `hasattr(self, "_controller_ref")`:

1. `_get_last_segment_roi()` — ROI последней автоматической сегментации
   (`controller.last_segment_roi_xyxy`).
2. Условие перед вызовом LA-assist внутри `_finish_manual_contour` — «есть ли вообще куда
   обращаться» (`hasattr(...) and ... is not None`).
3. `_request_la_assist_for_manual()` — ленивая подписка на `controller.la_assist_contour_ready`
   (один раз) и сам вызов `controller.request_la_assist_for_manual(...)`.
4. `_get_fusion_result()` — результат слияния фаз (`controller.fusion_result`).

Это был непроверяемый контракт: любой `AppController`-подобный объект проходил незамеченным, опечатка
в имени атрибута превращалась в `AttributeError` только во время выполнения конкретной ветки, а тесты
не могли подставить фейковый источник без создания целого `AppController`.

## 2. Что сделано

| Решение | Где |
|---|---|
| Три явных провайдера вместо одной ссылки на контроллер: `set_last_segment_roi_provider`, `set_fusion_result_provider`, `set_la_assist_provider` | `viewer_widget.py` |
| `set_la_assist_provider(request, ready_signal)` принимает оба конца сразу — вызываемый объект для запроса и bound-сигнал для ответа; подписка на сигнал остаётся ленивой («один раз, при первом запросе»), как было | `viewer_widget.py` |
| Повторный вызов `set_la_assist_provider` сбрасывает флаг подписки — проводка больше не может «залипнуть» на сигнале прежнего контроллера | `viewer_widget.py` |
| `MainWindow`/`PresenterView` зовут провайдеры один раз при создании виджета вместо прямой записи приватного поля | `main_window.py`, `presenter_view.py` |
| Инициализация провайдеров вынесена в `ViewerWidget._init_controller_providers()`, проводка в `MainWindow._wire_viewer_controller_providers()` — оба «вне бюджета длины `__init__`» (тот же приём, что уже применялся к `_wire_gallery_signals`), чтобы не раздувать и так переразмеренные конструкторы (ретчет `check_function_length.py`) | `viewer_widget.py`, `main_window.py` |

`_get_last_segment_roi`, `_get_fusion_result`, `_on_la_assist_contour_ready` — те же приватные методы,
что и раньше, с теми же сигнатурами; контракт (`viewer_contract.py` /
`tests/architecture/viewer_contract_allowlist.json`) не менялся.

## 3. Числа

| Показатель | До | После |
|---|---|---|
| Мест, читающих `_controller_ref` через `hasattr` | 4 | 0 |
| Мест, пишущих `_controller_ref` напрямую в приватное поле виджета | 2 (`main_window.py`, `presenter_view.py`) | 0 |
| Публичных узких провайдеров на `ViewerWidget` | 0 | 3 |
| Строк в `MainWindow.__init__` / `ViewerWidget.__init__`, добавленных проводкой провайдеров | — | 1 / 1 (вынесено в отдельные методы) |

## 4. Тесты

- `tests/unit/test_qh3_controller_providers.py` — новый файл (12 GUI-случаев):
  - `_controller_ref` отсутствует на `ViewerWidget` (характеризация отсутствия моста);
  - `set_last_segment_roi_provider` / `set_fusion_result_provider`: без провайдера возвращают `None`;
    с провайдером — прокидывают значение; очистка провайдера (`None`) восстанавливает `None`;
  - `set_la_assist_provider`: запрос без провайдера — безопасный no-op (флаг подписки не трогается);
    запрос с провайдером передаёт ровно нужные именованные аргументы
    (`frame_index`, `user_septal`, `user_lateral`, `user_apex`); сигнал подключается ровно один раз при
    нескольких запросах подряд; повторная проводка (`set_la_assist_provider` второй раз) подключает
    новый сигнал, а не остаётся на старом;
  - сквозной путь `_finish_manual_contour`: завершение ручного контура LA/A4C/ES вызывает провайдер
    ровно один раз; тот же контур для LV — не вызывает вовсе (условие перенесено без изменений, но
    теперь проверено явно, а не только опосредованно).
- `ruff check` / `ruff format --check` по изменённым и новому файлам — чисто.
- Прогнаны также все локально исполнимые ретчеты репозитория (не требуют Qt/GUI, см. ограничение
  ниже): `check_test_private_access.py`, `check_test_signal.py`, `check_function_length.py`,
  `check_type_ignores.py`, `check_ui_colors.py`, `check_layer_directions.py`,
  `check_id_references.py` (базовая линия обновлена `--fix`: 676 → 675 — чистая правка убрала одно
  упоминание спек-ID), `check_doc_links.py` — все проходят.
- Базовая линия разбиения pytest обновлена вручную (`total 10178 → 10190`, `gui 4115 → 4127`,
  `gui_files 213 → 214` — один новый GUI-файл) — см. ограничение ниже.

## 5. Что осталось от #420 (отдельный срез)

1. Мёртвые владельцы: `FrameOverlayController`, `DebugOverlayController`, `ToolInteractionController`,
   `ContourEditingController`, `CalibrationController`, `WorkerBridge` — подключать или удалять;
   правка `test_50_cycles_controller_inventory_stable` (ожидает ровно 9 владельцев).

## 6. Ограничения

- **В этой песочнице не было возможности запустить набор GUI-тестов**: нет `libGL`/`libEGL`/X11-стека,
  а сеть ограничена `github.com`/`pypi.org`/`npmjs.org` — установить системные библиотеки (`apt`) или
  собрать их из исходников не получилось. Проверка ограничилась `ruff check`, `ruff format --check`,
  всеми локально исполнимыми AST-ретчетами репозитория и построчным прослеживанием кода (каждый вызов
  удалённых методов и каждое поле найдены через `grep` по всему `src/`, типовые значения для
  `fit_contour_from_landmarks` в новых тестах взяты из уже существующего `test_la_assist_integration.py`,
  чтобы не гадать с координатами). Базовая линия pytest-партиции посчитана вручную, а не скриптом
  `update_pytest_baseline.py --fix`. **CI обязателен для подтверждения** — это не замена прогону, а
  честная фиксация того, что было и не было проверено локально.
- Нативная проверка Windows/macOS по этому срезу не проводилась (как и у предыдущих срезов).
