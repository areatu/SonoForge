# Tests

> [English version](README.md)

Тесты SonoForge: юнит, интеграционные, приёмочные, регрессионные, миграционные,
безопасность, совместимость и бенчмарки.

## Структура

| Папка | Описание |
|-------|----------|
| `unit/` | Юнит-тесты domain, infrastructure, application, presentation; CI без потерь разделяет их по маркеру `gui` |
| `integration/` | Реальный DICOM и живой Orthanc (`ECHO_ORTHANC=1`) |
| `acceptance/` | Сквозные пользовательские сценарии с замоканными бэкендами; обязательная CI-джоба `test-acceptance` (Xvfb) с манифестом обязательных тестов |
| `regression/` | Снапшотные и golden-file регрессии (контуры, допплер, M-Mode) |
| `migration/` | Миграции данных, совместимость схем, резервные копии |
| `security/` | Фаззинг, анонимизация, TLS/таймауты, учётные данные — полностью замокано; обязательная CI-джоба `test-security` с манифестом обязательных тестов |
| `system/` | Black-box тесты установленного приложения (`ECHO_SYSTEM=1`) |
| `compat/` | Совместимость ОС/платформ (`ECHO_COMPAT=1`) |
| `exploratory/` | Property-based и фаззинг-исследования |
| `interactive/` | Ручная диагностика сегментации cine (по умолчанию исключены: `-m 'not interactive'` в `pyproject.toml`) |
| `bench/` | Производительность: декодирование, память, сеть, pipeline, playback, прокрутка, рендеринг (`ECHO_BENCH=1`) |
| `benchmark/` | pytest-benchmark эталоны ядерных операций |
| `fixtures/` | Тестовые данные и генераторы (см. ниже) |

В корне `tests/` также лежат сквозные модули: `test_smoke.py`,
`test_annotation_chain.py`, `test_dicom_tag_dictionary.py`,
`test_samsung_tick_calibration.py`, `test_upload_flow.py`,
`test_vendor_profiles*.py`, общий `conftest.py` и отладочный хелпер
`debug_doppler_tags.py`.

Обязательная Linux CI-проверка контролирует текущий инвентарь unit-тестов: 7 650
тестов без `interactive`, без потерь разделённые на 4 254 логических и 3 396 GUI
в 4 файловых GUI-шардах. GUI-тесты находятся в 172 файлах; изменение инвентаря требует явного пересмотра
baseline (`_BASELINE` в `.github/scripts/verify_pytest_partition.py`).

### Гейты обязательных тестов (security, acceptance)

`tests/security/` и `tests/acceptance/` выполняются на каждом PR как обязательные
джобы `test-security` и `test-acceptance`. Обе *невакуумные*: плагин метрик
записывает исход каждого выполненного теста, а
`.github/scripts/check_required_tests.py` валит джобу, если хотя бы одна запись
из `.github/required-tests/security.txt` / `acceptance.txt` не была собрана **и
пройдена**. Пропущенный, xfail, переименованный или удалённый обязательный тест,
пустая выборка или полностью пропущенный прогон — это провал, а не PASS. Пропуски
допускаются только для точных node id из `security-allowed-skips.txt` с указанием
причины (сейчас список пуст: у security-набора нет живых предусловий).

```bash
export PYTHONPATH="$PWD/.github/scripts${PYTHONPATH:+:$PYTHONPATH}"
PYTEST_CI_METRICS_FILE=/tmp/pytest-metrics-security.json \
python -m pytest tests/security/ -p pytest_ci_metrics --junitxml=/tmp/pytest-junit-security.xml
python .github/scripts/check_pytest_counts.py \
  --junit /tmp/pytest-junit-security.xml --metrics /tmp/pytest-metrics-security.json
python .github/scripts/check_required_tests.py \
  --metrics /tmp/pytest-metrics-security.json \
  --required .github/required-tests/security.txt \
  --allowed-skips .github/required-tests/security-allowed-skips.txt
```

## Запуск

```bash
# Весь набор (без interactive)
python -m pytest tests/ -x -q

# Только юнит-тесты
python -m pytest tests/unit/ -x -q

# Отдельные группы (переменные окружения включают соответствующие маркеры;
# security и acceptance переменных не требуют — они замоканы и идут на каждом PR)
ECHO_ORTHANC=1    python -m pytest tests/integration/ -v
python -m pytest tests/acceptance/ -v
python -m pytest tests/security/ -v
ECHO_SYSTEM=1     python -m pytest tests/system/ -v
ECHO_COMPAT=1     python -m pytest tests/compat/ -v
ECHO_BENCH=1      python -m pytest tests/bench/ -v

# Эталоны производительности
python -m pytest tests/benchmark/ --benchmark-json=results.json

# GUI-тесты (обязательная CI-проверка; в Linux используйте xvfb)
QT_QPA_PLATFORM=offscreen xvfb-run -a python -m pytest tests/unit/ -m "gui and not interactive"
```

