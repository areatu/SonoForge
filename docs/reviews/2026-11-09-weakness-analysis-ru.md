# Анализ слабых сторон SonoForge: механизмы, а не симптомы

> **Снимок на 2026-11-09.** Документ фиксирует состояние на эту дату и не обновляется вслед за кодом:
> актуальное состояние — в коде, `README.md`, HELP и открытых issues (метка `audit-2026-11`).

**База:** `main` @ `9984977` (v0.4.0), ветка анализа `arena/76c7b5a0-sonoforge`
**Тип документа:** инженерный анализ по коду, CI и истории git (не сертификация, не клиническая валидация)
**Повод:** внешний «комплексный аудит» от 2026-11-09 (оценка 7.8/10). Его утверждения сверены с кодом в §1;
собственные находки — в §2.

---

## 0. Границы достоверности

Что **реально запускалось**:

| Проверка | Результат |
|---|---|
| `mypy` с конфигурацией CI (mypy 2.4.1, PySide6 6.11.3, numpy, pydicom, opencv по `uv.lock`) | основной набор: `no issues found in 270 source files` |
| тот же `mypy` strict на `ui` / `constructor` / `presentation` | **31 / 25 / 1 229** ошибок в собственных файлах слоя |
| `python scripts/check_layer_directions.py` | 29 import'ов в 25 рёбрах, без новых/выросших |
| AST-инвентарь классов, методов, `self.*`-полей, `except` | §2 |
| История git (`git rev-list --before`) по размеру фасадов | §2.1 |
| `gh run list` по `ci.yml`, 60 последних прогонов | §2.6 |
| `scripts/check_doc_links.py`, `scripts/check_id_references.py`, `tests/unit/test_docs_links.py` (Qt через `tools/qtstub`) | зелёные |

Что **не** запускалось: полный unit/GUI-набор (песочница 2 vCPU / 3 ГБ, системного `libGL.so.1` нет — Qt
поднимается только через `tools/qtstub`), покрытие по модулям (CI-логи недоступны с этого хоста),
Windows/macOS, реальный PACS, ONNX-инференс. «Модуль без тестов» в §2.7 — статический признак (нет
упоминания пути или публичного имени в `tests/`), а не измеренное покрытие.

---

## 1. Сверка внешнего аудита с кодом

