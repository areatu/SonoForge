# S-02 и дальнейшая работа: план для следующей сессии

> **Снимок на 2026-11-12.** Документ фиксирует состояние на эту дату и не обновляется вслед за кодом: актуальное состояние — в коде, `README.md`, HELP и открытых issues.

> **Назначение.** Самодостаточная записка для переноса контекста в новую сессию/PR: что уже сделано, какие решения зафиксированы, что делать дальше и в каком порядке. Состояние на 2026-11-12. Актуальный код важнее этого текста.

## 1. Где мы находимся

- Срез **S-02 / tab memory** реализован и оформлен: issue [#510](https://github.com/areatu/SonoForge/issues/510), PR [#511](https://github.com/areatu/SonoForge/pull/511), ветка `arena/7a002d97-sonoforge` (от `39cd49b`), коммиты `231e8ff` (код) и `5f64bdc` (HELP + два теста).
- Владелец значений вкладки — `application/tab_clinical_memory.py` (`TabClinicalMemory`): снимок `StudyMeasurementData` по каждому исследованию вкладки, ручные `calculator inputs`, cine HR estimate.
- `TabSession.clinical_memory` — единственное место хранения снимка. Ключ — **вкладка**, не `study_uid`: одно исследование в двух вкладках не делит значения.
- `TabCoordinator`: `park_active` паркует снимок при уходе; `load_content` отдаёт его обратно; флаг `restoring_parked_tab` не даёт `finish_load` стереть снимок при возврате (в т.ч. после закрытия активной вкладки и выхода из сравнения). Новый источник в той же вкладке (`not is_switch`) снимок сбрасывает.
- `AppController.snapshot_tab_clinical_memory()` возвращает `None` при включённой persistence; `_restore_measurement_studies(clinical_memory)` применяет снимок только при выключенной persistence. Диск остаётся источником истины.
- Тесты: `tests/unit/test_s02_tab_isolation.py` — 7 контроллерных сценариев; `tests/unit/test_tab_clinical_memory.py` — 6 изолированных; `tests/unit/test_tab_coordinator.py` — 4 сценария памяти (park/adopt, запрет воскрешения, очистка новым источником, возврат при закрытии).
- Ratchet'ы после среза: `AppController` 4 339 → **4 337** строк (167 методов, 88 полей; модуль 4 525 → 4 524), приватные обращения тестов к контроллеру 539 → **530**, ID-ссылки 642 → **641**, test-signal: 0 тестов без сигнала, mypy presentation 833/833, untranslated 0.
- HELP_RU/HELP_EN §2.6 описывают новое поведение: значения вкладки живут в её памяти и возвращаются A→B→A; закрытие память освобождает; при автосохранении работает хранилище по UID.

**Важно:** локальные прогоны — offscreen Qt со стабами системных библиотек (`tools/qtstub`). Это не нативная приёмка Qt, не клиническая валидация и не основание закрывать issue как «проверено нативно».

## 2. Правила, которые нельзя нарушать

1. **Одно владение состоянием.** Новый срез выбирается по критерию «кто владеет состоянием», а не по префиксу имён или ключевым словам.
2. **Узкий неизменяемый порт.** Зависимость передаётся как данные/протокол; класс себя в чужой слой не передаёт. Без мостов совместимости и без service locator в `MainWindow`/`AppController`.
3. **Перемещение методов — не декомпозиция.** Срез принимается, только если у состояния появился один владелец и это видно по тестам.
4. **Ratchet'ы только вниз:** `check_class_size`, `check_test_private_access`, `check_mypy_presentation`, `check_test_signal`, `check_id_references`, `check_broad_excepts`. Рост означает переделку, а не новый baseline.
5. **Тесты изолированные**, без `MainWindow` там, где проверяется последовательность (пример — `test_tab_coordinator.py` с `FakeWindow`); Qt-тесты помечаются `gui`.
6. **Каждый срез:** changelog-фрагмент `changelog.d/NNN-*.md` + строка в индексе `Unreleased` в `CHANGELOG.md`, HELP при пользовательском изменении, review-записка при архитектурном.
7. **Решения владельца ≠ evidence.** Не заявлять клиническую валидацию, нативный GUI-прогон или закрытие issue по stub/offscreen-проверкам.

## 3. Рекомендуемый порядок работ

### S-02a. Восстановление вкладки после сорванного переключения — **сделано** ([#512](https://github.com/areatu/SonoForge/issues/512))

**Проблема.** Если переключение не удалось (`abort_load` после исключения или синхронного отказа контроллера), координатор возвращает активной прежнюю вкладку, но не перезагружает её. Контроллер при этом уже прошёл `_begin_study_switch`, то есть очистил значения; снимок прежней вкладки лежит в `TabSession.clinical_memory`, но пользователь увидит его только при следующем успешном переключении. Это единственная известная дыра в только что введённом контракте, и проявляется она именно в аварийном сценарии.

**Подход.**
- В `abort_load` после отката активной вкладки перезагрузить её так же, как это делает `switch_to`, но без повторного `park_active`: `load_content(previous_tab)`. Защититься от рекурсии явным флагом (`restoring_after_abort`), потому что `load_content` сам может упасть.
- Не менять контроллер, если отказал `flush()` до `_begin_study_switch` — там состояние ещё цело.
- Если отказ пришёл из контроллера синхронно (`load_pre_scanned_studies` вернулся без загрузки), не активировать целевую вкладку вовсе.

**Тесты.**
- `test_abort_reloads_the_previous_tab_with_its_memory` (координатор, `FakeWindow`): прежняя вкладка получает `clinical_memory` и её клип снова выбран.
- `test_refused_switch_keeps_the_previous_values` (реальный `AppController`, persistence off): после отказа ручная калибровка/BSA видны без второго переключения.
- Негативный тест на рекурсию: падение уже при восстановлении не оставляет `loading_tab_id` и флаг.

**Риск:** средний — путь ошибок загрузки, легко потерять маркер загрузки. Держать изменения в `tab_coordinator.py` и одном выходе контроллера.

**Сделано.** `load_pre_scanned_studies` возвращает `bool` (`False` — отказ `flush()` до изменения состояния). `load_content`/`switch_to` возвращают `False` при отказе: вкладки откатываются, прежняя остаётся на экране со значениями, повторной загрузки нет. Исключение после старта загрузки перезагружает прежнюю вкладку её снимком (`_restore_aborted_tab`), флаг `_restoring_after_abort` исключает цикл. Ограничение: асинхронный отказ при включённом автосохранении рекаверится диском на следующем успешном переключении. Разбор: [2026-11-12-s02a-aborted-switch-ru.md](2026-11-12-s02a-aborted-switch-ru.md).

### S-02b. Граница «состояние вкладки»: FPS-правка и strain — P1, ~1 день

**Проблема.** В снимок не входят два вида состояния:
- `AppController._frame_time_overrides` — ручная правка частоты кадров, влияет на тайминги измерений; сейчас теряется при переключении.
- `_strain_studies` — кэш выполненных strain-расчётов; очищается в `_begin_study_switch`, хотя сам результат лежит в `StudyMeasurementData.strain`.

**Предложение.**
- **FPS-правки парковать с вкладкой.** Расширить `TabClinicalMemory` полем `frame_time_overrides: dict[str, float]` (ключ — `instance_uid` или составной `(study_uid, instance_uid)`), добавить узкий метод контроллера «применить правки» и учесть их в `has_measurements` только если они меняют клинический результат (обсудить с владельцем — см. §5).
- **Strain не парковать как кэш.** Результат уже в DTO; при возврате в вкладку пересчитывать/переиспользовать из снимка при выборе клипа. Тест должен утверждать одинаковые числа strain после A→B→A, а не факт наличия кэша.

**Тесты.**
- FPS: A задаёт 40 мс → B → A: значение применяется и участвует в расчёте.
- При persistence on FPS-правки по-прежнему не паркуются (`snapshot_tab_clinical_memory() is None`).
- Strain: результат после возврата совпадает с исходным; без клипа strain-оверлей не появляется.

**Риск:** средний. Правки FPS могут быть частью сохранённой записи — это вопрос формата DTO и обратной совместимости, поэтому сначала решение владельца, потом код.

### QH-0. Characterization harness для `ViewerWidget` — P2, ~2–3 дня

**Зачем.** `ViewerWidget` — 7 972 строки, 427 методов, 198 полей. Любая экстракция без «снимка поведения» недоказуема: тесты будут проверять новую структуру, а не сохранённое поведение.

**Что сделать.**
- Набор characterization-тестов на текущем коде (без рефакторинга): какие сигналы и в каком порядке эмитятся при выборе инструмента, клике, смене кадра, старте/остановке cine, смене window/level; что попадает в `state_manager`; какие пункты контекстного меню доступны.
- Каждый тест должен уметь падать (test-signal ratchet это проверяет); фиксировать не внутренние поля, а наблюдаемый контракт.
- Прогнать harness на трёх ОС через CI `test-gui`-шарды до начала экстракции.

**Только после QH-0** — по одному PR на кластер, в порядке возрастания риска:
1. frame/transport — 17 методов / 217 строк / 45 полей;
2. display/lut — 13 / 251 / 31;
3. zoom/pan — 20 / 231 / 32;
4. label picker — 33 / 483 / 64;
5. контурный owner — 90 / 1 703 / 143 (последним: у него больше всего клинически значимого состояния).

**Запрещено:** тащить несколько кластеров в один PR; вводить «менеджеры» без владения состоянием; оставлять дублирующее состояние в `ViewerWidget` «на время».

### S-03. Следующий owner-срез в application-слое — P2, оценка после выбора

Продолжать только там, где состояние меняет владельца. Кандидаты (размеры — из `scripts/class_size_baseline.json`):
- `OrthancStudyDialog` — 2 601 строка, 153 метода: владение состоянием загрузки/выбора исследований;
- `ToolPanelV2` — 1 861 / 117;
- `DopplerOverlayTools` — 1 671 / 126;
- `MainWindow` overlay — 2 метода / 32 строки / 6 полей (мал, но изолируем).

Перед началом — review-записка с ответом: какое состояние сейчас имеет двух владельцев, кто останется единственным, какие тесты докажут перенос. Если ответа нет, срез не начинать.

### Постоянная линия: верификация и риск teardown — P2, фоном

- Перед каждым merge: `pytest tests/unit -q` и `.github/scripts/verify_pytest_partition.py`; локально — только offscreen + `tools/qtstub`.
- Известный риск вне декомпозиции: Qt lifecycle segfault в teardown (PR #507, run 43018455360). Мониторить, не «чинить» переносом кода.
- Нативная приёмка Windows/macOS — за владельцем; CI `build-*` и `test-gui-smoke` её не заменяют.

## 4. Definition of done для любого среза

- [ ] У состояния один владелец; зависимость — узкий порт, класс себя не передаёт.
- [ ] Изолированные тесты на новое поведение + негативный сценарий; все тесты могут падать.
- [ ] `ruff check`/`format`, mypy (strict для `application`), все ratchet-скрипты зелёные и baseline'ы не выросли.
- [ ] changelog-фрагмент + строка в `CHANGELOG.md`; HELP обновлён, если меняется поведение пользователя.
- [ ] В PR написано, что **не** проверено (нативный GUI, клиника), и какие ограничения остались.

## 5. Открытые вопросы владельцу (блокируют соответствующие срезы)

1. **Граница снимка.** Полный `StudyMeasurementData` (сделано) или только калибровка + BSA? Если только калибровка/BSA — контуры, допплер и manual inputs придётся вынести из снимка, это упростит S-02a/S-02b, но ухудшит A→B→A.
2. **FPS-правка — клиническое состояние?** Парковать в памяти вкладки и/или сохранять на диск? От этого зависит формат записи и совместимость.
3. **UX сорванного переключения:** молча вернуть прежнюю вкладку с её значениями или показать статус «переключение отменено, значения восстановлены»?
4. **Strain:** допустим ли пересчёт при возврате в вкладку (может быть заметная задержка) вместо хранения кэша?

## 6. Как начать новую сессию

```bash
# окружение (не сохраняется между сессиями)
python -m pip install pytest pytest-qt pyside6 numpy pydicom psutil opencv-python-headless \
  scipy pyqtgraph pyyaml reportlab openpyxl httpx pymupdf ruff pynetdicom jsonschema keyring pytest-timeout mypy types-PyYAML
CI=1 python tools/qtstub/mkstub.py

# тесты
PYTHONPATH=src LD_LIBRARY_PATH=tools/qtstub/lib QT_QPA_PLATFORM=offscreen \
  python -m pytest tests/unit/test_s02_tab_isolation.py tests/unit/test_tab_coordinator.py -q

# ratchet'ы
python -m ruff check src tests && python -m ruff format --check src tests
for s in check_class_size check_test_private_access check_test_signal check_id_references \
         check_broad_excepts check_doc_links check_untranslated_ui_strings check_ui_colors; do
  python scripts/$s.py || exit 1
done
python scripts/check_mypy_presentation.py

# PR
gh pr checks <N>; gh pr merge <N> --merge
```

**Ключевые файлы:** `application/tab_clinical_memory.py`, `application/tab_session.py`, `application/app_controller.py` (`snapshot_tab_clinical_memory`, `_begin_study_switch`, `_restore_measurement_studies`, `_frame_time_overrides`), `presentation/tab_coordinator.py` (`park_active`, `load_content`, `finish_load`, `abort_load`), тесты `test_s02_tab_isolation.py`, `test_tab_clinical_memory.py`, `test_tab_coordinator.py`.

**Чего не делать:** не возвращать `_adopt_loaded_manual_bsa` и обходы через `measurement_persistence.loaded`; не добавлять keyword-only параметры в `TabClinicalMemory.capture/restore_into` (вызовы позиционные); не трогать `ViewerWidget` до QH-0; не заявлять нативную/клиническую проверку по offscreen-прогону.