### Параллельный Linux-прогон как в CI

После `uv sync --locked --extra dev` (инструментальная цепочка CI; `pip install -e ".[dev]"`
тоже работает, но не фиксирует версии) полный unit-набор можно локально воспроизвести одним
запуском логики и четырьмя GUI-шардами. Они сохраняют coverage в отдельных файлах;
маркеры `interactive` остаются исключены, файлы GUI выполняются под xvfb. Шардирование
ограничивает накопление Qt-виджетов в одном процессе (неосвобождаемые MainWindow
выращивают воркеры до OOM-киллера); каждый шард — непересекающаяся четверть
отсортированного списка `tests/unit/test_*.py`:

```bash
export PYTHONPATH="$PWD/.github/scripts${PYTHONPATH:+:$PYTHONPATH}"
export QT_QPA_PLATFORM=offscreen PYTHONFAULTHANDLER=1 PYTHONUNBUFFERED=1

PYTEST_CURRENT_NODE_FILE=/tmp/pytest-last-node \
PYTEST_CI_METRICS_FILE=/tmp/pytest-metrics-logic.json \
COVERAGE_FILE=.coverage.logic \
python -m pytest tests/unit/ -n auto --dist loadfile --max-worker-restart=2 \
  -p pytest_current_node -p pytest_ci_metrics -m "not gui and not interactive" \
  --junitxml=/tmp/pytest-junit-logic.xml \
  --cov=src/echo_personal_tool --cov-report= --durations=25

python .github/scripts/check_pytest_counts.py \
  --junit /tmp/pytest-junit-logic.xml --metrics /tmp/pytest-metrics-logic.json

for shard in 0 1 2 3; do
  mapfile -t unit_files < <(git ls-files 'tests/unit/test_*.py' | sort)
  shard_files=()
  for i in "${!unit_files[@]}"; do
    if [ "$((i % 4))" -eq "$shard" ]; then shard_files+=("${unit_files[$i]}"); fi
  done
  PYTEST_CURRENT_NODE_FILE=/tmp/pytest-last-node \
  PYTEST_CI_METRICS_FILE=/tmp/pytest-metrics-gui-$shard.json \
  COVERAGE_FILE=.coverage.gui$shard \
  xvfb-run -a python -m pytest "${shard_files[@]}" -n 4 --dist loadfile --max-worker-restart=2 \
    -p pytest_current_node -p pytest_ci_metrics -m "gui and not interactive" \
    --junitxml=/tmp/pytest-junit-gui-$shard.xml \
    --cov=src/echo_personal_tool --cov-report= --durations=25
  python .github/scripts/check_pytest_counts.py \
    --junit /tmp/pytest-junit-gui-$shard.xml --metrics /tmp/pytest-metrics-gui-$shard.json
done

python .github/scripts/verify_pytest_partition.py \
  --logic /tmp/pytest-metrics-logic.json \
  --gui /tmp/pytest-metrics-gui-0.json /tmp/pytest-metrics-gui-1.json \
        /tmp/pytest-metrics-gui-2.json /tmp/pytest-metrics-gui-3.json
coverage combine
coverage report
```

Обёртка для проблемных окружений (кириллические пути, неактивируемый venv):
[`scripts/run_tests.sh`](../scripts/run_tests.sh) — сам выставляет
`PYTHONPATH` и `QT_QPA_PLATFORM=offscreen`.

## Фикстуры (`fixtures/`)

| Путь | Описание |
|------|----------|
| `generate_synthetic_dicom.py` | Генерация синтетических DICOM |
| `generate_synthetic_media.py` | Генерация MP4/JPEG тестовых данных |
| `orthanc/` | Моки ответов Orthanc API (+ пример `sample.dcm`) |
| `reference_manifest.json` | Тестовый манифест справочника |
| `ste_phantom.py` | Генератор синтетического STE-фантома |
| `for_pero/` | Компактные фикстуры из реальных клипов — см. [`for_pero/README.md`](fixtures/for_pero/README.md); контракт к ним проверяет `unit/test_ste_real_clips.py` |

## Юнит-тесты (`unit/`)

Покрывают:
- Модели данных (Contour, Doppler, Speckle, MMode)
- Расчёты (Simpson, Bernoulli, Teichholz, BSA, RWT, FAC)
- Инфраструктуру (DICOM, Orthanc, ONNX, DIMSE)
- Презентационный слой (Viewer, M-Mode, Doppler, STE)
- Безопасность (валидация, PHI-фильтрация, TLS)