| Утверждение аудита | Факт в `9984977` | Статус |
|---|---|---|
| ViewerWidget 10 553 строк / 563 метода | файл 10 553; класс — 9 640 строк, **515** методов, **232** поля `self.*`, 27 сигналов | ✓ (по сути) |
| «ViewerWidget +1 700 строк за 2 недели» | 9 640 (22.10) → 10 553 (09.11) = **+913** | ✗ |
| MainWindow 7 719 строк | ✓, и растёт **быстрее** ViewerWidget: 2 752 (01.09) → 6 165 (22.10) → 7 719 | ✓, недооценено |
| mypy не покрывает presentation/ui/constructor | ✓; при включении — 1 285 ошибок (§2.2) | ✓ |
| «UI читает DICOM, ходит в PACS, пишет PDF напрямую» | рёбер `presentation→infrastructure` **0** (#307); нет импортов `reportlab`/`httpx`/`pynetdicom` в UI; есть фасады `dicom_io`/`server_io`/`report_export`. Остаток: 2× `pydicom.dcmread` в `orthanc_study_dialog.py:2908,2927`, `openpyxl` в `constructor/importers` | ✗ в основном |
| Coverage не гейтится (`--cov-fail-under` нет) | `coverage report --fail-under=80` и `--include=domain/* --fail-under=88` (`ci.yml:1170-1171`) | ✗ |
| sha256 модели проверяется **после** распаковки | `verify_models_archive()` вызывается **до** `tarfile.open` + tar-slip-проверка (`runtime_setup.py`) | ✗ |
| Нет защиты от «pixel bomb» | лимит на исследование убран **сознательно** (`dicom_session.py:544-548`: длинные cine — норма); **лимита на один кадр нет** | ⚠ частично (§2.5) |
| `closeEvent` конструктора теряет данные | спрашивает Yes/No/Cancel при `_dirty` (`constructor_dialog.py:276`) | ✗ исправлено |
| Excel-импорт `pass # TODO` | TODO/FIXME в `src` нет | ✗ исправлено |
| 280 широких `except Exception` | 281, из них **41 молчаливый** (тело — `pass`/`continue`/`return const`) | ✓ + уточнение |
| 43 `setAccessibleName` | ✓ 43 на ~300 интерактивных контролов | ✓ |
| system/compat/integration вне обязательного CI | ✓, плюс `tests/exploratory` (hypothesis, fuzzing) | ✓ + уточнение |
| ~9 885 тестов по baseline | действующий `_BASELINE.total` = **10 338** | устарело |
| Теоретический пик памяти > 5 ГиБ | кэш кадров адаптивный: `min(prefs, 8% available RAM)` (`app_controller.py:257`) | не подтверждаю |
| ONNX только CPU, «сотни мс/кадр» | CPU-only ✓ (`onnx_engine.py:121`); латентность не измерял | ✓ / не проверено |

**Вывод по сверке:** из 16 проверяемых утверждений 6 устарели или неверны. Аудит местами пересказывает
октябрьский документ, а не текущий код. Ниже — только то, что подтверждено в `9984977`.

---

## 2. Слабые стороны (по убыванию стоимости для проекта)

Общий тезис: проект **очень хорошо защищён от регресса** (ratchet-гейты, baseline тестов, anti-skip,
test-signal), но часть гейтов измеряет не то, что на самом деле растёт, а часть контрактов существует
только формально. Все три главные слабости — следствие этого.

### 2.1 Гейты поощряют неправильную декомпозицию → фасады растут

| Класс | 01.09 | 01.10 | 22.10 | 09.11 | методов | полей `self.*` |
|---|---|---|---|---|---|---|
| ViewerWidget (файл) | 7 505 | 8 229 | 9 640 | **10 553** | 515 | 232 |
| MainWindow (файл) | 2 752 | 3 195 | 6 165 | **7 719** | 488 (469 приватных) | 110 |
| AppController | 3 333 | 3 870 | 4 460 | 4 548 | 167 | 88 |

- `scripts/check_function_length.py` ограничивает **функцию** 200 строками. Гейта на размер **класса/модуля**
  нет. Самый дешёвый способ пройти гейт — разрезать длинную функцию на приватные методы того же класса:
  гейт зелёный, класс растёт. Гейт стимулирует именно ту декомпозицию, которая не помогает.
- QH-3 вынес в `presentation/viewer/` **1 886 строк** (~15 % фасада); 4 из оставшихся контроллеров не
  вызываются из виджета (#466). Через `ViewerContract` экспонировано **229** приватных имён виджета.
- **Тесты прибиты к приватным полям фасадов:** `check_test_private_access.py` имеет scope только
  `tests/unit/test_*viewer*.py` (там 0). Вне scope — **2 172** обращения `window._…`/`main_window._…` в
  41 файле и 721 обращение `viewer._…`. Любой вынос из MainWindow ломает сотни тестов — поэтому его и не
  делают, и новое поведение продолжает оседать в фасаде.
- MainWindow по природе — **медиатор** (кластеры имён `sync_*` 18, `ensure_*` 16, `open_*` 16,
  `on_protocol_*` 13, `on_report_*`+`report_*` 18, `multiview_*` 9, `tab_*` 6), а не виджет. Его режут
  координаторами без виджетов, а не так, как ViewerWidget.

**Исправление:** ratchet размера классов/модулей и расширение scope private-access (#474), затем
срезы по владению состоянием: метрика — число полей `self.*`, а не строк.

### 2.2 Контракты UI ↔ application формальны: их никто не проверяет

- mypy strict проверяет `domain`/`imaging`/`application`/`infrastructure` (270 файлов, чисто), но не
  `presentation`/`ui`/`constructor` — 46 % кода. При включении:
  `ui` 31, `constructor` 25, `presentation` **1 229** ошибок в 103 из 146 файлов (**58 файлов уже чистые**).
  Структура presentation: `no-untyped-def` 368, `attr-defined` 294, `unused-ignore` **125**,
  `union-attr` 108, `arg-type` 84; по файлам — ViewerWidget 205, MainWindow 185.
- **123 из 294 `attr-defined` — `"UserPreferences" has no attribute …`.** Протокол
  `application/preferences_contract.py::UserPreferences` описывает **37** членов, конкретный
  `infrastructure/user_preferences.py::UserPreferences` — **85**. Presentation типизирован протоколом, а
  использует ещё 48 членов. Порт есть, но он ничего не обещает — mypy поймал бы это сразу.
- Фасады частично — переэкспорт адаптеров: `server_io.ServerSettings = _settings_adapter.ServerSettings`.
  Layer-ratchet считает **импорты**, а не **типы**, поэтому infrastructure-типы протекают через application
  незамеченными.
- 125 мёртвых `# type: ignore` в presentation не видит `warn_unused_ignores`, потому что mypy туда не смотрит.

**Исправление:** mypy через per-file baseline (число ошибок только уменьшается), протокол
`UserPreferences` до фактического использования, app-owned DTO вместо реэкспорта.

### 2.3 Композиция приложения скрыта в конструкторах

`main.py` → `MainWindow(user_preferences=…)` → `self._controller = controller or AppController()` →
`AppController.__init__` сам вызывает `load_user_preferences()`, `psutil.virtual_memory()`, создаёт
`StateManager`, `StudyMeasurementSessionStore`, `CalculatorInputStore`, `MeasurementPersistence`,
`FrameCache`. Шов для тестов (`controller=`) есть — это хорошо, но граф объектов собирается в двух
конструкторах, и Presenter-сборка отличается проверками профиля во время работы.

`ui/` и `constructor/` — не «третий и четвёртый UI-слой», а **несогласованное владение**: `ui→presentation`
6 импортов (запрещённое направление, в baseline), `constructor` → 15 infrastructure + 14 presentation,
решение по нему явно отложено (`layer_direction_allowlist.json`: «NOT DECIDED in #419»). i18n непоследователен:
presentation ходит через `application.localization` (128 импортов), `ui`/`constructor` — напрямую в
`infrastructure.i18n`.

**Исправление:** явный `build_app(profile) -> AppServices`; общие примитивы (`segment_labels`, `ui_metrics`,
`cine_phase_strip`) опустить в `ui/`; `constructor` заморозить в layer-ratchet **сейчас** (заморозка не
решает за владельца, она только останавливает рост).

### 2.4 Точность отображения измерений задаётся в трёх местах

`measurement_catalog` хранит `decimals` на измерение (`decimals_for(unit)`), но читает его только
`application/tool_status.py` (панель инструментов). Панель результатов (`measurement_results_formatter.py`,
**19** литералов `decimals=`, текстовая и HTML-ветки дублируют друг друга) и PDF (`report_builder.py`,
**14** литералов) задают точность сами. Сейчас значения совпадают (например, площадь ЛП — 2 знака везде),
но при изменении каталога экран, панель и PDF разойдутся молча. Для инструмента, где число — результат,
это клинический, а не косметический риск. Контрактного теста «одно измерение → одна строка везде» нет.

### 2.5 Декодирование: нет лимита на один кадр

Отказ от лимита на всё исследование обоснован (длинные cine нормальны, память ограничена кэшем и memmap).
Но `Rows × Columns × SamplesPerPixel × BitsAllocated` одного кадра из заголовка не проверяется
(`dicom_session.py:583,722,773` берут `ds.Rows`/`ds.Columns` как есть): заголовок 65 535 × 65 535 RGB — это
~12,9 ГБ на один кадр при декодировании J2K/JPEG. Источники — открытый пользователем файл, кэш PACS, Storage
SCP (он loopback-only, это снижает риск). Попутно: при `frame_count <= 1` `_open_impl` делает
`resolved.read_bytes()` всего файла и для encapsulated — второй полный `dcmread` из памяти.

### 2.6 Процесс: точный счётчик тестов — горячая точка слияний

- `verify_pytest_partition.py` сверяет инвентарь тестов на **точное равенство** с `_BASELINE`. За период с
  01.10 — **289** правок этого файла на **241** смёрженный PR (167 из них — агентные ветки `arena/*`).
- В файле **20** присваиваний `_BASELINE` (Python использует последнее; git при слиянии склеивает
  добавленные строки) и **132** строки комментариев «auto-refresh». Скрипт `--fix` знает об этом и правит
  последнее — то есть проблема признана и обойдена, а не решена.
- Из 60 последних прогонов `ci.yml`: 32 success, **19 failure**, 9 cancelled; провалы — в PR-ветках, в
  заметной части — `pytest counters gate`. Прогон занимает 23–57 минут: каждый «счётчик не сошёлся» стоит
  полчаса обратной связи.

Цель гейта (тест нельзя удалить молча) верная; реализация через глобальное равенство — нет. Достаточно
«не меньше, чем на merge-base, если удаление не задекларировано в PR».

### 2.7 Тесты: наборы вне CI и непокрытые модули

- Вне любого workflow: `tests/exploratory` (**hypothesis**-свойства формул — 9 `@given`, fuzzing ввода),
  `tests/compat` (`test_windows_paths.py` — 242 строки, **не гоняется на Windows**), `tests/system`,
  `tests/integration`.
- 19 модулей (~2,3k строк) не упоминаются в тестах ни путём, ни именем публичного класса/функции, в т.ч.
  `application/workers/dcm_export_worker.py` (экспорт DICOM), `domain/services/roi_validator.py`,
  `application/workers/orthanc_enrichment_worker.py`, `presentation/web_reference/web_reference_bridge.py`
  (480 строк). Общий порог покрытия 80 % такие дыры не ловит.
- 41 молчаливый широкий `except` (16 infrastructure, 16 presentation, 4 domain, 4 application) — ошибки,
  которые не оставляют следа даже в санитизированном логе.

### 2.8 Доступность и хвосты i18n

43 `setAccessibleName`, 1 `setAccessibleDescription`, 4 `setTabOrder` на ~180 кнопок и ~120 полей ввода;
иконочные `QToolButton` без текста экранным диктором не озвучиваются. ~39 пользовательских строк мимо `tr()`
(`properties_panel.py`: `"Label:"`, `"Area:"`, `"Chamber:"`…; `command_palette.py` выбирает язык тернарным
оператором вместо ключа). Паритет-тест RU/EN эти строки не видит, потому что их нет в словарях.

---

## 3. Что я сознательно не считаю приоритетом

- **GPU execution provider для ONNX.** EchoNet-Dynamic работает на входе 112×112; выигрыш не измерен, а
  цена — три бэкенда и три матрицы сборки. Сначала замер латентности, потом решение.
- **Coverage-гейт** — уже есть (80 % / domain 88 %); нужен не порог, а адресные тесты (§2.7).
- **DICOM SR, RBAC, at-rest** — это решение владельца о клиническом пути (#331), а не инженерный долг.
- **3D/4D** — вне ниши продукта.

---

## 4. План по шагам

| Фаза | Цель | Issues |
|---|---|---|
| 0. Быстрые победы | убрать трение и остановить рост | #473 счётчик тестов, #474 ratchet-гейты, #475 лимит кадра |
| 1. Страховочная сеть | контракты проверяются типами | #476 mypy-ratchet, #477 контракты UI↔application |
| 2. Декомпозиция | фасады худеют по владению состоянием | #478 MainWindow → ReportCoordinator, #479 ViewerWidget → M-mode/Doppler (после #466) |
| 3. Структура | одна точка сборки, ясное владение | #480 composition root, #481 ui/constructor |
| 4. Качество | клиническая согласованность и охват | #482 точность отображения, #483 тесты вне CI, #484 доступность |

Трекинг и зависимости — эпик #485 (метка `audit-2026-11`).

---

## 5. Воспроизведение

```bash
# размер фасадов во времени
for d in 2026-09-01 2026-10-22 2026-11-09; do
  c=$(git rev-list -1 --before="$d 23:59" --first-parent HEAD)
  git show $c:src/echo_personal_tool/presentation/main_window.py | wc -l
done

# mypy strict на UI-слоях (окружение — как в job lint из ci.yml)
mypy src/echo_personal_tool/presentation | grep '^src/echo_personal_tool/presentation/' | wc -l
mypy src/echo_personal_tool/presentation | grep -c 'UserPreferences" has no attribute'

# приватный доступ тестов к MainWindow вне scope ratchet
grep -rhoE "(window|win|mw|main_window)\._[a-z][a-z_]+" tests --include=*.py | wc -l

# присваивания _BASELINE и правки файла
grep -c '^_BASELINE' .github/scripts/verify_pytest_partition.py
git log --since=2026-10-01 --oneline -- .github/scripts/verify_pytest_partition.py | wc -l

# литералы точности мимо каталога
grep -c 'decimals=' src/echo_personal_tool/domain/services/measurement_results_formatter.py \
                    src/echo_personal_tool/domain/services/report_builder.py

# слои
python scripts/check_layer_directions.py
```
