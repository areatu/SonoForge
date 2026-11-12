# S-02 — память вкладки: калибровка, BSA и измерения

> **Снимок на 2026-11-12.** Документ фиксирует состояние на эту дату и не обновляется вслед за кодом: актуальное состояние — в коде, `README.md`, HELP и открытых issues.

Основание: решение владельца от 2026-11-10 — при выключенном автосохранении ручная калибровка и BSA живут в памяти исходной вкладки, не переносятся между вкладками и не пишутся на диск ([решения](2026-11-10-160-owner-decisions-ru.md), [риски](2026-11-10-risk-and-owner-questions-ru.md)). Реализация: issue [#510](https://github.com/areatu/SonoForge/issues/510). База кода — `39cd49b`; это не клиническая валидация и не нативная приёмка Qt.

## Что было сломано

Переключение вкладки идёт тем же путём, что и новая загрузка: `TabCoordinator.load_content` → `AppController.load_pre_scanned_studies`. Внутри `_begin_study_switch` очищал `self._calculator_inputs`, а `_restore_measurement_studies` вызывал `self._measurement_session.clear()`. При выключенном автосохранении `MeasurementPersistence.load()` сразу вызывает callback и ничего не восстанавливает, поэтому терялись:

- ручная калибровка (spacing по кадру и `manual_pixel_spacing` состояния);
- ручной BSA и остальные manual calculator inputs;
- контуры, линейные и сосудистые измерения, Doppler DTO, M-mode/Doppler-калибровки;
- cine-оценка ЧСС (в DTO не хранится).

При включённом автосохранении значения возвращались с диска, поэтому дефект проявлялся только в профиле без локального хранения. Прежний `test_s02_tab_isolation.py` закреплял именно потерю: после A→B→A он ожидал `None`.

Узкая формулировка решения (калибровка + BSA) закрыла бы меньшую часть риска: тот же `clear()` уносил и измерения. Срез владеет целым снимком сессии, а калибровка и BSA остаются обязательным минимумом приёмки.

## Владелец и граница

`application/tab_clinical_memory.py` — Qt-free владелец значений вкладки:

- `TabClinicalMemory` хранит `StudyMeasurementData` по каждому исследованию, `manual_inputs` и cine `heart_rates`;
- `capture()` делает deep copy через существующий `StudyMeasurementSessionStore.snapshot()`;
- `restore_into()` возвращает DTO в store, manual inputs — в `CalculatorInputStore`, ЧСС — через `set_hr_estimate`;
- `adopt_loaded_bsa()` — прежний `_adopt_loaded_manual_bsa`, вынесенный из `AppController` в тот же модуль (источник — загруженные с диска записи).

`TabSession.clinical_memory` — единственная ссылка на снимок. Ключ — **вкладка**, не `study_uid`: одно исследование может быть открыто в двух вкладках, и общий кеш по UID смешал бы их значения. Снимок живёт только в памяти и умирает вместе с вкладкой.

Поток:

1. `TabCoordinator.park_active` берёт `AppController.snapshot_tab_clinical_memory()`, кладёт в `tab.clinical_memory`, обновляет `tab.has_measurements`.
2. `TabCoordinator.load_content` передаёт `clinical_memory` в `load_pre_scanned_studies`.
3. `AppController._restore_measurement_studies` очищает store, восстанавливает снимок и только затем публикует `studies_loaded`; `load_instance` сам поднимает spacing и контуры из store.
4. Новый источник в той же вкладке (`open_folder`, батч PACS, повторная загрузка) идёт без снимка и начинает пусто.
5. `snapshot_tab_clinical_memory()` возвращает `None` при включённой persistence: диск — источник истины, RAM-копия не создаётся. `_restore_measurement_studies` игнорирует снимок в этом режиме.

## Поведение и проверка

Сценарии в `tests/unit/test_s02_tab_isolation.py` (контроллер, fake-воркеры, без `QMainWindow`):

- A→B не переносит калибровку, BSA, контуры;
- A→B→A возвращает калибровку, BSA, контуры и HR estimate;
- одно исследование в двух вкладках хранит разные значения;
- новая папка в той же вкладке начинает пусто;
- при persistence on снимок не паркуется.

`tests/unit/test_tab_clinical_memory.py` — изолированные проверки deep copy, restore, `has_measurements` (калибровка без измерений — не измерение), восстановления BSA из DTO и только для загруженных записей.

`tests/unit/test_tab_coordinator.py` — park кладёт снимок и возврат отдаёт его в `load_pre_scanned_studies`; park без снимка не воскрешает старую память; новый источник в той же вкладке сбрасывает снимок, а возврат из закрытия/сравнения его сохраняет.

Регрессия: `test_main_window_tabs.py` (реальный `MainWindow`, offscreen), `test_measurement_controller*.py`, `test_measurement_cache_compatibility.py`, `test_controller_calculators.py`, `test_bsa_*`. Ratchet'ы: `AppController` 4 339 → 4 337 строк (методы 167, поля 88; модуль 4 525 → 4 524), приватные обращения тестов к контроллеру 539 → 530, ID-ссылки 642 → 641; baseline'ы понижены. mypy strict по `application` чист, ratchet presentation — 833/833.

## Ограничения и остаток

- **`abort_load`.** Если загрузка падает до публикации набора, вкладка-источник не перезагружается; её снимок остаётся в `TabSession` и будет принят при следующем успешном переключении, но текущая поверхность остаётся без измерений. Прежнее поведение не ухудшено; отдельный срез не заявлен.
- **Включённая persistence.** Путь с диска не менялся: снимок не паркуется, конфликт RAM/диска разрешается существующим механизмом. `adopt_loaded_bsa` вызывается как раньше.
- **Память процесса.** Снимок хранит DTO до 8 вкладок; пиксели не копируются, но контуры/Doppler занимают память, пока вкладка открыта. Освобождение — при закрытии вкладки.
- **Не входит.** Владение контурами внутри `ViewerWidget` (отдельный QH-3 срез), формат хранения на диске, `strain`-состояние вне DTO, нативная проверка Qt lifecycle.
- **Проверка.** GUI-тесты запускались offscreen в Linux с библиотечными заглушками `tools/qtstub`; реальный GL, Windows/macOS и полный набор не проверялись. CI-результат — в PR.
