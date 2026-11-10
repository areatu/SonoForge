# QH-3 follow-up (#466): удаление четырёх неподключённых владельцев из `presentation/viewer`

> **Снимок на 2026-11-10.** Документ фиксирует состояние на эту дату и не обновляется вслед за кодом: актуальное состояние — в коде, `README.md`, HELP и открытых issues.

Задача: `#466` (продолжение `#420` / `docs/reviews/2026-11-08-qh3-dead-overlay-owners-removed-ru.md`).

## 1. Контекст и принятое решение

После удаления `FrameOverlayController` и `DebugOverlayController` в `#420` в `ViewerWidget._all_qh3_controllers` оставались четыре класса из среза QH-3.2 (`#185`):

- `ToolInteractionController` (`presentation/viewer/tool_controller.py`)
- `ContourEditingController` (`presentation/viewer/contour_controller.py`)
- `CalibrationController` (`presentation/viewer/calibration_controller.py`)
- `WorkerBridge` / `WorkerToken` (`presentation/viewer/worker_bridge.py`)

`ViewerWidget` создавал их в `__init__` и рассылал им `set_context()` / `dispose()`, но **ни один** рабочий путь мыши, контуров, калибровки или фоновых воркеров на них не делегировал — вся реальная логика оставалась инлайн в `ViewerWidget`, а реальная декомпозиция пошла по пути узких доменных контроллеров с явными портами (`MModeController` в `#479` с `MModeViewerPort`).

Принято явное решение владельца по всем четырём классам: **удалить владельцев и их модульные тесты**, устранив дублирование ответственности и фиктивный fan-out в `_all_qh3_controllers`.

## 2. Что изменено

| Изменение | Файлы |
|---|---|
| Удалены 4 неподключённых модуля | `src/echo_personal_tool/presentation/viewer/{tool_controller,contour_controller,calibration_controller,worker_bridge}.py` |
| Удалён изолированный набор тестов удалённых классов | `tests/unit/test_qh3_controllers.py` |
| Убраны реэкспорты и строки контракта удалённых классов | `src/echo_personal_tool/presentation/viewer/{__init__,target_boundary}.py` |
| Удалены поля `_tool_controller`, `_contour_controller`, `_calibration_controller`, `_worker_bridge` из `ViewerWidget`; `_all_qh3_controllers` сокращён до 3 реально подключённых контроллеров (`ResultsOverlayController`, `TagsOverlayController`, `MagnifierController`) | `src/echo_personal_tool/presentation/viewer_widget.py` |
| Актуализированы комментарии кнопок панели инструментов | `src/echo_personal_tool/presentation/tool_buttons/{base,buttons}.py` |
| Обновлены проверки экспорта пакета и lifecycle-инвентаря (`7 → 3`, включая `test_50_cycles_controller_inventory_stable`) с явной проверкой отсутствия всех 6 удалённых владельцев | `tests/unit/test_qh3_boundary.py`, `tests/unit/test_qh3_lifecycle.py` |
| Понижены потолки ретчетов размера класса/функции и строгой типизации | `pyproject.toml`, `scripts/{class_size,function_length,id_references,mypy_presentation,broad_except}_baseline.json` |
