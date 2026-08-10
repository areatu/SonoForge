# CI debug notes — флаки-Linux Qt SIGSEGV (2026-08-10)

Заметки для продолжения на другой машине. `git pull` — и всё здесь доступно.

## Контекст
Цель: зелёный CI на main.
Workflows: CI = 316414439, Coverage = 318411854.
PR #39 закрыт через API, вердикт опубликован.

## Коммиты на main (кодовые фиксы)
- `bb66a93` style(lint): `ruff check --fix` + `ruff format` (14 ошибок, 28 файлов)
- `2d77cb2` test(ci): autouse `_drain_global_thread_pool` в `tests/unit/conftest.py`
  (`QThreadPool.globalInstance().waitForDone(5000)` после каждого теста)
- `4721b46` fix(ci): регрессы doppler/cache
  - `tests/unit/test_doppler_axis.py::test_poc_default` — ожидает `time_span_ms == 0.0`
    (Phase A убрал молчаливый дефолт 1000 мс)
  - `ultrasound_region_physics.py` — отказ от SPATIAL_2D до unit-веток
  - `dicom_reader.py::read_pixels` — возвращает `_pixel_cache.get(...)` (owned copy, identity-тест)

## SIGSEGV на Linux (флаки, не детерминирован)
Дампа faulthandler (включается pytest'ом):
- Главный поток: `pytestqt/plugin.py:220 _process_events` (qWait внутри qtbot-теста)
- Побочный поток: `threading.py` wait → матчится `threading.Timer.run:1399 finished.wait`
  (проверено сурсами CPython 3.11.15)
- `ECHO_FREEZE_DIAG` в CI НЕ выставлен → Timer из `main.py` (_mem_dump) исключён
- pytest-timeout (`timeout=60, timeout_method="thread"`) заводит по Timer на тест —
  вероятнее всего именно он в дампе; daemon, сам по себе не крашит

Прогоны: success — coverage `30863934784` (eb23639), `31367122417` (9689110);
failure — ci `31355077694` (e91deb0), `31374006784` (2d77cb2, ubuntu segfault).
Один и тот же код проходит и падает → гонка, не детерминированный тест.

## Локальный прогон (Windows, 2026-08-10)
`uv run pytest tests/unit -v --tb=short --no-header --cov=src/echo_personal_tool --cov-report=term-missing`
- Прошёл бывшую зону аборта (~36–38%, `test_main_window_extended`) без краша
- Закончился **pytest-timeout 60с** (thread-метод) на
  `tests/unit/test_main_window_layout.py:107 test_activity_bar_off_restores_tool_panel_with_horizontal_gallery`
  → `_make_window` → `MainWindow._rebuild_layout` → `main_window.py:641 _content_layout.addWidget(left)`
- Общее время руна: ~1263 с
- Флаки `F` локально в `tests/unit/test_linear_caliper_click_click.py` (~34%, не CI-блокер)

## Гипотезы
1. Leftover QThread/QTimer/сигнал трогает удалённый QObject во время qWait;
   дренаж QThreadPool не помог → либо не QThread, либо гонка шире.
2. Зона крашей/зависаний густует в тяжёлых gui-тестах main window
   (`test_main_window_extended` / `test_main_window_layout`, ~36–40%).
3. Локальный хэнг (60с) в `_rebuild_layout/addWidget` — конструирование MainWindow
   может буксовывать под coverage — возможно, та же природа, что крэш в CI.

## Следующие шаги
1. Добавить `-v` в Linux-команду pytest ci.yml, чтобы назвать крашащий тест
   (или гонять локально с `-v` до воспроизведения).
2. Альтернатива: pytest-xdist `--dist=loadscope -n 2..4` — крэш убьёт только один
   модуль-процесс, остальные досчитают (и диагностика).
3. Разобрать хэнг `MainWindow._rebuild_layout` (main_window_layout) — вероятный источник.
4. Когда тест найден: чинить гонку / изолировать / отметить flaky с retry.
5. Перепрогнать CI + Coverage до зелёного.

## Команды воспроизведения
- Локально (Windows): `uv run pytest tests/unit -v --tb=short --no-header --cov=src/echo_personal_tool --cov-report=term-missing`
- CI Linux: `xvfb-run -a pytest tests/unit/ -q --tb=line --no-header --cov=src/echo_personal_tool --cov-report=xml`

## Артефакты (НЕ коммитить)
- `C:\Temp\opencode\*.log` — логи джоб: `ubuntu_prev.log` (дампа), `ci_runs_*.json`
- В корне репо untracked-мусор: `_tmp_*.py`, `coverage.xml`, `traceback.txt` и т.п. — не коммитить